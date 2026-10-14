"""Generate the static /water/ pages from water/data/water-systems.json.

Writes real HTML (no client-side rendering) so search engines and readers without
JavaScript see every system, figure and violation:

  water/index.html                       "Is my water safe?" index: explainer, find-your-system
                                         list (active community systems by county, alphabetical),
                                         other systems with a violation on record, statewide figures,
                                         and the lead service line note (text copied from
                                         water/data/water-summary.json, unchanged)
  water/system/<pwsid-lowercase>/        one page per system (active community systems plus any
                                         system with a violation on record)
  sitemap.xml                            only with --sitemap, and only between
                                         <!-- WATER:START --> and <!-- WATER:END --> if both exist

Stale system folders (a PWSID no longer in the data) are removed. Output is
deterministic: a run on unchanged data changes no file.

Neutrality: systems are listed alphabetically or by PWSID, never by violation
count. No page calls a system's water safe or unsafe. Every figure carries its
EPA source and the date the records were retrieved.

Run:  python3 -m etl.pages.water_pages [--sitemap]     (after etl.sources.epa_sdwis_systems)
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = "https://firststatelens.com"
DATA_REL = Path("water") / "data" / "water-systems.json"
LEAD_REL = Path("water") / "data" / "water-summary.json"

ECHO = "https://echo.epa.gov/detailed-facility-report?fid="
SDWIS_URL = "https://www.epa.gov/enviro/sdwis-overview"
CCR_URL = "https://www.epa.gov/ccr/ccr-information-consumers"
ODW_URL = "https://dhss.delaware.gov/dph/homepage/about/sections/hsp/licenses-and-permits/odw/"
ODW_CONSUMER_URL = "https://dhss.delaware.gov/dph/homepage/about/sections/hsp/licenses-and-permits/odw/consumer-information/"
DWW_URL = "https://drinkingwater.dhss.delaware.gov/"
WELLS_URL = "https://dhss.delaware.gov/dph/homepage/about/sections/ehdishome/labs/environmental-laboratory/private-drinking-water/"
REGS_URL = "https://www.epa.gov/sdwa/drinking-water-regulations-and-contaminants"

COUNTY_ORDER = ["New Castle", "Kent", "Sussex"]
NO_COUNTY = "County not listed in EPA records"

TYPE = {
    "CWS": "Community water system",
    "NTNCWS": "Non-transient non-community water system",
    "TNCWS": "Transient non-community water system",
}
ACTIVITY = {
    "A": "Active",
    "I": "Inactive",
    "N": "Changed from public to non-public",
    "M": "Merged with another system",
    "P": "Potential future system",
}
SOURCE = {
    "GW": "Ground water",
    "SW": "Surface water",
    "GWP": "Ground water, purchased from another system",
    "SWP": "Surface water, purchased from another system",
    "GU": "Ground water under the direct influence of surface water",
    "GUP": "Ground water under the direct influence of surface water, purchased",
}
CATEGORY = {
    "MCL": "Maximum contaminant level (MCL)",
    "MRDL": "Maximum residual disinfectant level (MRDL)",
    "TT": "Treatment technique (TT)",
    "MR": "Monitoring and reporting (MR)",
    "MON": "Monitoring (MON)",
    "RPT": "Reporting (RPT)",
    "Other": "Other",
}

e = lambda s: html.escape(str(s), quote=True)  # noqa: E731


def nice_date(iso: str | None) -> str:
    if not iso:
        return ""
    d = datetime.date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def fmt(n: int | None) -> str:
    return f"{n:,}" if n is not None else "Not listed"


def place_label(s: dict) -> str:
    if s.get("city"):
        return f"{s['city']}, DE"
    if s.get("county"):
        word = "Counties" if " and " in s["county"] else "County"
        return f"{s['county']} {word}, DE"
    return "Delaware"


def page_path(s: dict) -> str:
    return f"/water/system/{s['pwsid'].lower()}/"


def status_text(s: dict) -> str:
    base = ACTIVITY.get(s.get("activity") or "", f"EPA status code {s.get('activity') or 'not listed'}")
    if s.get("deactivated") and s.get("activity") != "A":
        return f"{base} (EPA deactivation date {nice_date(s['deactivated'])})"
    return base


def titles(systems: list[dict]) -> dict[str, str]:
    """Unique page titles; a PWSID is added only where two systems would share a title."""
    base = {s["pwsid"]: f"{s['name']} water system ({place_label(s)}): EPA violations on record" for s in systems}
    seen: dict[str, int] = {}
    for t in base.values():
        seen[t] = seen.get(t, 0) + 1
    return {p: (t if seen[t] == 1 else t.replace(" water system (", f" water system, PWSID {p} (", 1)) for p, t in base.items()}


STYLE = """<style>
  :root { --accent-primary: #38bdf8; }
  .title-eyebrow { color: #38bdf8; border-color: rgba(56,189,248,0.25); background: rgba(56,189,248,0.05); }
  .title-eyebrow::before { background: #38bdf8; box-shadow: 0 0 6px #38bdf8; }
  .neutrality { border-left-color: #38bdf8; }
  .crumbs { font-size: 13px; color: var(--text-tertiary); margin-bottom: 18px; }
  .crumbs a { color: var(--text-secondary); }
  .prose { font-size: 15px; color: var(--text-secondary); line-height: 1.65; max-width: 860px; }
  .prose p + p, .prose p + ol, .prose ol + p { margin-top: 12px; }
  .prose ol, .prose ul { margin: 10px 0 0 22px; }
  .prose li { margin: 4px 0; }
  .prose a, .src a, .facts a, .note a, .lead-card a { color: var(--text-primary); text-decoration: underline; }
  .prose strong { color: var(--text-primary); }
  .src { font-size: 12px; color: var(--text-tertiary); margin-top: 12px; line-height: 1.55; max-width: 980px; }
  .note { background: var(--surface-elevated); border: 1px solid var(--border-default); border-radius: 14px; padding: 18px 20px; max-width: 980px; font-size: 14px; color: var(--text-secondary); line-height: 1.6; }
  .note p + p { margin-top: 10px; }
  .facts { width: 100%; max-width: 860px; border-collapse: collapse; font-size: 14px; }
  .facts th, .facts td { text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--border-subtle); vertical-align: top; }
  .facts th { color: var(--text-tertiary); font-weight: 500; width: 40%; }
  .facts td { color: var(--text-primary); }
  .tablewrap { overflow-x: auto; }
  .viol-table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
  .viol-table th, .viol-table td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border-subtle); vertical-align: top; }
  .viol-table thead th { font-family: 'JetBrains Mono', monospace; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-tertiary); font-weight: 500; }
  .viol-table td { color: var(--text-secondary); }
  .viol-table td.rule { color: var(--text-primary); }
  .lead-card { background: var(--surface-elevated); border: 1px solid var(--border-default); border-left: 3px solid var(--amber-400); border-radius: 12px; padding: 20px 22px; }
  .lead-card ul { margin: 12px 0 0 18px; }
  .finder label { display: block; font-size: 14px; color: var(--text-primary); margin-bottom: 6px; }
  .finder input { width: 100%; max-width: 520px; padding: 10px 12px; font-size: 15px; border-radius: 10px; border: 1px solid var(--border-default); background: rgba(15,23,42,0.9); color: var(--text-primary); }
  .finder .count { font-size: 13px; color: var(--text-tertiary); margin-top: 6px; min-height: 1.2em; }
  .sys-group h3 { font-family: 'Space Grotesk', sans-serif; font-size: 18px; color: var(--text-primary); margin: 22px 0 8px; }
  .sys-list { list-style: none; margin: 0; padding: 0; columns: 2 320px; column-gap: 32px; }
  .sys-list li { break-inside: avoid; padding: 6px 0; border-bottom: 1px solid var(--border-subtle); font-size: 14px; }
  .sys-list a { color: var(--text-primary); }
  .sys-meta { display: block; font-size: 12px; color: var(--text-tertiary); }
  details.others { margin-top: 26px; }
  details.others summary { cursor: pointer; font-size: 15px; color: var(--text-primary); }
  .terms dt { color: var(--text-primary); font-weight: 600; margin-top: 12px; }
  .terms dd { margin: 2px 0 0 0; }
  @media (max-width: 640px) {
    .viol-table thead { display: none; }
    .viol-table, .viol-table tbody, .viol-table tr, .viol-table td { display: block; width: 100%; }
    .viol-table tr { border-bottom: 1px solid var(--border-subtle); padding: 8px 0; }
    .viol-table td { border: 0; padding: 3px 0; }
    .viol-table td[data-k]::before { content: attr(data-k) ": "; color: var(--text-tertiary); font-size: 12px; }
    .facts th { width: 45%; }
  }
