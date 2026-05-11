"""Census American Community Survey (ACS) 5-year puller — Delaware tracts.

Source: https://api.census.gov/data/{vintage}/acs/acs5
License: Public domain (US federal government work)
Cadence: Annual (most-recent 5-year release each December)
Output: etl/raw/acs-tract-de.json (Census API raw JSON)

The Census API is keyless for low-volume queries; registering for an API
key is encouraged for higher rate limits and is the recommended posture
for CI. We support either path: if CENSUS_API_KEY is set in the environment,
we include it; otherwise we issue keyless requests.

Methodology v0.2.0 needs (per the SB 254-effective tract computation):
  - Population (B01003_001E)
  - Median family income (B19113_001E)
  - Poverty rate denominator + numerator (B17001_001E, B17001_002E)
  - Race / ethnicity (B03002_*) for demographic overlay
  - Median household income (B19013_001E)

S+1: pulls the variable bundle for all tracts in Delaware (state FIPS 10).
S+3: joins this to the TIGER shapefile and computes the SB 254-effective
flag per the methodology rules.

Run standalone:
    python -m etl.sources.census_acs --out etl/raw/
    python -m etl.sources.census_acs --out etl/raw/ --vintage 2022
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from etl.lib.atomic_io import atomic_write_bytes
from etl.lib.fetch import FetchResult, fetch


# State FIPS code for Delaware. Hard-coded; Delaware is the scope of FSL.
DELAWARE_STATE_FIPS = "10"

# Default vintage. parameters.yaml is the source of truth at run time;
# this constant is just the fallback for the standalone CLI.
DEFAULT_ACS_VINTAGE = "2023"

# Variables needed for methodology v0.2.0. The 'NAME' variable is the
# human-readable tract label Census returns; useful for sanity checks.
ACS_VARIABLES = [
    "NAME",
    "B01003_001E",  # Total population
    "B19013_001E",  # Median household income
    "B19113_001E",  # Median family income
    "B17001_001E",  # Poverty status denominator
    "B17001_002E",  # Poverty status numerator (in poverty)
    "B03002_001E",  # Race/ethnicity total
    "B03002_003E",  # Not Hispanic, White alone
    "B03002_004E",  # Not Hispanic, Black alone
    "B03002_006E",  # Not Hispanic, Asian alone
    "B03002_012E",  # Hispanic or Latino
]


def build_url(vintage: str = DEFAULT_ACS_VINTAGE) -> str:
    """Construct the canonical Census ACS 5-year tract-level URL for DE."""
    var_csv = ",".join(ACS_VARIABLES)
    return (
        f"https://api.census.gov/data/{vintage}/acs/acs5"
        f"?get={var_csv}"
        f"&for=tract:*"
        f"&in=state:{DELAWARE_STATE_FIPS}"
    )


OUTPUT_FILENAME = "acs-tract-de.json"


def pull(
    out_dir: Path,
    *,
    vintage: str = DEFAULT_ACS_VINTAGE,
    api_key: str | None = None,
) -> tuple[Path, FetchResult]:
    """Pull DE tract-level ACS to `out_dir`. Returns (path, FetchResult)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    url = build_url(vintage)
    if api_key:
        url = f"{url}&key={api_key}"
    result = fetch(url)
    target = out_dir / OUTPUT_FILENAME
    atomic_write_bytes(target, result.body)
    return target, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull DE ACS tract-level data.")
    parser.add_argument("--out", type=Path, default=Path("etl/raw"))
    parser.add_argument(
        "--vintage",
        default=DEFAULT_ACS_VINTAGE,
        help=f"ACS 5-year endpoint year (default: {DEFAULT_ACS_VINTAGE})",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("CENSUS_API_KEY")
    target, result = pull(args.out, vintage=args.vintage, api_key=api_key)
    print(f"wrote {target} ({result.http_status}; {len(result.body)} bytes)")
    print(f"  vintage:      ACS5 {args.vintage}")
    print(f"  api_key_used: {bool(api_key)}")
    print(f"  sha256:       {result.sha256}")
    print(f"  last_fetched: {result.last_fetched}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
