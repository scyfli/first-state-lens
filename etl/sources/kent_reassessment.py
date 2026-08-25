"""Kent County (DE) property reassessment puller — AGGREGATE assessed values only.

Source: Kent County, Delaware — ArcGIS Server, Parcels/Parcels FeatureServer (layer 0).
        https://gis.kentcountyde.gov/server/rest/services/Parcels/Parcels/FeatureServer/0
License: Public record (county parcel/assessment roll). Aggregates are published; the
         parcel layer itself carries owner PII (OWNERNAME/MAILINGADDRESS) which this
         puller NEVER reads, requests, or writes. Only server-side statistics leave the
         county's system — no parcel rows, no owner fields, no geometry.
Cadence: The county edits parcels continuously; the assessed values reflect Kent's
         2024 court-ordered reassessment (valuation date 2023-07-01, values live
         2024-07-01 for tax year 2024 — Kent was the first DE county reassessed).
         Refresh weekly; the roll changes slowly.
Output: <out>/kent-reassessment-summary.json  +  <out>/manifest.json

Keyless: Kent County's ArcGIS Server is open. No API key. (No CENSUS_API_KEY path here —
this puller touches no Census endpoint, so ISC-7's key-threading requirement does not
apply; recorded as such in the ISA.)

Neutrality posture (assessed value is the MOST-MISREAD civic dataset):
  - We publish assessed market value ONLY. It is not a tax bill and we never compute,
    imply, or display a tax figure — the rate is set separately by each taxing body.
  - We lead with the MEDIAN (typical parcel), not the mean, because the mean is pulled
    up by a handful of very high-value commercial/institutional parcels. Mean is shown
    beside it, labelled, never as the headline.
  - We SEGMENT by property use — a "Single Family Dwelling" median and a per-use table —
    never one blended "typical Kent County property" number.
  - We do NOT show pre- vs post-reassessment "increases": the assessment BASIS changed
    (decades-old base -> current market value), so an old-vs-new delta would manufacture
    a false spike that is a methodology change, not appreciation.
  - Owner identity is never published. Aggregates only.

Run standalone:
    python3 -m etl.sources.kent_reassessment --out reassessment/data
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

import requests

LAYER = (
    "https://gis.kentcountyde.gov/server/rest/services/"
    "Parcels/Parcels/FeatureServer/0"
)
QUERY = LAYER + "/query"

UA = "FirstStateLens-ETL/0.1 (+https://firststatelens.com; contact: mark.sanders3@gmail.com)"
OUT_SUMMARY = "kent-reassessment-summary.json"
OUT_MANIFEST = "manifest.json"

# Residential use classes we surface a dedicated median for (the "what a resident owns"
# number). Kept small + explicit so the puller stays robust (each median = one query).
RESIDENTIAL_MEDIAN_USES = ["Single Family Dwelling", "Mobile Home", "Multi Family Dwelling"]

# Silent-zero guard floors. Kent has ~83k parcels; if the source ever returns far fewer
# or a zero roll, we RAISE rather than publish a hollow dashboard.
MIN_PARCELS = 50_000
MIN_ROLL_VALUE = 1_000_000_000  # $1B; the real roll is ~$29B.


def _utc_now() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _get(params: dict, tries: int = 4) -> dict:
    """One ArcGIS query with retries. Raises on persistent failure (no silent zero)."""
    last = None
    for i in range(tries):
        try:
            r = requests.get(
                QUERY,
                params={**params, "f": "json"},
                headers={"User-Agent": UA},
                timeout=40,
            )
            r.raise_for_status()
            d = r.json()
            if "error" in d:
                raise RuntimeError(f"ArcGIS error: {d['error']}")
            return d
        except Exception as e:  # noqa: BLE001 — retry any transient network/HTTP error
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"Kent ArcGIS query failed after {tries} tries: {last}")


def _count(where: str) -> int:
    d = _get({"where": where, "returnCountOnly": "true"})
    return int(d.get("count", 0))


def _stats(where: str, stats: list[dict], group_by: str | None = None) -> list[dict]:
    params = {
        "where": where,
        "outStatistics": json.dumps(stats),
        "returnGeometry": "false",
    }
    if group_by:
        params["groupByFieldsForStatistics"] = group_by
        params["orderByFields"] = "n DESC"
        # Belt-and-suspenders: ask for well more group rows than the ~95 use classes so a
        # low server default page size can never silently drop the tail (reconciled below).
        params["resultRecordCount"] = 2000
    d = _get(params)
    return [f["attributes"] for f in d.get("features", [])]


def _sql_str(v: str) -> str:
    """Escape a string literal for an ArcGIS SQL where-clause (single-quote doubling)."""
    return v.replace("'", "''")


def _median(where: str, n_valued: int) -> float | None:
    """Median TOTALASSESSMENT for the filter, via ordered offset query.

    Odd n: the single middle row. Even n: the average of the two middle rows (the
    statistical median), so an even-count class is not reported one rank high.
    """
    if n_valued <= 0:
        return None
    if n_valued % 2:
        offset, take = n_valued // 2, 1
    else:
        offset, take = n_valued // 2 - 1, 2
    d = _get(
        {
            "where": where,
            "orderByFields": "TOTALASSESSMENT ASC",
            "outFields": "TOTALASSESSMENT",
            "resultOffset": offset,
            "resultRecordCount": take,
            "returnGeometry": "false",
        }
    )
    vals = [
        float(f["attributes"]["TOTALASSESSMENT"])
        for f in d.get("features", [])
        if f["attributes"].get("TOTALASSESSMENT") is not None
    ]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def pull() -> dict:
    valued = "TOTALASSESSMENT>0"

    parcels_total = _count("1=1")
    parcels_valued = _count(valued)

    agg = _stats(
        valued,
        [
            {"statisticType": "sum", "onStatisticField": "TOTALASSESSMENT", "outStatisticFieldName": "sum_total"},
            {"statisticType": "sum", "onStatisticField": "LANDASSESSMENT", "outStatisticFieldName": "sum_land"},
            {"statisticType": "sum", "onStatisticField": "IMPROVE", "outStatisticFieldName": "sum_improve"},
            {"statisticType": "avg", "onStatisticField": "TOTALASSESSMENT", "outStatisticFieldName": "avg_total"},
        ],
    )[0]

    median_all = _median(valued, parcels_valued)

    # Per-property-use breakdown: count + total + mean. No per-use median here (bounded to
    # residential classes below) — grouped stats stay to one query.
    by_use_raw = _stats(
        valued,
        [
            {"statisticType": "count", "onStatisticField": "OBJECTID", "outStatisticFieldName": "n"},
            {"statisticType": "sum", "onStatisticField": "TOTALASSESSMENT", "outStatisticFieldName": "sum_total"},
            {"statisticType": "avg", "onStatisticField": "TOTALASSESSMENT", "outStatisticFieldName": "avg_total"},
        ],
        group_by="PropertyUse",
    )
    by_use = []
    for row in by_use_raw:
        use = row.get("PropertyUse")
        if not use:  # skip null/blank use class
            continue
        by_use.append(
            {
                "use": use,
                "parcels": int(row.get("n") or 0),
                "total_assessed": round(float(row.get("sum_total") or 0), 2),
                "mean_assessed": round(float(row.get("avg_total") or 0), 2),
            }
        )

    # Dedicated residential medians (the "typical home" figures).
    residential_medians = {}
    for use in RESIDENTIAL_MEDIAN_USES:
        where = f"PropertyUse='{_sql_str(use)}' AND TOTALASSESSMENT>0"
        n = _count(where)
        residential_medians[use] = {
            "parcels": n,
            "median_assessed": _median(where, n),
        }

    sum_total = round(float(agg.get("sum_total") or 0), 2)
    sum_land = round(float(agg.get("sum_land") or 0), 2)
    sum_improve = round(float(agg.get("sum_improve") or 0), 2)

    # Silent-zero guard.
    if parcels_total < MIN_PARCELS:
        raise RuntimeError(f"parcel count {parcels_total} < floor {MIN_PARCELS} (silent-zero guard)")
    if sum_total < MIN_ROLL_VALUE:
        raise RuntimeError(f"roll value {sum_total} < floor {MIN_ROLL_VALUE} (silent-zero guard)")

    # Silent-PARTIAL guard: the by-use table must cover the valued parcels. If the grouped
    # query were paginated/truncated, this sum would fall short of parcels_valued while the
    # headline totals stayed correct. A small gap is legitimate (valued parcels with a
    # null/blank PropertyUse are skipped), so allow a 2% tolerance.
    by_use_parcels = sum(u["parcels"] for u in by_use)
    if parcels_valued and by_use_parcels < parcels_valued * 0.98:
        raise RuntimeError(
            f"by-use parcels {by_use_parcels} < 98% of valued {parcels_valued} "
            "(possible grouped-stats truncation; silent-partial guard)"
        )

    return {
        "county": "Kent",
        "state": "DE",
        "reassessment": {
            "valuation_date": "2023-07-01",
            "effective_tax_year": 2024,
            "note": "Kent was the first Delaware county reassessed; new values became live "
            "2024-07-01 for tax year 2024, replacing a decades-old assessment basis.",
        },
        "totals": {
            "parcels_total": parcels_total,
            "parcels_valued": parcels_valued,
            "total_assessed": sum_total,
            "land_assessed": sum_land,
            "improvement_assessed": sum_improve,
            "mean_assessed": round(float(agg.get("avg_total") or 0), 2),
            "median_assessed": median_all,
        },
        "residential_medians": residential_medians,
        "by_property_use": by_use,
        "generated_at": _utc_now(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Kent County DE reassessment aggregate puller")
    ap.add_argument("--out", required=True, help="output dir (e.g. reassessment/data)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    summary = pull()

    (out / OUT_SUMMARY).write_text(json.dumps(summary, indent=2) + "\n")

    manifest = {
        "generated_at": summary["generated_at"],
        "dashboard": "kent-reassessment",
        "sources": {
            "kent_arcgis": {
                "name": "Kent County, Delaware — ArcGIS Parcels FeatureServer",
                "endpoint": LAYER,
                "license": "County public record (aggregate statistics only; no owner PII)",
                "url": "https://gis-kentcountyde.hub.arcgis.com/",
            }
        },
        "row_counts": {
            "parcels_total": summary["totals"]["parcels_total"],
            "parcels_valued": summary["totals"]["parcels_valued"],
            "property_use_classes": len(summary["by_property_use"]),
        },
    }
    (out / OUT_MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")

    t = summary["totals"]
    print(
        f"OK Kent reassessment: {t['parcels_total']:,} parcels "
        f"({t['parcels_valued']:,} valued), roll ${t['total_assessed']:,.0f}, "
        f"median ${t['median_assessed']:,.0f}, mean ${t['mean_assessed']:,.0f}, "
        f"{len(summary['by_property_use'])} use classes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
