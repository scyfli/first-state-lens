"""Generate the static /road-safety/ page from road-safety/data/crashes-summary.json.

Every figure is written into the HTML (no client-side rendering), so the page reads the
same with JavaScript off and search engines see every count.

Layout: a statewide KPI row for the last full calendar year, a table per county (and
statewide) by year, and a table per county by month for the latest 36 months, oldest
first. Every month since January 2009 stays in the data file linked from the page.

Run:  python3 -m etl.pages.road_safety_page      (after etl.sources.de_crashes)
"""

from __future__ import annotations

import datetime
import html
import json
import sys
from pathlib import Path

from etl.pages.candidate_pages import write_if_changed

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "road-safety" / "data" / "crashes-summary.json"
OUT = ROOT / "road-safety" / "index.html"
SITE = "https://firststatelens.com"
PATH = "/road-safety/"
MONTH_WINDOW = 36
OHS_REPORTS = "https://ohs.delaware.gov/reports.shtml"

e = lambda s: html.escape(str(s), quote=True)  # noqa: E731

COLS = [
    ("all_reports", "All reports"),
    ("non_reportable", "Non-reportable"),
    ("property_damage_only", "Property damage only"),
    ("personal_injury", "Personal injury crashes"),
    ("fatality", "Fatality crashes"),
]


def nice_date(iso: str) -> str:
    d = datetime.date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def month_label(ym: str) -> str:
    d = datetime.date(int(ym[:4]), int(ym[5:7]), 1)
    return f"{d.strftime('%B')} {d.year}"


def n(v: int) -> str:
    return f"{int(v):,}"


STYLE = """<style>
  /* Road safety accent: cyan. Neutral on purpose: no red/green, no colour encodes a count. */
  :root { --accent-primary: var(--cyan-400); }
  .title-eyebrow { color: var(--cyan-400); border-color: rgba(34,211,238,0.25); background: rgba(34,211,238,0.05); }
  .title-eyebrow::before { background: var(--cyan-400); box-shadow: 0 0 6px var(--cyan-400); }
  .neutrality { border-left-color: var(--cyan-400); }
  .neutrality p + p { margin-top: 10px; }
  .neutrality a, .src a, .kpi-source a, .note a { color: var(--text-primary); }
  .neutrality ul { margin: 8px 0 0 20px; }
  .neutrality li { margin: 4px 0; }
  .tbl-wrap { overflow-x: auto; }
  .tbl-wrap:focus { outline: 2px solid var(--cyan-400); outline-offset: 2px; }
  .data-table th[scope=row] { color: var(--text-primary); font-weight: 500; white-space: nowrap; }
  .sub-h { font-family: 'Space Grotesk', sans-serif; font-size: 18px; color: var(--text-primary); margin: 28px 0 10px; }
  .sub-h:first-of-type { margin-top: 0; }
  .src { font-size: 12px; color: var(--text-tertiary); margin-top: 10px; line-height: 1.5; }
  .note { font-size: 14px; color: var(--text-secondary); line-height: 1.6; max-width: 860px; margin-bottom: 16px; }
  .kpi-value.kpi-date { font-size: 22px; }
</style>"""


def head(s: dict) -> str:
    src = s["source"]
    cov = s["coverage"]
    title = "Delaware Crashes by County and Month | First State Lens"
    desc = (
        f"Crash reports in Delaware by county and month since {month_label(cov['first_month'])}, "
        "in the state's own classifications: property damage, personal injury and fatality crashes. "
        "From the Department of Safety and Homeland Security public crash data."
    )
    ld = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "Delaware crash reports by county and month",
        "description": (
            "Counts of Delaware crash reports by county, month and crash classification, aggregated "
            "from the Delaware Department of Safety and Homeland Security Public Crash Data "
            "(data.delaware.gov 827n-m6xc). Counts of crashes, not people. No individual crash records."
        ),
        "url": SITE + PATH,
        "isAccessibleForFree": True,
        "license": SITE + "/",
        "inLanguage": "en-US",
        "keywords": ["Delaware crashes", "traffic crashes", "fatality crashes", "road safety", "crash data by county"],
        "spatialCoverage": {"@type": "State", "name": "Delaware"},
        "temporalCoverage": f"{cov['first_month']}/{cov['last_crash_date']}",
        "creator": {"@type": "Organization", "name": "First State Lens", "url": SITE + "/"},
        "publisher": {"@type": "Organization", "name": "First State Lens", "url": SITE + "/"},
        "sourceOrganization": {"@type": "GovernmentOrganization", "name": src.get("publisher") or "Delaware Department of Safety and Homeland Security"},
        "isBasedOn": src["url"],
        "includedInDataCatalog": {"@type": "DataCatalog", "name": "First State Lens Dashboards", "url": SITE + "/"},
        "dateModified": src["rows_updated"],
    }
    ld_json = json.dumps(ld, indent=2).replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}" />
