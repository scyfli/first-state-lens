"""Delaware 2026 general election ballot puller (the full candidate list).

Source:  https://elections.delaware.gov/candidates/candidatelist/genl_fcddt_2026.html
         (Delaware Department of Elections, "Filed Candidates by Office")
License: Public election records.
Cadence: The Department updates the list as filings change; the page carries its own
         "Last Updated" stamp. Refreshed daily through Election Day by
         .github/workflows/candidates-daily.yml.
Output:  <out>/ballot-2026.json  +  <out>/ballot-manifest.json

Privacy (Mark's decision, 2026-10-05): PUBLIC-ROLE FIELDS ONLY. The state list carries
residential and mailing addresses, phone numbers and emails inside each candidate cell.
This puller reads the name, office, county, party, status, filing date and the campaign
website, and discards everything else in memory. A PII gate runs on the serialized output
before anything is written, and the write is refused if it trips.

Neutrality posture: candidates keep the state's own order within each race. Party is a
factual text label. A race with one qualified candidate is reported as a count, never as
"uncontested" or "safe". Incumbency is a label only where the voting-record roster
(votes/data/votes-summary.json) or a confirmed official source says so.

Run standalone:
    python3 -m etl.sources.de_candidates --out candidates/data
    python3 -m etl.sources.de_candidates --out candidates/data --html saved.html   # offline
"""

from __future__ import annotations

import argparse
import datetime
import html as htmllib
import json
import re
import sys
import time
from pathlib import Path

import requests

SOURCE_URL = "https://elections.delaware.gov/candidates/candidatelist/genl_fcddt_2026.html"
SOURCE_2024_URL = "https://elections.delaware.gov/candidates/candidatelist/genl_fcddt_2024.html"
UA = "FirstStateLens-ETL/0.1 (+https://firststatelens.com; contact: mark.sanders3@gmail.com)"
OUT_BALLOT = "ballot-2026.json"
OUT_MANIFEST = "ballot-manifest.json"
METHOD_VERSION = "1.0"
MIN_ROWS = 100  # silent-zero guard: the 2026 list had 128 rows on 2026-10-05

PARTY_LABELS = {
    "Democratic": "Democratic",
    "Republican": "Republican",
    "Ind Pty of DE": "Independent Party of Delaware",
    "Libertarian": "Libertarian",
    "Green": "Green",
    "Non-Partisan": "Nonpartisan",
}

# Statewide incumbents confirmed from official sources (checked 2026-10-05 in a browser;
# the state agency sites reject scripted requests). Name must match the ballot listing.
STATEWIDE_OFFICEHOLDERS = {
    "us-senate": {"name": "Chris Coons", "source": "https://www.coons.senate.gov/"},
    "us-house": {"name": "Sarah McBride", "source": "https://mcbride.house.gov/about"},
    "attorney-general": {"name": "Kathy Jennings", "source": "https://attorneygeneral.delaware.gov/"},
    "auditor": {"name": "Lydia York", "source": "https://auditor.delaware.gov/"},
    "state-treasurer": {"name": "Colleen Davis", "source": "https://treasurer.delaware.gov/"},
}

# State Senate districts NOT on the 2026 ballot were on the 2024 general election ballot
# (verified 2026-10-05: the 2024 list carries SD 2,3,4,6,10,11,16,17,18,21 and the 2026
# list SD 1,5,7,8,9,12,13,14,15,19,20, together all 21). Next regular election: 2028.
SENATE_2024_DISTRICTS = [2, 3, 4, 6, 10, 11, 16, 17, 18, 21]

PII_PATTERNS = [
    re.compile(r"\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"),
    re.compile(r"\bDE,?\s+19\d{3}\b"),
    re.compile(r"\b\d+\s+[A-Za-z0-9. ]{2,40}\b(Street|St\.|Road|Rd\.|Avenue|Ave\.|Drive|Dr\.|Lane|Ln\.|Court|Ct\.|Boulevard|Blvd|Way|Circle|Place|Apt)\b", re.I),
    re.compile(r"\bEmail\b|\bPO Box\b|P\.O\. Box", re.I),
    re.compile(r"Residential Address|Mailing Address|Email #|Phone #", re.I),
    re.compile(r"cdn-cgi/l/email-protection|__cf_email__"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
]


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch(url: str = SOURCE_URL, *, attempts: int = 4) -> str:
    last = None
    for i in range(attempts):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=(10, 60))
            if r.status_code >= 500 or r.status_code == 429:
                raise RuntimeError(f"HTTP {r.status_code} (transient)")
            r.raise_for_status()
            if "Request Rejected" in r.text[:2000]:
                raise RuntimeError("Department of Elections WAF rejected the request")
            return r.content.decode("utf-8", errors="strict")
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i < attempts - 1:
                time.sleep(2 ** i * 2)
    raise RuntimeError(f"GET {url} failed after {attempts}: {last}")


