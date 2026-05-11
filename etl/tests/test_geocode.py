"""Smoke tests for etl.lib.geocode (Census + Nominatim wrappers)."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from etl.lib.fetch import FetchResult
from etl.lib import geocode as geo_lib


def _fake_fetch_result(url: str, body: bytes) -> FetchResult:
    return FetchResult(
        url=url,
        http_status=200,
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
        last_fetched="2026-05-11T13:00:00Z",
        content_type="application/json",
        elapsed_ms=10,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Census Geocoder
# ---------------------------------------------------------------------------


def test_geocode_census_hit(tmp_path: Path, fixture_census_hit: bytes) -> None:
    with patch.object(
        geo_lib,
        "fetch",
        return_value=_fake_fetch_result("https://x", fixture_census_hit),
    ):
        result = geo_lib.geocode_census(
            "123 N Market St, Wilmington, DE 19801", cache_dir=tmp_path
        )
    assert result.found is True
    assert result.provider == "census"
    assert result.tract_geoid == "10003001100"
    assert result.county_fips == "003"
    assert result.state_fips == "10"
    assert result.lat == pytest.approx(39.7445)
    assert result.lon == pytest.approx(-75.5455)
    assert result.cache_hit is False


def test_geocode_census_miss(tmp_path: Path, fixture_census_miss: bytes) -> None:
    with patch.object(
        geo_lib,
        "fetch",
        return_value=_fake_fetch_result("https://x", fixture_census_miss),
    ):
        result = geo_lib.geocode_census(
            "9999 Nowhere Way, Nowhere, DE 99999", cache_dir=tmp_path
        )
    assert result.found is False
    assert result.tract_geoid is None
    assert result.lat is None and result.lon is None


def test_geocode_census_cache_hit_skips_network(
    tmp_path: Path, fixture_census_hit: bytes
) -> None:
    """First call writes cache; second call reads cache without calling fetch."""
    addr = "123 N Market St, Wilmington, DE 19801"
    with patch.object(
        geo_lib,
        "fetch",
        return_value=_fake_fetch_result("https://x", fixture_census_hit),
    ) as fetch_mock:
        first = geo_lib.geocode_census(addr, cache_dir=tmp_path)
    assert fetch_mock.call_count == 1
    assert first.cache_hit is False

    with patch.object(geo_lib, "fetch") as fetch_mock_2:
        second = geo_lib.geocode_census(addr, cache_dir=tmp_path)
    assert fetch_mock_2.call_count == 0
    assert second.cache_hit is True
    assert second.tract_geoid == first.tract_geoid


def test_geocode_census_api_key_appended_to_url(
    tmp_path: Path, fixture_census_hit: bytes
) -> None:
    captured = {}

    def capturing_fetch(url, **kwargs):
        captured["url"] = url
        return _fake_fetch_result(url, fixture_census_hit)

    with patch.object(geo_lib, "fetch", side_effect=capturing_fetch):
        geo_lib.geocode_census("anywhere", cache_dir=tmp_path, api_key="testkey42")
    assert "key=testkey42" in captured["url"]


# ---------------------------------------------------------------------------
# Nominatim
# ---------------------------------------------------------------------------


def test_geocode_nominatim_hit(tmp_path: Path, fixture_nominatim_hit: bytes) -> None:
    with patch.object(
        geo_lib,
        "fetch",
        return_value=_fake_fetch_result("https://x", fixture_nominatim_hit),
    ):
        result = geo_lib.geocode_nominatim(
            "123 N Market St, Wilmington, DE 19801", cache_dir=tmp_path
        )
    assert result.found is True
    assert result.provider == "nominatim"
    assert result.tract_geoid is None  # Nominatim doesn't return Census tracts
    assert result.lat == pytest.approx(39.74455)
    assert result.lon == pytest.approx(-75.54551)


def test_geocode_nominatim_miss(tmp_path: Path, fixture_nominatim_miss: bytes) -> None:
    with patch.object(
        geo_lib,
        "fetch",
        return_value=_fake_fetch_result("https://x", fixture_nominatim_miss),
    ):
        result = geo_lib.geocode_nominatim("nowhere", cache_dir=tmp_path)
    assert result.found is False


def test_geocode_nominatim_cache_hit(
    tmp_path: Path, fixture_nominatim_hit: bytes
) -> None:
    addr = "123 N Market St"
    with patch.object(
        geo_lib,
        "fetch",
        return_value=_fake_fetch_result("https://x", fixture_nominatim_hit),
    ) as fetch_mock:
        geo_lib.geocode_nominatim(addr, cache_dir=tmp_path)
    assert fetch_mock.call_count == 1

    with patch.object(geo_lib, "fetch") as fetch_mock_2:
        cached = geo_lib.geocode_nominatim(addr, cache_dir=tmp_path)
    assert fetch_mock_2.call_count == 0
    assert cached.cache_hit is True


def test_geocode_nominatim_rate_limit_enforced(
    tmp_path: Path, fixture_nominatim_hit: bytes
) -> None:
    """Two back-to-back live calls must be at least ~1 second apart."""
    # Use distinct addresses so the cache doesn't short-circuit.
    addrs = ["111 Test Ave", "222 Test Ave"]
    with patch.object(
        geo_lib,
        "fetch",
        return_value=_fake_fetch_result("https://x", fixture_nominatim_hit),
    ):
        t0 = time.monotonic()
        for a in addrs:
            geo_lib.geocode_nominatim(a, cache_dir=tmp_path)
        elapsed = time.monotonic() - t0
    # First call has no prior pause; second call should sleep ~1s.
    assert elapsed >= 1.0


# ---------------------------------------------------------------------------
# Normalization + cache keys
# ---------------------------------------------------------------------------


def test_cache_key_address_normalized(tmp_path: Path, fixture_census_hit: bytes) -> None:
    """Same address with different casing/whitespace hits the same cache entry."""
    with patch.object(
        geo_lib,
        "fetch",
        return_value=_fake_fetch_result("https://x", fixture_census_hit),
    ) as fetch_mock:
        geo_lib.geocode_census("  123 N MARKET st  ", cache_dir=tmp_path)
    assert fetch_mock.call_count == 1

    with patch.object(geo_lib, "fetch") as fetch_mock_2:
        # Differently-cased / spaced address; expect cache hit.
        result = geo_lib.geocode_census("123 n market St", cache_dir=tmp_path)
    assert fetch_mock_2.call_count == 0
    assert result.cache_hit is True
