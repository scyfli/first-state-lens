"""Tests for the Office Registry validator (etl/office_registry.py)."""

import copy
import json
from pathlib import Path

import pytest

from etl import office_registry as orx

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures" / "office_registry_min.json"
BALLOT = {"races": [{"id": "us-house", "path": "/candidates/us-house/"}], "senate_not_on_2026_ballot": []}


def load():
    return json.loads(FIX.read_text(encoding="utf-8"))


def test_fixture_is_valid():
    assert orx.validate(load(), ballot=BALLOT) == []


def test_next_election_must_equal_last_plus_term():
    reg = load()
    reg["offices"][0]["next_election"] = 2028
    errs = orx.validate(reg, ballot=BALLOT)
    assert any("next_election" in e for e in errs)


def test_sources_must_be_https():
    reg = load()
    reg["offices"][0]["term_source"] = "http://example.gov/"
    assert any("https" in e for e in orx.validate(reg, ballot=BALLOT))


def test_missing_source_or_checked_fails():
    for field in ("source", "checked"):
        reg = load()
        del reg["offices"][0][field]
        assert any(field in e for e in orx.validate(reg, ballot=BALLOT)), field


def test_holder_source_must_be_https():
    reg = load()
    reg["offices"][0]["holder"]["source"] = "/votes/"
    assert any("https" in e for e in orx.validate(reg, ballot=BALLOT))


def test_2026_seat_needs_ballot_link_that_exists():
    reg = load()
    reg["offices"][0]["ballot_2026_path"] = None
    assert any("ballot" in e for e in orx.validate(reg, ballot=BALLOT))
    reg = load()
    reg["offices"][0]["ballot_2026_path"] = "/candidates/nowhere/"
    assert any("ballot" in e for e in orx.validate(reg, ballot=BALLOT))


def test_every_2026_race_is_in_the_registry():
    ballot = copy.deepcopy(BALLOT)
    ballot["races"].append({"id": "auditor", "path": "/candidates/auditor/"})
    assert any("auditor" in e for e in orx.validate(load(), ballot=ballot))


def test_unverified_holder_needs_reason():
    reg = load()
    reg["offices"][0]["holder"] = None
    reg["offices"][0]["holder_status"] = "not_verified"
    reg["offices"][0]["holder_unverified_reason"] = None
    assert any("reason" in e for e in orx.validate(reg, ballot=BALLOT))


def test_party_is_a_known_label():
    reg = load()
    reg["offices"][0]["holder"]["party"] = "D"
    assert any("party" in e for e in orx.validate(reg, ballot=BALLOT))


def test_school_board_annual_next_year():
    reg = load()
    reg["school_boards"][0]["next_election"] = 2030
    assert any("next_election" in e for e in orx.validate(reg, ballot=BALLOT))


def test_appointed_board_has_no_election():
    reg = load()
    sb = reg["school_boards"][0]
    sb["cycle"] = "appointed"
    sb["selection"] = "appointed"
    assert any("appointed" in e for e in orx.validate(reg, ballot=BALLOT))


def test_pii_and_dashes_are_refused():
    reg = load()
    reg["offices"][0]["description"] = "Call 302-555-0100"
    assert any("PII" in e for e in orx.validate(reg, ballot=BALLOT))
    reg = load()
    reg["offices"][0]["description"] = "Federal " + chr(0x2014) + " seat"
    assert any("dash" in e for e in orx.validate(reg, ballot=BALLOT))


def test_duplicate_ids_fail():
    reg = load()
    reg["offices"].append(copy.deepcopy(reg["offices"][0]))
    assert any("duplicate" in e for e in orx.validate(reg, ballot=BALLOT))


def test_next_school_election_year():
    assert orx.next_annual_election_year("2026-10-14") == 2027
    assert orx.next_annual_election_year("2026-03-01") == 2026


def test_published_registry_is_valid():
    reg = json.loads((ROOT / "offices" / "data" / "registry.json").read_text(encoding="utf-8"))
    ballot = json.loads((ROOT / "candidates" / "data" / "ballot-2026.json").read_text(encoding="utf-8"))
    assert orx.validate(reg, ballot=ballot) == []
    levels = {o["level"] for o in reg["offices"]}
    assert levels == {"federal", "statewide", "general-assembly", "new-castle-county", "kent-county", "sussex-county"}
    assert sum(1 for o in reg["offices"] if o["level"] == "general-assembly") == 62
