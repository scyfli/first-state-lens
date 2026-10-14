"""Every bill and resolution in a Delaware General Assembly session, from the legislature.

Source: Delaware General Assembly, https://legis.delaware.gov/AllLegislation
  Listing:    POST https://legis.delaware.gov/json/AllLegislation/GetAllLegislation
              (the keyless JSON feed behind the site's "All Legislation" grid; 20 rows a page)
  Action log: POST https://legis.delaware.gov/json/BillDetail/GetRecentReportsByLegislationId
              (the "Bill Progress" list on each bill's official page)
License: public record of the Delaware General Assembly. The state is the authority:
  every row links to its official bill page.
Cadence: weekly (and on demand). The 153rd General Assembly ran 2025 to 2026; the 154th
  convenes 2027-01-12. To roll to a new assembly change CURRENT_SESSION below (the page
  generator reads the same constant) and add a floor to EXPECTED_FLOOR once the count is known.
Output: <out>/bills-<session>.json and <out>/bills-<session>-manifest.json
  (never <out>/manifest.json, which belongs to the SB 272 tracker in the same folder).

What is listed: bills, substitutes, and simple, concurrent and joint resolutions. Amendments
are not listed as rows; the legislature shows them on each bill's own page. Each row keeps
the source's own words: the bill number as the legislature displays it, the long title,
the primary sponsor, the status and the last entry of the action log.

NEUTRALITY: no curation, no picks, no grouping by topic or party. Order is the
legislature's own numbering order (its GridSort key) or a date. Sponsor links go to the
legislature's own member page, never to a party caucus site.

Silent-zero guard: the listing must match the server's own Total exactly, and the item
count must clear a floor (EXPECTED_FLOOR for a finished session, and 90% of the last
committed file for the same session). A failed guard raises and writes nothing.

Politeness: identifying User-Agent, at most one request every 2 seconds, retries with
backoff. A first run reads every action log (about 1,500 requests, roughly an hour). Later
runs re-read an action log only for bills that are new, whose status changed, or that had
activity in the last RECENT_DAYS days; --full re-reads them all.

Run:
    python3 -m etl.sources.de_legis_bills --out bill-tracker/data
    python3 -m etl.sources.de_legis_bills --session 154 --out bill-tracker/data --full
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time
from pathlib import Path
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import requests

CURRENT_SESSION = 153  # the one value to change when the next General Assembly convenes
EXPECTED_FLOOR = {153: 1000}  # a full two-year session lists well over 1,000 items

BASE = "https://legis.delaware.gov"
LISTING_PAGE = f"{BASE}/AllLegislation"
LISTING_URL = f"{BASE}/json/AllLegislation/GetAllLegislation"
ACTIONS_URL = f"{BASE}/json/BillDetail/GetRecentReportsByLegislationId"
BILL_URL = f"{BASE}/BillDetail?LegislationId={{}}"
MEMBER_URL = f"{BASE}/LegislatorDetail?personId={{}}"
GLOSSARY_URL = f"{BASE}/Resources/GlossaryOfTerms"

UA = "FirstStateLens-ETL/0.1 (+https://firststatelens.com; contact: mark.sanders3@gmail.com)"
MIN_INTERVAL = 2.0  # seconds between requests to the state site
PAGE_SIZE = 20  # the server caps the grid at 20 rows per page
RECENT_DAYS = 45
DE_TZ = ZoneInfo("America/New_York")

# LegislationTypeId -> the type label the legislature's own search filter uses.
TYPES = {1: "Bill", 2: "Resolution", 3: "Concurrent Resolution", 4: "Joint Resolution", 6: "Substitute"}
AMENDMENT_TYPE = 5
CHAMBER_IDS = {1: "Senate", 2: "House"}
PREFIX_CHAMBER = {"H": "House", "S": "Senate"}

FIELDS = ("legislation_id", "number", "type", "chamber", "title", "short_title",
          "primary_sponsor", "sponsor_url", "introduced", "status", "status_date",
          "last_action", "last_action_date", "url", "order")


# ---- session helpers ------------------------------------------------------------------

def assembly_years(session: int) -> tuple[int, int]:
    """General Assembly n convenes in January of 1719 + 2n (153rd: 2025) and runs two years."""
    start = 1719 + 2 * int(session)
    return start, start + 1


def ordinal(n: int) -> str:
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def default_floor(session: int, prior: dict | None, min_rows: int | None = None) -> int:
    base = EXPECTED_FLOOR.get(int(session), 1) if min_rows is None else int(min_rows)
    prior_n = len((prior or {}).get("bills") or [])
    return max(base, int(prior_n * 0.9))


# ---- parsing --------------------------------------------------------------------------

_MS = re.compile(r"/Date\((-?\d+)\)/")


def ms_date(value: str | None) -> str | None:
    """'/Date(1782419826587)/' -> '2026-06-25' (calendar day in Delaware)."""
    if not value:
        return None
    m = _MS.fullmatch(value.strip())
    if not m:
        raise ValueError(f"unrecognised date {value!r}")
    dt = datetime.datetime.fromtimestamp(int(m.group(1)) / 1000, DE_TZ)
    return dt.date().isoformat()


def action_date(value: str) -> str:
    """'6/25/26' -> '2026-06-25' (the action log's own m/d/yy form)."""
    return datetime.datetime.strptime(value.strip(), "%m/%d/%y").date().isoformat()


def last_action(actions: Iterable[dict]) -> tuple[str | None, str | None]:
    """Latest entry by action date, then by the log's own entry id."""
    best = None
    for a in actions:
        key = (action_date(a["OccuredAtDateTime"]), int(a["LegislationActionLogId"]))
        if best is None or key > best[0]:
            best = (key, a["ActionDescription"])
    if best is None:
        return None, None
    return best[1], best[0][0]


def _clean(s: str | None) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def normalize(row: dict, session: int) -> dict:
    """One listing row -> our record (without the action-log fields)."""
    number = _clean(row.get("LegislationDisplayCode"))
    if not number:
        raise ValueError(f"row {row.get('LegislationId')} has no bill number")
    if int(row.get("AssemblyNumber") or 0) != int(session):
        raise ValueError(f"{number}: assembly {row.get('AssemblyNumber')} is not session {session}")
    type_id = int(row["LegislationTypeId"])
    if type_id not in TYPES:
        raise ValueError(f"{number}: unknown legislation type {type_id}")
    chamber = PREFIX_CHAMBER.get(number[:1])
    if chamber is None or CHAMBER_IDS.get(row.get("ChamberId")) != chamber:
        raise ValueError(f"{number}: chamber id {row.get('ChamberId')} disagrees with the number prefix")
    lid = int(row["LegislationId"])
    person = row.get("SponsorPersonId")
    return {
        "legislation_id": lid,
        "number": number,
        "type": TYPES[type_id],
        "chamber": chamber,
        "title": _clean(row.get("LongTitle")),
        "short_title": _clean(row.get("ShortTitle")),
        "primary_sponsor": _clean(row.get("Sponsor")),
        "sponsor_url": MEMBER_URL.format(int(person)) if person else None,
        "introduced": ms_date(row.get("IntroductionDateTime")),
        "status": _clean(row.get("StatusName")),
        "status_date": ms_date(row.get("LegislationStatusDateTime")),
        "url": BILL_URL.format(lid),
        "order": int(row["GridSort"]),
    }


def check_listing_complete(rows: list[dict], total: int) -> None:
    ids = {r.get("LegislationId") for r in rows}
    if len(rows) != int(total) or len(ids) != int(total):
        raise RuntimeError(
            f"silent-zero guard: listing returned {len(rows)} rows ({len(ids)} unique) "
            f"but the server reported Total={total}; writing nothing.")


def _days_between(a: str, b: str) -> int:
    return abs((datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days)


def _needs_actions(rec: dict, old: dict | None, today: str, full: bool, recent_days: int) -> bool:
    if full or old is None:
        return True
    if (old.get("status"), old.get("status_date")) != (rec["status"], rec["status_date"]):
        return True
    if not old.get("last_action_date"):
        return True
    for d in (rec["status_date"], old.get("last_action_date")):
        if d and _days_between(d, today) <= recent_days:
            return True
    return False


def build(rows: list[dict], *, session: int, fetch_actions: Callable[[int], list[dict]],
          prior: dict | None = None, full: bool = False, today: str | None = None,
          min_rows: int | None = None, recent_days: int = RECENT_DAYS,
          stats: dict | None = None) -> dict:
    """Listing rows -> the session file. Pure apart from fetch_actions."""
    session = int(session)
    today = today or datetime.datetime.now(DE_TZ).date().isoformat()
    if prior is not None and int(prior.get("session") or 0) != session:
        prior = None
    old_by_id = {b["legislation_id"]: b for b in (prior or {}).get("bills", [])}

    records, amendments = [], 0
    for row in rows:
        if int(row.get("LegislationTypeId") or 0) == AMENDMENT_TYPE:
            if int(row.get("AssemblyNumber") or 0) != session:
                raise ValueError(f"amendment row from assembly {row.get('AssemblyNumber')}, not {session}")
            amendments += 1
            continue
        records.append(normalize(row, session))

    floor = default_floor(session, prior, min_rows)
    if len(records) < floor:
        raise RuntimeError(f"silent-zero guard: {len(records)} items for session {session}, "
                           f"floor is {floor}; writing nothing.")

    fetched = reused = 0
    for rec in records:
        old = old_by_id.get(rec["legislation_id"])
        if _needs_actions(rec, old, today, full, recent_days):
            rec["last_action"], rec["last_action_date"] = last_action(fetch_actions(rec["legislation_id"]))
            fetched += 1
        else:
            rec["last_action"], rec["last_action_date"] = old.get("last_action"), old.get("last_action_date")
            reused += 1
    if stats is not None:
        stats.update({"action_logs_read": fetched, "action_logs_reused": reused})

    records.sort(key=lambda r: r["order"])
    by_type: dict[str, int] = {}
    for r in records:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    start, end = assembly_years(session)
    return {
        "session": session,
        "assembly_name": f"{ordinal(session)} General Assembly",
        "years": [start, end],
        "source": {
            "name": "Delaware General Assembly",
            "all_legislation_page": LISTING_PAGE,
            "glossary": GLOSSARY_URL,
        },
        "counts": {"items": len(records), "by_type": dict(sorted(by_type.items())),
                   "amendments_not_listed": amendments},
        "bills": [{k: r[k] for k in FIELDS} for r in records],
    }


# ---- network --------------------------------------------------------------------------

class Client:
    """Polite POST client: identifying UA, >= MIN_INTERVAL between requests, retries."""

    def __init__(self, min_interval: float = MIN_INTERVAL):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "X-Requested-With": "XMLHttpRequest",
                               "Referer": LISTING_PAGE})
        self.min_interval = min_interval
        self._last = 0.0
        self.requests = 0

    def post(self, url: str, data: dict, attempts: int = 5, empty_ok: bool = False) -> dict:
        for i in range(attempts):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                r = self.s.post(url, data=data, timeout=(10, 60))
                if r.status_code in (429,) or r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                if empty_ok and r.status_code == 200 and not r.content.strip():
                    # The action-log endpoint answers 200 with an empty body for a bill that
                    # has no log entries yet (seen for HB 481, 153rd: its official page shows
                    # a status but no Bill Progress list).
                    return {"Data": [], "Total": 0}
                body = r.json()
                if body.get("Errors"):
                    raise RuntimeError(f"source reported errors: {body['Errors']}")
                return body
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError, ValueError) as exc:
                if i == attempts - 1:
                    raise RuntimeError(f"{url} failed after {attempts} attempts: {exc}") from exc
                time.sleep(5 * 2 ** i)
        raise AssertionError("unreachable")