def _cell(row: str, label: str) -> str:
    m = re.search(r"data-label='" + re.escape(label) + r"'>(.*?)</td>", row, re.S)
    return m.group(1) if m else ""


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _iso_date(us: str) -> str | None:
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$", us or "")
    if not m:
        return None
    mo, d, y = (int(x) for x in m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}"


def classify_office(office: str, county: str) -> dict:
    """Map the state's office string to a race id, level, page path and display name."""
    o = office.strip()
    fixed = {
        "U.S. Senator": ("us-senate", "federal", "/candidates/us-senate/", "U.S. Senate"),
        "Representative in Congress": ("us-house", "federal", "/candidates/us-house/", "U.S. House of Representatives, At-Large"),
        "Attorney General": ("attorney-general", "statewide", "/candidates/attorney-general/", "Attorney General"),
        "State Treasurer": ("state-treasurer", "statewide", "/candidates/state-treasurer/", "State Treasurer"),
        "Auditor of Accounts": ("auditor", "statewide", "/candidates/auditor/", "Auditor of Accounts"),
    }
    if o in fixed:
        rid, level, path, name = fixed[o]
        return {"id": rid, "level": level, "path": path, "display": name, "district": None, "county": None}
    m = re.match(r"State Senator District (\d+)$", o)
    if m:
        n = int(m.group(1))
        return {"id": f"state-senate-{n}", "level": "state-senate", "path": f"/candidates/state-senate/district-{n}/",
                "display": f"State Senate District {n}", "district": n, "county": None}
    m = re.match(r"State Representative District (\d+)$", o)
    if m:
        n = int(m.group(1))
        return {"id": f"state-house-{n}", "level": "state-house", "path": f"/candidates/state-house/district-{n}/",
                "display": f"State House District {n}", "district": n, "county": None}
    m = re.match(r"(New Castle|Kent|Sussex) County (.+)$", o)
    if m:
        cty, rest = m.group(1), m.group(2).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", rest.lower()).strip("-")
        cslug = cty.lower().replace(" ", "-") + "-county"
        dm = re.search(r"District (\d+)$", rest)
        return {"id": f"{cslug}-{slug}", "level": "county", "path": f"/candidates/{cslug}/#{slug}",
                "display": f"{cty} County {rest}", "district": int(dm.group(1)) if dm else None, "county": cty}
    raise ValueError(f"Unrecognised office on the state list: {office!r} (county {county!r}). "
                     "Add it to classify_office rather than dropping it.")


def parse(html_text: str) -> tuple[list[dict], str | None]:
    """Return (rows, source_last_updated). Each row holds public-role fields only."""
    stamp = re.search(r"Last Updated:\s*([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{1,2}:[0-9]{2} [AP]M)", html_text)
    body = re.search(r"<tbody>(.*?)</tbody>", html_text, re.S)
    if not body:
        raise RuntimeError("Candidate table body not found; the page layout changed.")
    rows_html = re.findall(r"<tr data-county='[^']*'>(.*?)</tr>", body.group(1), re.S)
    out = []
    for r in rows_html:
        office = _text(_cell(r, "Office"))
        county = _text(_cell(r, "County"))
        party_raw = _text(_cell(r, "Party"))
        cand_html = _cell(r, "Candidate")
        name_m = re.search(r"class='main-span'[^>]*>(.*?)(?:<i\b|</span>)", cand_html, re.S)
        name = _text(name_m.group(1)) if name_m else ""
        if len(name) > 80 or re.search(r"\d|:|address", name, re.I):
            raise RuntimeError(f"Implausible candidate name parsed ({len(name)} chars); the cell layout changed. Refusing.")
        # Website: the only contact-cell field we keep. Everything else in the cell is dropped here.
        web_m = re.search(r"Website:\s*<a href='(https?://[^'\s]+)'", cand_html)
        website = web_m.group(1) if web_m else None
        if website is None and re.search(r"Website:", cand_html):
            raise RuntimeError(f"State lists a website for {name!r} but it did not parse; refusing to publish a false 'Not listed'.")
        status_raw = _text(_cell(r, "Status"))
        filed = _iso_date(_text(_cell(r, "Date Filed")))
        wd = re.search(r"WITHDRAWN\s+(\d{1,2}/\d{1,2}/\d{4})", r, re.I)
        status = "withdrawn" if status_raw.lower().startswith("withdrawn") or wd else ("qualified" if status_raw.lower() == "qualified" else status_raw.lower())
        if not name or not office:
            raise RuntimeError(f"Row missing name or office: office={office!r}")
        out.append({
            "office_source": office,
            "county_source": county,
            "name": name,
            "party_source": party_raw,
            "party": PARTY_LABELS.get(party_raw, party_raw),
            "status": status,
            "filed": filed,
            "withdrawn_on": _iso_date(wd.group(1)) if wd else None,
            "website": website,
        })
    return out, (stamp.group(1) if stamp else None)


