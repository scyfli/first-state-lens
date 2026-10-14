"""Generate the static Delaware Office Registry pages from offices/data/registry.json.

Writes real HTML (no client-side rendering), deterministic output:

  offices/index.html                   every level, one compact table each
  offices/<level>/index.html           federal, statewide, general-assembly, new-castle-county,
                                       kent-county, sussex-county, school-boards

The registry is validated first (etl/office_registry.py); an invalid registry writes nothing.

Run:  python3 -m etl.pages.office_pages
"""

from __future__ import annotations

import datetime
import html
import json
import re
import sys
from pathlib import Path

from etl import office_registry as orx

ROOT = Path(__file__).resolve().parents[2]
SITE = "https://firststatelens.com"
e = lambda s: html.escape(str(s), quote=True)  # noqa: E731

INTRO = {
    "federal": "Delaware's two U.S. Senators and its one U.S. Representative, who is elected statewide.",
    "statewide": "The six state executive offices Delaware voters elect statewide.",
    "general-assembly": "All 21 State Senate seats and all 41 State House seats, with the member serving today.",
    "new-castle-county": "New Castle County's elected executive, council and row offices.",
    "kent-county": "Kent County Levy Court and the county's elected row offices.",
    "sussex-county": "Sussex County Council and the county's elected row offices.",
    "school-boards": "One row per public school district board: how many seats, how long a term, and when elections are held.",
}

STYLE = """<style>
  :root { --accent-primary: var(--indigo-400); }
  .title-eyebrow { color: var(--indigo-400); border-color: rgba(129,140,248,0.25); background: rgba(129,140,248,0.05); }
  .title-eyebrow::before { background: var(--indigo-400); box-shadow: 0 0 6px var(--indigo-400); }
  .neutrality { border-left-color: var(--indigo-400); }
  .crumbs { font-size: 13px; color: var(--text-tertiary); margin-bottom: 18px; }
  .crumbs a { color: var(--text-secondary); }
  .tbl-wrap { overflow-x: auto; max-width: 100%; }
  .reg { width: 100%; border-collapse: collapse; font-size: 14px; }
  .reg th, .reg td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border-subtle); vertical-align: top; }
  .reg thead th { font-family: 'JetBrains Mono', monospace; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-tertiary); font-weight: 500; }
  .reg td { color: var(--text-secondary); }
  .reg th[scope=row] { color: var(--text-primary); font-weight: 600; }
  .reg a { color: var(--text-primary); }
  .reg .small { display: block; font-size: 12px; color: var(--text-tertiary); margin-top: 4px; }
  .reg .small a { color: var(--text-tertiary); }
  .absent { font-style: italic; color: var(--text-tertiary); }
  .src { font-size: 12px; color: var(--text-tertiary); margin-top: 10px; max-width: 980px; }
  .src a { color: var(--text-tertiary); }
  .fact { font-size: 14px; color: var(--text-secondary); line-height: 1.6; max-width: 860px; margin-top: 12px; }
  .fact a { color: var(--text-primary); }
  .levels { display: flex; flex-wrap: wrap; gap: 10px 18px; font-size: 14px; margin: 8px 0 4px; }
  .levels a { color: var(--text-secondary); }
  @media (max-width: 720px) {
    .reg thead { display: none; }
    .reg, .reg tbody, .reg tr, .reg td, .reg th[scope=row] { display: block; width: 100%; }
    .reg tr { border-bottom: 1px solid var(--border-subtle); padding: 10px 0; }
    .reg td, .reg th[scope=row] { border: 0; padding: 3px 0; }
    .reg td[data-k]::before { content: attr(data-k) ": "; color: var(--text-tertiary); font-size: 12px; }
  }
</style>"""


def nice(iso: str) -> str:
    d = datetime.date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def host(u: str) -> str:
    return re.sub(r"^https://(www\.)?", "", u).split("/")[0]


def head(title: str, desc: str, path: str, crumbs: list[tuple[str, str]], reg: dict) -> str:
    url = SITE + path
    ld = [
        {"@context": "https://schema.org", "@type": "Dataset", "name": title, "description": desc, "url": url,
         "isAccessibleForFree": True, "inLanguage": "en-US", "dateModified": reg["checked"],
         "creator": {"@type": "Organization", "name": "First State Lens"},
         "keywords": ["Delaware elected officials", "Delaware office holders", "term of office", "next election"]},
        {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + p} for i, (n, p) in enumerate(crumbs)]},
    ]
    ld_json = json.dumps(ld, indent=2).replace("<", "\\u003c")
    trail = " › ".join(f'<a href="{e(p)}">{e(n)}</a>' for n, p in crumbs[:-1])
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
<meta property="og:type" content="website" />
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
{ld_json}
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
      <div class="meta-item"><span>OFFICE REGISTRY · CHECKED {e(nice(reg['checked']).upper())}</span></div>
    </div>
  </header>

  <main>
  <nav class="crumbs" aria-label="Breadcrumb">{trail}{' › ' if trail else ''}<span aria-current="page">{e(crumbs[-1][0])}</span></nav>