</style>"""


def head(title: str, desc: str, path: str, jsonld: dict, og_type: str = "article") -> str:
    url = SITE + path
    ld = json.dumps(jsonld, indent=2, ensure_ascii=False).replace("<", "\\u003c")  # no </script> breakout
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<!-- Generated by etl/pages/water_pages.py from water/data/water-systems.json. Edit the generator, not this file. -->
<title>{e(title)} | First State Lens</title>
<meta name="description" content="{e(desc)}" />
<link rel="canonical" href="{e(url)}" />
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1" />
<meta name="theme-color" content="#030712" />
<meta name="geo.region" content="US-DE" />
<link rel="icon" href="/favicon.svg" type="image/svg+xml" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
<meta property="og:type" content="{og_type}" />
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
{ld}
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
      <div class="meta-item"><span>EPA SDWIS · DRINKING WATER</span></div>
    </div>
  </header>

  <main>
"""


def foot(build_line: str) -> str:
    return f"""  </main>

  <footer class="site-footer">
    <div class="footer-build">{e(build_line)}</div>
    <div class="footer-links">
      <a href="/water/">All Delaware water systems</a>
      <a href="{ODW_URL}">Delaware Office of Drinking Water</a>
      <a href="https://echo.epa.gov/">EPA ECHO (primary source)</a>
      <a href="{SDWIS_URL}">EPA SDWIS</a>
      <a href="/">First State Lens home</a>
    </div>
    <div>First State Lens is a FirmSide AI Civic Analytics Lab project. Nonpartisan. Every figure is sourced to a public record. We show you the data; you decide.</div>
  </footer>

</div>
"""


