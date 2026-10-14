"""Delaware School Report Card puller — district-level outcomes.

Source: https://data.delaware.gov  (Socrata SODA, keyless) — DOE Report Card datasets
  ms6b-mt82  Student Assessment Performance (proficiency)
  crb4-kdc7  Student Attendance (chronic absenteeism)
  t7e6-zcnn  Student Graduation (4-year rate)
  6i7v-xnmf  Student Enrollment
  p3ez-si4g  Delaware Public Education Organization Directory (LEA type: Regular / Charter)
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

Additive keys (2026-10-14, Y3 district pages; every earlier key and value is unchanged):
  - districts[].lea_type: the directory's own District Type word ("Regular" or "Charter").
  - districts[].grad_rate_single_school: when an LEA has NO LEA-total graduation row and exactly
    one school-level 4-year row, and that row is REPORTED, {organization, schoolcode, value}.
    Context only; districts[].grad_rate stays null.
  - lea_directory: {dataset, schoolyear} for lea_type.
  - directory_leas_reported_within: LEAs the directory lists on their own that the report card
    files count as schools inside another district (e.g. Charter School of Wilmington under Red Clay).
  - source_updated: each dataset's own "rows updated" date from the portal.
Requests are throttled to one every 2 s with retries on 429/5xx.

Run standalone:
    python3 -m etl.sources.de_report_card --out schools/data
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

import requests

PORTAL = "https://data.delaware.gov/resource"
VIEWS = "https://data.delaware.gov/api/views"
UA = "FirstStateLens-ETL/0.1 (+https://firststatelens.com; contact: mark.sanders3@gmail.com)"
SBAC = "Smarter Balanced Summative Assessment"
OUT_SUMMARY = "schools-summary.json"
OUT_MANIFEST = "manifest.json"
DIRECTORY_DS = "p3ez-si4g"
MIN_DISTRICTS = 10
MIN_INTERVAL_S = 2.0

_last_request = [0.0]


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _get(url: str, params: dict | None = None):
    """GET with the repo User-Agent, one request per MIN_INTERVAL_S, retries on 429/5xx."""
    for attempt in range(4):
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()
        try:
            r = requests.get(url, params=params, timeout=(10, 90), headers={"User-Agent": UA})
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
    data = _get(f"{PORTAL}/{ds}.json", params)
    if not isinstance(data, list):
        raise RuntimeError(f"Socrata {ds} returned non-list (query error): {str(data)[:160]}")
    return data


def _view_updated(ds: str) -> str | None:
    """The portal's own 'rows updated' stamp for a dataset, as YYYY-MM-DD (UTC)."""
    meta = _get(f"{VIEWS}/{ds}.json")
    ts = meta.get("rowsUpdatedAt") if isinstance(meta, dict) else None
    if not ts:
        return None
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).date().isoformat()


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


def _soql_str(s: str) -> str:
    return s.replace("'", "''")


def pull(out_dir: Path) -> dict:
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

    # --- additive: school-level 4-year graduation rows (context for LEAs with no LEA-total row)
    grad_school_rows: dict[str, list[dict]] = {}
    for r in _soql("t7e6-zcnn", {
        "$where": (f"subgroup='All Students' AND schoolcode!='0' "
                   f"AND ratetype='4-year graduation rate' AND schoolyear='{grad_yr}'"),
        "$select": "districtcode,schoolcode,organization,rowstatus,pctgraduates",
        "$order": "districtcode,schoolcode", "$limit": "1000"}):
        grad_school_rows.setdefault(r["districtcode"], []).append(r)

    def single_school_grad(dc):
        if grad.get(dc) is not None:
            return None
        rows = grad_school_rows.get(dc, [])
        if len(rows) != 1 or rows[0].get("rowstatus") != "REPORTED" or _num(rows[0].get("pctgraduates")) is None:
            return None
        return {"organization": _clean(rows[0].get("organization")), "schoolcode": str(rows[0].get("schoolcode")),
                "value": _num(rows[0].get("pctgraduates"))}

    # --- additive: LEA type from the state directory
    dir_yr = _max_year(DIRECTORY_DS)
    lea_type, dir_names = {}, {}
    for r in _soql(DIRECTORY_DS, {"$select": "districtcode,districtname,districttype",
                                  "$where": f"schoolyear='{dir_yr}'",
                                  "$group": "districtcode,districtname,districttype",
                                  "$order": "districtcode", "$limit": "500"}):
        dc = str(r.get("districtcode"))
        if dc != "0":
            lea_type[dc] = _clean(r.get("districttype")) or None
            dir_names[dc] = _clean(r.get("districtname"))

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
    if len(districts) < MIN_DISTRICTS:
        raise RuntimeError(f"Only {len(districts)} districts with data — likely a filter failure (silent-zero guard).")
    for d in districts:
        d["lea_type"] = lea_type.get(d["districtcode"])
        d["grad_rate_single_school"] = single_school_grad(d["districtcode"])
    if sum(1 for d in districts if d["lea_type"]) < len(districts) * 0.8:
        raise RuntimeError("LEA type missing for most districts — directory query failure (silent-zero guard).")

    # Directory LEAs with no report card total of their own: where do the report card files count them?
    have = {d["districtcode"] for d in districts}
    reported_within = []
    for dc in sorted((dc for dc in dir_names if dc not in have), key=int):
        rows = _soql("6i7v-xnmf", {"$select": "districtcode,district",
                                   "$where": (f"organization='{_soql_str(dir_names[dc])}' AND schoolcode!='0' "
                                              f"AND schoolyear='{enr_yr}'"),
                                   "$group": "districtcode,district", "$limit": "5"})
        hosts = sorted({(str(r["districtcode"]), _clean(r.get("district"))) for r in rows})
        reported_within.append({
            "lea": dir_names[dc], "districtcode": dc, "lea_type": lea_type.get(dc),
            "reported_within_districtcode": hosts[0][0] if len(hosts) == 1 else None,
            "reported_within": hosts[0][1] if len(hosts) == 1 else None,
        })

    datasets = ("ms6b-mt82", "crb4-kdc7", "t7e6-zcnn", "6i7v-xnmf", DIRECTORY_DS)
    source_updated = {ds: _view_updated(ds) for ds in datasets}

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
        "lea_directory": {"dataset": DIRECTORY_DS, "schoolyear": dir_yr},
        "directory_leas_reported_within": reported_within,
        "source_updated": source_updated,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / OUT_SUMMARY).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / OUT_MANIFEST).write_text(json.dumps({
        "generated_at": summary["generated_at"], "dashboard": "schools",
        "vintages": summary["vintages"], "sources": summary["source"],
        "row_counts": {"districts": len(districts),
                       "lea_types": sum(1 for d in districts if d["lea_type"]),
                       "directory_leas_reported_within": len(reported_within)},
        "source_updated": source_updated,
        "lea_directory": summary["lea_directory"],
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
