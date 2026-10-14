"""Tests for etl.sources.de_contract_spend (Y9 contracts puller) and etl.pages.contracts_section.

Fixtures are trimmed, real SoQL aggregate responses from data.delaware.gov sifm-293u
(Statewide Central Contract Spend), grouped by contract, vendor, fiscal year and spend
group. Every vendor in the fixture is a business.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from etl.pages import contracts_section
from etl.sources import de_contract_spend as dcs
from etl.tests.html_balance import check_balanced

FX = Path(__file__).resolve().parent / "fixtures"
SMALL = {"min_rows": 1, "min_contracts": 1, "min_pairs": 1}


@pytest.fixture
def grouped() -> list[dict]:
    return json.loads((FX / "de_contract_spend_grouped.json").read_text(encoding="utf-8"))


@pytest.fixture
def meta() -> dict:
    return json.loads((FX / "de_contract_spend_meta.json").read_text(encoding="utf-8"))


def _rows(g):
    return sum(int(r["n"]) for r in g)


def _spend(g):
    return round(sum(float(r["spend"]) for r in g), 2)


def _summary(meta, grouped, **kw):
    args = {"total_rows": _rows(grouped), "total_spend": _spend(grouped), **SMALL}
    args.update(kw)
    return dcs.build_summary(meta, grouped, **args)


@pytest.mark.parametrize("ym,fy", [(202607, 2026), (202606, 2026), (202605, 2025), (202512, 2025), (202507, 2025)])
def test_latest_complete_fiscal_year(ym, fy):
    assert dcs.latest_complete_fy(ym) == fy


def test_kpis_for_latest_complete_year(meta, grouped):
    s = _summary(meta, grouped)
    fy = s["fiscal_year"]
    assert fy == dcs.latest_complete_fy(max(int(r["last_ym"]) for r in grouped))
    rows_fy = [r for r in grouped if int(r["fiscal_year"]) == fy]
    k = s["kpi"]
    assert k["total_spend"] == pytest.approx(_spend(rows_fy))
    assert k["contracts"] == len({r["long_contract_number"] for r in rows_fy})
    assert k["vendors"] == len({" ".join(r["vendor_name"].split()) for r in rows_fy})
    assert set(k["by_spend_group"]) == {"A", "M", "S"}
    assert sum(k["by_spend_group"].values()) == pytest.approx(k["total_spend"])


def test_table_rows_sorted_and_whitespace_collapsed(meta, grouped):
    fy = dcs.latest_complete_fy(max(int(r["last_ym"]) for r in grouped))
    grouped = [dict(r, fiscal_year=str(fy)) if r["vendor_name"].startswith("SIMONIK") else r for r in grouped]
    s = _summary(meta, grouped)
    t = s["contracts"]
    keys = [(r["description"], r["contract_number"], r["vendor"]) for r in t]
    assert keys == sorted(keys)
    vendors = {r["vendor"] for r in t}
    assert all("\n" not in v and "  " not in v for v in vendors)
    assert "SIMONIK TRANSPORTATION & WAREHOUSING GROUP LLC" in vendors
    fields = {tuple(sorted(r)) for r in t}
    assert fields == {("award_type", "contract_number", "description", "first_month", "fy_spend", "last_month", "vendor")}


def test_table_only_has_pairs_with_spend_in_the_year(meta, grouped):
    s = _summary(meta, grouped)
    fy = s["fiscal_year"]
    want = {(r["long_contract_number"], " ".join(r["vendor_name"].split())) for r in grouped if int(r["fiscal_year"]) == fy}
    got = {(r["contract_number"], r["vendor"]) for r in s["contracts"]}
    assert got == want


def test_first_and_last_month_cover_all_years(meta, grouped):
    s = _summary(meta, grouped)
    row = s["contracts"][0]
    src = [r for r in grouped if r["long_contract_number"] == row["contract_number"]
           and " ".join(r["vendor_name"].split()) == row["vendor"]]
    lo = min(int(r["first_ym"]) for r in src)
    hi = max(int(r["last_ym"]) for r in src)
    assert row["first_month"] == f"{lo // 100}-{lo % 100:02d}"
    assert row["last_month"] == f"{hi // 100}-{hi % 100:02d}"


def test_description_uses_latest_reported(meta, grouped):
    s = _summary(meta, grouped)
    descs = {}
    for r in grouped:
        descs.setdefault(r["long_contract_number"], set()).add(r["contract_description"])
    multi = [c for c, d in descs.items() if len(d) > 1]
    for c in multi:
        latest = max((int(r["last_ym"]), r["contract_description"]) for r in grouped if r["long_contract_number"] == c)[1]
        assert {r["description"] for r in s["contracts"] if r["contract_number"] == c} <= {latest}


def test_reconciliation_guards(meta, grouped):
    with pytest.raises(RuntimeError, match="reconcil"):
        _summary(meta, grouped, total_rows=_rows(grouped) + 5)
    with pytest.raises(RuntimeError, match="reconcil"):
        _summary(meta, grouped, total_spend=_spend(grouped) + 50)


def test_silent_zero_guard_with_real_floors(meta, grouped):
    with pytest.raises(RuntimeError, match="silent-zero"):
        dcs.build_summary(meta, grouped, total_rows=_rows(grouped), total_spend=_spend(grouped))


def test_source_stamps_and_determinism(meta, grouped):
    s = _summary(meta, grouped)
    assert s["source"]["dataset_id"] == "sifm-293u"
    assert s["source"]["rows_updated"] == "2026-09-16"
    a = json.dumps(s, sort_keys=True)
    assert a == json.dumps(_summary(meta, list(reversed(grouped))), sort_keys=True)
    assert "generated_at" not in a
    for bad in ("address", "phone", "email"):
        assert bad not in a.lower()


def test_write_outputs(tmp_path, meta, grouped):
    s = _summary(meta, grouped)
    dcs.write_outputs(tmp_path, s, generated_at="2026-10-14T00:00:00Z")
    assert json.loads((tmp_path / "contracts-summary.json").read_text(encoding="utf-8")) == json.loads(json.dumps(s))
    man = json.loads((tmp_path / "contracts-manifest.json").read_text(encoding="utf-8"))
    assert man["generated_at"] == "2026-10-14T00:00:00Z"
    assert man["row_counts"]["table_rows"] == len(s["contracts"])
    assert not (tmp_path / "manifest.json").exists()  # never clobber the checkbook manifest


# ---------------------------------------------------------------------------
# Section generator (spliced into spending/index.html between markers)
# ---------------------------------------------------------------------------

PAGE = """<html><body><main>
<p>Existing claim stays word for word.</p>
<!-- CONTRACTS:START -->old<!-- CONTRACTS:END -->
</main></body></html>
"""


def test_block_renders_static_table(meta, grouped):
    s = _summary(meta, grouped)
    block = contracts_section.render_block(s)
    assert block.startswith("<!-- CONTRACTS:START")
    assert block.rstrip().endswith("<!-- CONTRACTS:END -->")
    check_balanced(block)
    assert 'id="contracts"' in block
    assert block.count('<tr class="ct-row"') == len(s["contracts"])
    assert "sifm-293u" in block
    assert "September 16, 2026" in block
    assert "not contract start or end dates" in block
    for bad in ("\u2014", "\u2013", "&" + "mdash;", "&" + "ndash;"):
        assert bad not in block
    low = block.lower()
    for word in ("largest", "top vendor", "worst", "best"):
        assert word not in low, word


def test_splice_keeps_rest_of_page(meta, grouped):
    s = _summary(meta, grouped)
    out = contracts_section.splice(PAGE, contracts_section.render_block(s))
    assert "Existing claim stays word for word." in out
    assert "old" not in out.split("<!-- CONTRACTS:START")[1].split("CONTRACTS:END")[0][:5]
    assert out.count("<!-- CONTRACTS:START") == 1 and out.count("<!-- CONTRACTS:END -->") == 1
    # Idempotent: splicing twice gives the same page.
    assert contracts_section.splice(out, contracts_section.render_block(s)) == out


def test_splice_requires_markers():
    with pytest.raises(RuntimeError, match="marker"):
        contracts_section.splice("<html></html>", "<!-- CONTRACTS:START -->x<!-- CONTRACTS:END -->")