<link rel="canonical" href="{SITE}{PATH}" />
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1" />
<meta name="theme-color" content="#030712" />
<meta name="geo.region" content="US-DE" />
<link rel="icon" href="/favicon.svg" type="image/svg+xml" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="First State Lens" />
<meta property="og:title" content="{e(title)}" />
<meta property="og:description" content="{e(desc)}" />
<meta property="og:url" content="{SITE}{PATH}" />
<meta property="og:image" content="{SITE}/assets/og-image.png" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
<meta property="og:locale" content="en_US" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{e(title)}" />
<meta name="twitter:description" content="{e(desc)}" />
<meta name="twitter:image" content="{SITE}/assets/og-image.png" />
<script type="application/ld+json">
{ld_json}
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/fsl.css" />
{STYLE}
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
      <div class="meta-item"><span>DATA THROUGH {e(month_label(cov['last_month']).upper())}</span></div>
    </div>
  </header>

  <main>
"""


def src_line(s: dict, what: str) -> str:
    src = s["source"]
    return (
        f'<p class="src">Source: <a href="{e(src["url"])}">Delaware Department of Safety and Homeland Security, '
        f'Public Crash Data (data.delaware.gov {e(src["dataset_id"])})</a>, {e(what)}. '
        f'Source data updated {e(nice_date(src["rows_updated"]))}; crashes through {e(nice_date(s["coverage"]["last_crash_date"]))}.</p>'
    )


def neutrality(s: dict) -> str:
    cov = s["coverage"]
    tot = s["totals"]
    partial = ""
    if cov["last_month_partial"]:
        partial = (
            f"<p>The latest month, {e(month_label(cov['last_month']))}, is partial in the dataset: it runs only "
            f"through {e(nice_date(cov['last_crash_date']))}.</p>\n    "
        )
    return f"""  <div class="neutrality">
    <p><strong>How to read this.</strong> These are counts of crash reports from the Delaware Department of Safety and Homeland Security public crash data. Each record comes from a crash report filled out by the Delaware police officer who investigated the crash. The state updates the data monthly and says it covers crashes from 2009 through about six months before each update. In the update of {e(nice_date(s['source']['rows_updated']))}, it runs through {e(nice_date(cov['last_crash_date']))}. The state says this data is not an official record of any crash; official crash reports are confidential (21 Del. C. § 313).</p>
    {partial}<p>Each crash has one of the state's four classifications:</p>
    <ul>
      <li><strong>Non-reportable:</strong> every crash on private property, such as a parking lot, plus property-damage-only crashes on a public road with damage below Delaware's reporting threshold ($2,000, or $1,500 before September 30, 2021).</li>
      <li><strong>Property damage only:</strong> a crash on a public road with no injury and damage at or above the threshold. Because the threshold changed on September 30, 2021, counts in this column and the non-reportable column before and after that date are not on the same basis.</li>
      <li><strong>Personal injury crash</strong> and <strong>fatality crash:</strong> a crash on a public road, classified by the most serious injury in it.</li>
    </ul>
    <p>This dataset counts crashes, not people. A fatality crash is a crash in which at least one person died, and one crash can involve more than one death. The dataset has no field for the number of people killed or injured, so this page shows none. The <a href="{OHS_REPORTS}">Office of Highway Safety annual reports</a> count people.</p>
    <p>Months use Delaware local time. {n(tot['no_datetime'])} records have no crash date and are left out of the month and year tables. {n(tot['unclassified'])} records have no classification; they are counted in "All reports" only. Counties differ in population and miles of road, so these counts are not rates. We rank no county or month and add no commentary. We show you the data; you decide.</p>
  </div>
