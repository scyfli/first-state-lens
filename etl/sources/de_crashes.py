"""Delaware public crash data puller (Y8 road safety): crash counts by county and month.

Source:   Delaware Department of Safety and Homeland Security (DSHS), "Public Crash Data",
          data.delaware.gov dataset 827n-m6xc
          https://data.delaware.gov/Transportation/Public-Crash-Data/827n-m6xc
License:  Delaware Open Data Portal, public data (the portal lists no named license).
Cadence:  The state publishes monthly (about the 5th of the month). Each update covers
          crashes from 2009 through roughly six months before the update.
Output:   <out>/crashes-summary.json and <out>/manifest.json

What we pull (server-side aggregation only):
  - count(*) grouped by local month (America/New_York), county and the state's crash
    classification. The dataset stores crash_datetime in UTC, so we convert before
    truncating to a month; otherwise late-evening crashes on the last day of a month
    land in the next month.
  - the total row count, the count with no crash date, and the latest crash time.
  No row-level records are requested. The dataset carries crash coordinates; this
  puller never asks for them and writes none.

Neutrality posture:
  - Counts only, in the state's own four classifications, ordered by month and county
    name. No rates, ranks, trend labels or "better/worse" language.
  - The dataset counts crashes, not people. "Fatality Crash" means at least one death in
    the crash; there is no field for the number killed or injured, and we invent none.

Guards:
  - Silent-zero: fewer than 400,000 records or fewer than 150 months raises (the real
    dataset has about 588,000 records over 200+ months).
  - Reconciliation: grouped counts plus undated records must equal the total row count.
  - An unknown county or crash classification raises, so a schema change is reviewed
    instead of silently dropped.

Run:
    python3 -m etl.sources.de_crashes --out road-safety/data
"""

from __future__ import annotations

import argparse
import calendar
import datetime
import json
import sys
from pathlib import Path

from etl.lib import socrata

DATASET_ID = "827n-m6xc"
DATASET_URL = "https://data.delaware.gov/Transportation/Public-Crash-Data/827n-m6xc"
API_URL = f"{socrata.PORTAL}/resource/{DATASET_ID}.json"
OUT_SUMMARY = "crashes-summary.json"
OUT_MANIFEST = "manifest.json"

COUNTIES = ("Kent", "New Castle", "Sussex")
CLASS_KEYS = {
    "Non-Reportable": "non_reportable",
    "Property Damage Only": "property_damage_only",
    "Personal Injury Crash": "personal_injury",
    "Fatality Crash": "fatality",
    "NA": None,  # no classification in the source; counted in all_reports only
}
FIELDS = ("all_reports", "non_reportable", "property_damage_only", "personal_injury", "fatality")
LOCAL_TS = 'to_floating_timestamp(crash_datetime, "America/New_York")'
GROUP_LIMIT = 50000

MIN_RECORDS = 400_000
MIN_MONTHS = 150


def _blank() -> dict:
    return {k: 0 for k in FIELDS}


def _custom(meta: dict, key: str) -> str | None:
    return ((meta.get("metadata") or {}).get("custom_fields") or {}).get("Additional Information", {}).get(key)


