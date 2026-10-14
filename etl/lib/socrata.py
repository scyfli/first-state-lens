"""Polite, keyless client for data.delaware.gov (Socrata SODA + view metadata).

- Identifying User-Agent (same string as etl/sources/de_candidates.py).
- At most one request every 2 seconds to the state portal.
- Retries with backoff on 429/5xx and network errors; any other error raises.
- A SoQL error comes back as a JSON object, not a list: that raises too, so a bad
  query can never be read as "zero rows".
"""

from __future__ import annotations

import datetime
import time

import requests

UA = "FirstStateLens-ETL/0.1 (+https://firststatelens.com; contact: mark.sanders3@gmail.com)"
PORTAL = "https://data.delaware.gov"
MIN_INTERVAL_S = 2.0
_last_call = [0.0]


def _get(url: str, params: dict | None = None, tries: int = 4):
    last: Exception | None = None
    for i in range(tries):
        wait = _last_call[0] + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        try:
            r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=(10, 120))
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code} from {url}")
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, RuntimeError) as e:
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url} failed after {tries} tries: {last}")


def soql(dataset_id: str, params: dict) -> list[dict]:
    data = _get(f"{PORTAL}/resource/{dataset_id}.json", params)
    if not isinstance(data, list):
        raise RuntimeError(f"Socrata {dataset_id} query error: {str(data)[:200]}")
    return data


def metadata(dataset_id: str) -> dict:
    data = _get(f"{PORTAL}/api/views/{dataset_id}.json")
    if not isinstance(data, dict) or data.get("id") != dataset_id:
        raise RuntimeError(f"Socrata {dataset_id} metadata missing or mismatched")
    return data


def rows_updated(meta: dict) -> str:
    """The portal's own 'rows last updated' stamp as a UTC date (YYYY-MM-DD)."""
    ts = meta.get("rowsUpdatedAt")
    if not ts:
        raise RuntimeError("source metadata has no rowsUpdatedAt stamp")
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).date().isoformat()


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
