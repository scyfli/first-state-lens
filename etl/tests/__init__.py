"""Smoke tests for the DGI Food Access ETL.

Tests are offline-by-default: they use fixtures under tests/fixtures/ and
mock HTTP via responses / requests-mock or by injecting a fake fetch
function. Live-network tests are explicitly opt-in via the
RUN_LIVE_NETWORK_TESTS=1 environment variable.

Run locally:
  python -m pytest etl/tests/ -v
"""
