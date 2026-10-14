"""Tests for the static session index generator (bill-tracker/index.html)."""

from __future__ import annotations

import copy
import json
import re
from html.parser import HTMLParser

import pytest

from etl.pages import bill_tracker_pages as bp
from etl.sources import de_legis_bills as lb
from etl.tests.conftest import FIXTURES

LISTING = json.loads((FIXTURES / "de_legis_listing_153.json").read_text(encoding="utf-8"))
ACTIONS_HB500 = json.loads((FIXTURES / "de_legis_actions_143658.json").read_text(encoding="utf-8"))
MANIFEST = {"generated_at": "2026-10-14T15:00:00Z", "session": 153}


def actions(lid):
    if lid == 143658:
        return ACTIONS_HB500["Data"]
    if lid == 143228:  # SB 304: pretend the log is empty
        return []
    return [{"LegislationActionLogId": 1, "ActionDescription": "Passed By Senate. Votes: 21 YES",
             "OccuredAtDateTime": "6/30/26"}]


@pytest.fixture()
def data():
    return lb.build(LISTING["Data"], session=153, fetch_actions=actions, min_rows=1, today="2026-10-14")


class Checker(HTMLParser):
    VOID = {"meta", "link", "br", "img", "input", "hr", "source"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass  # <meta ... /> and friends open and close in one go

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append((tag, list(self.stack[-3:])))
        else:
            self.stack.pop()


def well_formed(text):
    c = Checker()
    c.feed(text)
    return c.errors == [] and c.stack == []


def test_every_item_is_a_server_rendered_row(data):
    pages = bp.render(data, MANIFEST)
    html = pages["bill-tracker/index.html"]
    assert len(re.findall(r'<tr data-n="', html)) == data["counts"]["items"] == 5
    for b in data["bills"]:
        assert f'href="{b["url"]}"' in html


def test_default_order_is_the_legislature_numbering(data):
    html = bp.render(data, MANIFEST)["bill-tracker/index.html"]
    order = re.findall(r'<tr data-n="(\d+)"', html)
    assert order == sorted(order, key=int)


def test_page_is_well_formed_and_dash_free(data):
    for path, html in bp.render(data, MANIFEST).items():
        assert well_formed(html), path
        assert not re.search("—|–|&mdash;|&ndash;", html), path


def test_page_contract(data):
    html = bp.render(data, MANIFEST)["bill-tracker/index.html"]
    assert '<link rel="canonical" href="https://firststatelens.com/bill-tracker/" />' in html
    assert 'class="neutrality"' in html
    assert "We do not pick, rank or group bills by topic" in html
    assert 'href="/bill-tracker/sb-272/"' in html
    assert '"@type": "Dataset"' in html
    assert "/assets/fsl.css" in html
    assert "153rd General Assembly" in html
    assert "2025 to 2026" in html
    assert "October 14, 2026" in html
    assert 'href="https://legis.delaware.gov/AllLegislation"' in html


def test_absences_are_stated_in_words(data):
    html = bp.render(data, MANIFEST)["bill-tracker/index.html"]
    row = re.search(r'<tr data-n="\d+"[^>]*>(?:(?!</tr>).)*SB 304(?:(?!</tr>).)*</tr>', html, re.S).group(0)
    assert "No action listed" in row


def test_source_words_are_escaped(data):
    d = copy.deepcopy(data)
    d["bills"][0]["title"] = 'AN ACT <script>alert("x")</script> & MORE'
    html = bp.render(d, MANIFEST)["bill-tracker/index.html"]
    assert "<script>alert" not in html
    assert "AN ACT &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; MORE" in html


def test_render_is_deterministic(data):
    assert bp.render(data, MANIFEST) == bp.render(copy.deepcopy(data), MANIFEST)


def test_groups_follow_the_number():
    assert bp.group_of("HB 500") == "house-bills"
    assert bp.group_of("HS 1 for HB 457 w/ HA 1") == "house-bills"
    assert bp.group_of("HS 1 for HR 19") == "house-resolutions"
    assert bp.group_of("HCR 158") == "house-resolutions"
    assert bp.group_of("SB 304 w/ SA 1 + HA 2") == "senate-bills"
    assert bp.group_of("SS 1 for SJR 7 w/ HA 1") == "senate-resolutions"
    assert bp.group_of("SJR 22") == "senate-resolutions"
    with pytest.raises(ValueError):
        bp.group_of("XB 1")


def test_rows_carry_their_group_for_the_filter(data):
    html = bp.render(data, MANIFEST)["bill-tracker/index.html"]
    assert re.search(r'<tr data-n="\d+" data-g="house-bills"', html)
    assert re.search(r'<tr data-n="\d+" data-g="senate-resolutions"', html)


def test_split_when_the_page_would_be_too_big(data):
    pages = bp.render(data, MANIFEST, max_bytes=2000)
    index = pages["bill-tracker/index.html"]
    assert "<tr data-n=" not in index
    for g in ("house-bills", "house-resolutions", "senate-bills", "senate-resolutions"):
        assert f'href="/bill-tracker/{g}/"' in index
        page = pages[f"bill-tracker/{g}/index.html"]
        assert 'class="neutrality"' in page
        assert well_formed(page)
        for n in re.findall(r'<tr data-n="\d+" data-g="([a-z-]+)"', page):
            assert n == g
    total = sum(len(re.findall(r"<tr data-n=", p)) for p in pages.values())
    assert total == data["counts"]["items"]


def test_single_page_when_small(data):
    pages = bp.render(data, MANIFEST)
    assert list(pages) == ["bill-tracker/index.html"]
