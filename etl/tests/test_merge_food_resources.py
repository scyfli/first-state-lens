"""Tests for etl.transforms.merge_food_resources."""

from __future__ import annotations

from etl.transforms.merge_food_resources import (
    FoodResource,
    merge_food_resources,
)


def _resource(
    source: str, name: str, lat: float, lon: float,
    category: str = "supermarket", address: str | None = None,
    external_id: str | None = None,
) -> FoodResource:
    return FoodResource(
        source=source, name=name, lat=lat, lon=lon,
        category=category, address=address, external_id=external_id,
    )


# ---------------------------------------------------------------------------
# Basic merge rules
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_list():
    assert merge_food_resources([]) == []


def test_single_resource_passes_through():
    r = _resource("usda-snap", "Acme Market", 39.7, -75.5)
    out = merge_food_resources([r])
    assert len(out) == 1
    assert out[0].name == "Acme Market"
    assert out[0].sources == ["usda-snap"]
    assert out[0].categories == ["supermarket"]
    assert out[0].contributor_count == 1


def test_co_located_same_name_merges():
    a = _resource("usda-snap", "Acme Market", 39.7, -75.5, address="123 Main")
    b = _resource("dgi-grantees", "Acme Market Inc", 39.7, -75.5,
                  category="corner-store", address="123 Main St")
    out = merge_food_resources([a, b])
    assert len(out) == 1
    merged = out[0]
    assert "usda-snap" in merged.sources
    assert "dgi-grantees" in merged.sources
    assert merged.contributor_count == 2
    assert set(merged.categories) == {"supermarket", "corner-store"}
    # Longer name preferred.
    assert merged.name == "Acme Market Inc"
    # Longer address preferred.
    assert merged.address == "123 Main St"


def test_different_name_at_same_location_stays_separate():
    a = _resource("usda-snap", "Acme Market", 39.7, -75.5)
    b = _resource("usda-snap", "Wawa", 39.7, -75.5)
    out = merge_food_resources([a, b])
    # Different names = different businesses in the same building, etc.
    assert len(out) == 2


def test_same_name_far_apart_stays_separate():
    a = _resource("usda-snap", "Acme Market", 39.7, -75.5)
    # ~5km away
    b = _resource("usda-snap", "Acme Market", 39.745, -75.5)
    out = merge_food_resources([a, b])
    assert len(out) == 2


def test_just_over_threshold_stays_separate():
    a = _resource("usda-snap", "Acme Market", 39.7, -75.5)
    # ~50m east — beyond the 30m default
    b = _resource("dgi-grantees", "Acme Market", 39.7, -75.4994)
    out = merge_food_resources([a, b], dedupe_distance_m=30.0)
    assert len(out) == 2


def test_just_under_threshold_merges():
    a = _resource("usda-snap", "Acme Market", 39.7, -75.5)
    # ~25m east (0.00029 deg lon ~ 24m at this latitude) — under 30m default
    b = _resource("dgi-grantees", "Acme Market", 39.7, -75.49971)
    out = merge_food_resources([a, b], dedupe_distance_m=30.0)
    assert len(out) == 1


# ---------------------------------------------------------------------------
# Noise-token + business-suffix tolerance
# ---------------------------------------------------------------------------


def test_business_suffix_tolerance():
    a = _resource("usda-snap", "Bright Star Foods", 39.7, -75.5)
    b = _resource("dgi-grantees", "Bright Star Foods LLC", 39.7, -75.5)
    out = merge_food_resources([a, b])
    assert len(out) == 1


def test_jaccard_threshold_blocks_weak_matches():
    a = _resource("usda-snap", "Mary's Corner Bodega", 39.7, -75.5)
    b = _resource("dgi-grantees", "Joe's Grocery", 39.7, -75.5)
    # Different names + no shared meaningful tokens.
    out = merge_food_resources([a, b])
    assert len(out) == 2


# ---------------------------------------------------------------------------
# Provenance preservation
# ---------------------------------------------------------------------------


def test_external_ids_accumulate_on_merge():
    a = _resource("usda-snap", "Acme Market", 39.7, -75.5, external_id="SNAP-123")
    b = _resource("dgi-grantees", "Acme Market", 39.7, -75.5, external_id="DGI-c3-Acme")
    out = merge_food_resources([a, b])
    assert len(out) == 1
    assert set(out[0].external_ids) == {"SNAP-123", "DGI-c3-Acme"}


def test_same_source_twice_does_not_duplicate_source_list():
    a = _resource("usda-snap", "Acme Market", 39.7, -75.5)
    b = _resource("usda-snap", "Acme Market", 39.7, -75.50001)  # within 30m
    out = merge_food_resources([a, b])
    assert len(out) == 1
    assert out[0].sources == ["usda-snap"]  # not duplicated
    assert out[0].contributor_count == 2


# ---------------------------------------------------------------------------
# Output stability
# ---------------------------------------------------------------------------


def test_output_is_sorted_stably():
    items = [
        _resource("usda-snap", "Charlie", 39.71, -75.5),
        _resource("usda-snap", "Alpha", 39.70, -75.5),
        _resource("usda-snap", "Bravo", 39.70, -75.49),
    ]
    out = merge_food_resources(items)
    # Sorted by (lat, lon, name). For two records at the same latitude,
    # the one with the more-negative longitude (further west) sorts first.
    assert [m.name for m in out] == ["Alpha", "Bravo", "Charlie"]


def test_first_record_keeps_latlon_on_merge():
    a = _resource("usda-snap", "Acme Market", 39.70000, -75.50000)
    b = _resource("dgi-grantees", "Acme Market", 39.70001, -75.50000)  # within 30m
    out = merge_food_resources([a, b])
    assert len(out) == 1
    assert out[0].lat == 39.70000
    assert out[0].lon == -75.50000
