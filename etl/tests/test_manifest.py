"""Smoke tests for etl.lib.manifest."""

from __future__ import annotations

import json
from pathlib import Path

from etl.lib.fetch import FetchResult
from etl.lib.manifest import Manifest, SourceEntry, load_manifest


def _fake_fetch_result(url: str, body: bytes) -> FetchResult:
    import hashlib

    return FetchResult(
        url=url,
        http_status=200,
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
        last_fetched="2026-05-11T12:00:00Z",
        content_type="application/json",
        elapsed_ms=42,
        warnings=[],
    )


def test_source_entry_from_fetch_result() -> None:
    fr = _fake_fetch_result("https://example.com/data.json", b'{"ok": true}')
    entry = SourceEntry.from_fetch_result(fr, raw_path="etl/raw/data.json")
    assert entry.url == "https://example.com/data.json"
    assert entry.http_status == 200
    assert entry.last_fetched == "2026-05-11T12:00:00Z"
    assert entry.size_bytes == len(b'{"ok": true}')
    assert entry.raw_path == "etl/raw/data.json"


def test_manifest_round_trip(tmp_path: Path) -> None:
    m = Manifest(etl_version="0.1.0", cycle_5_status="pending")
    fr = _fake_fetch_result("https://example.com/a.csv", b"col1,col2\n1,2\n")
    m.add_source("source_a", SourceEntry.from_fetch_result(fr, "etl/raw/a.csv"))

    target = tmp_path / "manifest.json"
    m.write(target)
    assert target.exists()

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["etl_version"] == "0.1.0"
    assert payload["cycle_5_status"] == "pending"
    assert "source_a" in payload["sources"]
    assert payload["sources"]["source_a"]["http_status"] == 200

    loaded = load_manifest(target)
    assert loaded.etl_version == "0.1.0"
    assert loaded.cycle_5_status == "pending"
    assert "source_a" in loaded.sources
    assert loaded.sources["source_a"].sha256 == fr.sha256


def test_manifest_default_status_is_pending() -> None:
    m = Manifest(etl_version="0.1.0")
    assert m.cycle_5_status == "pending"
