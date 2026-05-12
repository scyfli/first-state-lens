"""Census ACS state-level Median Family Income (B19113) puller — Delaware statewide.

Source: https://api.census.gov/data/{vintage}/acs/acs5
License: Public domain (US federal government work)
Cadence: Annual (most-recent 5-year release each December)
Output: etl/raw/acs-state-mfi-de.json (Census API raw JSON, single estimate)

Methodology v0.3.2 (patch — live state_mfi_median): the SB 254-effective
low-income test compares each tract's MFI to 0.8 x state median family
income. v0.3.1 and prior sourced the state median from a frozen
parameter (90,116 USD; ACS 2019-2023). v0.3.2 sources it live from the
ACS5 B19113 estimate at the state level, matching the same vintage the
tract-level ACS pull uses.

The Census API is keyless for low-volume queries; we support either
path (CENSUS_API_KEY env var if set; keyless otherwise).

Run standalone:
    python -m etl.sources.census_acs_state --out etl/raw/
    python -m etl.sources.census_acs_state --out etl/raw/ --vintage 2023
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from etl.lib.atomic_io import atomic_write_bytes
from etl.lib.fetch import FetchResult, fetch


DELAWARE_STATE_FIPS = "10"

DEFAULT_ACS_VINTAGE = "2023"

STATE_MFI_VARIABLE = "B19113_001E"

OUTPUT_FILENAME = "acs-state-mfi-de.json"


def build_url(vintage: str = DEFAULT_ACS_VINTAGE) -> str:
    """Construct the canonical Census ACS 5-year state-level B19113 URL for DE."""
    return (
        f"https://api.census.gov/data/{vintage}/acs/acs5"
        f"?get=NAME,{STATE_MFI_VARIABLE}"
        f"&for=state:{DELAWARE_STATE_FIPS}"
    )


def pull(
    out_dir: Path,
    *,
    vintage: str = DEFAULT_ACS_VINTAGE,
    api_key: str | None = None,
) -> tuple[Path, FetchResult]:
    """Pull DE state-level ACS MFI to `out_dir`. Returns (path, FetchResult)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    url = build_url(vintage)
    if api_key:
        url = f"{url}&key={api_key}"
    result = fetch(url)
    target = out_dir / OUTPUT_FILENAME
    atomic_write_bytes(target, result.body)
    return target, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull DE state-level ACS Median Family Income (B19113)."
    )
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
    print(f"  variable:     {STATE_MFI_VARIABLE}")
    print(f"  api_key_used: {bool(api_key)}")
    print(f"  sha256:       {result.sha256}")
    print(f"  last_fetched: {result.last_fetched}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
