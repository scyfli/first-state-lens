"""Generate the static 2026 ballot pages from candidates/data/ballot-2026.json.

Writes real HTML (no client-side rendering) so search engines and readers without
JavaScript see every candidate:

  candidates/us-senate/, attorney-general/, state-treasurer/, auditor/      statewide (thin record)
  candidates/state-senate/district-1..21/                                  on and off the 2026 ballot
  candidates/state-house/district-1..41/
  candidates/new-castle-county/, kent-county/, sussex-county/               every county race
  candidates/index.html                                                    race list between BALLOT markers
  sitemap.xml                                                              page list between BALLOT markers

candidates/us-house/ is the hand-built full record and is never overwritten here.

Run:  python3 -m etl.pages.candidate_pages            (after etl.sources.de_candidates)
"""

from __future__ import annotations

import datetime
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "candidates" / "data" / "ballot-2026.json"
SITE = "https://firststatelens.com"
STATE_LIST = "https://elections.delaware.gov/candidates/candidatelist/genl_fcddt_2026.html"
STATE_MAPS = "https://elections.delaware.gov/maps/"
IVOTE = "https://ivote.de.gov"
COUNTIES = [("New Castle", "new-castle-county"), ("Kent", "kent-county"), ("Sussex", "sussex-county")]
STATEWIDE_PAGES = ["us-senate", "attorney-general", "state-treasurer", "auditor"]  # us-house is hand-built

e = lambda s: html.escape(str(s), quote=True)  # noqa: E731


def nice_date(iso: str | None) -> str:
    if not iso:
        return "Not listed"
    d = datetime.date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def stamp_text(b: dict) -> str:
    s = b["source"].get("last_updated")
    if not s:
        return "the current Department of Elections list"
    d = datetime.datetime.strptime(s, "%Y-%m-%d %I:%M %p")
    return f"the Department of Elections list as updated {d.strftime('%B')} {d.day}, {d.year}, at {d.strftime('%I:%M %p').lstrip('0').replace('AM', 'a.m.').replace('PM', 'p.m.')}"


def sentence(s: str) -> str:
    """End a sentence with exactly one period (stamps already end in 'a.m.' / 'p.m.')."""
    return s if s.endswith(".") else s + "."


def lastmod(b: dict) -> str:
    s = b["source"].get("last_updated")
    if not s:
        raise RuntimeError("source last_updated missing; refusing to stamp the sitemap with today's date")
    return s[:10]


BANNER = """  <div class="deadline-banner" data-election-banner role="region" aria-label="2026 election deadline">
    <span class="db-label">2026 election</span>
    <span class="db-text" data-election-text>Voter registration for the November 3 general election closes Saturday, October 10, at 11:59 p.m.</span>
    <a href="/vote/#register" data-election-link>How to vote</a>
  </div>
"""

STYLE = """<style>
  :root { --accent-primary: var(--violet-400); }
  .title-eyebrow { color: var(--violet-400); border-color: rgba(167,139,250,0.25); background: rgba(167,139,250,0.05); }
  .title-eyebrow::before { background: var(--violet-400); box-shadow: 0 0 6px var(--violet-400); }
  .neutrality { border-left-color: var(--violet-400); }
  .crumbs { font-size: 13px; color: var(--text-tertiary); margin-bottom: 18px; }
  .crumbs a { color: var(--text-secondary); }
  .slate { width: 100%; max-width: 980px; border-collapse: collapse; font-size: 14px; }
  .slate th, .slate td { text-align: left; padding: 12px 14px; border-bottom: 1px solid var(--border-subtle); vertical-align: top; }
  .slate th { font-family: 'JetBrains Mono', monospace; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-tertiary); font-weight: 500; }
  .slate td { color: var(--text-secondary); }
  .slate .cand { color: var(--text-primary); font-weight: 600; text-align: left; }
  .slate a { color: var(--text-primary); word-break: break-all; }
  .badge { display: inline-block; margin-left: 8px; padding: 1px 8px; border: 1px solid rgba(167,139,250,0.4); border-radius: 999px; font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--violet-400); vertical-align: middle; }
  .fact { font-size: 14px; color: var(--text-secondary); line-height: 1.6; max-width: 860px; margin-top: 12px; }
  .fact strong { color: var(--text-primary); }
  .fact a, .note a { color: var(--text-primary); }
  .note { background: var(--surface-elevated); border: 1px solid var(--border-default); border-radius: 14px; padding: 18px 20px; max-width: 980px; font-size: 14px; color: var(--text-secondary); line-height: 1.6; }
  .src { font-size: 12px; color: var(--text-tertiary); margin-top: 10px; }
  .src a { color: var(--text-tertiary); }
  .pager { display: flex; gap: 16px; flex-wrap: wrap; font-size: 14px; margin-top: 8px; }
  .pager a { color: var(--text-secondary); }
  @media (max-width: 640px) {
    .slate thead { display: none; }
    .slate, .slate tbody, .slate tr, .slate td, .slate th[scope=row] { display: block; width: 100%; }
    .slate tr { border-bottom: 1px solid var(--border-subtle); padding: 10px 0; }
    .slate td, .slate th[scope=row] { border: 0; padding: 4px 0; }
    .slate td[data-k]::before { content: attr(data-k) ": "; color: var(--text-tertiary); font-size: 12px; }
  }
</style>"""