def fetch_listing(client: Client, session: int) -> tuple[list[dict], int]:
    rows: list[dict] = []
    page, total = 1, None
    while True:
        body = client.post(LISTING_URL, {
            "sort": "", "page": page, "pageSize": PAGE_SIZE, "group": "", "filter": "",
            "selectedGA[0]": str(session), "sponsorName": "", "fromIntroDate": "",
            "toIntroDate": "", "coSponsorCheck": "false"})
        total = int(body["Total"])
        data = body.get("Data") or []
        rows.extend(data)
        if not data or len(rows) >= total:
            break
        page += 1
        if page > 1000:
            raise RuntimeError("listing pagination did not end")
    check_listing_complete(rows, total)
    return rows, total


def fetch_actions(client: Client, legislation_id: int) -> list[dict]:
    url = f"{ACTIONS_URL}?legislationId={int(legislation_id)}"
    body = client.post(url, {}, empty_ok=True)
    data, total = body.get("Data") or [], int(body.get("Total") or 0)
    if len(data) >= total:
        return data
    data, page = [], 1  # the unpaged call came back short: walk the pages instead
    while len(data) < total:
        body = client.post(url, {"sort": "", "page": page, "pageSize": PAGE_SIZE, "group": "", "filter": ""})
        chunk = body.get("Data") or []
        if not chunk:
            break
        data.extend(chunk)
        page += 1
    if len(data) != total:
        raise RuntimeError(f"action log for {legislation_id}: got {len(data)} of {total}")
    return data


