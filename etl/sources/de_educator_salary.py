"""Delaware educator salary by LEA (district or charter school), classroom teachers.

Sources: https://data.delaware.gov (Socrata SODA, keyless), Delaware Department of Education
  5tvj-rx46  Educator Salary Distribution
             "counts of full-time staff across 12 salary ranges". The dataset has NO average
             or median field; we publish its range counts as given.
  rv4m-vy79  Educator Average Salary
             "average total, federal, state, and local salaries for full-time staff". We publish
             the field "Average Total Salary" (average_total_salary) and "Educators (FTE)".
License: Delaware Open Data Portal, open data
Cadence: annual (school year; 2026 = the school year that ended June 2026)
Output: <out>/educator-salary.json + <out>/educator-salary-manifest.json

Filters (identical for every LEA and the state row):
  schoolcode = 0 (LEA or state total), subgroup = 'All Educators',
  staff_type = 'Professional', staff_category = 'Classroom Teacher', job_classification = 'ALL'
  rv4m-vy79 also experience = 'ALL'.
Each dataset uses its own latest COMPLETE school year: the newest year whose state row exists
and whose LEA-row count is at least 90% of the largest LEA-row count in any year.

Neutrality and accuracy:
  - Range counts are FTE-like (fractions occur); rounded to 0.1 to remove float noise.
  - A range missing from a row is written as 0 only when the ranges present add up to the row's
    own total (so the missing ones are provably zero). Otherwise it is null ("Not reported").
  - No people: every row is an aggregate for the state or a public LEA.

Silent-zero guard: fewer than MIN_LEAS LEAs, or no state row, in either dataset => raise, write nothing.

Run standalone:
    python3 -m etl.sources.de_educator_salary --out schools/data
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

import requests

PORTAL = "https://data.delaware.gov"
UA = "FirstStateLens-ETL/0.1 (+https://firststatelens.com; contact: mark.sanders3@gmail.com)"
DIST_DS = "5tvj-rx46"
AVG_DS = "rv4m-vy79"
OUT_FILE = "educator-salary.json"
OUT_MANIFEST = "educator-salary-manifest.json"
MIN_LEAS = 30
MIN_INTERVAL_S = 2.0

# (key, label) in the dataset's own order; key = column suffix after "staffcount_salary_".
RANGES = [
    ("lt_30k", "Less than $30K"),
    ("30k_37k", "$30K to $37K"),
    ("37k_44k", "$37K to $44K"),
    ("44k_51k", "$44K to $51K"),
    ("51k_58k", "$51K to $58K"),
    ("58k_65k", "$58K to $65K"),
    ("65k_72k", "$65K to $72K"),
    ("72k_79k", "$72K to $79K"),
    ("79k_86k", "$79K to $86K"),
    ("86k_93k", "$86K to $93K"),
    ("93k_100k", "$93K to $100K"),
    ("gt_100k", "More than $100K"),
]

BASE_WHERE = ("schoolcode=0 AND subgroup='All Educators' AND staff_type='Professional' "
              "AND staff_category='Classroom Teacher' AND job_classification='ALL'")
AVG_WHERE = BASE_WHERE + " AND experience='ALL'"

_last_request = [0.0]


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _get(url: str, params: dict | None = None):
    """GET with the repo User-Agent, one request per MIN_INTERVAL_S, retries on 429/5xx."""
    for attempt in range(4):
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()
        try:
            r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=(10, 120))
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt * 2)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == 3:
                r.raise_for_status()
            time.sleep(2 ** attempt * 2)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"unreachable: {url}")


def _soql(ds: str, params: dict) -> list[dict]:
    data = _get(f"{PORTAL}/resource/{ds}.json", params)
    if not isinstance(data, list):
        raise RuntimeError(f"Socrata {ds} returned non-list (query error): {str(data)[:160]}")
    return data


def _view_updated(ds: str) -> str | None:
    """The portal's own 'rows updated' stamp for a dataset, as YYYY-MM-DD (UTC)."""
    meta = _get(f"{PORTAL}/api/views/{ds}.json")
    ts = meta.get("rowsUpdatedAt") if isinstance(meta, dict) else None
    if not ts:
        return None
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).date().isoformat()


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _r1(x: float) -> float:
    return round(x + 0.0, 1)


def parse_distribution_row(row: dict) -> dict:
    """One 5tvj-rx46 row -> {"total", "counts" (ordered as RANGES), "complete"}."""
    total = _num(row.get("total"))
    present = {k: _num(row.get(f"staffcount_salary_{k}")) for k, _ in RANGES}
    have = sum(v for v in present.values() if v is not None)
    complete = total is not None and abs(have - total) <= 0.15
    counts = {}
    for k, _ in RANGES:
        v = present[k]
        counts[k] = _r1(v) if v is not None else (0.0 if complete else None)
    return {"total": _r1(total) if total is not None else None, "counts": counts, "complete": complete}


def pick_complete_year(lea_counts: dict[str, int], has_state: set[str]) -> str:
    """Newest numeric year with a state row and >= 90% of the largest LEA-row count."""
    years = sorted((y for y in lea_counts if y.isdigit() and len(y) == 4), reverse=True)
    if not years:
        raise RuntimeError("No numeric school years (silent-zero guard).")
    peak = max(lea_counts[y] for y in years)
    for y in years:
        if y in has_state and lea_counts[y] >= 0.9 * peak:
            return y
    raise RuntimeError("No complete school year found (silent-zero guard).")


