"""Apply manual-review tract overrides to geocoded grantees.

Per methodology v0.2.0 §Q5 + the design brief's "Wilmington corner-store
manual review" section: the ETL runs in two passes. First pass geocodes
every grantee and flags Wilmington corner-store / specialty-grocer
disagreements (see etl.transforms.geocode). Second pass — this module —
reads `etl/manual-reviews.yaml`, looks up each `(grantee, cycle)` against
the geocoded set, and overrides the tract_geoid with the human-confirmed
assignment.

This is the *only* place tract_geoid can be set by something other than
the Census Geocoder. The audit trail is preserved because:

  1. The yaml file is version-controlled and reviewer-attributed
  2. The override flips `geocoding_confidence` to "manual"
  3. The override flips `wilmington_manual_reviewed` to True
  4. The original Census + Nominatim matched_address fields stay intact
     for forensic comparison

Schema of manual-reviews.yaml (validated by load_manual_reviews):

    reviews:
      - grantee: "Acme Corner Store"
        cycle: 3
        storefront_address: "123 N Market St, Wilmington, DE 19801"
        confirmed_tract_geoid: "10003001100"
        reviewed_by: "Mark Sanders"
        reviewed_at: "2026-05-15"
        notes: "..."

Missing optional fields are tolerated (e.g. `notes`, `storefront_address`)
but `grantee`, `cycle`, `confirmed_tract_geoid`, and `reviewed_by` are
required. `confirmed_tract_geoid` must be an 11-character string.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Iterable, Optional

import yaml

from etl.transforms.geocode import CONFIDENCE_MANUAL, GeocodedGrantee


TRACT_GEOID_PATTERN = re.compile(r"^\d{11}$")


class ManualReviewError(Exception):
    """Raised when manual-reviews.yaml is malformed or inconsistent."""


@dataclasses.dataclass
class ManualReview:
    grantee: str
    cycle: int
    confirmed_tract_geoid: str
    reviewed_by: str
    reviewed_at: Optional[str] = None
    storefront_address: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Load + validate
# ---------------------------------------------------------------------------


def load_manual_reviews(path: Path) -> list[ManualReview]:
    """Parse and validate `path`. Returns the list (possibly empty)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    if raw is None:
        return []
    if not isinstance(raw, dict) or "reviews" not in raw:
        raise ManualReviewError(
            "manual-reviews.yaml must have a top-level 'reviews:' list"
        )
    reviews_raw = raw["reviews"] or []
    if not isinstance(reviews_raw, list):
        raise ManualReviewError("'reviews' must be a YAML list")

    out: list[ManualReview] = []
    seen: set[tuple[str, int]] = set()
    for i, entry in enumerate(reviews_raw):
        if not isinstance(entry, dict):
            raise ManualReviewError(f"reviews[{i}] is not a mapping: {entry!r}")
        review = _coerce_entry(i, entry)
        key = (review.grantee, review.cycle)
        if key in seen:
            raise ManualReviewError(
                f"duplicate review for grantee={review.grantee!r}, cycle={review.cycle}"
            )
        seen.add(key)
        out.append(review)
    return out


def _coerce_entry(i: int, entry: dict) -> ManualReview:
    for required in ("grantee", "cycle", "confirmed_tract_geoid", "reviewed_by"):
        if required not in entry:
            raise ManualReviewError(
                f"reviews[{i}] missing required field {required!r}"
            )

    grantee = entry["grantee"]
    if not isinstance(grantee, str) or not grantee.strip():
        raise ManualReviewError(f"reviews[{i}].grantee must be a non-empty string")

    cycle = entry["cycle"]
    if not isinstance(cycle, int):
        raise ManualReviewError(f"reviews[{i}].cycle must be an integer")

    geoid = entry["confirmed_tract_geoid"]
    if not isinstance(geoid, str) or not TRACT_GEOID_PATTERN.match(geoid):
        raise ManualReviewError(
            f"reviews[{i}].confirmed_tract_geoid must be 11 digits; got {geoid!r}"
        )

    reviewed_by = entry["reviewed_by"]
    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise ManualReviewError(f"reviews[{i}].reviewed_by must be a non-empty string")

    return ManualReview(
        grantee=grantee,
        cycle=cycle,
        confirmed_tract_geoid=geoid,
        reviewed_by=reviewed_by,
        reviewed_at=entry.get("reviewed_at"),
        storefront_address=entry.get("storefront_address"),
        notes=entry.get("notes"),
    )


# ---------------------------------------------------------------------------
# Apply the merge
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ApplyResult:
    """Outcome of applying manual reviews to a geocoded set."""

    records: list[GeocodedGrantee]
    applied_reviews: list[ManualReview]
    unmatched_reviews: list[ManualReview]


def apply_manual_reviews(
    geocoded: Iterable[GeocodedGrantee],
    reviews: Iterable[ManualReview],
) -> ApplyResult:
    """Override tract_geoid for any (grantee, cycle) in `reviews`.

    Returns the modified records + the reviews that were actually applied
    + any reviews that didn't match a grantee (surfaced for triage; common
    cause is a typo in the yaml file or a renamed grantee).
    """
    records = list(geocoded)
    review_index: dict[tuple[str, int], ManualReview] = {
        (r.grantee, r.cycle): r for r in reviews
    }
    applied: list[ManualReview] = []
    matched_keys: set[tuple[str, int]] = set()

    for i, rec in enumerate(records):
        key = (rec.grantee, rec.cycle)
        review = review_index.get(key)
        if review is None:
            continue
        # Build the overridden record. We keep most fields; the override
        # specifically swaps tract_geoid + confidence + wilmington flag.
        new_rec = dataclasses.replace(
            rec,
            tract_geoid=review.confirmed_tract_geoid,
            geocoding_confidence=CONFIDENCE_MANUAL,
            wilmington_manual_reviewed=True,
        )
        records[i] = new_rec
        applied.append(review)
        matched_keys.add(key)

    unmatched = [
        r
        for (key, r) in review_index.items()
        if key not in matched_keys
    ]
    return ApplyResult(
        records=records,
        applied_reviews=applied,
        unmatched_reviews=unmatched,
    )
