"""Delaware legislator voting-record puller — Open States v3.

Source: https://v3.openstates.org  (Open States / Plural Policy API)
License: Open States data is public-domain dedicated (attribution requested).
Cadence: Open States re-scrapes the official source on a recurring basis.
Output: <out>/votes-summary.json + <out>/manifest.json

Reads OPENSTATES_API_KEY from the environment (free key). The orchestrated path
MUST thread it (same silent-zero discipline as the Census key). We aggregate the
current legislative session's recorded roll-call votes per legislator: each
member-vote in Open States is self-describing (voter.id, party, chamber, district,
option), so no separate roster join is needed.

NEUTRALITY: this is the most politically charged dashboard, so it reports only
factual counts — votes recorded, yes/no/other, participation. No scoring, no
ideology framing, no party-line judgment. The official record is legis.delaware.gov;
we cite it and Open States.

Run standalone (key from env):
    OPENSTATES_API_KEY=... python3 -m etl.sources.openstates_de --out votes/data
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

import requests

BASE = "https://v3.openstates.org"
JUR = "Delaware"
OUT_SUMMARY = "votes-summary.json"
OUT_MANIFEST = "manifest.json"
CHAMBER = {"upper": "Senate", "lower": "House"}


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _key() -> str:
    k = os.environ.get("OPENSTATES_API_KEY")
    if not k:
        raise RuntimeError("OPENSTATES_API_KEY not set (silent-zero guard).")
    return k


def _get(path: str, key: str, *, attempts: int = 6) -> dict:
    url = BASE + path
    for i in range(attempts):
        r = requests.get(url, headers={"X-API-KEY": key, "User-Agent": "FirstStateLens-ETL/0.1 (+https://firststatelens.com)"}, timeout=(10, 90))
        if r.status_code == 429:
            time.sleep(5 * (i + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Open States rate-limited after {attempts} attempts: {path}")


def _latest_session(key: str) -> str:
    j = _get(f"/jurisdictions/{JUR}?include=legislative_sessions", key)
    sessions = [s.get("identifier") for s in j.get("legislative_sessions", []) if s.get("identifier")]
    numeric = [s for s in sessions if s.isdigit()]
    if not numeric:
        raise RuntimeError("No numeric DE legislative session found.")
    return max(numeric, key=int)


def pull(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    key = _key()
    session = _latest_session(key)

    legs: dict[str, dict] = {}
    bills_seen = 0
    bills_with_votes = 0
    vote_events = 0
    page = 1
    max_page = 1

    while True:
        d = _get(f"/bills?jurisdiction={JUR}&session={session}&include=votes&sort=latest_action_desc&per_page=20&page={page}", key)
        max_page = d.get("pagination", {}).get("max_page", page)
        for bl in d.get("results", []):
            bills_seen += 1
            vs = bl.get("votes", []) or []
            if vs:
                bills_with_votes += 1
            for ev in vs:
                vote_events += 1
                for mv in ev.get("votes", []) or []:
                    voter = mv.get("voter") or {}
                    vid = voter.get("id") or mv.get("voter_name")
                    if not vid:
                        continue
                    role = voter.get("current_role") or {}
                    rec = legs.setdefault(vid, {
                        "id": vid,
                        "name": voter.get("name") or mv.get("voter_name") or "—",
                        "party": voter.get("party") or "—",
                        "chamber": CHAMBER.get(role.get("org_classification"), role.get("org_classification") or "—"),
                        "district": role.get("district") or "—",
                        "yes": 0, "no": 0, "other": 0, "total": 0,
                    })
                    opt = (mv.get("option") or "").lower()
                    rec["total"] += 1
                    if opt == "yes":
                        rec["yes"] += 1
                    elif opt == "no":
                        rec["no"] += 1
                    else:
                        rec["other"] += 1
        if page >= max_page:
            break
        page += 1
        time.sleep(0.8)

    legislators = list(legs.values())
    if len(legislators) < 30:
        raise RuntimeError(f"Only {len(legislators)} legislators with recorded votes — coverage/threading failure (silent-zero guard).")
    for L in legislators:
        L["participation_pct"] = round((L["yes"] + L["no"]) / L["total"] * 100, 1) if L["total"] else None
    legislators.sort(key=lambda L: (L["chamber"], _dist_key(L["district"]), L["name"]))

    summary = {
        "generated_at": _utc_now(),
        "session": session,
        "bills_in_session": bills_seen,
        "bills_with_recorded_votes": bills_with_votes,
        "vote_events": vote_events,
        "legislator_count": len(legislators),
        "legislators": legislators,
        "source": {
            "name": "Open States v3 (Plural Policy)",
            "endpoint": f"{BASE}/bills?jurisdiction=Delaware&session={session}&include=votes",
            "license": "Public domain dedication (attribution requested)",
            "official": "https://legis.delaware.gov/",
            "note": "Counts cover recorded roll-call votes in the current session. Voice votes and bills not brought to a recorded vote are not included. For the authoritative record, see legis.delaware.gov.",
        },
    }

    (out_dir / OUT_SUMMARY).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / OUT_MANIFEST).write_text(json.dumps({
        "generated_at": summary["generated_at"], "dashboard": "votes", "session": session,
        "sources": {"openstates": summary["source"]},
        "row_counts": {"legislators": len(legislators), "vote_events": vote_events, "bills_with_votes": bills_with_votes},
    }, indent=2), encoding="utf-8")
    return summary


def _dist_key(d: str):
    try:
        return (0, int(d))
    except (TypeError, ValueError):
        return (1, str(d))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull Delaware legislator voting records (Open States).")
    parser.add_argument("--out", type=Path, default=Path("votes/data"))
    args = parser.parse_args(argv)
    s = pull(args.out)
    print(f"wrote {args.out}/{OUT_SUMMARY}")
    print(f"  session {s['session']}: {s['legislator_count']} legislators, "
          f"{s['vote_events']} vote events across {s['bills_with_recorded_votes']}/{s['bills_in_session']} bills")
    top = sorted(s["legislators"], key=lambda L: -L["total"])[0]
    print(f"  most recorded votes: {top['name']} ({top['chamber']} dist {top['district']}) — {top['total']} votes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
