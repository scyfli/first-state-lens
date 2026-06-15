"""Smoke tests for etl.sources.dsb_grants (HTML parser + Cycle 5 detection)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from etl.lib.fetch import FetchResult
from etl.sources import dsb_grants


# ---------------------------------------------------------------------------
# detect_cycle_5_status
# ---------------------------------------------------------------------------


def test_cycle_5_pending_when_no_cycle_5_records() -> None:
    assert dsb_grants.detect_cycle_5_status([], "anything") == "pending"


def test_cycle_5_pending_when_only_placeholder() -> None:
    grantees = [
        dsb_grants.GranteeRecord(
            cycle=5,
            grantee="(pending publication)",
            storefront_address=None,
            amount_usd=700000.0,
            awarded_date=None,
            category=None,
            raw_context="",
        )
    ]
    assert dsb_grants.detect_cycle_5_status(grantees, "") == "pending"


def test_cycle_5_published_when_real_grantee_present() -> None:
    grantees = [
        dsb_grants.GranteeRecord(
            cycle=5,
            grantee="Acme Corner Store",
            storefront_address="123 N Market St, Wilmington, DE 19801",
            amount_usd=125000.0,
            awarded_date=None,
            category=None,
            raw_context="",
        )
    ]
    assert dsb_grants.detect_cycle_5_status(grantees, "") == "published"


# ---------------------------------------------------------------------------
# parse_html — pending page (current live state)
# ---------------------------------------------------------------------------


def test_parse_pending_page(fixture_dsb_page_pending: str) -> None:
    result = dsb_grants.parse_html(fixture_dsb_page_pending)
    # No grantees parseable from the pending page.
    assert result.grantees == []
    assert result.cycle_5_status == "pending"
    assert result.snapshot_sha  # populated
    # The parser surfaces a "this is normal pre-announcement" warning.
    assert any("pre-announcement" in w or "application-status" in w for w in result.parser_warnings)


# ---------------------------------------------------------------------------
# parse_html — published page (synthetic / toy fixture)
# ---------------------------------------------------------------------------


def test_parse_published_page(fixture_dsb_page_published: str) -> None:
    result = dsb_grants.parse_html(fixture_dsb_page_published)
    assert len(result.grantees) >= 3
    cycles = {g.cycle for g in result.grantees}
    assert 1 in cycles
    assert 5 in cycles
    # Cycle 5 has a real grantee → published.
    assert result.cycle_5_status == "published"
    # Verify a Cycle 1 amount + address parse.
    cycle_1 = [g for g in result.grantees if g.cycle == 1]
    assert any(g.amount_usd == 250000.0 for g in cycle_1)
    assert any(
        g.storefront_address and "Dover" in g.storefront_address
        for g in cycle_1
    )


# ---------------------------------------------------------------------------
# Snapshot SHA stability
# ---------------------------------------------------------------------------


def test_snapshot_sha_stable_across_whitespace_changes(
    fixture_dsb_page_pending: str,
) -> None:
    """Extra whitespace, identical visible content → same SHA."""
    a = dsb_grants.compute_snapshot_sha(fixture_dsb_page_pending)
    perturbed = fixture_dsb_page_pending.replace(
        "Applications have <strong>closed</strong>",
        "Applications  have   <strong>closed</strong>  ",
    )
    b = dsb_grants.compute_snapshot_sha(perturbed)
    assert a == b


def test_snapshot_sha_changes_when_visible_text_changes(
    fixture_dsb_page_pending: str,
) -> None:
    a = dsb_grants.compute_snapshot_sha(fixture_dsb_page_pending)
    perturbed = fixture_dsb_page_pending.replace(
        "late April of 2026", "early May of 2026"
    )
    b = dsb_grants.compute_snapshot_sha(perturbed)
    assert a != b


def test_snapshot_sha_ignores_scripts_and_styles(
    fixture_dsb_page_pending: str,
) -> None:
    """Script/style/comment changes should NOT shift the SHA."""
    a = dsb_grants.compute_snapshot_sha(fixture_dsb_page_pending)
    perturbed = fixture_dsb_page_pending.replace(
        "</body>",
        "<script>window.x = 42;</script>\n<style>.cls{color:red}</style>\n<!--comment-->\n</body>",
    )
    b = dsb_grants.compute_snapshot_sha(perturbed)
    assert a == b


# ---------------------------------------------------------------------------
# pull() — full puller flow with mocked fetch
# ---------------------------------------------------------------------------


def _fake_fetch_result(url: str, body: bytes) -> FetchResult:
    import hashlib

    return FetchResult(
        url=url,
        http_status=200,
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
        last_fetched="2026-05-11T13:00:00Z",
        content_type="text/html; charset=utf-8",
        elapsed_ms=42,
        warnings=[],
    )


def test_pull_writes_raw_html_and_parsed_json(
    tmp_path: Path, fixture_dsb_page_pending: str
) -> None:
    body = fixture_dsb_page_pending.encode("utf-8")
    fake = _fake_fetch_result(dsb_grants.DEFAULT_DSB_URL, body)
    with patch.object(dsb_grants, "fetch", return_value=fake):
        out_path, fetch_result, parse_result = dsb_grants.pull(tmp_path)

    raw_html_path = tmp_path / dsb_grants.OUTPUT_RAW_HTML
    parsed_json_path = tmp_path / dsb_grants.OUTPUT_PARSED_JSON
    assert raw_html_path.exists()
    assert parsed_json_path.exists()
    assert out_path == parsed_json_path

    # Warnings surface up to FetchResult.
    assert any("cycle_5_status=pending" in w for w in fetch_result.warnings)
    assert any("grantee_count=0" in w for w in fetch_result.warnings)
    assert parse_result.cycle_5_status == "pending"


# ---------------------------------------------------------------------------
# .docx winner-summary parsing (session-26 — DSB canonical source)
# ---------------------------------------------------------------------------


def _make_docx(paragraphs: list[str]) -> bytes:
    """Build a minimal .docx (zip with word/document.xml) from paragraph texts."""
    import io
    import zipfile

    body = "".join(
        "<w:p><w:r><w:t>" + p.replace("&", "&amp;") + "</w:t></w:r></w:p>"
        for p in paragraphs
    )
    doc = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="x"><w:body>' + body + "</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc)
    return buf.getvalue()


def test_parse_docx_extracts_awardees_with_and_without_region() -> None:
    docx = _make_docx([
        "2026 Awardees of the Delaware Grocery Initiative",  # header, no $ -> skipped
        "Bellevue Community Center (NCC) $22,203  - Restoring cold storage.",
        "Bennett Orchards $53,999 - Installing wind machines.",  # NO region parens
        "La Red Health Center (Kent/Sussex) - $28,500 Integrating food.",  # dash before $
        "Midas Harvest Urban Farm (NCC / Kent)$30,748 - CSA scaling.",  # no space before $
    ])
    result = dsb_grants.parse_docx(docx)
    assert result.cycle_5_status == "published"
    names = {g.grantee for g in result.grantees}
    assert names == {
        "Bellevue Community Center",
        "Bennett Orchards",
        "La Red Health Center",
        "Midas Harvest Urban Farm",
    }
    by_name = {g.grantee: g for g in result.grantees}
    assert by_name["Bellevue Community Center"].amount_usd == 22203.0
    assert by_name["Bellevue Community Center"].category == "NCC"
    assert by_name["Bennett Orchards"].category is None  # no region published
    assert by_name["La Red Health Center"].amount_usd == 28500.0
    assert by_name["Midas Harvest Urban Farm"].amount_usd == 30748.0
    assert all(g.cycle == 5 for g in result.grantees)


def test_parse_docx_handles_corrupt_bytes() -> None:
    result = dsb_grants.parse_docx(b"not a zip file")
    assert result.grantees == []
    assert result.cycle_5_status == "pending"
    assert any("docx" in w for w in result.parser_warnings)