def _last_name(name: str) -> str:
    n = re.sub(r'"[^"]*"', " ", name)
    n = re.sub(r"\b(Jr|Sr|II|III|IV)\.?$", "", n.strip(), flags=re.I)
    parts = [p for p in re.split(r"[\s,\-]+", n) if p and not re.fullmatch(r"[A-Z]\.?", p)]
    return parts[-1].lower().strip(".") if parts else ""


def load_roster(repo_root: Path) -> dict:
    """{('House'|'Senate', district:int): {name, party}} from the voting-record dashboard."""
    p = repo_root / "votes" / "data" / "votes-summary.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    roster = {}
    for leg in data.get("legislators", []):
        try:
            roster[(leg["chamber"], int(leg["district"]))] = {"name": leg["name"], "party": leg.get("party")}
        except (KeyError, ValueError, TypeError):
            continue
    return roster


def build(rows: list[dict], stamp: str | None, roster: dict) -> dict:
    races: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        c = classify_office(row["office_source"], row["county_source"])
        rid = c["id"]
        if rid not in races:
            races[rid] = {**c, "office_source": row["office_source"], "candidates": [], "current_holder": None}
            order.append(rid)
        races[rid]["candidates"].append({k: row[k] for k in ("name", "party", "status", "filed", "withdrawn_on", "website")})

    for rid in order:
        race = races[rid]
        holder = None
        if race["level"] in ("state-senate", "state-house"):
            chamber = "Senate" if race["level"] == "state-senate" else "House"
            leg = roster.get((chamber, race["district"]))
            if leg:
                holder = {"name": leg["name"], "party": leg["party"], "source": "/votes/", "source_label": "First State Lens voting record (Open States)"}
        elif rid in STATEWIDE_OFFICEHOLDERS:
            h = STATEWIDE_OFFICEHOLDERS[rid]
            holder = {"name": h["name"], "party": None, "source": h["source"], "source_label": "Official office website"}
        race["current_holder"] = holder
        for cand in race["candidates"]:
            cand["incumbent"] = bool(holder and _last_name(cand["name"]) == _last_name(holder["name"]))
        qualified = [x for x in race["candidates"] if x["status"] == "qualified"]
        race["qualified_count"] = len(qualified)
        race["withdrawals"] = [{"name": x["name"], "withdrawn_on": x["withdrawn_on"]} for x in race["candidates"] if x["status"] == "withdrawn"]

    # Senate districts not on the 2026 ballot get a stated record, not a missing page.
    off_ballot = []
    for n in SENATE_2024_DISTRICTS:
        if f"state-senate-{n}" in races:
            raise RuntimeError(f"SD {n} is on the 2026 list but recorded as a 2024 seat; update SENATE_2024_DISTRICTS.")
        leg = roster.get(("Senate", n))
        off_ballot.append({
            "id": f"state-senate-{n}", "level": "state-senate", "district": n,
            "path": f"/candidates/state-senate/district-{n}/", "display": f"State Senate District {n}",
            "on_2026_ballot": False, "last_election": 2024, "next_election": 2028, "last_election_source": SOURCE_2024_URL,
            "current_holder": {"name": leg["name"], "party": leg["party"], "source": "/votes/", "source_label": "First State Lens voting record (Open States)"} if leg else None,
        })

    return {
        "cycle": 2026,
        "election_date": "2026-11-03",
        "method_version": METHOD_VERSION,
        "source": {"url": SOURCE_URL, "name": "Delaware Department of Elections, Filed Candidates by Office", "last_updated": stamp},
        "counts": {
            "rows": len(rows),
            "qualified": sum(1 for r in rows if r["status"] == "qualified"),
            "withdrawn": sum(1 for r in rows if r["status"] == "withdrawn"),
            "races": len(order),
        },
        "races": [races[r] for r in order],
        "senate_not_on_2026_ballot": off_ballot,
    }


