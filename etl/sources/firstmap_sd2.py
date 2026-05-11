"""FirstMap Senate District 2 boundary puller.

Source: https://de-firstmap-delaware.hub.arcgis.com/
License: Open data (Delaware open data portal)
Cadence: Per redistricting (2022 plan is current)
Output: etl/raw/firstmap-sd2.geojson

FirstMap exposes Senate Districts as an ArcGIS Feature Service. The
`/query` endpoint with `f=geojson&where=DISTRICT=2` returns SD2 as a single
GeoJSON FeatureCollection. We persist verbatim — no transformation here;
the S+3 transform may simplify geometry for web delivery.

The FirstMap layer ID is the open question Q-LAYER-ID-STABILITY from the
design brief. If the layer URL changes, the puller raises in fetch();
the recovery path is to look up the current layer at the hub URL above
and pin the new ID via parameters.yaml.

Run standalone:
    python -m etl.sources.firstmap_sd2 --out etl/raw/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from etl.lib.atomic_io import atomic_write_bytes
from etl.lib.fetch import FetchResult, fetch
from etl.lib.validate import validate_geojson


# DE FirstMap "DE Political Boundaries" Feature Service, layer 1 (Senate
# Districts). The post-2020-census redistricting plan is the active
# layer (reapportionment effective for 2032 general election per the
# layer metadata). DISTRICT is a string field so the query value is
# single-quoted ('2', not 2).
#
# Drift history:
#   - S+1 (session-14): `services1.arcgis.com/PlW5JOTYJBLn5Bvc/.../Delaware_Senate_Districts_2022/FeatureServer/0/query?where=DISTRICT%3D2`
#   - session-18 patch: that service returns 400 Invalid URL on the live
#     run — the service path was retired in favor of the consolidated
#     `enterprise.firstmap.delaware.gov` Political Boundaries
#     FeatureServer. The new URL queries layer 1 ("Senate Districts")
#     with the now-string-typed DISTRICT field.
DEFAULT_SD2_QUERY_URL = (
    "https://enterprise.firstmap.delaware.gov/arcgis/rest/services/"
    "Boundaries/DE_Political_Boundaries/FeatureServer/1/query"
    "?where=DISTRICT%3D%272%27"
    "&outFields=*"
    "&outSR=4326"
    "&f=geojson"
)

OUTPUT_FILENAME = "firstmap-sd2.geojson"


def pull(
    out_dir: Path, *, url: str = DEFAULT_SD2_QUERY_URL
) -> tuple[Path, FetchResult]:
    """Pull FirstMap SD2 GeoJSON to `out_dir`. Returns (path, FetchResult)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result = fetch(url)
    # Validate the payload IS a GeoJSON FeatureCollection before persisting.
    validate_geojson(result.body, require_features=True)
    target = out_dir / OUTPUT_FILENAME
    atomic_write_bytes(target, result.body)
    return target, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull FirstMap SD2 GeoJSON.")
    parser.add_argument("--out", type=Path, default=Path("etl/raw"))
    parser.add_argument("--url", default=DEFAULT_SD2_QUERY_URL)
    args = parser.parse_args(argv)

    target, result = pull(args.out, url=args.url)
    print(f"wrote {target} ({result.http_status}; {len(result.body)} bytes)")
    print(f"  sha256:       {result.sha256}")
    print(f"  last_fetched: {result.last_fetched}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
