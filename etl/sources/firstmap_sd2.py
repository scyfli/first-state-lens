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


# DE FirstMap "Delaware Senate Districts 2022" Feature Service. The 2022 plan
# is the active redistricting in effect at methodology v0.2.0 close.
# Service ID is documented in parameters.yaml if it needs to be overridden.
DEFAULT_SD2_QUERY_URL = (
    "https://services1.arcgis.com/PlW5JOTYJBLn5Bvc/arcgis/rest/services/"
    "Delaware_Senate_Districts_2022/FeatureServer/0/query"
    "?where=DISTRICT%3D2"
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
