"""Smoke tests for the S+5 pullers (TIGER counties, SNAP retailers, USDA farmers markets)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from etl.lib.fetch import FetchResult
from etl.sources import snap_retailers, tiger_counties, usda_farmers_markets


def _make_fetch_result(
    url: str, body: bytes, *, status: int = 200, content_type: str = "application/json"
) -> FetchResult:
    return FetchResult(
        url=url,
        http_status=status,
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
        last_fetched="2026-05-11T18:00:00Z",
        content_type=content_type,
        elapsed_ms=10,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# TIGER counties
# ---------------------------------------------------------------------------


def test_tiger_counties_url_targets_national_2020() -> None:
    url = tiger_counties.build_url(2020)
    assert "TIGER2020/COUNTY/" in url
    assert "tl_2020_us_county.zip" in url


def test_tiger_counties_url_year_override() -> None:
    url = tiger_counties.build_url(2023)
    assert "TIGER2023/COUNTY/" in url
    assert "tl_2023_us_county.zip" in url


def test_tiger_counties_pull_writes_zip(tmp_path: Path) -> None:
    fake_zip = b"PK\x03\x04fake-county-shapefile-zip"
    fake_url = tiger_counties.build_url(tiger_counties.DEFAULT_TIGER_YEAR)
    fake_result = _make_fetch_result(fake_url, fake_zip, content_type="application/zip")

    with patch.object(tiger_counties, "fetch", return_value=fake_result):
        target, result = tiger_counties.pull(tmp_path)

    assert target.exists()
    assert target.name == tiger_counties.OUTPUT_FILENAME
    assert target.read_bytes() == fake_zip
    assert result.warnings == []


def test_tiger_counties_pull_warns_on_non_zip(tmp_path: Path) -> None:
    fake_url = tiger_counties.build_url(tiger_counties.DEFAULT_TIGER_YEAR)
    fake_result = _make_fetch_result(fake_url, b"<html>404</html>")
    with patch.object(tiger_counties, "fetch", return_value=fake_result):
        target, result = tiger_counties.pull(tmp_path)
    assert target.exists()
    assert any("zip magic bytes" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# SNAP retailers
# ---------------------------------------------------------------------------


def test_snap_retailers_query_url_includes_state_filter() -> None:
    url = snap_retailers.build_query_url(state_abbr="DE")
    assert "State%3D%27DE%27" in url  # urlencoded "State='DE'"
    assert "f=geojson" in url
    assert "Store_Name" in url
    assert "resultOffset=0" in url


def test_snap_retailers_query_url_paginates() -> None:
    url = snap_retailers.build_query_url(state_abbr="DE", result_offset=2000)
    assert "resultOffset=2000" in url


def _make_snap_page(features: list[dict], *, exceeded: bool = False) -> bytes:
    payload: dict = {
        "type": "FeatureCollection",
        "features": features,
    }
    if exceeded:
        payload["properties"] = {"exceededTransferLimit": True}
    return json.dumps(payload).encode("utf-8")


def _snap_feature(name: str, lat: float, lon: float) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "Store_Name": name,
            "City": "Wilmington",
            "State": "DE",
            "Zip_Code": "19801",
            "Store_Type": "Grocery Store",
            "Latitude": lat,
            "Longitude": lon,
        },
    }


def test_snap_retailers_pull_single_page(tmp_path: Path) -> None:
    body = _make_snap_page([_snap_feature("Store A", 39.7, -75.5)], exceeded=False)
    fake_result = _make_fetch_result("test://snap", body)

    with patch.object(snap_retailers, "fetch", return_value=fake_result):
        target, result = snap_retailers.pull(tmp_path)

    assert target.exists()
    assert target.name == snap_retailers.OUTPUT_FILENAME
    fc = json.loads(target.read_text(encoding="utf-8"))
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    assert fc["features"][0]["properties"]["Store_Name"] == "Store A"
    # feature_count warning is appended
    assert any("feature_count=1" in w for w in result.warnings)


def test_snap_retailers_pull_paginates_through_pages(tmp_path: Path) -> None:
    page1 = _make_snap_page(
        [_snap_feature(f"S{i}", 39.7 + i / 100, -75.5) for i in range(3)],
        exceeded=True,
    )
    page2 = _make_snap_page(
        [_snap_feature(f"T{i}", 39.6 + i / 100, -75.6) for i in range(2)],
        exceeded=False,
    )

    calls: list[int] = []

    def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        calls.append(len(calls))
        body = page1 if "resultOffset=0" in url else page2
        return _make_fetch_result(url, body)

    with patch.object(snap_retailers, "fetch", side_effect=fake_fetch):
        target, _ = snap_retailers.pull(tmp_path, page_size=2000)

    assert len(calls) == 2
    fc = json.loads(target.read_text(encoding="utf-8"))
    assert len(fc["features"]) == 5  # 3 + 2 across pages


def test_snap_retailers_pull_stops_when_no_more_features(tmp_path: Path) -> None:
    empty = _make_snap_page([], exceeded=False)
    fake_result = _make_fetch_result("test://snap", empty)
    with patch.object(snap_retailers, "fetch", return_value=fake_result):
        target, result = snap_retailers.pull(tmp_path)
    fc = json.loads(target.read_text(encoding="utf-8"))
    assert fc["features"] == []


def test_snap_retailers_pull_warns_on_non_json_page(tmp_path: Path) -> None:
    bad = _make_fetch_result("test://snap", b"<html>error</html>")
    with patch.object(snap_retailers, "fetch", return_value=bad):
        target, result = snap_retailers.pull(tmp_path)
    assert target.exists()
    assert any("non-JSON" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# USDA farmers markets — scaffold parser
# ---------------------------------------------------------------------------


def test_usda_fm_parse_top_level_list() -> None:
    text = json.dumps([
        {"listing_name": "Wilmington FM", "location_x": -75.55, "location_y": 39.74, "location_state": "Delaware"},
        {"listing_name": "Newark FM", "location_x": -75.75, "location_y": 39.68, "location_state": "Delaware"},
    ])
    result = usda_farmers_markets.parse_payload(text)
    assert len(result.markets) == 2
    assert result.markets[0].listing_name == "Wilmington FM"
    assert result.markets[0].location_lat == 39.74
    assert result.markets[0].location_lon == -75.55


def test_usda_fm_parse_nested_data_key() -> None:
    text = json.dumps({
        "data": [
            {"listing_name": "Test Market", "location_x": -75.5, "location_y": 39.7},
        ]
    })
    result = usda_farmers_markets.parse_payload(text)
    assert len(result.markets) == 1


def test_usda_fm_parse_returns_empty_on_html_response() -> None:
    """When the URL returns HTML (auth gate or 403 page), parser surfaces a warning, not a crash."""
    result = usda_farmers_markets.parse_payload("<html><body>403 Forbidden</body></html>")
    assert result.markets == []
    assert any("non-JSON" in w for w in result.parser_warnings)


def test_usda_fm_parse_returns_empty_on_unknown_shape() -> None:
    text = json.dumps({"unexpected": "shape"})
    result = usda_farmers_markets.parse_payload(text)
    assert result.markets == []
    assert any("could not find" in w for w in result.parser_warnings)


def test_usda_fm_parse_handles_missing_lat_lon() -> None:
    text = json.dumps([{"listing_name": "No Coords FM"}])
    result = usda_farmers_markets.parse_payload(text)
    assert len(result.markets) == 1
    assert result.markets[0].location_lat is None
    assert result.markets[0].location_lon is None


def test_usda_fm_pull_writes_files(tmp_path: Path) -> None:
    body = json.dumps([
        {"listing_name": "FM1", "location_x": -75.5, "location_y": 39.7, "location_state": "Delaware"},
    ]).encode("utf-8")
    fake_result = _make_fetch_result("test://fm", body)
    with patch.object(usda_farmers_markets, "fetch", return_value=fake_result):
        parsed_path, result, parsed = usda_farmers_markets.pull(tmp_path)

    assert (tmp_path / usda_farmers_markets.OUTPUT_RAW).exists()
    assert (tmp_path / usda_farmers_markets.OUTPUT_PARSED).exists()
    assert parsed_path == tmp_path / usda_farmers_markets.OUTPUT_PARSED
    assert len(parsed.markets) == 1
    assert any("count=1" in w for w in result.warnings)


def test_usda_fm_pull_tolerates_html_gateway_response(tmp_path: Path) -> None:
    """Scaffold posture: an HTML 403 page from the gated USDA endpoint
    must not crash the puller; it produces empty parsed output + a warning."""
    fake_result = _make_fetch_result("test://fm", b"<html>403 Forbidden</html>")
    with patch.object(usda_farmers_markets, "fetch", return_value=fake_result):
        _, result, parsed = usda_farmers_markets.pull(tmp_path)
    assert parsed.markets == []
    assert any("non-JSON" in w for w in result.warnings)
