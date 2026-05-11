"""Smoke tests for methodology v0.3.0 pullers (Census UAC10).

Methodology v0.3.0 replaces the v0.2.x county-level urbanicity proxy with
the canonical Census 2010 Urban Areas (UAC10) shapefile cross-walk. The
puller fetches the national TIGER UAC10 zip; the load_raw spatial-join
helpers (see test_load_raw.py) consume it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

from etl.lib.fetch import FetchResult
from etl.sources import census_uac


def _make_fetch_result(
    url: str, body: bytes, *, status: int = 200, content_type: str = "application/zip"
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


def test_census_uac_url_targets_national_uac10_2020() -> None:
    """v0.3.0 pins UAC10 (2010 urban areas) to align with USDA LILA."""
    url = census_uac.build_url(2020)
    assert "TIGER2020/UAC/" in url
    assert "tl_2020_us_uac10.zip" in url


def test_census_uac_url_year_override() -> None:
    url = census_uac.build_url(2023)
    assert "TIGER2023/UAC/" in url
    assert "tl_2023_us_uac10.zip" in url


def test_census_uac_pull_writes_zip(tmp_path: Path) -> None:
    fake_zip = b"PK\x03\x04fake-uac-shapefile-zip"
    fake_url = census_uac.build_url(census_uac.DEFAULT_TIGER_YEAR)
    fake_result = _make_fetch_result(fake_url, fake_zip)

    with patch.object(census_uac, "fetch", return_value=fake_result):
        target, result = census_uac.pull(tmp_path)

    assert target.exists()
    assert target.name == census_uac.OUTPUT_FILENAME
    assert target.read_bytes() == fake_zip
    assert result.warnings == []


def test_census_uac_pull_warns_on_non_zip(tmp_path: Path) -> None:
    """If TIGER returns HTML (e.g., 404 with text/html body), warn."""
    fake_url = census_uac.build_url(census_uac.DEFAULT_TIGER_YEAR)
    fake_result = _make_fetch_result(fake_url, b"<html>404</html>", content_type="text/html")
    with patch.object(census_uac, "fetch", return_value=fake_result):
        target, result = census_uac.pull(tmp_path)
    assert target.exists()
    assert any("zip magic bytes" in w for w in result.warnings)