def crumbs(items: list[tuple[str, str]]) -> str:
    links = " › ".join(f'<a href="{e(p)}">{e(n)}</a>' for n, p in items[:-1])
    return f'  <nav class="crumbs" aria-label="Breadcrumb">{links} › <span aria-current="page">{e(items[-1][0])}</span></nav>\n'


def breadcrumb_ld(items: list[tuple[str, str]]) -> dict:
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + p} for i, (n, p) in enumerate(items)]}


def as_of_text(d: dict) -> str:
    return nice_date(d["data_as_of"])


SYSTEM_NEUTRALITY = """  <p class="neutrality">
    <strong>How to read this.</strong> This page copies EPA's record for one public water system from the Safe Drinking Water Information System (SDWIS), without interpretation. A <strong>violation</strong> is recorded when a water system breaks a federal or state drinking water rule. A <strong>health-based</strong> violation means a contaminant went over a federal limit or a required treatment step was not met. Most other violations are tests or reports that were missed or late. A <strong>returned to compliance</strong> date means the state recorded the violation as resolved. A past violation does not describe the water today. EPA updates this data about every three months, so the newest violations may not appear yet. Delaware's Office of Drinking Water regulates this system; if this page and the state's records differ, the state is right and we fix this page. We rank no water system and draw no conclusions.
  </p>
"""


def violation_rows(s: dict) -> str:
    rows = []
    for v in s["violations"]:
        rule = v["contaminant"] or f"EPA contaminant code {v['contaminant_code'] or 'not listed'}"
        cat = CATEGORY.get(v["category"] or "", v["category"] or "Not listed")
        rows.append(f"""        <tr class="viol">
          <td data-k="Period began">{e(nice_date(v['begin']) or 'Not listed')}</td>
          <td data-k="Period ended">{e(nice_date(v['end']) or 'Not listed')}</td>
          <td data-k="Rule or contaminant" class="rule">{e(rule)}</td>
          <td data-k="Category">{e(cat)}</td>
          <td data-k="Health-based">{'Yes' if v['health_based'] is True else ('No' if v['health_based'] is False else 'Not reported')}</td>
          <td data-k="Returned to compliance">{e(nice_date(v['returned_to_compliance']) or 'No date recorded')}</td>
        </tr>""")
    return "\n".join(rows)