def _latest_complete_year(ds: str, where: str) -> str:
    rows = _soql(ds, {"$select": "schoolyear,districtcode,count(*)", "$where": where,
                      "$group": "schoolyear,districtcode", "$limit": "5000"})
    lea_counts: dict[str, int] = {}
    has_state: set[str] = set()
    for r in rows:
        y = str(r.get("schoolyear", ""))
        if str(r.get("districtcode")) == "0":
            has_state.add(y)
        else:
            lea_counts[y] = lea_counts.get(y, 0) + 1
    return pick_complete_year(lea_counts, has_state)


def pull(out_dir: Path) -> dict:
    # --- distribution (5tvj-rx46)
    dist_yr = _latest_complete_year(DIST_DS, BASE_WHERE)
    dist_rows = _soql(DIST_DS, {
        "$where": f"{BASE_WHERE} AND schoolyear='{dist_yr}'",
        "$select": "districtcode,districtname,total," + ",".join(f"staffcount_salary_{k}" for k, _ in RANGES),
        "$order": "districtcode", "$limit": "500"})
    dist_state, dist_leas = None, {}
    for r in dist_rows:
        dc = str(r.get("districtcode"))
        rec = parse_distribution_row(r)
        if dc == "0":
            dist_state = rec
        else:
            rec["district"] = (r.get("districtname") or "").strip()
            dist_leas[dc] = rec

    # --- average (rv4m-vy79)
    avg_yr = _latest_complete_year(AVG_DS, AVG_WHERE)
    avg_rows = _soql(AVG_DS, {
        "$where": f"{AVG_WHERE} AND schoolyear='{avg_yr}'",
        "$select": "districtcode,district,average_total_salary,educators_fte",
        "$order": "districtcode", "$limit": "500"})
    avg_state, avg_leas = None, {}
    for r in avg_rows:
        dc = str(r.get("districtcode"))
        a, fte = _num(r.get("average_total_salary")), _num(r.get("educators_fte"))
        rec = {"average_total_salary": round(a, 2) if a is not None else None,
               "educators_fte": _r1(fte) if fte is not None else None}
        if dc == "0":
            avg_state = rec
        else:
            rec["district"] = (r.get("district") or "").strip()
            avg_leas[dc] = rec

    # --- silent-zero guard (before any write)
    if dist_state is None or not dist_state["complete"] or avg_state is None or avg_state["average_total_salary"] is None:
        raise RuntimeError("State salary row missing or incomplete (silent-zero guard).")
    if len(dist_leas) < MIN_LEAS or len(avg_leas) < MIN_LEAS:
        raise RuntimeError(f"Only {len(dist_leas)}/{len(avg_leas)} LEAs with salary rows (silent-zero guard).")

    updated = {DIST_DS: _view_updated(DIST_DS), AVG_DS: _view_updated(AVG_DS)}
    data = {
        "generated_at": _utc_now(),
        "distribution": {
            "dataset": DIST_DS, "name": "Educator Salary Distribution",
            "schoolyear": dist_yr, "source_updated": updated[DIST_DS],
            "definition": "Counts of full-time staff in each of 12 salary ranges (fractions are part-time shares as published).",
            "filters": BASE_WHERE,
            "ranges": [{"key": k, "label": lbl} for k, lbl in RANGES],
            "state": dist_state,
            "leas": {dc: dist_leas[dc] for dc in sorted(dist_leas, key=int)},
        },
        "average": {
            "dataset": AVG_DS, "name": "Educator Average Salary",
            "schoolyear": avg_yr, "source_updated": updated[AVG_DS],
            "field": "average_total_salary",
            "definition": "Average Total Salary: average total salary for the particular set of educators (full-time staff).",
            "filters": AVG_WHERE,
            "state": avg_state,
            "leas": {dc: avg_leas[dc] for dc in sorted(avg_leas, key=int)},
        },
        "license": "Delaware Open Data Portal, open data",
        "publisher": "Delaware Department of Education",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / OUT_FILE).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / OUT_MANIFEST).write_text(json.dumps({
        "generated_at": data["generated_at"], "dashboard": "schools",
        "sources": {DIST_DS: f"{PORTAL}/d/{DIST_DS}", AVG_DS: f"{PORTAL}/d/{AVG_DS}"},
        "source_updated": updated,
        "vintages": {"distribution": dist_yr, "average": avg_yr},
        "row_counts": {"distribution_leas": len(dist_leas), "average_leas": len(avg_leas)},
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Pull Delaware classroom teacher salary by LEA.")
    p.add_argument("--out", type=Path, default=Path("schools/data"))
    a = p.parse_args(argv)
    d = pull(a.out)
    print(f"wrote {a.out}/{OUT_FILE}")
    print(f"  distribution {DIST_DS} SY{d['distribution']['schoolyear']}: {len(d['distribution']['leas'])} LEAs, "
          f"state total {d['distribution']['state']['total']}")
    print(f"  average {AVG_DS} SY{d['average']['schoolyear']}: {len(d['average']['leas'])} LEAs, "
          f"state ${d['average']['state']['average_total_salary']:,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
