"""Validator for the Delaware Office Registry (offices/data/registry.json).

The registry is hand-curated: every office holder was read from the office's own official
page or roster, and every term length cites the U.S. Constitution, the Delaware Constitution
or the Delaware Code. This module checks the file so a bad edit cannot ship:

  - required fields on every entry, including `source` and `checked`
  - every source is an https URL
  - next_election == last_regular_election + term_years for even-year offices
  - annual school board elections point at the next second-Tuesday-of-May year
  - every seat on the 2026 ballot links to its /candidates/ page, and every 2026 race is covered
  - party is a factual text label from a fixed set
  - no phone numbers, emails, street addresses, em dashes or en dashes

Run:  python3 -m etl.office_registry            (exit 1 and list errors if invalid)
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "offices" / "data" / "registry.json"
BALLOT = ROOT / "candidates" / "data" / "ballot-2026.json"

PARTIES = {"Democratic", "Republican", "Independent Party of Delaware", "Libertarian", "Green", "Nonpartisan"}
LEVELS = {"federal", "statewide", "general-assembly", "new-castle-county", "kent-county", "sussex-county"}
OFFICE_REQUIRED = ("id", "level", "office", "description", "selection", "term_years", "term_source", "cycle",
                   "last_regular_election", "last_election_source", "next_election", "holder", "holder_status",
                   "ballot_2026_path", "source", "checked")
BOARD_REQUIRED = ("id", "district", "county", "selection", "seats", "term_years", "term_source", "cycle",
                  "next_election", "board_page", "source", "checked")
PII = [
    re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"mailto:|tel:", re.I),
    re.compile(r"\bDE,?\s+19\d{3}\b"),
    re.compile(r"\b\d+\s+[A-Za-z0-9. ]{2,40}\b(Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Lane|Ln|Boulevard|Blvd|Court|Ct|Way|Circle|Cir|Place|Pl|Highway|Hwy|Pike)\b\.?"),
    re.compile(r"\b(Address|Phone|Tel|Fax|Contact)\s*:", re.I),
    re.compile(r"P\.?O\.? Box", re.I),
]
# Completeness gate (codex audit 2026-10-14): a deletion must fail validation, not publish
# a silently smaller registry.
EXPECTED_OFFICE_IDS = (
    {"us-senate-class-1", "us-senate-class-2", "us-house", "governor", "lieutenant-governor",
     "attorney-general", "state-treasurer", "auditor", "insurance-commissioner"}
    | {f"state-senate-{n}" for n in range(1, 22)} | {f"state-house-{n}" for n in range(1, 42)}
    | {"ncc-county-executive", "ncc-council-president", "ncc-clerk-of-the-peace", "ncc-recorder-of-deeds",
       "ncc-register-of-wills", "ncc-sheriff"} | {f"ncc-council-district-{n}" for n in range(1, 13)}
    | {"kent-levy-court-at-large", "kent-clerk-of-the-peace", "kent-recorder-of-deeds", "kent-register-of-wills",
       "kent-sheriff"} | {f"kent-levy-court-district-{n}" for n in range(1, 7)}
    | {"sussex-clerk-of-the-peace", "sussex-recorder-of-deeds", "sussex-register-of-wills", "sussex-sheriff"}
    | {f"sussex-council-district-{n}" for n in range(1, 6)}
)
EXPECTED_SCHOOL_BOARDS = 19
DASHES = re.compile("[\\u2013\\u2014]|&" + "mdash;|&" + "ndash;")
HTTPS = re.compile(r"https://[^\s\"'<>]+$")


def next_annual_election_year(checked: str) -> int:
    """Year of the next school board election (second Tuesday of May) on or after `checked`."""
    d = datetime.date.fromisoformat(checked)
    may1 = datetime.date(d.year, 5, 1)
    second_tue = may1 + datetime.timedelta(days=(1 - may1.weekday()) % 7 + 7)
    return d.year if d <= second_tue else d.year + 1


def _is_date(s) -> bool:
    try:
        datetime.date.fromisoformat(str(s))
        return True
    except ValueError:
        return False


def _https(errs: list[str], where: str, field: str, val, allow_none: bool = False) -> None:
    if val is None and allow_none:
        return
    if not isinstance(val, str) or not HTTPS.match(val):
        errs.append(f"{where}: {field} must be an https URL (got {val!r})")


def validate(reg: dict, ballot: dict | None = None, complete: bool = True) -> list[str]:
    errs: list[str] = []
    text = json.dumps(reg, ensure_ascii=False)
    for p in PII:
        if p.search(text):
            errs.append(f"PII gate: pattern {p.pattern!r} matched; the registry must not carry contact data")
    if DASHES.search(text):
        errs.append("em dash or en dash found; use commas, colons or 'to'")

    seen: set[str] = set()
    on_2026: set[str] = set()
    for o in reg.get("offices", []):
        w = f"office {o.get('id', '?')}"
        for f in OFFICE_REQUIRED:
            if f not in o:
                errs.append(f"{w}: missing required field {f}")
        if o.get("id") in seen:
            errs.append(f"{w}: duplicate id")
        seen.add(o.get("id"))
        if o.get("level") not in LEVELS:
            errs.append(f"{w}: unknown level {o.get('level')!r}")
        if "checked" in o and not _is_date(o["checked"]):
            errs.append(f"{w}: checked must be an ISO date")
        for f in ("source", "term_source", "last_election_source"):
            if f in o:
                _https(errs, w, f, o[f])
        t, last, nxt = o.get("term_years"), o.get("last_regular_election"), o.get("next_election")
        if o.get("cycle") == "even-year":
            if not (isinstance(t, int) and isinstance(last, int) and isinstance(nxt, int)):
                errs.append(f"{w}: term_years, last_regular_election and next_election must be integers")
            else:
                if nxt != last + t:
                    errs.append(f"{w}: next_election {nxt} != last_regular_election {last} + term_years {t}")
                if last % 2 or nxt % 2:
                    errs.append(f"{w}: regular elections fall in even years")
                if "checked" in o and _is_date(o["checked"]) and nxt < int(o["checked"][:4]):
                    errs.append(f"{w}: next_election {nxt} is already past; the entry is stale")
        else:
            errs.append(f"{w}: unknown cycle {o.get('cycle')!r}")
        h = o.get("holder")
        status = o.get("holder_status")
        if status == "verified":
            if not isinstance(h, dict) or not h.get("name"):
                errs.append(f"{w}: holder_status verified but no holder name")
            else:
                for f in ("source", "party_source"):
                    _https(errs, w, f"holder.{f}", h.get(f))
                _https(errs, w, "holder.took_office_source", h.get("took_office_source"), allow_none=True)
                if h.get("party") is None and h.get("party_status") != "not_listed_on_source":
                    errs.append(f"{w}: verified holder has no party; set it, or set party_status "
                                f"'not_listed_on_source' only after reading the source")
                if h.get("party") is not None and h["party"] not in PARTIES:
                    errs.append(f"{w}: holder party {h['party']!r} is not a known party label")
                if not _is_date(h.get("checked")):
                    errs.append(f"{w}: holder.checked must be an ISO date")
        elif status == "not_verified":
            if h is not None:
                errs.append(f"{w}: holder present but status not_verified")
            if not o.get("holder_unverified_reason"):
                errs.append(f"{w}: not_verified holder needs a holder_unverified_reason")
        else:
            errs.append(f"{w}: holder_status must be verified or not_verified")
        path = o.get("ballot_2026_path")
        if nxt == 2026 and not path:
            errs.append(f"{w}: next election is 2026 but no ballot_2026_path")
        if nxt != 2026 and path:
            errs.append(f"{w}: ballot_2026_path set but next election is {nxt}")
        if path:
            on_2026.add(path)

    if ballot is not None:
        paths = {r["path"]: r["id"] for r in ballot.get("races", [])}
        for p in on_2026:
            if p not in paths:
                errs.append(f"ballot_2026_path {p} is not a race path in ballot-2026.json")
        for p, rid in paths.items():
            if p not in on_2026:
                errs.append(f"2026 ballot race {rid} ({p}) has no registry entry")

    ids = {o.get("id") for o in reg.get("offices", [])}
    missing = sorted(EXPECTED_OFFICE_IDS - ids) if complete else []
    if missing:
        errs.append(f"registry incomplete: {len(missing)} expected offices missing (e.g. {missing[:4]})")
    if complete and len(reg.get("school_boards", [])) != EXPECTED_SCHOOL_BOARDS:
        errs.append(f"registry incomplete: {len(reg.get('school_boards', []))} school boards, expected {EXPECTED_SCHOOL_BOARDS}")

    for b in reg.get("school_boards", []):
        w = f"school board {b.get('id', '?')}"
        for f in BOARD_REQUIRED:
            if f not in b:
                errs.append(f"{w}: missing required field {f}")
        if b.get("id") in seen:
            errs.append(f"{w}: duplicate id")
        seen.add(b.get("id"))
        for f in ("source", "term_source"):
            if f in b:
                _https(errs, w, f, b[f])
        _https(errs, w, "board_page", b.get("board_page"), allow_none=True)
        _https(errs, w, "seats_source", b.get("seats_source"), allow_none=b.get("seats") is None)
        if "checked" in b and not _is_date(b["checked"]):
            errs.append(f"{w}: checked must be an ISO date")
        if b.get("cycle") == "annual":
            if b.get("selection") != "elected":
                errs.append(f"{w}: annual cycle requires selection elected")
            if _is_date(b.get("checked")) and b.get("next_election") != next_annual_election_year(b["checked"]):
                errs.append(f"{w}: next_election {b.get('next_election')} is not the next May election "
                            f"({next_annual_election_year(b['checked'])})")
        elif b.get("cycle") == "appointed":
            if b.get("selection") != "appointed" or b.get("next_election") is not None:
                errs.append(f"{w}: appointed boards have selection appointed and no next_election")
            if b.get("next_election") is None and b.get("selection") == "appointed" and b.get("election_month"):
                errs.append(f"{w}: appointed boards have no election month")
        else:
            errs.append(f"{w}: unknown cycle {b.get('cycle')!r}")
    return errs


def main(argv: list[str] | None = None) -> int:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    ballot = json.loads(BALLOT.read_text(encoding="utf-8")) if BALLOT.exists() else None
    errs = validate(reg, ballot)
    for e in errs:
        print("ERROR", e)
    n_v = sum(1 for o in reg["offices"] if o["holder_status"] == "verified")
    print(f"office registry: {len(reg['offices'])} offices ({n_v} holders verified), "
          f"{len(reg.get('school_boards', []))} school boards; {'INVALID' if errs else 'valid'}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
