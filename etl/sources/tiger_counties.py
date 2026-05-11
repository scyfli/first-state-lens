"""TIGER/Line Census county shapefile puller — Delaware.

Source: https://www2.census.gov/geo/tiger/TIGER{year}/COUNTY/
License: Public domain (US federal government work)
Cadence: Annual (Census publishes a new TIGER vintage each year)
Output: etl/raw/tiger-counties-de.zip (raw Census shapefile bundle)

TIGER's COUNTY shapefile is published as a single national file
(tl_<year>_us_county.zip); there is no per-state county file at the
TIGER endpoint. The geo-stack transform stage clips to STATEFP == '10'
(Delaware) before joining to MMG county-level food-insecurity counts.

Methodology v0.2.0 §Q3 (MMG apportionment): the county-polygon layer
serves as the SOURCE geometry for population-weighted areal
interpolation (county-level counts -> tract-level apportioned values).
Without this layer the apportionment stage cleanly skips; with it
wired, the MMG layer flows into the dashboard.

The vintage default matches the tract + BG pullers (TIGER 2020) — same
geographic reference frame.

Run standalone:
    python -m etl.sources.tiger_counties --out etl/raw/
    python -m etl.sources.tiger_counties --out etl/raw/ --year 2023
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from etl.lib.atomic_io import atomic_write_bytes
from etl.lib.fetch import FetchResult, fetch


DEFAULT_TIGER_YEAR = 2020


def build_url(year: int = DEFAULT_TIGER_YEAR) -> str:
    """Construct the canonical TIGER national-county shapefile URL."""
    return (
        f"https://www2.census.gov/geo/tiger/TIGER{year}/COUNTY/"
        f"tl_{year}_us_county.zip"
    )


OUTPUT_FILENAME = "tiger-counties-us.zip"


def pull(
    out_dir: Path,
    *,
    year: int = DEFAULT_TIGER_YEAR,
    url: str | None = None,
) -> tuple[Path, FetchResult]:
    """Pull the national TIGER county zip to `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved_url = url or build_url(year)
    result = fetch(resolved_url)

    if not result.body.startswith(b"PK"):
        result.warnings.append(
            f"TIGER payload at {resolved_url} does not begin with the zip "
            f"magic bytes — got {result.body[:16]!r}"
        )

    target = out_dir / OUTPUT_FILENAME
    atomic_write_bytes(target, result.body)
    return target, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull national TIGER counties (clipped to DE downstream).")
    parser.add_argument("--out", type=Path, default=Path("etl/raw"))
    parser.add_argument(
        "--year",
        type=int,
        default=DEFAULT_TIGER_YEAR,
        help=f"TIGER vintage year (default: {DEFAULT_TIGER_YEAR})",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Override the TIGER URL (skips --year if set).",
    )
    args = parser.parse_args(argv)

    target, result = pull(args.out, year=args.year, url=args.url)
    print(f"wrote {target} ({result.http_status}; {len(result.body)} bytes)")
    print(f"  vintage:      TIGER {args.year}")
    print(f"  sha256:       {result.sha256}")
    print(f"  last_fetched: {result.last_fetched}")
    if result.warnings:
        print(f"  warnings:     {result.warnings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