def render_system(s: dict, d: dict, title: str) -> str:
    path = page_path(s)
    as_of = as_of_text(d)
    n = len(s["violations"])
    hb = sum(1 for v in s["violations"] if v["health_based"] is True)
    nr = sum(1 for v in s["violations"] if v["returned_to_compliance"] is None)
    type_label = TYPE.get(s["type"] or "", f"EPA type code {s['type'] or 'not listed'}")
    where = place_label(s)
    if n:
        desc = (f"{s['name']} (PWSID {s['pwsid']}), {type_label.lower()}, {where}: {n:,} drinking water "
                f"violation{'s' if n != 1 else ''} in EPA records, with dates, rule names, health-based flags "
                f"and return-to-compliance dates.")
        count_line = (f"EPA SDWIS lists <strong>{n:,}</strong> violation{'s' if n != 1 else ''} for this system: "
                      f"{hb:,} health-based and {nr:,} with no return-to-compliance date recorded. Newest first.")
    else:
        desc = (f"{s['name']} (PWSID {s['pwsid']}), {type_label.lower()}, {where}: EPA drinking water records, "
                f"people served, water source and how to get the yearly water quality report.")
        count_line = f"EPA SDWIS lists no violations for this system in the records retrieved {e(as_of)}."
    items = [("Home", "/"), ("Delaware drinking water", "/water/"), (s["name"], path)]
    out = [head(title, desc, path, breadcrumb_ld(items)), crumbs(items)]
    out.append(f"""  <div class="title-block">
    <span class="title-eyebrow">Drinking Water · {e(type_label)}</span>
    <h1 class="title-h1">{e(s['name'])} <span class="highlight">water system</span></h1>
    <p class="title-sub">PWSID {e(s['pwsid'])} · {e(where)}. EPA's record of drinking water violations for this public water system, as retrieved {e(as_of)}.</p>
  </div>

{SYSTEM_NEUTRALITY}
  <section class="section" aria-labelledby="facts-title">
    <div class="section-head">
      <h2 class="section-title" id="facts-title">System facts</h2>
      <span class="section-meta">EPA SDWIS · AS OF {e(as_of.upper())}</span>
    </div>
    <table class="facts">
      <caption class="sr-only">Facts EPA records for {e(s['name'])}</caption>
      <tbody>
        <tr><th scope="row">Name in EPA records</th><td>{e(s['epa_name'] or 'Not listed')}</td></tr>
        <tr><th scope="row">Public water system ID (PWSID)</th><td>{e(s['pwsid'])}</td></tr>
        <tr><th scope="row">System type</th><td>{e(type_label)}</td></tr>
        <tr><th scope="row">Status</th><td>{e(status_text(s))}</td></tr>
        <tr><th scope="row">County served</th><td>{e(s['county'] or 'Not listed in EPA records')}</td></tr>
        <tr><th scope="row">City or town served</th><td>{e(s['city'] or 'Not listed in EPA records')}</td></tr>
        <tr><th scope="row">People served (EPA figure)</th><td>{e(fmt(s['population']))}</td></tr>
        <tr><th scope="row">Primary water source</th><td>{e(SOURCE.get(s['source'] or '', s['source'] or 'Not listed'))}</td></tr>
      </tbody>
    </table>
    <p class="src">Source: <a href="{e(d['source']['water_system'])}">EPA SDWIS water system record</a> and <a href="{e(d['source']['geographic_area'])}">area served</a>, Delaware systems, retrieved {e(as_of)}. Full EPA report: <a href="{ECHO}{e(s['pwsid'])}">EPA ECHO report for {e(s['pwsid'])}</a>.</p>
  </section>

  <section class="section" aria-labelledby="viol-title">
    <div class="section-head">
      <h2 class="section-title" id="viol-title">Violations on record</h2>
      <span class="section-meta">BY DATE, NEWEST FIRST</span>
    </div>
    <p class="prose">{count_line}</p>
""")
    if n:
        out.append(f"""    <div class="tablewrap">
    <table class="viol-table">
      <caption class="sr-only">Drinking water violations EPA records for {e(s['name'])}, newest first</caption>
      <thead><tr><th scope="col">Compliance period began</th><th scope="col">Period ended</th><th scope="col">Rule or contaminant (EPA wording)</th><th scope="col">Category</th><th scope="col">Health-based</th><th scope="col">Returned to compliance</th></tr></thead>
      <tbody>
{violation_rows(s)}
      </tbody>
    </table>
    </div>
""")
    out.append(f"""    <p class="src">Source: <a href="{e(d['source']['violation'])}">EPA SDWIS violation records</a>, Delaware systems, retrieved {e(as_of)}. Rule and contaminant names: <a href="{e(d['source']['contaminant_names'])}">EPA ECHO contaminant list</a>. A blank end date or return-to-compliance date means EPA's record has none. For enforcement actions and the latest status, see the <a href="{ECHO}{e(s['pwsid'])}">EPA ECHO report for this system</a>.</p>
  </section>

  <section class="section" aria-labelledby="ccr-title">
    <div class="section-head">
      <h2 class="section-title" id="ccr-title">Get this system's water quality report</h2>
      <span class="section-meta">CONSUMER CONFIDENCE REPORT</span>
    </div>
    <div class="note">
      <p>Every community water system must give its customers a yearly water quality report, called a Consumer Confidence Report (CCR). It lists the contaminants found in the water and the federal limit for each. To get it, ask your water supplier (the contact is on your water bill) or check its website. <a href="{CCR_URL}">EPA: how to find and read your CCR</a>.</p>
      <p>Delaware's <a href="{ODW_URL}">Office of Drinking Water</a> (Division of Public Health) regulates public water systems in the state and can answer questions about this system. The state also publishes system records in <a href="{DWW_URL}">Drinking Water Watch</a>.</p>
    </div>
  </section>
""")
    out.append(foot(f"WATER SYSTEM {s['pwsid']} · {n:,} VIOLATIONS ON RECORD · DATA AS OF {d['data_as_of']} · SOURCE: EPA SDWIS"))
    out.append("</body>\n</html>\n")
    return "".join(out)


