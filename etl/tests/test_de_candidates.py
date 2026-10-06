"""Tests for the 2026 ballot puller against a scrubbed copy of the state list.

The fixture is the Department of Elections page from 2026-10-05 with every candidate's
contact block replaced by an obviously fake one (100 Example Street, (555) 555-0100), so
the tests prove the puller drops contact data without this repo ever holding real
addresses or phone numbers.
"""

from __future__ import annotations

import json

import pytest

from etl.sources import de_candidates as dc
from etl.tests.conftest import FIXTURES

FIXTURE = FIXTURES / "de_candidates_2026-10-05.html"


@pytest.fixture(scope="module")
def parsed():
    rows, stamp = dc.parse(FIXTURE.read_text(encoding="utf-8"))
    return rows, stamp


@pytest.fixture(scope="module")
def ballot(parsed):
    rows, stamp = parsed
    roster = {("House", 17): {"name": "Melissa Minor-Brown", "party": "Democratic"},
              ("Senate", 2): {"name": "Example Senator", "party": "Democratic"}}
    b = dc.build(rows, stamp, roster)
    dc.validate(b)
    return b


def test_counts_match_source(parsed, ballot):
    rows, stamp = parsed
    assert len(rows) == 128
    assert ballot["counts"] == {"rows": 128, "qualified": 124, "withdrawn": 4, "races": 77}
    assert stamp == "2026-10-05 07:56 PM"


def test_every_house_district_and_statewide_race_present(ballot):
    ids = {r["id"] for r in ballot["races"]}
    assert {f"state-house-{n}" for n in range(1, 42)} <= ids
    assert {"us-senate", "us-house", "attorney-general", "state-treasurer", "auditor"} <= ids
    senate = sorted(r["district"] for r in ballot["races"] if r["level"] == "state-senate")
    assert senate == [1, 5, 7, 8, 9, 12, 13, 14, 15, 19, 20]


def test_off_ballot_senate_districts_complete_the_chamber(ballot):
    on = {r["district"] for r in ballot["races"] if r["level"] == "state-senate"}
    off = {r["district"] for r in ballot["senate_not_on_2026_ballot"]}
    assert on.isdisjoint(off) and on | off == set(range(1, 22))
    sd2 = next(r for r in ballot["senate_not_on_2026_ballot"] if r["district"] == 2)
    assert sd2["next_election"] == 2028 and sd2["current_holder"]["name"] == "Example Senator"


def test_contact_data_never_survives(ballot):
    text = json.dumps(ballot)
    for needle in ("[REDACTED]", "Residential", "cdn-cgi", "Email #", "Phone #"):
        assert needle not in text
    dc.pii_gate(text)  # raises on any hit


def test_pii_gate_trips_on_contact_data():
    with pytest.raises(RuntimeError):
        dc.pii_gate('{"name": "X", "phone": "(302) 555-0100"}')
    with pytest.raises(RuntimeError):
        dc.pii_gate('{"note": "someone@example.com"}')


def test_websites_kept_and_withdrawals_dated(ballot):
    house = next(r for r in ballot["races"] if r["id"] == "us-house")
    murphy = next(c for c in house["candidates"] if c["name"] == "Lee Murphy")
    assert murphy["status"] == "withdrawn" and murphy["withdrawn_on"] == "2026-07-21"
    assert house["withdrawals"] == [{"name": "Lee Murphy", "withdrawn_on": "2026-07-21"}]
    coons = next(c for c in next(r for r in ballot["races"] if r["id"] == "us-senate")["candidates"] if c["name"] == "Chris Coons")
    assert coons["website"] == "https://chriscoons.com" and coons["filed"] == "2026-06-12"


def test_incumbent_match_handles_hyphenated_surname(ballot):
    hd17 = next(r for r in ballot["races"] if r["id"] == "state-house-17")
    assert [c["incumbent"] for c in hd17["candidates"]] == [True]


def test_statewide_officeholder_not_on_ballot_is_not_labelled(ballot):
    tr = next(r for r in ballot["races"] if r["id"] == "state-treasurer")
    assert tr["current_holder"]["name"] == "Colleen Davis"
    assert not any(c["incumbent"] for c in tr["candidates"])