"""


def title_block(eyebrow: str, h1: str, sub: str) -> str:
    return f"""  <section class="title-block">
    <div class="title-eyebrow">{e(eyebrow)}</div>
    <h1 class="title-h1">{e(h1)}</h1>
    <p class="title-sub">{e(sub)}</p>
  </section>
"""


def neutrality(reg: dict) -> str:
    return f"""  <p class="neutrality">
    <strong>How to read this.</strong> Every office gets the same fields in the same order: what the office does, the term, who holds it today, the party label, the last and next regular election. Offices are listed by level, then by district number. Each holder was read from the office's own official page or roster on {e(nice(reg['checked']))}, and each term length cites the U.S. Constitution, the Delaware Constitution or the Delaware Code. Where we could not read an official source, the page says so and names no one. Party is the label on the Delaware Department of Elections list or the official roster. We rank no one and endorse no one. The official sources are the authority; if this page and an official source differ, the official source is right and we fix this page.
  </p>
"""


def foot(reg: dict) -> str:
    return f"""  </main>

  <footer class="site-footer">
    <div class="footer-build">DELAWARE OFFICE REGISTRY · CHECKED {e(reg['checked'])} · SCHEMA v{e(reg['schema_version'])} · SOURCES: OFFICIAL OFFICE PAGES, DELAWARE CODE, DEPARTMENT OF ELECTIONS</div>
    <div class="footer-links">
      <a href="/offices/">Delaware Office Registry</a>
      <a href="/candidates/">Who's on the Delaware ballot</a>
      <a href="/votes/">General Assembly voting record</a>
      <a href="/">First State Lens home</a>
    </div>
    <div>First State Lens is a FirmSide AI Civic Analytics Lab project. Nonpartisan. Every figure is sourced to a public record. We show you the data; you decide.</div>
  </footer>

</div>
</body>
</html>
"""


def office_label(o: dict) -> str:
    return o["office"] + (f", {o['seat']}" if o.get("seat") else "")


def holder_cell(o: dict) -> str:
    h = o.get("holder")
    if not h:
        return (f'<span class="absent">Not verified.</span><span class="small">{e(o["holder_unverified_reason"])} '
                f'<a href="{e(o["source"])}">Official page</a></span>')
    out = e(h["name"])
    extra = []
    if h.get("note"):
        extra.append(e(h["note"]) + (f' <a href="{e(h["took_office_source"])}">Caucus page</a>.' if h.get("took_office_source") else ""))
    extra.append(f'Source: <a href="{e(h["source"])}">{e(host(h["source"]))}</a>, checked {e(nice(h["checked"]))}.')
    return out + f'<span class="small">{" ".join(extra)}</span>'


def party_cell(o: dict) -> str:
    h = o.get("holder")
    if not h:
        return '<span class="absent">Not listed</span>'
    if not h.get("party"):
        return '<span class="absent">Not listed on the source</span>'
    return f'{e(h["party"])}<span class="small"><a href="{e(h["party_source"])}">{e(host(h["party_source"]))}</a></span>'


def next_cell(o: dict) -> str:
    out = str(o["next_election"])
    if o.get("ballot_2026_path"):
        out += f'<span class="small"><a href="{e(o["ballot_2026_path"])}">On the 2026 ballot: see candidates</a></span>'
    return out


def sort_key(o: dict):
    m = re.search(r"\d+", o.get("seat") or "")
    return (int(m.group()) if m else 0)


def office_table(rows: list[dict], caption: str) -> str:
    body = []
    for o in rows:
        body.append(f"""      <tr>
        <th scope="row">{e(office_label(o))}<span class="small">{e(o['description'])}</span></th>
        <td data-k="Holder">{holder_cell(o)}</td>
        <td data-k="Party">{party_cell(o)}</td>
        <td data-k="Term">{o['term_years']} years<span class="small"><a href="{e(o['term_source'])}">{e(host(o['term_source']))}</a></span></td>
        <td data-k="Last regular election"><a href="{e(o['last_election_source'])}">{o['last_regular_election']}</a></td>
        <td data-k="Next regular election">{next_cell(o)}</td>
      </tr>""")
        if o.get("notes"):
            body[-1] = body[-1].replace("</span></th>", f" {e(o['notes'])}</span></th>", 1)
    return f"""    <div class="tbl-wrap">
    <table class="reg">
      <caption class="sr-only">{e(caption)}</caption>
      <thead><tr><th scope="col">Office</th><th scope="col">Current holder</th><th scope="col">Party</th><th scope="col">Term</th><th scope="col">Last regular election</th><th scope="col">Next regular election</th></tr></thead>
      <tbody>
{chr(10).join(body)}
      </tbody>
    </table>
    </div>
