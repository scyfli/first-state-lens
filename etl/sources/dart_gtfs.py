"""DART (Delaware Authority for Regional Transit) GTFS puller.

Source: Delaware open data portal — DART GTFS feed
License: Open data
Cadence: Quarterly (DART republishes the feed on a rolling schedule)
Output: etl/raw/dart-gtfs.zip
        etl/raw/dart-stops.csv     (extracted stops.txt; convenience pre-extract)

A GTFS feed is a zip of CSVs (`stops.txt`, `routes.txt`, `trips.txt`,
`shapes.txt`, etc.). For the food-access dashboard we care primarily about
`stops.txt` (point geometry → tract overlay in S+3) and `shapes.txt`
(route LineStrings → dart-routes.geojson at S+3).

S+1 persists the raw zip and pre-extracts `stops.txt` for downstream
convenience. The full transform (LineString reconstruction from shapes.txt)
lands in S+3.

The canonical URL (Q-DART-CANONICAL from design brief) is verified here.
If DART rotates the URL, the puller raises and the parameters.yaml override
is the fix.

Run standalone:
    python -m etl.sources.dart_gtfs --out etl/raw/
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

from etl.lib.atomic_io import atomic_write_bytes
from etl.lib.fetch import FetchResult, fetch


# Public DART GTFS feed. The canonical URL is published in the DART
# developer information / RiderInfo section; transit.land's feed-registry
# is the de-facto canonical pointer when DART rotates the path. If DART
# moves the feed again, override via --url at the command line or via
# parameters.yaml.
#
# Drift history:
#   - S+1 (session-14): `https://www.dartfirststate.com/information/routes/gtfs_data/dartfirststate_de_us.zip`
#   - session-18 patch: 404'd on the live-etl run; DART rotated the path
#     to /RiderInfo/Routes/... (and dropped the www. prefix in some
#     contexts; the apex host still serves both). transit.land's feed
#     registry confirms the new URL.
DEFAULT_DART_GTFS_URL = (
    "https://dartfirststate.com/RiderInfo/Routes/gtfs_data/dartfirststate_de_us.zip"
)

OUTPUT_ZIP_FILENAME = "dart-gtfs.zip"
OUTPUT_STOPS_FILENAME = "dart-stops.csv"


def pull(
    out_dir: Path, *, url: str = DEFAULT_DART_GTFS_URL
) -> tuple[Path, FetchResult]:
    """Pull DART GTFS zip + pre-extract stops.txt. Returns (zip_path, FetchResult)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result = fetch(url)

    zip_target = out_dir / OUTPUT_ZIP_FILENAME
    atomic_write_bytes(zip_target, result.body)

    # Pre-extract stops.txt as a CSV for convenient downstream consumption.
    # The S+3 transform may re-read the zip directly; both paths are valid.
    try:
        with zipfile.ZipFile(io.BytesIO(result.body)) as zf:
            names = zf.namelist()
            if "stops.txt" in names:
                stops_bytes = zf.read("stops.txt")
                atomic_write_bytes(out_dir / OUTPUT_STOPS_FILENAME, stops_bytes)
            else:
                result.warnings.append(
                    f"GTFS zip missing stops.txt; namelist={names!r}"
                )
    except zipfile.BadZipFile as exc:
        result.warnings.append(f"GTFS payload is not a valid zip: {exc}")

    return zip_target, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull DART GTFS feed.")
    parser.add_argument("--out", type=Path, default=Path("etl/raw"))
    parser.add_argument("--url", default=DEFAULT_DART_GTFS_URL)
    args = parser.parse_args(argv)

    target, result = pull(args.out, url=args.url)
    print(f"wrote {target} ({result.http_status}; {len(result.body)} bytes)")
    print(f"  sha256:       {result.sha256}")
    print(f"  last_fetched: {result.last_fetched}")
    if result.warnings:
        print(f"  warnings:     {result.warnings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
