"""Smoke tests for etl.lib.fetch.

These tests stub `requests.Session.get` so they run offline. A live
network test is gated behind the RUN_LIVE_NETWORK_TESTS environment
variable and exists as a sanity check, not part of the default suite.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
import requests

from etl.lib.fetch import TransientHTTPError, fetch


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes, headers: dict | None = None) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 500:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Client Error"
            )


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls = 0

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls += 1
        return self._response


def test_fetch_happy_path() -> None:
    fake_response = _FakeResponse(200, b"hello world", {"Content-Type": "text/plain"})
    fake_session = _FakeSession(fake_response)

    result = fetch("https://example.com/x", session=fake_session)

    assert result.http_status == 200
    assert result.body == b"hello world"
    assert result.content_type == "text/plain"
    assert result.text() == "hello world"
    # sha256 of 'hello world'
    assert (
        result.sha256
        == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    )
    assert result.last_fetched.endswith("Z")
    assert fake_session.calls == 1


def test_fetch_raises_on_4xx() -> None:
    fake_session = _FakeSession(_FakeResponse(404, b"not found"))
    with pytest.raises(requests.exceptions.HTTPError, match="404"):
        fetch("https://example.com/missing", session=fake_session)


def test_fetch_retries_on_5xx_then_raises() -> None:
    """tenacity should retry transient HTTP 5xx until attempts exhaust."""
    fake_session = _FakeSession(_FakeResponse(503, b""))
    with pytest.raises(TransientHTTPError):
        fetch("https://example.com/down", session=fake_session)
    # Default is 5 attempts.
    assert fake_session.calls == 5


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_NETWORK_TESTS") != "1",
    reason="live network test; set RUN_LIVE_NETWORK_TESTS=1 to enable",
)
def test_fetch_live_example_com() -> None:
    """Live sanity check; opt-in via env var. Not run in CI by default."""
    result = fetch("https://example.com/")
    assert result.http_status == 200
    assert b"Example Domain" in result.body