def build_summary(
    meta: dict,
    grouped: list[dict],
    *,
    total_records: int,
    no_datetime: int,
    last_crash_local: str,
    min_records: int = MIN_RECORDS,
    min_months: int = MIN_MONTHS,
) -> dict:
    cells: dict[tuple[str, str], dict] = {}
    unclassified = 0
    grouped_sum = 0
    seen_counties: set[str] = set()
    for r in grouped:
        county = (r.get("county_desc") or "").strip()
        if county not in COUNTIES:
            raise RuntimeError(f"unknown county {county!r} in crash data; review before publishing")
        cls = (r.get("crash_class_desc") or "").strip()
        if cls not in CLASS_KEYS:
            raise RuntimeError(f"unknown crash class {cls!r}; review before publishing")
        month = str(r["month"])[:7]
        n = int(r["n"])
        seen_counties.add(county)
        grouped_sum += n
        c = cells.setdefault((month, county), _blank())
        c["all_reports"] += n
        key = CLASS_KEYS[cls]
        if key:
            c[key] += n
        else:
            unclassified += n

    missing = set(COUNTIES) - seen_counties
    if missing:
        raise RuntimeError(f"county missing from crash data: {sorted(missing)}")
    if grouped_sum + no_datetime != total_records:
        raise RuntimeError(
            f"grouped counts {grouped_sum} + undated {no_datetime} do not reconcile with total {total_records}"
        )
    months = sorted({m for m, _ in cells})
    if total_records < min_records or len(months) < min_months:
        raise RuntimeError(
            f"only {total_records} records over {len(months)} months (silent-zero guard)"
        )

    monthly = []
    for m in months:
        for county in COUNTIES:
            monthly.append({"month": m, "county": county, **cells.get((m, county), _blank())})

    yearly_cells: dict[tuple[int, str], dict] = {}
    for row in monthly:
        y = int(row["month"][:4])
        for county in (row["county"], "Statewide"):
            yc = yearly_cells.setdefault((y, county), _blank())
            for k in FIELDS:
                yc[k] += row[k]
    order = {c: i for i, c in enumerate(("Statewide",) + COUNTIES)}
    yearly = [{"year": y, "county": c, **v} for (y, c), v in sorted(yearly_cells.items(), key=lambda kv: (kv[0][0], order[kv[0][1]]))]

    last_date = datetime.date.fromisoformat(last_crash_local[:10])
    if last_date.strftime("%Y-%m") != months[-1]:
        raise RuntimeError(f"latest crash {last_date} is not in the latest grouped month {months[-1]}")
    month_end = calendar.monthrange(last_date.year, last_date.month)[1]
    kpi_year = last_date.year if (last_date.month, last_date.day) == (12, 31) else last_date.year - 1
    statewide = yearly_cells.get((kpi_year, "Statewide"))
    if statewide is None:
        raise RuntimeError(f"no crash data for the KPI year {kpi_year}")

    return {
        "source": {
            "dataset_id": DATASET_ID,
            "name": meta.get("name"),
            "publisher": meta.get("attribution"),
            "url": DATASET_URL,
            "api": API_URL,
            "rows_updated": socrata.rows_updated(meta),
            "cadence": _custom(meta, "Frequency of publishing"),
            "publishing_timeframe": _custom(meta, "Publishing Timeframe"),
            "temporal_coverage": _custom(meta, "Temporal Coverage"),
        },
        "coverage": {
            "first_month": months[0],
            "last_month": months[-1],
            "last_crash_date": last_date.isoformat(),
            "last_month_partial": last_date.day != month_end,
        },
        "counties": list(COUNTIES),
        "totals": {
            "records": total_records,
            "no_datetime": no_datetime,
            "unclassified": unclassified,
            "in_tables": grouped_sum,
        },
        "kpi": {"year": kpi_year, "statewide": statewide},
        "yearly": yearly,
        "monthly": monthly,
    }


def pull() -> dict:
    meta = socrata.metadata(DATASET_ID)
    total = int(socrata.soql(DATASET_ID, {"$select": "count(*) as n"})[0]["n"])
    no_dt = int(socrata.soql(DATASET_ID, {"$select": "count(*) as n", "$where": "crash_datetime IS NULL"})[0]["n"])
    last = socrata.soql(DATASET_ID, {"$select": f"max({LOCAL_TS}) as mx"})[0]["mx"]
    grouped = socrata.soql(DATASET_ID, {
        "$select": f"date_trunc_ym({LOCAL_TS}) as month, county_desc, crash_class_desc, count(*) as n",
        "$where": "crash_datetime IS NOT NULL",
        "$group": "month, county_desc, crash_class_desc",
        "$order": "month, county_desc, crash_class_desc",
        "$limit": str(GROUP_LIMIT),
    })
    if len(grouped) >= GROUP_LIMIT:
        raise RuntimeError("grouped crash query hit its row limit; results may be truncated")
    return build_summary(meta, grouped, total_records=total, no_datetime=no_dt, last_crash_local=last)


def write_outputs(out_dir: Path, summary: dict, generated_at: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / OUT_SUMMARY).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "generated_at": generated_at,
        "dashboard": "road-safety",
        "source": summary["source"],
        "coverage": summary["coverage"],
        "row_counts": {
            "records": summary["totals"]["records"],
            "monthly_rows": len(summary["monthly"]),
            "yearly_rows": len(summary["yearly"]),
            "months": len({r["month"] for r in summary["monthly"]}),
        },
    }
    (out_dir / OUT_MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Delaware public crash data: counts by county and month")
    ap.add_argument("--out", type=Path, default=Path("road-safety/data"))
    args = ap.parse_args(argv)
    s = pull()
    write_outputs(args.out, s, socrata.utc_now())
    k = s["kpi"]
    print(
        f"OK crashes: {s['totals']['records']:,} records, {s['coverage']['first_month']} to "
        f"{s['coverage']['last_month']} (through {s['coverage']['last_crash_date']}), "
        f"{k['year']} statewide: {k['statewide']['all_reports']:,} reports, "
        f"{k['statewide']['fatality']:,} fatality crashes; source rows updated {s['source']['rows_updated']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