def head(title: str, desc: str, path: str, crumbs: list[tuple[str, str]]) -> str:
    url = SITE + path
    bc = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + p} for i, (n, p) in enumerate(crumbs)]}
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{e(title)} | First State Lens</title>
<meta name="description" content="{e(desc)}" />
<link rel="canonical" href="{e(url)}" />
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1" />
<meta name="theme-color" content="#030712" />
<meta name="geo.region" content="US-DE" />
<link rel="icon" href="/favicon.svg" type="image/svg+xml" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
<meta property="og:type" content="article" />
<meta property="og:site_name" content="First State Lens" />
<meta property="og:title" content="{e(title)}" />
<meta property="og:description" content="{e(desc)}" />
<meta property="og:url" content="{e(url)}" />
<meta property="og:image" content="{SITE}/assets/og-image.png" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
<meta property="og:locale" content="en_US" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{e(title)}" />
<meta name="twitter:description" content="{e(desc)}" />
<meta name="twitter:image" content="{SITE}/assets/og-image.png" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/fsl.css" />
{STYLE}
<script type="application/ld+json">
{json.dumps(bc, indent=2)}
</script>
</head>
<body>

<div class="container">

  <header class="topbar">
    <a class="brand" href="/" style="text-decoration:none;color:inherit;">
      <div class="brand-mark">FS</div>
      <div class="brand-text">
        <div class="brand-name">First State Lens</div>
        <div class="brand-tagline">Civic Analytics Lab · Delaware</div>
      </div>
    </a>
    <div class="topbar-meta">
      <div class="meta-item"><span>GENERAL ELECTION · NOV 3, 2026</span></div>
      <div class="meta-item"><a href="/candidates/method/">Method ↗</a></div>
    </div>
  </header>

  <main>
  <nav class="crumbs" aria-label="Breadcrumb">{' › '.join(f'<a href="{e(p)}">{e(n)}</a>' for n, p in crumbs[:-1])} › <span aria-current="page">{e(crumbs[-1][0])}</span></nav>
"""


NEUTRALITY = """  <p class="neutrality">
    <strong>How to read this.</strong> This page lists every candidate the Delaware Department of Elections shows for this office, in the state's own order, with the same fields for each person: party, filing status, filing date, and campaign website if the state lists one. We publish no home addresses or phone numbers, rank no one and endorse no one. The Department of Elections is the authority; if this page and the state list differ, the state is right and we fix this page. <a href="/candidates/method/">Read the method.</a>
  </p>
"""


def foot(b: dict) -> str:
    return f"""  </main>

  <footer class="site-footer">
    <div class="footer-build">CANDIDATE RECORD · 2026 GENERAL ELECTION · SOURCE: DELAWARE DEPARTMENT OF ELECTIONS · METHOD v{e(b['method_version'])}</div>
    <div class="footer-links">
      <a href="/candidates/">Who's on the Delaware ballot</a>
      <a href="/vote/">How to vote in 2026</a>
      <a href="/">First State Lens home</a>
    </div>
    <div>First State Lens is a FirmSide AI Civic Analytics Lab project. Nonpartisan. Every figure is sourced to a public record. We show you the data; you decide.</div>
  </footer>

