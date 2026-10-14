"""Tests for the restaurant inspections puller (etl/sources/de_food_inspections.py).

Fixture: etl/tests/fixtures/de_food_inspections_rows.json, real rows from data.delaware.gov
dataset 384s-wygj (business names and business addresses only; the source carries no
inspector or contact-person fields).
"""

from __future__ import annotations

import datetime
import json
import random
from pathlib import Path

import pytest

from etl.sources import de_food_inspections as m

FIX = Path(__file__).resolve().parent / "fixtures" / "de_food_inspections_rows.json"
SOURCE_UPDATED = datetime.date(2026, 10, 9)


def rows() -> list[dict]:
    return json.loads(FIX.read_text(encoding="utf-8"))


def built() -> dict:
    return m.build(rows(), SOURCE_UPDATED)


def all_establishments(b: dict) -> list[dict]:
    return [e for t in b["towns"].values() for e in t["establishments"]]


def test_groups_into_towns_with_normalised_names_and_slugs():
    b = built()
    # Future-dated rows (Camden, Wyoming) are excluded, so only three towns remain.
    assert sorted(b["towns"]) == ["dewey-beach", "newark", "wilmington"]
    assert b["towns"]["dewey-beach"]["town"] == "Dewey Beach"  # double space in the source collapsed
    names = [e["name"] for e in b["towns"]["wilmington"]["establishments"]]
    assert names == ["3 Cs Deli", "Dueling Rabbits"]  # alphabetical


def test_inspections_newest_first_with_state_wording_and_no_violation_inspections_kept():
    deli = next(e for e in all_establishments(built()) if e["name"] == "3 Cs Deli")
    dates = [i["date"] for i in deli["inspections"]]
    assert dates == sorted(dates, reverse=True)
    assert dates == ["2026-06-08", "2025-05-22", "2025-05-13", "2025-05-05"]
    follow = next(i for i in deli["inspections"] if i["date"] == "2025-05-22")
    assert follow["type"] == "Follow-up"
    assert follow["violations"] == []  # the state lists this inspection with no violation
    routine = next(i for i in deli["inspections"] if i["date"] == "2025-05-05")
    codes = [v["code"] for v in routine["violations"]]
    assert codes == sorted(codes) and len(codes) == 8
    v = next(v for v in routine["violations"] if v["code"] == "3-302.12")
    assert v["description"] == "Food Storage Containers Identified with Common Name of Food"


def test_future_dated_rows_are_excluded_and_counted():
    s = built()["stats"]
    assert s["rows_after_source_update"] == 10
    assert s["dates_after_source_update"] == ["2026-11-18", "2026-12-03"]
    assert s["date_max"] <= SOURCE_UPDATED.isoformat()


def test_rows_older_than_the_window_are_excluded():
    r = rows()
    old = dict(r[0])
    old["insp_date"] = "2022-01-04T00:00:00.000"
    b = m.build(r + [old], SOURCE_UPDATED)
    assert b["stats"]["rows_before_window"] == 1
    assert b["stats"]["date_min"] >= "2023-10-09"


def test_only_whitelisted_fields_are_written():
    for e in all_establishments(built()):
        assert set(e) == {"id", "name", "address", "city", "zip", "inspections"}
        for i in e["inspections"]:
            assert set(i) == {"date", "type", "violations"}
            for v in i["violations"]:
                assert set(v) == {"code", "description"}
    text = json.dumps(built())
    assert "geocoded" not in text and "human_address" not in text


def test_missing_address_is_none_not_blank():
    rabbits = next(e for e in all_establishments(built()) if e["name"] == "Dueling Rabbits")
    assert rabbits["address"] is None


def test_output_is_deterministic_regardless_of_input_order():
    a = json.dumps(m.build(rows(), SOURCE_UPDATED), sort_keys=True)
    shuffled = rows()
    random.Random(7).shuffle(shuffled)
    b = json.dumps(m.build(shuffled, SOURCE_UPDATED), sort_keys=True)
    assert a == b


def test_establishment_ids_are_stable_and_unique():
    ids = [e["id"] for e in all_establishments(built())]
    assert len(ids) == len(set(ids))
    assert ids == [e["id"] for e in all_establishments(built())]


def test_silent_zero_guard_raises_on_thin_results():
    with pytest.raises(RuntimeError):
        m.check_plausible(built()["stats"])  # a 4-establishment fixture is implausible statewide
    m.check_plausible(built()["stats"], min_rows=10, min_establishments=3, min_towns=3)


def _fake_meta(session):
    return {"source_updated": SOURCE_UPDATED.isoformat(), "rows_updated_at": "2026-10-09T07:31:10Z"}


def test_pull_writes_nothing_when_the_guard_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "fetch_meta", _fake_meta)
    monkeypatch.setattr(m, "fetch_rows", lambda session: rows())
    out = tmp_path / "data"
    with pytest.raises(RuntimeError):
        m.pull(out)
    assert not out.exists() or not any(out.rglob("*"))


def test_pull_writes_towns_and_manifest_when_plausible(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "fetch_meta", _fake_meta)
    monkeypatch.setattr(m, "fetch_rows", lambda session: rows())
    monkeypatch.setattr(m, "MIN_ROWS", 10)
    monkeypatch.setattr(m, "MIN_ESTABLISHMENTS", 3)
    monkeypatch.setattr(m, "MIN_TOWNS", 3)
    out = tmp_path / "data"
    (out / "towns").mkdir(parents=True)
    (out / "towns" / "gone-town.json").write_text("{}", encoding="utf-8")  # stale town file
    m.pull(out)
    files = sorted(p.name for p in (out / "towns").iterdir())
    assert files == ["dewey-beach.json", "newark.json", "wilmington.json"]
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for k in ("generated_at", "source", "source_updated", "row_counts", "window"):
        assert k in man
    assert man["row_counts"]["establishments"] == 4
    assert man["row_counts"]["rows_after_source_update"] == 10
    town = json.loads((out / "towns" / "newark.json").read_text(encoding="utf-8"))
    assert town["town"] == "Newark" and town["establishments"][0]["name"] == "Klondike Kates"


def test_rows_missing_name_city_or_date_are_dropped_and_counted():
    r = rows()
    bad = dict(r[0])
    bad["restname"] = "  "
    b = m.build(r + [bad], SOURCE_UPDATED)
    assert b["stats"]["rows_incomplete"] == 1