"""


def board_table(rows: list[dict]) -> str:
    body = []
    for b in rows:
        seats = (f'{b["seats"]}<span class="small"><a href="{e(b["seats_source"])}">{e(host(b["seats_source"]))}</a></span>'
                 if b.get("seats") else '<span class="absent">Not verified</span>')
        page = (f'<a href="{e(b["board_page"])}">Board page</a><span class="small">Members listed on the district\'s board page.</span>'
                if b.get("board_page") else '<span class="absent">Not reached.</span><span class="small">The district site did not answer on the checked date.</span>')
        how = "Elected" if b["selection"] == "elected" else "Appointed by the Governor"
        when = (f'Every May<span class="small">{e(b["election_rule"])} <a href="{e(b["election_source"])}">delcode.delaware.gov</a></span>'
                if b["cycle"] == "annual" else '<span class="absent">No election</span>')
        nxt = str(b["next_election"]) if b.get("next_election") else '<span class="absent">Not elected</span>'
        body.append(f"""      <tr>
        <th scope="row">{e(b['district'])}<span class="small">{e(b['county'])} County</span></th>
        <td data-k="How chosen">{how}</td>
        <td data-k="Seats">{seats}</td>
        <td data-k="Term">{b['term_years']} years<span class="small">{e(b['term_note'])} <a href="{e(b['term_source'])}">delcode.delaware.gov</a></span></td>
        <td data-k="Election">{when}</td>
        <td data-k="Next election">{nxt}</td>
        <td data-k="Members">{page}</td>
      </tr>""")
    return f"""    <div class="tbl-wrap">
    <table class="reg">
      <caption class="sr-only">Delaware school district boards</caption>
      <thead><tr><th scope="col">District</th><th scope="col">How chosen</th><th scope="col">Seats</th><th scope="col">Term</th><th scope="col">Election</th><th scope="col">Next election</th><th scope="col">Members</th></tr></thead>
      <tbody>
{chr(10).join(body)}
      </tbody>
    </table>
    </div>
"""


def level_nav(reg: dict, current: str | None) -> str:
    links = []
    for lv in reg["levels"]:
        if lv["id"] == current:
            links.append(f'<span aria-current="page">{e(lv["name"])}</span>')
        else:
            links.append(f'<a href="{e(lv["path"])}">{e(lv["name"])}</a>')
    return f'  <nav class="levels" aria-label="Registry levels">{" ".join(links)}</nav>\n'


def level_rows(reg: dict, level: str) -> list[dict]:
    rows = [o for o in reg["offices"] if o["level"] == level]
    if level == "general-assembly":
        return sorted([o for o in rows if o["office"] == "State Senator"], key=sort_key) + \
            sorted([o for o in rows if o["office"] == "State Representative"], key=sort_key)
    return rows  # curated order: executive, then districts by number, then row offices


def level_page(reg: dict, lv: dict) -> str:
    lid, name, path = lv["id"], lv["name"], lv["path"]
    title = f"{name} elected offices in Delaware" if lid != "school-boards" else "Delaware school boards"
    desc = f"{INTRO[lid]} Term, current holder and next regular election, each linked to its official source."
    if lid == "school-boards":
        desc = INTRO[lid] + " Each fact links to the Delaware Code or the district's own page."
    parts = [head(title, desc, path, [("Home", "/"), ("Office Registry", "/offices/"), (name, path)], reg),
             title_block("Delaware Office Registry", title, INTRO[lid]), neutrality(reg), level_nav(reg, lid)]
    if lid == "school-boards":
        parts.append(f"""  <section>
    <div class="section-head"><h2>School district boards</h2></div>
    <p class="fact">Elected boards hold their election on the second Tuesday of May each year, and a member's term starts July 1 after the election. The boards of the three vocational-technical districts are appointed by the Governor, not elected.</p>
{board_table(reg['school_boards'])}    <p class="src">Sources: <a href="https://delcode.delaware.gov/title14/c010/sc03/index.html">14 Del. C. Chapter 10, Subchapter III</a> (board size, terms, appointed vocational-technical boards) and <a href="https://delcode.delaware.gov/title14/c010/sc04/index.html">Subchapter IV</a> (election date), and each district's own board page, checked {e(nice(reg['checked']))}.</p>
  </section>
