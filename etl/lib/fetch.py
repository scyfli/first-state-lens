"""HTTP fetch with retries, sane defaults, and audit-trail metadata.

The puller-facing API is `fetch(url, ...)` which returns a `FetchResult`
dataclass carrying the response bytes plus everything the orchestrator
needs to write into manifest.json:

  - url:          the canonical URL fetched
  - http_status:  HTTP status code
  - sha256:       hex digest of response body
  - last_fetched: ISO8601 UTC timestamp
  - content_type: response Content-Type header (if any)
  - elapsed_ms:   wall-clock duration of the request
  - warnings:     list of soft issues (e.g., unexpected content-type)

Retries are exponential-backoff via `tenacity`. We retry on transient
network errors and 5xx responses; 4xx fails immediately. Default timeout
is 60s connect + read.

The Nominatim usage policy (1 req/sec, custom UA required) is handled by
the geocoding puller specifically, not here — this is the generic client.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import time
from typing import Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)


DEFAULT_USER_AGENT = (
    "FirstStateLens-ETL/0.1 "
    "(+https://firststatelens.com; contact: mark.sanders3@gmail.com)"
)

DEFAULT_TIMEOUT_S = (10.0, 60.0)  # (connect, read)
DEFAULT_MAX_ATTEMPTS = 5


@dataclasses.dataclass
class FetchResult:
    url: str
    http_status: int
    body: bytes
    sha256: str
    last_fetched: str
    content_type: Optional[str]
    elapsed_ms: int
    warnings: list[str]

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding)


class TransientHTTPError(Exception):
    """Raised for HTTP 5xx so tenacity can retry."""


def _utc_now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_hex(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@retry(
    retry=(
        retry_if_exception_type(requests.exceptions.ConnectionError)
        | retry_if_exception_type(requests.exceptions.Timeout)
        | retry_if_exception_type(TransientHTTPError)
    ),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(DEFAULT_MAX_ATTEMPTS),
    reraise=True,
)
def fetch(
    url: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: tuple[float, float] = DEFAULT_TIMEOUT_S,
    extra_headers: Optional[dict] = None,
    session: Optional[requests.Session] = None,
) -> FetchResult:
    """Issue a GET request with retries and return a FetchResult.

    Raises:
      requests.exceptions.HTTPError on 4xx (no retry)
      TransientHTTPError on 5xx after exhausted retries
      requests.exceptions.ConnectionError / Timeout after exhausted retries
    """
    headers = {"User-Agent": user_agent}
    if extra_headers:
        headers.update(extra_headers)

    sess = session or requests.Session()
    warnings: list[str] = []
    t0 = time.monotonic()

    resp = sess.get(url, headers=headers, timeout=timeout)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if 500 <= resp.status_code < 600:
        raise TransientHTTPError(
            f"HTTP {resp.status_code} from {url} (transient; will retry)"
        )
    resp.raise_for_status()  # raises on 4xx

    body = resp.content
    return FetchResult(
        url=url,
        http_status=resp.status_code,
        body=body,
        sha256=_sha256_hex(body),
        last_fetched=_utc_now_iso(),
        content_type=resp.headers.get("Content-Type"),
        elapsed_ms=elapsed_ms,
        warnings=warnings,
    )