</div>

<script src="/assets/election-banner.js"></script>
</body>
</html>
"""


def short_url(u: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", u).rstrip("/")


def slate_table(race: dict, caption: str) -> str:
    q = [c for c in race["candidates"] if c["status"] == "qualified"]
    rows = []
    for c in q:
        badge = ' <span class="badge">Incumbent</span>' if c.get("incumbent") else ""
        web = f'<a href="{e(c["website"])}" rel="nofollow noopener">{e(short_url(c["website"]))}</a>' if c.get("website") else "Not listed"
        rows.append(f"""        <tr>
          <th scope="row" class="cand">{e(c['name'])}{badge}</th>
          <td data-k="Party">{e(c['party'])}</td>
          <td data-k="Status">Qualified</td>
          <td data-k="Filed">{e(nice_date(c['filed']))}</td>
          <td data-k="Website">{web}</td>
        </tr>""")
    n = len(q)
    count = ("One qualified candidate is listed for this office." if n == 1 else f"{n} qualified candidates are listed for this office.")
    wd = ""
    if race.get("withdrawals"):
        items = "; ".join(f"{e(w['name'])} (withdrew {e(nice_date(w['withdrawn_on']))})" if w.get("withdrawn_on") else e(w["name"]) for w in race["withdrawals"])
        wd = f'\n    <p class="fact"><strong>Withdrawals on the state list:</strong> {items}.</p>'
    return f"""    <table class="slate">
      <caption class="sr-only">{e(caption)}</caption>
      <thead><tr><th scope="col">Candidate</th><th scope="col">Party</th><th scope="col">Status</th><th scope="col">Filed</th><th scope="col">Campaign website</th></tr></thead>
      <tbody>
{chr(10).join(rows)}
      </tbody>
    </table>
    <p class="fact">{count}</p>{wd}"""


def holder_block(race: dict, office_name: str) -> str:
    h = race.get("current_holder")
    if not h:
        return ""
    party = f" ({e(h['party'])})" if h.get("party") else ""
    cands = race.get("candidates", [])
    running = any(c.get("incumbent") and c["status"] == "qualified" for c in cands)
    withdrew = next((c for c in cands if c.get("incumbent") and c["status"] == "withdrawn"), None)
    if "candidates" not in race:
        status = ""
    elif running:
        status = f" {e(h['name'])} is a candidate for this office in 2026."
    elif withdrew:
        when = f" on {e(nice_date(withdrew['withdrawn_on']))}" if withdrew.get("withdrawn_on") else ""
        status = f" {e(h['name'])} withdrew from this race{when}, according to the state list."
    else:
        status = f" {e(h['name'])} does not appear on the 2026 candidate list for this office."
    if race["level"] in ("state-house", "state-senate"):
        src = f'<a href="/votes/">Voting record on First State Lens</a> (Open States)'
    else:
        src = f'<a href="{e(h["source"])}" rel="noopener">{e(h["source_label"])}</a>'
    lead = f"The current officeholder is <strong>{e(h['name'])}</strong>{party}." + status
    return f"""  <section class="section" aria-labelledby="holder-title">
    <div class="section-head"><h2 class="section-title" id="holder-title">Who holds this office now</h2></div>
    <p class="fact">{lead}</p>
    <p class="src">Source: {src}.</p>
  </section>
"""


def find_district_block() -> str:
    return f"""  <section class="section" aria-labelledby="find-title">
    <div class="section-head"><h2 class="section-title" id="find-title">Not sure which district you live in?</h2></div>
    <p class="fact">Look up your registration and districts at <a href="{IVOTE}">ivote.de.gov</a>, or see the Department of Elections <a href="{STATE_MAPS}">district maps</a>.</p>
  </section>
"""


def source_line(b: dict) -> str:
    return f'    <p class="src">Source: <a href="{STATE_LIST}">Delaware Department of Elections, Filed Candidates by Office</a>, checked against {e(sentence(stamp_text(b)))}</p>'


def race_page(b: dict, race: dict, title: str, h1: str, desc: str, crumbs, pager: str = "") -> str:
    return (head(title, desc, race["path"], crumbs) + f"""  <div class="title-block">
    <span class="title-eyebrow">2026 General Election · Delaware</span>
    <h1 class="title-h1">{h1}</h1>
    <p class="title-sub">{e(desc)}</p>
  </div>

