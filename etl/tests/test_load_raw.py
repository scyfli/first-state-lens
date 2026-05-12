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
    _build_dart_routes_geojson_from_gtfs,
    _build_lila_geojson_from_xlsx,
    _build_shape_lines,
    _build_tracts_from_gdfs,
    _coerce_lila_flag,
    _coerce_lila_numeric,
    _compute_tract_urbanicity_lookup,
    _gtfs_routes_by_shape,
    _load_acs_tract_demographics,
    _load_lila_urban_lookup_from_xlsx,
    _load_state_mfi_from_acs_json,
    _normalize_lila_tract,
    _read_lila_xlsx,
    load_raw_artifacts,
)
from etl.lib.manifest import Manifest


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
# v0.3.2 — live state_mfi_median from ACS B19113 statewide (Tier 1 cascade)
# ---------------------------------------------------------------------------


def _write_acs_state_mfi_json(path: Path, estimate: object) -> None:
    """Write a Census-API-shaped state-level B19113 response."""
    payload = [
        ["NAME", "B19113_001E", "state"],
        ["Delaware", estimate, "10"],
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_state_mfi_from_acs_json_happy_path(tmp_path: Path) -> None:
    path = tmp_path / "acs-state-mfi-de.json"
    _write_acs_state_mfi_json(path, "92500")
    assert _load_state_mfi_from_acs_json(path) == pytest.approx(92500.0)


def test_load_state_mfi_from_acs_json_missing_file(tmp_path: Path) -> None:
    assert _load_state_mfi_from_acs_json(tmp_path / "nope.json") is None


def test_load_state_mfi_from_acs_json_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json at all", encoding="utf-8")
    assert _load_state_mfi_from_acs_json(path) is None


def test_load_state_mfi_from_acs_json_missing_column(tmp_path: Path) -> None:
    path = tmp_path / "acs-state-mfi-de.json"
    path.write_text(
        json.dumps([["NAME", "state"], ["Delaware", "10"]]), encoding="utf-8"
    )
    assert _load_state_mfi_from_acs_json(path) is None


def test_load_state_mfi_from_acs_json_null_estimate(tmp_path: Path) -> None:
    path = tmp_path / "acs-state-mfi-de.json"
    _write_acs_state_mfi_json(path, None)
    assert _load_state_mfi_from_acs_json(path) is None


def test_load_state_mfi_from_acs_json_negative_sentinel(tmp_path: Path) -> None:
    """Census uses negative values as 'data not available' sentinels."""
    path = tmp_path / "acs-state-mfi-de.json"
    _write_acs_state_mfi_json(path, "-666666666")
    assert _load_state_mfi_from_acs_json(path) is None


def test_load_state_mfi_from_acs_json_non_numeric(tmp_path: Path) -> None:
    path = tmp_path / "acs-state-mfi-de.json"
    _write_acs_state_mfi_json(path, "not-a-number")
    assert _load_state_mfi_from_acs_json(path) is None


def test_load_raw_state_mfi_tier1_live_acs_wins_over_parameters(tmp_path: Path) -> None:
    """Tier 1 (live ACS) takes precedence over Tier 2 (parameters)."""
    _write_acs_state_mfi_json(tmp_path / "acs-state-mfi-de.json", "93750")
    result = load_raw_artifacts(tmp_path, {"state_mfi_median": 88000.0})
    assert result.state_mfi_median == pytest.approx(93750.0)
    assert "acs-state-mfi" in result.manifest.sources


def test_load_raw_state_mfi_tier1_malformed_falls_back_to_parameters(tmp_path: Path) -> None:
    """Tier 1 malformed -> Tier 2 (parameters); manifest does NOT record acs-state-mfi."""
    (tmp_path / "acs-state-mfi-de.json").write_text("garbage", encoding="utf-8")
    result = load_raw_artifacts(tmp_path, {"state_mfi_median": 88000.0})
    assert result.state_mfi_median == pytest.approx(88000.0)
    assert "acs-state-mfi" not in result.manifest.sources


def test_load_raw_state_mfi_tier1_malformed_no_params_falls_back_to_default(tmp_path: Path) -> None:
    """Tier 1 malformed + no Tier 2 -> Tier 3 (hardcoded 90116)."""
    (tmp_path / "acs-state-mfi-de.json").write_text("garbage", encoding="utf-8")
    result = load_raw_artifacts(tmp_path, {})
    assert result.state_mfi_median == pytest.approx(90116.0)
    assert "acs-state-mfi" not in result.manifest.sources


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


# ---------------------------------------------------------------------------
# S+6 — ACS tract demographics → TractInput.poverty_rate + .mfi
# ---------------------------------------------------------------------------


def _acs_demographics_payload(rows: list[list]) -> bytes:
    """Helper: build a Census-API-shaped JSON payload from row tuples.

    Each input row is [B17001_001E, B17001_002E, B19113_001E, state, county, tract].
    """
    header = ["NAME", "B17001_001E", "B17001_002E", "B19113_001E", "state", "county", "tract"]
    payload = [header]
    for r in rows:
        # Slot in a NAME column up front to match real Census API layout.
        payload.append(["Tract X", *r])
    return json.dumps(payload).encode("utf-8")


def test_load_acs_tract_demographics_computes_poverty_rate_and_mfi() -> None:
    raw = _acs_demographics_payload([
        # denom, numer, mfi, state, county, tract
        ["1000", "250", "75000", "10", "001", "040100"],
        ["2000", "100", "120000", "10", "003", "010100"],
    ])
    lookup = _load_acs_tract_demographics(raw)
    assert lookup["10001040100"]["poverty_rate"] == pytest.approx(0.25)
    assert lookup["10001040100"]["mfi"] == pytest.approx(75000.0)
    assert lookup["10003010100"]["poverty_rate"] == pytest.approx(0.05)
    assert lookup["10003010100"]["mfi"] == pytest.approx(120000.0)


def test_load_acs_tract_demographics_handles_sentinels() -> None:
    raw = _acs_demographics_payload([
        # Census "no sample" sentinel for MFI; poverty data intact.
        ["1000", "200", "-666666666", "10", "001", "040100"],
        # Sentinel poverty denominator → poverty_rate None; MFI intact.
        ["-999999999", "100", "85000", "10", "003", "010100"],
        # Both ranges of sentinels.
        ["-222222222", "-555555555", "-333333333", "10", "005", "030100"],
    ])
    lookup = _load_acs_tract_demographics(raw)
    assert lookup["10001040100"]["poverty_rate"] == pytest.approx(0.20)
    assert lookup["10001040100"]["mfi"] is None
    assert lookup["10003010100"]["poverty_rate"] is None
    assert lookup["10003010100"]["mfi"] == pytest.approx(85000.0)
    assert lookup["10005030100"]["poverty_rate"] is None
    assert lookup["10005030100"]["mfi"] is None


def test_load_acs_tract_demographics_handles_zero_denominator() -> None:
    raw = _acs_demographics_payload([
        ["0", "0", "75000", "10", "001", "040100"],
    ])
    lookup = _load_acs_tract_demographics(raw)
    assert lookup["10001040100"]["poverty_rate"] is None
    assert lookup["10001040100"]["mfi"] == pytest.approx(75000.0)


def test_load_acs_tract_demographics_handles_zero_mfi() -> None:
    """An MFI of 0 is not meaningful — should coerce to None."""
    raw = _acs_demographics_payload([
        ["1000", "100", "0", "10", "001", "040100"],
    ])
    lookup = _load_acs_tract_demographics(raw)
    assert lookup["10001040100"]["poverty_rate"] == pytest.approx(0.1)
    assert lookup["10001040100"]["mfi"] is None


def test_load_acs_tract_demographics_handles_empty_payload() -> None:
    assert _load_acs_tract_demographics(b"") == {}
    assert _load_acs_tract_demographics(b"[]") == {}
    assert _load_acs_tract_demographics(b"not json") == {}


def test_load_acs_tract_demographics_handles_missing_column() -> None:
    """Without the required Census variables, return {} cleanly."""
    payload = json.dumps([
        ["NAME", "B01003_001E", "state", "county", "tract"],
        ["Tract 1", "1234", "10", "001", "040100"],
    ]).encode("utf-8")
    assert _load_acs_tract_demographics(payload) == {}


def test_load_acs_tract_demographics_skips_malformed_rows() -> None:
    """Rows that can't form a valid 11-char GEOID are skipped."""
    raw = _acs_demographics_payload([
        ["1000", "100", "75000", "10", "001", "040100"],   # OK
        ["1000", "100", "75000", "999", "001", "040100"],  # 3-char state -> 12 chars, skipped
    ])
    lookup = _load_acs_tract_demographics(raw)
    assert "10001040100" in lookup
    assert len(lookup) == 1


def test_load_raw_populates_demographics_lookup_note(tmp_path: Path) -> None:
    """When acs-tract-de.json is present, the loader notes how many demos joined."""
    raw = _acs_demographics_payload([
        ["1000", "250", "75000", "10", "001", "040100"],
        ["2000", "100", "120000", "10", "003", "010100"],
    ])
    (tmp_path / "acs-tract-de.json").write_bytes(raw)
    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert result.acs_demographics_csv is not None
    # Loader's notes should mention the demographics record count
    demo_notes = [n for n in result.notes if "tract demographics records loaded" in n]
    assert len(demo_notes) == 1
    assert "2 tract demographics records" in demo_notes[0]


# ---------------------------------------------------------------------------
# Geo-stack integration: TractInput.poverty_rate + .mfi populated end-to-end
# ---------------------------------------------------------------------------


def test_build_tracts_from_gdfs_joins_demographics() -> None:
    """End-to-end: TIGER + BG GDFs + demographics_lookup → TractInputs with demos."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point, Polygon

    # Two tract polygons. One has demographics; the other doesn't (lookup miss).
    tract_gdf = gpd.GeoDataFrame(
        {
            "GEOID": ["10001040100", "10003010100"],
            "geometry": [
                Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
            ],
        },
        crs="EPSG:4326",
    )
    # One block group per tract; centroid inside the polygon.
    bg_gdf = gpd.GeoDataFrame(
        {
            "GEOID": ["100010401001", "100030101001"],
            "POP": [500, 800],
            "geometry": [Point(0.5, 0.5), Point(2.5, 0.5)],
        },
        crs="EPSG:4326",
    )
    demographics = {
        "10001040100": {"poverty_rate": 0.25, "mfi": 60000.0},
        # 10003010100 deliberately absent — should yield None/None.
    }

    notes: list[str] = []
    tracts = _build_tracts_from_gdfs(
        tract_gdf, bg_gdf, notes, demographics_lookup=demographics
    )
    by_geoid = {t.tract_geoid: t for t in tracts}
    assert by_geoid["10001040100"].poverty_rate == pytest.approx(0.25)
    assert by_geoid["10001040100"].mfi == pytest.approx(60000.0)
    assert by_geoid["10003010100"].poverty_rate is None
    assert by_geoid["10003010100"].mfi is None
    # Both tracts get urbanicity classified (10001 starts with non-10003 → nonurban)
    assert by_geoid["10001040100"].urbanicity == "nonurban"
    assert by_geoid["10003010100"].urbanicity == "urban"


def test_build_tracts_from_gdfs_without_demographics_defaults_to_none() -> None:
    """Backward compat: no demographics_lookup → poverty_rate=mfi=None on all tracts."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    tract_gdf = gpd.GeoDataFrame(
        {
            "GEOID": ["10003010100"],
            "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        },
        crs="EPSG:4326",
    )
    tracts = _build_tracts_from_gdfs(tract_gdf, None, [])
    assert len(tracts) == 1
    assert tracts[0].poverty_rate is None
    assert tracts[0].mfi is None


# ---------------------------------------------------------------------------
# S+6 — USDA LILA xlsx → DE-clipped GeoJSON transform
# ---------------------------------------------------------------------------


def test_normalize_lila_tract_zero_pads_and_handles_types() -> None:
    """USDA's CensusTract column may be int or string; normalize to 11 chars."""
    assert _normalize_lila_tract("10001040100") == "10001040100"
    assert _normalize_lila_tract(10001040100) == "10001040100"
    assert _normalize_lila_tract(10001040100.0) == "10001040100"
    # Leading-zero state (e.g., Alabama "01") survives zero-padding.
    assert _normalize_lila_tract("1001040100") == "01001040100"
    assert _normalize_lila_tract(None) is None
    assert _normalize_lila_tract("") is None
    # Anything longer than 11 chars is rejected as malformed.
    assert _normalize_lila_tract("123456789012") is None


def test_coerce_lila_flag_handles_xlsx_cell_variants() -> None:
    """LILA flags arrive as ints, floats, strings, or blank cells."""
    assert _coerce_lila_flag(1) == 1
    assert _coerce_lila_flag(0) == 0
    assert _coerce_lila_flag(1.0) == 1
    assert _coerce_lila_flag("1") == 1
    assert _coerce_lila_flag("0") == 0
    assert _coerce_lila_flag(None) == 0
    assert _coerce_lila_flag("") == 0
    assert _coerce_lila_flag("NA") == 0


def test_coerce_lila_numeric_returns_none_for_blanks() -> None:
    assert _coerce_lila_numeric(0.123) == pytest.approx(0.123)
    assert _coerce_lila_numeric("15.5") == pytest.approx(15.5)
    assert _coerce_lila_numeric(None) is None
    assert _coerce_lila_numeric("") is None
    assert _coerce_lila_numeric("not a number") is None


def _write_lila_xlsx(
    path: Path,
    rows: list[dict],
    *,
    sheet_name: str = "Food Access Research Atlas",
    header_offset: int = 0,
) -> Path:
    """Build a LILA-shaped xlsx fixture programmatically.

    `header_offset` lets a test simulate USDA workbooks that prepend
    title rows above the header. The header row is written at
    `header_offset + 1` (openpyxl is 1-indexed).
    """
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    # Replace the default sheet rather than appending — keeps the workbook tidy.
    ws = wb.active
    ws.title = sheet_name
    # Optional title row before the header.
    for i in range(header_offset):
        ws.cell(row=i + 1, column=1, value=f"Title row {i + 1}")
    # Header: a stable subset of LILA columns. `Urban` is included
    # (methodology v0.3.1 reads it); records that don't set it leave the
    # cell blank, which the reader coerces to None.
    header = [
        "CensusTract",
        "State",
        "County",
        "LILATracts_1And10",
        "LILATracts_halfAnd10",
        "LowIncomeTracts",
        "PovertyRate",
        "MedianFamilyIncome",
        "Urban",
    ]
    for col_idx, name in enumerate(header, start=1):
        ws.cell(row=header_offset + 1, column=col_idx, value=name)
    for row_idx, record in enumerate(rows, start=header_offset + 2):
        for col_idx, name in enumerate(header, start=1):
            ws.cell(row=row_idx, column=col_idx, value=record.get(name))
    wb.save(path)
    return path


def test_read_lila_xlsx_filters_to_de_tracts(tmp_path: Path) -> None:
    """The reader keeps DE tracts (FIPS prefix '10') and drops others."""
    pytest.importorskip("openpyxl")
    xlsx = _write_lila_xlsx(
        tmp_path / "lila.xlsx",
        [
            {"CensusTract": "10001040100", "State": "Delaware", "County": "Kent",
             "LILATracts_1And10": 1, "LowIncomeTracts": 1,
             "PovertyRate": 21.5, "MedianFamilyIncome": 55000},
            {"CensusTract": "10003010100", "State": "Delaware", "County": "New Castle",
             "LILATracts_1And10": 0, "LowIncomeTracts": 0,
             "PovertyRate": 9.0, "MedianFamilyIncome": 95000},
            # Non-DE row that must be filtered out.
            {"CensusTract": "01001020100", "State": "Alabama", "County": "Autauga",
             "LILATracts_1And10": 1, "LowIncomeTracts": 1,
             "PovertyRate": 30.0, "MedianFamilyIncome": 40000},
        ],
    )
    out = _read_lila_xlsx(xlsx)
    assert set(out.keys()) == {"10001040100", "10003010100"}
    assert out["10001040100"]["LILATracts_1And10"] == 1
    assert out["10001040100"]["LowIncomeTracts"] == 1
    assert out["10001040100"]["PovertyRate"] == pytest.approx(21.5)
    assert out["10003010100"]["LILATracts_1And10"] == 0


def test_read_lila_xlsx_finds_header_below_title_rows(tmp_path: Path) -> None:
    """USDA workbooks sometimes prepend metadata rows above the header."""
    pytest.importorskip("openpyxl")
    xlsx = _write_lila_xlsx(
        tmp_path / "lila.xlsx",
        [{"CensusTract": "10005030100", "LILATracts_1And10": 1, "PovertyRate": 18.0}],
        header_offset=3,
    )
    out = _read_lila_xlsx(xlsx)
    assert "10005030100" in out
    assert out["10005030100"]["LILATracts_1And10"] == 1


def test_read_lila_xlsx_handles_integer_census_tract(tmp_path: Path) -> None:
    """When CensusTract is stored as an integer (no leading zero), zero-pad."""
    pytest.importorskip("openpyxl")
    xlsx = _write_lila_xlsx(
        tmp_path / "lila.xlsx",
        [{"CensusTract": 10001040100, "LILATracts_1And10": 1}],
    )
    out = _read_lila_xlsx(xlsx)
    assert "10001040100" in out


def test_build_lila_geojson_joins_tiger_geometry(tmp_path: Path) -> None:
    """End-to-end: xlsx + TIGER GDF → FeatureCollection bytes with LILA props."""
    pytest.importorskip("openpyxl")
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    xlsx = _write_lila_xlsx(
        tmp_path / "usda-lila-raw.xlsx",
        [
            {"CensusTract": "10001040100", "LILATracts_1And10": 1, "LowIncomeTracts": 1,
             "PovertyRate": 21.5, "MedianFamilyIncome": 55000},
            {"CensusTract": "10003010100", "LILATracts_1And10": 0, "LowIncomeTracts": 0,
             "PovertyRate": 9.0, "MedianFamilyIncome": 95000},
        ],
    )
    tract_gdf = gpd.GeoDataFrame(
        {
            "GEOID": ["10001040100", "10003010100"],
            "geometry": [
                Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
            ],
        },
        crs="EPSG:4326",
    )
    notes: list[str] = []
    out = _build_lila_geojson_from_xlsx(xlsx, tract_gdf, notes)
    assert out is not None
    payload = json.loads(out.decode("utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 2
    by_geoid = {f["properties"]["tract_geoid"]: f for f in payload["features"]}
    assert by_geoid["10001040100"]["properties"]["LILATracts_1And10"] == 1
    assert by_geoid["10001040100"]["geometry"]["type"] == "Polygon"
    # Diagnostic note reports join coverage.
    join_notes = [n for n in notes if "joined" in n]
    assert any("2 tracts joined" in n for n in join_notes)


def test_build_lila_geojson_returns_none_when_no_join_hits(tmp_path: Path) -> None:
    """Workbook has DE tracts but the TIGER GDF lacks matching GEOIDs → None."""
    pytest.importorskip("openpyxl")
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    xlsx = _write_lila_xlsx(
        tmp_path / "lila.xlsx",
        [{"CensusTract": "10001040100", "LILATracts_1And10": 1}],
    )
    tract_gdf = gpd.GeoDataFrame(
        {
            "GEOID": ["99999999999"],  # No match
            "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        },
        crs="EPSG:4326",
    )
    notes: list[str] = []
    out = _build_lila_geojson_from_xlsx(xlsx, tract_gdf, notes)
    assert out is None
    assert any("zero matched TIGER GEOIDs" in n for n in notes)


def test_load_raw_skips_lila_build_when_xlsx_missing(tmp_path: Path) -> None:
    """If no xlsx and no pre-clipped geojson, lila_geojson stays None cleanly."""
    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert result.lila_geojson is None
    # No noise about the LILA xlsx if it wasn't requested
    assert not any("usda-lila-xlsx" in n for n in result.notes)


def test_load_raw_pre_clipped_lila_takes_precedence_over_xlsx_build(tmp_path: Path) -> None:
    """When the operator pre-runs the transform, the prebuilt geojson wins."""
    pre = b'{"type":"FeatureCollection","features":[{"prebuilt":true}]}'
    (tmp_path / "usda-lila-de-clipped.geojson").write_bytes(pre)
    # Also drop an xlsx alongside; the prebuilt path must take precedence.
    pytest.importorskip("openpyxl")
    _write_lila_xlsx(
        tmp_path / "usda-lila-raw.xlsx",
        [{"CensusTract": "10001040100", "LILATracts_1And10": 1}],
    )
    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert result.lila_geojson == pre


# ---------------------------------------------------------------------------
# S+6 — DART GTFS shapes.txt → dart-routes.geojson transform
# ---------------------------------------------------------------------------


def _write_gtfs_zip(
    path: Path,
    *,
    shapes_rows: list[dict],
    trips_rows: list[dict] | None = None,
    routes_rows: list[dict] | None = None,
    omit_shapes: bool = False,
) -> Path:
    """Build a synthetic GTFS zip fixture in `path`."""
    import zipfile

    def _to_csv(headers: list[str], rows: list[dict]) -> str:
        out = [",".join(headers)]
        for r in rows:
            out.append(",".join(str(r.get(h, "")) for h in headers))
        return "\n".join(out) + "\n"

    with zipfile.ZipFile(path, "w") as zf:
        if not omit_shapes:
            zf.writestr(
                "shapes.txt",
                _to_csv(
                    ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"],
                    shapes_rows,
                ),
            )
        if trips_rows is not None:
            zf.writestr(
                "trips.txt",
                _to_csv(["route_id", "service_id", "trip_id", "shape_id"], trips_rows),
            )
        if routes_rows is not None:
            zf.writestr(
                "routes.txt",
                _to_csv(
                    ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"],
                    routes_rows,
                ),
            )
    return path


def test_build_shape_lines_groups_and_sorts_by_sequence() -> None:
    csv_text = (
        "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
        # Deliberately scrambled sequence order to exercise the sort.
        "1,39.71,-75.51,2\n"
        "1,39.70,-75.50,1\n"
        "1,39.72,-75.52,3\n"
        "2,39.60,-75.60,1\n"
        "2,39.61,-75.61,2\n"
    )
    out = _build_shape_lines(csv_text)
    assert set(out.keys()) == {"1", "2"}
    # Coordinates in [lon, lat] order, sorted by sequence
    assert out["1"] == [[-75.50, 39.70], [-75.51, 39.71], [-75.52, 39.72]]
    assert out["2"] == [[-75.60, 39.60], [-75.61, 39.61]]


def test_build_shape_lines_skips_malformed_rows() -> None:
    csv_text = (
        "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
        "1,39.70,-75.50,1\n"
        "1,not_a_number,-75.51,2\n"        # bad lat
        "1,39.71,-75.51,not_a_seq\n"        # bad seq
        "1,39.72,-75.52,3\n"
    )
    out = _build_shape_lines(csv_text)
    assert out == {"1": [[-75.50, 39.70], [-75.52, 39.72]]}


def test_gtfs_routes_by_shape_dedupes_and_preserves_order() -> None:
    trips_csv = (
        "route_id,service_id,trip_id,shape_id\n"
        "R1,wd,T1,1\n"
        "R1,wk,T2,1\n"          # duplicate route on same shape — dedupe
        "R2,wd,T3,1\n"          # second route shares the shape
        "R1,wd,T4,2\n"
    )
    routes_csv = (
        "route_id,agency_id,route_short_name,route_long_name,route_type\n"
        "R1,DART,1,Wilmington Loop,3\n"
        "R2,DART,2,New Castle Express,3\n"
    )
    out = _gtfs_routes_by_shape(trips_csv, routes_csv)
    assert out["1"]["short_names"] == ["1", "2"]
    assert out["1"]["long_names"] == ["Wilmington Loop", "New Castle Express"]
    assert out["2"]["short_names"] == ["1"]


def test_gtfs_routes_by_shape_returns_empty_when_files_missing() -> None:
    assert _gtfs_routes_by_shape("", "anything") == {}
    assert _gtfs_routes_by_shape("anything", "") == {}


def test_build_dart_routes_geojson_full_pipeline(tmp_path: Path) -> None:
    """Synthesize zip → parse → emit GeoJSON with route joins."""
    zip_path = _write_gtfs_zip(
        tmp_path / "dart-gtfs.zip",
        shapes_rows=[
            {"shape_id": "1", "shape_pt_lat": 39.70, "shape_pt_lon": -75.50, "shape_pt_sequence": 1},
            {"shape_id": "1", "shape_pt_lat": 39.71, "shape_pt_lon": -75.51, "shape_pt_sequence": 2},
            {"shape_id": "1", "shape_pt_lat": 39.72, "shape_pt_lon": -75.52, "shape_pt_sequence": 3},
            {"shape_id": "2", "shape_pt_lat": 39.60, "shape_pt_lon": -75.60, "shape_pt_sequence": 1},
            {"shape_id": "2", "shape_pt_lat": 39.61, "shape_pt_lon": -75.61, "shape_pt_sequence": 2},
        ],
        trips_rows=[
            {"route_id": "R1", "service_id": "wd", "trip_id": "T1", "shape_id": "1"},
            {"route_id": "R2", "service_id": "wd", "trip_id": "T2", "shape_id": "2"},
        ],
        routes_rows=[
            {"route_id": "R1", "agency_id": "DART", "route_short_name": "1", "route_long_name": "Loop A", "route_type": 3},
            {"route_id": "R2", "agency_id": "DART", "route_short_name": "2", "route_long_name": "Loop B", "route_type": 3},
        ],
    )
    notes: list[str] = []
    out = _build_dart_routes_geojson_from_gtfs(zip_path, notes)
    assert out is not None
    payload = json.loads(out.decode("utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 2
    by_shape = {f["properties"]["shape_id"]: f for f in payload["features"]}
    assert by_shape["1"]["geometry"]["type"] == "LineString"
    assert by_shape["1"]["geometry"]["coordinates"][0] == [-75.50, 39.70]
    assert by_shape["1"]["properties"]["route_short_names"] == ["1"]
    assert by_shape["1"]["properties"]["route_long_names"] == ["Loop A"]
    assert any("2 LineString(s)" in n for n in notes)


def test_build_dart_routes_geojson_skips_short_shapes(tmp_path: Path) -> None:
    """A shape with only one point can't be a LineString — drop it."""
    zip_path = _write_gtfs_zip(
        tmp_path / "dart-gtfs.zip",
        shapes_rows=[
            {"shape_id": "1", "shape_pt_lat": 39.70, "shape_pt_lon": -75.50, "shape_pt_sequence": 1},  # singleton
            {"shape_id": "2", "shape_pt_lat": 39.60, "shape_pt_lon": -75.60, "shape_pt_sequence": 1},
            {"shape_id": "2", "shape_pt_lat": 39.61, "shape_pt_lon": -75.61, "shape_pt_sequence": 2},
        ],
    )
    out = _build_dart_routes_geojson_from_gtfs(zip_path, [])
    payload = json.loads(out.decode("utf-8"))
    assert [f["properties"]["shape_id"] for f in payload["features"]] == ["2"]


def test_build_dart_routes_geojson_works_without_trips_or_routes(tmp_path: Path) -> None:
    """Shapes alone produce LineStrings; route names default to empty lists."""
    zip_path = _write_gtfs_zip(
        tmp_path / "dart-gtfs.zip",
        shapes_rows=[
            {"shape_id": "1", "shape_pt_lat": 39.70, "shape_pt_lon": -75.50, "shape_pt_sequence": 1},
            {"shape_id": "1", "shape_pt_lat": 39.71, "shape_pt_lon": -75.51, "shape_pt_sequence": 2},
        ],
    )
    out = _build_dart_routes_geojson_from_gtfs(zip_path, [])
    payload = json.loads(out.decode("utf-8"))
    feature = payload["features"][0]
    assert feature["properties"]["route_short_names"] == []
    assert feature["properties"]["route_long_names"] == []


def test_build_dart_routes_geojson_returns_none_when_shapes_missing(tmp_path: Path) -> None:
    """Zip with no shapes.txt → None and a diagnostic note."""
    zip_path = _write_gtfs_zip(
        tmp_path / "dart-gtfs.zip",
        shapes_rows=[],
        omit_shapes=True,
    )
    notes: list[str] = []
    out = _build_dart_routes_geojson_from_gtfs(zip_path, notes)
    assert out is None
    assert any("missing shapes.txt" in n for n in notes)


def test_build_dart_routes_geojson_returns_none_for_corrupt_zip(tmp_path: Path) -> None:
    bad_zip = tmp_path / "dart-gtfs.zip"
    bad_zip.write_bytes(b"this is not a zip")
    notes: list[str] = []
    out = _build_dart_routes_geojson_from_gtfs(bad_zip, notes)
    assert out is None
    assert any("read failed" in n for n in notes)


def test_load_raw_builds_dart_routes_from_gtfs_zip(tmp_path: Path) -> None:
    """End-to-end through load_raw: zip in raw_dir → dart_routes_geojson populated."""
    _write_gtfs_zip(
        tmp_path / "dart-gtfs.zip",
        shapes_rows=[
            {"shape_id": "1", "shape_pt_lat": 39.70, "shape_pt_lon": -75.50, "shape_pt_sequence": 1},
            {"shape_id": "1", "shape_pt_lat": 39.71, "shape_pt_lon": -75.51, "shape_pt_sequence": 2},
        ],
    )
    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert result.dart_routes_geojson is not None
    payload = json.loads(result.dart_routes_geojson.decode("utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 1
    assert "dart-gtfs-zip" in result.manifest.sources


def test_load_raw_pre_built_dart_geojson_takes_precedence(tmp_path: Path) -> None:
    """When the operator pre-runs the transform, the prebuilt geojson wins."""
    pre = b'{"type":"FeatureCollection","features":[{"prebuilt":true}]}'
    (tmp_path / "dart-routes.geojson").write_bytes(pre)
    _write_gtfs_zip(
        tmp_path / "dart-gtfs.zip",
        shapes_rows=[
            {"shape_id": "1", "shape_pt_lat": 39.70, "shape_pt_lon": -75.50, "shape_pt_sequence": 1},
            {"shape_id": "1", "shape_pt_lat": 39.71, "shape_pt_lon": -75.51, "shape_pt_sequence": 2},
        ],
    )
    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    assert result.dart_routes_geojson == pre
    # The "dart-gtfs-zip" source should NOT have been recorded; the
    # pre-built path took precedence and we never opened the zip.
    assert "dart-gtfs-zip" not in result.manifest.sources


# ---------------------------------------------------------------------------
# Methodology v0.3.0 — UAC urbanicity refinement
# ---------------------------------------------------------------------------


def test_build_tracts_falls_back_to_county_proxy_without_urbanicity_lookup() -> None:
    """When no UAC lookup is supplied, the legacy county-level proxy applies."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    tract_gdf = gpd.GeoDataFrame(
        {
            "GEOID": ["10003010100", "10001040100", "10005030100"],
            "geometry": [
                Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
                Polygon([(4, 0), (5, 0), (5, 1), (4, 1)]),
            ],
        },
        crs="EPSG:4326",
    )
    tracts = _build_tracts_from_gdfs(tract_gdf, None, [])
    by_geoid = {t.tract_geoid: t for t in tracts}
    # Proxy: New Castle (10003) → urban; Kent (10001) + Sussex (10005) → nonurban.
    assert by_geoid["10003010100"].urbanicity == "urban"
    assert by_geoid["10001040100"].urbanicity == "nonurban"
    assert by_geoid["10005030100"].urbanicity == "nonurban"


def test_build_tracts_uses_urbanicity_lookup_when_supplied() -> None:
    """v0.3.0: lookup overrides the proxy on a per-tract basis."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    tract_gdf = gpd.GeoDataFrame(
        {
            "GEOID": ["10003010100", "10001040100"],
            "geometry": [
                Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
            ],
        },
        crs="EPSG:4326",
    )
    # Deliberately invert the proxy: a New Castle tract is marked nonurban
    # (e.g., south of the C&D canal) and a Kent tract is urban (inside the
    # Dover urbanized area). The lookup must win over the proxy.
    urbanicity_lookup = {
        "10003010100": "nonurban",
        "10001040100": "urban",
    }
    tracts = _build_tracts_from_gdfs(
        tract_gdf, None, [], urbanicity_lookup=urbanicity_lookup
    )
    by_geoid = {t.tract_geoid: t for t in tracts}
    assert by_geoid["10003010100"].urbanicity == "nonurban"
    assert by_geoid["10001040100"].urbanicity == "urban"


def test_compute_tract_urbanicity_lookup_classifies_by_intersection(tmp_path: Path) -> None:
    """sjoin-based urban detection: tract intersects an urban polygon → urban."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    tract_gdf = gpd.GeoDataFrame(
        {
            "GEOID": ["10003010100", "10001040100", "10005030100"],
            "geometry": [
                # Inside the urban polygon
                Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                # Touches the urban cluster polygon (edge intersect counts)
                Polygon([(3, 0), (4, 0), (4, 1), (3, 1)]),
                # Far away — no urban overlap → nonurban
                Polygon([(10, 10), (11, 10), (11, 11), (10, 11)]),
            ],
        },
        crs="EPSG:4326",
    )
    urban_gdf = gpd.GeoDataFrame(
        {
            "UATYP10": ["U", "C"],
            "geometry": [
                # Urbanized Area covering the first tract
                Polygon([(-1, -1), (2, -1), (2, 2), (-1, 2)]),
                # Urban Cluster touching the second tract
                Polygon([(4, 0), (5, 0), (5, 1), (4, 1)]),
            ],
        },
        crs="EPSG:4326",
    )
    notes: list[str] = []
    lookup = _compute_tract_urbanicity_lookup(tract_gdf, urban_gdf, notes)
    assert lookup["10003010100"] == "urban"
    assert lookup["10001040100"] == "urban"
    assert lookup["10005030100"] == "nonurban"
    assert any("2/3" in n and "urban" in n for n in notes)


def test_compute_tract_urbanicity_lookup_drops_non_urban_uatyp(tmp_path: Path) -> None:
    """Polygons with unknown UATYP10 should be ignored, not counted as urban."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    tract_gdf = gpd.GeoDataFrame(
        {
            "GEOID": ["10003010100"],
            "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        },
        crs="EPSG:4326",
    )
    # UATYP10 value 'X' is unknown — methodology says only 'U' and 'C' count.
    urban_gdf = gpd.GeoDataFrame(
        {
            "UATYP10": ["X"],
            "geometry": [Polygon([(-1, -1), (2, -1), (2, 2), (-1, 2)])],
        },
        crs="EPSG:4326",
    )
    lookup = _compute_tract_urbanicity_lookup(tract_gdf, urban_gdf, [])
    assert lookup["10003010100"] == "nonurban"


# ---------------------------------------------------------------------------
# Methodology v0.3.1 — LILA xlsx Urban column urbanicity (closes v0.3.0
# over-permissive sjoin caveat). Reads USDA's authoritative per-tract
# classification directly from the workbook instead of reconstructing it
# via a UAC10 spatial join.
# ---------------------------------------------------------------------------


def test_load_lila_urban_lookup_classifies_urban_tracts(tmp_path: Path) -> None:
    """Urban=1 → 'urban'; Urban=0 → 'nonurban'; Urban=None → omitted."""
    pytest.importorskip("openpyxl")
    xlsx = _write_lila_xlsx(
        tmp_path / "usda-lila-raw.xlsx",
        [
            {"CensusTract": "10003010100", "Urban": 1, "LILATracts_1And10": 0},
            {"CensusTract": "10001040100", "Urban": 0, "LILATracts_1And10": 1},
            # Urban column blank — record present but classification missing.
            {"CensusTract": "10005030100", "LILATracts_1And10": 1},
        ],
    )
    manifest = Manifest(etl_version="test")
    notes: list[str] = []
    lookup = _load_lila_urban_lookup_from_xlsx(xlsx, manifest, notes)
    assert lookup == {
        "10003010100": "urban",
        "10001040100": "nonurban",
    }
    # The xlsx is registered in the manifest when the lookup succeeds —
    # the LILA file is a load-bearing input even when the inline geojson
    # build doesn't run.
    assert "usda-lila-xlsx" in manifest.sources
    # Diagnostic note reports the urban share.
    assert any("1/2" in n and "urban" in n for n in notes)


def test_load_lila_urban_lookup_skips_non_de_rows(tmp_path: Path) -> None:
    """The FIPS-prefix '10' filter inherited from _read_lila_xlsx still applies."""
    pytest.importorskip("openpyxl")
    xlsx = _write_lila_xlsx(
        tmp_path / "usda-lila-raw.xlsx",
        [
            {"CensusTract": "10003010100", "Urban": 1},
            # Alabama row — must not appear in the DE lookup.
            {"CensusTract": "01001020100", "Urban": 1},
        ],
    )
    manifest = Manifest(etl_version="test")
    lookup = _load_lila_urban_lookup_from_xlsx(xlsx, manifest, [])
    assert set(lookup) == {"10003010100"}


def test_load_lila_urban_lookup_returns_empty_when_no_urban_column(tmp_path: Path) -> None:
    """Workbook without an Urban column → empty dict + diagnostic note."""
    pytest.importorskip("openpyxl")
    openpyxl = pytest.importorskip("openpyxl")

    # Write a minimal workbook by hand that lacks the Urban column entirely
    # (the standard _write_lila_xlsx fixture always includes it).
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Food Access Research Atlas"
    ws.append(["CensusTract", "LILATracts_1And10", "PovertyRate"])
    ws.append(["10003010100", 1, 18.0])
    xlsx = tmp_path / "no-urban-col.xlsx"
    wb.save(xlsx)

    manifest = Manifest(etl_version="test")
    notes: list[str] = []
    lookup = _load_lila_urban_lookup_from_xlsx(xlsx, manifest, notes)
    assert lookup == {}
    # Without a successful classification, the source is NOT recorded in
    # the manifest — the file was inspected but contributed nothing.
    assert "usda-lila-xlsx" not in manifest.sources
    assert any("no rows carry an Urban column value" in n for n in notes)


def test_load_lila_urban_lookup_returns_empty_when_xlsx_unreadable(tmp_path: Path) -> None:
    """A corrupt workbook surfaces a diagnostic note and falls through cleanly."""
    pytest.importorskip("openpyxl")
    xlsx = tmp_path / "corrupt.xlsx"
    xlsx.write_bytes(b"not actually a workbook")
    manifest = Manifest(etl_version="test")
    notes: list[str] = []
    lookup = _load_lila_urban_lookup_from_xlsx(xlsx, manifest, notes)
    assert lookup == {}
    assert any("workbook read failed" in n for n in notes)


def test_load_raw_runs_lila_urban_lookup_outside_geo_stack(tmp_path: Path) -> None:
    """The Tier 1 LILA-Urban lookup runs even when geopandas is absent.

    The lookup is plain-tabular (xlsx-only), so it executes outside the
    geo-stack block. Tract construction still requires geopandas; this
    test asserts only on the lookup's manifest + diagnostic side effects.
    """
    pytest.importorskip("openpyxl")
    _write_lila_xlsx(
        tmp_path / "usda-lila-raw.xlsx",
        [
            {"CensusTract": "10003010100", "Urban": 0, "LILATracts_1And10": 0},
            {"CensusTract": "10001040100", "Urban": 1, "LILATracts_1And10": 1},
            {"CensusTract": "10005030100", "Urban": 1, "LILATracts_1And10": 0},
        ],
    )
    result = load_raw_artifacts(tmp_path, DEFAULT_PARAMETERS)
    # Diagnostic note reports the urban share built from the lookup.
    lila_notes = [n for n in result.notes if "usda-lila-urban" in n]
    assert any("2/3" in n and "urban" in n for n in lila_notes), lila_notes
    # The xlsx is recorded in the manifest as a load-bearing urbanicity
    # input — preserves the audit trail even when the inline LILA geojson
    # build doesn't run (no TIGER tracts on disk).
    assert "usda-lila-xlsx" in result.manifest.sources