def group_active(active: list[dict]) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    for s in active:
        groups.setdefault(s["county"] or NO_COUNTY, []).append(s)
    for members in groups.values():
        members.sort(key=lambda s: (s["name"].lower(), s["pwsid"]))
    keys = [k for k in COUNTY_ORDER if k in groups]
    keys += sorted(k for k in groups if k not in COUNTY_ORDER and k != NO_COUNTY)
    if NO_COUNTY in groups:
        keys.append(NO_COUNTY)
    return [(k, groups[k]) for k in keys]


def _li(s: dict, extra: str = "") -> str:
    meta = " · ".join(x for x in (s["city"] or ("City not listed" if s["county"] else ""), extra, s["pwsid"]) if x)
    q = " ".join(x for x in (s["name"], s["epa_name"] or "", s["city"] or "", s["county"] or "", s["pwsid"]) if x).lower()
    return f'          <li data-q="{e(q)}"><a href="{page_path(s)}">{e(s["name"])}</a><span class="sys-meta">{e(meta)}</span></li>'


INDEX_NEUTRALITY = """  <p class="neutrality">
    <strong>How to read this.</strong> These are violations recorded in EPA's Safe Drinking Water Information System (SDWIS) for the public water systems Delaware regulates, shown without interpretation. A <strong>health-based</strong> violation means a contaminant went over a federal limit or a required treatment step was not met; most other violations are tests or reports that were missed or late. A <strong>returned to compliance</strong> date means the state recorded the violation as resolved. A past violation does not describe the water today. Systems are listed alphabetically; we rank none of them. EPA's data syncs about every three months, so a very recent violation may not appear yet. Lead service lines are covered separately below. First State Lens draws no conclusions. We show you the data; you decide.
  </p>
"""


def kpi(label: str, value: int, context: str, source_html: str) -> str:
    return f"""    <div class="kpi-card">
      <div class="kpi-label">{e(label)}</div>
      <div class="kpi-value">{value:,}</div>
      <div class="kpi-context">{e(context)}</div>
      <div class="kpi-source">{source_html}</div>
    </div>"""


