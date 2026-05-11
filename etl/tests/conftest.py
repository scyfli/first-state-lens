"""Shared pytest fixtures and path bootstrap.

Adds the repo root to sys.path so `import etl.lib.fetch` works when
pytest is invoked from any directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Ensure `import etl.X` resolves regardless of pytest invocation dir.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def fixture_sd2_geojson() -> bytes:
    return (FIXTURES / "sd2-toy.geojson").read_bytes()


@pytest.fixture
def fixture_mmg_csv() -> bytes:
    return (FIXTURES / "mmg-toy.csv").read_bytes()


@pytest.fixture
def fixture_acs_json() -> bytes:
    return (FIXTURES / "acs-toy.json").read_bytes()
