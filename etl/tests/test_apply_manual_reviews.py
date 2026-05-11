"""Smoke tests for etl.transforms.apply_manual_reviews."""

from __future__ import annotations

from pathlib import Path

import pytest

from etl.transforms.apply_manual_reviews import (
    ManualReview,
    ManualReviewError,
    apply_manual_reviews,
    load_manual_reviews,
)
from etl.transforms.geocode import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MANUAL,
    CONFIDENCE_MEDIUM,
    GeocodedGrantee,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_grantee(
    grantee: str, cycle: int, *, tract_geoid: str | None = "10003001100",
    confidence: str = CONFIDENCE_HIGH,
) -> GeocodedGrantee:
    return GeocodedGrantee(
        cycle=cycle,
        grantee=grantee,
        amount_usd=100000.0,
        category="corner-store",
        storefront_address="123 N Market St, Wilmington, DE 19801",
        zip_code="19801",
        awarded_date=None,
        lat=39.7445,
        lon=-75.5455,
        tract_geoid=tract_geoid,
        county_fips="003",
        state_fips="10",
        geocoding_confidence=confidence,
        wilmington_manual_reviewed=False,
        census_matched_address="123 N MARKET ST, WILMINGTON, DE 19801",
        nominatim_matched_address=None,
        distance_disagreement_m=None,
    )


# ---------------------------------------------------------------------------
# load_manual_reviews — schema validation
# ---------------------------------------------------------------------------


def test_load_empty_reviews(tmp_path: Path) -> None:
    f = tmp_path / "reviews.yaml"
    f.write_text("reviews: []\n")
    assert load_manual_reviews(f) == []


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_manual_reviews(tmp_path / "does-not-exist.yaml") == []


def test_load_valid_review(tmp_path: Path) -> None:
    f = tmp_path / "reviews.yaml"
    f.write_text(
        """\
reviews:
  - grantee: "Acme Corner Store"
    cycle: 3
    storefront_address: "123 N Market St, Wilmington, DE 19801"
    confirmed_tract_geoid: "10003001100"
    reviewed_by: "Mark Sanders"
    reviewed_at: "2026-05-15"
    notes: "Census returned wrong tract; manual confirms."
"""
    )
    out = load_manual_reviews(f)
    assert len(out) == 1
    assert out[0].grantee == "Acme Corner Store"
    assert out[0].cycle == 3
    assert out[0].confirmed_tract_geoid == "10003001100"
    assert out[0].reviewed_by == "Mark Sanders"


def test_load_rejects_missing_required(tmp_path: Path) -> None:
    f = tmp_path / "reviews.yaml"
    f.write_text(
        """\
reviews:
  - grantee: "Acme"
    cycle: 3
    # missing confirmed_tract_geoid and reviewed_by
"""
    )
    with pytest.raises(ManualReviewError, match="missing required"):
        load_manual_reviews(f)


def test_load_rejects_bad_geoid(tmp_path: Path) -> None:
    f = tmp_path / "reviews.yaml"
    f.write_text(
        """\
reviews:
  - grantee: "Acme"
    cycle: 3
    confirmed_tract_geoid: "TOO_SHORT"
    reviewed_by: "Mark Sanders"
"""
    )
    with pytest.raises(ManualReviewError, match="11 digits"):
        load_manual_reviews(f)


def test_load_rejects_duplicate(tmp_path: Path) -> None:
    f = tmp_path / "reviews.yaml"
    f.write_text(
        """\
reviews:
  - grantee: "Acme"
    cycle: 3
    confirmed_tract_geoid: "10003001100"
    reviewed_by: "Mark Sanders"
  - grantee: "Acme"
    cycle: 3
    confirmed_tract_geoid: "10003001200"
    reviewed_by: "Mark Sanders"
"""
    )
    with pytest.raises(ManualReviewError, match="duplicate"):
        load_manual_reviews(f)


def test_load_rejects_top_level_shape(tmp_path: Path) -> None:
    f = tmp_path / "reviews.yaml"
    f.write_text("not_a_reviews_key: 42\n")
    with pytest.raises(ManualReviewError, match="top-level"):
        load_manual_reviews(f)


# ---------------------------------------------------------------------------
# apply_manual_reviews — override behaviour
# ---------------------------------------------------------------------------


def test_apply_overrides_tract_and_flips_confidence_and_wilmington_flag() -> None:
    grantees = [
        _make_grantee(
            "Acme", 3,
            tract_geoid="10003001200",  # wrong tract per manual review
            confidence=CONFIDENCE_MEDIUM,
        ),
    ]
    reviews = [
        ManualReview(
            grantee="Acme",
            cycle=3,
            confirmed_tract_geoid="10003001100",
            reviewed_by="Mark Sanders",
        )
    ]
    result = apply_manual_reviews(grantees, reviews)
    assert len(result.records) == 1
    rec = result.records[0]
    assert rec.tract_geoid == "10003001100"
    assert rec.geocoding_confidence == CONFIDENCE_MANUAL
    assert rec.wilmington_manual_reviewed is True
    # Original Census matched_address is preserved.
    assert rec.census_matched_address == "123 N MARKET ST, WILMINGTON, DE 19801"
    assert len(result.applied_reviews) == 1
    assert result.unmatched_reviews == []


def test_apply_passes_through_unreviewed_records() -> None:
    grantees = [
        _make_grantee("Acme", 3),
        _make_grantee("Other", 2),
    ]
    reviews = [
        ManualReview(
            grantee="Acme",
            cycle=3,
            confirmed_tract_geoid="10003999900",
            reviewed_by="Mark Sanders",
        )
    ]
    result = apply_manual_reviews(grantees, reviews)
    assert result.records[0].grantee == "Acme"
    assert result.records[0].tract_geoid == "10003999900"  # overridden
    assert result.records[1].grantee == "Other"
    assert result.records[1].tract_geoid == "10003001100"  # untouched


def test_apply_surfaces_unmatched_reviews() -> None:
    """A review for a grantee not in the input set comes back as unmatched."""
    grantees = [_make_grantee("Acme", 3)]
    reviews = [
        ManualReview(
            grantee="Misspelled Name",
            cycle=3,
            confirmed_tract_geoid="10003001100",
            reviewed_by="Mark Sanders",
        )
    ]
    result = apply_manual_reviews(grantees, reviews)
    assert len(result.unmatched_reviews) == 1
    assert result.unmatched_reviews[0].grantee == "Misspelled Name"
    assert result.applied_reviews == []
    # The Acme record is untouched.
    assert result.records[0].tract_geoid == "10003001100"


def test_apply_matches_by_cycle_too() -> None:
    """Same grantee name in different cycles is distinct."""
    grantees = [
        _make_grantee("Acme", 2),
        _make_grantee("Acme", 3),
    ]
    reviews = [
        ManualReview(
            grantee="Acme",
            cycle=3,
            confirmed_tract_geoid="10003999900",
            reviewed_by="Mark Sanders",
        )
    ]
    result = apply_manual_reviews(grantees, reviews)
    # Cycle-2 record untouched.
    assert result.records[0].cycle == 2
    assert result.records[0].tract_geoid == "10003001100"
    # Cycle-3 record overridden.
    assert result.records[1].cycle == 3
    assert result.records[1].tract_geoid == "10003999900"
