"""Generate /my-delaware/ (docs/UPGRADE-PLAN.md, Y4): one address, everything public about it.

The page is static HTML plus a JSON data block built here from records already on the site:

  offices/data/registry.json         who holds each legislative and county council seat
  candidates/data/ballot-2026.json   the 2026 race pages for each district and county
  schools/district/*/index.html      the school district report card pages (title -> path)

The browser sends the typed address to /api/districts (the E2 Worker, which stores and logs
nothing) and fills the answer in from this data block with assets/my-delaware.js. Water
systems cannot be matched to an address yet (no public service-area layer covers municipal
systems), so the page says so and links the water search instead of guessing.

Run:  python3 -m etl.pages.my_delaware_page
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

from etl.pages.candidate_pages import head, write_if_changed

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "offices" / "data" / "registry.json"
BALLOT = ROOT / "candidates" / "data" / "ballot-2026.json"
SCHOOLS = ROOT / "schools" / "district"
OUT = ROOT / "my-delaware" / "index.html"
COUNTY_SLUG = {"New Castle": "new-castle-county", "Kent": "kent-county", "Sussex": "sussex-county"}
COUNCIL_ID = {"New Castle": ("ncc-council-district-", "County Council"),
              "Kent": ("kent-levy-court-district-", "Levy Court"),
              "Sussex": ("sussex-council-district-", "County Council")}
e = html.escape


def holder(o: dict) -> dict:
    h = o.get("holder") or {}
    return {"name": h.get("name"), "party": h.get("party"), "status": o.get("holder_status")}


def build_data() -> dict:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    by_id = {o["id"]: o for o in reg["offices"]}
    ballot = json.loads(BALLOT.read_text(encoding="utf-8"))
    races = {r["id"]: r for r in ballot["races"]}
    senate, house = {}, {}
    for n in range(1, 22):
        o = by_id[f"state-senate-{n}"]
        senate[n] = {**holder(o), "path": f"/candidates/state-senate/district-{n}/", "on_ballot": f"state-senate-{n}" in races}
    for n in range(1, 42):
        o = by_id[f"state-house-{n}"]
        house[n] = {**holder(o), "path": f"/candidates/state-house/district-{n}/", "on_ballot": True}
    council = {}
    for county, (prefix, body) in COUNCIL_ID.items():
        seats = {}
        for o in reg["offices"]:
            if o["id"].startswith(prefix):
                seats[int(o["id"][len(prefix):])] = {**holder(o), "body": body}
        if not seats:
            raise RuntimeError(f"registry has no {county} council seats")
        council[county] = seats
    schools = {}
    for f in sorted(SCHOOLS.glob("*/index.html")):
        m = re.search(r"<title>(.*?) report card", f.read_text(encoding="utf-8"))
        if m:
            schools[html.unescape(m.group(1))] = f"/schools/district/{f.parent.name}/"
    if len(schools) < 16:
        raise RuntimeError("fewer than 16 school district pages found")
    statewide = [[r["display"], r["path"]] for rid in ("us-senate", "us-house", "attorney-general", "state-treasurer", "auditor")
                 for r in [races[rid]]]
    counties = {c: {"offices": f"/offices/{s}/", "ballot": f"/candidates/{s}/"} for c, s in COUNTY_SLUG.items()}
    return {"checked": reg.get("checked"), "senate": senate, "house": house, "council": council,
            "schools": schools, "statewide": statewide, "counties": counties}


STYLE_EXTRA = """<style>
  :root { --accent-primary: var(--violet-400); }
  .crumbs { font-size: 13px; color: var(--text-tertiary); margin-bottom: 18px; }
  .crumbs a { color: var(--text-secondary); }
  .bl-form { max-width: 760px; background: var(--surface-elevated); border: 1px solid var(--border-default); border-left: 3px solid var(--violet-400); border-radius: 14px; padding: 18px 20px; }
  .bl-form label { display: block; font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; }
  .bl-row { display: flex; gap: 10px; flex-wrap: wrap; }
  .bl-row input { flex: 1 1 280px; min-width: 0; font: inherit; font-size: 15px; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border-strong); background: rgba(3,7,18,0.6); color: var(--text-primary); }
  .bl-row button { font: inherit; font-weight: 600; font-size: 14px; padding: 10px 16px; border-radius: 8px; border: 1px solid var(--violet-400); background: rgba(167,139,250,0.15); color: var(--text-primary); cursor: pointer; min-height: 44px; }
  .bl-row button:disabled { opacity: .6; cursor: progress; }
  .bl-privacy { font-size: 12px; color: var(--text-tertiary); margin-top: 10px; }
  .bl-status { font-size: 14px; color: var(--text-secondary); margin: 10px 0 0; min-height: 1.4em; max-width: 760px; }
  .md-result { max-width: 760px; margin-top: 16px; }
  .md-result h3 { font-family: 'Space Grotesk', sans-serif; font-size: 17px; color: var(--text-primary); margin: 22px 0 8px; }
  .md-result h3:first-child { margin-top: 6px; }
  .md-result h3:focus { outline: 2px solid var(--violet-400); outline-offset: 4px; }
  .md-msg { font-size: 14px; color: var(--text-secondary); line-height: 1.6; margin: 8px 0; }
  .md-msg strong { color: var(--text-primary); }
  .md-msg a, .md-list a { color: var(--text-primary); font-weight: 600; }
  .md-list { list-style: none; margin: 8px 0; padding: 0; display: grid; gap: 8px; }
  .md-list li { background: var(--surface-elevated); border: 1px solid var(--border-default); border-radius: 10px; padding: 10px 14px; font-size: 14px; color: var(--text-secondary); line-height: 1.5; }
  .md-warn { color: var(--amber-400); }
  .md-what { font-size: 14px; color: var(--text-secondary); line-height: 1.7; max-width: 860px; }
  .md-what a { color: var(--text-primary); }
