"""Delaware food establishment inspections puller (restaurant inspections, Y7).

Source:   data.delaware.gov dataset 384s-wygj, "Food Establishment Inspection Violations"
          https://data.delaware.gov/Health/Food-Establishment-Inspection-Violations/384s-wygj
          Published by the Department of Health and Social Services, Division of Public
          Health, Office of Food Protection.
License:  Public Domain (as stated on the dataset).
Cadence:  The state publishes weekly and keeps about the past two years. We refresh weekly.
Output:   <out>/towns/<town-slug>.json   one file per town (city as the state lists it)
          <out>/manifest.json            generated_at, source URLs, the state's own update
                                         stamp, the window, row counts and exclusions

Shape:    per establishment (business name, business street address, city and ZIP as the
          state lists them): its inspections newest first (date, inspection type) and each
          violation as the state words it (code and description). The source has no
          establishment type and no corrected-on-site flag, so neither is written.

Neutrality posture (docs/UPGRADE-PLAN.md B3, Mark's 2026-10-05 decision): raw and dated, in
the state's own wording. No grades, scores, counts-based labels or rankings are computed.
Establishments are ordered alphabetically and inspections by date. Text is kept as the state
spells it; only runs of whitespace are collapsed.

Privacy (B4): the source names businesses and business addresses. It carries no inspector,
employee or contact-person fields. We request only the fields we publish (no geocoded
location) and write nothing else.

Exclusions, all counted in the manifest:
  - rows dated after the state's own "rows updated" stamp (the file carries a few inspections
    dated in the future, which cannot be right),
  - rows older than WINDOW_YEARS before that stamp (the state keeps about two years now;
    this cap keeps the page bounded if that changes),
  - rows missing a business name, city or inspection date.

Silent-zero guard: if the result is implausibly small, raise and write nothing.

Run standalone:
    python3 -m etl.sources.de_food_inspections --out inspections/data
Then render the pages:
    python3 -m etl.pages.inspection_pages
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests

from etl.lib.atomic_io import atomic_write_text

DATASET = "384s-wygj"
RESOURCE = f"https://data.delaware.gov/resource/{DATASET}.json"
META = f"https://data.delaware.gov/api/views/{DATASET}.json"
DATASET_PAGE = "https://data.delaware.gov/Health/Food-Establishment-Inspection-Violations/384s-wygj"
PUBLISHER = "Delaware Department of Health and Social Services, Division of Public Health, Office of Food Protection"
UA = "FirstStateLens-ETL/0.1 (+https://firststatelens.com; contact: mark.sanders3@gmail.com)"
FIELDS = "restname,restaddress,restcity,restzip,insp_date,insp_type,violation,vio_desc"
PAGE_SIZE = 10000
WINDOW_YEARS = 3

# Silent-zero guard thresholds. The live file (2026-10) has about 33,000 rows, 3,700
# establishments and 55 towns; anything far below that is a query or source failure.
MIN_ROWS = 10000
MIN_ESTABLISHMENTS = 1000
MIN_TOWNS = 30

_WS = re.compile(r"\s+")


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean(s) -> str | None:
    if s is None:
        return None
    t = _WS.sub(" ", str(s)).strip()
    return t or None


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


_MOBILE = re.compile(r"\bMOB\b|\bmobile\b|food truck|\btruck\b|\btrailer\b|\bcart\b", re.I)


def is_mobile_unit(name: str) -> bool:
    """The state marks mobile food units with "MOB" in the name; trucks, trailers and carts too."""
    return bool(_MOBILE.search(name))


def establishment_id(name: str, address: str | None, city: str) -> str:
    key = f"{name}|{address or ''}|{city}".casefold()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def _years_before(d: datetime.date, years: int) -> datetime.date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 29 February
        return d.replace(year=d.year - years, day=28)


# ---- network ---------------------------------------------------------------------------

_last_call = 0.0


def _get(session: requests.Session, url: str, params: dict | None = None):
    """GET with an identifying User-Agent, one call every 2 s, and backoff on 429/5xx."""
    global _last_call
    for attempt in range(5):
        wait = 2.0 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
        try:
            r = session.get(url, params=params, headers={"User-Agent": UA}, timeout=(10, 120))
        except requests.RequestException:
            if attempt == 4:
                raise
            time.sleep(2 ** (attempt + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == 4:
                r.raise_for_status()
            time.sleep(2 ** (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("unreachable")


def fetch_meta(session: requests.Session) -> dict:
    d = _get(session, META)
    ts = d.get("rowsUpdatedAt")
    if not ts:
        raise RuntimeError("Dataset metadata has no rowsUpdatedAt stamp; refusing to publish undated data.")
    dt = datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc)
    return {"source_updated": dt.date().isoformat(),
            "rows_updated_at": dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")}


def fetch_rows(session: requests.Session) -> list[dict]:
    total = int(_get(session, RESOURCE, {"$select": "count(*) as n"})[0]["n"])
    rows: list[dict] = []
    offset = 0
    while True:
        page = _get(session, RESOURCE, {"$select": FIELDS, "$order": ":id", "$limit": str(PAGE_SIZE), "$offset": str(offset)})
        if not isinstance(page, list):
            raise RuntimeError(f"Socrata returned a non-list page: {str(page)[:160]}")
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    if len(rows) != total:
        raise RuntimeError(f"Fetched {len(rows)} rows but the source counts {total}; the file changed mid-pull or paging failed.")
    return rows


# ---- transform -------------------------------------------------------------------------

def build(rows: list[dict], source_updated: datetime.date, window_years: int = WINDOW_YEARS) -> dict:
    """Group raw rows into towns -> establishments -> inspections -> violations. Pure."""
    window_start = _years_before(source_updated, window_years)
    stats = {"rows_in": len(rows), "rows_incomplete": 0, "rows_after_source_update": 0,
             "rows_before_window": 0}
    after_dates: set[str] = set()
    ests: dict[str, dict] = {}
    for r in rows:
        name, city = _clean(r.get("restname")), _clean(r.get("restcity"))
        raw_date = _clean(r.get("insp_date"))
        if not name or not city or not raw_date:
            stats["rows_incomplete"] += 1
            continue
        try:
            d = datetime.date.fromisoformat(raw_date[:10])
        except ValueError:
            stats["rows_incomplete"] += 1
            continue
        if d > source_updated:
            stats["rows_after_source_update"] += 1
            after_dates.add(d.isoformat())
            continue
        if d < window_start:
            stats["rows_before_window"] += 1
            continue
        address = _clean(r.get("restaddress"))
        eid = establishment_id(name, address, city)
        mobile = is_mobile_unit(name)
        if mobile:
            # B4: a mobile food unit's listed street address is often the operator's home.
            # Keep the id (a hash) stable, but never write the street address or ZIP.
            stats["mobile_units_address_withheld"] = stats.get("mobile_units_address_withheld", 0) + (eid not in ests)
            address = None
        e = ests.setdefault(eid, {"id": eid, "name": name, "address": address, "city": city,
                                  "zip": None if mobile else _clean(r.get("restzip")), "mobile": mobile, "_insp": {}})
        if e["zip"] is None and not e["mobile"]:
            e["zip"] = _clean(r.get("restzip"))
        itype = _clean(r.get("insp_type")) or "Not listed"
        insp = e["_insp"].setdefault((d.isoformat(), itype), [])
        code, desc = _clean(r.get("violation")), _clean(r.get("vio_desc"))
        if code or desc:
            insp.append({"code": code, "description": desc})

    towns: dict[str, dict] = {}
    n_insp = n_viol = 0
    for e in ests.values():
        inspections = []
        for (d, t), vs in e.pop("_insp").items():
            vs.sort(key=lambda v: ((v["code"] or "").casefold(), (v["description"] or "").casefold()))
            inspections.append({"date": d, "type": t, "violations": vs})
            n_viol += len(vs)
        inspections.sort(key=lambda i: (i["date"], i["type"].casefold()), reverse=True)
        n_insp += len(inspections)
        e["inspections"] = inspections
        slug = slugify(e["city"])
        towns.setdefault(slug, {"town": e["city"], "slug": slug, "establishments": []})["establishments"].append(e)
    for t in towns.values():
        t["establishments"].sort(key=lambda e: (e["name"].casefold(), (e["address"] or "").casefold(), e["id"]))
    towns = {k: towns[k] for k in sorted(towns)}

    all_dates = [i["date"] for t in towns.values() for e in t["establishments"] for i in e["inspections"]]
    stats.update({
        "rows_used": stats["rows_in"] - stats["rows_incomplete"] - stats["rows_after_source_update"] - stats["rows_before_window"],
        "dates_after_source_update": sorted(after_dates),
        "establishments": len(ests), "inspections": n_insp, "violations": n_viol, "towns": len(towns),
        "date_min": min(all_dates) if all_dates else None, "date_max": max(all_dates) if all_dates else None,
        "window_start": window_start.isoformat(),
    })
    return {"towns": towns, "stats": stats}


def check_plausible(stats: dict, min_rows: int | None = None, min_establishments: int | None = None,
                    min_towns: int | None = None) -> None:
    min_rows = MIN_ROWS if min_rows is None else min_rows
    min_establishments = MIN_ESTABLISHMENTS if min_establishments is None else min_establishments
    min_towns = MIN_TOWNS if min_towns is None else min_towns
    if stats["rows_used"] < min_rows or stats["establishments"] < min_establishments or stats["towns"] < min_towns:
        raise RuntimeError(
            f"Implausibly small result ({stats['rows_used']} rows, {stats['establishments']} establishments, "
            f"{stats['towns']} towns); likely a query or source failure (silent-zero guard). Nothing written.")


def manifest_for(b: dict, source_updated: str, rows_updated_at: str, generated_at: str) -> dict:
    s = b["stats"]
    return {
        "generated_at": generated_at,
        "dashboard": "inspections",
        "source": {"name": "Food Establishment Inspection Violations", "publisher": PUBLISHER,
                   "dataset": DATASET, "url": DATASET_PAGE, "api": RESOURCE, "license": "Public Domain",
                   "publishing": "Weekly; the state keeps about the past two years"},
        "source_updated": source_updated,
        "rows_updated_at": rows_updated_at,
        "window": {"years": WINDOW_YEARS, "start": s["window_start"], "date_min": s["date_min"], "date_max": s["date_max"]},
        "row_counts": {k: s[k] for k in ("rows_in", "rows_used", "rows_incomplete", "rows_after_source_update",
                                         "rows_before_window", "establishments", "inspections", "violations", "towns")},
        "dates_after_source_update": s["dates_after_source_update"],
        "towns": [{"town": t["town"], "slug": t["slug"], "establishments": len(t["establishments"])} for t in b["towns"].values()],
    }


def _dump(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def pull(out_dir: Path, session: requests.Session | None = None) -> dict:
    session = session or requests.Session()
    meta = fetch_meta(session)
    rows = fetch_rows(session)
    b = build(rows, datetime.date.fromisoformat(meta["source_updated"]))
    check_plausible(b["stats"])  # raises before anything is written

    towns_dir = out_dir / "towns"
    towns_dir.mkdir(parents=True, exist_ok=True)
    for slug, t in b["towns"].items():
        atomic_write_text(towns_dir / f"{slug}.json", _dump({**t, "source_updated": meta["source_updated"]}))
    for stale in towns_dir.glob("*.json"):
        if stale.stem not in b["towns"]:
            stale.unlink()
    man = manifest_for(b, meta["source_updated"], meta["rows_updated_at"], _utc_now())
    atomic_write_text(out_dir / "manifest.json", _dump(man))
    return man


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pull Delaware food establishment inspection violations (384s-wygj).")
    ap.add_argument("--out", type=Path, default=Path("inspections/data"))
    args = ap.parse_args(argv)
    man = pull(args.out)
    c = man["row_counts"]
    print(f"wrote {args.out}/towns/*.json ({c['towns']} towns, {c['establishments']} establishments, "
          f"{c['inspections']} inspections, {c['violations']} violations) + manifest.json")
    print(f"  state stamp {man['source_updated']} · dates {man['window']['date_min']} to {man['window']['date_max']} · "
          f"excluded: {c['rows_after_source_update']} future-dated, {c['rows_before_window']} before window, "
          f"{c['rows_incomplete']} incomplete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
