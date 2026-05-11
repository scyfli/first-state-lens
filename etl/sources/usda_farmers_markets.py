"""USDA AMS National Farmers Market Directory puller — Delaware scaffold.

Source (canonical, but access-friction-laden):
  - https://www.usdalocalfoodportal.com/api/farmersmarket/  (API key required;
    contact USDA AMS for credentials)
  - https://search.ams.usda.gov/farmersmarkets/v1/  (legacy svcdesc; SSL
    cert expired as of session-18 recon — usage blocked)
  - https://www.ams.usda.gov/local-food-directories/farmersmarkets  (web UI
    returns 403 to non-browser User-Agents; bulk export gated)

License: Public domain data; access form-gated.
Cadence: USDA AMS reviews quarterly per market self-reporting.
Output: etl/raw/usda-farmers-markets-de.json

================================================================================
OPEN QUESTION (carry to next session unless resolved): canonical source URL
================================================================================

Session-18 recon failed to identify a usable open public download URL:

  1. usdalocalfoodportal.com/api/farmersmarket/ requires an API key
     (contact USDA AMS Local Food Portal team for credentials)
  2. search.ams.usda.gov/farmersmarkets/v1/ has an expired SSL cert
     (the OLD svcdesc URL was the v1 service that has been retired)
  3. ams.usda.gov returns 403 to non-browser User-Agents on the main
     directory page, so scraping the HTML for embedded JSON is blocked

This puller is therefore a CONFIGURABLE SCAFFOLD — same shape as the
DSB grantee puller. URL is passed via --source (CLI) or
`parameters.yaml: usda_farmers_markets_url`. Output schema follows the
methodology v0.2.0 Q6 food-resource shape that the merge stage expects.

================================================================================
Parser strategy
================================================================================

The expected response shape (post-API-key-resolution) is a JSON array
of market objects with fields:

  {
    "listing_id": "...",
    "listing_name": "Wilmington Farmers Market",
    "location_address": "...",
    "location_state": "Delaware",
    "location_x": <longitude>,
    "location_y": <latitude>,
    ...
  }

`parse_payload` is pure (no I/O), takes the JSON text, returns a
normalized list of MarketRecord dataclasses suitable for handing to
`etl.transforms.merge_food_resources`. Adapter pattern: when the URL
question resolves to a different shape (CSV, KML, ArcGIS FeatureLayer),
this parser is the swap-out point.

Run standalone:
    python -m etl.sources.usda_farmers_markets --source <URL> --out etl/raw/
    python -m etl.sources.usda_farmers_markets --fixture etl/tests/fixtures/farmers-markets-toy.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Optional

from etl.lib.atomic_io import atomic_write_bytes, atomic_write_text
from etl.lib.fetch import FetchResult, fetch


# Sentinel default; the puller will fetch this URL but the response
# will almost certainly be unusable until the URL is pinned via
# parameters.yaml or --source. See module docstring.
DEFAULT_FM_URL = "https://www.usdalocalfoodportal.com/api/farmersmarket/?location_state=Delaware"

OUTPUT_RAW = "usda-farmers-markets-raw.json"
OUTPUT_PARSED = "usda-farmers-markets-de.json"


@dataclasses.dataclass
class MarketRecord:
    """Normalized farmers market record for downstream food-resource merge."""
    listing_id: Optional[str]
    listing_name: str
    location_address: Optional[str]
    location_state: Optional[str]
    location_lat: Optional[float]
    location_lon: Optional[float]


@dataclasses.dataclass
class ParseResult:
    markets: list[MarketRecord]
    parser_warnings: list[str]


def pull(
    out_dir: Path, *, url: str = DEFAULT_FM_URL
) -> tuple[Path, FetchResult, ParseResult]:
    """Fetch the farmers-markets feed, persist raw + parsed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result = fetch(url)
    atomic_write_bytes(out_dir / OUTPUT_RAW, result.body)

    parsed = parse_payload(result.body.decode("utf-8", errors="replace"))

    atomic_write_text(
        out_dir / OUTPUT_PARSED,
        json.dumps(
            {"markets": [dataclasses.asdict(m) for m in parsed.markets]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    for w in parsed.parser_warnings:
        result.warnings.append(f"usda-farmers-markets parser: {w}")
    result.warnings.append(f"usda-farmers-markets count={len(parsed.markets)}")
    return out_dir / OUTPUT_PARSED, result, parsed


def parse_payload(text: str) -> ParseResult:
    """Pure parser. Tolerant — returns empty markets when shape is wrong."""
    warnings: list[str] = []
    text = text.strip()
    if not text:
        return ParseResult(markets=[], parser_warnings=["empty payload"])

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return ParseResult(markets=[], parser_warnings=[f"non-JSON response: {exc}"])

    # Accept three known shapes: bare list; { "data": [...] }; { "markets": [...] }.
    raw_list = None
    if isinstance(payload, list):
        raw_list = payload
    elif isinstance(payload, dict):
        for key in ("data", "markets", "results", "items"):
            if isinstance(payload.get(key), list):
                raw_list = payload[key]
                break
    if raw_list is None:
        return ParseResult(
            markets=[],
            parser_warnings=[
                "could not find a list of market records in the response payload; "
                "tried top-level array and keys [data, markets, results, items]"
            ],
        )

    markets: list[MarketRecord] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        name = item.get("listing_name") or item.get("name") or ""
        if not name:
            continue
        try:
            lat = float(item.get("location_y") or item.get("lat") or item.get("latitude") or 0.0) or None
            lon = float(item.get("location_x") or item.get("lon") or item.get("longitude") or 0.0) or None
        except (TypeError, ValueError):
            lat = lon = None
        markets.append(
            MarketRecord(
                listing_id=str(item.get("listing_id") or item.get("id") or "") or None,
                listing_name=str(name),
                location_address=item.get("location_address") or item.get("address"),
                location_state=item.get("location_state") or item.get("state"),
                location_lat=lat,
                location_lon=lon,
            )
        )

    if not markets:
        warnings.append(
            "response parsed but no markets extracted — schema may have drifted "
            "or the URL is gated (auth/cert/UA). Treat the canonical URL as a "
            "carried open question."
        )

    return ParseResult(markets=markets, parser_warnings=warnings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull + parse USDA farmers markets (scaffold; URL parameterized)."
    )
    parser.add_argument("--source", default=DEFAULT_FM_URL)
    parser.add_argument("--out", type=Path, default=Path("etl/raw"))
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Parse a local JSON fixture instead of fetching the URL.",
    )
    args = parser.parse_args(argv)

    if args.fixture:
        text = args.fixture.read_text(encoding="utf-8")
        parsed = parse_payload(text)
        print(f"parsed {len(parsed.markets)} market(s) from {args.fixture}")
        for w in parsed.parser_warnings:
            print(f"  warning: {w}")
        for m in parsed.markets[:5]:
            print(f"  - {m.listing_name} @ ({m.location_lat}, {m.location_lon}) "
                  f"[{m.location_address!r}]")
        return 0

    target, fetch_result, parse_result = pull(args.out, url=args.source)
    print(f"wrote {target} ({fetch_result.http_status}; {len(fetch_result.body)} raw bytes)")
    print(f"  market_count: {len(parse_result.markets)}")
    for w in fetch_result.warnings:
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
