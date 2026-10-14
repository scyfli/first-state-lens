"""Tests for etl.sources.de_crashes (Y8 road safety puller) and etl.pages.road_safety_page.

Fixtures are trimmed, real SoQL aggregate responses from data.delaware.gov 827n-m6xc
(grouped counts only: month, county, crash classification, count). No row-level data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from etl.pages import road_safety_page
from etl.sources import de_crashes
from etl.tests.html_balance import check_balanced

FX = Path(__file__).resolve().parent / "fixtures"
LAST = "2026-03-31T22:25:00.000"
SMALL = {"min_records": 1, "min_months": 1}


@pytest.fixture
def grouped() -> list[dict]:
    return json.loads((FX / "de_crashes_grouped.json").read_text(encoding="utf-8"))


@pytest.fixture
def meta() -> dict:
    return json.loads((FX / "de_crashes_meta.json").read_text(encoding="utf-8"))


def _total(rows):
    return sum(int(r["n"]) for r in rows)


def _summary(meta, grouped, **kw):
    args = {"total_records": _total(grouped) + 3, "no_datetime": 3, "last_crash_local": LAST, **SMALL}
    args.update(kw)
    return de_crashes.build_summary(meta, grouped, **args)


def test_monthly_rows_are_chronological_with_identical_fields(meta, grouped):
    s = _summary(meta, grouped)
    months = [r["month"] for r in s["monthly"]]
    assert months == sorted(months)
    assert len(s["monthly"]) == 5 * 3  # 5 months x 3 counties in the fixture
    keys = {tuple(sorted(r)) for r in s["monthly"]}
    assert keys == {("all_reports", "county", "fatality", "month", "non_reportable", "personal_injury", "property_damage_only")}
    assert [r["county"] for r in s["monthly"][:3]] == ["Kent", "New Castle", "Sussex"]


def test_all_reports_includes_unclassified(meta, grouped):
    s = _summary(meta, grouped)
    for r in s["monthly"]:
        parts = r["non_reportable"] + r["property_damage_only"] + r["personal_injury"] + r["fatality"]
        assert r["all_reports"] >= parts
    na = sum(int(r["n"]) for r in grouped if r["crash_class_desc"] == "NA")
    assert na > 0
    assert s["totals"]["unclassified"] == na
    assert sum(r["all_reports"] for r in s["monthly"]) == _total(grouped)


def test_yearly_and_statewide_rollups(meta, grouped):
    s = _summary(meta, grouped)
    jan25 = [r for r in s["monthly"] if r["month"] == "2025-01"]
    y25 = [r for r in s["yearly"] if r["year"] == 2025]
    assert {r["county"] for r in y25} == {"Kent", "New Castle", "Sussex", "Statewide"}
    st = next(r for r in y25 if r["county"] == "Statewide")
    assert st["fatality"] == sum(r["fatality"] for r in jan25)
    assert s["kpi"]["year"] == 2025
    assert s["kpi"]["statewide"]["all_reports"] == st["all_reports"]


def test_coverage_and_source_stamps(meta, grouped):
    s = _summary(meta, grouped)
    cov = s["coverage"]
    assert cov["first_month"] == "2018-11"
    assert cov["last_month"] == "2026-03"
    assert cov["last_crash_date"] == "2026-03-31"
    assert cov["last_month_partial"] is False
    assert s["source"]["rows_updated"] == "2026-10-05"
    assert s["source"]["dataset_id"] == "827n-m6xc"
    assert s["source"]["url"].startswith("https://data.delaware.gov/")


def test_partial_last_month_is_flagged(meta, grouped):
    s = _summary(meta, grouped, last_crash_local="2026-03-15T10:00:00.000")
    assert s["coverage"]["last_month_partial"] is True
    assert s["kpi"]["year"] == 2025


def test_kpi_year_is_last_full_calendar_year(meta, grouped):
    upto = [r for r in grouped if r["month"] < "2025"]
    s = _summary(meta, upto, total_records=_total(upto) + 3, last_crash_local="2024-12-31T23:10:00.000")
    assert s["kpi"]["year"] == 2024
    assert s["coverage"]["last_month_partial"] is False


def test_latest_crash_must_sit_in_latest_month(meta, grouped):
    with pytest.raises(RuntimeError, match="latest"):
        _summary(meta, grouped, last_crash_local="2026-04-02T01:00:00.000")


def test_reconciliation_guard(meta, grouped):
    with pytest.raises(RuntimeError, match="reconcil"):
        _summary(meta, grouped, total_records=_total(grouped) + 99)


def test_silent_zero_guard_with_real_floors(meta, grouped):
    with pytest.raises(RuntimeError, match="silent-zero"):
        de_crashes.build_summary(meta, grouped, total_records=_total(grouped) + 3, no_datetime=3, last_crash_local=LAST)


def test_unknown_or_missing_county_raises(meta, grouped):
    odd = [dict(r) for r in grouped]
    odd[0]["county_desc"] = "Elsewhere"
    with pytest.raises(RuntimeError, match="county"):
        _summary(meta, odd)
    no_kent = [r for r in grouped if r["county_desc"] != "Kent"]
    with pytest.raises(RuntimeError, match="county"):
        _summary(meta, no_kent, total_records=_total(no_kent) + 3)


def test_unknown_class_raises(meta, grouped):
    odd = [dict(r) for r in grouped]
    odd[0]["crash_class_desc"] = "Something New"
    with pytest.raises(RuntimeError, match="class"):
        _summary(meta, odd)


def test_summary_is_deterministic_and_has_no_location_fields(meta, grouped):
    a = json.dumps(_summary(meta, grouped), sort_keys=True)
    b = json.dumps(_summary(meta, list(reversed(grouped))), sort_keys=True)
    assert a == b
    assert "generated_at" not in a
    for bad in ("latitude", "longitude", "the_geom"):
        assert bad not in a


def test_write_outputs(tmp_path, meta, grouped):
    s = _summary(meta, grouped)
    de_crashes.write_outputs(tmp_path, s, generated_at="2026-10-14T00:00:00Z")
    data = json.loads((tmp_path / "crashes-summary.json").read_text(encoding="utf-8"))
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert data == json.loads(json.dumps(s))
    assert man["generated_at"] == "2026-10-14T00:00:00Z"
    assert man["source"]["rows_updated"] == "2026-10-05"
    assert man["row_counts"]["monthly_rows"] == 15


# ---------------------------------------------------------------------------
# Page generator
# ---------------------------------------------------------------------------


def test_page_renders_static_tables(meta, grouped):
    page = road_safety_page.render(_summary(meta, grouped))
    check_balanced(page)
    assert "<h1" in page and 'class="neutrality"' in page
    for county in ("Kent County", "New Castle County", "Sussex County"):
        assert county in page
    months = page[page.index('id="month-title"'):]
    row = lambda m: months.index(f'<th scope="row">{m}</th>')  # noqa: E731
    assert row("November 2018") < row("January 2025") < row("February 2026") < row("March 2026")
    years = page[page.index('id="year-title"'):page.index('id="month-title"')]
    assert '<th scope="row">2018 (from November 2018)</th>' in years
    assert '<th scope="row">2026 (through March 31, 2026)</th>' in years
    assert "827n-m6xc" in page
    assert "October 5, 2026" in page  # source rows-updated stamp
    assert "March 31, 2026" in page  # data coverage end
    assert "counts crashes, not people" in page
    assert 'rel="canonical" href="https://firststatelens.com/road-safety/"' in page
    assert '"@type": "Dataset"' in page


def test_page_copy_rules(meta, grouped):
    page = road_safety_page.render(_summary(meta, grouped))
    for bad in ("\u2014", "\u2013", "&" + "mdash;", "&" + "ndash;"):
        assert bad not in page
    low = page.lower()
    for word in ("worst", "best", "safest", "most dangerous", "deadliest", "better", "worse"):
        assert word not in low, word


def test_sparse_first_year_note_states_counts_only():
    yr = lambda y, nr: {"year": y, "county": "Statewide", "non_reportable": nr}  # noqa: E731
    note = road_safety_page.sparse_first_year_note({"yearly": [yr(2009, 196), yr(2010, 12291)]})
    assert "196 non-reportable records for 2009" in note and "12,291 for 2010" in note
    assert road_safety_page.sparse_first_year_note({"yearly": [yr(2009, 9000), yr(2010, 12291)]}) == ""


def test_page_is_deterministic(meta, grouped):
    s = _summary(meta, grouped)
    assert road_safety_page.render(s) == road_safety_page.render(s)
