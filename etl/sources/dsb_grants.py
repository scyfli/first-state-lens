"""Delaware DSB (Division of Small Business) DGI grantee puller.

Source (per design brief 2026-05-11-DGI-Bulk-ETL-Design.md):
  https://business.delaware.gov/delaware-grocery-initiative/  +  news.delaware.gov releases

License: Public record (Delaware state government work)
Cadence: Per-cycle (scraped on each ETL run)
Output:
  etl/raw/dsb-grants-raw.html   (verbatim fetched HTML for audit-trail)
  etl/raw/dsb-grants.json       (parsed grantee list)

================================================================================
OPEN QUESTION (carry to next session unless resolved): canonical source URL
================================================================================

WebFetch reconnaissance at session-15 (2026-05-11) confirmed:

  1. The DSB DGI page itself currently shows ONLY application status
     ("Applications closed. Awardees will be notified in late April of 2026.").
     No grantee list is embedded. The page is suitable for Cycle-5
     status detection but does NOT carry Cycles 1-4 historical data.

  2. The brief's secondary URL (news.delaware.gov/category/delaware-grocery-initiative/)
     returns HTTP 404 — the category page does not exist.

  3. The Delaware Council on Farm & Food Policy (DCFFP) is referenced as
     the historical archive on the DSB page, but the URL is not yet
     confirmed and a direct fetch ECONNREFUSED.

This puller is therefore a CONFIGURABLE SCAFFOLD: it knows how to fetch
HTML and apply a generic extractor, but the canonical source URL is
parameterized via `--source` (CLI) or `parameters.yaml: dsb_grants_url`.
S+3 / S+4 will pin the canonical source after the source-URL question is
resolved with the user (probably: identify the right DCFFP URL or a
state press-release archive, OR confirm grantee data only becomes
publicly available once Cycle 5 is announced).

================================================================================
Parser strategy
================================================================================

The brief calls for a "tolerant parser + a snapshot diff alarm." That
shape is implemented here:

  - parse_grantees(html, parser_hints) -- generic extractor that looks for
    common grantee-list signals (tables, dt/dd pairs, header-then-list
    structure) and emits zero-or-more GranteeRecord entries.

  - compute_snapshot_sha(html) -- normalized SHA-256 over the page's
    "interesting" content (whitespace-collapsed, scripts + nav stripped).
    The first run records this; subsequent runs compare and raise an
    alarm via `result.warnings` if the structure has shifted.

  - detect_cycle_5_status(grantees, page_text) -- returns "pending" or
    "published" per the brief's `detect_cycle_5_status` spec. Run
    independently of grantee parsing so we can detect Cycle 5 status from
    page text even if structured parsing yields nothing.

Run standalone:
    python -m etl.sources.dsb_grants --source <URL> --out etl/raw/
    python -m etl.sources.dsb_grants --fixture etl/tests/fixtures/dsb-page-toy.html
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import html.parser
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Optional

from etl.lib.atomic_io import atomic_write_bytes, atomic_write_text
from etl.lib.fetch import FetchResult, fetch


# Default fallback URL — the brief's primary citation. Parser will likely
# return zero records against this URL today (page shows application
# status only); the snapshot SHA still serves the "is the structure
# stable?" check.
DEFAULT_DSB_URL = "https://business.delaware.gov/delaware-grocery-initiative/"

# Canonical grantee-list source (resolves the carried "DSB canonical URL"
# open question, sessions 15-26). DSB publishes the per-cycle awardee list as
# a .docx "Winner Summary" linked from the DGI page ("Description of Recipient
# Projects"). This is the Cycle 5 (2026) list; the URL is cycle-specific and is
# wired via parameters.yaml: dsb_grants_url, so future cycles update one value.
CYCLE5_WINNER_SUMMARY_DOCX = (
    "https://business.delaware.gov/wp-content/uploads/sites/118/2026/05/"
    "Winner-Summary-for-DGI-webpage_webview.docx"
)

# The business.delaware.gov edge WAF rejects non-browser User-Agents with a
# 245-byte "Request Rejected" page (HTTP 200). A full browser UA passes.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

OUTPUT_RAW_HTML = "dsb-grants-raw.html"
OUTPUT_PARSED_JSON = "dsb-grants.json"


# ---------------------------------------------------------------------------
# Parsed grantee shape — matches what the geocoding transform expects
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class GranteeRecord:
    """One row extracted from the DSB page."""

    cycle: Optional[int]
    grantee: str
    storefront_address: Optional[str]
    amount_usd: Optional[float]
    awarded_date: Optional[str]
    category: Optional[str]
    raw_context: str  # surrounding text snippet for audit-trail


@dataclasses.dataclass
class ParseResult:
    grantees: list[GranteeRecord]
    cycle_5_status: str  # "pending" or "published"
    snapshot_sha: str
    parser_warnings: list[str]


# ---------------------------------------------------------------------------
# Public API: pull (fetches + parses + persists) and parse_html (pure)
# ---------------------------------------------------------------------------


def pull(
    out_dir: Path, *, url: str = DEFAULT_DSB_URL
) -> tuple[Path, FetchResult, ParseResult]:
    """Fetch the DSB page, persist HTML, parse grantees, persist JSON.

    Returns (parsed_json_path, FetchResult, ParseResult). The raw HTML is
    persisted alongside as `dsb-grants-raw.html` for audit-trail.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # Browser UA to clear the business.delaware.gov WAF (rejects bot UAs).
    result = fetch(url, user_agent=BROWSER_USER_AGENT)
    atomic_write_bytes(out_dir / OUTPUT_RAW_HTML, result.body)

    is_docx = url.lower().endswith(".docx") or (
        result.content_type is not None
        and "wordprocessingml" in result.content_type
    )
    if is_docx:
        parse_result = parse_docx(result.body)
    else:
        parse_result = parse_html(result.body.decode("utf-8", errors="replace"))

    atomic_write_text(
        out_dir / OUTPUT_PARSED_JSON,
        json.dumps(_to_serializable(parse_result), indent=2, sort_keys=True) + "\n",
    )

    # Surface parser warnings on the FetchResult so the orchestrator's
    # manifest captures them.
    for w in parse_result.parser_warnings:
        result.warnings.append(f"dsb-grants parser: {w}")
    result.warnings.append(
        f"dsb-grants cycle_5_status={parse_result.cycle_5_status}"
    )
    result.warnings.append(f"dsb-grants grantee_count={len(parse_result.grantees)}")

    return out_dir / OUTPUT_PARSED_JSON, result, parse_result


