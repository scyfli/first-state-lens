"""Per-puller smoke tests.

Each puller is exercised against a fake fetch + a fixture payload to
verify: URL is well-formed; payload validates per source schema; output
file is atomically written; the FetchResult plumbs through correctly.

No live network. Live runs are exercised by running the puller's CLI
manually (`python -m etl.sources.<name> --out ...`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from etl.lib.fetch import FetchResult
from etl.sources import (
    census_acs,
    dart_gtfs,
    firstmap_sd2,
    mmg_food_insecurity,
    usda_lila,
)


def _make_fetch_result(url: str, body: bytes, status: int = 200) -> FetchResult:
    import hashlib

    return FetchResult(
        url=url,
        http_status=status,
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
        last_fetched="2026-05-11T12:00:00Z",
        content_type="application/json",
        elapsed_ms=10,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# FirstMap SD2
# ---------------------------------------------------------------------------


def test_firstmap_sd2_default_url_has_district_filter() -> None:
    assert "DISTRICT" in firstmap_sd2.DEFAULT_SD2_QUERY_URL
    assert "f=geojson" in firstmap_sd2.DEFAULT_SD2_QUERY_URL


def test_firstmap_sd2_pull_writes_file(
    tmp_path: Path, fixture_sd2_geojson: bytes
) -> None:
    fake_result = _make_fetch_result(
        firstmap_sd2.DEFAULT_SD2_QUERY_URL, fixture_sd2_geojson
    )

    with patch.object(firstmap_sd2, "fetch", return_value=fake_result):
        target, result = firstmap_sd2.pull(tmp_path)

    assert target.exists()
    assert target.name == firstmap_sd2.OUTPUT_FILENAME
    assert target.read_bytes() == fixture_sd2_geojson
    assert result.http_status == 200


def test_firstmap_sd2_pull_rejects_non_geojson(tmp_path: Path) -> None:
    fake_result = _make_fetch_result(
        firstmap_sd2.DEFAULT_SD2_QUERY_URL, b'{"type": "Feature"}'
    )
    with patch.object(firstmap_sd2, "fetch", return_value=fake_result):
        with pytest.raises(Exception, match="FeatureCollection"):
            firstmap_sd2.pull(tmp_path)


# ---------------------------------------------------------------------------
# MMG
# ---------------------------------------------------------------------------


def test_mmg_pull_writes_file_and_validates(
    tmp_path: Path, fixture_mmg_csv: bytes
) -> None:
    fake_result = _make_fetch_result(
        mmg_food_insecurity.DEFAULT_MMG_URL, fixture_mmg_csv
    )
    with patch.object(mmg_food_insecurity, "fetch", return_value=fake_result):
        target, result = mmg_food_insecurity.pull(tmp_path)

    assert target.exists()
    assert target.name == mmg_food_insecurity.OUTPUT_FILENAME
    assert target.read_bytes() == fixture_mmg_csv
    # The puller records the row count as a soft warning.
    assert any("row_count" in w for w in result.warnings)


def test_mmg_required_columns_are_documented() -> None:
    assert "FIPS" in mmg_food_insecurity.EXPECTED_COLUMNS
    assert "Year" in mmg_food_insecurity.EXPECTED_COLUMNS


# ---------------------------------------------------------------------------
# Census ACS
# ---------------------------------------------------------------------------


def test_census_acs_url_includes_delaware_state_fips() -> None:
    url = census_acs.build_url("2023")
    assert "state:10" in url  # Delaware FIPS = 10
    assert "for=tract:*" in url
    assert "B01003_001E" in url  # Total population variable


def test_census_acs_pull_writes_file(
    tmp_path: Path, fixture_acs_json: bytes
) -> None:
    fake_url = census_acs.build_url("2023")
    fake_result = _make_fetch_result(fake_url, fixture_acs_json)
    with patch.object(census_acs, "fetch", return_value=fake_result):
        target, result = census_acs.pull(tmp_path)

    assert target.exists()
    assert target.name == census_acs.OUTPUT_FILENAME
    assert target.read_bytes() == fixture_acs_json


def test_census_acs_pull_includes_api_key_when_provided(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def capturing_fetch(url: str, **kwargs: Any) -> FetchResult:
        captured["url"] = url
        # Valid minimal Census shape (header + one data row) so the
        # source-boundary validate_census_json guard passes.
        return _make_fetch_result(url, b'[["NAME"],["Delaware"]]')

    with patch.object(census_acs, "fetch", side_effect=capturing_fetch):
        census_acs.pull(tmp_path, api_key="testkey123")
    assert "key=testkey123" in captured["url"]


def test_census_acs_pull_raises_on_html_rate_limit_page(tmp_path: Path) -> None:
    """Regression (session-26): an HTML rate-limit page at HTTP 200 must raise
    at the source boundary, not be persisted and silently zero the build."""
    from etl.lib.validate import ValidationError

    html = b"<!DOCTYPE html><html><head><script>AwsWAF captcha</script></head></html>"
    fake_result = _make_fetch_result(census_acs.build_url("2023"), html)
    with patch.object(census_acs, "fetch", return_value=fake_result):
        with pytest.raises(ValidationError, match="not valid JSON"):
            census_acs.pull(tmp_path)
    # And nothing was written to disk.
    assert not (tmp_path / census_acs.OUTPUT_FILENAME).exists()


# ---------------------------------------------------------------------------
# USDA LILA
# ---------------------------------------------------------------------------


def test_usda_lila_pull_writes_file(tmp_path: Path) -> None:
    fake_xlsx = b"PK\x03\x04fake-xlsx-bytes"  # XLSX is a zip; magic header
    fake_result = _make_fetch_result(usda_lila.DEFAULT_USDA_LILA_URL, fake_xlsx)
    with patch.object(usda_lila, "fetch", return_value=fake_result):
        target, result = usda_lila.pull(tmp_path)

    assert target.exists()
    assert target.name == usda_lila.OUTPUT_FILENAME
    assert target.read_bytes() == fake_xlsx


# ---------------------------------------------------------------------------
# DART GTFS
# ---------------------------------------------------------------------------


def _build_fake_gtfs_zip(stops_csv: bytes) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("stops.txt", stops_csv)
        zf.writestr("routes.txt", b"route_id,route_short_name\n1,1\n")
    return buf.getvalue()


def test_dart_gtfs_pull_extracts_stops(tmp_path: Path) -> None:
    stops = (
        b"stop_id,stop_name,stop_lat,stop_lon\n"
        b"1,Main St & 5th,39.7430,-75.5510\n"
        b"2,Market St & 10th,39.7500,-75.5400\n"
    )
    gtfs_zip = _build_fake_gtfs_zip(stops)
    fake_result = _make_fetch_result(dart_gtfs.DEFAULT_DART_GTFS_URL, gtfs_zip)

    with patch.object(dart_gtfs, "fetch", return_value=fake_result):
        zip_target, result = dart_gtfs.pull(tmp_path)

    assert zip_target.exists()
    assert (tmp_path / dart_gtfs.OUTPUT_STOPS_FILENAME).exists()
    extracted = (tmp_path / dart_gtfs.OUTPUT_STOPS_FILENAME).read_bytes()
    assert extracted == stops


def test_dart_gtfs_pull_warns_on_missing_stops(tmp_path: Path) -> None:
    """If the zip lacks stops.txt, a warning is appended but pull still succeeds."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("routes.txt", b"route_id\n1\n")
    fake_result = _make_fetch_result(dart_gtfs.DEFAULT_DART_GTFS_URL, buf.getvalue())
    with patch.object(dart_gtfs, "fetch", return_value=fake_result):
        zip_target, result = dart_gtfs.pull(tmp_path)
    assert zip_target.exists()
    assert any("missing stops.txt" in w for w in result.warnings)


def test_dart_gtfs_pull_warns_on_bad_zip(tmp_path: Path) -> None:
    fake_result = _make_fetch_result(
        dart_gtfs.DEFAULT_DART_GTFS_URL, b"this is not a zip file"
    )
    with patch.object(dart_gtfs, "fetch", return_value=fake_result):
        zip_target, result = dart_gtfs.pull(tmp_path)
    assert zip_target.exists()  # raw bytes still persisted
    assert any("not a valid zip" in w for w in result.warnings)
