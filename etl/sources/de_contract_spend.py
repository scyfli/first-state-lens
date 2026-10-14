"""Delaware Statewide Central Contract Spend puller (Y9: contracts section of /spending/).

Source:   Office of Management and Budget (OMB), Government Support Services (GSS),
          "Statewide Central Contract Spend", data.delaware.gov dataset sifm-293u
          https://data.delaware.gov/Government-and-Finance/Statewide-Central-Contract-Spend/sifm-293u
License:  Public Domain (as listed on the portal).
Cadence:  The state publishes monthly; the dataset covers about five years.
Output:   <out>/contracts-summary.json and <out>/contracts-manifest.json
          (named so they sit beside the Online Checkbook files in spending/data/ without
          overwriting that puller's manifest.json).

What the dataset is (and is not):
  - Monthly spend reported against statewide central contracts that GSS administers
    for state agencies (spend group A), school districts (S) and municipalities (M).
    Fields: agency type (GSS or GSA), short and long contract number, contract
    description, vendor name, total spend, month, spend group, calendar and fiscal year.
  - It has NO contract start or end dates and NO contract award or ceiling values. We
    publish the first and last month with reported spend for each contract and vendor,
    labelled as exactly that, and invent no dates or values.
  - It does not cover every contract the state signs, only these central contracts.

What we pull (server-side aggregation only): sum(total_spend), count(*), and the first
and last reported month, grouped by contract number, contract description, agency type,
vendor name, fiscal year and spend group. Vendor names are published as the state
publishes them (whitespace collapsed). The dataset has no address or contact fields and
we add none.

Neutrality posture: the table is ordered by contract description, then contract number,
then vendor, never by amount. The page may add sortable columns; it never presents a
ranking.

Guards:
  - Silent-zero: fewer than 10,000 source rows, 100 contracts or 100 contract and vendor
    pairs in the latest complete fiscal year raises.
  - Reconciliation: grouped row counts must equal count(*), and grouped spend must equal
    sum(total_spend) to the cent.

Run:
    python3 -m etl.sources.de_contract_spend --out spending/data
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from etl.lib import socrata

DATASET_ID = "sifm-293u"
DATASET_URL = "https://data.delaware.gov/Government-and-Finance/Statewide-Central-Contract-Spend/sifm-293u"
API_URL = f"{socrata.PORTAL}/resource/{DATASET_ID}.json"
OUT_SUMMARY = "contracts-summary.json"
OUT_MANIFEST = "contracts-manifest.json"
GROUP_LIMIT = 50000

SPEND_GROUPS = {"A": "State agencies", "S": "School districts", "M": "Municipalities"}
AWARD_TYPES = {
    "GSS": "Awarded by Government Support Services through solicitation or cooperative agreement",
    "GSA": "Negotiated by Government Support Services with vendors on U.S. General Services Administration schedules",
}

MIN_ROWS = 10_000
MIN_CONTRACTS = 100
MIN_PAIRS = 100


def latest_complete_fy(last_ym: int) -> int:
    """Delaware's fiscal year N runs July of N-1 to June of N."""
    year, month = divmod(int(last_ym), 100)
    return year if month >= 6 else year - 1


def _ym(v: int) -> str:
    y, m = divmod(int(v), 100)
    return f"{y}-{m:02d}"


def _clean(s: str | None) -> str:
    return " ".join((s or "").split())


def _cents(x: float) -> float:
    return round(float(x) + 0.0, 2)