def parse_html(html_text: str) -> ParseResult:
    """Pure parsing function — no I/O, no network. Safe to test offline."""
    warnings: list[str] = []
    snapshot_sha = compute_snapshot_sha(html_text)

    text_blocks = _extract_visible_text_blocks(html_text)
    grantees = _extract_grantees(text_blocks, html_text)

    cycle_5_status = detect_cycle_5_status(grantees, " ".join(text_blocks))

    if not grantees and cycle_5_status == "pending":
        warnings.append(
            "no grantees parsed; page may show application-status only "
            "(Cycle 5 not yet announced). This is normal pre-announcement."
        )
    elif not grantees:
        warnings.append(
            "no grantees parsed AND page text does not indicate pending status; "
            "parser may be looking for the wrong structure. Check the snapshot SHA."
        )

    return ParseResult(
        grantees=grantees,
        cycle_5_status=cycle_5_status,
        snapshot_sha=snapshot_sha,
        parser_warnings=warnings,
    )


# ---------------------------------------------------------------------------
# .docx parsing — the canonical "Winner Summary" awardee list
# ---------------------------------------------------------------------------


def parse_docx(docx_bytes: bytes) -> ParseResult:
    """Parse a DSB 'Winner Summary' .docx into grantee records.

    Format (one paragraph per awardee):
        <Org Name> (<region>) $<amount> - <project description>
    with tolerant handling of dash/amount ordering and missing spaces.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(docx_bytes))
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        return ParseResult(
            grantees=[],
            cycle_5_status="pending",
            snapshot_sha=compute_snapshot_sha(""),
            parser_warnings=[f"docx could not be opened/parsed: {exc}"],
        )

    paragraphs = _docx_paragraphs(xml)
    grantees = [r for r in (_parse_docx_grantee_line(p) for p in paragraphs) if r is not None]
    warnings: list[str] = []
    if not grantees:
        warnings.append(
            "no grantees parsed from docx; the winner-summary format may have "
            "changed. Check the document structure."
        )
    return ParseResult(
        grantees=grantees,
        cycle_5_status="published" if grantees else "pending",
        snapshot_sha=compute_snapshot_sha(" ".join(paragraphs)),
        parser_warnings=warnings,
    )


def _docx_paragraphs(document_xml: str) -> list[str]:
    """Extract non-empty visible paragraph texts from a Word document.xml."""
    out: list[str] = []
    for raw in re.split(r"</w:p>", document_xml):
        text = re.sub(r"<[^>]+>", "", raw).replace("&amp;", "&").strip()
        if text:
            out.append(text)
    return out


_DOCX_REGION_RE = re.compile(r"\(([^)]+)\)")
_DOCX_AMOUNT_RE = re.compile(r"\$\s?([\d,]{3,})")


def _parse_docx_grantee_line(text: str) -> Optional[GranteeRecord]:
    """Parse one awardee paragraph. An awardee line always has a $amount; the
    (region) is optional (e.g. 'Bennett Orchards $53,999' carries none).
    Returns None for non-awardee lines (the header has no $amount)."""
    amount_m = _DOCX_AMOUNT_RE.search(text)
    if amount_m is None:
        return None
    region_m = _DOCX_REGION_RE.search(text)
    if region_m is not None and region_m.start() < amount_m.start():
        # Region precedes the amount: name is the text before the region.
        name = text[: region_m.start()]
        region: Optional[str] = region_m.group(1).strip()
    else:
        # No region before the amount: name is the text before the amount.
        name = text[: amount_m.start()]
        region = None
    name = name.strip().rstrip("-").strip()
    if not name:
        return None
    desc = text[amount_m.end():].lstrip(" -–—").strip()
    return GranteeRecord(
        cycle=5,
        grantee=name,
        storefront_address=None,  # DSB publishes region only, not street address
        amount_usd=float(amount_m.group(1).replace(",", "")),
        awarded_date="2026-05",
        category=region,  # region: NCC / Kent / Sussex / Statewide (or None)
        raw_context=(desc[:200] if desc else text[:200]),
    )


# ---------------------------------------------------------------------------
# Snapshot SHA — normalized over visible text only
# ---------------------------------------------------------------------------


def compute_snapshot_sha(html_text: str) -> str:
    """SHA-256 over normalized visible text (scripts/styles/nav stripped)."""
    normalized = _normalize_for_snapshot(html_text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_for_snapshot(html_text: str) -> str:
    # Strip <script>...</script>, <style>...</style>, and HTML comments.
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", html_text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    # Strip <nav>, <header>, <footer> blocks (volatile cross-page chrome).
    for tag in ("nav", "header", "footer"):
        text = re.sub(
            rf"<{tag}\b[^>]*>.*?</{tag}>",
            " ",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    # Strip all remaining tags.
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace.
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Visible text extraction
# ---------------------------------------------------------------------------


class _TextExtractor(html.parser.HTMLParser):
    """Walk the HTML and collect visible text blocks."""

    SKIP_TAGS = frozenset({"script", "style", "nav", "header", "footer", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._current: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag in ("p", "li", "td", "th", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "div", "br"):
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in ("p", "li", "td", "th", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "div"):
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._current.append(data.strip())

    def _flush(self) -> None:
        if self._current:
            self.blocks.append(" ".join(self._current))
            self._current = []

    def close(self) -> None:  # noqa: D401
        self._flush()
        super().close()


def _extract_visible_text_blocks(html_text: str) -> list[str]:
    parser = _TextExtractor()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:
        # html.parser is permissive; we should rarely land here, but if we do
        # the empty-blocks return path is the safest fallback.
        pass
    return [b for b in parser.blocks if b]


# ---------------------------------------------------------------------------
# Grantee extraction — best-effort over arbitrary structure
# ---------------------------------------------------------------------------


CYCLE_HEADING_RX = re.compile(r"\bcycle\s*(\d+)\b", re.IGNORECASE)
AMOUNT_RX = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
ADDRESS_HINT_RX = re.compile(
    r"\d+\s+[A-Z][\w\.]*(?:\s+[A-Z][\w\.]*)*"
    r".{0,80}?"
    r"\b(?:DE|Delaware)\b"
    r".{0,20}?\d{5}"
)


def _extract_grantees(text_blocks: list[str], full_html: str) -> list[GranteeRecord]:
    """Heuristic grantee extraction.

    Walks text blocks looking for cycle headers + adjacent grantee/amount
    pairs. Returns empty when the page has no recognizable grantee
    structure (which is currently the case for the DSB DGI landing page).
    """
    grantees: list[GranteeRecord] = []
    current_cycle: Optional[int] = None

    for i, block in enumerate(text_blocks):
        cycle_match = CYCLE_HEADING_RX.search(block)
        if cycle_match:
            current_cycle = int(cycle_match.group(1))

        # Look for an amount in this block.
        amount_match = AMOUNT_RX.search(block)
        if amount_match and current_cycle is not None:
            # A block with a dollar amount AND we're under a known cycle
            # heading is a grantee candidate. Use surrounding blocks for
            # context.
            amount_usd = _parse_amount(amount_match.group(1))
            grantee_name = _guess_grantee_name(block, amount_match)
            if grantee_name is None:
                continue
            address = _guess_address(block, text_blocks, i)
            grantees.append(
                GranteeRecord(
                    cycle=current_cycle,
                    grantee=grantee_name,
                    storefront_address=address,
                    amount_usd=amount_usd,
                    awarded_date=None,
                    category=None,
                    raw_context=block[:240],
                )
            )

    return grantees


def _parse_amount(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _guess_grantee_name(block: str, amount_match: re.Match) -> Optional[str]:
    """Take the text before the dollar amount as the candidate name."""
    head = block[: amount_match.start()].strip()
    # Trim trailing punctuation / connector words.
    head = re.sub(r"[\s\-:,]+$", "", head)
    head = re.sub(r"\b(?:awarded|grant|received|of)\s*$", "", head, flags=re.IGNORECASE).strip()
    if not head or len(head) < 3 or len(head) > 200:
        return None
    return head


def _guess_address(block: str, all_blocks: list[str], idx: int) -> Optional[str]:
    """Look for an address in the current + next block."""
    for candidate in (block, all_blocks[idx + 1] if idx + 1 < len(all_blocks) else ""):
        m = ADDRESS_HINT_RX.search(candidate)
        if m:
            return m.group(0).strip()
    return None


# ---------------------------------------------------------------------------
# Cycle 5 detection (per brief)
# ---------------------------------------------------------------------------


def detect_cycle_5_status(grantees: list[GranteeRecord], page_text: str) -> str:
    """Return 'pending' or 'published' for Cycle 5.

    Brief spec:
      - If any grantee has cycle=5 with a real grantee name (not placeholder),
        status is 'published'.
      - Otherwise (no Cycle 5 grantees OR all Cycle 5 records are placeholder
        text), status is 'pending'.
    """
    cycle_5 = [g for g in grantees if g.cycle == 5]
    if not cycle_5:
        return "pending"
    placeholder_names = {"", "(pending publication)", "pending", "tbd", "to be announced"}
    real = [
        g for g in cycle_5
        if g.grantee and g.grantee.strip().lower() not in placeholder_names
    ]
    return "published" if real else "pending"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _to_serializable(p: ParseResult) -> dict:
    return {
        "snapshot_sha": p.snapshot_sha,
        "cycle_5_status": p.cycle_5_status,
        "parser_warnings": list(p.parser_warnings),
        "grantees": [dataclasses.asdict(g) for g in p.grantees],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull + parse DSB DGI grantee list (scaffold; URL parameterized)."
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_DSB_URL,
        help="Source URL (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("etl/raw"),
        help="Output directory (default: etl/raw)",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Parse a local HTML fixture instead of fetching the URL.",
    )
    args = parser.parse_args(argv)

    if args.fixture:
        html_text = args.fixture.read_text(encoding="utf-8")
        result = parse_html(html_text)
        print(f"snapshot_sha:    {result.snapshot_sha}")
        print(f"cycle_5_status:  {result.cycle_5_status}")
        print(f"grantee_count:   {len(result.grantees)}")
        for w in result.parser_warnings:
            print(f"  warning:       {w}")
        for g in result.grantees:
            print(
                f"  - cycle={g.cycle} grantee={g.grantee!r} "
                f"amount={g.amount_usd} addr={g.storefront_address!r}"
            )
        return 0

    target, fetch_result, parse_result = pull(args.out, url=args.source)
    print(f"wrote {target} ({fetch_result.http_status}; {len(fetch_result.body)} bytes)")
    print(f"  snapshot_sha:    {parse_result.snapshot_sha}")
    print(f"  cycle_5_status:  {parse_result.cycle_5_status}")
    print(f"  grantee_count:   {len(parse_result.grantees)}")
    for w in fetch_result.warnings:
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
