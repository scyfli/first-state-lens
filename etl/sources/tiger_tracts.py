"""TIGER/Line Census tract shapefile puller — Delaware.

Source: https://www2.census.gov/geo/tiger/TIGER{year}/TRACT/
License: Public domain (US federal government work)
Cadence: Annual (Census publishes a new TIGER vintage each year)
Output: etl/raw/tiger-tracts-de.zip (raw Census shapefile bundle)

Methodology v0.2.0 anchors the tract geometry layer at TIGER 2020 (the
post-2020-census reference frame; tract IDs reshuffled vs 2010). The
`tiger_year` knob in parameters.yaml pins the vintage at run time; the
fallback below matches that pin.

The downloaded artifact is the raw zip; the geo-stack transform stage
(`etl/transforms/apportion.py`) opens it via geopandas when present.
This puller is pure HTTP — no GDAL needed to fetch.

State FIPS 10 = Delaware. TIGER URLs are stable since 2010; if Census
moves the path, the puller raises in fetch() and the override is
`--url`.

Run standalone:
    python -m etl.sources.tiger_tracts --out etl/raw/
    python -m etl.sources.tiger_tracts --out etl/raw/ --year 2023
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from etl.lib.atomic_io import atomic_write_bytes
from etl.lib.fetch import FetchResult, fetch


# State FIPS code for Delaware. Hard-coded; Delaware is the scope of FSL.
DELAWARE_STATE_FIPS = "10"

# Default TIGER vintage. Methodology v0.2.0 locks this to 2020 (the
# post-2020-census reference frame). parameters.yaml is the source of
# truth at run time; the constant here is the standalone-CLI fallback.
DEFAULT_TIGER_YEAR = 2020


def build_url(year: int = DEFAULT_TIGER_YEAR) -> str:
    """Construct the canonical TIGER tract shapefile URL for Delaware."""
    return (
        f"https://www2.census.gov/geo/tiger/TIGER{year}/TRACT/"
        f"tl_{year}_{DELAWARE_STATE_FIPS}_tract.zip"
    )


OUTPUT_FILENAME = "tiger-tracts-de.zip"


def pull(
    out_dir: Path,
    *,
    year: int = DEFAULT_TIGER_YEAR,
    url: str | None = None,
) -> tuple[Path, FetchResult]:
    """Pull the Delaware TIGER tract zip to `out_dir`. Returns (path, FetchResult)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved_url = url or build_url(year)
    result = fetch(resolved_url)

    # TIGER ships zips. A non-zip payload (e.g., redirect to an HTML error
    # page) is a soft warning rather than a raise — the run still records
    # the failure in the manifest, and the geo-stack stage will reject the
    # file when it tries to open it.
    if not result.body.startswith(b"PK"):
        result.warnings.append(
            f"TIGER payload at {resolved_url} does not begin with the zip "
            f"magic bytes — got {result.body[:16]!r}"
        )

    target = out_dir / OUTPUT_FILENAME
    atomic_write_bytes(target, result.body)
    return target, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull Delaware TIGER tracts.")
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
