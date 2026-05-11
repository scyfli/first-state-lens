"""Map the Meal Gap (Feeding America) county-level CSV puller.

Source: https://www.feedingamerica.org/research/map-the-meal-gap/
License: Feeding America EULA — RESEARCH USE; attribution required.
         See: https://www.feedingamerica.org/research/map-the-meal-gap/about
         The county-level public file is the "free" tier; tract-level
         requires partnership. We use the county file as input and
         apportion to tracts via population weighting in S+3 (per
         methodology v0.2.0 §"Layer specifications").
Cadence: Annual (May release)
Output: etl/raw/mmg-county.csv

The MMG public county file URL is the open question Q-MMG-URL from the
design brief. Feeding America hosts a downloadable Excel + CSV pair.
The puller uses a configurable URL because the year-to-year hosting
pattern varies (sometimes a versioned URL, sometimes a stable filename
with the latest content).

Open question Q-EULA-COMPLIANCE: the EULA is research-use; attribution
required. The dashboard footer + methodology page already credit Feeding
America by name; the datapackage.json carries Feeding America in the
`sources[]` block. No additional EULA work needed at v1.

Run standalone:
    python -m etl.sources.mmg_food_insecurity --out etl/raw/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from etl.lib.atomic_io import atomic_write_bytes
from etl.lib.fetch import FetchResult, fetch
from etl.lib.validate import validate_csv


# Canonical-URL open question — CARRIED THROUGH SESSION-18.
#
# The placeholder URL below points at a Tableau viz, which returns the
# Tableau HTML loader page on a direct HTTP GET (not CSV). The S+4
# live-etl run (session-18) confirmed this empirically — the puller's
# validate_csv() correctly rejected the HTML response with header
# starting `<!DOCTYPE html>...`. So the placeholder URL was always
# wrong; this is not URL drift but an unresolved canonical source.
#
# Resolution paths (carried alongside DSB canonical URL):
#   (a) Coordinate with Feeding America for a stable direct download URL.
#       Their public site is form-gated; the data is research-use under
#       attribution. Email feedingamerica.org research contact.
#   (b) Pull the file manually once per release and check it into a
#       separate "vendor data" repo we control, then point the puller
#       at that mirror via parameters.yaml: mmg_food_insecurity_url.
#   (c) Rely on the apportionment-stage skip when MMG fails; the
#       dashboard renders without the food-insecurity-tracts layer
#       (acceptable until (a) or (b) lands).
#
# Until then, the live-etl logs MMG as FAILED and the pipeline emits
# an empty food-insecurity-tracts.geojson with a manifest note.
DEFAULT_MMG_URL = (
    "https://public.tableau.com/views/MaptheMealGap2024/"
    "OverallCountyandCongressionalDistrict.csv"
)

OUTPUT_FILENAME = "mmg-county.csv"


# Columns the S+3 apportionment transform requires. The CSV header naming
# changes year to year; validate_csv() only checks the column NAMES, so
# this list documents the expected names. If MMG renames a column the
# validator surfaces it immediately.
EXPECTED_COLUMNS = (
    "FIPS",  # Census county FIPS — the join key for apportionment
    "Year",  # Data year (most recent MMG release year)
)


def pull(
    out_dir: Path, *, url: str = DEFAULT_MMG_URL
) -> tuple[Path, FetchResult]:
    """Pull MMG county-level CSV to `out_dir`. Returns (path, FetchResult)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result = fetch(url)
    # Validate it parses as CSV with the columns we expect. If MMG changes
    # the schema or URL, this fires early.
    row_count = validate_csv(result.body, required_columns=EXPECTED_COLUMNS)
    result.warnings.append(f"mmg row_count={row_count}")
    target = out_dir / OUTPUT_FILENAME
    atomic_write_bytes(target, result.body)
    return target, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull MMG county-level CSV.")
    parser.add_argument("--out", type=Path, default=Path("etl/raw"))
    parser.add_argument("--url", default=DEFAULT_MMG_URL)
    args = parser.parse_args(argv)

    target, result = pull(args.out, url=args.url)
    print(f"wrote {target} ({result.http_status}; {len(result.body)} bytes)")
    print(f"  sha256:       {result.sha256}")
    print(f"  last_fetched: {result.last_fetched}")
    if result.warnings:
        for w in result.warnings:
            print(f"  warning:      {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