{BANNER}
{NEUTRALITY}
  <section class="section" aria-labelledby="slate-title">
    <div class="section-head"><h2 class="section-title" id="slate-title">Candidates on the November 3, 2026 ballot</h2></div>
{slate_table(race, title)}
{source_line(b)}
  </section>

{holder_block(race, race['display'])}{find_district_block()}  <nav class="pager" aria-label="More races">{pager}<a href="/candidates/">Every race on the 2026 ballot</a></nav>
""" + foot(b))


def off_ballot_page(b: dict, r: dict, pager: str) -> str:
    n = r["district"]
    title = f"Delaware State Senate District {n}: not on the 2026 ballot"
    desc = f"Delaware State Senate District {n} is not on the November 3, 2026 general election ballot. It was on the 2024 ballot; its next regular election is in 2028."
    crumbs = [("Home", "/"), ("Who's on the ballot", "/candidates/"), ("State Senate", "/candidates/#state-senate"), (f"District {n}", r["path"])]
    h = holder_block({**r, "level": "state-senate"}, r["display"])
    return (head(title, desc, r["path"], crumbs) + f"""  <div class="title-block">
    <span class="title-eyebrow">2026 General Election · Delaware</span>
    <h1 class="title-h1">State Senate District <span class="highlight">{n}</span> is not on the 2026 ballot</h1>
    <p class="title-sub">{e(desc)}</p>
  </div>

{BANNER}
  <section class="section" aria-labelledby="cycle-title">
    <div class="section-head"><h2 class="section-title" id="cycle-title">Why there is no race here this year</h2></div>
    <div class="note">This seat is not on the 2026 general election ballot. It was on the <a href="{e(r['last_election_source'])}">2024 general election ballot</a>, and its next regular election is in 2028. Delaware elects its 21 state senators in staggered groups, so about half the Senate is on the ballot in a given general election.</div>
    <p class="src">Source: <a href="{STATE_LIST}">2026 candidate list</a> (District {n} not listed) and <a href="{e(r['last_election_source'])}">2024 candidate list</a> (District {n} listed), Delaware Department of Elections.</p>
  </section>

{h}{find_district_block()}  <nav class="pager" aria-label="More races">{pager}<a href="/candidates/">Every race on the 2026 ballot</a></nav>
""" + foot(b))


def county_page(b: dict, county: str, slug: str, races: list[dict]) -> str:
    path = f"/candidates/{slug}/"
    title = f"Who is running for {county} County offices in 2026"
    names = ", ".join(r["display"].replace(f"{county} County ", "") for r in races)
    desc = f"Every candidate for {county} County offices on Delaware's November 3, 2026 general election ballot: {names}."
    crumbs = [("Home", "/"), ("Who's on the ballot", "/candidates/"), (f"{county} County", path)]
    sections = []
    for r in races:
        anchor = r["path"].split("#", 1)[1]
        sections.append(f"""  <section class="section" aria-labelledby="{e(anchor)}">
    <div class="section-head"><h2 class="section-title" id="{e(anchor)}">{e(r['display'])}</h2></div>
{slate_table(r, r['display'])}
  </section>
""")
    return (head(title, desc, path, crumbs) + f"""  <div class="title-block">
    <span class="title-eyebrow">2026 General Election · {e(county)} County</span>
    <h1 class="title-h1">Who's running for <span class="highlight">{e(county)} County</span> offices</h1>
    <p class="title-sub">{e(desc)}</p>
  </div>

