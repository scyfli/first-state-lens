"""Tests for etl.pages.water_pages (static /water/ index + one page per system)."""

from __future__ import annotations

import html
import html.parser
import json
import re

import pytest

from etl.pages import water_pages as wp
from etl.sources import epa_sdwis_systems as src

LEAD = {
    "headline": "Lead service lines are not centrally published at the address level in Delaware.",
    "detail": "Each water utility maintains its own inventory under EPA's Lead and Copper Rule Revisions. Check your utility directly.",
    "links": [{"name": "Wilmington Water service-line map", "url": "https://www.wilmingtondewater.gov/245/Service-Line-Inventory-Map"}],
}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


@pytest.fixture
def data(fixtures_dir):
    fx = json.loads((fixtures_dir / "epa_sdwis_systems.json").read_text(encoding="utf-8"))
    d = src.build(fx["water_system"], fx["geographic_area"], fx["violation"],
                  src.parse_contaminants(fx["contaminants"], minimum=1),
                  min_systems=1, min_violations=1, min_active_cws=1, min_contaminants=1)
    d["data_as_of"] = "2026-10-14"
    return d


@pytest.fixture
def pages(data):
    return wp.build_pages(data, LEAD)


class Balance(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append((tag, list(self.stack[-3:])))
        else:
            self.stack.pop()


def text_of(page: str) -> str:
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def test_one_page_per_system_plus_index(data, pages):
    want = {"/water/"} | {f"/water/system/{s['pwsid'].lower()}/" for s in data["systems"]}
    assert set(pages) == want


def test_every_page_parses_balanced_and_has_no_dashes(pages):
    for path, page in pages.items():
        b = Balance()
        b.feed(page)
        assert not b.errors, (path, b.errors[:3])
        assert b.stack == [], (path, b.stack)
        for bad in ("—", "–", "&mdash;", "&ndash;"):
            assert bad not in page, (path, bad)


def test_system_page_title_and_facts(data, pages):
    p = pages["/water/system/de0000263/"]
    assert "<title>Holiday Pines water system (Millsboro, DE): EPA violations on record | First State Lens</title>" in p
    assert '<link rel="canonical" href="https://firststatelens.com/water/system/de0000263/" />' in p
    t = text_of(p)
    for needed in ("DE0000263", "HOLIDAY PINES", "Community water system", "Inactive", "January 17, 2020",
                   "Sussex", "Millsboro", "210", "Ground water"):
        assert needed in t, needed
    assert 'class="neutrality"' in p
    assert "https://echo.epa.gov/detailed-facility-report?fid=DE0000263" in p
    assert "https://www.epa.gov/ccr/ccr-information-consumers" in p
    assert wp.ODW_URL in p


def test_place_fallbacks(data, pages):
    p = pages["/water/system/de0000834/"]
    assert "(Sussex County, DE): EPA violations on record" in p
    s = dict(next(x for x in data["systems"] if x["pwsid"] == "DE0000834"), county=None)
    assert wp.place_label(s) == "Delaware"


def test_violation_table_rows_match_record(data, pages):
    for s in data["systems"]:
        p = pages[f"/water/system/{s['pwsid'].lower()}/"]
        rows = re.findall(r'<tr class="viol">', p)
        assert len(rows) == len(s["violations"])
        if not s["violations"]:
            assert "EPA SDWIS lists no violations for this system" in text_of(p)
        for v in s["violations"]:
            label = v["contaminant"] or f"EPA contaminant code {v['contaminant_code']}"
            assert wp.e(label) in p
    p = pages["/water/system/de0000115/"]
    assert "No date recorded" in p


def test_system_pages_never_call_water_safe_or_unsafe(pages):
    for path, page in pages.items():
        if path == "/water/":
            continue
        t = text_of(page)
        t = re.sub(r"Safe Drinking Water( Information System| Act)?", "", t)
        assert not re.search(r"\b(un)?safe\b", t, re.I), path


def test_no_ranking_language(pages):
    for path, page in pages.items():
        assert not re.search(r"\b(worst|best|most-flagged|ranked|sorted by health)\b", page, re.I), path


def test_index_groups_alphabetically_and_links_every_page(data, pages):
    idx = pages["/water/"]
    for s in data["systems"]:
        assert f'href="/water/system/{s["pwsid"].lower()}/"' in idx
    active = [s for s in data["systems"] if s["type"] == "CWS" and s["activity"] == "A"]
    groups = wp.group_active(active)
    keys = [k for k, _ in groups]
    order = [k for k in wp.COUNTY_ORDER if k in keys]
    assert keys[:len(order)] == order
    for _, members in groups:
        names = [m["name"].lower() for m in members]
        assert names == sorted(names)


def test_index_static_figures_and_lead_note(data, pages):
    idx = pages["/water/"]
    t = text_of(idx)
    tot = data["totals"]
    for k in ("systems_on_record", "community_active", "systems_with_violations", "violations_on_record",
              "health_based", "no_return_to_compliance_date"):
        assert f"{tot[k]:,}" in t, k
    assert LEAD["headline"] in t and LEAD["detail"] in t
    assert LEAD["links"][0]["url"] in idx
    assert "<title>Is My Water Safe? Delaware Drinking Water Systems and EPA Violations | First State Lens</title>" in idx
    assert '"@type": "Dataset"' in idx
    assert 'class="neutrality"' in idx


def test_deterministic(data):
    assert wp.build_pages(data, LEAD) == wp.build_pages(data, LEAD)


def test_main_writes_cleans_stale_and_fills_sitemap_markers(data, tmp_path):
    (tmp_path / "water" / "data").mkdir(parents=True)
    (tmp_path / "water" / "data" / src.OUT_DATA).write_text(src.dumps(data), encoding="utf-8")
    (tmp_path / "water" / "data" / "water-summary.json").write_text(json.dumps({"lead_note": LEAD}), encoding="utf-8")
    stale = tmp_path / "water" / "system" / "de9999999"
    stale.mkdir(parents=True)
    (stale / "index.html").write_text("old", encoding="utf-8")
    sm = tmp_path / "sitemap.xml"
    sm.write_text("<urlset>\n  <!-- WATER:START -->\n  <!-- WATER:END -->\n</urlset>\n", encoding="utf-8")
    wp.main(["--root", str(tmp_path), "--sitemap"])
    assert not stale.exists()
    assert (tmp_path / "water" / "system" / "de0000263" / "index.html").exists()
    assert (tmp_path / "water" / "index.html").exists()
    s = sm.read_text(encoding="utf-8")
    assert "<loc>https://firststatelens.com/water/system/de0000263/</loc><lastmod>2026-10-14</lastmod>" in s
    first = {p: p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.html")}
    wp.main(["--root", str(tmp_path), "--sitemap"])
    assert first == {p: p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.html")}
    assert sm.read_text(encoding="utf-8") == s


def test_main_leaves_sitemap_alone_without_markers(data, tmp_path):
    (tmp_path / "water" / "data").mkdir(parents=True)
    (tmp_path / "water" / "data" / src.OUT_DATA).write_text(src.dumps(data), encoding="utf-8")
    (tmp_path / "water" / "data" / "water-summary.json").write_text(json.dumps({"lead_note": LEAD}), encoding="utf-8")
    sm = tmp_path / "sitemap.xml"
    sm.write_text("<urlset></urlset>\n", encoding="utf-8")
    wp.main(["--root", str(tmp_path), "--sitemap"])
    assert sm.read_text(encoding="utf-8") == "<urlset></urlset>\n"
