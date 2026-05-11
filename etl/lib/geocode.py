"""Geocoding library — Census Geocoder primary, Nominatim cross-check.

Per methodology v0.2.0 §Q5: every DGI grantee storefront address is
geocoded via the Census Geocoder (high-resolution, US-specific, no API
key required at low volume) AND cross-checked with Nominatim (OpenStreetMap
worldwide; respects 1 req/sec rate limit + custom UA per OSM policy).

The cross-check produces a `geocoding_confidence` field:

  - high   : both geocoders agree on the same Census tract (GEOID match)
  - medium : geocoders disagree on the tract but both returned a result;
             flag for manual review per Q5
  - manual : at least one geocoder failed; explicit manual assignment
             required via etl/manual-reviews.yaml
  - pending-disbursement : grant exists but storefront not yet announced
             (Cycle 5 placeholder; not geocoded)

The transform layer (etl.transforms.geocode) wires this library into the
DGI grantee pipeline. The library itself is provider-agnostic: it knows
how to ask Census + Nominatim and parse their responses, but doesn't know
anything about DGI semantics.

API key handling:
  - Census Geocoder: no API key required for the free public endpoint;
    we use the `onelineaddress` flow with the Census Bureau geographies
    benchmark. Higher-volume users can register at https://api.census.gov/
    for a key and pass it via the CENSUS_GEOCODER_API_KEY env var. The
    free endpoint handles the DGI grantee scale comfortably.
  - Nominatim: no key; usage policy is the constraint. We sleep 1 second
    between requests within a single process (`_nominatim_lock` enforces
    this) and identify ourselves via a custom User-Agent per
    https://operations.osmfoundation.org/policies/nominatim/.

Disk cache:
  - Both geocoders cache responses keyed by sha256(normalized address)
    under `etl/cache/geocode/<provider>/<sha>.json`. Cache hits skip
    network and rate-limit pauses entirely. The cache is gitignored
    (etl/cache/ in .gitignore) and survives across runs — geocoding is
    expensive enough that re-running an ETL with the same grantee list
    should be free.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

from .atomic_io import atomic_write_text
from .fetch import fetch


# ---------------------------------------------------------------------------
# Constants & shared types
# ---------------------------------------------------------------------------


DEFAULT_CACHE_DIR = Path("etl/cache/geocode")

# Census Geocoder public endpoint. The "geographies" flow returns lat/lon
# plus the tract GEOID we need for downstream apportionment, in a single
# request. The "Public_AR_Current" benchmark + "Current_Current" vintage
# pairing is the Census Bureau's "latest as of today" pointer.
CENSUS_GEOCODER_BASE = (
    "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
)
CENSUS_GEOCODER_BENCHMARK = "Public_AR_Current"
CENSUS_GEOCODER_VINTAGE = "Current_Current"

# Nominatim is the OpenStreetMap geocoder. Per usage policy we must
# (a) provide a contactable User-Agent (handled by etl.lib.fetch's default
# UA which includes the maintainer's email); (b) keep requests under
# 1 per second. The rate limit is enforced via _nominatim_lock below.
NOMINATIM_BASE = "https://nominatim.openstreetmap.org/search"
NOMINATIM_MIN_INTERVAL_S = 1.05  # tiny margin over the 1s policy

# Global lock + last-call time for Nominatim rate limiting. This is
# process-local; CI runs are single-process so a lock is sufficient. For
# multi-process orchestration we'd switch to a file-based lock.
_nominatim_lock = threading.Lock()
_nominatim_last_call_monotonic: float = 0.0


class GeocodeError(Exception):
    """Raised when a geocoder cannot produce a usable result."""


# ---------------------------------------------------------------------------
# Result type — common shape across providers
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class GeocodeResult:
    """Provider-agnostic geocoding outcome.

    `provider` is "census" or "nominatim". `tract_geoid` is the 11-character
    Census GEOID (state+county+tract) when the provider returns one; for
    Nominatim we leave it as None unless we post-process (Nominatim doesn't
    return Census tracts directly; the transform layer handles tract
    assignment via geometry intersection if needed).
    """

    provider: str
    address: str
    found: bool
    lat: Optional[float]
    lon: Optional[float]
    tract_geoid: Optional[str]
    county_fips: Optional[str]
    state_fips: Optional[str]
    matched_address: Optional[str]
    raw: dict
    cache_hit: bool
    fetched_at: str


# ---------------------------------------------------------------------------
# Address normalization + cache key
# ---------------------------------------------------------------------------


def _normalize_address(addr: str) -> str:
    """Whitespace-collapse + lowercase for deterministic cache keys."""
    return " ".join(addr.strip().lower().split())


def _cache_key(provider: str, address: str) -> str:
    norm = _normalize_address(address)
    return hashlib.sha256(f"{provider}|{norm}".encode("utf-8")).hexdigest()


def _cache_path(cache_dir: Path, provider: str, address: str) -> Path:
    sha = _cache_key(provider, address)
    return cache_dir / provider / f"{sha}.json"


def _read_cache(cache_path: Path) -> Optional[dict]:
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(cache_path: Path, payload: dict) -> None:
    atomic_write_text(cache_path, json.dumps(payload, indent=2) + "\n")


def _utc_now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Census Geocoder
# ---------------------------------------------------------------------------


def geocode_census(
    address: str,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    api_key: Optional[str] = None,
    benchmark: str = CENSUS_GEOCODER_BENCHMARK,
    vintage: str = CENSUS_GEOCODER_VINTAGE,
) -> GeocodeResult:
    """Geocode `address` via the Census Geocoder.

    Returns a GeocodeResult. `found=False` is a normal outcome (Census
    couldn't match the address); only catastrophic failures (network down,
    HTTP 5xx after retries) raise.
    """
    cache_path = _cache_path(cache_dir, "census", address)
    cached = _read_cache(cache_path)
    if cached is not None:
        cached["cache_hit"] = True
        return GeocodeResult(**cached)

    params = {
        "address": address,
        "benchmark": benchmark,
        "vintage": vintage,
        "format": "json",
    }
    if api_key:
        params["key"] = api_key

    url = CENSUS_GEOCODER_BASE + "?" + _urlencode(params)
    result = fetch(url)
    body = json.loads(result.body.decode("utf-8"))

    parsed = _parse_census_response(address, body)
    parsed_dict = dataclasses.asdict(parsed)
    # Don't persist cache_hit; it's set on read.
    parsed_dict["cache_hit"] = False
    _write_cache(cache_path, parsed_dict)
    return parsed


def _parse_census_response(address: str, body: dict) -> GeocodeResult:
    matches = body.get("result", {}).get("addressMatches", [])
    if not matches:
        return GeocodeResult(
            provider="census",
            address=address,
            found=False,
            lat=None,
            lon=None,
            tract_geoid=None,
            county_fips=None,
            state_fips=None,
            matched_address=None,
            raw=body,
            cache_hit=False,
            fetched_at=_utc_now_iso(),
        )

    # We use the first match (Census ranks by score).
    m = matches[0]
    coords = m.get("coordinates", {})
    lat = _safe_float(coords.get("y"))
    lon = _safe_float(coords.get("x"))
    geographies = m.get("geographies", {})
    tracts = geographies.get("Census Tracts", [])
    tract_geoid = None
    county_fips = None
    state_fips = None
    if tracts:
        t = tracts[0]
        tract_geoid = t.get("GEOID")
        county_fips = t.get("COUNTY")
        state_fips = t.get("STATE")
    return GeocodeResult(
        provider="census",
        address=address,
        found=True,
        lat=lat,
        lon=lon,
        tract_geoid=tract_geoid,
        county_fips=county_fips,
        state_fips=state_fips,
        matched_address=m.get("matchedAddress"),
        raw=body,
        cache_hit=False,
        fetched_at=_utc_now_iso(),
    )


# ---------------------------------------------------------------------------
# Nominatim
# ---------------------------------------------------------------------------


def geocode_nominatim(
    address: str,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> GeocodeResult:
    """Geocode `address` via Nominatim with TOS-compliant rate limiting.

    Within one process, the global `_nominatim_lock` enforces 1 req/sec.
    Cache hits skip network and the rate-limit pause entirely.
    """
    cache_path = _cache_path(cache_dir, "nominatim", address)
    cached = _read_cache(cache_path)
    if cached is not None:
        cached["cache_hit"] = True
        return GeocodeResult(**cached)

    params = {
        "q": address,
        "format": "json",
        "addressdetails": "1",
        "limit": "1",
    }
    url = NOMINATIM_BASE + "?" + _urlencode(params)

    _nominatim_wait()
    result = fetch(url)
    body = json.loads(result.body.decode("utf-8"))

    parsed = _parse_nominatim_response(address, body)
    parsed_dict = dataclasses.asdict(parsed)
    parsed_dict["cache_hit"] = False
    _write_cache(cache_path, parsed_dict)
    return parsed


def _nominatim_wait() -> None:
    """Sleep just enough to respect the 1 req/sec Nominatim usage policy."""
    global _nominatim_last_call_monotonic
    with _nominatim_lock:
        now = time.monotonic()
        elapsed = now - _nominatim_last_call_monotonic
        if elapsed < NOMINATIM_MIN_INTERVAL_S:
            time.sleep(NOMINATIM_MIN_INTERVAL_S - elapsed)
        _nominatim_last_call_monotonic = time.monotonic()


def _parse_nominatim_response(address: str, body: list | dict) -> GeocodeResult:
    if not isinstance(body, list) or not body:
        return GeocodeResult(
            provider="nominatim",
            address=address,
            found=False,
            lat=None,
            lon=None,
            tract_geoid=None,  # Nominatim doesn't return Census tracts directly
            county_fips=None,
            state_fips=None,
            matched_address=None,
            raw={"results": body},
            cache_hit=False,
            fetched_at=_utc_now_iso(),
        )

    top = body[0]
    return GeocodeResult(
        provider="nominatim",
        address=address,
        found=True,
        lat=_safe_float(top.get("lat")),
        lon=_safe_float(top.get("lon")),
        tract_geoid=None,
        county_fips=None,
        state_fips=None,
        matched_address=top.get("display_name"),
        raw={"results": body},
        cache_hit=False,
        fetched_at=_utc_now_iso(),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _urlencode(params: dict) -> str:
    from urllib.parse import urlencode

    return urlencode({k: v for k, v in params.items() if v is not None})


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Test seam: reset rate-limit state (used by smoke tests)
# ---------------------------------------------------------------------------


def _reset_rate_limit_state_for_tests() -> None:
    """Reset module-level Nominatim rate-limit state. Test-use only."""
    global _nominatim_last_call_monotonic
    with _nominatim_lock:
        _nominatim_last_call_monotonic = 0.0


# ---------------------------------------------------------------------------
# CLI (smoke / debug)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Geocode an address via Census + Nominatim (debug)."
    )
    parser.add_argument("address", help="Address to geocode (in quotes).")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="Disk cache directory (default: etl/cache/geocode)",
    )
    parser.add_argument(
        "--skip-nominatim",
        action="store_true",
        help="Only call Census; skip Nominatim cross-check.",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("CENSUS_GEOCODER_API_KEY")

    census = geocode_census(args.address, cache_dir=args.cache_dir, api_key=api_key)
    print(f"[census]    found={census.found}; cache_hit={census.cache_hit}")
    if census.found:
        print(f"            lat={census.lat}, lon={census.lon}")
        print(f"            tract_geoid={census.tract_geoid}")
        print(f"            matched={census.matched_address!r}")

    if not args.skip_nominatim:
        nominatim = geocode_nominatim(args.address, cache_dir=args.cache_dir)
        print(f"[nominatim] found={nominatim.found}; cache_hit={nominatim.cache_hit}")
        if nominatim.found:
            print(f"            lat={nominatim.lat}, lon={nominatim.lon}")
            print(f"            matched={nominatim.matched_address!r}")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