"""


def kpis(s: dict) -> str:
    k = s["kpi"]
    y = k["year"]
    st = k["statewide"]
    srcu = e(s["source"]["url"])
    asof = e(nice_date(s["source"]["rows_updated"]).upper())
    srcl = f'<div class="kpi-source"><a href="{srcu}">SOURCE · DSHS PUBLIC CRASH DATA</a> · {y} · AS OF {asof}</div>'
    cards = [
        (f"Crash reports, {y}", n(st["all_reports"]), f"Every crash report in Delaware dated in {y}, all four classifications."),
        (f"Personal injury crashes, {y}", n(st["personal_injury"]), f"Crashes on a public road in {y} where the most serious injury was a personal injury."),
        (f"Fatality crashes, {y}", n(st["fatality"]), f"Crashes in {y} in which at least one person died. A count of crashes, not of deaths."),
    ]
    out = ['  <section class="kpi-grid" aria-label="Statewide figures">']
    for label, value, ctx in cards:
        out.append(f"""    <div class="kpi-card">
      <div class="kpi-label">{e(label)}</div>
      <div class="kpi-value">{value}</div>
      <div class="kpi-context">{e(ctx)}</div>
      {srcl}
    </div>""")
    out.append(f"""    <div class="kpi-card">
      <div class="kpi-label">Data runs through</div>
      <div class="kpi-value kpi-date">{e(nice_date(s['coverage']['last_crash_date']))}</div>
      <div class="kpi-context">Latest crash date in the dataset. The state publishes monthly, about six months behind.</div>
      {srcl}
    </div>""")
    out.append("  </section>")
    return "\n".join(out) + "\n"


def table(caption: str, first_col: str, rows: list[tuple[str, dict]], label: str) -> str:
    head_cells = "".join(f'<th scope="col" class="num">{e(t)}</th>' for _, t in COLS)
    body = []
    for name, r in rows:
        tds = "".join(f'<td class="num">{n(r[k])}</td>' for k, _ in COLS)
        body.append(f'          <tr><th scope="row">{e(name)}</th>{tds}</tr>')
    return f"""      <div class="tbl-wrap" tabindex="0" role="region" aria-label="{e(label)}">
      <table class="data-table">
        <caption>{e(caption)}</caption>
        <thead><tr><th scope="col">{e(first_col)}</th>{head_cells}</tr></thead>
        <tbody>
{chr(10).join(body)}
        </tbody>
      </table>
      </div>
"""


def year_label(y: int, s: dict) -> str:
    cov = s["coverage"]
    last = datetime.date.fromisoformat(cov["last_crash_date"])
    first_y, first_m = int(cov["first_month"][:4]), int(cov["first_month"][5:7])
    if y == last.year and (last.month, last.day) != (12, 31):
        return f"{y} (through {nice_date(cov['last_crash_date'])})"
    if y == first_y and first_m != 1:
        return f"{y} (from {month_label(cov['first_month'])})"
    return str(y)


def sparse_first_year_note(s: dict) -> str:
    """A factual note when the first year holds far fewer non-reportable records than the next.

    The 2009 data has almost none (they start in December 2009), so "All reports" for that
    year is not on the same footing as later years. We state the counts and say the state
    gives no reason; we do not guess one.
    """
    st = {r["year"]: r for r in s["yearly"] if r["county"] == "Statewide"}
    years = sorted(st)
    if len(years) < 2:
        return ""
    y0, y1 = years[0], years[1]
    a, b = st[y0]["non_reportable"], st[y1]["non_reportable"]
    if b == 0 or a >= 0.1 * b:
        return ""
    return (
        f" The dataset holds {n(a)} non-reportable records for {y0} and {n(b)} for {y1}, so the {y0} "
        f'"All reports" figure is not on the same footing as later years. The state\'s notes do not give a reason.'
    )


def by_year(s: dict) -> str:
    parts = [f"""  <section class="section" aria-labelledby="year-title">
    <div class="section-head">
      <h2 class="section-title" id="year-title">Crash reports by year</h2>
      <span class="section-meta">STATEWIDE AND BY COUNTY · OLDEST FIRST</span>
    </div>
    <div class="panel">
      <p class="note">Each table lists years in date order, oldest first. A year marked "through" or "from" is not complete in the dataset.{e(sparse_first_year_note(s))}</p>