def test_party_labels_expanded(ballot):
    parties = {c["party"] for r in ballot["races"] for c in r["candidates"]}
    assert "Independent Party of Delaware" in parties and "Ind Pty of DE" not in parties


def test_unknown_office_fails_loudly():
    with pytest.raises(ValueError):
        dc.classify_office("Governor", "Statewide")


def test_silent_zero_guard():
    with pytest.raises(RuntimeError):
        dc.validate({"counts": {"rows": 3, "qualified": 3, "withdrawn": 0, "races": 1}, "races": []})


def test_unchanged_content_is_not_rewritten(tmp_path, ballot):
    assert dc.write(tmp_path, ballot) is True
    assert dc.write(tmp_path, ballot) is False


# --- Forge audit fixes (2026-10-05) -------------------------------------------------

SHAPES = FIXTURES / "de_candidates_shapes.html"


def test_live_contact_layouts_are_all_dropped():
    rows, stamp = dc.parse(SHAPES.read_text(encoding="utf-8"))
    assert [r["name"] for r in rows] == ["Test Candidate Alpha", "Test O'Candidate-Beta Jr.", "Test Candidate Gamma"]
    assert rows[0]["website"] == "https://alpha.example.org" and rows[1]["website"] is None
    assert rows[2]["status"] == "withdrawn" and rows[2]["withdrawn_on"] == "2026-08-03"
    text = json.dumps(dc.build(rows, stamp, {}))
    for needle in ("PO Box", "4242", "19903", "example.org/", "@", "555", "Synthetic Lane", "19904"):
        assert needle not in text.replace("https://alpha.example.org", "")
    dc.pii_gate(text.replace("https://alpha.example.org", "https://alpha.example.org"))


@pytest.mark.parametrize("leak", ["302.555.0199", "(302)5550142", "302 555 0199", "3025550199",
                                  "Dover, DE 19904", "12 Synthetic Lane", "PO Box 4242", "Email"])
def test_pii_gate_catches_other_formats(leak):
    with pytest.raises(RuntimeError):
        dc.pii_gate(json.dumps({"x": leak}))


def test_pii_gate_allows_real_output(ballot):
    dc.pii_gate(json.dumps(ballot))


def _ballot_with(ballot, mutate):
    import copy
    b = copy.deepcopy(ballot)
    mutate(b)
    return b


def test_unknown_status_fails(ballot):
    b = _ballot_with(ballot, lambda b: b["races"][0]["candidates"][0].update(status="pending"))
    with pytest.raises(RuntimeError, match="Unknown candidate status"):
        dc.validate(b)


def test_missing_filed_date_fails(ballot):
    b = _ballot_with(ballot, lambda b: b["races"][0]["candidates"][0].update(filed=None))
    with pytest.raises(RuntimeError, match="filing date"):
        dc.validate(b)


def test_missing_senate_district_fails(ballot):
    def drop(b):
        b["races"] = [r for r in b["races"] if r["id"] != "state-senate-9"]
        b["counts"]["rows"] = sum(len(r["candidates"]) for r in b["races"])
    with pytest.raises(RuntimeError, match="State Senate districts"):
        dc.validate(_ballot_with(ballot, drop))


def test_missing_stamp_fails(ballot):
    b = _ballot_with(ballot, lambda b: b["source"].update(last_updated=None))
    with pytest.raises(RuntimeError, match="Last Updated"):
        dc.validate(b)


def test_unparsed_website_fails():
    html_text = SHAPES.read_text(encoding="utf-8").replace("Website: <a href='https://alpha.example.org'>https://alpha.example.org</a>", "Website: www.alpha.example.org")
    with pytest.raises(RuntimeError, match="website"):
        dc.parse(html_text)


def test_name_absorbing_contact_block_fails():
    html_text = SHAPES.read_text(encoding="utf-8").replace("Test Candidate Alpha<i class", "Test Candidate Alpha Residential Address: 12 Main<i class")
    with pytest.raises(RuntimeError, match="implausible candidate name"):
        dc.parse(html_text)


