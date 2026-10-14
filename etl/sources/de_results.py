"""Delaware general election results puller (statewide totals per contest).

Source:  https://elections.delaware.gov/reports/GE<year>.html
         (Delaware Department of Elections, official general election results report)
License: Public election records.
Cadence: Past elections are fixed once certified, so 2020, 2022 and 2024 are pulled once
         and committed. For 2026 the Department publishes GE2026.html after the Boards of
         Canvass certify on Nov 5; run this puller with --years 2026 then (UPGRADE-PLAN E5).
Output:  <out>/results-history.json  +  <out>/results-manifest.json

What it reads: only the first ("Statewide") tab of the report. Each contest there is an
<h3 class="contest-title ..."> followed by a table whose rows carry the candidate as the
state lists it, the party, and the total votes and percentage. Later tabs repeat the same
contests split by district, election district and county; they are ignored. Only the first
occurrence of each contest title is used, which is the statewide total.

Mapping: every 2026 race (candidates/data/ballot-2026.json) and every State Senate seat not
on the 2026 ballot is matched to exactly one prior contest: the last general election for
that seat. U.S. Senate (Coons's seat) was last elected in 2020; U.S. House, State House and
the State Senate seats not up in 2026 in 2024; Attorney General, Treasurer, Auditor, the
State Senate seats up in 2026 and the 2026 county offices in 2022. A missing or duplicate
match raises and nothing is written.

Neutrality posture: raw totals and the state's own percentage, in the state's order. No
winner flag, no margin, no labels computed from the numbers. Names stay as the state prints
them.

Run standalone:
    python3 -m etl.sources.de_results --out candidates/data
    python3 -m etl.sources.de_results --out candidates/data --html-dir saved/   # offline, GE<year>.html files
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

REPORT_URL = "https://elections.delaware.gov/reports/GE{year}.html"
UA = "FirstStateLens-ETL/0.1 (+https://firststatelens.com; contact: mark.sanders3@gmail.com)"
OUT_HISTORY = "results-history.json"
OUT_MANIFEST = "results-manifest.json"
BALLOT_FILE = "ballot-2026.json"
YEARS = (2020, 2022, 2024)
MIN_CONTESTS = {2020: 60, 2022: 60, 2024: 60}  # silent-zero guard; each report has 85+ statewide contests

# 2026 race id -> (year, contest title as the state prints it, normalized below)
STATEWIDE_MAP = {
    "us-senate": (2020, "U.S. Senator"),
    "us-house": (2024, "U.S. Representative In Congress"),
    "attorney-general": (2022, "Attorney General"),
    "state-treasurer": (2022, "State Treasurer"),
    "auditor": (2022, "Auditor of Accounts"),
}
COUNTY_PREFIX = {"New Castle": "NCC", "Kent": "KC", "Sussex": "SC"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip().lower()


def fetch(year: int, session: requests.Session) -> str:
    url = REPORT_URL.format(year=year)
    last = None
    for attempt in range(4):
        try:
            r = session.get(url, headers={"User-Agent": UA}, timeout=60)
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            if "contest-title" not in r.text:
                raise RuntimeError(f"{url} returned no contest tables (WAF page or layout change)")
            return r.content.decode("utf-8-sig", errors="replace")
        except requests.RequestException as ex:
            last = str(ex)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not fetch {url}: {last}")


# Title must be plain text: later tabs nest district sub-headings inside the h3, and those
# blocks are skipped by construction (they are the by-district breakdowns, not totals).
_CONTEST = re.compile(r'<h3 class="contest-title[^"]*">([^<]*)</h3>\s*<table[^>]*>(.*?)</table>', re.S)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TH = re.compile(r"<th[^>]*>(.*?)</th>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)  # cells read by column position: some rows omit data-label
HEADER_ALIASES = {"candidate name": "candidate", "party name": "party"}


def _text(v: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", v))).strip()


def _num(s: str) -> int:
    s = s.replace(",", "").strip()
    if not re.fullmatch(r"\d+", s):
        raise ValueError(f"not a vote count: {s!r}")
    return int(s)


def _pct(s: str) -> float:
    s = s.replace("%", "").strip()
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        raise ValueError(f"not a percentage: {s!r}")
    return float(s)


def parse_report(text: str, year: int) -> dict[str, dict]:
    """Return {normalized title: contest} for the FIRST occurrence of each contest (statewide tab)."""
    out: dict[str, dict] = {}
    for m in _CONTEST.finditer(text):
        title = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip()
        key = norm(title)
        if key in out:
            continue
        cands = []
        header: list[str] = []
        for row in _ROW.findall(m.group(2)):
            ths = _TH.findall(row)
            if ths:
                header = [HEADER_ALIASES.get(norm(_text(t)), norm(_text(t))) for t in ths]
                continue
            tds = [_text(v) for v in _TD.findall(row)]
            if not tds:
                continue
            if not {"candidate", "party", "total votes", "percentage"} <= set(header) or len(tds) != len(header):
                raise RuntimeError(f"GE{year} contest {title!r}: unexpected table shape {header} / {len(tds)} cells")
            cells = dict(zip(header, tds))
            if not cells["candidate"]:
                raise RuntimeError(f"GE{year} contest {title!r}: blank candidate cell")
            cands.append({"name": cells["candidate"], "party": cells["party"], "votes": _num(cells["total votes"]), "percent": _pct(cells["percentage"])})
        if not cands:
            raise RuntimeError(f"GE{year} contest {title!r} has no candidate rows")
        out[key] = {"title": title, "candidates": cands, "total_votes": sum(c["votes"] for c in cands)}
    if len(out) < MIN_CONTESTS.get(year, 20):
        raise RuntimeError(f"GE{year}: only {len(out)} statewide contests parsed; refusing to write")
    return out


def target_for(race: dict) -> tuple[int, str]:
    rid, level, n = race["id"], race["level"], race.get("district")
    if rid in STATEWIDE_MAP:
        return STATEWIDE_MAP[rid]
    if level == "state-senate":
        return (2022 if race.get("on_2026_ballot", True) else 2024, f"State Senator District {n}")
    if level == "state-house":
        return 2024, f"State Representative District {n}"
    if level == "county":
        county = race["county"]
        rest = race["display"][len(f"{county} County "):]
        if county == "Kent" and rest.startswith("Levy Court"):
            return 2022, f"KC {rest}"
        if rest.startswith("Council District"):
            return 2022, f"{COUNTY_PREFIX[county]} County {rest}"
        return 2022, f"{COUNTY_PREFIX[county]} {rest}"
    raise RuntimeError(f"no results mapping rule for race {rid!r}")


def build(ballot: dict, reports: dict[int, dict[str, dict]]) -> dict:
    seats = list(ballot["races"]) + [{**r, "on_2026_ballot": False} for r in ballot["senate_not_on_2026_ballot"]]
    results = {}
    for race in seats:
        year, title = target_for(race)
        c = reports[year].get(norm(title))
        if c is None:
            raise RuntimeError(f"race {race['id']}: no GE{year} contest titled {title!r}")
        results[race["id"]] = {"year": year, "contest": c["title"], "source": REPORT_URL.format(year=year),
                               "candidates": c["candidates"], "total_votes": c["total_votes"]}
    if len(results) != len(seats):
        raise RuntimeError("duplicate race ids in the ballot file")
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--html-dir", help="read GE<year>.html from this folder instead of the network")
    ap.add_argument("--ballot", help="path to ballot-2026.json (default: <out>/ballot-2026.json)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    ballot = json.loads(Path(a.ballot or out / BALLOT_FILE).read_text(encoding="utf-8"))
    s = requests.Session()
    reports = {}
    for i, y in enumerate(YEARS):
        if a.html_dir:
            text = (Path(a.html_dir) / f"GE{y}.html").read_text(encoding="utf-8-sig", errors="replace")
        else:
            if i:
                time.sleep(2)
            text = fetch(y, s)
        reports[y] = parse_report(text, y)
    results = build(ballot, reports)
    hist = {"method_version": "1.0", "note": "Statewide totals from the last general election for each seat, as the Department of Elections reports them.",
            "results": dict(sorted(results.items()))}
    man = {"generated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
           "sources": {str(y): REPORT_URL.format(year=y) for y in YEARS},
           "contests_parsed": {str(y): len(reports[y]) for y in YEARS},
           "seats_mapped": len(results)}
    out.mkdir(parents=True, exist_ok=True)
    new = json.dumps(hist, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    f = out / OUT_HISTORY
    if not f.exists() or f.read_text(encoding="utf-8") != new:
        f.write_text(new, encoding="utf-8")
        (out / OUT_MANIFEST).write_text(json.dumps(man, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"results: {len(results)} seats mapped from {', '.join(f'GE{y} ({len(reports[y])} contests)' for y in YEARS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
