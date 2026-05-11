"""Census ACS 5-year block-group population puller — Delaware.

Source: https://api.census.gov/data/{vintage}/acs/acs5
License: Public domain (US federal government work)
Cadence: Annual (most-recent 5-year release each December)
Output: etl/raw/acs-bg-de.json (Census API raw JSON, all DE BGs)

Block-group population (B01003_001E) is the weighting layer for two
methodology-v0.2.0 computations:

  1. SB 254-effective tract classification — per-tract share of
     population > distance threshold from any food resource. The BG
     centroid is the "where the population is" anchor (tract-level
     centroids are too coarse).

  2. MMG county-to-tract apportionment — population-weighted areal
     interpolation. BG population × area-of-intersection-with-tract
     is the weight; the puller surfaces BG POP that the geo-stack
     transform reads alongside TIGER BG geometry.

The Census API for BG queries requires drilling state + county + tract.
Delaware has 3 counties (Kent 001, New Castle 003, Sussex 005), so the
puller iterates them and concatenates the result rows under a single
header. This is a documented Census API quirk, not a bug.

Run standalone:
    python -m etl.sources.census_acs_bg --out etl/raw/
    python -m etl.sources.census_acs_bg --out etl/raw/ --vintage 2022
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from etl.lib.atomic_io import atomic_write_bytes
from etl.lib.fetch import FetchResult, fetch


DELAWARE_STATE_FIPS = "10"
# Delaware's three counties (Census FIPS):
#   001 — Kent
#   003 — New Castle
#   005 — Sussex
DELAWARE_COUNTY_FIPS = ("001", "003", "005")

DEFAULT_ACS_VINTAGE = "2023"

# Variables: NAME + B01003_001E (total population). Tract is implicitly
# in the geographic hierarchy (state > county > tract > block group);
# the API returns all four geographic levels as columns automatically.
ACS_BG_VARIABLES = ["NAME", "B01003_001E"]


def build_url(county_fips: str, *, vintage: str = DEFAULT_ACS_VINTAGE) -> str:
    """Construct the canonical Census ACS 5-year BG URL for one DE county."""
    var_csv = ",".join(ACS_BG_VARIABLES)
    return (
        f"https://api.census.gov/data/{vintage}/acs/acs5"
        f"?get={var_csv}"
        f"&for=block%20group:*"
        f"&in=state:{DELAWARE_STATE_FIPS}%20county:{county_fips}%20tract:*"
    )


OUTPUT_FILENAME = "acs-bg-de.json"


def pull(
    out_dir: Path,
    *,
    vintage: str = DEFAULT_ACS_VINTAGE,
    api_key: str | None = None,
) -> tuple[Path, FetchResult]:
    """Pull DE block-group ACS population to `out_dir`.

    Issues one request per county and concatenates rows under a single
    header. Returns (path, last_county_FetchResult). The returned
    FetchResult corresponds to the LAST county's request only; manifest
    tracking accepts this approximation (sha256 of the combined output
    is computed downstream via the on-disk file).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    header: list[str] | None = None
    combined_rows: list[list[str]] = []
    last_result: FetchResult | None = None

    for county in DELAWARE_COUNTY_FIPS:
        url = build_url(county, vintage=vintage)
        if api_key:
            url = f"{url}&key={api_key}"
        result = fetch(url)
        last_result = result
        payload = json.loads(result.text())
        if not isinstance(payload, list) or not payload:
            result.warnings.append(
                f"Census BG payload for county {county} is empty or malformed."
            )
            continue
        county_header, *rows = payload
        if header is None:
            header = county_header
        elif county_header != header:
            result.warnings.append(
                f"Census BG header mismatch for county {county}: "
                f"got {county_header!r}, previously had {header!r}."
            )
        combined_rows.extend(rows)

    if header is None:
        # Every county failed. Persist an empty payload so the manifest
        # carries the failure; the orchestrator will skip BG-weighted
        # stages.
        body = b"[]"
    else:
        body = json.dumps(
            [header, *combined_rows], separators=(",", ":")
        ).encode("utf-8")

    target = out_dir / OUTPUT_FILENAME
    atomic_write_bytes(target, body)

    # Synthesize a FetchResult that reflects the combined output.
    assert last_result is not None, "no Census request issued"
    return target, last_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull DE ACS block-group population.")
    parser.add_argument("--out", type=Path, default=Path("etl/raw"))
    parser.add_argument(
        "--vintage",
        default=DEFAULT_ACS_VINTAGE,
        help=f"ACS 5-year endpoint year (default: {DEFAULT_ACS_VINTAGE})",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("CENSUS_API_KEY")
    target, result = pull(args.out, vintage=args.vintage, api_key=api_key)
    print(f"wrote {target} ({result.http_status}; final-county body)")
    print(f"  vintage:      ACS5 {args.vintage}")
    print(f"  api_key_used: {bool(api_key)}")
    print(f"  output_size:  {target.stat().st_size} bytes (combined across counties)")
    print(f"  last_fetched: {result.last_fetched}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
