"""Tests for etl.transforms.apportion (population-weighted areal interpolation).

Requires the geo stack (geopandas + shapely). Skipped on Windows local
dev when GDAL isn't installed; runs in CI per the dgi-etl.yml workflow.
"""

from __future__ import annotations

import pytest


geopandas = pytest.importorskip("geopandas")
shapely = pytest.importorskip("shapely")
from shapely.geometry import Polygon  # noqa: E402


from etl.transforms.apportion import (  # noqa: E402
    population_weighted_interpolate,
)


# ---------------------------------------------------------------------------
# Toy fixtures
# ---------------------------------------------------------------------------


def _make_county(name: str, polygon: Polygon, count: int) -> dict:
    return {"FIPS": name, "geometry": polygon, "food_insecure_count": count}


def _make_tract(name: str, polygon: Polygon) -> dict:
    return {"GEOID": name, "geometry": polygon}


def _make_bg(name: str, polygon: Polygon, pop: int) -> dict:
    return {"BG_ID": name, "geometry": polygon, "POP": pop}


def _to_gdf(rows: list[dict]) -> geopandas.GeoDataFrame:
    return geopandas.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


# Two adjacent counties, each split into two tracts. Block groups
# distribute population unevenly so apportionment differs from area-only.
COUNTY_A = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
COUNTY_B = Polygon([(10, 0), (20, 0), (20, 10), (10, 10)])

TRACT_A1 = Polygon([(0, 0), (5, 0), (5, 10), (0, 10)])    # left half of A
TRACT_A2 = Polygon([(5, 0), (10, 0), (10, 10), (5, 10)])  # right half of A
TRACT_B1 = Polygon([(10, 0), (15, 0), (15, 10), (10, 10)])
TRACT_B2 = Polygon([(15, 0), (20, 0), (20, 10), (15, 10)])

# Block groups: A1 has 900 pop in 90% of its area, A2 has 100. So A's
# food-insecure count should apportion 900/1000 to A1 and 100/1000 to A2.
BG_A1 = (Polygon([(0, 0), (5, 0), (5, 10), (0, 10)]), 900)
BG_A2 = (Polygon([(5, 0), (10, 0), (10, 10), (5, 10)]), 100)
BG_B1 = (Polygon([(10, 0), (15, 0), (15, 10), (10, 10)]), 500)
BG_B2 = (Polygon([(15, 0), (20, 0), (20, 10), (15, 10)]), 500)


# ---------------------------------------------------------------------------
# Apportionment correctness
# ---------------------------------------------------------------------------


def test_population_weighted_apportionment_basic():
    source = _to_gdf([
        _make_county("10001", COUNTY_A, count=1000),
        _make_county("10003", COUNTY_B, count=500),
    ])
    target = _to_gdf([
        _make_tract("10001000100", TRACT_A1),
        _make_tract("10001000200", TRACT_A2),
        _make_tract("10003000100", TRACT_B1),
        _make_tract("10003000200", TRACT_B2),
    ])
    weights = _to_gdf([
        _make_bg("A1", BG_A1[0], BG_A1[1]),
        _make_bg("A2", BG_A2[0], BG_A2[1]),
        _make_bg("B1", BG_B1[0], BG_B1[1]),
        _make_bg("B2", BG_B2[0], BG_B2[1]),
    ])

    result = population_weighted_interpolate(
        source, target, weights,
        source_id_col="FIPS",
        target_id_col="GEOID",
        weight_pop_col="POP",
        extensive_variables=("food_insecure_count",),
        # Use a metric CRS for tests — we use a simple cartesian CRS;
        # EPSG:5070 doesn't make sense for unit-square polygons, so we
        # stay in EPSG:4326 for this synthetic test.
        working_crs="EPSG:4326",
    )

    apportioned = {
        row["GEOID"]: row["food_insecure_count_apportioned"]
        for _, row in result.target.iterrows()
    }
    # A1 holds 900/1000 of A's pop -> 900 of the 1000 count
    assert apportioned["10001000100"] == pytest.approx(900, rel=1e-6)
    assert apportioned["10001000200"] == pytest.approx(100, rel=1e-6)
    # B is split 500/500 -> 250 each
    assert apportioned["10003000100"] == pytest.approx(250, rel=1e-6)
    assert apportioned["10003000200"] == pytest.approx(250, rel=1e-6)


def test_apportionment_preserves_source_totals():
    """Sum of apportioned values should equal source totals (per-county)."""
    source = _to_gdf([
        _make_county("10001", COUNTY_A, count=1500),
    ])
    target = _to_gdf([
        _make_tract("10001000100", TRACT_A1),
        _make_tract("10001000200", TRACT_A2),
    ])
    weights = _to_gdf([
        _make_bg("A1", BG_A1[0], BG_A1[1]),
        _make_bg("A2", BG_A2[0], BG_A2[1]),
    ])
    result = population_weighted_interpolate(
        source, target, weights,
        source_id_col="FIPS",
        target_id_col="GEOID",
        weight_pop_col="POP",
        extensive_variables=("food_insecure_count",),
        working_crs="EPSG:4326",
    )
    apportioned = result.target["food_insecure_count_apportioned"].sum()
    assert apportioned == pytest.approx(1500, rel=1e-6)


def test_coverage_diagnostic_is_one_for_full_population_coverage():
    source = _to_gdf([
        _make_county("10001", COUNTY_A, count=1000),
    ])
    target = _to_gdf([
        _make_tract("10001000100", TRACT_A1),
        _make_tract("10001000200", TRACT_A2),
    ])
    weights = _to_gdf([
        _make_bg("A1", BG_A1[0], BG_A1[1]),
        _make_bg("A2", BG_A2[0], BG_A2[1]),
    ])
    result = population_weighted_interpolate(
        source, target, weights,
        source_id_col="FIPS",
        target_id_col="GEOID",
        weight_pop_col="POP",
        extensive_variables=("food_insecure_count",),
        working_crs="EPSG:4326",
    )
    assert result.coverage["10001"] == pytest.approx(1.0, rel=1e-6)
    assert result.unmatched_sources == []


def test_county_with_no_weight_population_is_flagged():
    """A county with no overlapping weight layer should land in unmatched."""
    # County C doesn't overlap any of the BGs.
    COUNTY_C = Polygon([(100, 100), (110, 100), (110, 110), (100, 110)])
    source = _to_gdf([
        _make_county("10999", COUNTY_C, count=500),
    ])
    target = _to_gdf([
        _make_tract("10999000100", COUNTY_C),  # one tract that is the full county
    ])
    weights = _to_gdf([
        _make_bg("A1", BG_A1[0], BG_A1[1]),
    ])
    result = population_weighted_interpolate(
        source, target, weights,
        source_id_col="FIPS",
        target_id_col="GEOID",
        weight_pop_col="POP",
        extensive_variables=("food_insecure_count",),
        working_crs="EPSG:4326",
    )
    assert "10999" in result.unmatched_sources
    # The target gets a 0 contribution (no weight pop).
    apportioned = result.target["food_insecure_count_apportioned"].iloc[0]
    assert apportioned == pytest.approx(0.0)