{BANNER}
{NEUTRALITY}
{''.join(sections)}  <p class="src">Source: <a href="{STATE_LIST}">Delaware Department of Elections, Filed Candidates by Office</a>, checked against {e(sentence(stamp_text(b)))}</p>
{find_district_block()}  <nav class="pager" aria-label="More races"><a href="/candidates/">Every race on the 2026 ballot</a></nav>
""" + foot(b))


def pager_links(prefix: str, n: int, lo: int, hi: int, label: str) -> str:
    out = []
    if n > lo:
        out.append(f'<a href="{prefix}district-{n-1}/">← {label} District {n-1}</a>')
    if n < hi:
        out.append(f'<a href="{prefix}district-{n+1}/">{label} District {n+1} →</a>')
    return "".join(out)


def index_block(b: dict) -> str:
    by = {r["id"]: r for r in b["races"]}

    def card(rid: str, label: str, href: str) -> str:
        r = by[rid]
        n = r["qualified_count"]
        return f'      <a class="race live" href="{href}"><div class="race-office">{e(label)}</div><div class="race-desc">{n} qualified candidate{"s" if n != 1 else ""}</div><span class="race-status">● Candidate list</span></a>'

    fed = [card("us-senate", "U.S. Senate", "/candidates/us-senate/"),
           card("us-house", "U.S. House, At-Large", "/candidates/us-house/"),
           card("attorney-general", "Attorney General", "/candidates/attorney-general/"),
           card("state-treasurer", "State Treasurer", "/candidates/state-treasurer/"),
           card("auditor", "Auditor of Accounts", "/candidates/auditor/")]
    sen = sorted((r for r in b["races"] if r["level"] == "state-senate"), key=lambda r: r["district"])
    sen_links = "\n".join(f'      <a class="dist" href="{r["path"]}">District {r["district"]}<span>{r["qualified_count"]} candidate{"s" if r["qualified_count"] != 1 else ""}</span></a>' for r in sen)
    off = ", ".join(f'<a href="{r["path"]}">District {r["district"]}</a>' for r in b["senate_not_on_2026_ballot"])
    house = sorted((r for r in b["races"] if r["level"] == "state-house"), key=lambda r: r["district"])
    house_links = "\n".join(f'      <a class="dist" href="{r["path"]}">District {r["district"]}<span>{r["qualified_count"]} candidate{"s" if r["qualified_count"] != 1 else ""}</span></a>' for r in house)
    cty = []
    for county, slug in COUNTIES:
        rs = [r for r in b["races"] if r["level"] == "county" and r["county"] == county]
        cty.append(f'      <a class="race live" href="/candidates/{slug}/"><div class="race-office">{e(county)} County</div><div class="race-desc">{len(rs)} race{"s" if len(rs) != 1 else ""} on the ballot</div><span class="race-status">● Candidate list</span></a>')
    c = b["counts"]
    return f"""<!-- BALLOT:START (generated by etl/pages/candidate_pages.py; edits here are overwritten) -->
  <section class="section" aria-labelledby="races-title">
    <div class="section-head">
      <h2 class="section-title" id="races-title">Every race on the 2026 ballot</h2>
      <span class="section-meta">{c['qualified']} QUALIFIED CANDIDATES · {c['races']} RACES</span>
    </div>
    <p class="fact">From {e(sentence(stamp_text(b)))} Not sure which districts you live in? Check <a href="{IVOTE}">ivote.de.gov</a> or the state's <a href="{STATE_MAPS}">district maps</a>.</p>
    <h3 class="sub-h" id="federal">Federal and statewide</h3>
    <div class="race-grid">
{chr(10).join(fed)}
    </div>
    <h3 class="sub-h" id="state-senate">State Senate</h3>
    <div class="dist-grid">
{sen_links}
    </div>
    <p class="fact">Not on the 2026 ballot (on the 2024 ballot, next election 2028): {off}.</p>
    <h3 class="sub-h" id="state-house">State House (all 41 districts)</h3>
    <div class="dist-grid">
{house_links}
    </div>
    <h3 class="sub-h" id="county">County offices</h3>
    <div class="race-grid">
{chr(10).join(cty)}
    </div>
    <p class="src">Source: <a href="{STATE_LIST}">Delaware Department of Elections, Filed Candidates by Office</a>.</p>
  </section>