"""]
    for place in ["Statewide"] + s["counties"]:
        heading = "Statewide" if place == "Statewide" else f"{place} County"
        rows = [(year_label(r["year"], s), r) for r in s["yearly"] if r["county"] == place]
        parts.append(f'      <h3 class="sub-h">{e(heading)}</h3>\n')
        parts.append(table(f"{heading}: crash reports by year and classification, in date order.", "Year", rows, f"{heading} crash reports by year"))
    parts.append("      " + src_line(s, "count of crash reports grouped by year, county and crash classification") + "\n")
    parts.append("    </div>\n  </section>\n")
    return "".join(parts)


def by_month(s: dict) -> str:
    months = sorted({r["month"] for r in s["monthly"]})
    window = months[-MONTH_WINDOW:]
    first, last = month_label(window[0]), month_label(window[-1])
    parts = [f"""  <section class="section" aria-labelledby="month-title">
    <div class="section-head">
      <h2 class="section-title" id="month-title">Crash reports by county and month</h2>
      <span class="section-meta">LATEST {len(window)} MONTHS · OLDEST FIRST</span>
    </div>
    <div class="panel">
      <p class="note">Each county table lists the latest {len(window)} months in the dataset, {e(first)} to {e(last)}, in date order with the oldest month first. Every month since {e(month_label(months[0]))} is in the <a href="/road-safety/data/crashes-summary.json">data file</a>.</p>
"""]
    for county in s["counties"]:
        rows = [(month_label(r["month"]), r) for r in s["monthly"] if r["county"] == county and r["month"] in window]
        parts.append(f'      <h3 class="sub-h">{e(county)} County</h3>\n')
        parts.append(table(f"{county} County: crash reports by month and classification, {first} to {last}, in date order.", "Month", rows, f"{county} County crash reports by month"))
    parts.append("      " + src_line(s, "count of crash reports grouped by month (Delaware local time), county and crash classification") + "\n")
    parts.append("    </div>\n  </section>\n")
    return "".join(parts)


def data_section(s: dict) -> str:
    src = s["source"]
    return f"""  <section class="section" aria-labelledby="data-title">
    <div class="section-head">
      <h2 class="section-title" id="data-title">Get the data</h2>
      <span class="section-meta">JSON · AGGREGATE COUNTS ONLY</span>
    </div>
    <div class="panel">
      <p class="note"><a href="/road-safety/data/crashes-summary.json">crashes-summary.json</a> holds every month and county count shown here, back to {e(month_label(s['coverage']['first_month']))}. It holds counts only: no crash locations and no individual records. The full record-level dataset, including crash locations and conditions, is on the state portal: <a href="{e(src['url'])}">Public Crash Data on data.delaware.gov</a>.</p>
    </div>
  </section>
"""


def foot(s: dict) -> str:
    src = s["source"]
    return f"""  </main>

  <footer class="site-footer">
    <div class="footer-build">ROAD SAFETY · {n(s['totals']['records'])} CRASH REPORTS · THROUGH {e(nice_date(s['coverage']['last_crash_date']).upper())} · SOURCE DATA UPDATED {e(nice_date(src['rows_updated']).upper())} · SOURCE: DSHS PUBLIC CRASH DATA</div>
    <div class="footer-links">
      <a href="{e(src['url'])}">Delaware Public Crash Data (primary source)</a>
      <a href="{OHS_REPORTS}">Office of Highway Safety reports</a>
      <a href="/">First State Lens home</a>
    </div>
    <div>First State Lens is a FirmSide AI Civic Analytics Lab project. Nonpartisan. Every figure is sourced to a public record. We show you the data; you decide.</div>
  </footer>

</div>

</body>
</html>
"""


def render(s: dict) -> str:
    cov = s["coverage"]
    title_block = f"""  <div class="title-block">
    <span class="title-eyebrow">Road Safety · Delaware</span>
    <h1 class="title-h1">Crashes on Delaware roads, <span class="highlight">by county and month</span></h1>
    <p class="title-sub">Every crash report in the state's public crash data from {e(month_label(cov['first_month']))} through {e(nice_date(cov['last_crash_date']))}, counted by county, month and the state's own crash classification. The counts are computed on the state's open data portal; no individual crash records are copied here.</p>
  </div>

"""
    return head(s) + title_block + neutrality(s) + "\n" + kpis(s) + "\n" + by_year(s) + "\n" + by_month(s) + "\n" + data_section(s) + "\n" + foot(s)


def main() -> int:
    s = json.loads(DATA.read_text(encoding="utf-8"))
    changed = write_if_changed(OUT, render(s))
    print(f"road-safety page: {'written' if changed else 'unchanged'} ({OUT.relative_to(ROOT)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