def render_index(d: dict, lead: dict) -> str:
    t = d["totals"]
    as_of = as_of_text(d)
    systems = d["systems"]
    active = [s for s in systems if s["type"] == "CWS" and s["activity"] == "A"]
    others = sorted((s for s in systems if not (s["type"] == "CWS" and s["activity"] == "A")),
                    key=lambda s: (s["name"].lower(), s["pwsid"]))
    title = "Is My Water Safe? Delaware Drinking Water Systems and EPA Violations"
    desc = ("Find your Delaware public water system and read its EPA drinking water violation record: dates, rules, "
            "health-based flags and return-to-compliance dates for every community water system and every system with a violation on record, plus how to get your water quality report.")
    ld = {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": "Delaware public water systems and drinking water violations",
        "description": "Delaware's active community water systems and every Delaware public water system with a drinking water violation on record, with every violation EPA records for them, from the EPA Safe Drinking Water Information System (SDWIS). Nonpartisan, source-traced.",
        "url": SITE + "/water/", "isAccessibleForFree": True, "license": SITE + "/", "inLanguage": "en-US",
        "keywords": ["Is my water safe", "Delaware drinking water", "water quality", "EPA SDWIS",
                     "water violations", "public water systems", "Consumer Confidence Report"],
        "spatialCoverage": {"@type": "State", "name": "Delaware"},
        "creator": {"@type": "Organization", "name": "First State Lens", "url": SITE + "/"},
        "publisher": {"@type": "Organization", "name": "First State Lens", "url": SITE + "/"},
        "sourceOrganization": {"@type": "GovernmentOrganization", "name": "U.S. Environmental Protection Agency"},
        "includedInDataCatalog": {"@type": "DataCatalog", "name": "First State Lens Dashboards", "url": SITE + "/"},
        "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                          "contentUrl": SITE + "/water/data/water-systems.json"}],
        "dateModified": d["data_as_of"],
    }
    out = [head(title, desc, "/water/", ld, og_type="website")]
    src_ws = f'SOURCE · <a href="{e(d["source"]["water_system"])}">EPA SDWIS</a> · {e(as_of.upper())}'
    src_v = f'SOURCE · <a href="{e(d["source"]["violation"])}">EPA SDWIS</a> · {e(as_of.upper())}'
    out.append(f"""  <div class="title-block">
    <span class="title-eyebrow">Drinking Water · Delaware</span>
    <h1 class="title-h1">Is my <span class="highlight">water</span> safe?</h1>
    <p class="title-sub">Find your public water system and read its drinking water record from EPA: every violation, its dates, and whether the state recorded it as resolved. Delaware regulates {t['systems_on_record']:,} public water systems; this page covers the {t['community_active']:,} active community systems (where people live) and every other system with a violation on record, {t['pages']:,} in all, as retrieved {e(as_of)}.</p>
  </div>

{INDEX_NEUTRALITY}
  <section class="section" aria-labelledby="start-title">
    <div class="section-head">
      <h2 class="section-title" id="start-title">What these records can and cannot tell you</h2>
      <span class="section-meta">START HERE</span>
    </div>
    <div class="prose">
      <p>No website can tell you whether the water in your glass is safe right now. Two public records help you judge for yourself. Your water system's <strong>yearly water quality report</strong>, the Consumer Confidence Report, lists what was found in your water and the federal limit for each contaminant. EPA's <strong>violation record</strong>, on this site, shows when your system broke a drinking water rule and whether the state recorded the problem as resolved.</p>
      <ol>
        <li>Find your water supplier's name on your water bill.</li>
        <li>Find that system in the list below and open its page.</li>
        <li>Get its yearly water quality report from your supplier. <a href="{CCR_URL}">EPA explains how to find and read it.</a></li>
        <li>For questions, contact your supplier or Delaware's <a href="{ODW_URL}">Office of Drinking Water</a>. The state also publishes system records in <a href="{DWW_URL}">Drinking Water Watch</a>.</li>
      </ol>
      <p><strong>On a private well?</strong> A private well is not a public water system, so it is not in these records. The Division of Public Health has <a href="{WELLS_URL}">information for private well owners</a>.</p>
    </div>
  </section>

  <section class="section" aria-labelledby="find-title">
    <div class="section-head">
      <h2 class="section-title" id="find-title">Find your water system</h2>
      <span class="section-meta">ALPHABETICAL BY COUNTY</span>
    </div>
    <p class="prose">Homes on public water are served by a <strong>community water system</strong>. These are the {len(active):,} community systems EPA lists as active in Delaware, grouped by the county EPA records as served.</p>
    <div class="finder" id="finder" hidden>
      <label for="sys-filter">Filter by system name, town or PWSID</label>
      <input id="sys-filter" type="search" autocomplete="off" spellcheck="false" />
      <p class="count" id="sys-count" aria-live="polite"></p>
    </div>
""")
    for county, members in group_active(active):
        heading = county if county == NO_COUNTY else (f"{county} Counties" if " and " in county else f"{county} County")
        gid = "g-" + re.sub(r"[^a-z]+", "-", county.lower()).strip("-")
        out.append(f"""    <div class="sys-group" data-group>
      <h3 id="{gid}">{e(heading)} ({len(members):,})</h3>
        <ul class="sys-list" aria-labelledby="{gid}">
{chr(10).join(_li(s) for s in members)}
        </ul>
    </div>
""")
    out.append(f"""    <details class="others" id="others" data-group>
      <summary>Other systems with a violation on record ({len(others):,}): inactive systems, and schools, workplaces, restaurants and campgrounds with their own water</summary>
        <ul class="sys-list">
{chr(10).join(_li(s, TYPE.get(s['type'] or '', s['type'] or '') + (', ' + ACTIVITY.get(s['activity'] or '', '').lower() if s['activity'] != 'A' else '')) for s in others)}
        </ul>
    </details>
    <p class="src">Source: <a href="{e(d['source']['water_system'])}">EPA SDWIS water system records</a> and <a href="{e(d['source']['geographic_area'])}">areas served</a>, Delaware systems, retrieved {e(as_of)}. Names are shown as EPA records them, in readable capitals; each page also shows the exact EPA name.</p>
  </section>

  <section class="section" aria-labelledby="fig-title">
    <div class="section-head">
      <h2 class="section-title" id="fig-title">Statewide figures</h2>
      <span class="section-meta">EPA SDWIS · AS OF {e(as_of.upper())}</span>
    </div>
    <div class="kpi-grid">
{kpi("Public water systems on record", t["systems_on_record"], "Every public water system Delaware regulates, active or not.", src_ws)}
{kpi("Active community water systems", t["community_active"], "Systems that serve the same people year-round where they live.", src_ws)}
{kpi("Systems with a violation on record", t["systems_with_violations"], f"Systems with at least one recorded violation, recent or historical, out of {t['systems_on_record']:,}.", src_v)}
{kpi("Violations on record", t["violations_on_record"], "All recorded violations, recent and historical, for Delaware systems.", src_v)}
{kpi("Health-based violations", t["health_based"], "Recorded violations where a contaminant went over a federal limit or a required treatment step was not met.", src_v)}
{kpi("No return-to-compliance date", t["no_return_to_compliance_date"], "Recorded violations with no date showing the state recorded them as resolved. Some belong to systems that are no longer active.", src_v)}
    </div>
    <p class="src">Source: <a href="{e(d['source']['violation'])}">EPA SDWIS violation records</a> for systems with Delaware as the regulating state (PWSIDs beginning DE), retrieved {e(as_of)}. Download the <a href="/water/data/water-systems.json">data as JSON</a> (the {t['pages']:,} systems listed here and their violations; systems with no violation on record that are not community systems are counted but not listed).</p>
  </section>

  <section class="section" aria-labelledby="terms-title">
    <div class="section-head">
      <h2 class="section-title" id="terms-title">What the terms mean</h2>
      <span class="section-meta">EPA DEFINITIONS</span>
    </div>
    <dl class="prose terms">
      <dt>Community water system</dt><dd>Serves the same people year-round where they live, such as a town, a utility or a manufactured home community.</dd>
      <dt>Non-transient non-community water system</dt><dd>Serves at least 25 of the same people for at least six months a year where they are not living, such as a school or a workplace.</dd>
      <dt>Transient non-community water system</dt><dd>Serves people who do not stay long, such as a restaurant, a gas station or a campground.</dd>
      <dt>Maximum contaminant level (MCL)</dt><dd>A contaminant was measured above its federal limit.</dd>
      <dt>Treatment technique (TT)</dt><dd>A required treatment step or process was not met.</dd>
      <dt>Monitoring and reporting (MR, MON, RPT)</dt><dd>A required test or report was missed or late.</dd>
      <dt>Returned to compliance</dt><dd>The state recorded the violation as resolved, on the date shown.</dd>
    </dl>
    <p class="src">Source: <a href="{REGS_URL}">EPA drinking water regulations and contaminants</a> and <a href="{SDWIS_URL}">EPA SDWIS overview</a>.</p>
  </section>

  <section class="section" aria-labelledby="lead-title">
    <div class="section-head">
      <h2 class="section-title" id="lead-title">Lead service lines</h2>
      <span class="section-meta">CHECK YOUR UTILITY</span>
    </div>
    <div class="lead-card">
      <strong>{e(lead['headline'])}</strong>
      <p style="margin-top:8px; color:var(--text-secondary); font-size:13.5px;">{e(lead['detail'])}</p>
      <ul>
{chr(10).join(f'        <li><a href="{e(l["url"])}">{e(l["name"])}</a></li>' for l in lead['links'])}
      </ul>
      <p class="kpi-source" style="margin-top:14px;">DELAWARE PUBLISHES NO CENTRAL ADDRESS-LEVEL LEAD-LINE DATASET · EACH UTILITY MAINTAINS ITS OWN INVENTORY</p>
    </div>
  </section>
""")
    out.append(foot(f"{t['systems_on_record']:,} SYSTEMS · {t['violations_on_record']:,} VIOLATIONS ON RECORD · DATA AS OF {d['data_as_of']} · SOURCE: EPA SDWIS"))
    out.append(FILTER_JS)
    out.append("</body>\n</html>\n")
    return "".join(out)


