"""Tests for etl/sources/de_results.py (E3: last general election result per seat)."""

from pathlib import Path

import pytest

from etl.sources import de_results as R

FIX = Path(__file__).parent / "fixtures" / "de_results_GE2024_excerpt.html"


def parse(min_contests=1):
    R.MIN_CONTESTS[9999] = min_contests
    return R.parse_report(FIX.read_text(encoding="utf-8"), 9999)


def test_parses_statewide_totals_by_column_position():
    c = parse()
    hd39 = c["state representative district 39"]
    # this table's rows carry no data-label attributes: cells are read by header position
    assert hd39["candidates"] == [{"name": "DANIEL B. SHORT", "party": "Republican Party", "votes": 7440, "percent": 100.0}]
    house = c["representative in congress"]
    assert [x["name"] for x in house["candidates"]] == ["SARAH MCBRIDE", "JOHN J. WHALEN III"]
    assert house["total_votes"] == 287830 + 209606


def test_first_occurrence_wins_and_nested_titles_are_skipped():
    c = parse()
    assert c["state representative district 39"]["total_votes"] == 7440  # not the later-tab repeat
    assert not any("<h4" in k or "representative district 39 representative" in k for k in c)


def test_state_order_is_kept_not_sorted_by_votes():
    c = parse()
    rows = [(x["name"], x["votes"]) for x in c["state representative district 41"]["candidates"]]
    # the state lists the lower total first here; we must not reorder by votes
    assert rows == [("TOM BRETT", 5242), ("RICH COLLINS", 9490)]


def test_silent_zero_guard():
    with pytest.raises(RuntimeError, match="refusing to write"):
        parse(min_contests=50)


def test_bad_vote_cell_raises():
    with pytest.raises(ValueError):
        R._num("12a")
    assert R._pct("56.63 %") == 56.63 and R._pct("55.47") == 55.47


def test_mapping_rules():
    assert R.target_for({"id": "us-senate", "level": "federal"}) == (2020, "U.S. Senator")
    assert R.target_for({"id": "state-senate-5", "level": "state-senate", "district": 5}) == (2022, "State Senator District 5")
    assert R.target_for({"id": "state-senate-2", "level": "state-senate", "district": 2, "on_2026_ballot": False}) == (2024, "State Senator District 2")
    assert R.target_for({"id": "state-house-7", "level": "state-house", "district": 7}) == (2024, "State Representative District 7")
    assert R.target_for({"id": "x", "level": "county", "county": "Kent", "display": "Kent County Levy Court District 2"}) == (2022, "KC Levy Court District 2")
    assert R.target_for({"id": "x", "level": "county", "county": "New Castle", "display": "New Castle County Council District 3"}) == (2022, "NCC County Council District 3")
    assert R.target_for({"id": "x", "level": "county", "county": "Sussex", "display": "Sussex County Sheriff"}) == (2022, "SC Sheriff")


def test_build_refuses_unmatched_seat():
    reports = {2020: {}, 2022: {}, 2024: {}}
    with pytest.raises(RuntimeError, match="no GE2020 contest"):
        R.build({"races": [{"id": "us-senate", "level": "federal"}], "senate_not_on_2026_ballot": []}, reports)


def test_canonical_titles_match_across_years():
    assert R.canon("NCC County Council District 1") == R.canon("New Castle County Council District 1")
    assert R.canon("SC County Council District 4") == R.canon("Sussex County Council District 4")
    assert R.canon("KC Levy Court At-Large") == R.canon("Kent County Levy Court At-Large")
    assert R.canon("Levy Court District 1") == R.canon("Kent County Levy Court District 1")
    assert R.canon("U.S. Representative In Congress") == R.canon("Representative in Congress")
    assert R.canon("NCC Sheriff") == "new castle county sheriff"


def test_certified_refuses_partial_results():
    report = parse()
    ballot = {"races": [{"id": "us-house", "level": "federal"}, {"id": "state-house-39", "level": "state-house", "district": 39}]}
    got = R.certified(ballot, report, 9999)
    assert got["state-house-39"]["candidates"][0]["votes"] == 7440 and got["us-house"]["year"] == 9999
    ballot["races"].append({"id": "state-house-1", "level": "state-house", "district": 1})
    with pytest.raises(RuntimeError, match="partial"):
        R.certified(ballot, report, 9999)


def test_certified_refuses_unofficial_report(tmp_path):
    f = tmp_path / "GE2026.html"
    f.write_text(FIX.read_text(encoding="utf-8").replace("<body>", "<body>UNOFFICIAL RESULTS"), encoding="utf-8")
    with pytest.raises(RuntimeError, match="not marked OFFICIAL"):
        R.main_certified(2026, tmp_path, {"races": []}, str(f))
