"""Tests for etl.sources.epa_sdwis_systems (per-system Delaware water records).

Fixture: etl/tests/fixtures/epa_sdwis_systems.json, a trimmed live pull of five
Delaware systems. Contact fields in it are obvious placeholders that exist only to
prove the puller drops them.
"""

from __future__ import annotations

import copy
import json

import pytest

from etl.sources import epa_sdwis_systems as m

SMALL = dict(min_systems=1, min_violations=1, min_active_cws=1, min_contaminants=1)


@pytest.fixture
def fx(fixtures_dir):
    return json.loads((fixtures_dir / "epa_sdwis_systems.json").read_text(encoding="utf-8"))


def build(fx, **kw):
    args = dict(SMALL)
    args.update(kw)
    return m.build(fx["water_system"], fx["geographic_area"], fx["violation"],
                   m.parse_contaminants(fx["contaminants"], minimum=1), **args)


def test_contact_fields_never_reach_output(fx):
    out = json.dumps(build(fx))
    assert "PLACEHOLDER" not in out
    assert "example.invalid" not in out
    assert "000-000-0000" not in out
    for key in m.CONTACT_FIELDS:
        assert f'"{key}"' not in out


def test_page_set_is_active_cws_plus_any_system_with_violations(fx):
    d = build(fx)
    ids = [s["pwsid"] for s in d["systems"]]
    assert ids == sorted(ids)
    assert "DE0000007" in ids          # active CWS, no violations
    assert "DE0000263" in ids          # inactive CWS with violations
    assert "DE0000834" in ids          # non-community system with violations
    assert "DE0000115" in ids          # active CWS with violations
    assert "DE0000002" not in ids      # inactive, no violations: no page


def test_totals_cover_every_system_on_record(fx):
    d = build(fx)
    t = d["totals"]
    assert t["systems_on_record"] == 5
    assert t["violations_on_record"] == len(fx["violation"])
    assert t["health_based"] == sum(1 for v in fx["violation"] if v["is_health_based_ind"] == "Y")
    assert t["no_return_to_compliance_date"] == sum(1 for v in fx["violation"] if not v["rtc_date"])
    assert t["systems_with_violations"] == 3
    assert t["community_active"] == 2
    assert t["pages"] == 4


def test_violation_fields_and_order(fx):
    d = build(fx)
    s = next(x for x in d["systems"] if x["pwsid"] == "DE0000115")
    vs = s["violations"]
    assert len(vs) == sum(1 for v in fx["violation"] if v["pwsid"] == "DE0000115")
    keys = [(v["begin"] or "", v["id"]) for v in vs]
    assert keys == sorted(keys, reverse=True)  # newest first
    for v in vs:
        assert set(v) == {"id", "begin", "end", "returned_to_compliance", "contaminant_code", "contaminant",
                          "category", "health_based", "rule_code", "violation_code"}
        assert v["begin"] is None or len(v["begin"]) == 10
        assert isinstance(v["health_based"], bool)
    assert any(v["returned_to_compliance"] is None for v in vs)  # the open one is kept as null, never guessed


def test_contaminant_names_use_epa_wording_with_code_fallback(fx):
    lu = m.parse_contaminants(fx["contaminants"], minimum=1)
    d = build(fx)
    seen = {v["contaminant_code"]: v["contaminant"] for s in d["systems"] for v in s["violations"]}
    assert any(c not in lu for c in seen)  # fixture deliberately lacks one code
    for code, name in seen.items():
        if code in lu:
            assert name == lu[code]
        else:
            assert name is None  # the page states the code, never invents a name


def test_place_and_name_formatting(fx):
    d = build(fx)
    hp = next(x for x in d["systems"] if x["pwsid"] == "DE0000263")
    assert hp["name"] == "Holiday Pines"
    assert hp["epa_name"] == "HOLIDAY PINES"
    assert hp["city"] == "Millsboro"
    assert hp["county"] == "Sussex"
    assert hp["activity"] == "I"
    assert hp["deactivated"] == "2020-01-17"
    mc = next(x for x in d["systems"] if x["pwsid"] == "DE0000834")
    assert mc["county"] == "Sussex"
    assert mc["city"] is None   # EPA lists a county but no city: kept as absent, not guessed


@pytest.mark.parametrize("raw,want", [
    ("SHAWNEE COUNTRY CLUB (SYSTEM #4)", "Shawnee Country Club (System #4)"),
    ("JOE'S MHP", "Joe's MHP"),
    ("CAMDEN-WYOMING", "Camden-Wyoming"),
    ("ARTESIAN WATER CO LLC", "Artesian Water Co LLC"),
    ("  TOWN OF  SMYRNA ", "Town of Smyrna"),
])
def test_titlecase(raw, want):
    assert m.titlecase(raw) == want


def test_county_join():
    assert m.county_name("Kent,Sussex") == "Kent and Sussex"
    assert m.county_name("New Castle") == "New Castle"
    assert m.county_name(None) is None


def test_silent_zero_guard_with_production_thresholds(fx):
    with pytest.raises(RuntimeError, match="silent-zero"):
        m.build(fx["water_system"], fx["geographic_area"], fx["violation"],
                m.parse_contaminants(fx["contaminants"], minimum=1))


def test_non_delaware_system_is_refused(fx):
    bad = copy.deepcopy(fx)
    bad["water_system"][0]["pwsid"] = "MD0070003"
    with pytest.raises(RuntimeError, match="non-Delaware"):
        build(bad)


def test_violation_for_unknown_system_is_refused(fx):
    bad = copy.deepcopy(fx)
    bad["violation"][0]["pwsid"] = "DE9999999"
    with pytest.raises(RuntimeError, match="not in WATER_SYSTEM"):
        build(bad)


def test_deterministic_and_as_of_is_kept_when_content_unchanged(fx, tmp_path):
    d1 = build(fx)
    d2 = build(fx)
    assert m.dumps(d1) == m.dumps(d2)
    m.write(tmp_path, d1, as_of="2026-10-01", manifest_extra={"generated_at": "x"})
    first = (tmp_path / m.OUT_DATA).read_text(encoding="utf-8")
    m.write(tmp_path, d2, as_of="2026-10-14", manifest_extra={"generated_at": "y"})
    assert (tmp_path / m.OUT_DATA).read_text(encoding="utf-8") == first
    assert json.loads(first)["data_as_of"] == "2026-10-01"
    changed = build(fx)
    changed["systems"][0]["population"] = 123456
    m.write(tmp_path, changed, as_of="2026-10-14", manifest_extra={"generated_at": "z"})
    assert json.loads((tmp_path / m.OUT_DATA).read_text(encoding="utf-8"))["data_as_of"] == "2026-10-14"
    man = json.loads((tmp_path / m.OUT_MANIFEST).read_text(encoding="utf-8"))
    assert man["generated_at"] == "z"


def test_parse_contaminants_rejects_error_payload():
    with pytest.raises(RuntimeError):
        m.parse_contaminants({"Results": {"Error": {"ErrorMessage": "nope"}}})