FILTER_JS = """
<script>
(function () {
  var box = document.getElementById("finder");
  var input = document.getElementById("sys-filter");
  var count = document.getElementById("sys-count");
  var others = document.getElementById("others");
  if (!box || !input) return;
  box.hidden = false;
  var items = Array.prototype.slice.call(document.querySelectorAll("li[data-q]"));
  var groups = Array.prototype.slice.call(document.querySelectorAll("[data-group]"));
  function run() {
    var q = input.value.trim().toLowerCase();
    var shown = 0;
    items.forEach(function (li) {
      var hit = !q || li.getAttribute("data-q").indexOf(q) !== -1;
      li.hidden = !hit;
      if (hit) shown++;
    });
    groups.forEach(function (g) {
      g.hidden = !!q && !g.querySelector("li[data-q]:not([hidden])");
    });
    if (others && q && !others.hidden) others.open = true;
    count.textContent = q ? (shown === 1 ? "1 system matches." : shown + " systems match.") : "";
  }
  input.addEventListener("input", run);
})();
</script>
"""


def build_pages(d: dict, lead: dict) -> dict[str, str]:
    for k in ("headline", "detail", "links"):
        if not lead.get(k):
            raise RuntimeError(f"lead_note.{k} missing from water-summary.json; refusing to drop the lead note.")
    t = titles(d["systems"])
    pages = {page_path(s): render_system(s, d, t[s["pwsid"]]) for s in d["systems"]}
    pages["/water/"] = render_index(d, lead)
    return pages


