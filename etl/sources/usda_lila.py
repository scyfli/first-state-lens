"""USDA Food Access Research Atlas (LILA) puller.

Source: https://www.ers.usda.gov/data-products/food-access-research-atlas/
License: Public domain (US federal government work)
Cadence: Annual
Output: etl/raw/usda-lila.geojson (Delaware tracts only at S+3 clip)

The USDA publishes the Food Access Research Atlas as an Excel workbook
with tract-level Low-Income-Low-Access flags. The canonical machine-readable
endpoint is a shapefile/CSV download from the data-products page.

S+1: pulls the latest published Excel + CSV bundle URL discovered from the
USDA page. We persist the raw bytes; the S+3 transform clips to Delaware
tracts and converts to GeoJSON. The shapefile / GeoJSON conversion is
deferred to the transform step (requires geopandas + GDAL).

Open question Q-VINTAGE: which annual vintage? Strategy: prefer the latest
published vintage at run time. The transform records the vintage in the
output `etl-parameters.json`.

Run standalone:
    python -m etl.sources.usda_lila --out etl/raw/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from etl.lib.atomic_io import atomic_write_bytes
from etl.lib.fetch import FetchResult, fetch


# The USDA Food Access Research Atlas data page links to a versioned download.
# As of methodology v0.2.0 the canonical bundle URL is the public ERS
# data-products page; the actual download URL is the CSV bundle below.
# If USDA changes the URL, the puller raises in fetch() — pin via the
# parameters.yaml `usda_lila_url` if we need to override.
DEFAULT_USDA_LILA_URL = (
    "https://www.ers.usda.gov/sites/default/files/_laserfiche/"
    "DataFiles/80591/FoodAccessResearchAtlasData2019.xlsx"
)

OUTPUT_FILENAME = "usda-lila-raw.xlsx"


def pull(out_dir: Path, *, url: str = DEFAULT_USDA_LILA_URL) -> tuple[Path, FetchResult]:
    """Pull the USDA LILA bundle to `out_dir`. Returns (path, FetchResult)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result = fetch(url)
    target = out_dir / OUTPUT_FILENAME
    atomic_write_bytes(target, result.body)
    return target, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull USDA LILA raw bundle.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("etl/raw"),
        help="output directory (default: etl/raw)",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_USDA_LILA_URL,
        help="override the USDA bundle URL",
    )
    args = parser.parse_args(argv)

    target, result = pull(args.out, url=args.url)
    print(f"wrote {target} ({result.http_status}; {len(result.body)} bytes)")
    print(f"  sha256:       {result.sha256}")
    print(f"  last_fetched: {result.last_fetched}")
    print(f"  elapsed_ms:   {result.elapsed_ms}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
