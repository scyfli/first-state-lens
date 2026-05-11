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


@pytest.fixture
def fixture_census_hit() -> bytes:
    return (FIXTURES / "census-geocode-hit.json").read_bytes()


@pytest.fixture
def fixture_census_miss() -> bytes:
    return (FIXTURES / "census-geocode-miss.json").read_bytes()


@pytest.fixture
def fixture_nominatim_hit() -> bytes:
    return (FIXTURES / "nominatim-hit.json").read_bytes()


@pytest.fixture
def fixture_nominatim_miss() -> bytes:
    return (FIXTURES / "nominatim-miss.json").read_bytes()


@pytest.fixture
def fixture_nominatim_disagree() -> bytes:
    return (FIXTURES / "nominatim-disagree.json").read_bytes()


@pytest.fixture
def fixture_dsb_page_pending() -> str:
    return (FIXTURES / "dsb-page-pending.html").read_text(encoding="utf-8")


@pytest.fixture
def fixture_dsb_page_published() -> str:
    return (FIXTURES / "dsb-page-published.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_nominatim_rate_limit():
    """Reset Nominatim rate-limit state between tests so a slow sleep
    isn't carried across unrelated tests. Auto-applied."""
    try:
        from etl.lib.geocode import _reset_rate_limit_state_for_tests
        _reset_rate_limit_state_for_tests()
    except ImportError:
        pass
    yield
