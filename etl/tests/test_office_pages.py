"""Tests for the static Office Registry pages (etl/pages/office_pages.py)."""

import html.parser
import json
from pathlib import Path

from etl import office_registry as orx
from etl.pages import office_pages as op

ROOT = Path(__file__).resolve().parents[2]


def reg():
    return json.loads((ROOT / "offices" / "data" / "registry.json").read_text(encoding="utf-8"))


class _Check(html.parser.HTMLParser):
    VOID = {"meta", "link", "br", "img", "input", "hr"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass  # self-closing tags (<meta ... />) open nothing

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unbalanced </{tag}> (open: {self.stack[-3:]})")
        else:
            self.stack.pop()


def test_builds_index_and_seven_level_pages():
    pages = op.build_all(reg())
    assert sorted(pages) == sorted([
        "offices/index.html", "offices/federal/index.html", "offices/statewide/index.html",
        "offices/general-assembly/index.html", "offices/new-castle-county/index.html",
        "offices/kent-county/index.html", "offices/sussex-county/index.html", "offices/school-boards/index.html"])


def test_pages_are_well_formed_and_static():
    for rel, text in op.build_all(reg()).items():
        c = _Check()
        c.feed(text)
        assert c.errors == [] and c.stack == [], (rel, c.errors[:3], c.stack)
        assert "<script src" not in text, rel  # works without JavaScript
        assert not orx.DASHES.search(text), rel
        assert 'class="neutrality"' in text, rel
        assert text.count("<h1") == 1, rel


def test_every_verified_holder_and_2026_link_is_rendered():
    r = reg()
    pages = op.build_all(r)
    for o in r["offices"]:
        page = pages[o["level"] + "/index.html" if False else f"offices/{o['level']}/index.html"]
        if o["holder"]:
            assert op.e(o["holder"]["name"]) in page, o["id"]
            assert op.e(o["holder"]["source"]) in page, o["id"]
        else:
            assert "Not verified" in page, o["id"]
        if o["ballot_2026_path"]:
            assert op.e(o["ballot_2026_path"]) in page, o["id"]


def test_deterministic():
    assert op.build_all(reg()) == op.build_all(reg())
