"""EPA Safe Drinking Water puller — Delaware public water systems + violations.

Source: EPA Envirofacts SDWIS, data service (efservice), keyless.
  - WATER_SYSTEM filtered to STATE_CODE=DE (1,344 systems) — names + population.
  - WATER_SYSTEM(DE) JOIN VIOLATION (on PWSID) — the ONLY correct DE-filter for
    violations. `VIOLATION/STATE_CODE/DE` is a SILENT-WRONG filter (returns ~3.4M
    national rows); the table has no usable state column, so we join through
    WATER_SYSTEM, which does filter (see ISA D12).
License: US public domain (EPA).
Cadence: Envirofacts syncs SDWIS quarterly.
Output: <out>/water-summary.json + <out>/manifest.json

Currency semantics (the accuracy gate): we do NOT guess `compliance_status_code`.
A violation is "open / unresolved" iff it has NO `rtc_date` (Return To Compliance
date) — EPA's own field. Health-based = `is_health_based_ind='Y'`. We label counts
as "recorded in EPA SDWIS," link each system to its authoritative ECHO report, and
make no real-time claim.

ECHO's state services would pre-compute this, but ECHO is rate-limited (300/hr,
1,500/day) and unsuitable for anything but a sparse ETL; Envirofacts has no such
limit, so it is the backbone.

Run standalone:
    python3 -m etl.sources.epa_sdwa_de --out water/data
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

from etl.lib.fetch import fetch

EF = "https://data.epa.gov/efservice"
WS_COUNT = f"{EF}/WATER_SYSTEM/STATE_CODE/DE/COUNT/JSON"
JOIN = f"{EF}/WATER_SYSTEM/STATE_CODE/DE/VIOLATION/ROWS/0:9999/JSON"
OUT_SUMMARY = "water-summary.json"
OUT_MANIFEST = "manifest.json"


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _num(x) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def _is_open(r: dict) -> bool:
    """Open / unresolved iff there is no Return-To-Compliance date (EPA's field)."""
    rtc = r.get("rtc_date")
    return rtc in (None, "", "null")


def pull(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    total_systems = _num(json.loads(fetch(WS_COUNT).body)[0].get("TOTALQUERYRESULTS"))
    if total_systems <= 0:
        raise RuntimeError("WATER_SYSTEM DE count = 0 (silent-zero guard).")

    rows = json.loads(fetch(JOIN).body)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("DE violation join returned no rows (silent-zero guard).")

    systems: dict[str, dict] = {}
    for r in rows:
        pid = r.get("pwsid")
        if not pid:
            continue
        s = systems.setdefault(pid, {
            "pwsid": pid,
            "name": (r.get("pws_name") or "").strip().title(),
            "population": _num(r.get("population_served_count")),
            "city": (r.get("city_name") or "").strip().title(),
            "type": (r.get("pws_type_code") or "").strip(),
            "violations": 0, "health_based": 0, "open": 0, "open_health_based": 0,
        })
        s["violations"] += 1
        hb = (r.get("is_health_based_ind") == "Y")
        op = _is_open(r)
        if hb:
            s["health_based"] += 1
        if op:
            s["open"] += 1
            if hb:
                s["open_health_based"] += 1

    sys_list = list(systems.values())
    summary = {
        "generated_at": _utc_now(),
        "total_systems": total_systems,
        "systems_with_violations": len(sys_list),
        "systems_with_open": sum(1 for s in sys_list if s["open"] > 0),
        "systems_with_open_health_based": sum(1 for s in sys_list if s["open_health_based"] > 0),
        "total_violations_on_record": len(rows),
        "total_health_based": sum(1 for r in rows if r.get("is_health_based_ind") == "Y"),
        "total_open": sum(1 for r in rows if _is_open(r)),
        # Systems sorted by severity: open-health-based, then open, then health-based, then total.
        "systems": sorted(sys_list, key=lambda s: (-s["open_health_based"], -s["open"], -s["health_based"], -s["violations"])),
        "source": {
            "name": "EPA Envirofacts SDWIS (Safe Drinking Water)",
            "join": "WATER_SYSTEM(STATE_CODE=DE) ⋈ VIOLATION on PWSID",
            "endpoint": JOIN,
            "license": "US public domain",
            "echo_detail": "https://echo.epa.gov/detailed-facility-report?fid=",
            "note": "Counts are violations recorded in EPA SDWIS. 'Open' = no Return-To-Compliance date. Not a real-time status; see each system's ECHO report.",
        },
        "lead_note": {
            "headline": "Lead service lines are not centrally published at the address level in Delaware.",
            "detail": "Each water utility maintains its own inventory under EPA's Lead and Copper Rule Revisions. Check your utility directly.",
            "links": [
                {"name": "New Castle Municipal Services Commission inventory", "url": "https://newcastlemsc.delaware.gov/msc-lead-service-line-inventory/"},
                {"name": "Wilmington Water service-line map", "url": "https://www.wilmingtondewater.gov/245/Service-Line-Inventory-Map"},
                {"name": "Veolia Water Delaware inventory", "url": "https://storymaps.arcgis.com/stories/eaa20f76c16244929a16cb4f60f602fe"},
            ],
        },
    }

    (out_dir / OUT_SUMMARY).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / OUT_MANIFEST).write_text(json.dumps({
        "generated_at": summary["generated_at"], "dashboard": "water",
        "sources": {"epa_sdwis": summary["source"]},
        "row_counts": {"systems_total": total_systems, "systems_with_violations": len(sys_list),
                       "violations_on_record": len(rows)},
    }, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull Delaware drinking-water violations (EPA SDWIS).")
    parser.add_argument("--out", type=Path, default=Path("water/data"))
    args = parser.parse_args(argv)
    s = pull(args.out)
    print(f"wrote {args.out}/{OUT_SUMMARY}")
    print(f"  {s['total_systems']:,} DE public water systems")
    print(f"  {s['systems_with_violations']} systems with violations on record; "
          f"{s['systems_with_open']} with OPEN (no return-to-compliance)")
    print(f"  {s['total_violations_on_record']} violations on record "
          f"({s['total_health_based']} health-based, {s['total_open']} open)")
    if s["systems"]:
        t = s["systems"][0]
        print(f"  most-flagged: {t['name']} — {t['open']} open / {t['health_based']} health-based / {t['violations']} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
