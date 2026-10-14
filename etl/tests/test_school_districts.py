"""Tests for Y3 school district report card pages.

Covers:
  - etl.sources.de_educator_salary  (5tvj-rx46 distribution + rv4m-vy79 average)
  - etl.sources.de_report_card       (additive keys: lea_type, grad_rate_single_school,
                                      directory_leas_reported_within, source_updated)
  - etl.pages.school_district_pages (static per-LEA pages + /schools/ table rows)

Network is never touched: the pullers are replayed against SoQL responses recorded
from data.delaware.gov on 2026-10-14 and trimmed to a handful of LEAs
(etl/tests/fixtures/school_districts_soql.json). The fixture holds only
aggregate rows for public bodies (state, districts, charter schools): no people.
"""

from __future__ import annotations

import copy
import html.parser
import json
import re
from pathlib import Path

import pytest

from etl.pages import school_district_pages as gen
from etl.sources import de_educator_salary as sal
from etl.sources import de_report_card as rc

FIX = Path(__file__).resolve().parent / "fixtures" / "school_districts_soql.json"
DASHES = re.compile("[—–]|&mdash;|&ndash;")
VERDICT_WORDS = re.compile(
    r"\b(best|worst|ranks?|ranked|ranking|scores?|scored|above average|below average|better|worse|"
    r"high-performing|low-performing|failing)\b", re.I)


# --------------------------------------------------------------------------- replay

def _key(ds: str, params: dict) -> str:
    return ds + "?" + json.dumps(params, sort_keys=True)


@pytest.fixture
def replay(monkeypatch):
    rec = json.loads(FIX.read_text(encoding="utf-8"))
    calls = []

    def fake_soql(ds, params):
        k = _key(ds, params)
        calls.append(k)
        if k not in rec["soql"]:
            raise AssertionError(f"unrecorded query: {k}")
        return copy.deepcopy(rec["soql"][k])

    def fake_updated(ds):
        return rec["updated"][ds]

    for mod in (rc, sal):
        monkeypatch.setattr(mod, "_soql", fake_soql)
        monkeypatch.setattr(mod, "_view_updated", fake_updated)
    return calls


# --------------------------------------------------------------------------- slugs + years

@pytest.mark.parametrize("name,slug", [
    ("Indian River School District", "indian-river"),
    ("Red Clay Consolidated School District", "red-clay-consolidated"),
    ("New Castle County Vocational-Technical School District", "new-castle-county-vocational-technical"),
    ("POLYTECH School District", "polytech"),
    ("Edison (Thomas A.) Charter School", "edison-thomas-a-charter-school"),
    ("ASPIRA Delaware", "aspira-delaware"),
    ("Early College High School at Del State", "early-college-high-school-at-del-state"),
])
def test_slugify(name, slug):
    assert gen.slugify(name) == slug


def test_school_year_label():
    assert gen.school_year("2026") == "2025-26"
    assert gen.school_year("2000") == "1999-00"


# --------------------------------------------------------------------------- salary parsing

def _dist_row(total, **bins):
    r = {"districtcode": "36", "districtname": "Indian River School District", "total": str(total)}
    for k, v in bins.items():
        r[f"staffcount_salary_{k}"] = str(v)
    return r


def test_distribution_absent_bins_are_zero_only_when_sum_matches_total():
    d = sal.parse_distribution_row(_dist_row(10.0, **{"51k_58k": 4, "gt_100k": "6.0000000001"}))
    assert d["complete"] is True
    assert d["total"] == 10.0
    assert d["counts"]["51k_58k"] == 4.0
    assert d["counts"]["gt_100k"] == 6.0          # float noise rounded away
    assert d["counts"]["lt_30k"] == 0.0           # proven zero: present bins sum to total
    assert list(d["counts"]) == [k for k, _ in sal.RANGES]


def test_distribution_absent_bins_not_reported_when_sum_short():
    d = sal.parse_distribution_row(_dist_row(10.0, **{"51k_58k": 4}))
    assert d["complete"] is False
    assert d["counts"]["51k_58k"] == 4.0
    assert d["counts"]["lt_30k"] is None          # suppressed or missing, never zero


def test_pick_complete_year_skips_partial_latest():
    counts = {"2024": 43, "2025": 44, "2026": 12}
    assert sal.pick_complete_year(counts, has_state={"2024", "2025", "2026"}) == "2025"
    assert sal.pick_complete_year({"2025": 44, "2026": 44}, has_state={"2025"}) == "2025"
    assert sal.pick_complete_year({"2025": 44, "2026": 44}, has_state={"2025", "2026"}) == "2026"
    with pytest.raises(RuntimeError):
        sal.pick_complete_year({}, has_state=set())


# --------------------------------------------------------------------------- pullers (replayed)

