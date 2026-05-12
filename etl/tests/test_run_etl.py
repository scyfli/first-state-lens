"""End-to-end orchestrator test for etl.run_etl.

Feeds toy inputs to `run_pipeline`, asserts that every output file lands
on disk and that datapackage.json is valid Frictionless JSON. Apportionment
is exercised separately in test_apportion (geo-stack-dependent); here we
test the orchestrator wiring without geopandas inputs (apportionment stage
falls through to the placeholder).
"""

from __future__ import annotations

import json
from pathlib import Path

from etl.lib.manifest import Manifest, SourceEntry
from etl.run_etl import PipelineInputs, run_pipeline
from etl.transforms.geocode import GeocoderPair, GranteeInput
from etl.transforms.merge_food_resources import FoodResource
from etl.transforms.sb254_effective import BlockGroup, TractInput, URBANICITY_URBAN

# These are the orchestrator's expected output filenames.
EXPECTED_FILES = {
    "dgi-grants.csv",
    "dgi-grants-geocoded.geojson",
    "snap-retailers.geojson",
    "sb254-effective-tracts.geojson",
    "food-insecurity-tracts.geojson",
    "usda-lila-tracts.geojson",
    "senate-district-2.geojson",
    "dart-routes.geojson",
    "acs-tract-demographics.csv",
    "mhc-tract-health.csv",
    "data-quality-flags.csv",
    "etl-parameters.json",
    "manifest.json",
    "datapackage.json",
}


def _toy_manifest() -> Manifest:
    m = Manifest(etl_version="0.1.0", cycle_5_status="pending")
    m.add_source(
        "usda-lila",
        SourceEntry(
            url="https://example.test/lila",
            last_fetched="2026-05-11T00:00:00Z",
            http_status=200,
            sha256="d" * 64,
            raw_path="etl/raw/usda-lila.geojson",
            size_bytes=10,
            warnings=[],
        ),
    )
    return m


def _toy_parameters() -> dict:
    return {
        "sb254_population_threshold": 0.5,
        "sb254_urban_distance_mi": 0.5,
        "sb254_nonurban_distance_mi": 10.0,
        "low_income_poverty_threshold": 0.20,
        "low_income_mfi_threshold": 0.80,
        "geocoder_tie_break_distance_m": 200,
    }


def _fake_census_hit(address: str):
    from etl.lib.geocode import GeocodeResult

    return GeocodeResult(
        provider="census",
        address=address,
        found=True,
        lat=39.7400,
        lon=-75.5500,
        tract_geoid="10003000100",
        county_fips="003",
        state_fips="10",
        matched_address=address.upper(),
        raw={},
        cache_hit=False,
        fetched_at="2026-05-11T00:00:00Z",
    )


def _fake_nominatim_hit(address: str):
    from etl.lib.geocode import GeocodeResult

    return GeocodeResult(
        provider="nominatim",
        address=address,
        found=True,
        lat=39.7401,  # ~11m off Census -> high confidence
        lon=-75.5500,
        tract_geoid=None,
        county_fips=None,
        state_fips=None,
        matched_address=address,
        raw={"results": []},
        cache_hit=False,
        fetched_at="2026-05-11T00:00:00Z",
    )


def _toy_inputs() -> PipelineInputs:
    grantees = [
        GranteeInput(
            cycle=3,
            grantee="Acme Corner Store",
            amount_usd=50000.0,
            category="corner-store",
            storefront_address="123 N Market St, Wilmington, DE 19801",
            zip_code="19801",
            awarded_date="2025-08-01",
        ),
        GranteeInput(
            cycle=5,
            grantee="(pending publication)",
            amount_usd=700000.0,
            category="other",
            storefront_address=None,
        ),
    ]
    food_resources = [
        FoodResource(
            source="usda-snap",
            name="SNAP retailer near downtown",
            lat=39.7398,
            lon=-75.5505,
            category="supermarket",
            address="N Market St",
        ),
        FoodResource(
            source="de-ag-farmers-markets",
            name="Riverfront Market",
            lat=39.7420,
            lon=-75.5470,
            category="farmers-market",
        ),
    ]
    tracts = [
        TractInput(
            tract_geoid="10003000100",
            urbanicity=URBANICITY_URBAN,
            poverty_rate=0.28,
            mfi=55000,
            block_groups=(
                BlockGroup(
                    bg_geoid="100030001001",
                    centroid_lat=39.7400,
                    centroid_lon=-75.5500,
                    population=1000,
                ),
            ),
        ),
    ]
    geocoders = GeocoderPair(
        census_fn=_fake_census_hit,
        nominatim_fn=_fake_nominatim_hit,
    )
    return PipelineInputs(
        grantees=grantees,
        food_resources_raw=food_resources,
        tracts=tracts,
        state_mfi_median=80000.0,
        parameters=_toy_parameters(),
        manifest=_toy_manifest(),
        geocoders=geocoders,
    )


