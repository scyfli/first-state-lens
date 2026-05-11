"""TIGER/Line Census Urban Areas shapefile puller (national).

Source: https://www2.census.gov/geo/tiger/TIGER{year}/UAC/
License: Public domain (US federal government work)
Cadence: Decennial (the UAC layer is republished alongside each decennial
         Census). The 2010 Urban Areas (UAC10) classification is the one
         USDA LILA uses for its urban/rural distinction.
Output: etl/raw/tiger-uac-us.zip (raw Census shapefile bundle)

Methodology v0.3.0 (UAC urbanicity refinement): the SB 254-effective stage
needs to know which tracts are *urban* vs *nonurban* per the LILA
definition (½-mile vs 10-mile food-resource distance thresholds). At
methodology v0.2.x this was a county-level proxy — New Castle (FIPS
'10003') → urban; Kent + Sussex → nonurban — documented as a caveat
because Delaware has only one major urban area, so a county proxy is
reasonable but coarse.

v0.3.0 replaces the proxy with the canonical Census UAC10 cross-walk:
a tract is `urban` if its geometry intersects any 2010 Urban Area or
Urban Cluster polygon (UATYP10 = 'U' for Urbanized Area; 'C' for Urban
Cluster — USDA LILA counts both as "urban").

The UAC10 file is the same file the USDA Food Access Research Atlas
uses for its urban/rural determination, so by aligning here the
methodology becomes byte-identical to LILA's own urban/rural test —
not just "in the spirit of" LILA.

Run standalone:
    python -m etl.sources.census_uac --out etl/raw/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from etl.lib.atomic_io import atomic_write_bytes
from etl.lib.fetch import FetchResult, fetch


DEFAULT_TIGER_YEAR = 2020


def build_url(year: int = DEFAULT_TIGER_YEAR) -> str:
    """Construct the canonical TIGER national-UAC10 shapefile URL.

    TIGER hosts both UAC10 (2010 urban areas, the LILA-aligned vintage)
    and UAC20 (2020 urban areas, the post-Census-2020 classification).
    We pin UAC10 here so the methodology is byte-aligned with USDA LILA.
    """
    return (
        f"https://www2.census.gov/geo/tiger/TIGER{year}/UAC/"
        f"tl_{year}_us_uac10.zip"
    )


OUTPUT_FILENAME = "tiger-uac-us.zip"


def pull(
    out_dir: Path,
    *,
    year: int = DEFAULT_TIGER_YEAR,
    url: str | None = None,
) -> tuple[Path, FetchResult]:
    """Pull the national TIGER UAC10 zip to `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved_url = url or build_url(year)
    result = fetch(resolved_url)

    if not result.body.startswith(b"PK"):
        result.warnings.append(
            f"TIGER UAC payload at {resolved_url} does not begin with "
            f"the zip magic bytes — got {result.body[:16]!r}"
        )

    target = out_dir / OUTPUT_FILENAME
    atomic_write_bytes(target, result.body)
    return target, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull national TIGER Urban Areas (UAC10) shapefile."
    )
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
    print(f"  vintage:      TIGER {args.year} UAC10")
    print(f"  sha256:       {result.sha256}")
    print(f"  last_fetched: {result.last_fetched}")
    if result.warnings:
        print(f"  warnings:     {result.warnings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