<!-- BALLOT:END -->"""


def replace_between(text: str, start: str, end: str, block: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError(f"markers {start!r}/{end!r} must each appear exactly once")
    i, j = text.find(start), text.find(end)
    if i > j:
        raise RuntimeError(f"marker {end!r} comes before {start!r}")
    j += len(end)
    # the block carries its own markers
    return text[:i] + block + text[j:]


def write_if_changed(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def build_all(b: dict) -> dict:
    pages: dict[str, str] = {}
    by = {r["id"]: r for r in b["races"]}
    statewide_titles = {
        "us-senate": ("U.S. Senate", "Who is running for U.S. Senate in Delaware in 2026"),
        "attorney-general": ("Attorney General", "Who is running for Delaware Attorney General in 2026"),
        "state-treasurer": ("State Treasurer", "Who is running for Delaware State Treasurer in 2026"),
        "auditor": ("Auditor of Accounts", "Who is running for Delaware Auditor of Accounts in 2026"),
    }
    for rid in STATEWIDE_PAGES:
        r = by[rid]
        short, title = statewide_titles[rid]
        desc = f"Every qualified candidate for Delaware {short} on the November 3, 2026 general election ballot, from the Department of Elections list: party, filing date and campaign website."
        h1 = f"Who's running for Delaware <span class=\"highlight\">{e(short)}</span>"
        crumbs = [("Home", "/"), ("Who's on the ballot", "/candidates/"), (short, r["path"])]
        pages[r["path"]] = race_page(b, r, title, h1, desc, crumbs)
    for r in (x for x in b["races"] if x["level"] == "state-senate"):
        n = r["district"]
        title = f"Who is running for Delaware State Senate District {n} in 2026"
        desc = f"Every qualified candidate for Delaware State Senate District {n} on the November 3, 2026 general election ballot, from the Department of Elections list: party, filing date and campaign website."
        crumbs = [("Home", "/"), ("Who's on the ballot", "/candidates/"), ("State Senate", "/candidates/#state-senate"), (f"District {n}", r["path"])]
        pages[r["path"]] = race_page(b, r, title, f"Who's running for State Senate District <span class=\"highlight\">{n}</span>", desc, crumbs, pager_links("/candidates/state-senate/", n, 1, 21, "Senate"))
    for r in b["senate_not_on_2026_ballot"]:
        pages[r["path"]] = off_ballot_page(b, r, pager_links("/candidates/state-senate/", r["district"], 1, 21, "Senate"))
    for r in (x for x in b["races"] if x["level"] == "state-house"):
        n = r["district"]
        title = f"Who is running for Delaware State House District {n} in 2026"
        desc = f"Every qualified candidate for Delaware State House District {n} on the November 3, 2026 general election ballot, from the Department of Elections list: party, filing date and campaign website."
        crumbs = [("Home", "/"), ("Who's on the ballot", "/candidates/"), ("State House", "/candidates/#state-house"), (f"District {n}", r["path"])]
        pages[r["path"]] = race_page(b, r, title, f"Who's running for State House District <span class=\"highlight\">{n}</span>", desc, crumbs, pager_links("/candidates/state-house/", n, 1, 41, "House"))
    for county, slug in COUNTIES:
        rs = [r for r in b["races"] if r["level"] == "county" and r["county"] == county]
        if not rs:
            raise RuntimeError(f"No races parsed for {county} County")
        pages[f"/candidates/{slug}/"] = county_page(b, county, slug, rs)
    return pages


def main() -> int:
    b = json.loads(DATA.read_text(encoding="utf-8"))
    pages = build_all(b)
    if "/candidates/us-house/" in pages:
        raise RuntimeError("Refusing to overwrite the hand-built /candidates/us-house/ page.")
    changed = 0
    for path, text in pages.items():
        changed += write_if_changed(ROOT / path.strip("/") / "index.html", text)

    idx = ROOT / "candidates" / "index.html"
    t = idx.read_text(encoding="utf-8")
    t2 = replace_between(t, "<!-- BALLOT:START", "<!-- BALLOT:END -->", index_block(b))
    changed += write_if_changed(idx, t2)

    sm = ROOT / "sitemap.xml"
    s = sm.read_text(encoding="utf-8")
    lm = lastmod(b)
    urls = "\n".join(f"  <url><loc>{SITE}{p}</loc><lastmod>{lm}</lastmod><priority>0.7</priority></url>" for p in sorted(pages))
    s2 = replace_between(s, "<!-- BALLOT:START", "<!-- BALLOT:END -->", f"<!-- BALLOT:START (generated) -->\n{urls}\n  <!-- BALLOT:END -->")
    changed += write_if_changed(sm, s2)
    print(f"candidate pages: {len(pages)} generated, {changed} files changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