# ---------------------------------------------------------------------------
# Orchestrator end-to-end
# ---------------------------------------------------------------------------


def test_run_pipeline_writes_every_expected_file(tmp_path: Path):
    inputs = _toy_inputs()
    result = run_pipeline(inputs, tmp_path)
    on_disk = {p.name for p in tmp_path.iterdir() if p.is_file()}
    missing = EXPECTED_FILES - on_disk
    assert not missing, f"missing files: {missing}"


def test_run_pipeline_datapackage_is_valid_json(tmp_path: Path):
    inputs = _toy_inputs()
    run_pipeline(inputs, tmp_path)
    payload = json.loads((tmp_path / "datapackage.json").read_text(encoding="utf-8"))
    assert payload["name"] == "first-state-lens-dgi-food-access"
    # Every resource should now be present on disk.
    resource_names_present = {r["name"]: r["present"] for r in payload["resources"]}
    assert all(resource_names_present.values()), resource_names_present


def test_run_pipeline_dgi_grants_csv_has_both_real_and_pending_rows(tmp_path: Path):
    inputs = _toy_inputs()
    run_pipeline(inputs, tmp_path)
    text = (tmp_path / "dgi-grants.csv").read_text(encoding="utf-8")
    # Header + 2 data rows
    rows = [r for r in text.splitlines() if r]
    assert len(rows) == 3
    assert "Acme Corner Store" in text
    assert "pending publication" in text


