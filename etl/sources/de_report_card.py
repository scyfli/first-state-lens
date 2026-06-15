"""Delaware School Report Card puller — district-level outcomes.

Source: https://data.delaware.gov  (Socrata SODA, keyless) — DOE Report Card datasets
  ms6b-mt82  Student Assessment Performance (proficiency)
  crb4-kdc7  Student Attendance (chronic absenteeism)
  t7e6-zcnn  Student Graduation (4-year rate)
  6i7v-xnmf  Student Enrollment
License: Delaware Open Data Portal — open data
Cadence: Annual (per school year)
Output: <out>/schools-summary.json + <out>/manifest.json

Accuracy gates (see ISA D13):
  - schoolcode='0' is the AGGREGATE total: districtcode='0' => statewide, districtcode>0
    => district total. Schools have real schoolcodes. We pull only schoolcode='0'.
  - Numeric fields are ABSENT on rowstatus='REDACTED' rows — we filter rowstatus='REPORTED'
    so suppressed cells become missing (null → "—" on the page), never zero or text.
  - Proficiency uses the 'Smarter Balanced Summative Assessment' (the statewide 3-8 test),
    grade='All Students', so ELA/Math are one comparable number per LEA — NOT mixed with
    the SAT or the alternate assessment.
  - Each metric carries its OWN latest school year (graduation lags ~2 years); the page
    labels the vintage per metric and never implies they share a year.

Run standalone:
    python3 -m etl.sources.de_report_card --out schools/data
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import requests

PORTAL = "https://data.delaware.gov/resource"
SBAC = "Smarter Balanced Summative Assessment"
OUT_SUMMARY = "schools-summary.json"
OUT_MANIFEST = "manifest.json"


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _soql(ds: str, params: dict) -> list[dict]:
    r = requests.get(f"{PORTAL}/{ds}.json", params=params, timeout=(10, 90),
                    headers={"User-Agent": "FirstStateLens-ETL/0.1 (+https://firststatelens.com)"})
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Socrata {ds} returned non-list (query error): {str(data)[:160]}")
    return data


def _max_year(ds: str) -> str:
    # Some DOE datasets carry a junk 'SchoolYear' literal in the year column, and
    # string max() sorts it above real years — pick the max 4-digit numeric year.
    rows = _soql(ds, {"$select": "schoolyear", "$group": "schoolyear", "$limit": "80"})
    yrs = [str(r.get("schoolyear", "")) for r in rows]
    yrs = [y for y in yrs if y.isdigit() and len(y) == 4]
    if not yrs:
        raise RuntimeError(f"No numeric schoolyear in {ds}")
    return max(yrs)


def _clean(s: str) -> str:
    return (s or "").strip()


def pull(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    assess_yr = _max_year("ms6b-mt82")
    att_yr = _max_year("crb4-kdc7")
    enr_yr = _max_year("6i7v-xnmf")
    grad_yr = _max_year("t7e6-zcnn")

    def assess(content):
        return _soql("ms6b-mt82", {
            "$where": (f"rowstatus='REPORTED' AND subgroup='All Students' AND grade='All Students' "
                       f"AND assessmentname='{SBAC}' AND contentarea='{content}' AND schoolcode='0' "
                       f"AND schoolyear='{assess_yr}'"),
            "$select": "districtcode,district,pctproficient", "$limit": "200"})

    ela = {r["districtcode"]: _num(r.get("pctproficient")) for r in assess("ELA")}
    math = {r["districtcode"]: _num(r.get("pctproficient")) for r in assess("MATH")}

    att = {r["districtcode"]: _num(r.get("pctstudentschronicallyabsent")) for r in _soql("crb4-kdc7", {
        "$where": (f"rowstatus='REPORTED' AND subgroup='All Students' AND grade='All Students' "
                   f"AND schoolcode='0' AND schoolyear='{att_yr}'"),
        "$select": "districtcode,district,pctstudentschronicallyabsent", "$limit": "200"})}

    enr = {}
    names = {}
    for r in _soql("6i7v-xnmf", {
        "$where": (f"subgroup='All Students' AND grade='All Students' AND schoolcode='0' "
                   f"AND schoolyear='{enr_yr}'"),
        "$select": "districtcode,district,eoyenrollment", "$limit": "200"}):
        enr[r["districtcode"]] = _num(r.get("eoyenrollment"))
        names[r["districtcode"]] = _clean(r.get("district"))

    grad = {r["districtcode"]: _num(r.get("pctgraduates")) for r in _soql("t7e6-zcnn", {
        "$where": (f"rowstatus='REPORTED' AND subgroup='All Students' AND schoolcode='0' "
                   f"AND ratetype='4-year graduation rate' AND schoolyear='{grad_yr}'"),
        "$select": "districtcode,district,pctgraduates", "$limit": "200"})}

    # Collect district names from every source (some appear in one but not another).
    for src in (ela, math, att, enr, grad):
        pass
    for r_src, ds in (("ms6b-mt82", None),):
        pass
    # Names: prefer enrollment; backfill from assessment query.
    for dc in set(list(ela) + list(math) + list(att) + list(grad)):
        if dc not in names:
            names[dc] = None
    # Backfill missing names via a directory-ish query on assessment.
    if any(v is None for v in names.values()):
        for r in _soql("ms6b-mt82", {"$select": "districtcode,district", "$group": "districtcode,district", "$limit": "300"}):
            dc = r["districtcode"]
            if names.get(dc) is None:
                names[dc] = _clean(r.get("district"))

    def rec(dc):
        return {
            "districtcode": dc,
            "district": names.get(dc) or dc,
            "enrollment": int(enr[dc]) if enr.get(dc) is not None else None,
            "ela_proficient": ela.get(dc),
            "math_proficient": math.get(dc),
            "chronic_absenteeism": att.get(dc),
            "grad_rate": grad.get(dc),
        }

    state = rec("0")
    if state["ela_proficient"] is None:
        raise RuntimeError("State ELA proficiency missing — query/filter failure (silent-zero guard).")

    district_codes = sorted([dc for dc in names if dc != "0"], key=lambda dc: (names.get(dc) or dc).lower())
    districts = [rec(dc) for dc in district_codes]
    # Keep only LEAs that have at least one real metric (drop empty shells).
    districts = [d for d in districts if any(d[k] is not None for k in ("enrollment", "ela_proficient", "math_proficient", "chronic_absenteeism", "grad_rate"))]
    if len(districts) < 10:
        raise RuntimeError(f"Only {len(districts)} districts with data — likely a filter failure (silent-zero guard).")

    summary = {
        "generated_at": _utc_now(),
        "vintages": {
            "proficiency": assess_yr, "chronic_absenteeism": att_yr,
            "enrollment": enr_yr, "graduation": grad_yr,
        },
        "assessment": SBAC,
        "state": state,
        "districts": districts,
        "source": {
            "name": "Delaware Report Card (data.delaware.gov / DOE)",
            "datasets": {"assessment": "ms6b-mt82", "attendance": "crb4-kdc7",
                         "graduation": "t7e6-zcnn", "enrollment": "6i7v-xnmf"},
            "license": "Delaware Open Data Portal — open data",
            "url": "https://reportcard.doe.k12.de.us/",
            "note": "Proficiency = Smarter Balanced Summative (statewide 3-8 test), All Students, REPORTED only.",
        },
    }

    (out_dir / OUT_SUMMARY).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / OUT_MANIFEST).write_text(json.dumps({
        "generated_at": summary["generated_at"], "dashboard": "schools",
        "vintages": summary["vintages"], "sources": summary["source"],
        "row_counts": {"districts": len(districts)},
    }, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull Delaware School Report Card (district level).")
    parser.add_argument("--out", type=Path, default=Path("schools/data"))
    args = parser.parse_args(argv)
    s = pull(args.out)
    v = s["vintages"]
    st = s["state"]
    print(f"wrote {args.out}/{OUT_SUMMARY}  ({len(s['districts'])} districts)")
    print(f"  vintages: proficiency FY{v['proficiency']}, chronic-abs FY{v['chronic_absenteeism']}, "
          f"enroll FY{v['enrollment']}, grad FY{v['graduation']}")
    enr = f"{st['enrollment']:,}" if st['enrollment'] is not None else "—"
    print(f"  STATE: ELA {st['ela_proficient']}% · Math {st['math_proficient']}% · "
          f"chronic-abs {st['chronic_absenteeism']}% · grad {st['grad_rate']}% · enroll {enr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