def test_salary_pull_replay(tmp_path, replay, monkeypatch):
    monkeypatch.setattr(sal, "MIN_LEAS", 6)
    out = sal.pull(tmp_path)
    data = json.loads((tmp_path / sal.OUT_FILE).read_text())
    man = json.loads((tmp_path / sal.OUT_MANIFEST).read_text())
    assert data == out
    dist, avg = data["distribution"], data["average"]
    assert dist["dataset"] == "5tvj-rx46" and avg["dataset"] == "rv4m-vy79"
    assert dist["schoolyear"].isdigit() and avg["schoolyear"].isdigit()
    assert dist["state"]["complete"] is True
    assert "36" in dist["leas"] and "36" in avg["leas"]
    ir = avg["leas"]["36"]
    assert ir["average_total_salary"] > 30000 and ir["educators_fte"] > 100
    assert man["row_counts"]["distribution_leas"] == len(dist["leas"])
    assert man["source_updated"]["5tvj-rx46"] and man["source_updated"]["rv4m-vy79"]
    # deterministic: a second run writes identical files apart from generated_at
    first = (tmp_path / sal.OUT_FILE).read_text()
    sal.pull(tmp_path)
    second = (tmp_path / sal.OUT_FILE).read_text()
    strip = lambda s: re.sub(r'"generated_at": "[^"]+"', "", s)  # noqa: E731
    assert strip(first) == strip(second)


def test_salary_silent_zero_guard(tmp_path, monkeypatch, replay):
    real = sal._soql

    def thin(ds, params):
        rows = real(ds, params)
        return rows if "$group" in params else rows[:3]
    monkeypatch.setattr(sal, "_soql", thin)
    monkeypatch.setattr(sal, "MIN_LEAS", 6)
    with pytest.raises(RuntimeError):
        sal.pull(tmp_path / "x")
    assert not (tmp_path / "x" / sal.OUT_FILE).exists()


OLD_DISTRICT_KEYS = {"districtcode", "district", "enrollment", "ela_proficient", "math_proficient",
                     "chronic_absenteeism", "grad_rate"}
OLD_TOP_KEYS = {"generated_at", "vintages", "assessment", "state", "districts", "source"}


def test_report_card_replay_keeps_existing_keys_and_adds_new(tmp_path, replay, monkeypatch):
    monkeypatch.setattr(rc, "MIN_DISTRICTS", 6)
    s = rc.pull(tmp_path)
    assert OLD_TOP_KEYS <= set(s)
    assert set(s["vintages"]) == {"proficiency", "chronic_absenteeism", "enrollment", "graduation"}
    assert set(s["source"]["datasets"]) == {"assessment", "attendance", "graduation", "enrollment"}
    for d in s["districts"]:
        assert OLD_DISTRICT_KEYS <= set(d)
        assert d["lea_type"] in ("Regular", "Charter")
    by = {d["districtcode"]: d for d in s["districts"]}
    assert by["36"]["lea_type"] == "Regular"
    assert by["77"]["lea_type"] == "Charter"
    # Sussex Academy has no LEA-total graduation row; its one school row is carried as context.
    assert by["77"]["grad_rate"] is None
    assert by["77"]["grad_rate_single_school"]["organization"] == "Sussex Academy"
    assert 0 < by["77"]["grad_rate_single_school"]["value"] <= 100
    assert by["36"]["grad_rate_single_school"] is None          # district total exists
    # Charter School of Wilmington is its own LEA in the directory but a Red Clay school in the report card files.
    within = {x["lea"]: x for x in s["directory_leas_reported_within"]}
    assert within["Charter School of Wilmington"]["reported_within_districtcode"] == "32"
    assert set(s["source_updated"]) == {"ms6b-mt82", "crb4-kdc7", "t7e6-zcnn", "6i7v-xnmf", "p3ez-si4g"}
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert man["row_counts"]["districts"] == len(s["districts"])
    assert man["source_updated"] == s["source_updated"]


# --------------------------------------------------------------------------- generator

@pytest.fixture
def built(tmp_path, replay, monkeypatch):
    monkeypatch.setattr(rc, "MIN_DISTRICTS", 6)
    monkeypatch.setattr(sal, "MIN_LEAS", 6)
    summary = rc.pull(tmp_path / "rc")
    salary = sal.pull(tmp_path / "sal")
    return summary, salary, gen.build_pages(summary, salary)


class _Parse(html.parser.HTMLParser):
    VOID = {"meta", "link", "br", "img", "input", "hr", "col", "source", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack, self.ld = [], []
        self._in_ld = False

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)
        if tag == "script" and ("type", "application/ld+json") in attrs:
            self._in_ld = True

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        assert self.stack and self.stack[-1] == tag, f"mismatched </{tag}>; open: {self.stack[-3:]}"
        self.stack.pop()
        self._in_ld = False

    def handle_data(self, data):
        if self._in_ld and data.strip():
            self.ld.append(json.loads(data))