def test_withdrawn_incumbent_is_not_called_a_candidate():
    from etl.pages import candidate_pages as cp
    race = {"level": "state-house", "district": 1, "current_holder": {"name": "Test Candidate Gamma", "party": "Republican"},
            "candidates": [{"name": "Test Candidate Gamma", "status": "withdrawn", "withdrawn_on": "2026-08-03", "incumbent": True}]}
    out = cp.holder_block(race, "State House District 1")
    assert "withdrew from this race on August 3, 2026" in out and "is a candidate" not in out


# --- Cato (codex gpt-6-astra) cross-vendor fixes, 2026-10-06 ------------------------

FULL = FIXTURE.read_text(encoding="utf-8")


def test_double_quoted_row_markup_still_parses():
    alt = FULL.replace("<tr data-county='Statewide'>", '<tr data-county="Statewide">', 1).replace("data-label='Office'>U.S. Senator", 'data-label="Office">U.S. Senator', 1)
    rows, _ = dc.parse(alt)
    assert len(rows) == 128 and any(r["name"] == "Chris Coons" for r in rows)


def test_a_row_the_parser_cannot_close_fails_loudly():
    head, body = FULL.split("<tbody>", 1)
    broken = head + "<tbody>" + body.replace("</tr>", "", 1)
    with pytest.raises(RuntimeError, match="complete rows"):
        dc.parse(broken)


def test_candidate_vanishing_without_withdrawal_refuses_write(tmp_path, ballot):
    import copy
    assert dc.write(tmp_path, ballot) is True
    b = copy.deepcopy(ballot)
    sen = next(r for r in b["races"] if r["id"] == "us-senate")
    sen["candidates"] = [c for c in sen["candidates"] if c["name"] != "Chris Coons"]
    with pytest.raises(RuntimeError, match="missing from this pull"):
        dc.write(tmp_path, b)


@pytest.mark.parametrize("site", ["https://example.org/?contact=person%40example.org", "https://wa.me/13025550100",
                                  "mailto:someone@example.org", "javascript:alert(1)", "https://x.example/tel:3025550100"])
def test_contact_data_in_website_field_is_refused(site):
    html_text = SHAPES.read_text(encoding="utf-8").replace("https://alpha.example.org'>https://alpha.example.org", site + "'>" + site)
    with pytest.raises(RuntimeError, match="website"):
        dc.parse(html_text)


def test_html_entities_in_website_are_decoded():
    html_text = SHAPES.read_text(encoding="utf-8").replace("https://alpha.example.org'>", "https://alpha.example.org/?a=1&amp;b=2'>")
    rows, _ = dc.parse(html_text)
    assert rows[0]["website"] == "https://alpha.example.org/?a=1&b=2"


@pytest.mark.parametrize("leak", ["+1 302 555 0100", "13025550100", "person%40example.org", "wa.me/13025550100"])
def test_pii_gate_catches_encoded_and_international(leak):
    with pytest.raises(RuntimeError):
        dc.pii_gate(json.dumps({"x": leak}))


def test_unknown_or_empty_party_fails():
    with pytest.raises(RuntimeError, match="party"):
        dc.parse(SHAPES.read_text(encoding="utf-8").replace("data-label='Party'>Democratic", "data-label='Party'>", 1))


def test_error_messages_never_echo_source_text():
    try:
        dc.parse(SHAPES.read_text(encoding="utf-8").replace("Test Candidate Alpha<i class", "Test Candidate Alpha jane@example.org Address: 12 Main<i class"))
    except RuntimeError as exc:
        assert "jane" not in str(exc) and "Main" not in str(exc)
    else:
        raise AssertionError("expected a refusal")


def test_two_surname_matches_refuse_the_label(parsed):
    rows, stamp = parsed
    roster = {("House", 1): {"name": "Test Smith", "party": "Democratic"}}
    import copy
    rs = copy.deepcopy(rows)
    for r in rs:
        if r["office_source"] == "State Representative District 1":
            r["name"] = "Pat Smith"
    with pytest.raises(RuntimeError, match="more than one candidate"):
        dc.build(rs, stamp, roster)


def test_jsonld_cannot_break_out_of_script():
    from etl.pages import candidate_pages as cp
    out = cp.head("t", "d", "/x/", [("Home", "/"), ("</script><script>alert(1)</script>", "/x/")])
    block = out.split('<script type="application/ld+json">', 1)[1].split("</script>", 1)[0]
    assert "<" not in block
