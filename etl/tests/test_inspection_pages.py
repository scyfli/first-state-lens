"""Tests for the restaurant inspections page generator (etl/pages/inspection_pages.py)."""

from __future__ import annotations

import datetime
import html.parser
import json
import re
from pathlib import Path

from etl.pages import inspection_pages as p
from etl.sources import de_food_inspections as m

FIX = Path(__file__).resolve().parent / "fixtures" / "de_food_inspections_rows.json"
SOURCE_UPDATED = datetime.date(2026, 10, 9)
DASHES = re.compile(r"[\u2013\u2014]|&[mn]dash;")  # written so the repo's dash grep stays clean


def model():
    b = m.build(json.loads(FIX.read_text(encoding="utf-8")), SOURCE_UPDATED)
    manifest = m.manifest_for(b, SOURCE_UPDATED.isoformat(), "2026-10-09T07:31:10Z", "2026-10-14T00:00:00Z")
    towns = [b["towns"][k] for k in sorted(b["towns"])]
    return manifest, towns


class _Strict(html.parser.HTMLParser):
    VOID = {"meta", "link", "br", "img", "input", "hr", "source"}

    def __init__(self):
        super().__init__()
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        assert tag in self.VOID, f"self-closing <{tag} />"

    def handle_endtag(self, tag):
        assert tag not in self.VOID, f"</{tag}> on a void element"
        assert self.stack and self.stack[-1] == tag, f"unbalanced </{tag}> (open: {self.stack[-3:]})"
        self.stack.pop()


def parses(doc: str) -> None:
    s = _Strict()
    s.feed(doc)
    s.close()
    assert s.stack == [], s.stack


def test_town_page_title_pattern_and_content():
    pages, _ = p.build_all(*model())
    doc = pages["/inspections/wilmington/"]
    assert "<title>Restaurant inspections in Wilmington, DE: violations on record from the state | First State Lens</title>" in doc
    assert "3 Cs Deli" in doc and "Dueling Rabbits" in doc
    assert "Food Storage Containers Identified with Common Name of Food" in doc
    assert "No violation listed for this inspection" in doc
    assert "Street address not listed" in doc
    assert 'class="neutrality"' in doc and "How to read this." in doc
    assert "A violation is not a closure" in doc
    assert "https://data.delaware.gov/Health/Food-Establishment-Inspection-Violations/384s-wygj" in doc
    # alphabetical order of establishments
    assert doc.index("3 Cs Deli") < doc.index("Dueling Rabbits")
    # newest inspection first
    assert doc.index('datetime="2026-06-08"') < doc.index('datetime="2025-05-05"')


def test_every_page_parses_has_no_dashes_and_no_scores():
    pages, _ = p.build_all(*model())
    assert {"/inspections/", "/inspections/wilmington/", "/inspections/newark/", "/inspections/dewey-beach/"} <= set(pages)
    for path, doc in pages.items():
        parses(doc)
        assert not DASHES.search(doc), path
        low = doc.lower()
        for word in ("grade", "score", "worst", "best", "rating"):
            assert re.search(rf"\b{word}\b", low) is None or "no grades or scores" in low, (path, word)


def test_future_dated_rows_are_disclosed_on_the_index():
    pages, _ = p.build_all(*model())
    doc = pages["/inspections/"]
    assert "10 rows" in doc and "after the state" in doc


def test_index_lists_every_town_and_works_without_js():
    pages, _ = p.build_all(*model())
    doc = pages["/inspections/"]
    for slug in ("wilmington", "newark", "dewey-beach"):
        assert f'href="/inspections/{slug}/"' in doc
    assert "<noscript>" in doc
    assert 'type="application/ld+json"' in doc and '"Dataset"' in doc


def test_split_into_alphabetical_parts_when_over_budget():
    manifest, towns = model()
    wil = next(t for t in towns if t["slug"] == "wilmington")
    pages, search = p.build_all(manifest, towns, budget=1500)
    parts = sorted(k for k in pages if k.startswith("/inspections/wilmington/"))
    assert parts[0] == "/inspections/wilmington/" and len(parts) == 2
    root, other = pages["/inspections/wilmington/"], pages[parts[1]]
    assert "3 Cs Deli" in root and "3 Cs Deli" not in other
    assert "Dueling Rabbits" in other and "Dueling Rabbits" not in root
    assert parts[1] in root and "/inspections/wilmington/" in other  # parts link to each other
    titles = {re.search(r"<title>(.*?)</title>", pages[k]).group(1) for k in parts}
    assert len(titles) == 2
    # every establishment lands on exactly one page, and search points at it
    for e in wil["establishments"]:
        hits = [k for k in parts if f'id="e-{e["id"]}"' in pages[k]]
        assert len(hits) == 1
        entry = next(s for s in search if s[3].endswith(f"#e-{e['id']}"))
        assert entry[3].startswith(hits[0])


def test_search_index_shape_and_order():
    _, search = p.build_all(*model())
    assert len(search) == 4
    names = [s[0] for s in search]
    assert names == sorted(names, key=str.casefold)
    for name, address, town, href, last in search:
        assert href.startswith("/inspections/") and "#e-" in href
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", last)


def test_sitemap_block_replaced_between_markers():
    pages, _ = p.build_all(*model())
    sm = "<urlset>\n  <!-- INSPECTIONS:START -->\n  old\n  <!-- INSPECTIONS:END -->\n</urlset>\n"
    out = p.sitemap_with_block(sm, sorted(pages), "2026-10-09")
    assert "old" not in out
    assert "<loc>https://firststatelens.com/inspections/newark/</loc><lastmod>2026-10-09</lastmod>" in out
    assert p.sitemap_with_block("<urlset></urlset>", sorted(pages), "2026-10-09") is None


def test_mobile_unit_address_never_reaches_pages_or_search_even_if_present_in_records():
    manifest, towns = model()
    est = towns[0]["establishments"][0]
    est.update({"name": est["name"] + " (MOB)", "address": "400 Bushy Tail Lane", "zip": "19901", "mobile": True})
    pages, search = p.build_all(manifest, towns)
    assert not any("Bushy Tail" in html for html in pages.values())
    assert not any("Bushy Tail" in json.dumps(row) for row in search)
