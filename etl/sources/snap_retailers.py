"""USDA SNAP authorized retailer puller — Delaware.

Source: USDA FNS SNAP Retailer Location ArcGIS Hub
        https://usda-snap-retailers-usda-fns.hub.arcgis.com/
License: Public domain (US federal government work). Attribution-friendly.
Cadence: Weekly refresh per USDA FNS.
Output: etl/raw/snap-retailers-de.geojson

The SNAP retailer dataset is one of three feeds into the methodology
v0.2.0 §Q6 "food resource" universe (SNAP + farmers markets + DGI
grantees). The merge stage (`etl/transforms/merge_food_resources.py`)
dedupes by 30m haversine + token-Jaccard name similarity.

This puller queries the ArcGIS FeatureServer with a Delaware filter
and pages through the result set (the server's default transfer
limit is ~2000 features). The output is a single concatenated GeoJSON
FeatureCollection.

Run standalone:
    python -m etl.sources.snap_retailers --out etl/raw/
    python -m etl.sources.snap_retailers --out etl/raw/ --state CA  # if useful for cross-state diagnostics
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path

from etl.lib.atomic_io import atomic_write_bytes
from etl.lib.fetch import FetchResult, fetch


DEFAULT_STATE_ABBR = "DE"

# Fields the methodology v0.2.0 cares about. Keeping the projection
# tight keeps the GeoJSON small.
SNAP_OUT_FIELDS = (
    "Record_ID",
    "Store_Name",
    "Store_Street_Address",
    "City",
    "State",
    "Zip_Code",
    "County",
    "Store_Type",
    "Latitude",
    "Longitude",
)

# Canonical ArcGIS FeatureServer (FNS-managed). If USDA rotates this,
# override via --url at the CLI.
DEFAULT_SNAP_FS = (
    "https://services1.arcgis.com/RLQu0rK7h4kbsBq5/ArcGIS/rest/"
    "services/snap_retailer_location_data/FeatureServer/0/query"
)

OUTPUT_FILENAME = "snap-retailers-de.geojson"

# Per-request transfer cap. ArcGIS Server's `maxRecordCount` is usually
# 2000; we stay just under to avoid edge-case truncation.
PAGE_SIZE = 2000

# Safety cap: bail if a state's retailers exceed this (DE will be well
# under 10k; this catches an infinite-pagination loop).
MAX_FEATURES = 50_000


def build_query_url(
    *,
    fs_url: str = DEFAULT_SNAP_FS,
    state_abbr: str = DEFAULT_STATE_ABBR,
    result_offset: int = 0,
    result_record_count: int = PAGE_SIZE,
) -> str:
    """Construct one paginated query URL for the SNAP retailers FeatureServer."""
    out_fields = ",".join(SNAP_OUT_FIELDS)
    where = f"State='{state_abbr}'"
    params = {
        "where": where,
        "outFields": out_fields,
        "outSR": "4326",
        "f": "geojson",
        "resultOffset": str(result_offset),
        "resultRecordCount": str(result_record_count),
    }
    return f"{fs_url}?{urllib.parse.urlencode(params)}"


def pull(
    out_dir: Path,
    *,
    state_abbr: str = DEFAULT_STATE_ABBR,
    fs_url: str = DEFAULT_SNAP_FS,
    page_size: int = PAGE_SIZE,
    max_features: int = MAX_FEATURES,
) -> tuple[Path, FetchResult]:
    """Pull SNAP retailers for `state_abbr` to `out_dir`.

    Returns (path, FetchResult) where the FetchResult corresponds to
    the LAST paginated request. Total feature count is recorded in
    warnings.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    all_features: list[dict] = []
    crs_block: dict | None = None
    last_result: FetchResult | None = None
    offset = 0

    while offset < max_features:
        url = build_query_url(
            fs_url=fs_url,
            state_abbr=state_abbr,
            result_offset=offset,
            result_record_count=page_size,
        )
        result = fetch(url)
        last_result = result
        try:
            payload = json.loads(result.text())
        except json.JSONDecodeError as exc:
            result.warnings.append(
                f"SNAP page at offset {offset} returned non-JSON: {exc}"
            )
            break

        features = payload.get("features") or []
        if crs_block is None and "crs" in payload:
            crs_block = payload["crs"]
        all_features.extend(features)

        # Server tells us when there's more via `exceededTransferLimit`.
        exceeded = bool(payload.get("properties", {}).get("exceededTransferLimit")) or bool(
            payload.get("exceededTransferLimit")
        )
        if not exceeded or not features:
            break
        offset += page_size

    if last_result is None:
        raise RuntimeError("snap_retailers.pull issued zero requests")

    out_payload: dict = {
        "type": "FeatureCollection",
        "features": all_features,
    }
    if crs_block is not None:
        out_payload["crs"] = crs_block

    body = json.dumps(out_payload).encode("utf-8")
    target = out_dir / OUTPUT_FILENAME
    atomic_write_bytes(target, body)

    last_result.warnings.append(f"snap-retailers feature_count={len(all_features)}")
    return target, last_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull SNAP retailers GeoJSON.")
    parser.add_argument("--out", type=Path, default=Path("etl/raw"))
    parser.add_argument("--state", default=DEFAULT_STATE_ABBR)
    parser.add_argument("--url", default=DEFAULT_SNAP_FS, help="Override the FeatureServer URL.")
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE)
    args = parser.parse_args(argv)

    target, result = pull(
        args.out,
        state_abbr=args.state,
        fs_url=args.url,
        page_size=args.page_size,
    )
    size = target.stat().st_size
    print(f"wrote {target} ({result.http_status}; final-page size={len(result.body)} bytes; output {size} bytes)")
    print(f"  state:        {args.state}")
    print(f"  last_fetched: {result.last_fetched}")
    for w in result.warnings:
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
