"""Smoke tests for etl.transforms.geocode (cross-check + confidence)."""

from __future__ import annotations

import json

import pytest

from etl.lib.geocode import GeocodeResult
from etl.transforms.geocode import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MANUAL,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_PENDING,
    GeocoderPair,
    GranteeInput,
    geocode_grantees,
)


# ---------------------------------------------------------------------------
# Helpers to build deterministic GeocodeResult fixtures
# ---------------------------------------------------------------------------


def _census_hit(
    address: str,
    *,
    lat: float = 39.7445,
    lon: float = -75.5455,
    tract_geoid: str = "10003001100",
) -> GeocodeResult:
    return GeocodeResult(
        provider="census",
        address=address,
        found=True,
        lat=lat,
        lon=lon,
        tract_geoid=tract_geoid,
        county_fips="003",
        state_fips="10",
        matched_address=address.upper(),
        raw={},
        cache_hit=False,
        fetched_at="2026-05-11T13:00:00Z",
    )


def _nominatim_hit(
    address: str, *, lat: float = 39.7445, lon: float = -75.5455
) -> GeocodeResult:
    return GeocodeResult(
        provider="nominatim",
        address=address,
        found=True,
        lat=lat,
        lon=lon,
        tract_geoid=None,
        county_fips=None,
        state_fips=None,
        matched_address=address,
        raw={},
        cache_hit=False,
        fetched_at="2026-05-11T13:00:00Z",
    )


def _miss(provider: str, address: str) -> GeocodeResult:
    return GeocodeResult(
        provider=provider,
        address=address,
        found=False,
        lat=None,
        lon=None,
        tract_geoid=None,
        county_fips=None,
        state_fips=None,
        matched_address=None,
        raw={},
        cache_hit=False,
        fetched_at="2026-05-11T13:00:00Z",
    )


def _make_geocoders(census_results: dict, nominatim_results: dict) -> GeocoderPair:
    def census_fn(addr: str, **kwargs) -> GeocodeResult:
        return census_results.get(addr) or _miss("census", addr)

    def nominatim_fn(addr: str, **kwargs) -> GeocodeResult:
        return nominatim_results.get(addr) or _miss("nominatim", addr)

    return GeocoderPair(census_fn=census_fn, nominatim_fn=nominatim_fn)


# ---------------------------------------------------------------------------
# Confidence classification
# ---------------------------------------------------------------------------


def test_confidence_high_when_geocoders_agree() -> None:
    addr = "123 N Market St, Wilmington, DE 19801"
    geocoders = _make_geocoders(
        census_results={addr: _census_hit(addr)},
        nominatim_results={addr: _nominatim_hit(addr)},  # same lat/lon
    )
    g = GranteeInput(
        cycle=3,
        grantee="Acme Corner",
        amount_usd=125000.0,
        category="corner-store",
        storefront_address=addr,
    )
    records, flags = geocode_grantees([g], geocoders=geocoders)
    assert len(records) == 1
    assert records[0].geocoding_confidence == CONFIDENCE_HIGH
    assert records[0].tract_geoid == "10003001100"
    assert records[0].distance_disagreement_m == pytest.approx(0.0, abs=1.0)
    assert flags == []


def test_confidence_medium_when_geocoders_disagree_far_enough() -> None:
    addr = "123 N Market St, Wilmington, DE 19801"
    geocoders = _make_geocoders(
        census_results={addr: _census_hit(addr, lat=39.7445, lon=-75.5455)},
        nominatim_results={
            addr: _nominatim_hit(addr, lat=39.7445, lon=-75.5575)  # ~1km west
        },
    )
    g = GranteeInput(
        cycle=3,
        grantee="Acme Corner",
        amount_usd=125000.0,
        category="corner-store",
        storefront_address=addr,
    )
    records, flags = geocode_grantees([g], geocoders=geocoders)
    assert records[0].geocoding_confidence == CONFIDENCE_MEDIUM
    assert records[0].distance_disagreement_m > 200
    # Wilmington corner-store at medium → data-quality flag
    assert len(flags) == 1
    assert flags[0].flag == "pending-manual-review"


