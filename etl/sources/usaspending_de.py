"""USAspending.gov puller — federal awards flowing into Delaware.

Source: https://api.usaspending.gov  (POST /api/v2/search/...)
License: Public domain (US federal government work; openly licensed API)
Cadence: Contracts ~5 days after action (FPDS); financial assistance twice
         monthly (3rd, 6th, 18th, 21st).
Output: <out>/federal-summary.json  +  <out>/manifest.json

The USAspending search API is POST-based, so this puller uses requests.post
directly rather than the shared GET fetch() helper. It is otherwise built to
the same convention: standalone-runnable, audit metadata, fail-loud on a
zero/empty payload (the silent-zero discipline — a job that "succeeds" with no
rows is the failure mode this project has been bitten by before).

The dashboard answers a citizen question: "what federal money lands in
Delaware, from which agency, to whom, and of what kind." We report by
PLACE OF PERFORMANCE = DE (money spent in Delaware) as the headline, which is
distinct from recipient-state = DE; mixing them double-counts.

Run standalone:
    python3 -m etl.sources.usaspending_de --out federal/data
    python3 -m etl.sources.usaspending_de --out federal/data --fy 2024
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

import requests

API_BASE = "https://api.usaspending.gov/api/v2"
DELAWARE = {"country": "USA", "state": "DE"}
DEFAULT_FY = 2024

# Award-type code groups (USAspending taxonomy).
CONTRACTS = ["A", "B", "C", "D"]
GRANTS = ["02", "03", "04", "05"]
DIRECT_PAYMENTS = ["06", "10"]
LOANS = ["07", "08"]
OTHER = ["09", "11", "-1"]

UA = "FirstStateLens-ETL/0.1 (+https://firststatelens.com; contact: mark.sanders3@gmail.com)"
OUT_SUMMARY = "federal-summary.json"
OUT_MANIFEST = "manifest.json"


def _utc_now() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _fy_window(fy: int) -> dict:
    return {"start_date": f"{fy - 1}-10-01", "end_date": f"{fy}-09-30"}


def _post(path: str, payload: dict, *, attempts: int = 4) -> dict:
    """POST with simple exponential backoff on transient failures."""
    url = f"{API_BASE}{path}"
    last_err = None
    for i in range(attempts):
        try:
            resp = requests.post(
                url,
                json=payload,
                headers={"User-Agent": UA, "Content-Type": "application/json"},
                timeout=(10, 90),
            )
            if 500 <= resp.status_code < 600:
                raise RuntimeError(f"HTTP {resp.status_code} (transient)")
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 — retry envelope
            last_err = exc
            if i < attempts - 1:
                time.sleep(2 ** i)
    raise RuntimeError(f"USAspending POST {path} failed after {attempts}: {last_err}")


def _award_type_counts(fy: int) -> dict:
    """Count of DE place-of-performance awards by category (one call)."""
    payload = {
        "filters": {
            "time_period": [_fy_window(fy)],
            "place_of_performance_locations": [DELAWARE],
        }
    }
    data = _post("/search/spending_by_award_count/", payload)
    results = data.get("results", {})
    # Normalize to the citizen-facing buckets.
    return {
        "contracts": int(results.get("contracts", 0) or 0),
        "grants": int(results.get("grants", 0) or 0),
        "direct_payments": int(results.get("direct_payments", 0) or 0),
        "loans": int(results.get("loans", 0) or 0),
        "idvs": int(results.get("idvs", 0) or 0),
        "other": int(results.get("other", 0) or 0),
    }


def _top_awards(fy: int, award_type_codes: list[str], limit: int = 15) -> list[dict]:
    """Top awards by amount for a given type group, DE place-of-performance."""
    payload = {
        "filters": {
            "time_period": [_fy_window(fy)],
            "place_of_performance_locations": [DELAWARE],
            "award_type_codes": award_type_codes,
        },
        "fields": ["Award Amount", "Recipient Name", "Awarding Agency", "Award Type"],
        "sort": "Award Amount",
        "order": "desc",
        "limit": limit,
        "page": 1,
    }
    data = _post("/search/spending_by_award/", payload)
    rows = []
    for r in data.get("results", []):
        rows.append(
            {
                "recipient": r.get("Recipient Name") or "—",
                "amount": float(r.get("Award Amount") or 0),
                "agency": r.get("Awarding Agency") or "—",
                "type": r.get("Award Type") or "—",
            }
        )
    return rows


def pull(out_dir: Path, *, fy: int = DEFAULT_FY) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    counts = _award_type_counts(fy)
    total_awards = sum(counts.values())
    # Silent-zero guard: a real DE fiscal year has thousands of awards.
    if total_awards == 0:
        raise RuntimeError(
            "USAspending returned 0 DE awards for FY"
            f"{fy} — refusing to write empty data (silent-zero guard)."
        )

    top_contracts = _top_awards(fy, CONTRACTS, limit=15)
    top_grants = _top_awards(fy, GRANTS, limit=15)

    summary = {
        "generated_at": _utc_now(),
        "fiscal_year": fy,
        "scope": "place_of_performance=DE",
        "scope_note": "Money spent in Delaware (place of performance), not money to Delaware-based recipients.",
        "counts": counts,
        "total_awards": total_awards,
        "top_contracts": top_contracts,
        "top_grants": top_grants,
        "source": {
            "name": "USAspending.gov",
            "endpoint": f"{API_BASE}/search/spending_by_award/",
            "license": "U.S. Government public domain",
            "url": "https://www.usaspending.gov/",
        },
    }

    (out_dir / OUT_SUMMARY).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    manifest = {
        "generated_at": summary["generated_at"],
        "dashboard": "federal-dollars",
        "fiscal_year": fy,
        "sources": {"usaspending": summary["source"]},
        "row_counts": {
            "award_type_buckets": len([k for k, v in counts.items() if v]),
            "top_contracts": len(top_contracts),
            "top_grants": len(top_grants),
            "total_awards": total_awards,
        },
    }
    (out_dir / OUT_MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull federal awards into Delaware (USAspending).")
    parser.add_argument("--out", type=Path, default=Path("federal/data"))
    parser.add_argument("--fy", type=int, default=DEFAULT_FY)
    args = parser.parse_args(argv)

    summary = pull(args.out, fy=args.fy)
    c = summary["counts"]
    print(f"wrote {args.out}/{OUT_SUMMARY}")
    print(f"  FY{summary['fiscal_year']} DE place-of-performance awards: {summary['total_awards']:,}")
    print(f"  contracts={c['contracts']:,} grants={c['grants']:,} "
          f"direct={c['direct_payments']:,} loans={c['loans']:,} other={c['other']:,}")
    print(f"  top contract: {summary['top_contracts'][0]['recipient']} "
          f"(${summary['top_contracts'][0]['amount']:,.0f})" if summary["top_contracts"] else "  (no contracts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
