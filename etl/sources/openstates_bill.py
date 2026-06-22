"""Single-bill tracker puller — Open States v3 (Plural Policy).

Source: https://v3.openstates.org
License: Open States data is public-domain dedicated (attribution requested).
Output: <out>/bill.json + <out>/manifest.json

Reusable bill-tracking module for First State Lens. Given a Delaware bill
identifier (e.g. "SB 272") and a legislative session, it pulls the bill's
sponsors, full action timeline, recorded roll-call votes (with per-member
breakdown), and official documents, then writes a normalized bill.json the
static page renders. Point it at any bill to monitor that effort.

Reads OPENSTATES_API_KEY from the environment (free key). The orchestrated path
MUST thread it (same silent-zero discipline as the Census and votes pullers).

NEUTRALITY: this monitors WHERE a bill is and HOW members voted. It reports the
official record only — status, sponsors, actions, recorded votes. No scoring,
no side taken, no advocacy framing. The authoritative record is
legis.delaware.gov; we cite it and Open States.

Run standalone (key from env):
    OPENSTATES_API_KEY=... python3 -m etl.sources.openstates_bill --bill "SB 272" --session 153 --out bill-tracker/data
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
OUT_BILL = "bill.json"
OUT_MANIFEST = "manifest.json"
CHAMBER = {"upper": "Senate", "lower": "House"}
INCLUDES = ["sponsorships", "actions", "votes", "documents", "versions", "abstracts"]


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _key() -> str:
    k = os.environ.get("OPENSTATES_API_KEY")
    if not k:
        raise RuntimeError("OPENSTATES_API_KEY not set (silent-zero guard).")
    return k


def _get(url: str, key: str, *, attempts: int = 6) -> dict:
    for i in range(attempts):
        r = requests.get(
            url,
            headers={"X-API-KEY": key, "User-Agent": "FirstStateLens-ETL/0.1 (+https://firststatelens.com)"},
            timeout=(10, 90),
        )
        if r.status_code == 429:
            time.sleep(5 * (i + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Open States rate-limited after {attempts} attempts: {url}")


def _stable_timestamp(path: Path, new_obj: dict) -> str:
    """Preserve the prior generated_at when the substantive content is unchanged.

    The puller stamps generated_at on every run. Without this, an unchanged bill
    would still produce a differing file each run, defeating the workflow's
    commit-on-change gate (a quiet legislative week would churn a commit + redeploy).
    Comparing everything except generated_at lets an idle pull write a byte-identical
    file, so git sees no diff and the weekly job exits clean.
    """
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return new_obj["generated_at"]
        old_core = {k: v for k, v in old.items() if k != "generated_at"}
        new_core = {k: v for k, v in new_obj.items() if k != "generated_at"}
        if old_core == new_core:
            return old.get("generated_at", new_obj["generated_at"])
    return new_obj["generated_at"]


def _chamber_of(action: dict) -> str:
    org = (action.get("organization") or {}).get("name") or ""
    if "Senate" in org:
        return "Senate"
    if "House" in org:
        return "House"
    return org or "—"


def pull(bill_id: str, session: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    key = _key()

    inc = "&".join(f"include={i}" for i in INCLUDES)
    quoted = requests.utils.quote(bill_id)
    d = _get(f"{BASE}/bills/{JUR}/{session}/{quoted}?{inc}", key)

    if not d.get("identifier"):
        raise RuntimeError(f"Bill {bill_id!r} not found in session {session} (silent-zero guard): {d.get('detail')}")

    abstract = ""
    for a in d.get("abstracts", []):
        if a.get("abstract"):
            abstract = a["abstract"]
            break

    sponsors = [
        {"name": s.get("name"), "classification": s.get("classification"), "primary": bool(s.get("primary"))}
        for s in d.get("sponsorships", [])
    ]

    actions = [
        {"date": a.get("date", "")[:10], "chamber": _chamber_of(a), "description": a.get("description")}
        for a in d.get("actions", [])
    ]

    votes = []
    for v in d.get("votes", []):
        counts = {c.get("option"): c.get("value") for c in v.get("counts", [])}
        members = []
        for mv in v.get("votes", []):
            voter = mv.get("voter") or {}
            role = voter.get("current_role") or {}
            members.append({
                "name": mv.get("voter_name") or voter.get("name") or "—",
                "party": voter.get("party") or "—",
                "chamber": CHAMBER.get(role.get("org_classification"), role.get("org_classification") or "—"),
                "district": role.get("district") or "—",
                "option": (mv.get("option") or "other").lower(),
            })
        members.sort(key=lambda m: (m["option"] != "yes", m["name"]))
        votes.append({
            "date": (v.get("start_date") or "")[:10],
            "motion": v.get("motion_text") or "—",
            "result": v.get("result") or "—",
            "chamber": CHAMBER.get((v.get("organization") or {}).get("classification"),
                                   (v.get("organization") or {}).get("name") or "—"),
            "counts": {"yes": counts.get("yes", 0), "no": counts.get("no", 0), "other": counts.get("other", 0)},
            "members": members,
        })
    votes.sort(key=lambda v: v["date"])

    documents = []
    for x in d.get("documents", []) + d.get("versions", []):
        links = x.get("links") or []
        if links:
            documents.append({"note": x.get("note") or "Document", "url": links[0].get("url")})

    bill = {
        "generated_at": _utc_now(),
        "session": session,
        "identifier": d.get("identifier"),
        "title": d.get("title"),
        "abstract": abstract,
        "subjects": d.get("subject", []),
        "status": {
            "latest_action_date": (d.get("latest_action_date") or "")[:10],
            "latest_action_description": d.get("latest_action_description"),
            "first_action_date": (d.get("first_action_date") or "")[:10],
            "latest_passage_date": (d.get("latest_passage_date") or "")[:10] if d.get("latest_passage_date") else None,
        },
        "sponsors": sponsors,
        "actions": actions,
        "votes": votes,
        "documents": documents,
        "source": {
            "name": "Open States v3 (Plural Policy)",
            "openstates_url": d.get("openstates_url"),
            "endpoint": f"{BASE}/bills/{JUR}/{session}/{quoted}",
            "official": "https://legis.delaware.gov/",
            "license": "Public domain dedication (attribution requested)",
            "note": (
                "Status, sponsors, actions, and recorded votes are the official legislative record. "
                "Voice votes and unrecorded committee actions are not itemized. "
                "For the authoritative record, see legis.delaware.gov."
            ),
        },
    }

    # Idempotency: keep the prior timestamp if nothing substantive changed, so an
    # unchanged pull leaves both files byte-identical (no churn commit). The manifest
    # derives its generated_at and counts from the bill, so stabilizing the bill
    # stabilizes the manifest too.
    bill["generated_at"] = _stable_timestamp(out_dir / OUT_BILL, bill)

    (out_dir / OUT_BILL).write_text(json.dumps(bill, indent=2), encoding="utf-8")
    (out_dir / OUT_MANIFEST).write_text(json.dumps({
        "generated_at": bill["generated_at"], "dashboard": "bill-tracker",
        "session": session, "bill": bill["identifier"],
        "sources": {"openstates": bill["source"]},
        "row_counts": {"sponsors": len(sponsors), "actions": len(actions), "recorded_votes": len(votes)},
    }, indent=2), encoding="utf-8")
    return bill


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Pull a single Delaware bill's tracking record (Open States).")
    p.add_argument("--bill", required=True, help='Bill identifier, e.g. "SB 272"')
    p.add_argument("--session", default="153", help="Legislative session identifier (default 153)")
    p.add_argument("--out", type=Path, default=Path("bill-tracker/data"))
    args = p.parse_args(argv)
    b = pull(args.bill, args.session, args.out)
    print(f"wrote {args.out}/{OUT_BILL}")
    print(f"  {b['identifier']} (session {b['session']}): {len(b['sponsors'])} sponsors, "
          f"{len(b['actions'])} actions, {len(b['votes'])} recorded vote(s)")
    print(f"  status: {b['status']['latest_action_description']} ({b['status']['latest_action_date']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
