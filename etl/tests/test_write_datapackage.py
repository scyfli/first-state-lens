"""Tests for etl.outputs.write_datapackage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from etl.lib.manifest import Manifest, SourceEntry
from etl.outputs.write_datapackage import (
    CANONICAL_RESOURCES,
    DATAPACKAGE_NAME,
    ResourceSpec,
    build_datapackage,
    write_datapackage,
)


def _toy_manifest() -> Manifest:
    m = Manifest(etl_version="0.1.0", cycle_5_status="pending")
    m.add_source(
        "usda-lila",
        SourceEntry(
            url="https://example.test/lila",
            last_fetched="2026-05-11T00:00:00Z",
            http_status=200,
            sha256="deadbeef",
            raw_path="etl/raw/usda-lila.geojson",
            size_bytes=1024,
            warnings=["lila row_count=199"],
        ),
    )
    m.add_source(
        "mmg",
        SourceEntry(
            url="https://example.test/mmg",
            last_fetched="2026-05-11T00:00:00Z",
            http_status=200,
            sha256="cafef00d",
            raw_path="etl/raw/mmg-county.csv",
            size_bytes=512,
            warnings=[],
        ),
    )
    return m


def _toy_parameters() -> dict:
    return {
        "sb254_population_threshold": 0.5,
        "sb254_urban_distance_mi": 0.5,
        "sb254_nonurban_distance_mi": 10.0,
        "low_income_poverty_threshold": 0.20,
        "low_income_mfi_threshold": 0.80,
        "mmg_release": "2025",
    }


def _write_tiny_resource(path: Path, content: str = "x,y\n1,2\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# build_datapackage
# ---------------------------------------------------------------------------


def test_build_datapackage_lenient_mode_includes_all_resources(tmp_path: Path):
    manifest = _toy_manifest()
    payload = build_datapackage(
        output_dir=tmp_path,
        version="0.2.1",
        manifest=manifest,
        parameters=_toy_parameters(),
        require_present=False,
    )
    assert payload["name"] == DATAPACKAGE_NAME
    assert payload["version"] == "0.2.1"
    assert payload["methodology_version"] == "0.2.0"
    assert payload["cycle_5_status"] == "pending"
    assert len(payload["resources"]) == len(CANONICAL_RESOURCES)
    # All resources should be marked not-present.
    for entry in payload["resources"]:
        assert entry["present"] is False
        assert entry["bytes"] == 0


def test_build_datapackage_strict_mode_raises_when_missing(tmp_path: Path):
    manifest = _toy_manifest()
    with pytest.raises(FileNotFoundError) as exc:
        build_datapackage(
            output_dir=tmp_path,
            version="0.2.1",
            manifest=manifest,
            parameters=_toy_parameters(),
            require_present=True,
        )
    assert "missing on disk" in str(exc.value)


def test_build_datapackage_computes_sha_and_size_for_present_files(tmp_path: Path):
    manifest = _toy_manifest()
    _write_tiny_resource(tmp_path / "dgi-grants.csv", "cycle,grantee\n1,Test\n")

    payload = build_datapackage(
        output_dir=tmp_path,
        version="0.2.1",
        manifest=manifest,
        parameters=_toy_parameters(),
        require_present=False,
    )
    by_name = {r["name"]: r for r in payload["resources"]}
    assert by_name["dgi-grants"]["present"] is True
    assert by_name["dgi-grants"]["bytes"] > 0
    assert len(by_name["dgi-grants"]["sha256"]) == 64  # hex sha256


def test_build_datapackage_includes_sources_block(tmp_path: Path):
    manifest = _toy_manifest()
    payload = build_datapackage(
        output_dir=tmp_path,
        version="0.2.1",
        manifest=manifest,
        parameters=_toy_parameters(),
        require_present=False,
    )
    sources_by_name = {s["name"]: s for s in payload["sources"]}
    assert "usda-lila" in sources_by_name
    assert sources_by_name["usda-lila"]["path"] == "https://example.test/lila"
    assert sources_by_name["usda-lila"]["sha256"] == "deadbeef"


def test_build_datapackage_includes_etl_parameters(tmp_path: Path):
    payload = build_datapackage(
        output_dir=tmp_path,
        version="0.2.1",
        manifest=_toy_manifest(),
        parameters=_toy_parameters(),
        require_present=False,
    )
    assert payload["etl_parameters"]["sb254_urban_distance_mi"] == 0.5
    assert payload["etl_parameters"]["low_income_poverty_threshold"] == 0.20


def test_build_datapackage_drops_non_serializable_parameters(tmp_path: Path):
    params = {"good": 1, "bad": object()}
    payload = build_datapackage(
        output_dir=tmp_path,
        version="0.2.1",
        manifest=_toy_manifest(),
        parameters=params,
        require_present=False,
    )
    assert payload["etl_parameters"] == {"good": 1}


# ---------------------------------------------------------------------------
# write_datapackage
# ---------------------------------------------------------------------------


def test_write_datapackage_writes_valid_json(tmp_path: Path):
    payload = build_datapackage(
        output_dir=tmp_path,
        version="0.2.1",
        manifest=_toy_manifest(),
        parameters=_toy_parameters(),
        require_present=False,
    )
    target = write_datapackage(tmp_path, payload)
    assert target.exists()
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed["name"] == DATAPACKAGE_NAME
    assert parsed["version"] == "0.2.1"


# ---------------------------------------------------------------------------
# Custom resource list
# ---------------------------------------------------------------------------


def test_build_datapackage_accepts_custom_resource_list(tmp_path: Path):
    custom = (
        ResourceSpec(
            name="custom",
            path="custom.json",
            format="json",
            description="A custom resource.",
        ),
    )
    payload = build_datapackage(
        output_dir=tmp_path,
        version="0.2.1",
        manifest=_toy_manifest(),
        parameters=_toy_parameters(),
        resources=custom,
        require_present=False,
    )
    assert len(payload["resources"]) == 1
    assert payload["resources"][0]["name"] == "custom"