</style>"""


def page(data: dict) -> str:
    title = "My Delaware: your legislators, school district, county and ballot by address"
    desc = ("Type a Delaware street address to see your State Senator and Representative, your county council or "
            "levy court member, your school district report card and every race on your 2026 ballot, from public records.")
    crumbs = [("Home", "/"), ("My Delaware", "/my-delaware/")]
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c")
    h = head(title, desc, "/my-delaware/", crumbs)
    h = h.replace("</head>", STYLE_EXTRA + "\n</head>", 1)
    return h + f"""  <div class="title-block">
    <span class="title-eyebrow">My Delaware · By address</span>
    <h1 class="title-h1">Your <span class="highlight">Delaware</span>, by address</h1>
    <p class="title-sub">{e(desc)}</p>
  </div>

  <p class="neutrality"><strong>How to read this.</strong> One address, the public record that goes with it. Districts come from the U.S. Census Bureau's geocoder; officeholders from the official pages listed in the <a href="/offices/">Delaware Office Registry</a> (checked {e(data.get("checked") or "")}); school figures from the Department of Education. We rank no one and recommend nothing. Confirm your districts and polling place at <a href="https://ivote.de.gov">ivote.de.gov</a>.</p>

  <section class="section" aria-labelledby="md-title">
    <div class="section-head"><h2 class="section-title" id="md-title">Look up an address</h2></div>
    <form id="md-form" class="bl-form" method="post" action="/api/districts" autocomplete="on">
      <label for="md-address">Your street address in Delaware</label>
      <div class="bl-row">
        <input id="md-address" name="address" type="text" autocomplete="street-address" required maxlength="200" aria-describedby="md-privacy" placeholder="411 Legislative Ave, Dover" />
        <button type="submit" disabled>Show my Delaware</button>
      </div>
      <p class="bl-privacy" id="md-privacy">Your address is sent to the U.S. Census Bureau's public geocoder to find your districts; the Census Bureau keeps its own server records. First State Lens does not store or log it. A ZIP code alone shows the districts it overlaps.</p>
      <noscript><p class="bl-privacy">This lookup needs JavaScript. You can find your districts at <a href="https://ivote.de.gov">ivote.de.gov</a>, then use the <a href="/offices/">Office Registry</a> and the <a href="/schools/">school report cards</a>.</p></noscript>
    </form>
    <p id="md-status" class="bl-status" role="status" aria-live="polite"></p>
    <div id="md-result" class="md-result" hidden></div>
  </section>

  <section class="section" aria-labelledby="md-what">
    <div class="section-head"><h2 class="section-title" id="md-what">What the lookup shows</h2></div>
    <ul class="md-what">
      <li>Your <a href="/offices/general-assembly/">State Senator and State Representative</a>, and their <a href="/votes/">recorded votes</a>.</li>
      <li>Your county council or levy court district and who holds it (<a href="/offices/new-castle-county/">New Castle</a>, <a href="/offices/kent-county/">Kent</a>, <a href="/offices/sussex-county/">Sussex</a>).</li>
      <li>Your public school district and its <a href="/schools/">report card</a>.</li>
      <li>Every race on your <a href="/candidates/">2026 ballot</a>.</li>
      <li>Drinking water: we cannot match an address to a water system yet, because no public service-area map covers every system. Find yours by name or town on <a href="/water/">Is my water safe?</a></li>
      <li>Child care: see <a href="/childcare/">licensed child care by county</a>.</li>
    </ul>
  </section>

<script type="application/json" id="md-data">{blob}</script>
<script src="/assets/my-delaware.js" defer></script>
  </main>

  <footer class="site-footer">
    <div class="footer-build">MY DELAWARE · DISTRICTS: U.S. CENSUS GEOCODER · HOLDERS: DELAWARE OFFICE REGISTRY · NO ADDRESS IS STORED</div>
    <div class="footer-links">
      <a href="/offices/">Delaware Office Registry</a>
      <a href="/candidates/">Who's on the Delaware ballot</a>
      <a href="/">First State Lens home</a>
    </div>
    <div class="footer-firm">First State Lens is a FirmSide AI Civic Analytics Lab project. Nonpartisan. Every figure is sourced to a public record. We show you the data; you decide.</div>
  </footer>
</div>
</body>
</html>
"""


def main() -> int:
    changed = write_if_changed(OUT, page(build_data()))
    print(f"my-delaware: {'written' if changed else 'unchanged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
