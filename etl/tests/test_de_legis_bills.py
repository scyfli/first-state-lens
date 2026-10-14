"""Tests for the full-session bill puller (legis.delaware.gov All Legislation feed).

Fixtures are trimmed copies of the legislature's own JSON responses, saved 2026-10-14:
- de_legis_listing_153.json: six rows of /json/AllLegislation/GetAllLegislation for the
  153rd General Assembly (a bill, a substitute, a bill in committee, a concurrent
  resolution, a joint resolution and one amendment).
- de_legis_actions_143658.json: the action log for HB 500.
Names in them are legislators (public officials). No private person appears.
"""

from __future__ import annotations

import copy
import json

import pytest

from etl.sources import de_legis_bills as lb
from etl.tests.conftest import FIXTURES

LISTING = json.loads((FIXTURES / "de_legis_listing_153.json").read_text(encoding="utf-8"))
ACTIONS_HB500 = json.loads((FIXTURES / "de_legis_actions_143658.json").read_text(encoding="utf-8"))


def fake_actions(calls):
    """An action-log fetcher that records which bills it was asked for."""

    def fetch(legislation_id):
        calls.append(legislation_id)
        if legislation_id == 143658:
            return ACTIONS_HB500["Data"]
        return [{"LegislationActionLogId": 1, "LegislationId": legislation_id,
                 "ActionDescription": "Introduced and Assigned to Judiciary Committee in Senate",
                 "OccuredAtDateTime": "5/6/26"}]

    return fetch


def build(rows=None, prior=None, full=False, today="2026-10-14", min_rows=1):
    calls = []
    out = lb.build(
        LISTING["Data"] if rows is None else rows,
        session=153,
        fetch_actions=fake_actions(calls),
        prior=prior,
        full=full,
        today=today,
        min_rows=min_rows,
    )
    return out, calls


# ---- session parameterisation ---------------------------------------------------------

def test_assembly_years_roll_with_the_session_number():
    assert lb.assembly_years(153) == (2025, 2026)
    assert lb.assembly_years(154) == (2027, 2028)


def test_ordinal_names():
    assert lb.ordinal(153) == "153rd"
    assert lb.ordinal(154) == "154th"
    assert lb.ordinal(151) == "151st"
    assert lb.ordinal(152) == "152nd"
    assert lb.ordinal(111) == "111th"


# ---- date parsing ---------------------------------------------------------------------

def test_ms_date_is_read_in_delaware_time():
    assert lb.ms_date("/Date(1782419826587)/") == "2026-06-25"
    # midnight Eastern is still the same Delaware calendar day
    assert lb.ms_date("/Date(1781582400000)/") == "2026-06-16"
    assert lb.ms_date(None) is None


def test_action_date():
    assert lb.action_date("6/25/26") == "2026-06-25"
    assert lb.action_date("12/1/25") == "2025-12-01"


# ---- normalisation --------------------------------------------------------------------

def test_amendments_are_left_to_the_bill_pages():
    out, _ = build()
    numbers = [b["number"] for b in out["bills"]]
    assert "HA 1 to HB 472" not in numbers
    assert out["counts"]["amendments_not_listed"] == 1
    assert out["counts"]["items"] == 5


def test_bill_fields_are_the_source_words():
    out, _ = build()
    hb = next(b for b in out["bills"] if b["number"] == "HB 500")
    assert hb["legislation_id"] == 143658
    assert hb["type"] == "Bill"
    assert hb["chamber"] == "House"
    assert hb["primary_sponsor"] == "Heffernan"
    assert hb["introduced"] == "2026-06-25"
    assert hb["status"] == "Signed"
    assert hb["status_date"] == "2026-07-08"
    assert hb["title"].startswith("A BOND AND CAPITAL IMPROVEMENTS ACT")
    assert hb["short_title"] == "FY 2027 Bond and Capital Improvements Act"
    assert hb["last_action"] == "Line-Item Veto - See Governor's Advisory #46"
    assert hb["last_action_date"] == "2026-07-06"
    assert hb["url"] == "https://legis.delaware.gov/BillDetail?LegislationId=143658"


def test_sponsor_links_to_the_official_legislature_page_not_a_caucus_site():
    out, _ = build()
    for b in out["bills"]:
        assert b["sponsor_url"].startswith("https://legis.delaware.gov/LegislatorDetail?personId=")
        assert "dems" not in b["sponsor_url"] and "gop" not in b["sponsor_url"]


def test_types_and_chambers():
    out, _ = build()
    got = {b["number"]: (b["type"], b["chamber"]) for b in out["bills"]}
    assert got["HS 1 for HB 457"] == ("Substitute", "House")
    assert got["SB 304"] == ("Bill", "Senate")
    assert got["HCR 158"] == ("Concurrent Resolution", "House")
    assert got["SJR 22"] == ("Joint Resolution", "Senate")


def test_default_order_is_the_legislature_numbering():
    out, _ = build()
    assert [b["number"] for b in out["bills"]] == [
        "HS 1 for HB 457", "HB 500", "HCR 158", "SB 304", "SJR 22"]


def test_chamber_must_agree_with_the_prefix():
    rows = copy.deepcopy(LISTING["Data"])
    rows[0]["ChamberId"] = 1  # HB 500 claimed by the Senate
    with pytest.raises(ValueError, match="chamber"):
        build(rows=rows)


def test_rows_from_another_assembly_are_refused():
    rows = copy.deepcopy(LISTING["Data"])
    rows[1]["AssemblyNumber"] = 152
    with pytest.raises(ValueError, match="assembly"):
        build(rows=rows)