def pii_gate(serialized: str) -> None:
    hits = [p.pattern for p in PII_PATTERNS if p.search(serialized)]
    if hits:
        raise RuntimeError(f"PII gate tripped ({hits}); refusing to write candidate data.")


def validate(ballot: dict) -> None:
    c = ballot["counts"]
    if c["rows"] < MIN_ROWS:
        raise RuntimeError(f"Only {c['rows']} rows parsed (< {MIN_ROWS}); refusing to write (silent-zero guard).")
    ids = {r["id"] for r in ballot["races"]}
    for must in ("us-senate", "us-house", "attorney-general", "state-treasurer", "auditor"):
        if must not in ids:
            raise RuntimeError(f"Statewide race {must} missing from the parse; refusing to write.")
    house = sorted(r["district"] for r in ballot["races"] if r["level"] == "state-house")
    if house != list(range(1, 42)):
        raise RuntimeError(f"State House districts parsed {house}, expected 1..41.")
    statuses = {cand["status"] for r in ballot["races"] for cand in r["candidates"]}
    if not statuses <= {"qualified", "withdrawn"}:
        raise RuntimeError(f"Unknown candidate status values {sorted(statuses - {'qualified', 'withdrawn'})}; refusing to hide candidates.")
    if any(cand["filed"] is None for r in ballot["races"] for cand in r["candidates"] if cand["status"] == "qualified"):
        raise RuntimeError("A qualified candidate has no parsed filing date; the 'Date Filed' cell changed.")
    on = {r["district"] for r in ballot["races"] if r["level"] == "state-senate"}
    off = set(SENATE_2024_DISTRICTS)
    if on & off or on | off != set(range(1, 22)):
        raise RuntimeError(f"State Senate districts parsed {sorted(on)} do not complete 1..21 with the 2024 set; refusing.")
    if not ballot["source"].get("last_updated"):
        raise RuntimeError("The state's 'Last Updated' stamp did not parse; refusing (it dates every page).")
    if sum(len(r["candidates"]) for r in ballot["races"]) != c["rows"]:
        raise RuntimeError("Candidate total does not equal the source row count.")


def _content(obj: dict) -> dict:
    return {k: v for k, v in obj.items() if k not in ("generated_at", "retrieved_at")}


def write(out_dir: Path, ballot: dict) -> bool:
    """Write only when the content changed, so a no-change daily run makes no commit."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / OUT_BALLOT
    if target.exists():
        try:
            if _content(json.loads(target.read_text(encoding="utf-8"))) == _content(ballot):
                return False
        except json.JSONDecodeError:
            pass
    now = _utc_now()
    doc = {**ballot, "generated_at": now}
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    pii_gate(text)
    target.write_text(text, encoding="utf-8")
    manifest = {
        "dashboard": "candidates",
        "file": OUT_BALLOT,
        "generated_at": now,
        "source": ballot["source"],
        "row_counts": ballot["counts"],
        "method_version": METHOD_VERSION,
        "privacy": "Public-role fields only. Addresses, phone numbers and emails on the state list are not collected.",
    }
    mtext = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    pii_gate(mtext)
    (out_dir / OUT_MANIFEST).write_text(mtext, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="candidates/data")
    ap.add_argument("--html", help="parse a saved copy of the state page instead of fetching")
    args = ap.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    html_text = Path(args.html).read_text(encoding="utf-8") if args.html else fetch()
    rows, stamp = parse(html_text)
    ballot = build(rows, stamp, load_roster(repo_root))
    validate(ballot)
    changed = write(Path(args.out), ballot)
    c = ballot["counts"]
    print(f"ballot: {c['rows']} rows, {c['qualified']} qualified, {c['withdrawn']} withdrawn, {c['races']} races; "
          f"source updated {stamp}; {'written' if changed else 'unchanged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
