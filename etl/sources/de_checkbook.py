"""Delaware Online Checkbook puller — state spending (where the money goes).

Source: https://data.delaware.gov/resource/5s6n-7hpx.json  (Socrata SODA API)
        "State of Delaware Checkbook" — leaner schema WITH a human-readable
        `category` column (the detail table 7bip-nb4g lacks it).
License: Open data (Delaware Open Data Portal / Tyler Data & Insights)
Cadence: Monthly
Output: <out>/spending-summary.json + <out>/manifest.json

The table has ~14M transaction rows, so this puller NEVER pulls rows — it
asks Socrata to aggregate server-side via SoQL ($select=sum(amount), $group).
Amounts come back as JSON strings; we cast in Python. Fail-loud on a zero/empty
aggregate (the silent-zero discipline).

Citizen question: "What does Delaware spend, on what, and with which vendors?"
These are ACTUAL disbursements (checks written), not the budgeted/appropriated
side (which is PDF-bound at OMB) — the neutrality header on the page says so.

Run standalone:
    python3 -m etl.sources.de_checkbook --out spending/data
    python3 -m etl.sources.de_checkbook --out spending/data --fy 2025
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

from etl.lib.fetch import fetch

DATASET = "5s6n-7hpx"
BASE = f"https://data.delaware.gov/resource/{DATASET}.json"
OUT_SUMMARY = "spending-summary.json"
OUT_MANIFEST = "manifest.json"


def _utc_now() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _soql(params: dict) -> list[dict]:
    url = f"{BASE}?{urlencode(params)}"
    result = fetch(url)
    data = json.loads(result.body)
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected SoQL response from {url}: {type(data)}")
    return data


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _latest_fy_in_data() -> int:
    rows = _soql({"$select": "max(fiscal_year) as mx"})
    if not rows or rows[0].get("mx") in (None, ""):
        raise RuntimeError("Could not determine latest fiscal_year from checkbook.")
    return int(float(rows[0]["mx"]))


def _de_latest_complete_fy() -> int:
    """Delaware FY ends June 30 and is labeled by its ending calendar year.
    The most recent COMPLETE FY as of today avoids headlining a partial year."""
    today = datetime.date.today()
    return today.year if today.month >= 7 else today.year - 1


def _default_fy() -> int:
    """Latest complete FY that actually has data (min of the two)."""
    return min(_latest_fy_in_data(), _de_latest_complete_fy())


def _grouped(field: str, fy: int, limit: int) -> list[dict]:
    rows = _soql(
        {
            "$select": f"{field}, sum(amount) as total, count(*) as n",
            "$where": f"fiscal_year={fy}",
            "$group": field,
            "$order": "total DESC",
            "$limit": str(limit),
        }
    )
    out = []
    for r in rows:
        label = (r.get(field) or "").strip() or "(unspecified)"
        out.append({"label": label, "total": _f(r.get("total")), "count": int(_f(r.get("n")))})
    return out


def pull(out_dir: Path, *, fy: int | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    if fy is None:
        fy = _default_fy()

    totals = _soql(
        {"$select": "sum(amount) as total, count(*) as n", "$where": f"fiscal_year={fy}"}
    )
    total_spend = _f(totals[0].get("total")) if totals else 0.0
    txn_count = int(_f(totals[0].get("n"))) if totals else 0
    # Silent-zero guard: a real Delaware fiscal year is billions of dollars.
    if total_spend <= 0 or txn_count == 0:
        raise RuntimeError(
            f"Checkbook returned ${total_spend:,.0f} / {txn_count} txns for FY{fy} "
            "— refusing to write empty data (silent-zero guard)."
        )

    by_department = _grouped("department", fy, 15)
    by_category = _grouped("category", fy, 12)
    by_vendor = _grouped("vendor", fy, 20)

    summary = {
        "generated_at": _utc_now(),
        "fiscal_year": fy,
        "total_spend": total_spend,
        "transaction_count": txn_count,
        "by_department": by_department,
        "by_category": by_category,
        "by_vendor": by_vendor,
        "source": {
            "name": "Delaware Online Checkbook (data.delaware.gov)",
            "dataset": DATASET,
            "endpoint": BASE,
            "license": "Delaware Open Data Portal — open data",
            "url": "https://data.delaware.gov/Government-and-Finance/State-of-Delaware-Checkbook/5s6n-7hpx",
            "note": "Actual disbursements (checks written), not budgeted/appropriated amounts.",
        },
    }

    (out_dir / OUT_SUMMARY).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    manifest = {
        "generated_at": summary["generated_at"],
        "dashboard": "state-spending",
        "fiscal_year": fy,
        "sources": {"de_checkbook": summary["source"]},
        "row_counts": {
            "departments": len(by_department),
            "categories": len(by_category),
            "vendors": len(by_vendor),
            "total_spend": total_spend,
            "transactions": txn_count,
        },
    }
    (out_dir / OUT_MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull Delaware state spending (Online Checkbook).")
    parser.add_argument("--out", type=Path, default=Path("spending/data"))
    parser.add_argument("--fy", type=int, default=None)
    args = parser.parse_args(argv)

    s = pull(args.out, fy=args.fy)
    print(f"wrote {args.out}/{OUT_SUMMARY}")
    print(f"  FY{s['fiscal_year']}: ${s['total_spend']:,.0f} across {s['transaction_count']:,} transactions")
    if s["by_department"]:
        d = s["by_department"][0]
        print(f"  top department: {d['label']} (${d['total']:,.0f})")
    if s["by_category"]:
        c = s["by_category"][0]
        print(f"  top category:   {c['label']} (${c['total']:,.0f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
