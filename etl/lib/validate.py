"""Datapackage and freshness validation.

S+1 contents:
  - assert_fresh:    verify a manifest's per-source last_fetched is within N days
  - validate_geojson: assert payload parses as GeoJSON with a FeatureCollection
  - validate_csv:    assert payload parses with the csv module (encoding probe)

S+3 adds:
  - validate_datapackage: Frictionless datapackage validation (full schema check)
"""

from __future__ import annotations

import csv
import datetime
import io
import json
from pathlib import Path
from typing import Iterable

from .manifest import Manifest


class ValidationError(Exception):
    """Raised when an ETL output does not satisfy its contract."""


def assert_fresh(manifest: Manifest, max_age_days: int) -> None:
    """Fail if any source in the manifest is older than `max_age_days`."""
    now = datetime.datetime.now(datetime.timezone.utc)
    stale: list[tuple[str, str, int]] = []
    for name, entry in manifest.sources.items():
        fetched = _parse_iso8601_z(entry.last_fetched)
        age_days = (now - fetched).days
        if age_days > max_age_days:
            stale.append((name, entry.last_fetched, age_days))
    if stale:
        report = "; ".join(
            f"{name} fetched {ts} ({age}d old)" for name, ts, age in stale
        )
        raise ValidationError(
            f"{len(stale)} source(s) exceed max_age_days={max_age_days}: {report}"
        )


def validate_geojson(payload: bytes, *, require_features: bool = True) -> dict:
    """Parse `payload` as a GeoJSON FeatureCollection. Return the parsed dict."""
    try:
        doc = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"payload is not valid UTF-8 JSON: {exc}") from exc

    if not isinstance(doc, dict):
        raise ValidationError("GeoJSON root must be a JSON object")
    if doc.get("type") != "FeatureCollection":
        raise ValidationError(
            f"expected type=FeatureCollection, got type={doc.get('type')!r}"
        )
    features = doc.get("features")
    if not isinstance(features, list):
        raise ValidationError("GeoJSON.features must be a list")
    if require_features and not features:
        raise ValidationError("GeoJSON.features is empty")
    return doc


def validate_census_json(payload: bytes) -> list:
    """Assert `payload` is a well-formed Census API response and return it.

    Census returns a JSON array-of-arrays: ``[[header...], [row...], ...]``.
    When the unauthenticated per-IP quota is exhausted (or a WAF challenges the
    request) the API returns an **HTML rate-limit/captcha page at HTTP 200** —
    not a 4xx. Writing that HTML to disk raw is the silent-zero trap that hid a
    month-long production regression: the file is present and non-empty, so
    ``--strict`` passes, but the downstream JSON load fails and every
    ACS-derived value zeroes. This guard runs at the source boundary so the
    bad payload raises here (surfacing as a per-source FAILED note in the
    orchestrator) instead of being persisted and silently zeroing the build.

    Raises ValidationError on: non-JSON (HTML), non-list root, empty list, a
    non-list header row, or a header with zero data rows.
    """
    try:
        doc = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        preview = payload[:120].decode("utf-8", "replace").replace("\n", " ").strip()
        raise ValidationError(
            "Census payload is not valid JSON (likely an HTML rate-limit/WAF "
            f"page returned at HTTP 200): {exc}; first bytes: {preview!r}"
        ) from exc

    if not isinstance(doc, list) or not doc:
        raise ValidationError(
            f"Census payload must be a non-empty JSON list; got "
            f"{type(doc).__name__} of length {len(doc) if hasattr(doc, '__len__') else '?'}"
        )
    if not isinstance(doc[0], list):
        raise ValidationError(
            f"Census payload first row (header) must be a list; got {type(doc[0]).__name__}"
        )
    if len(doc) < 2:
        raise ValidationError(
            "Census payload has a header row but zero data rows"
        )
    return doc


def validate_csv(payload: bytes, *, required_columns: Iterable[str] = ()) -> int:
    """Parse `payload` as CSV. Return the row count (excluding header).

    Raises ValidationError if the payload isn't decodable, the header is
    missing, or any required column is absent.
    """
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Fall back; MMG and some state CSVs are latin-1.
        try:
            text = payload.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"CSV not decodable as utf-8 or latin-1: {exc}") from exc

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValidationError("CSV is empty (no header row)") from exc

    missing = [c for c in required_columns if c not in header]
    if missing:
        raise ValidationError(
            f"CSV missing required columns: {missing}; header was: {header}"
        )

    return sum(1 for _ in reader)


def _parse_iso8601_z(s: str) -> datetime.datetime:
    """Parse an ISO8601 timestamp with optional 'Z' suffix as UTC."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt
