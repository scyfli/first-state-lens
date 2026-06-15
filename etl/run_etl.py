"""Top-level DGI Food Access ETL orchestrator.

Composes the puller -> transform -> writer pipeline end-to-end and
writes a complete Frictionless datapackage to `dgi-food-access/data/`.

Design:
  - Most of the orchestrator is a pure function (`run_pipeline`) that
    takes pre-loaded inputs and writes outputs. This keeps integration
    testing trivial: feed it toy fixtures, assert on outputs.
  - The CLI wrapper (`main`) is the future-S+4 wire-in point. It loads
    raw artifacts from `etl/raw/` (when present), invokes the
    orchestrator, and writes outputs. At S+3 the CLI is functional but
    deliberately lenient: missing raw artifacts produce empty
    pass-through outputs, not hard errors. That posture flips to strict
    at S+4 when the methodology page goes `publish: true`.

End-to-end stages (per design brief §"Data flow"):
  1. geocode_grantees     (DGI grantees -> geocoded points + flags)
  2. apply_manual_reviews (manual-reviews.yaml second pass)
  3. merge_food_resources (SNAP + farmers + DGI -> dedupe -> universe)
  4. apportion_mmg        (county counts -> tract-apportioned)
  5. compute_sb254        (per-tract distance + low-income rule)
  6. pass-through layers  (LILA, SD2, DART, ACS, MHC)
  7. write outputs        (CSV + GeoJSON + JSON parameters dump)
  8. write datapackage    (datapackage.json + manifest.json)
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

from etl import __version__ as ETL_VERSION
from etl.lib.atomic_io import atomic_write_bytes, atomic_write_text
from etl.lib.manifest import Manifest
from etl.outputs.write_datapackage import (
    build_datapackage,
    write_datapackage,
)
from etl.transforms.apply_manual_reviews import (
    apply_manual_reviews,
    load_manual_reviews,
)
from etl.transforms.geocode import (
    GeocoderPair,
    GranteeInput,
    geocode_grantees,
)
from etl.transforms.merge_food_resources import (
    FoodResource,
    merge_food_resources,
)
from etl.transforms.sb254_effective import (
    FoodResourcePoint,
    TractInput,
    classify_tracts,
)


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class PipelineInputs:
    """Everything the orchestrator needs to produce a full datapackage.

    Anything optional may be None; the orchestrator emits an empty
    placeholder file for that resource. This is the S+3 posture; S+4
    flips it to strict.
    """

    grantees: list[GranteeInput]
    food_resources_raw: list[FoodResource]
    tracts: list[TractInput]
    state_mfi_median: float
    parameters: dict
    manifest: Manifest

    # Optional inputs the orchestrator passes through:
    lila_geojson: Optional[bytes] = None
    sd2_geojson: Optional[bytes] = None
    dart_routes_geojson: Optional[bytes] = None
    acs_demographics_csv: Optional[bytes] = None
    mhc_csv: Optional[bytes] = None

    # Geo-stack-dependent: MMG apportionment inputs. If any is None, the
    # orchestrator writes an empty food-insecurity-tracts.geojson and
    # notes it in data-quality-flags.csv. At S+3 these are typically
    # None on Windows local dev (no GDAL) and populated in CI.
    mmg_counties_gdf: Optional[Any] = None       # GeoDataFrame
    target_tracts_gdf: Optional[Any] = None      # GeoDataFrame
    weights_bg_gdf: Optional[Any] = None         # GeoDataFrame
    mmg_extensive_variables: tuple[str, ...] = ("food_insecure_count",)
    mmg_source_id_col: str = "FIPS"
    mmg_target_id_col: str = "GEOID"
    mmg_weight_pop_col: str = "POP"

    # Geocoder pair (injectable for tests).
    geocoders: Optional[GeocoderPair] = None

    # Manual reviews YAML path; None = skip the merge.
    manual_reviews_path: Optional[Path] = None


@dataclasses.dataclass
class PipelineResult:
    """Diagnostic summary of one pipeline run."""

    output_dir: Path
    files_written: list[Path]
    geocoded_count: int
    food_resources_merged_count: int
    sb254_effective_tract_count: int
    data_quality_flag_count: int
    cycle_5_status: str
    apportionment_ran: bool


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_csv(target: Path, header: list[str], rows: list[list]) -> Path:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for r in rows:
        writer.writerow(r)
    return atomic_write_text(target, buf.getvalue())


def _write_geojson(target: Path, payload: dict) -> Path:
    return atomic_write_text(target, json.dumps(payload, indent=2) + "\n")


def _write_empty_feature_collection(target: Path, note: str) -> Path:
    return _write_geojson(
        target,
        {
            "type": "FeatureCollection",
            "features": [],
            "note": note,
        },
    )


# ---------------------------------------------------------------------------
# Stage 1+2 — grantees → geocoded → manual-reviews second pass
# ---------------------------------------------------------------------------


def _stage_geocode(
    inputs: PipelineInputs,
) -> tuple[list, list]:
    """Return (geocoded_grantees, data_quality_flags)."""
    geocoders = inputs.geocoders or GeocoderPair()
    geocoded, flags = geocode_grantees(
        inputs.grantees,
        geocoders=geocoders,
        tie_break_distance_m=float(
            inputs.parameters.get("geocoder_tie_break_distance_m", 200)
        ),
    )

    if inputs.manual_reviews_path and inputs.manual_reviews_path.exists():
        reviews = load_manual_reviews(inputs.manual_reviews_path)
        applied = apply_manual_reviews(geocoded, reviews)
        geocoded = applied.records
        for unmatched in applied.unmatched_reviews:
            flags.append(
                _ManualReviewFlag(
                    cycle=unmatched.cycle,
                    grantee=unmatched.grantee,
                    flag="other",
                    note=(
                        "Manual review present but no matching grantee in "
                        "geocoded set — typo or renamed grantee."
                    ),
                )
            )

    return geocoded, flags


@dataclasses.dataclass
class _ManualReviewFlag:
    cycle: int
    grantee: str
    flag: str
    note: str


# ---------------------------------------------------------------------------
# Stage 3 — merge food resources, include DGI geocoded grantees
# ---------------------------------------------------------------------------


def _stage_merge_food_resources(
    inputs: PipelineInputs,
    geocoded_grantees: list,
) -> list:
    """Compose the food-resource universe — return list of MergedFoodResource."""
    resources: list[FoodResource] = list(inputs.food_resources_raw)
    for g in geocoded_grantees:
        if g.lat is None or g.lon is None:
            continue
        resources.append(
            FoodResource(
                source="dgi-grantees",
                name=g.grantee,
                lat=g.lat,
                lon=g.lon,
                category=g.category,
                address=g.storefront_address,
                external_id=f"dgi-c{g.cycle}-{g.grantee}",
            )
        )
    return merge_food_resources(resources)


# ---------------------------------------------------------------------------
# Stage 4 — MMG apportionment (geo stack)
# ---------------------------------------------------------------------------


def _stage_apportion_mmg(
    inputs: PipelineInputs,
    output_dir: Path,
) -> tuple[bool, Optional[dict]]:
    """Run apportionment if geo inputs are available. Return (ran, result_geojson)."""
    if (
        inputs.mmg_counties_gdf is None
        or inputs.target_tracts_gdf is None
        or inputs.weights_bg_gdf is None
    ):
        target = output_dir / "food-insecurity-tracts.geojson"
        _write_empty_feature_collection(
            target,
            "MMG apportionment skipped: geo inputs missing at run time.",
        )
        return False, None

    # Defense-in-depth: confirm the source GDF carries the required join + value
    # columns before invoking the interpolator. S+5 added a TIGER-counties
    # puller that populates `mmg_counties_gdf` with bare county geometry, but
    # the `food_insecure_count` column comes from the MMG food-insecurity CSV
    # merge — which is gated on the MMG canonical URL (carried open question).
    # When the MMG CSV is missing/invalid the column never gets joined; skip
    # cleanly here instead of letting pandas raise KeyError mid-apportionment.
    required_cols = {inputs.mmg_source_id_col, *inputs.mmg_extensive_variables}
    source_cols = set(inputs.mmg_counties_gdf.columns)
    missing_cols = required_cols - source_cols
    if missing_cols:
        target = output_dir / "food-insecurity-tracts.geojson"
        _write_empty_feature_collection(
            target,
            (
                "MMG apportionment skipped: counties GDF missing required "
                f"columns {sorted(missing_cols)} (MMG food-insecurity CSV "
                "was not joined — see carried open question)."
            ),
        )
        return False, None

    # Local import to keep apportion module loading until we know we need it.
    from etl.transforms.apportion import population_weighted_interpolate

    result = population_weighted_interpolate(
        source=inputs.mmg_counties_gdf,
        target=inputs.target_tracts_gdf,
        weights=inputs.weights_bg_gdf,
        source_id_col=inputs.mmg_source_id_col,
        target_id_col=inputs.mmg_target_id_col,
        weight_pop_col=inputs.mmg_weight_pop_col,
        extensive_variables=inputs.mmg_extensive_variables,
    )
    target = output_dir / "food-insecurity-tracts.geojson"
    # Serialize the GeoDataFrame to GeoJSON via geopandas.to_json
    payload = json.loads(result.target.to_json())
    payload["apportionment_coverage"] = result.coverage
    payload["unmatched_sources"] = result.unmatched_sources
    _write_geojson(target, payload)
    return True, payload


# ---------------------------------------------------------------------------
# Stage 5 — SB 254-effective tract classification
# ---------------------------------------------------------------------------


def _stage_sb254(
    inputs: PipelineInputs,
    merged_food_resources: list,
) -> list:
    """Classify each tract per methodology Q6."""
    food_points = [
        FoodResourcePoint(lat=r.lat, lon=r.lon) for r in merged_food_resources
    ]
    return classify_tracts(
        inputs.tracts,
        food_points,
        state_mfi_median=inputs.state_mfi_median,
        population_threshold=float(
            inputs.parameters.get("sb254_population_threshold", 0.5)
        ),
        urban_distance_mi=float(
            inputs.parameters.get("sb254_urban_distance_mi", 0.5)
        ),
        nonurban_distance_mi=float(
            inputs.parameters.get("sb254_nonurban_distance_mi", 10.0)
        ),
        poverty_threshold=float(
            inputs.parameters.get("low_income_poverty_threshold", 0.20)
        ),
        mfi_ratio_threshold=float(
            inputs.parameters.get("low_income_mfi_threshold", 0.80)
        ),
    )


# ---------------------------------------------------------------------------
# Stage 7 — write tabular outputs
# ---------------------------------------------------------------------------


DGI_GRANTS_HEADER = [
    "cycle", "grantee", "amount_usd", "awarded_date", "storefront_address",
    "category", "geocoding_confidence", "tract_geoid", "lat", "lon",
    "wilmington_manual_reviewed", "notes",
]


def _write_dgi_grants_csv(output_dir: Path, geocoded: list) -> Path:
    rows = []
    for g in geocoded:
        rows.append(
            [
                g.cycle, g.grantee, g.amount_usd, g.awarded_date or "",
                g.storefront_address or "", g.category,
                g.geocoding_confidence, g.tract_geoid or "",
                g.lat if g.lat is not None else "",
                g.lon if g.lon is not None else "",
                "true" if g.wilmington_manual_reviewed else "false",
                "",
            ]
        )
    return _write_csv(output_dir / "dgi-grants.csv", DGI_GRANTS_HEADER, rows)


def _write_dgi_grants_geocoded_geojson(output_dir: Path, geocoded: list) -> Path:
    features = []
    for g in geocoded:
        if g.lat is None or g.lon is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [g.lon, g.lat],
                },
                "properties": {
                    "cycle": g.cycle,
                    "grantee": g.grantee,
                    "amount_usd": g.amount_usd,
                    "category": g.category,
                    "tract_geoid": g.tract_geoid,
                    "geocoding_confidence": g.geocoding_confidence,
                    "wilmington_manual_reviewed": g.wilmington_manual_reviewed,
                },
            }
        )
    return _write_geojson(
        output_dir / "dgi-grants-geocoded.geojson",
        {"type": "FeatureCollection", "features": features},
    )


def _write_food_resources_geojson(output_dir: Path, merged: list) -> Path:
    features = []
    for m in merged:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [m.lon, m.lat],
                },
                "properties": {
                    "name": m.name,
                    "address": m.address,
                    "categories": m.categories,
                    "sources": m.sources,
                    "external_ids": m.external_ids,
                    "contributor_count": m.contributor_count,
                },
            }
        )
    return _write_geojson(
        output_dir / "snap-retailers.geojson",
        {"type": "FeatureCollection", "features": features},
    )


def _build_tract_geom_lookup(target_tracts_gdf) -> Optional[dict]:
    """Map tract_geoid -> GeoJSON geometry from the TIGER tract GeoDataFrame.

    Without this, _write_sb254_geojson falls back to Point [0,0] for every
    tract (the geometry gap that left all 262 SB 254 tracts at null island).
    TIGER carries the real polygon for every Delaware tract; reproject to
    WGS84 and emit it so the SB 254 layer renders as actual tracts.
    Returns None if the geo stack / gdf is unavailable so the [0,0] fallback
    (diagnostic-only, exercised by offline tests) is preserved.
    """
    if target_tracts_gdf is None:
        return None
    try:
        from shapely.geometry import mapping  # noqa: PLC0415

        gdf = target_tracts_gdf
        geoid_col = next(
            (c for c in ("GEOID", "geoid", "tract_geoid", "GEOID20", "GEOID10") if c in gdf.columns),
            None,
        )
        if geoid_col is None:
            return None
        if gdf.crs is not None and str(gdf.crs).upper() not in ("EPSG:4326", "OGC:CRS84"):
            gdf = gdf.to_crs(4326)
        lookup: dict = {}
        for geoid, geom in zip(gdf[geoid_col].astype(str), gdf.geometry):
            if geom is not None and not geom.is_empty:
                lookup[str(geoid)] = mapping(geom)
        return lookup or None
    except Exception:  # noqa: BLE001 — geometry is best-effort; fall back to [0,0]
        return None


def _write_sb254_geojson(
    output_dir: Path,
    sb254_results: list,
    tracts_lookup_geom: Optional[dict],
) -> Path:
    """Write sb254-effective-tracts.geojson.

    If `tracts_lookup_geom` is provided (dict from tract_geoid to GeoJSON
    geometry), the output is a real FeatureCollection. Otherwise we
    emit Point features at (0,0) — diagnostic-only and never used in
    production where the geo stack is available.
    """
    features = []
    for s in sb254_results:
        geom = None
        if tracts_lookup_geom:
            geom = tracts_lookup_geom.get(s.tract_geoid)
        if geom is None:
            geom = {"type": "Point", "coordinates": [0, 0]}
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "tract_geoid": s.tract_geoid,
                    "sb254_effective": s.sb254_effective,
                    "urbanicity": s.urbanicity,
                    "distance_threshold_mi": s.distance_threshold_mi,
                    "population_total": s.population_total,
                    "population_underserved": s.population_underserved,
                    "underserved_share": s.underserved_share,
                    "low_income": s.low_income,
                    "low_income_reason": s.low_income_reason,
                    "poverty_rate": s.poverty_rate,
                    "mfi": s.mfi,
                    "mfi_ratio_to_state": s.mfi_ratio_to_state,
                },
            }
        )
    return _write_geojson(
        output_dir / "sb254-effective-tracts.geojson",
        {"type": "FeatureCollection", "features": features},
    )


def _write_data_quality_flags(output_dir: Path, flags: list) -> Path:
    rows = [[f.cycle, f.grantee, f.flag, f.note] for f in flags]
    return _write_csv(
        output_dir / "data-quality-flags.csv",
        ["cycle", "grantee", "flag", "note"],
        rows,
    )


def _write_parameters_dump(
    output_dir: Path, parameters: dict, manifest: Manifest, methodology_version: str
) -> Path:
    payload = {
        **{k: v for k, v in parameters.items()},
        "cycle_5_status": manifest.cycle_5_status,
        "methodology_version": methodology_version,
        "etl_version": ETL_VERSION,
    }
    return atomic_write_text(
        output_dir / "etl-parameters.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )


def _write_passthrough(
    output_dir: Path, filename: str, content: Optional[bytes], placeholder_note: str
) -> Path:
    target = output_dir / filename
    if content is not None:
        return atomic_write_bytes(target, content)
    if filename.endswith(".geojson"):
        return _write_empty_feature_collection(target, placeholder_note)
    if filename.endswith(".csv"):
        # Empty CSV with no header (consumers should treat as zero rows).
        return atomic_write_text(target, "")
    return atomic_write_text(target, placeholder_note + "\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_pipeline(
    inputs: PipelineInputs,
    output_dir: Path,
    *,
    methodology_version: str = "0.3.2",
    datapackage_version: str = "0.2.1",
    sb254_tracts_geom_lookup: Optional[dict] = None,
    strict: bool = False,
) -> PipelineResult:
    """Run the full pipeline end-to-end. Writes outputs to `output_dir`.

    `methodology_version` MUST be bumped in tandem with every change
    to `05-Methodology/DGI-Food-Access-KPI-Definitions.md` in the vault
    (the audit-trail source of truth). The CLI does not currently expose
    `--methodology-version`, so the default here is what production
    `etl-parameters.json` stamps. Drift between this default and the
    vault methodology version is the bug pattern surfaced in session-24
    (production stamped `0.2.1` for v0.2.2/v0.3.0/v0.3.1/v0.3.2 runs).

    `datapackage_version` tracks the Frictionless tabular schemas
    independently; it does not need to advance every time the
    methodology rules change.

    When `strict=True` (the CLI default for live runs), the datapackage
    writer raises on any missing output file. Lenient mode (False) is
    the test ergonomics path: missing outputs are flagged but not
    fatal.
    """
    output_dir = _ensure_dir(output_dir)
    files: list[Path] = []

    # Stage 1+2: geocode + manual reviews
    geocoded, flags = _stage_geocode(inputs)

    # Stage 3: merge food resources
    merged_food = _stage_merge_food_resources(inputs, geocoded)

    # Stage 4: apportionment (geo stack)
    apportionment_ran, _ = _stage_apportion_mmg(inputs, output_dir)
    files.append(output_dir / "food-insecurity-tracts.geojson")

    # Stage 5: SB 254-effective classification
    sb254_results = _stage_sb254(inputs, merged_food)

    # Stage 7: tabular outputs
    files.append(_write_dgi_grants_csv(output_dir, geocoded))
    files.append(_write_dgi_grants_geocoded_geojson(output_dir, geocoded))
    files.append(_write_food_resources_geojson(output_dir, merged_food))
    # Build the tract geometry lookup from TIGER polygons when not supplied,
    # so SB 254 tracts render as real polygons instead of Point [0,0].
    geom_lookup = sb254_tracts_geom_lookup
    if geom_lookup is None:
        geom_lookup = _build_tract_geom_lookup(inputs.target_tracts_gdf)
    files.append(_write_sb254_geojson(output_dir, sb254_results, geom_lookup))
    files.append(_write_data_quality_flags(output_dir, flags))
    files.append(
        _write_parameters_dump(output_dir, inputs.parameters, inputs.manifest, methodology_version)
    )

    # Stage 6: pass-through layers
    files.append(_write_passthrough(
        output_dir, "usda-lila-tracts.geojson", inputs.lila_geojson,
        "USDA LILA layer not loaded at run time.",
    ))
    files.append(_write_passthrough(
        output_dir, "senate-district-2.geojson", inputs.sd2_geojson,
        "FirstMap SD2 not loaded at run time.",
    ))
    files.append(_write_passthrough(
        output_dir, "dart-routes.geojson", inputs.dart_routes_geojson,
        "DART GTFS not converted at run time.",
    ))
    files.append(_write_passthrough(
        output_dir, "acs-tract-demographics.csv", inputs.acs_demographics_csv,
        "ACS demographics not loaded at run time.",
    ))
    files.append(_write_passthrough(
        output_dir, "mhc-tract-health.csv", inputs.mhc_csv,
        "DPH MHC overlay not loaded at run time.",
    ))

    # Stage 8: write manifest + datapackage
    manifest_path = inputs.manifest.write(output_dir / "manifest.json")
    files.append(manifest_path)

    payload = build_datapackage(
        output_dir=output_dir,
        version=datapackage_version,
        manifest=inputs.manifest,
        parameters=inputs.parameters,
        methodology_version=methodology_version,
        require_present=strict,
    )
    files.append(write_datapackage(output_dir, payload))

    return PipelineResult(
        output_dir=output_dir,
        files_written=files,
        geocoded_count=len(geocoded),
        food_resources_merged_count=len(merged_food),
        sb254_effective_tract_count=sum(1 for s in sb254_results if s.sb254_effective),
        data_quality_flag_count=len(flags),
        cycle_5_status=inputs.manifest.cycle_5_status,
        apportionment_ran=apportionment_ran,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_parameters(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Live-pull dispatch — fetches every source puller into raw_dir
# ---------------------------------------------------------------------------


def _pull_all_sources(raw_dir: Path, parameters: dict) -> list[str]:
    """Run every source puller; persist raws to raw_dir; return notes."""
    notes: list[str] = []
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Census API key: read once from env and thread into the ACS pullers.
    # WITHOUT this, the orchestrated --pull path calls the ACS pullers with no
    # api_key, so requests go out unauthenticated and Census returns an HTML
    # rate-limit/WAF page at HTTP 200 (not JSON) — silently zeroing every
    # ACS-derived value downstream (low_income, sb254_effective, mfi, poverty).
    # The puller __main__ blocks already read this env var; the orchestrator
    # must do the same or CI runs are unauthenticated regardless of the secret.
    # Kwargs with value None are dropped below, so a missing key falls through
    # to the puller's keyless default.
    census_api_key = os.environ.get("CENSUS_API_KEY")

    # Imports are local so the CLI starts fast and so partial-import
    # failures (e.g., requests missing in a minimal env) don't break
    # offline test runs.
    from etl.sources import (
        census_acs,
        census_acs_bg,
        census_acs_state,
        census_uac,
        dart_gtfs,
        dsb_grants,
        firstmap_sd2,
        mmg_food_insecurity,
        snap_retailers,
        tiger_bgs,
        tiger_counties,
        tiger_tracts,
        usda_farmers_markets,
        usda_lila,
    )

    pullers: list[tuple[str, callable, dict]] = [
        ("firstmap_sd2", firstmap_sd2.pull, {}),
        ("dart_gtfs", dart_gtfs.pull, {}),
        ("census_acs_tracts", census_acs.pull, {"api_key": census_api_key}),
        ("census_acs_bgs", census_acs_bg.pull, {"api_key": census_api_key}),
        ("census_acs_state", census_acs_state.pull,
         {"api_key": census_api_key}),  # methodology v0.3.2
        ("mmg_food_insecurity", mmg_food_insecurity.pull, {}),
        ("usda_lila", usda_lila.pull, {}),
        ("tiger_tracts", tiger_tracts.pull, {}),
        ("tiger_bgs", tiger_bgs.pull, {}),
        ("tiger_counties", tiger_counties.pull, {}),  # S+5
        ("census_uac", census_uac.pull, {}),  # methodology v0.3.0
        ("snap_retailers", snap_retailers.pull, {}),  # S+5
        ("usda_farmers_markets", usda_farmers_markets.pull,  # S+5 (scaffold)
         {"url": parameters.get("usda_farmers_markets_url")}),
        ("dsb_grants", dsb_grants.pull, {"url": parameters.get("dsb_grants_url")}),
    ]

    for name, fn, kwargs in pullers:
        # Drop kwargs whose value is None so the puller defaults apply.
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        try:
            r = fn(raw_dir, **kwargs)
            # Different pullers return tuples of varying arity; the first
            # element is always the persisted path.
            if isinstance(r, tuple):
                path = r[0]
                fetch_result = r[1] if len(r) > 1 else None
            else:
                path = r
                fetch_result = None
            status = fetch_result.http_status if fetch_result else "ok"
            warns = (fetch_result.warnings if fetch_result else [])
            notes.append(f"  - {name}: {path.name} ({status}; {len(warns)} warning(s))")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"  - {name}: FAILED ({type(exc).__name__}: {exc})")

    return notes


# ---------------------------------------------------------------------------
# PipelineInputs assembler — bridges LoadedRaw to the orchestrator
# ---------------------------------------------------------------------------


def assemble_pipeline_inputs(loaded, parameters: dict, manual_reviews_path: Optional[Path]):
    """Build a PipelineInputs from a LoadedRaw + parameters + manual-reviews path."""
    return PipelineInputs(
        grantees=loaded.grantees,
        food_resources_raw=loaded.food_resources_raw,
        tracts=loaded.tracts,
        state_mfi_median=loaded.state_mfi_median,
        parameters=parameters,
        manifest=loaded.manifest,
        lila_geojson=loaded.lila_geojson,
        sd2_geojson=loaded.sd2_geojson,
        dart_routes_geojson=loaded.dart_routes_geojson,
        acs_demographics_csv=loaded.acs_demographics_csv,
        mhc_csv=loaded.mhc_csv,
        mmg_counties_gdf=loaded.mmg_counties_gdf,
        target_tracts_gdf=loaded.target_tracts_gdf,
        weights_bg_gdf=loaded.weights_bg_gdf,
        manual_reviews_path=(
            manual_reviews_path if manual_reviews_path and manual_reviews_path.exists() else None
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the DGI Food Access ETL.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dgi-food-access/data"),
        help="Where to write outputs (default: dgi-food-access/data/)",
    )
    parser.add_argument(
        "--parameters",
        type=Path,
        default=Path("etl/parameters.yaml"),
        help="Path to parameters.yaml (default: etl/parameters.yaml)",
    )
    parser.add_argument(
        "--manual-reviews",
        type=Path,
        default=Path("etl/manual-reviews.yaml"),
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("etl/raw"),
        help="Where raw artifacts live / will be persisted (default: etl/raw/)",
    )
    parser.add_argument(
        "--pull",
        action="store_true",
        help="Run every source puller against the network before composing the pipeline. "
             "Without --pull, only artifacts already in --raw-dir are read.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require every datapackage resource to be present on disk; raise otherwise. "
             "Recommended for live CI runs. Defaults to lenient.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect the raw_dir and print what would be loaded; do not write outputs.",
    )
    parser.add_argument(
        "--methodology-version",
        default=None,
        help="Override the methodology version stamped into outputs. When "
             "omitted, falls through to run_pipeline's signature default. "
             "Exposing this lets the CI workflow be the single source-of-truth "
             "call site, eliminating the stamp-drift class (session-24/25).",
    )
    args = parser.parse_args(argv)

    parameters = load_parameters(args.parameters)
    print(f"Loaded parameters from {args.parameters} ({len(parameters)} keys).")

    if args.pull:
        print(f"Pulling all sources to {args.raw_dir} ...")
        for note in _pull_all_sources(args.raw_dir, parameters):
            print(note)

    # Late import: load_raw imports geopandas behind importorskip but
    # keeps the CLI's startup time low for --dry-run probes.
    from etl.lib.load_raw import load_raw_artifacts

    loaded = load_raw_artifacts(args.raw_dir, parameters)
    print(f"Inspected {args.raw_dir} (geo_stack_available={loaded.geo_stack_available}):")
    for note in loaded.notes:
        print(f"  - {note}")

    if args.dry_run:
        print("--dry-run: no outputs written.")
        return 0

    inputs = assemble_pipeline_inputs(loaded, parameters, args.manual_reviews)

    # Only forward methodology_version when explicitly set, so an unset flag
    # falls through to run_pipeline's signature default rather than overriding
    # it with None.
    pipeline_kwargs: dict = {}
    if args.methodology_version is not None:
        pipeline_kwargs["methodology_version"] = args.methodology_version

    result = run_pipeline(
        inputs,
        output_dir=args.output_dir,
        strict=args.strict,
        **pipeline_kwargs,
    )

    print()
    print(f"Pipeline complete. Outputs in {result.output_dir}/")
    print(f"  geocoded_count:               {result.geocoded_count}")
    print(f"  food_resources_merged_count:  {result.food_resources_merged_count}")
    print(f"  sb254_effective_tract_count:  {result.sb254_effective_tract_count}")
    print(f"  data_quality_flag_count:      {result.data_quality_flag_count}")
    print(f"  cycle_5_status:               {result.cycle_5_status}")
    print(f"  apportionment_ran:            {result.apportionment_ran}")
    print(f"  files_written:                {len(result.files_written)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
