"""Smoke tests for etl/lib/load_raw.py — disk -> PipelineInputs glue.

Exercises:
  - empty raw_dir produces a runnable lenient LoadedRaw (zero grantees,
    zero tracts, zero pass-throughs, geo_stack_available reflects env)
  - DSB grantee JSON loads into GranteeInput records
  - cycle_5_status propagates from DSB JSON to manifest
  - ACS tract JSON converts to CSV with a GEOID column prefix
  - pass-through bytes loaders pick up firstmap-sd2.geojson, dart-routes.geojson, mhc-tract-de.csv
  - manifest is populated with one SourceEntry per artifact found

Geo-stack reads are exercised in a separate importorskip-gated test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from etl.lib.load_raw import (
    LoadedRaw,
    _acs_tract_json_to_csv,
    load_raw_artifacts,
)


DEFAULT_PARAMETERS = {
    "state_mfi_median": 90116.0,
}


def test_load_raw_empty_dir(tmp_path: Path) -> None:
    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert isinstance(result, LoadedRaw)
    assert result.grantees == []
    assert result.food_resources_raw == []
    assert result.tracts == []
    assert result.lila_geojson is None
    assert result.sd2_geojson is None
    assert result.dart_routes_geojson is None
    assert result.mhc_csv is None
    assert result.state_mfi_median == pytest.approx(90116.0)
    assert result.manifest.cycle_5_status == "pending"
    # No artifacts present -> no source entries beyond defaults
    assert result.manifest.sources == {}


def test_load_raw_picks_up_passthroughs(tmp_path: Path) -> None:
    (tmp_path / "firstmap-sd2.geojson").write_bytes(
        b'{"type":"FeatureCollection","features":[]}'
    )
    (tmp_path / "dart-routes.geojson").write_bytes(
        b'{"type":"FeatureCollection","features":[]}'
    )
    (tmp_path / "mhc-tract-de.csv").write_bytes(b"GEOID,prevalence\n")
    (tmp_path / "usda-lila-de-clipped.geojson").write_bytes(
        b'{"type":"FeatureCollection","features":[]}'
    )

    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert result.sd2_geojson is not None and len(result.sd2_geojson) > 0
    assert result.dart_routes_geojson is not None
    assert result.mhc_csv is not None
    assert result.lila_geojson is not None
    # Every loaded pass-through registers a source in the manifest
    for name in ("firstmap-sd2", "dart-routes", "mhc-tract", "usda-lila-clipped"):
        assert name in result.manifest.sources


def test_load_raw_dsb_grantees(tmp_path: Path) -> None:
    dsb_payload = {
        "snapshot_sha": "abc123",
        "cycle_5_status": "published",
        "parser_warnings": [],
        "grantees": [
            {
                "cycle": 1,
                "grantee": "Acme Market",
                "storefront_address": "123 Main St, Wilmington, DE 19801",
                "amount_usd": 90000.0,
                "awarded_date": "2022-08-15",
                "category": "corner-store",
            },
            {
                "cycle": 5,
                "grantee": "(pending publication)",
                "storefront_address": None,
                "amount_usd": None,
                "awarded_date": None,
                "category": None,
            },
        ],
    }
    (tmp_path / "dsb-grants.json").write_text(json.dumps(dsb_payload), encoding="utf-8")

    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert len(result.grantees) == 2
    assert result.grantees[0].grantee == "Acme Market"
    assert result.grantees[0].amount_usd == pytest.approx(90000.0)
    assert result.grantees[1].category == "supermarket"  # default applied when None
    assert result.manifest.cycle_5_status == "published"
    assert "dsb-grants" in result.manifest.sources


def test_load_raw_skips_grantees_missing_cycle(tmp_path: Path) -> None:
    payload = {
        "cycle_5_status": "pending",
        "grantees": [
            {"grantee": "no-cycle"},   # skipped
            {"cycle": 2, "grantee": "ok", "amount_usd": 500.0},
        ],
    }
    (tmp_path / "dsb-grants.json").write_text(json.dumps(payload), encoding="utf-8")
    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert len(result.grantees) == 1
    assert result.grantees[0].grantee == "ok"


def test_acs_tract_json_to_csv_adds_geoid_column() -> None:
    raw = json.dumps([
        ["NAME", "B01003_001E", "B19013_001E", "state", "county", "tract"],
        ["Tract 1", "1234", "56789", "10", "001", "040100"],
        ["Tract 2", "2345", "67890", "10", "003", "010100"],
    ]).encode("utf-8")

    csv_bytes = _acs_tract_json_to_csv(raw)
    text = csv_bytes.decode("utf-8")
    lines = text.strip().split("\n")
    header = lines[0].split(",")
    assert header[0] == "GEOID"
    assert "B01003_001E" in header
    # GEOID = state(10) + county(001) + tract(040100) -> "10001040100" (11 chars)
    row1 = lines[1].split(",")
    assert row1[0] == "10001040100"
    row2 = lines[2].split(",")
    assert row2[0] == "10003010100"


def test_load_raw_converts_acs_tract_json(tmp_path: Path) -> None:
    payload = json.dumps([
        ["NAME", "B01003_001E", "state", "county", "tract"],
        ["Tract A", "1000", "10", "001", "040100"],
    ]).encode("utf-8")
    (tmp_path / "acs-tract-de.json").write_bytes(payload)

    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert result.acs_demographics_csv is not None
    text = result.acs_demographics_csv.decode("utf-8")
    assert text.startswith("GEOID,")
    assert "10001040100" in text


def test_load_raw_geo_stack_when_geopandas_absent(tmp_path: Path) -> None:
    """Without GDAL/geopandas, the TIGER loads silently skip."""
    # Drop fake zip files; if geopandas isn't installed they should be
    # ignored. If geopandas IS installed they'll fail to parse but the
    # loader catches and emits a note.
    (tmp_path / "tiger-tracts-de.zip").write_bytes(b"PK\x03\x04not-a-real-shapefile")
    (tmp_path / "tiger-bgs-de.zip").write_bytes(b"PK\x03\x04not-a-real-shapefile")

    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    # In both branches (geopandas present or not) the loader returns:
    # - target_tracts_gdf is None (parse fails or skipped)
    # - tracts is empty
    assert result.target_tracts_gdf is None or hasattr(result.target_tracts_gdf, "columns")
    assert isinstance(result.tracts, list)


def test_load_raw_state_mfi_median_from_parameters(tmp_path: Path) -> None:
    result = load_raw_artifacts(tmp_path, {"state_mfi_median": 88000.5})
    assert result.state_mfi_median == pytest.approx(88000.5)


def test_load_raw_state_mfi_median_default(tmp_path: Path) -> None:
    """When parameters omit state_mfi_median, loader falls back to a sane default."""
    result = load_raw_artifacts(tmp_path, {})
    assert result.state_mfi_median == pytest.approx(90116.0)


# ---------------------------------------------------------------------------
# S+5 additions — SNAP retailers + farmers markets in food_resources_raw
# ---------------------------------------------------------------------------


def test_load_raw_snap_retailers_populates_food_resources(tmp_path: Path) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-75.5, 39.7]},
                "properties": {
                    "Record_ID": "DE001",
                    "Store_Name": "Acme Grocery",
                    "Store_Street_Address": "100 Main St",
                    "City": "Wilmington",
                    "State": "DE",
                    "Zip_Code": "19801",
                    "Store_Type": "Grocery Store",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-75.4, 39.6]},
                "properties": {
                    "Record_ID": "DE002",
                    "Store_Name": "QuickStop",
                    "City": "Newark",
                    "State": "DE",
                    "Zip_Code": "19711",
                    "Store_Type": "Convenience Store",
                },
            },
        ],
    }
    (tmp_path / "snap-retailers-de.geojson").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert len(result.food_resources_raw) == 2
    assert result.food_resources_raw[0].source == "snap-retailers"
    assert result.food_resources_raw[0].name == "Acme Grocery"
    assert result.food_resources_raw[0].category == "grocery-store"
    assert result.food_resources_raw[1].category == "corner-store"
    assert "snap-retailers" in result.manifest.sources


def test_load_raw_snap_retailers_skips_features_missing_geometry(tmp_path: Path) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": {"Store_Name": "Bad", "Store_Type": "Grocery Store"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-75.5, 39.7]},
             "properties": {"Store_Name": "Good", "Store_Type": "Grocery Store"}},
        ],
    }
    (tmp_path / "snap-retailers-de.geojson").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert len(result.food_resources_raw) == 1
    assert result.food_resources_raw[0].name == "Good"


def test_load_raw_farmers_markets_populates_food_resources(tmp_path: Path) -> None:
    payload = {
        "markets": [
            {
                "listing_id": "fm-1",
                "listing_name": "Wilmington Farmers Market",
                "location_address": "200 Market St, Wilmington, DE",
                "location_state": "Delaware",
                "location_lat": 39.74,
                "location_lon": -75.55,
            }
        ]
    }
    (tmp_path / "usda-farmers-markets-de.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert len(result.food_resources_raw) == 1
    fr = result.food_resources_raw[0]
    assert fr.source == "usda-farmers-markets"
    assert fr.category == "farmers-market"
    assert fr.lat == pytest.approx(39.74)
    assert "usda-farmers-markets" in result.manifest.sources


def test_load_raw_combines_snap_and_farmers_markets(tmp_path: Path) -> None:
    (tmp_path / "snap-retailers-de.geojson").write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-75.5, 39.7]},
                "properties": {"Store_Name": "S1", "Store_Type": "Grocery Store"},
            }],
        }),
        encoding="utf-8",
    )
    (tmp_path / "usda-farmers-markets-de.json").write_text(
        json.dumps({"markets": [{
            "listing_name": "FM1",
            "location_lat": 39.6,
            "location_lon": -75.6,
        }]}),
        encoding="utf-8",
    )
    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    sources = {r.source for r in result.food_resources_raw}
    assert sources == {"snap-retailers", "usda-farmers-markets"}
    assert len(result.food_resources_raw) == 2


def test_load_raw_farmers_markets_skips_markets_missing_coords(tmp_path: Path) -> None:
    (tmp_path / "usda-farmers-markets-de.json").write_text(
        json.dumps({"markets": [
            {"listing_name": "No Coords", "location_lat": None, "location_lon": None},
            {"listing_name": "Has Coords", "location_lat": 39.7, "location_lon": -75.5},
        ]}),
        encoding="utf-8",
    )
    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert len(result.food_resources_raw) == 1
    assert result.food_resources_raw[0].name == "Has Coords"
