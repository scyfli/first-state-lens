"""FEC (OpenFEC) puller — federal campaign finance for Delaware candidates.

Source: https://api.open.fec.gov/v1  (fronted by api.data.gov; free key)
License: Public domain (US Federal Election Commission work; open API)
Cadence: Filings are periodic (quarterly + pre/post-election); the most recent
         filing lags current fundraising. Refresh weekly; the data is as-filed.
Output: <out>/campaign-finance-summary.json  +  <out>/manifest.json

Reads FEC_API_KEY from the environment (the free api.data.gov key). The orchestrated
path threads the key the same way the census/openstates pullers do; a missing key
raises (silent-zero discipline) rather than silently pulling with DEMO_KEY's tiny quota.

Neutrality posture (this is a MOST-CHARGED dashboard, same class as Votes):
report the raw as-filed numbers only — receipts, disbursements, cash on hand — per
candidate, grouped by office. Party is carried as a FACTUAL label (FEC's own field),
never a color-encoded or ranked signal. No "who's winning the money race" framing, no
totals-as-scoreboard. The citizen sees what each candidate raised and spent, sourced to
the FEC, and decides. We report FEC-registered 2026-cycle candidates; that is distinct
from who is certified on the Delaware ballot (the Candidate Record dashboard covers that).

Run standalone:
    FEC_API_KEY=... python3 -m etl.sources.fec_de --out campaign-finance/data
    FEC_API_KEY=... python3 -m etl.sources.fec_de --out campaign-finance/data --cycle 2026
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

import requests

API_BASE = "https://api.open.fec.gov/v1"
DEFAULT_CYCLE = 2026
STATE = "DE"

UA = "FirstStateLens-ETL/0.1 (+https://firststatelens.com; contact: mark.sanders3@gmail.com)"
OUT_SUMMARY = "campaign-finance-summary.json"
OUT_MANIFEST = "manifest.json"


def _utc_now() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _key() -> str:
    k = os.environ.get("FEC_API_KEY")
    if not k:
        raise RuntimeError("FEC_API_KEY not set (silent-zero guard); the free api.data.gov key is required.")
    return k


def _get(path: str, params: dict, *, attempts: int = 4) -> dict:
    """GET with simple exponential backoff on transient failures."""
    url = f"{API_BASE}{path}"
    params = {**params, "api_key": _key()}
    last_err = None
    for i in range(attempts):
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=(10, 90))
            if 500 <= resp.status_code < 600 or resp.status_code == 429:
                raise RuntimeError(f"HTTP {resp.status_code} (transient)")
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 — retry envelope
            last_err = exc
            if i < attempts - 1:
                time.sleep(2 ** i)
    raise RuntimeError(f"OpenFEC GET {path} failed after {attempts}: {last_err}")


def _num(v) -> float | None:
    """Cast to float; None stays None so the page renders '—', never a fake 0."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pull_candidate_totals(cycle: int) -> list[dict]:
    """Every DE candidate's as-filed financial totals for the cycle (one paginated call set)."""
    rows: list[dict] = []
    page = 1
    while True:
        data = _get(
            "/candidates/totals/",
            {
                "state": STATE,
                "election_year": cycle,
                "cycle": cycle,
                "per_page": 100,
                "page": page,
                "sort": "-receipts",
            },
        )
        for r in data.get("results", []):
            office = r.get("office_full") or {"H": "House", "S": "Senate", "P": "President"}.get(r.get("office"), r.get("office") or "—")
            rows.append(
                {
                    "name": r.get("name") or "—",
                    "candidate_id": r.get("candidate_id"),
                    "office": office,
                    "party": r.get("party") or "—",
                    "incumbency": r.get("incumbent_challenge_full") or "—",
                    "receipts": _num(r.get("receipts")),
                    "disbursements": _num(r.get("disbursements")),
                    "cash_on_hand": _num(r.get("last_cash_on_hand_end_period")),
                    "coverage_end": r.get("coverage_end_date"),
                }
            )
        pages = (data.get("pagination") or {}).get("pages") or 1
        if page >= pages:
            break
        page += 1
    return rows


def pull(out_dir: Path, *, cycle: int = DEFAULT_CYCLE) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates = _pull_candidate_totals(cycle)
    # Silent-zero guard: a real DE federal cycle has multiple candidates with filed receipts.
    with_receipts = [c for c in candidates if (c["receipts"] or 0) > 0]
    if not candidates or not with_receipts:
        raise RuntimeError(
            f"OpenFEC returned {len(candidates)} DE candidates and {len(with_receipts)} with receipts "
            f"for cycle {cycle} — refusing to write empty data (silent-zero guard)."
        )

    # Order: by office, then receipts desc — the page keeps this but never labels it a ranking.
    candidates.sort(key=lambda c: (c["office"], -(c["receipts"] or 0)))

    total_receipts = sum(c["receipts"] or 0 for c in candidates)
    total_disbursements = sum(c["disbursements"] or 0 for c in candidates)
    offices = sorted({c["office"] for c in candidates})

    summary = {
        "generated_at": _utc_now(),
        "cycle": cycle,
        "scope": f"Delaware federal candidates, {cycle} election cycle",
        "scope_note": (
            "Money raised and spent by candidates for U.S. House and U.S. Senate from Delaware, "
            "as reported to the Federal Election Commission. Amounts are as-filed and the most "
            "recent filing may lag current activity. FEC registration is not the Delaware ballot: "
            "a registered candidate may or may not be certified on the November ballot."
        ),
        "offices": offices,
        "candidates": candidates,
        "totals": {
            "candidate_count": len(candidates),
            "candidates_with_receipts": len(with_receipts),
            "total_receipts": total_receipts,
            "total_disbursements": total_disbursements,
        },
        "source": {
            "name": "Federal Election Commission (OpenFEC)",
            "endpoint": f"{API_BASE}/candidates/totals/",
            "license": "U.S. Government public domain",
            "url": "https://www.fec.gov/data/",
        },
    }

    (out_dir / OUT_SUMMARY).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    manifest = {
        "generated_at": summary["generated_at"],
        "dashboard": "federal-campaign-finance",
        "cycle": cycle,
        "sources": {"openfec": summary["source"]},
        "row_counts": {
            "candidates": len(candidates),
            "candidates_with_receipts": len(with_receipts),
            "offices": len(offices),
        },
    }
    (out_dir / OUT_MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull Delaware federal campaign finance (OpenFEC).")
    parser.add_argument("--out", type=Path, default=Path("campaign-finance/data"))
    parser.add_argument("--cycle", type=int, default=DEFAULT_CYCLE)
    args = parser.parse_args(argv)

    summary = pull(args.out, cycle=args.cycle)
    t = summary["totals"]
    print(f"wrote {args.out}/{OUT_SUMMARY}")
    print(f"  cycle {summary['cycle']}: {t['candidate_count']} DE candidates "
          f"({t['candidates_with_receipts']} with filed receipts) across {len(summary['offices'])} offices")
    print(f"  total receipts ${t['total_receipts']:,.0f} · total disbursements ${t['total_disbursements']:,.0f}")
    top = summary["candidates"][0] if summary["candidates"] else None
    if top:
        print(f"  example: {top['name']} ({top['office']}) receipts "
              f"${(top['receipts'] or 0):,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