def test_run_pipeline_geocoded_geojson_excludes_pending_disbursement(tmp_path: Path):
    inputs = _toy_inputs()
    run_pipeline(inputs, tmp_path)
    payload = json.loads((tmp_path / "dgi-grants-geocoded.geojson").read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
    grantees = [f["properties"]["grantee"] for f in payload["features"]]
    assert "Acme Corner Store" in grantees
    assert "(pending publication)" not in grantees


def test_run_pipeline_merges_food_resources_with_dgi_grantees(tmp_path: Path):
    inputs = _toy_inputs()
    run_pipeline(inputs, tmp_path)
    payload = json.loads((tmp_path / "snap-retailers.geojson").read_text(encoding="utf-8"))
    names = [f["properties"]["name"] for f in payload["features"]]
    # SNAP retailer + Acme Corner Store + Riverfront Market; SNAP and Acme
    # are within ~60m, but names don't share enough tokens (Jaccard < 0.5)
    # — so all three should land as separate features.
    assert "Acme Corner Store" in names
    assert "Riverfront Market" in names
    assert "SNAP retailer near downtown" in names


def test_run_pipeline_sb254_tract_classification_runs(tmp_path: Path):
    inputs = _toy_inputs()
    run_pipeline(inputs, tmp_path)
    payload = json.loads((tmp_path / "sb254-effective-tracts.geojson").read_text(encoding="utf-8"))
    assert len(payload["features"]) == 1
    props = payload["features"][0]["properties"]
    assert props["tract_geoid"] == "10003000100"
    # The SNAP retailer + farmers market + the geocoded Acme grantee should
    # all be within 0.5mi of the BG centroid -> not underserved.
    assert props["underserved_share"] == 0.0
    assert props["sb254_effective"] is False


def test_run_pipeline_skips_apportionment_when_geo_inputs_missing(tmp_path: Path):
    inputs = _toy_inputs()
    result = run_pipeline(inputs, tmp_path)
    assert result.apportionment_ran is False
    payload = json.loads((tmp_path / "food-insecurity-tracts.geojson").read_text(encoding="utf-8"))
    assert payload["features"] == []
    assert "MMG apportionment skipped" in payload.get("note", "")


class _FakeGdfMissingColumns:
    """Minimal fake of a GeoDataFrame for the apportionment column-check gate.

    Surfaced after S+5: the tiger_counties puller populates `mmg_counties_gdf`
    with bare TIGER county geometry (`GEOID`, `STATEFP`, etc.), but the
    `food_insecure_count` column is meant to be joined from the MMG CSV.
    When the MMG CSV is missing (carried open question), the join doesn't
    happen and the apportion stage used to raise KeyError. The gate added
    in this commit returns False with a clear note instead.
    """

    columns = ["GEOID", "STATEFP", "COUNTYFP", "geometry"]


def test_run_pipeline_skips_apportionment_when_mmg_csv_not_joined(tmp_path: Path):
    """S+5 regression: TIGER counties present but MMG CSV missing → skip cleanly."""
    inputs = _toy_inputs()
    # Populate all three required geo inputs so we get past the None-check,
    # but mmg_counties_gdf lacks the FIPS + food_insecure_count columns
    # because the MMG CSV merge never happened.
    inputs.mmg_counties_gdf = _FakeGdfMissingColumns()
    inputs.target_tracts_gdf = _FakeGdfMissingColumns()
    inputs.weights_bg_gdf = _FakeGdfMissingColumns()

    result = run_pipeline(inputs, tmp_path)
    assert result.apportionment_ran is False
    payload = json.loads((tmp_path / "food-insecurity-tracts.geojson").read_text(encoding="utf-8"))
    assert payload["features"] == []
    assert "MMG apportionment skipped" in payload.get("note", "")
    assert "FIPS" in payload["note"]
    assert "food_insecure_count" in payload["note"]


def test_run_pipeline_passthrough_uses_provided_content(tmp_path: Path):
    inputs = _toy_inputs()
    inputs.lila_geojson = b'{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"X":1},"geometry":null}]}'
    run_pipeline(inputs, tmp_path)
    payload = json.loads((tmp_path / "usda-lila-tracts.geojson").read_text(encoding="utf-8"))
    assert payload["features"][0]["properties"]["X"] == 1


def test_run_pipeline_writes_manifest_with_cycle_5_status(tmp_path: Path):
    inputs = _toy_inputs()
    run_pipeline(inputs, tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cycle_5_status"] == "pending"
    assert manifest["etl_version"] == "0.1.0"
    assert "usda-lila" in manifest["sources"]


def test_run_pipeline_parameters_dump_includes_methodology_version(tmp_path: Path):
    inputs = _toy_inputs()
    run_pipeline(inputs, tmp_path)
    payload = json.loads((tmp_path / "etl-parameters.json").read_text(encoding="utf-8"))
    # Default in run_pipeline() MUST track the vault methodology version
    # (05-Methodology/DGI-Food-Access-KPI-Definitions.md frontmatter).
    # Bump this assertion in tandem with every methodology version change.
    assert payload["methodology_version"] == "0.3.2"
    assert payload["cycle_5_status"] == "pending"
    assert payload["sb254_urban_distance_mi"] == 0.5


def test_run_pipeline_result_summary(tmp_path: Path):
    inputs = _toy_inputs()
    result = run_pipeline(inputs, tmp_path)
    assert result.geocoded_count == 2  # 1 real + 1 pending
    assert result.food_resources_merged_count >= 2
    assert result.cycle_5_status == "pending"
    assert result.apportionment_ran is False


def test_run_pipeline_applies_manual_reviews_when_yaml_present(tmp_path: Path):
    inputs = _toy_inputs()
    reviews_yaml = tmp_path / "manual-reviews.yaml"
    reviews_yaml.write_text(
        "reviews:\n"
        "  - grantee: \"Acme Corner Store\"\n"
        "    cycle: 3\n"
        "    confirmed_tract_geoid: \"10003099999\"\n"
        "    reviewed_by: \"Test Reviewer\"\n"
        "    storefront_address: \"123 N Market St\"\n",
        encoding="utf-8",
    )
    inputs.manual_reviews_path = reviews_yaml
    run_pipeline(inputs, tmp_path)
    text = (tmp_path / "dgi-grants.csv").read_text(encoding="utf-8")
    # The override tract should now appear for the Acme row.
    assert "10003099999" in text
