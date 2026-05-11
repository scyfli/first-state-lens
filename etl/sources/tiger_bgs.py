"""TIGER/Line Census block-group shapefile puller — Delaware.

Source: https://www2.census.gov/geo/tiger/TIGER{year}/BG/
License: Public domain (US federal government work)
Cadence: Annual
Output: etl/raw/tiger-bgs-de.zip (raw Census shapefile bundle)

Block groups are one level finer than tracts (a tract typically contains
1-9 block groups). Methodology v0.2.0 §Q6 uses BG centroids + population
to compute population-weighted "share of tract pop > distance from any
food resource" for SB 254-effective classification. The BG geometry is
also the weighting layer for the MMG county-to-tract apportionment
(per the design brief's tidycensus::interpolate_pw equivalence).

Vintage matches the tract puller (TIGER 2020 default) — same geographic
reference frame.

Run standalone:
    python -m etl.sources.tiger_bgs --out etl/raw/
    python -m etl.sources.tiger_bgs --out etl/raw/ --year 2023
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from etl.lib.atomic_io import atomic_write_bytes
from etl.lib.fetch import FetchResult, fetch


DELAWARE_STATE_FIPS = "10"
DEFAULT_TIGER_YEAR = 2020


def build_url(year: int = DEFAULT_TIGER_YEAR) -> str:
    """Construct the canonical TIGER block-group shapefile URL for Delaware."""
    return (
        f"https://www2.census.gov/geo/tiger/TIGER{year}/BG/"
        f"tl_{year}_{DELAWARE_STATE_FIPS}_bg.zip"
    )


OUTPUT_FILENAME = "tiger-bgs-de.zip"


def pull(
    out_dir: Path,
    *,
    year: int = DEFAULT_TIGER_YEAR,
    url: str | None = None,
) -> tuple[Path, FetchResult]:
    """Pull the Delaware TIGER block-group zip to `out_dir`."""
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
    parser = argparse.ArgumentParser(description="Pull Delaware TIGER block groups.")
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