def test_output_carries_no_party_or_caucus_fields():
    out, _ = build()
    allowed = {"legislation_id", "number", "type", "chamber", "title", "short_title",
               "primary_sponsor", "sponsor_url", "introduced", "status", "status_date",
               "last_action", "last_action_date", "url", "order"}
    for b in out["bills"]:
        assert set(b) == allowed


# ---- silent-zero guard ----------------------------------------------------------------

def test_floor_refuses_a_thin_result():
    with pytest.raises(RuntimeError, match="silent-zero"):
        build(min_rows=1000)


def test_prior_count_raises_the_floor():
    out, _ = build()
    prior = copy.deepcopy(out)
    prior["bills"] = prior["bills"] * 3  # pretend we had 15 items last time
    with pytest.raises(RuntimeError, match="silent-zero"):
        build(prior=prior, min_rows=1)


def test_listing_must_match_server_total():
    with pytest.raises(RuntimeError, match="Total"):
        lb.check_listing_complete(rows=LISTING["Data"][:3], total=6)
    lb.check_listing_complete(rows=LISTING["Data"], total=6)


def test_default_floor():
    assert lb.default_floor(153, prior=None) >= 1000
    assert lb.default_floor(154, prior=None) >= 1
    assert lb.default_floor(154, prior={"bills": [{}] * 100}) == 90


# ---- action-log refresh rules ---------------------------------------------------------

def test_first_run_reads_every_action_log():
    _, calls = build()
    assert sorted(calls) == sorted(r["LegislationId"] for r in LISTING["Data"] if r["LegislationTypeId"] != 5)


def test_unchanged_quiet_bills_reuse_the_prior_last_action():
    first, _ = build()
    out, calls = build(prior=first, today="2026-10-14")
    assert calls == []
    assert out == first


def test_status_change_rereads_the_action_log():
    first, _ = build()
    rows = copy.deepcopy(LISTING["Data"])
    sb = next(r for r in rows if r["LegislationDisplayCode"] == "SB 304")
    sb["StatusName"] = "Out of Committee"
    _, calls = build(rows=rows, prior=first)
    assert calls == [sb["LegislationId"]]


def test_recent_activity_rereads_the_action_log():
    first, _ = build()
    _, calls = build(prior=first, today="2026-07-20")  # HB 500's last action was 2026-07-06
    assert 143658 in calls


def test_full_flag_rereads_everything():
    first, _ = build()
    _, calls = build(prior=first, full=True)
    assert len(calls) == 5


def test_prior_from_another_session_is_ignored():
    first, _ = build()
    other = copy.deepcopy(first)
    other["session"] = 152
    _, calls = build(prior=other)
    assert len(calls) == 5


def test_last_action_picks_latest_date_then_entry():
    acts = [
        {"LegislationActionLogId": 5, "ActionDescription": "B", "OccuredAtDateTime": "7/6/26"},
        {"LegislationActionLogId": 9, "ActionDescription": "C", "OccuredAtDateTime": "7/6/26"},
        {"LegislationActionLogId": 12, "ActionDescription": "A", "OccuredAtDateTime": "6/1/26"},
    ]
    assert lb.last_action(acts) == ("C", "2026-07-06")
    assert lb.last_action([]) == (None, None)


class _Resp:
    def __init__(self, status, content, payload=None):
        self.status_code, self.content, self._payload = status, content, payload

    def raise_for_status(self):
        pass

    def json(self):
        if self._payload is None:
            raise ValueError("Expecting value")
        return self._payload


def test_empty_action_log_body_means_no_actions(monkeypatch):
    c = lb.Client(min_interval=0)
    monkeypatch.setattr(c.s, "post", lambda *a, **k: _Resp(200, b""))
    assert lb.fetch_actions(c, 143678) == []


def test_empty_listing_body_is_an_error(monkeypatch):
    c = lb.Client(min_interval=0)
    monkeypatch.setattr(c.s, "post", lambda *a, **k: _Resp(200, b""))
    monkeypatch.setattr(lb.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="failed after"):
        lb.fetch_listing(c, 153)


# ---- writing --------------------------------------------------------------------------

def test_write_is_deterministic_and_keeps_generated_at_when_unchanged(tmp_path):
    out, _ = build()
    lb.write_outputs(out, tmp_path, now="2026-10-14T12:00:00Z", source_meta={"server_total": 6})
    data1 = (tmp_path / "bills-153.json").read_bytes()
    man1 = json.loads((tmp_path / "bills-153-manifest.json").read_text())
    lb.write_outputs(out, tmp_path, now="2026-10-21T12:00:00Z", source_meta={"server_total": 6})
    assert (tmp_path / "bills-153.json").read_bytes() == data1
    man2 = json.loads((tmp_path / "bills-153-manifest.json").read_text())
    assert man2["generated_at"] == man1["generated_at"] == "2026-10-14T12:00:00Z"
    assert man2["row_counts"]["items"] == 5
    assert man2["source"]["listing_endpoint"].startswith("https://legis.delaware.gov/")
    # never clobbers the SB 272 tracker's own manifest
    assert not (tmp_path / "manifest.json").exists()


def test_write_moves_generated_at_when_content_changes(tmp_path):
    out, _ = build()
    lb.write_outputs(out, tmp_path, now="2026-10-14T12:00:00Z", source_meta={})
    changed = copy.deepcopy(out)
    changed["bills"][0]["status"] = "Passed"
    lb.write_outputs(changed, tmp_path, now="2026-10-21T12:00:00Z", source_meta={})
    man = json.loads((tmp_path / "bills-153-manifest.json").read_text())
    assert man["generated_at"] == "2026-10-21T12:00:00Z"