""")
    elif lid == "general-assembly":
        for chamber, label in (("State Senator", "State Senate"), ("State Representative", "State House of Representatives")):
            rows = [o for o in level_rows(reg, lid) if o["office"] == chamber]
            parts.append(f"""  <section>
    <div class="section-head"><h2>{e(label)}</h2></div>
{office_table(rows, label)}    <p class="src">Holders and party: <a href="{e(rows[0]['holder']['source'])}">Delaware General Assembly member list</a>, checked {e(nice(reg['checked']))}. Terms: <a href="{e(rows[0]['term_source'])}">Delaware Constitution, Article II, Section 2</a>. Election years: Delaware Department of Elections candidate lists for <a href="{e(reg['election_lists']['2022'])}">2022</a>, <a href="{e(reg['election_lists']['2024'])}">2024</a> and <a href="{e(reg['election_lists']['2026'])}">2026</a>.</p>
  </section>
""")
    else:
        rows = level_rows(reg, lid)
        parts.append(f"""  <section>
    <div class="section-head"><h2>{e(name)} offices</h2></div>
{office_table(rows, name + ' offices')}    <p class="src">Each holder links to the official page it was read from. Election years: Delaware Department of Elections candidate lists for <a href="{e(reg['election_lists']['2022'])}">2022</a>, <a href="{e(reg['election_lists']['2024'])}">2024</a> and <a href="{e(reg['election_lists']['2026'])}">2026</a>.</p>
  </section>
""")
    parts.append(foot(reg))
    return "".join(parts)


def index_page(reg: dict) -> str:
    desc = ("Every elected office in Delaware from U.S. Senate to county row offices and school boards: "
            "what the office does, the term, who holds it, and the next regular election, each linked to an official source.")
    parts = [head("Delaware Office Registry", desc, "/offices/", [("Home", "/"), ("Office Registry", "/offices/")], reg),
             title_block("Who holds office in Delaware", "Delaware Office Registry", desc), neutrality(reg), level_nav(reg, None)]
    for lv in reg["levels"]:
        if lv["id"] == "school-boards":
            n = len(reg["school_boards"])
            parts.append(f"""  <section>
    <div class="section-head"><h2><a href="{e(lv['path'])}">{e(lv['name'])}</a></h2></div>
    <p class="fact">{n} school district boards. Elected boards vote every May; the three vocational-technical boards are appointed by the Governor. <a href="{e(lv['path'])}">See every board</a>.</p>
  </section>
""")
            continue
        rows = level_rows(reg, lv["id"])
        items = []
        for o in rows:
            h = o["holder"]["name"] if o.get("holder") else "Not verified"
            items.append(f'      <tr><th scope="row">{e(office_label(o))}</th><td data-k="Holder">{e(h)}</td><td data-k="Next regular election">{o["next_election"]}</td></tr>')
        parts.append(f"""  <section>
    <div class="section-head"><h2><a href="{e(lv['path'])}">{e(lv['name'])}</a></h2></div>
    <div class="tbl-wrap">
    <table class="reg">
      <caption class="sr-only">{e(lv['name'])} offices</caption>
      <thead><tr><th scope="col">Office</th><th scope="col">Current holder</th><th scope="col">Next regular election</th></tr></thead>
      <tbody>
{chr(10).join(items)}
      </tbody>
    </table>
    </div>
    <p class="src">Sources, party labels and terms for each office are on the <a href="{e(lv['path'])}">{e(lv['name'])} page</a>.</p>
  </section>
""")
    parts.append(foot(reg))
    return "".join(parts)


def write_if_changed(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def build_all(reg: dict) -> dict[str, str]:
    pages = {"offices/index.html": index_page(reg)}
    for lv in reg["levels"]:
        pages[lv["path"].strip("/") + "/index.html"] = level_page(reg, lv)
    return pages


def main() -> int:
    reg = json.loads(orx.REGISTRY.read_text(encoding="utf-8"))
    ballot = json.loads(orx.BALLOT.read_text(encoding="utf-8"))
    errs = orx.validate(reg, ballot)
    if errs:
        for x in errs:
            print("ERROR", x)
        raise SystemExit("registry invalid; no pages written")
    pages = build_all(reg)
    for rel, text in pages.items():
        if orx.DASHES.search(text):
            raise SystemExit(f"{rel}: em dash or en dash in generated page")
    changed = [rel for rel, text in pages.items() if write_if_changed(ROOT / rel, text)]
    print(f"office pages: {len(pages)} built, {len(changed)} changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
