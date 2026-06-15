"""Delaware childcare access puller — licensed providers + child-population denominator.

Sources:
  - FirstMap DE_ChildCareCenters FeatureServer (ArcGIS, keyless) — licensed
    providers with capacity, STARS quality rating, county, and point geometry.
  - US Census ACS 5-year B09001 (under-6 population by county) — the denominator.
License: DE open data (FirstMap) + US public domain (Census).
Cadence: FirstMap tracks the OCCL load; ACS annual.
Output: <out>/providers.geojson + <out>/childcare-summary.json + <out>/manifest.json

The access metric is "children under 6 per licensed childcare slot," by county —
a reuse of the food-desert capacity-vs-need pattern, but county-level (FirstMap
carries ADR_COUNTY, so no geometry join is needed). Providers appear one row per
age-group, so capacity is deduped on the resource id (RSR_RSRC_I) before summing.

CENSUS_API_KEY is read from the environment and threaded into the request — the
orchestrated path must pass it (the silent-zero discipline: an unauthenticated
Census call returns HTML-at-200 and zeroes silently).

Run standalone (key from env):
    CENSUS_API_KEY=... python3 -m etl.sources.firstmap_childcare --out childcare/data
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import requests

from etl.lib.fetch import fetch

FIRSTMAP = (
    "https://enterprise.firstmap.delaware.gov/arcgis/rest/services/Society/"
    "DE_ChildCareCenters/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=geojson"
)
CENSUS = "https://api.census.gov/data/2023/acs/acs5"
ACS_VINTAGE = "2019-2023 5-year"
COUNTY_FIPS = {"001": "Kent", "003": "New Castle", "005": "Sussex"}
OUT_GEOJSON = "providers.geojson"
OUT_SUMMARY = "childcare-summary.json"
OUT_MANIFEST = "manifest.json"


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _norm_county(raw: str) -> str:
    s = (raw or "").upper()
    if "NEW CASTLE" in s:
        return "New Castle"
    if "KENT" in s:
        return "Kent"
    if "SUSSEX" in s:
        return "Sussex"
    return "(unknown)"


def _pull_providers() -> list[dict]:
    result = fetch(FIRSTMAP)
    data = json.loads(result.body)
    feats = data.get("features", [])
    if not feats:
        raise RuntimeError("FirstMap returned 0 childcare features (silent-zero guard).")
    # Dedupe one row per resource id; capacity is the provider total (same across age rows).
    by_id: dict[str, dict] = {}
    for f in feats:
        p = f.get("properties", {}) or {}
        rid = str(p.get("RSR_RSRC_I") or p.get("OBJECTID"))
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates")
        cap = _num(p.get("RSR_CPCT_N"))
        if rid not in by_id:
            by_id[rid] = {
                "id": rid,
                "name": (p.get("RSR_RESO_1") or "").strip() or "(unnamed)",
                "capacity": cap,
                "stars": (p.get("STARLEVEL") or "").strip() or "Unrated",
                "star_n": int(_num(p.get("DSI_STAR_LEVEL"))),
                "city": (p.get("ADR_CITYNA") or "").strip().title(),
                "county": _norm_county(p.get("ADR_COUNTY")),
                "license": (p.get("RGS_REGULA") or "").strip(),
                "lon": coords[0] if coords else None,
                "lat": coords[1] if coords else None,
            }
        else:
            by_id[rid]["capacity"] = max(by_id[rid]["capacity"], cap)
    return list(by_id.values())


def _pull_child_pop() -> dict:
    key = os.environ.get("CENSUS_API_KEY")
    params = {
        "get": "NAME,B09001_003E,B09001_004E,B09001_005E",
        "for": "county:*",
        "in": "state:10",
    }
    if key:
        params["key"] = key
    resp = requests.get(CENSUS, params=params, timeout=(10, 60),
                        headers={"User-Agent": "FirstStateLens-ETL/0.1 (+https://firststatelens.com)"})
    resp.raise_for_status()
    rows = resp.json()  # raises if HTML-at-200 (silent-zero guard fires here)
    header, *body = rows
    idx = {h: i for i, h in enumerate(header)}
    out = {}
    for r in body:
        fips = r[idx["county"]]
        county = COUNTY_FIPS.get(fips)
        if not county:
            continue
        under6 = sum(_num(r[idx[v]]) for v in ("B09001_003E", "B09001_004E", "B09001_005E"))
        out[county] = int(under6)
    if not out or sum(out.values()) == 0:
        raise RuntimeError("Census returned 0 under-6 population — key/threading failure (silent-zero guard).")
    return out


def pull(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    providers = _pull_providers()
    child_pop = _pull_child_pop()

    counties = {}
    for c in ("New Castle", "Kent", "Sussex"):
        prov = [p for p in providers if p["county"] == c]
        cap = sum(p["capacity"] for p in prov)
        pop = child_pop.get(c, 0)
        counties[c] = {
            "county": c,
            "providers": len(prov),
            "capacity": int(cap),
            "children_under_6": pop,
            "children_per_slot": round(pop / cap, 2) if cap else None,
        }

    total_cap = sum(p["capacity"] for p in providers)
    total_pop = sum(child_pop.values())
    # STARS quality distribution.
    stars = {}
    for p in providers:
        stars[p["stars"]] = stars.get(p["stars"], 0) + 1

    summary = {
        "generated_at": _utc_now(),
        "acs_vintage": ACS_VINTAGE,
        "total_providers": len(providers),
        "total_capacity": int(total_cap),
        "total_children_under_6": total_pop,
        "statewide_children_per_slot": round(total_pop / total_cap, 2) if total_cap else None,
        "by_county": [counties[c] for c in ("New Castle", "Kent", "Sussex")],
        "stars_distribution": [{"label": k, "count": v} for k, v in sorted(stars.items(), key=lambda kv: -kv[1])],
        "source": {
            "providers": {"name": "FirstMap DE_ChildCareCenters (DSCYF/OCCL)", "url": "https://firstmap.delaware.gov/", "license": "DE open data"},
            "population": {"name": "US Census ACS 5-year B09001", "vintage": ACS_VINTAGE, "license": "US public domain"},
        },
    }

    # providers.geojson for the map (deduped points).
    geo = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                "properties": {"name": p["name"], "capacity": p["capacity"], "stars": p["stars"],
                               "city": p["city"], "county": p["county"]},
            }
            for p in providers if p["lon"] is not None and p["lat"] is not None
        ],
    }

    (out_dir / OUT_SUMMARY).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / OUT_GEOJSON).write_text(json.dumps(geo), encoding="utf-8")
    (out_dir / OUT_MANIFEST).write_text(json.dumps({
        "generated_at": summary["generated_at"], "dashboard": "childcare-access",
        "sources": summary["source"],
        "row_counts": {"providers": len(providers), "mapped_points": len(geo["features"]),
                       "total_capacity": int(total_cap), "total_children_under_6": total_pop},
    }, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull Delaware childcare access (FirstMap + Census).")
    parser.add_argument("--out", type=Path, default=Path("childcare/data"))
    args = parser.parse_args(argv)
    s = pull(args.out)
    print(f"wrote {args.out}/ ({OUT_SUMMARY}, {OUT_GEOJSON})")
    print(f"  providers={s['total_providers']:,} capacity={s['total_capacity']:,} "
          f"under-6={s['total_children_under_6']:,} → {s['statewide_children_per_slot']} children/slot")
    for c in s["by_county"]:
        print(f"  {c['county']:11s}: {c['providers']:4d} providers, cap {c['capacity']:6,}, "
              f"{c['children_under_6']:6,} kids → {c['children_per_slot']} per slot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