def write_if_changed(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def remove_stale(root: Path, keep: set[str]) -> int:
    base = root / "water" / "system"
    removed = 0
    if not base.is_dir():
        return 0
    for child in sorted(base.iterdir()):
        if not child.is_dir() or not re.fullmatch(r"de[0-9a-z]{7}", child.name):
            continue
        if f"/water/system/{child.name}/" in keep:
            continue
        if {p.name for p in child.iterdir()} <= {"index.html"}:
            shutil.rmtree(child)
            removed += 1
    return removed


def update_sitemap(root: Path, paths: list[str], lastmod: str) -> bool:
    sm = root / "sitemap.xml"
    if not sm.exists():
        return False
    s = sm.read_text(encoding="utf-8")
    start, end = "<!-- WATER:START", "<!-- WATER:END -->"
    i, j = s.find(start), s.find(end)
    if i < 0 or j < 0 or j < i:
        return False
    urls = "\n".join(f"  <url><loc>{SITE}{p}</loc><lastmod>{lastmod}</lastmod><priority>0.6</priority></url>" for p in paths)
    block = f"<!-- WATER:START (generated by etl/pages/water_pages.py) -->\n{urls}\n  {end}"
    return write_if_changed(sm, s[:i] + block + s[j + len(end):])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the static /water/ pages.")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--sitemap", action="store_true", help="also fill the WATER:START/END block in sitemap.xml if present")
    a = ap.parse_args(argv)
    d = json.loads((a.root / DATA_REL).read_text(encoding="utf-8"))
    lead = json.loads((a.root / LEAD_REL).read_text(encoding="utf-8")).get("lead_note") or {}
    pages = build_pages(d, lead)
    changed = sum(write_if_changed(a.root / p.strip("/") / "index.html", txt) for p, txt in sorted(pages.items()))
    removed = remove_stale(a.root, set(pages))
    sm = False
    if a.sitemap:
        sm = update_sitemap(a.root, sorted(p for p in pages if p != "/water/"), d["data_as_of"])
    print(f"water pages: {len(pages)} generated, {changed} changed, {removed} stale removed, sitemap {'updated' if sm else 'unchanged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
