"""Frictionless datapackage.json writer.

The datapackage is the authoritative public contract for the DGI Food
Access bulk-data layer. Every published artifact (CSV, GeoJSON, JSON
parameters dump) appears here with last_fetched, sha256, size_bytes,
and (for tabular CSVs) a schema reference.

Design choices:
  - Schemas live as separate JSON files under `etl/outputs/schema/` and
    are referenced relatively from datapackage.json. Inlining would make
    the datapackage gigantic and hard to diff.
  - GeoJSON resources omit a tabular schema and document fields in their
    `description`. Frictionless tabular-data-schema doesn't apply.
  - The `etl_parameters` block is a top-level addition (Frictionless
    allows arbitrary properties). It carries the parameters.yaml values
    that drove this run, so a consumer can verify the rules in effect.
  - The `sources` block is built from manifest's FetchResult metadata.
  - sha256 + size are computed from on-disk files at write time. The
    caller is responsible for atomically committing files before this
    runs (rename-after-write discipline).

Output:
  dgi-food-access/data/datapackage.json
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
from pathlib import Path
from typing import Optional

from etl.lib.atomic_io import atomic_write_text
from etl.lib.manifest import Manifest


DATAPACKAGE_NAME = "first-state-lens-dgi-food-access"
DATAPACKAGE_TITLE = "First State Lens — DGI Food Access Bulk Data"
DATAPACKAGE_DESCRIPTION = (
    "Tract-level food-access dataset for Delaware's DGI program tracking. "
    "Covers DGI grant deployments (Cycles 1-5), Map the Meal Gap food "
    "insecurity apportioned to tracts via population-weighted areal "
    "interpolation, USDA LILA tracts, computed SB 254-effective tracts, "
    "the merged food-resource universe (SNAP retailers + farmers markets + "
    "DGI grantees), and supporting ACS demographics + DPH health overlays. "
    "Methodology v0.2.0 (definition-locked)."
)
DEFAULT_LICENSE = {
    "name": "CC-BY-4.0",
    "title": "Creative Commons Attribution 4.0",
    "path": "https://creativecommons.org/licenses/by/4.0/",
}


@dataclasses.dataclass
class ResourceSpec:
    """A single resource going into datapackage.json.

    `path` is the resource's path RELATIVE TO the datapackage file (i.e.,
    inside dgi-food-access/data/). `format` is "csv" or "geojson" or
    "json". `schema_path` (optional) is the relative path to a
    Frictionless table-schema JSON file; only tabular CSVs use this.
    `description` documents the fields when schema_path is absent.
    """

    name: str
    path: str
    format: str
    description: str
    schema_path: Optional[str] = None
    title: Optional[str] = None


# ---------------------------------------------------------------------------
# Canonical resource list (methodology v0.2.0)
# ---------------------------------------------------------------------------


CANONICAL_RESOURCES: tuple[ResourceSpec, ...] = (
    ResourceSpec(
        name="dgi-grants",
        path="dgi-grants.csv",
        format="csv",
        title="DGI grant ledger (Cycles 1-5)",
        description=(
            "One row per DGI grant award. See schema/dgi-grants.json. Cycle 5 "
            "rows may carry a synthetic placeholder when DSB has not yet "
            "published awardees (methodology v0.2.0 Q1)."
        ),
        schema_path="../../etl/outputs/schema/dgi-grants.json",
    ),
    ResourceSpec(
        name="dgi-grants-geocoded",
        path="dgi-grants-geocoded.geojson",
        format="geojson",
        title="DGI grantees as geocoded points",
        description=(
            "GeoJSON Point features for every DGI grantee whose storefront "
            "address has been geocoded. Properties mirror the tabular "
            "dgi-grants ledger: cycle, grantee, amount_usd, category, "
            "tract_geoid, geocoding_confidence, wilmington_manual_reviewed. "
            "Pending-disbursement rows are excluded (no geometry)."
        ),
    ),
    ResourceSpec(
        name="usda-lila-tracts",
        path="usda-lila-tracts.geojson",
        format="geojson",
        title="USDA LILA food-desert tracts (DE)",
        description=(
            "Pass-through of the USDA Food Access Research Atlas tract-level "
            "shapefile, clipped to Delaware. LILA flag fields preserved from "
            "USDA: LILATracts_1And10, LILATracts_Vehicle, lapophalfshare, etc. "
            "Methodology v0.2.0 uses this as the federal-definition layer."
        ),
    ),
    ResourceSpec(
        name="sb254-effective-tracts",
        path="sb254-effective-tracts.geojson",
        format="geojson",
        title="SB 254-effective tracts (state-statute interpretation)",
        description=(
            "Computed tract layer per methodology v0.2.0 Q6. Properties: "
            "tract_geoid, sb254_effective (bool), urbanicity, "
            "distance_threshold_mi, population_total, population_underserved, "
            "underserved_share, low_income (bool), low_income_reason, "
            "poverty_rate, mfi, mfi_ratio_to_state. See etl_parameters block "
            "for thresholds in effect."
        ),
    ),
    ResourceSpec(
        name="food-insecurity-tracts",
        path="food-insecurity-tracts.geojson",
        format="geojson",
        title="Food insecurity apportioned to tracts (MMG)",
        description=(
            "Map the Meal Gap county-level food-insecurity count, apportioned "
            "to Delaware Census tracts via population-weighted areal "
            "interpolation per methodology Q3. Properties: tract_geoid, "
            "food_insecurity_count_apportioned, food_insecurity_rate "
            "(intensive, county-level — repeated on every tract in the same "
            "county)."
        ),
    ),
    ResourceSpec(
        name="snap-retailers",
        path="snap-retailers.geojson",
        format="geojson",
        title="Merged food-resource universe",
        description=(
            "Deduplicated point set of SNAP retailers + DE farmers markets + "
            "DCFFP grantees + DGI grantees (methodology Q6 'food resource' "
            "set). Properties: name, sources (list of contributing pullers), "
            "categories, address, contributor_count. Dedupe within 30m + name "
            "similarity per etl.transforms.merge_food_resources."
        ),
    ),
    ResourceSpec(
        name="senate-district-2",
        path="senate-district-2.geojson",
        format="geojson",
        title="Senate District 2 boundary (FirstMap 2022 plan)",
        description=(
            "Single-feature polygon of Sen. Brown's district. Extracted from "
            "the FirstMap statewide senate-districts dataset (2022 redistricting "
            "plan, valid through 2032)."
        ),
    ),
    ResourceSpec(
        name="dart-routes",
        path="dart-routes.geojson",
        format="geojson",
        title="DART First State transit routes",
        description=(
            "LineString features derived from DART GTFS shapes.txt + "
            "routes.txt. Properties: route_id, route_short_name, "
            "route_long_name, route_type."
        ),
    ),
    ResourceSpec(
        name="acs-tract-demographics",
        path="acs-tract-demographics.csv",
        format="csv",
        title="ACS tract-level demographics (DE)",
        description=(
            "ACS 5-year tract-level demographics. See "
            "schema/acs-tract-demographics.json. Used downstream to compute "
            "the SB 254 low-income tract flag."
        ),
        schema_path="../../etl/outputs/schema/acs-tract-demographics.json",
    ),
    ResourceSpec(
        name="mhc-tract-health",
        path="mhc-tract-health.csv",
        format="csv",
        title="DPH My Healthy Community health overlay",
        description=(
            "Tract-level health indicators (food insecurity, diabetes, "
            "obesity, SNAP household share). See schema/mhc-tract-health.json."
        ),
        schema_path="../../etl/outputs/schema/mhc-tract-health.json",
    ),
    ResourceSpec(
        name="data-quality-flags",
        path="data-quality-flags.csv",
        format="csv",
        title="Data quality flags",
        description=(
            "Audit-trail rows for every flagged record. See "
            "schema/data-quality-flags.json."
        ),
        schema_path="../../etl/outputs/schema/data-quality-flags.json",
    ),
    ResourceSpec(
        name="etl-parameters",
        path="etl-parameters.json",
        format="json",
        title="ETL parameters in effect for this build",
        description=(
            "Mirror of etl/parameters.yaml at run time, plus cycle_5_status "
            "and methodology_version. Carries the rules that produced the "
            "rest of the package."
        ),
    ),
    ResourceSpec(
        name="manifest",
        path="manifest.json",
        format="json",
        title="Manifest (lightweight freshness cousin)",
        description=(
            "Per-source last_fetched + sha256, plus cycle_5_status. Lighter "
            "than datapackage.json for fast freshness checks."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_datapackage(
    *,
    output_dir: Path,
    version: str,
    manifest: Manifest,
    parameters: dict,
    resources: tuple[ResourceSpec, ...] = CANONICAL_RESOURCES,
    methodology_version: str = "0.2.0",
    require_present: bool = True,
) -> dict:
    """Compose the datapackage.json dict.

    `output_dir` is where the resource files live on disk (e.g.
    `dgi-food-access/data/`). Sha256 + size are computed for each
    resource that's present on disk. Resources missing from disk are
    included with `present: false` when `require_present=False`, or
    raise FileNotFoundError when `require_present=True`.
    """
    resource_entries: list[dict] = []
    for spec in resources:
        path = output_dir / spec.path
        entry: dict = {
            "name": spec.name,
            "title": spec.title or spec.name,
            "path": spec.path,
            "format": spec.format,
            "description": spec.description,
        }
        if spec.schema_path is not None:
            entry["schema"] = spec.schema_path
        if path.exists():
            data = path.read_bytes()
            entry["sha256"] = hashlib.sha256(data).hexdigest()
            entry["bytes"] = len(data)
            entry["present"] = True
        else:
            if require_present:
                raise FileNotFoundError(
                    f"datapackage resource {spec.name!r} missing on disk: {path}"
                )
            entry["sha256"] = None
            entry["bytes"] = 0
            entry["present"] = False
        resource_entries.append(entry)

    sources_block = _build_sources_block(manifest)

    return {
        "name": DATAPACKAGE_NAME,
        "title": DATAPACKAGE_TITLE,
        "version": version,
        "description": DATAPACKAGE_DESCRIPTION,
        "created": _utc_now_iso(),
        "licenses": [DEFAULT_LICENSE],
        "methodology_version": methodology_version,
        "cycle_5_status": manifest.cycle_5_status,
        "etl_parameters": _serialize_parameters(parameters),
        "sources": sources_block,
        "resources": resource_entries,
    }


def write_datapackage(
    output_dir: Path,
    payload: dict,
    *,
    filename: str = "datapackage.json",
) -> Path:
    """Serialize + atomic-write the datapackage to disk."""
    target = output_dir / filename
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return atomic_write_text(target, text)


def _build_sources_block(manifest: Manifest) -> list[dict]:
    """One entry per upstream source, derived from the manifest."""
    entries: list[dict] = []
    for name, src in manifest.sources.items():
        entries.append(
            {
                "name": name,
                "path": src.url,
                "last_fetched": src.last_fetched,
                "http_status": src.http_status,
                "sha256": src.sha256,
                "raw_path": src.raw_path,
                "warnings": list(src.warnings),
            }
        )
    return entries


def _serialize_parameters(parameters: dict) -> dict:
    """Best-effort serialization: drop anything non-JSON-serializable."""
    out: dict = {}
    for k, v in parameters.items():
        try:
            json.dumps(v)
        except (TypeError, ValueError):
            continue
        out[k] = v
    return out


def _utc_now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