def test_confidence_manual_when_census_misses() -> None:
    addr = "999 Unknown Way, Wilmington, DE 19801"
    geocoders = _make_geocoders(
        census_results={},  # census miss
        nominatim_results={addr: _nominatim_hit(addr)},
    )
    g = GranteeInput(
        cycle=2,
        grantee="Mystery Mart",
        amount_usd=50000.0,
        category="corner-store",
        storefront_address=addr,
    )
    records, flags = geocode_grantees([g], geocoders=geocoders)
    assert records[0].geocoding_confidence == CONFIDENCE_MANUAL
    # Wilmington corner-store with manual confidence → flagged
    assert len(flags) == 1
    assert flags[0].flag == "requires-manual-tract-assignment"


def test_confidence_manual_when_both_miss() -> None:
    geocoders = _make_geocoders(census_results={}, nominatim_results={})
    g = GranteeInput(
        cycle=1,
        grantee="Phantom Store",
        amount_usd=100000.0,
        category="supermarket",  # NOT a corner-store; should NOT flag
        storefront_address="completely unparseable input",
    )
    records, flags = geocode_grantees([g], geocoders=geocoders)
    assert records[0].geocoding_confidence == CONFIDENCE_MANUAL
    assert flags == []  # not a Wilmington corner-store


def test_pending_when_storefront_address_missing() -> None:
    g = GranteeInput(
        cycle=5,
        grantee="(pending publication)",
        amount_usd=700000.0,
        category="other",
        storefront_address=None,
    )
    records, flags = geocode_grantees([g])
    assert records[0].geocoding_confidence == CONFIDENCE_PENDING
    assert records[0].lat is None and records[0].lon is None
    assert records[0].tract_geoid is None


# ---------------------------------------------------------------------------
# Wilmington classification
# ---------------------------------------------------------------------------


def test_wilmington_corner_store_classification() -> None:
    """is_wilmington_corner_store covers category × zip combos."""
    cs_in = GranteeInput(
        cycle=1, grantee="A", amount_usd=1, category="corner-store",
        storefront_address="123 N Market St, Wilmington, DE 19801",
    )
    assert cs_in.is_wilmington_corner_store() is True

    cs_out = GranteeInput(
        cycle=1, grantee="A", amount_usd=1, category="corner-store",
        storefront_address="123 King St, Dover, DE 19901",
    )
    assert cs_out.is_wilmington_corner_store() is False

    super_wilm = GranteeInput(
        cycle=1, grantee="A", amount_usd=1, category="supermarket",
        storefront_address="123 N Market St, Wilmington, DE 19801",
    )
    assert super_wilm.is_wilmington_corner_store() is False

    specialty_wilm = GranteeInput(
        cycle=1, grantee="A", amount_usd=1, category="specialty-grocer",
        storefront_address="123 N Market St, Wilmington, DE 19801",
    )
    assert specialty_wilm.is_wilmington_corner_store() is True


def test_zip_extracted_when_not_provided() -> None:
    g = GranteeInput(
        cycle=1, grantee="A", amount_usd=1, category="corner-store",
        storefront_address="123 N Market St, Wilmington, DE 19805-1234",
    )
    assert g.is_wilmington_corner_store() is True


# ---------------------------------------------------------------------------
# Census-tract carries through when Census found
# ---------------------------------------------------------------------------


def test_tract_geoid_set_from_census_even_with_medium_confidence() -> None:
    """Even if Nominatim disagrees, we still use Census's tract."""
    addr = "5 Test St, Wilmington, DE 19801"
    geocoders = _make_geocoders(
        census_results={addr: _census_hit(addr, tract_geoid="10003999900")},
        nominatim_results={
            addr: _nominatim_hit(addr, lat=39.7445, lon=-75.5575)
        },
    )
    g = GranteeInput(
        cycle=1, grantee="Test", amount_usd=10000.0, category="corner-store",
        storefront_address=addr,
    )
    records, _ = geocode_grantees([g], geocoders=geocoders)
    assert records[0].geocoding_confidence == CONFIDENCE_MEDIUM
    assert records[0].tract_geoid == "10003999900"
