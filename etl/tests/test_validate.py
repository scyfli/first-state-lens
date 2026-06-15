"""Smoke tests for etl.lib.validate."""

from __future__ import annotations

import datetime

import pytest

from etl.lib.manifest import Manifest, SourceEntry
from etl.lib.validate import (
    ValidationError,
    assert_fresh,
    validate_census_json,
    validate_csv,
    validate_geojson,
)


# ---------------------------------------------------------------------------
# validate_census_json — the source-boundary guard against HTML-at-200 that
# silently zeroed production for a month (session-26).
# ---------------------------------------------------------------------------


def test_validate_census_json_happy_path() -> None:
    payload = b'[["NAME","B19113_001E","state"],["Delaware","102219","10"]]'
    doc = validate_census_json(payload)
    assert doc[0][0] == "NAME"
    assert doc[1][0] == "Delaware"


def test_validate_census_json_rejects_html_rate_limit_page() -> None:
    # The exact failure mode: Census returns an HTML WAF/captcha page at 200.
    html = b"<!DOCTYPE html><html lang=en><head><script>captcha</script></head></html>"
    with pytest.raises(ValidationError, match="not valid JSON"):
        validate_census_json(html)


def test_validate_census_json_rejects_empty_list() -> None:
    with pytest.raises(ValidationError, match="non-empty JSON list"):
        validate_census_json(b"[]")


def test_validate_census_json_rejects_header_only() -> None:
    with pytest.raises(ValidationError, match="zero data rows"):
        validate_census_json(b'[["NAME","B19113_001E"]]')


def test_validate_census_json_rejects_non_list_root() -> None:
    with pytest.raises(ValidationError, match="non-empty JSON list"):
        validate_census_json(b'{"error": "bad request"}')


def test_validate_geojson_happy_path(fixture_sd2_geojson: bytes) -> None:
    doc = validate_geojson(fixture_sd2_geojson)
    assert doc["type"] == "FeatureCollection"
    assert len(doc["features"]) == 1


def test_validate_geojson_rejects_non_json() -> None:
    with pytest.raises(ValidationError, match="not valid UTF-8 JSON"):
        validate_geojson(b"\xff\xfenot json")


def test_validate_geojson_rejects_wrong_type() -> None:
    with pytest.raises(ValidationError, match="FeatureCollection"):
        validate_geojson(b'{"type": "Feature"}')


def test_validate_geojson_rejects_empty_features() -> None:
    payload = b'{"type": "FeatureCollection", "features": []}'
    with pytest.raises(ValidationError, match="features is empty"):
        validate_geojson(payload, require_features=True)
    # But should pass when require_features=False
    doc = validate_geojson(payload, require_features=False)
    assert doc["features"] == []


def test_validate_csv_happy_path(fixture_mmg_csv: bytes) -> None:
    row_count = validate_csv(
        fixture_mmg_csv, required_columns=("FIPS", "Year")
    )
    assert row_count == 3


def test_validate_csv_missing_columns(fixture_mmg_csv: bytes) -> None:
    with pytest.raises(ValidationError, match="missing required columns"):
        validate_csv(fixture_mmg_csv, required_columns=("FIPS", "NonexistentCol"))


def test_validate_csv_empty_payload() -> None:
    with pytest.raises(ValidationError, match="empty"):
        validate_csv(b"")


def test_assert_fresh_passes_on_recent_source() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    recent_iso = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    m = Manifest(etl_version="0.1.0")
    m.sources["recent"] = SourceEntry(
        url="https://example.com/recent.csv",
        last_fetched=recent_iso,
        http_status=200,
        sha256="0" * 64,
        raw_path="etl/raw/recent.csv",
        size_bytes=10,
        warnings=[],
    )
    # Should not raise.
    assert_fresh(m, max_age_days=30)


def test_assert_fresh_fails_on_stale_source() -> None:
    old_iso = "2020-01-01T00:00:00Z"
    m = Manifest(etl_version="0.1.0")
    m.sources["stale"] = SourceEntry(
        url="https://example.com/stale.csv",
        last_fetched=old_iso,
        http_status=200,
        sha256="0" * 64,
        raw_path="etl/raw/stale.csv",
        size_bytes=10,
        warnings=[],
    )
    with pytest.raises(ValidationError, match="exceed max_age_days"):
        assert_fresh(m, max_age_days=30)