# ---- writing --------------------------------------------------------------------------

def _dumps(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_outputs(out: dict, out_dir: Path, *, now: str, source_meta: dict) -> bool:
    """Write bills-<s>.json + bills-<s>-manifest.json. No-op (returns False) if unchanged."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    s = out["session"]
    data_path = out_dir / f"bills-{s}.json"
    man_path = out_dir / f"bills-{s}-manifest.json"
    text = _dumps(out)
    if data_path.exists() and man_path.exists() and data_path.read_text(encoding="utf-8") == text:
        return False
    bills = out["bills"]
    manifest = {
        "generated_at": now,
        "dashboard": "bill-tracker",
        "session": s,
        "assembly_name": out["assembly_name"],
        "source": {
            "name": "Delaware General Assembly (legis.delaware.gov)",
            "all_legislation_page": LISTING_PAGE,
            "listing_endpoint": LISTING_URL,
            "action_log_endpoint": ACTIONS_URL,
            "license": "Public record of the Delaware General Assembly",
            "source_updated": "The source publishes no update stamp. See latest_status_date "
                              "and latest_action_date.",
        },
        "latest_status_date": max((b["status_date"] for b in bills if b["status_date"]), default=None),
        "latest_action_date": max((b["last_action_date"] for b in bills if b["last_action_date"]), default=None),
        "row_counts": out["counts"],
        "run": dict(sorted(source_meta.items())),
    }
    _atomic_write(data_path, text)
    _atomic_write(man_path, _dumps(manifest))
    return True


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def pull(session: int, out_dir: Path, *, full: bool = False, min_rows: int | None = None,
         recent_days: int = RECENT_DAYS) -> dict:
    out_dir = Path(out_dir)
    prior_path = out_dir / f"bills-{session}.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8")) if prior_path.exists() else None
    client = Client()
    rows, total = fetch_listing(client, session)
    stats: dict = {}
    out = build(rows, session=session, fetch_actions=lambda lid: fetch_actions(client, lid),
                prior=prior, full=full, min_rows=min_rows, recent_days=recent_days, stats=stats)
    stats.update({"server_total": total, "requests": client.requests, "full": bool(full)})
    changed = write_outputs(out, out_dir, now=_utc_now(), source_meta=stats)
    print(f"session {session}: {out['counts']['items']} items "
          f"({out['counts']['amendments_not_listed']} amendments not listed), "
          f"{stats['action_logs_read']} action logs read, {stats['action_logs_reused']} reused, "
          f"{'written' if changed else 'unchanged'}", file=sys.stderr)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", type=int, default=CURRENT_SESSION)
    ap.add_argument("--out", type=Path, default=Path("bill-tracker/data"))
    ap.add_argument("--full", action="store_true", help="re-read every action log")
    ap.add_argument("--min-rows", type=int, default=None, help="override the session floor")
    ap.add_argument("--recent-days", type=int, default=RECENT_DAYS)
    a = ap.parse_args(argv)
    pull(a.session, a.out, full=a.full, min_rows=a.min_rows, recent_days=a.recent_days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