def build_summary(
    meta: dict,
    grouped: list[dict],
    *,
    total_rows: int,
    total_spend: float,
    min_rows: int = MIN_ROWS,
    min_contracts: int = MIN_CONTRACTS,
    min_pairs: int = MIN_PAIRS,
) -> dict:
    rows_sum = sum(int(r["n"]) for r in grouped)
    spend_sum = round(sum(float(r["spend"]) for r in grouped), 2)
    if rows_sum != total_rows:
        raise RuntimeError(f"grouped rows {rows_sum} do not reconcile with count(*) {total_rows}")
    if abs(spend_sum - round(float(total_spend), 2)) > 0.005:
        raise RuntimeError(f"grouped spend {spend_sum} does not reconcile with sum(total_spend) {total_spend}")

    for r in grouped:
        if r.get("spend_group") not in SPEND_GROUPS:
            raise RuntimeError(f"unknown spend group {r.get('spend_group')!r}; review before publishing")
        if r.get("gss_gsa_agency") not in AWARD_TYPES:
            raise RuntimeError(f"unknown agency type {r.get('gss_gsa_agency')!r}; review before publishing")

    last_ym = max(int(r["last_ym"]) for r in grouped)
    first_ym = min(int(r["first_ym"]) for r in grouped)
    fy = latest_complete_fy(last_ym)

    # Latest description per contract number (a few numbers carry two wordings over time).
    desc_pick: dict[str, tuple[int, str]] = {}
    for r in grouped:
        c = r["long_contract_number"].strip()
        cand = (int(r["last_ym"]), _clean(r["contract_description"]))
        if c not in desc_pick or cand > desc_pick[c]:
            desc_pick[c] = cand

    pairs: dict[tuple[str, str], dict] = {}
    by_fy: dict[int, dict] = {}
    for r in grouped:
        c = r["long_contract_number"].strip()
        v = _clean(r["vendor_name"])
        f = int(r["fiscal_year"])
        s = float(r["spend"])
        p = pairs.setdefault((c, v), {"first": 10**9, "last": 0, "fy_spend": 0.0, "fy_rows": 0, "types": set()})
        p["first"] = min(p["first"], int(r["first_ym"]))
        p["last"] = max(p["last"], int(r["last_ym"]))
        p["types"].add(r["gss_gsa_agency"])
        if f == fy:
            p["fy_spend"] += s
            p["fy_rows"] += int(r["n"])
        y = by_fy.setdefault(f, {"rows": 0, "spend": 0.0, "by_spend_group": {g: 0.0 for g in SPEND_GROUPS},
                                 "contracts": set(), "vendors": set()})
        y["rows"] += int(r["n"])
        y["spend"] += s
        y["by_spend_group"][r["spend_group"]] += s
        y["contracts"].add(c)
        y["vendors"].add(v)

    if fy not in by_fy:
        raise RuntimeError(f"no rows for the latest complete fiscal year {fy}")

    table = []
    for (c, v), p in pairs.items():
        if not p["fy_rows"]:
            continue
        table.append({
            "description": desc_pick[c][1],
            "contract_number": c,
            "award_type": "/".join(sorted(p["types"])),
            "vendor": v,
            "fy_spend": _cents(p["fy_spend"]),
            "first_month": _ym(p["first"]),
            "last_month": _ym(p["last"]),
        })
    table.sort(key=lambda t: (t["description"], t["contract_number"], t["vendor"]))

    y = by_fy[fy]
    if total_rows < min_rows or len(y["contracts"]) < min_contracts or len(table) < min_pairs:
        raise RuntimeError(
            f"{total_rows} rows, {len(y['contracts'])} contracts, {len(table)} pairs in FY{fy} (silent-zero guard)"
        )

    fiscal_years = [
        {
            "fiscal_year": f,
            "rows": d["rows"],
            "spend": _cents(d["spend"]),
            "contracts": len(d["contracts"]),
            "vendors": len(d["vendors"]),
            "complete": f <= fy,
        }
        for f, d in sorted(by_fy.items())
    ]

    return {
        "source": {
            "dataset_id": DATASET_ID,
            "name": meta.get("name"),
            "publisher": meta.get("attribution"),
            "url": DATASET_URL,
            "api": API_URL,
            "rows_updated": socrata.rows_updated(meta),
            "license": "Public Domain",
        },
        "coverage": {"first_month": _ym(first_ym), "last_month": _ym(last_ym), "rows": total_rows,
                     "spend": round(float(total_spend), 2)},
        "definitions": {"spend_groups": SPEND_GROUPS, "award_types": AWARD_TYPES},
        "fiscal_year": fy,
        "fiscal_year_months": {"first": f"{fy - 1}-07", "last": f"{fy}-06"},
        "kpi": {
            "contracts": len(y["contracts"]),
            "vendors": len(y["vendors"]),
            "rows": y["rows"],
            "total_spend": _cents(y["spend"]),
            "by_spend_group": {g: _cents(x) for g, x in y["by_spend_group"].items()},
        },
        "fiscal_years": fiscal_years,
        "contracts": table,
    }


def pull() -> dict:
    meta = socrata.metadata(DATASET_ID)
    tot = socrata.soql(DATASET_ID, {"$select": "count(*) as n, sum(total_spend) as s"})[0]
    grouped = socrata.soql(DATASET_ID, {
        "$select": (
            "long_contract_number, contract_description, gss_gsa_agency, vendor_name, fiscal_year, spend_group, "
            "sum(total_spend) as spend, count(*) as n, "
            "min(calendar_year*100+calendar_month) as first_ym, max(calendar_year*100+calendar_month) as last_ym"
        ),
        "$group": "long_contract_number, contract_description, gss_gsa_agency, vendor_name, fiscal_year, spend_group",
        "$order": "long_contract_number, contract_description, gss_gsa_agency, vendor_name, fiscal_year, spend_group",
        "$limit": str(GROUP_LIMIT),
    })
    if len(grouped) >= GROUP_LIMIT:
        raise RuntimeError("grouped contract query hit its row limit; results may be truncated")
    return build_summary(meta, grouped, total_rows=int(tot["n"]), total_spend=float(tot["s"]))


def write_outputs(out_dir: Path, summary: dict, generated_at: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / OUT_SUMMARY).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "generated_at": generated_at,
        "dashboard": "spending-contracts",
        "source": summary["source"],
        "coverage": summary["coverage"],
        "fiscal_year": summary["fiscal_year"],
        "row_counts": {
            "source_rows": summary["coverage"]["rows"],
            "table_rows": len(summary["contracts"]),
            "contracts_in_fiscal_year": summary["kpi"]["contracts"],
            "vendors_in_fiscal_year": summary["kpi"]["vendors"],
        },
    }
    (out_dir / OUT_MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Delaware Statewide Central Contract Spend (sifm-293u)")
    ap.add_argument("--out", type=Path, default=Path("spending/data"))
    args = ap.parse_args(argv)
    s = pull()
    write_outputs(args.out, s, socrata.utc_now())
    k = s["kpi"]
    print(
        f"OK contract spend: {s['coverage']['rows']:,} rows {s['coverage']['first_month']} to {s['coverage']['last_month']}; "
        f"FY{s['fiscal_year']}: {k['contracts']} contracts, {k['vendors']} vendors, ${k['total_spend']:,.2f}, "
        f"{len(s['contracts'])} table rows; source rows updated {s['source']['rows_updated']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