def test_one_page_per_lea_at_slug_path(built):
    summary, _, pages = built
    assert len(pages) == len(summary["districts"])
    for d in summary["districts"]:
        assert f"/schools/district/{gen.slugify(d['district'])}/" in pages


def test_page_contract(built):
    summary, salary, pages = built
    ir = pages["/schools/district/indian-river/"]
    p = _Parse()
    p.feed(ir)
    assert p.stack == []
    assert {x["@type"] for x in p.ld} == {"BreadcrumbList", "Dataset"}
    title = re.search(r"<title>(.*?)</title>", ir).group(1)
    assert title.startswith("Indian River School District report card 20")
    assert "test scores, graduation, attendance" in title
    desc = re.search(r'<meta name="description" content="([^"]+)"', ir).group(1)
    st = {d["districtcode"]: d for d in summary["districts"]}["36"]
    assert f"{st['ela_proficient']:.1f}%" in desc
    assert f"{st['grad_rate']:.1f}%" in desc
    assert 'class="neutrality"' in ir and "Smarter Balanced" in ir and "REPORTED" in ir
    assert 'href="/schools/"' in ir
    assert '<link rel="canonical" href="https://firststatelens.com/schools/district/indian-river/"' in ir
    # statewide figures beside the LEA's, as plain numbers
    assert f"{summary['state']['ela_proficient']:.1f}%" in ir
    # every measure links its dataset
    for ds in ("ms6b-mt82", "crb4-kdc7", "t7e6-zcnn", "6i7v-xnmf", "5tvj-rx46", "rv4m-vy79", "p3ez-si4g"):
        assert f"https://data.delaware.gov/d/{ds}" in ir
    avg = salary["average"]["leas"]["36"]["average_total_salary"]
    assert f"${avg:,.0f}" in ir


def test_neutral_copy_everywhere(built):
    _, _, pages = built
    for path, text in pages.items():
        assert not DASHES.search(text), path
        visible = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", text, flags=re.S)
        m = VERDICT_WORDS.search(visible.replace("test scores", "").replace("We rank no school", ""))
        assert not m, (path, m and m.group(0))
        assert "None" not in visible and "null" not in visible and "nan" not in visible.lower().split(), path


def test_missing_values_say_not_reported(built):
    summary, _, pages = built
    by = {d["districtcode"]: d for d in summary["districts"]}
    vt = by["39"]  # POLYTECH: high school only, no Smarter Balanced rows
    assert vt["ela_proficient"] is None
    page = pages[f"/schools/district/{gen.slugify(vt['district'])}/"]
    assert "Not reported" in page
    title = re.search(r"<title>(.*?)</title>", page).group(1)
    assert "test scores" not in title


def test_charter_graduation_context_and_type(built):
    _, _, pages = built
    sa = pages["/schools/district/sussex-academy/"]
    assert "Charter" in sa
    assert "only school with a graduation row" in sa


def test_red_clay_notes_charters_reported_within(built):
    _, _, pages = built
    assert "Charter School of Wilmington" in pages["/schools/district/red-clay-consolidated/"]
    assert "Charter School of Wilmington" not in pages["/schools/district/indian-river/"]


def test_index_rows_link_every_lea(built):
    summary, _, _ = built
    block = gen.index_rows(summary)
    assert block.startswith(gen.ROWS_START) and block.rstrip().endswith(gen.ROWS_END)
    for d in summary["districts"]:
        assert f'href="/schools/district/{gen.slugify(d["district"])}/" data-dc="{d["districtcode"]}"' in block
    assert not DASHES.search(block)


def test_replace_rows_in_real_index(built):
    summary, _, _ = built
    idx = (Path(gen.ROOT) / "schools" / "index.html").read_text(encoding="utf-8")
    out = gen.replace_between(idx, gen.ROWS_START, gen.ROWS_END, gen.index_rows(summary))
    assert out.count(gen.ROWS_START) == 1 and "/schools/district/" in out
    again = gen.replace_between(out, gen.ROWS_START, gen.ROWS_END, gen.index_rows(summary))
    assert again == out


def test_build_is_deterministic(built):
    summary, salary, pages = built
    assert gen.build_pages(copy.deepcopy(summary), copy.deepcopy(salary)) == pages


def test_slugs_unique_or_raise(built):
    summary, salary, _ = built
    s2 = copy.deepcopy(summary)
    s2["districts"].append(dict(s2["districts"][0], districtcode="99999"))
    with pytest.raises(RuntimeError):
        gen.build_pages(s2, salary)


def test_unexplained_remainder_keeps_missing_ranges_unreported():
    d = sal.parse_distribution_row(_dist_row(1.0, **{"51k_58k": 0.9}))
    assert d["complete"] is False
    assert d["counts"]["lt_30k"] is None
