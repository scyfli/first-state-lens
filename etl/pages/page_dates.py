"""Truthful visible dates and sitemap lastmods for ANS-CNT-103 priority pages.

Run after page builders: python -m etl.pages.page_dates. Bootstrap once with
--seed (read-only, full git history); --force-seed explicitly permits reseeding.
Only main content and declared runtime data participate in hashes. JavaScript,
CSS, navigation, election banners and the date stamps are not data dependencies.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Literal
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
SITE = "https://firststatelens.com"
EASTERN = ZoneInfo("America/New_York")
START = "<!-- page-date -->"
END = "<!-- /page-date -->"
VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
MONTHS = "January February March April May June July August September October November December".split()


class PageDateError(ValueError):
    """Invalid input; nothing should be written."""


class UnavailableHistory(PageDateError):
    """A historical snapshot predates a required file or content region."""


@dataclass(frozen=True)
class PageSpec:
    file: str
    region: Literal["main", "header-footer"] = "main"
    data: tuple[str, ...] = ()
    volatile: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    insert_after: str = "</h1>"
    stamp_class: str = "section-meta"


# Explicit runtime files only; links to downloadable data and JSON-LD contentUrl
# citations are not fetches. No page loads a runtime-selected glob. Static builders
# already put their inputs into the HTML. A changed data period remains content.
REGISTRY: dict[str, PageSpec] = {
    "/": PageSpec("index.html", region="header-footer", stamp_class="card-tagline"),
    "/vote/": PageSpec("vote/index.html"),
    "/candidates/": PageSpec(
        "candidates/index.html", data=("candidates/data/ballot-2026.json",),
        volatile={"candidates/data/ballot-2026.json": ("generated_at",)},
    ),  # assets/ballot-lookup.js fetches the ballot; source.last_updated is data.
    "/my-delaware/": PageSpec("my-delaware/index.html"),  # #md-data is embedded.
    "/candidates/us-house/": PageSpec(
        "candidates/us-house/index.html", data=("candidates/data/us-house.json",),
        volatile={"candidates/data/us-house.json": ("generated_at",)},
    ),  # Candidate campaign_finance.as_of is a reporting date, not a run stamp.
    "/schools/": PageSpec(
        "schools/index.html", data=("schools/data/schools-summary.json",),
        volatile={"schools/data/schools-summary.json": ("generated_at",)},
    ),
    "/water/": PageSpec("water/index.html"),
    "/spending/": PageSpec(
        "spending/index.html", data=("spending/data/spending-summary.json",),
        volatile={"spending/data/spending-summary.json": ("generated_at",)},
    ),  # Contracts are embedded by the section builder, not fetched.
    "/federal/": PageSpec(
        "federal/index.html", data=("federal/data/federal-summary.json",),
        volatile={"federal/data/federal-summary.json": ("generated_at",)},
    ),
    "/childcare/": PageSpec(
        "childcare/index.html",
        data=("childcare/data/childcare-summary.json", "childcare/data/providers.geojson"),
        volatile={"childcare/data/childcare-summary.json": ("generated_at",)},
    ),  # providers.geojson has no run timestamps.
    "/votes/": PageSpec(
        "votes/index.html", data=("votes/data/votes-summary.json",),
        volatile={"votes/data/votes-summary.json": ("generated_at",)},
    ),
    "/campaign-finance/": PageSpec(
        "campaign-finance/index.html", data=("campaign-finance/data/campaign-finance-summary.json",),
        volatile={"campaign-finance/data/campaign-finance-summary.json": ("generated_at",)},
    ),
    "/reassessment/": PageSpec(
        "reassessment/index.html", data=("reassessment/data/kent-reassessment-summary.json",),
        volatile={"reassessment/data/kent-reassessment-summary.json": ("generated_at",)},
    ),
    "/inspections/": PageSpec("inspections/index.html", data=("inspections/data/search-index.json",)),
    "/offices/": PageSpec("offices/index.html"),
    "/road-safety/": PageSpec("road-safety/index.html"),
    "/dgi-food-access/": PageSpec(
        "dgi-food-access/index.html", region="header-footer",
        data=(
            "dgi-food-access/data/dart-routes.geojson",
            "dgi-food-access/data/datapackage.json",
            "dgi-food-access/data/manifest.json",
            "dgi-food-access/data/sb254-effective-tracts.geojson",
            "dgi-food-access/data/senate-district-2.geojson",
            "dgi-food-access/data/snap-retailers.geojson",
            "dgi-food-access/data/usda-lila-tracts.geojson",
        ),
        volatile={
            # write_datapackage.py creates these from the current ETL run.
            "dgi-food-access/data/datapackage.json": ("created", "sources.*.last_fetched"),
            "dgi-food-access/data/manifest.json": ("generated_at", "sources.*.last_fetched"),
        },
    ),
    "/bill-tracker/": PageSpec("bill-tracker/index.html"),
}

# Remote responses cannot be hashed from this checkout. Third-party executable
# libraries are recorded too, so the runtime inventory covers every script src.
RUNTIME_ONLY_SOURCES: dict[str, dict[str, str]] = {
    "/candidates/": {"/api/districts": "Worker resolves the submitted address or ZIP at runtime."},
    "/my-delaware/": {"/api/districts": "Worker resolves the submitted address or ZIP at runtime."},
    "/childcare/": {
        "https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.min.js": "Third-party map library; no local response blob.",
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png": "CARTO basemap tiles selected by viewport at runtime.",
    },
    "/dgi-food-access/": {
        "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js": "Third-party chart library; no local response blob.",
        "https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.min.js": "Third-party map library; no local response blob.",
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png": "CARTO basemap tiles selected by viewport at runtime.",
        "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png": "CARTO basemap tiles selected by viewport at runtime.",
        "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png": "CARTO basemap tiles selected by viewport at runtime.",
    },
}


@dataclass
class Element:
    tag: str
    attrs: dict[str, str | None]
    start: int
    open_end: int
    close_start: int | None = None
    end: int | None = None


class SourceElements(HTMLParser):
    """Locate elements without serializing HTML or changing any source bytes."""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0] + [m.end() for m in re.finditer("\n", source)]
        self.elements: list[Element] = []
        self.stack: list[Element] = []
        self.closing_tags: list[tuple[str, int]] = []
        self.feed(source)
        self.close()

    def source_offset(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        start = self.source_offset()
        element = Element(tag, dict(attrs), start, start + len(self.get_starttag_text()))
        self.elements.append(element)
        if tag in VOID:
            element.close_start = element.end = element.open_end
        else:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            element = self.stack.pop()
            element.close_start = element.end = element.open_end

    def handle_endtag(self, tag: str) -> None:
        self.closing_tags.append((tag, self.source.index(">", self.source_offset()) + 1))
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                element = self.stack[i]
                element.close_start = self.source_offset()
                element.end = self.source.index(">", element.close_start) + 1
                del self.stack[i:]
                break


def stamp_bounds(source: str, file: str) -> tuple[int, int] | None:
    starts, ends = source.count(START), source.count(END)
    if starts == ends == 0:
        return None
    if starts != 1 or ends != 1 or source.index(START) > source.index(END):
        raise PageDateError(f"{file}: missing, duplicated or reversed page-date markers ({starts}/{ends})")
    return source.index(START), source.index(END) + len(END)


def remove_stamp(source: str, file: str) -> str:
    bounds = stamp_bounds(source, file)
    return source if bounds is None else source[:bounds[0]] + source[bounds[1]:]


def unique_element(parser: SourceElements, tag: str, file: str) -> Element:
    elements = [element for element in parser.elements if element.tag == tag]
    if len(elements) != 1 or elements[0].end is None:
        raise UnavailableHistory(f"{file}: expected one complete <{tag}> content region/anchor; found {len(elements)}")
    return elements[0]


def canonical_page(source: str, spec: PageSpec) -> str:
    source = remove_stamp(source, spec.file)
    parser = SourceElements(source)
    if spec.region == "main":
        element = unique_element(parser, "main", spec.file)
        start, end = element.start, element.end
    elif spec.region == "header-footer":
        headers = [end for tag, end in parser.closing_tags if tag == "header"]
        footers = [element.start for element in parser.elements if element.tag == "footer"]
        if len(headers) != 1 or len(footers) != 1:
            raise UnavailableHistory(
                f"{spec.file}: expected one </header> and one <footer> region anchor; "
                f"found {len(headers)} and {len(footers)}"
            )
        start, end = headers[0], footers[0]
    else:
        raise PageDateError(f"{spec.file}: unsupported content region {spec.region!r}")
    if start is None or end is None or start >= end:
        raise UnavailableHistory(f"{spec.file}: missing or reversed content region anchors")
    removals: list[tuple[int, int]] = []
    for element in parser.elements:
        if start <= element.start < end and (element.tag == "nav" or "data-election-banner" in element.attrs):
            if element.end is None or element.end > end:
                raise PageDateError(f"{spec.file}: unclosed or out-of-region <{element.tag}> exclusion")
            removals.append((element.start, element.end))
    pieces: list[str] = []
    cursor = start
    for left, right in sorted(removals):
        if left >= cursor:
            pieces.append(source[cursor:left])
        cursor = max(cursor, right)
    pieces.append(source[cursor:end])
    return "".join(pieces)


def delete_volatile(value: object, parts: list[str], file: str, pointer: str) -> None:
    key, *rest = parts
    if key == "*":
        children = list(value.values()) if isinstance(value, dict) else value if isinstance(value, list) else []
        if not children or not rest:
            raise PageDateError(f"{file}: volatile key {pointer!r} has no matching children")
        for child in children:
            delete_volatile(child, rest, file, pointer)
    elif isinstance(value, dict) and key in value:
        if rest:
            delete_volatile(value[key], rest, file, pointer)
        else:
            del value[key]
    else:
        raise PageDateError(f"{file}: declared volatile key {pointer!r} is absent")


def canonical_data(raw: bytes, file: str, volatile: tuple[str, ...]) -> bytes:
    if Path(file).suffix.lower() in {".json", ".geojson"}:
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise PageDateError(f"{file}: JSON parse error: {exc}") from exc
        for pointer in volatile:
            delete_volatile(value, pointer.split("."), file, pointer)
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if volatile:
        raise PageDateError(f"{file}: volatile keys require JSON; no volatile CSV columns are declared")
    return raw.replace(b"\r\n", b"\n") if Path(file).suffix.lower() == ".csv" else raw


def decode_page(raw: bytes, file: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeError as exc:
        raise PageDateError(f"{file}: invalid UTF-8: {exc}") from exc


def read_file(root: Path, file: str) -> bytes:
    try:
        return (root / file).read_bytes()
    except FileNotFoundError as exc:
        raise UnavailableHistory(f"{file}: missing declared file") from exc
    except OSError as exc:
        raise PageDateError(f"{file}: {exc}") from exc


def hash_snapshot(spec: PageSpec, read: Callable[[str], bytes]) -> str:
    unknown = set(spec.volatile) - set(spec.data)
    if unknown:
        raise PageDateError(f"{spec.file}: volatile declarations for undeclared files: {sorted(unknown)}")
    digest = hashlib.sha256(canonical_page(decode_page(read(spec.file), spec.file), spec).encode("utf-8"))
    for file in sorted(spec.data):
        digest.update(file.encode("utf-8"))
        digest.update(canonical_data(read(file), file, spec.volatile.get(file, ())))
    return digest.hexdigest()


def canonical_hash(root: Path, spec: PageSpec) -> str:
    return hash_snapshot(spec, lambda file: read_file(root, file))


def eastern_today() -> date:
    return datetime.now(EASTERN).date()


def checked_date(value: str, path: str, today: date) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise PageDateError(f"{path}: invalid stored date {value!r}") from exc
    if parsed.isoformat() != value:
        raise PageDateError(f"{path}: stored date must be YYYY-MM-DD: {value!r}")
    if parsed > today:
        raise PageDateError(f"{path}: stored date {value} is in the future (ET today {today})")
    return parsed


def load_dates(root: Path, registry: Mapping[str, PageSpec], today: date) -> dict[str, dict[str, str]]:
    file = root / "page-dates.json"
    if not file.exists():
        return {}
    try:
        stored = json.loads(file.read_bytes())
    except (OSError, ValueError) as exc:
        raise PageDateError(f"page-dates.json: {exc}") from exc
    if not isinstance(stored, dict) or set(stored) - set(registry):
        raise PageDateError("page-dates.json: expected only registered page paths")
    for path, entry in stored.items():
        if not isinstance(entry, dict) or set(entry) != {"date", "hash"}:
            raise PageDateError(f"page-dates.json {path}: expected date and hash")
        checked_date(entry["date"], path, today)
        if not isinstance(entry["hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["hash"]):
            raise PageDateError(f"page-dates.json {path}: invalid SHA-256 hash")
    return stored


def render_stamp(source: str, spec: PageSpec, stored_date: str) -> str:
    parsed = date.fromisoformat(stored_date)
    label = f"{MONTHS[parsed.month - 1]} {parsed.day}, {parsed.year}"
    inner = f'<p class="{spec.stamp_class}">Updated <time datetime="{stored_date}">{label}</time></p>'
    bounds = stamp_bounds(source, spec.file)
    if bounds is not None:
        return source[:bounds[0] + len(START)] + inner + source[bounds[1] - len(END):]
    position = source.find(spec.insert_after)
    if position < 0:
        raise PageDateError(f"{spec.file}: missing stamp insertion anchor {spec.insert_after!r}")
    position += len(spec.insert_after)
    return source[:position] + START + inner + END + source[position:]


def render_sitemap(source: str, dates: Mapping[str, Mapping[str, str]]) -> str:
    try:
        document = ET.fromstring(source)
    except ET.ParseError as exc:
        raise PageDateError(f"sitemap.xml: invalid XML: {exc}") from exc
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    for path in dates:
        nodes = [node for node in document.findall("s:url", ns) if node.findtext("s:loc", namespaces=ns) == SITE + path]
        if len(nodes) != 1 or len(nodes[0].findall("s:lastmod", ns)) != 1:
            raise PageDateError(f"sitemap.xml {path}: expected one priority URL with one lastmod; found {len(nodes)} URLs")
    counts: dict[str, int] = {path: 0 for path in dates}

    def replace_url(match: re.Match[str]) -> str:
        block = match[0]
        loc = re.search(r"<loc>\s*([^<]+?)\s*</loc>", block)
        if loc is None or not loc[1].startswith(SITE):
            return block
        path = loc[1][len(SITE):]
        if path not in dates:
            return block
        counts[path] += 1
        return re.sub(r"(<lastmod>)[^<]*(</lastmod>)", lambda m: m[1] + dates[path]["date"] + m[2], block)

    # Keep comments opaque: a commented-out URL is not an entry.
    rendered = re.sub(r"<!--[\s\S]*?-->|<url\b[^>]*>[\s\S]*?</url>",
                      lambda m: m[0] if m[0].startswith("<!--") else replace_url(m), source)
    for path, count in counts.items():
        if count != 1:
            raise PageDateError(f"sitemap.xml {path}: cannot safely locate URL source for lastmod replacement")
    return rendered


def render_outputs(root: Path, registry: Mapping[str, PageSpec], dates: dict[str, dict[str, str]]) -> dict[Path, bytes]:
    outputs = {root / "page-dates.json": (json.dumps(dates, sort_keys=True, indent=2) + "\n").encode("utf-8")}
    for path, spec in registry.items():
        source = decode_page(read_file(root, spec.file), spec.file)
        outputs[root / spec.file] = render_stamp(source, spec, dates[path]["date"]).encode("utf-8")
    sitemap = decode_page(read_file(root, "sitemap.xml"), "sitemap.xml")
    outputs[root / "sitemap.xml"] = render_sitemap(sitemap, dates).encode("utf-8")
    return outputs


def plan_updates(root: Path = ROOT, registry: Mapping[str, PageSpec] = REGISTRY, today: date | None = None) -> dict[Path, bytes]:
    """Validate every input and compute every output, without writing anything."""
    today = today if today is not None else eastern_today()
    dates = load_dates(root, registry, today)
    for path, spec in registry.items():
        current = canonical_hash(root, spec)
        if path not in dates or dates[path]["hash"] != current:
            dates[path] = {"date": today.isoformat(), "hash": current}
    return render_outputs(root, registry, dates)


def write_outputs(outputs: Mapping[Path, bytes]) -> int:
    changed = 0
    for file, content in outputs.items():
        if not file.exists() or file.read_bytes() != content:
            file.write_bytes(content)
            changed += 1
    return changed


def run(root: Path = ROOT, registry: Mapping[str, PageSpec] = REGISTRY, today: date | None = None) -> int:
    return write_outputs(plan_updates(root, registry, today))


def git_read(root: Path, args: list[str], data: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(["git", *args], cwd=root, input=data, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        detail = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise PageDateError(f"{root}: git {' '.join(args)} failed: {detail}") from exc
    return result.stdout


class HistoryBlobs:
    """Batch-resolve snapshots and read each distinct blob only once per page."""

    def __init__(self, root: Path, commits: list[str], files: tuple[str, ...]) -> None:
        requests = [f"{commit}:{file}" for commit in commits for file in files]
        response = git_read(root, ["cat-file", "--batch-check"], ("\n".join(requests) + "\n").encode()).decode().splitlines()
        if len(response) != len(requests):
            raise PageDateError("git cat-file --batch-check: incomplete snapshot response")
        self.references: dict[str, str | None] = {}
        sizes: dict[str, int] = {}
        for request, line in zip(requests, response):
            if line == request + " missing":
                self.references[request] = None
                continue
            fields = line.split()
            if len(fields) != 3 or fields[1] != "blob" or not fields[2].isdigit():
                raise PageDateError(f"{request}: expected git blob, received {line!r}")
            self.references[request] = fields[0]
            sizes[fields[0]] = int(fields[2])
        self.blobs: dict[str, bytes] = {}
        if sizes:
            raw = git_read(root, ["cat-file", "--batch"], ("\n".join(sizes) + "\n").encode())
            offset = 0
            for oid, size in sizes.items():
                end = raw.find(b"\n", offset)
                if raw[offset:end] != f"{oid} blob {size}".encode():
                    raise PageDateError(f"git cat-file --batch: invalid header for {oid}")
                offset = end + 1
                self.blobs[oid] = raw[offset:offset + size]
                offset += size
                if raw[offset:offset + 1] != b"\n":
                    raise PageDateError(f"git cat-file --batch: truncated blob {oid}")
                offset += 1
            if offset != len(raw):
                raise PageDateError("git cat-file --batch: unexpected trailing response")

    def read(self, commit: str, file: str) -> bytes:
        oid = self.references[f"{commit}:{file}"]
        if oid is None:
            raise UnavailableHistory(f"{commit}:{file}: missing declared historical file")
        return self.blobs[oid]


def historical_hash(spec: PageSpec, blobs: HistoryBlobs, commit: str) -> str | None:
    try:
        return hash_snapshot(spec, lambda file: blobs.read(commit, file))
    except UnavailableHistory:
        return None
    except PageDateError as exc:
        raise PageDateError(f"{commit} {spec.file}: {exc}") from exc


def seed(root: Path = ROOT, registry: Mapping[str, PageSpec] = REGISTRY,
         today: date | None = None, force: bool = False) -> tuple[int, list[str]]:
    today = today if today is not None else eastern_today()
    if (root / "page-dates.json").exists() and not force:
        raise PageDateError("page-dates.json already exists; use --force-seed to replace it")
    # Future dates fail even with --force-seed; do not silently repair bad state.
    load_dates(root, registry, today)
    if git_read(root, ["rev-parse", "--is-shallow-repository"]).strip() == b"true":
        raise PageDateError("--seed requires full git history; this repository is shallow")
    head = git_read(root, ["rev-parse", "HEAD"]).decode().strip()
    metadata: dict[str, tuple[date, str]] = {}
    for line in git_read(root, ["log", "--format=%H%x00%cI%x00%s", "HEAD"]).decode().splitlines():
        sha, timestamp, subject = line.split("\0", 2)
        metadata[sha] = (datetime.fromisoformat(timestamp).astimezone(EASTERN).date(), subject)
    dates: dict[str, dict[str, str]] = {}
    table = ["| Path | Seed date (ET) | Content-setting commit |", "| --- | --- | --- |"]
    for path, spec in registry.items():
        current = canonical_hash(root, spec)
        files = (spec.file, *sorted(spec.data))
        commits = git_read(root, ["rev-list", "--full-history", "--reverse", "--topo-order", "HEAD", "--", *files]).decode().splitlines()
        snapshots = list(dict.fromkeys([*commits, head]))
        blobs = HistoryBlobs(root, snapshots, files)
        previous: str | None = None
        setting_commit: str | None = None
        for commit in commits:
            value = historical_hash(spec, blobs, commit)
            if value != previous:
                setting_commit = commit if value is not None else None
            previous = value
        head_hash = historical_hash(spec, blobs, head)
        if current != head_hash:
            seeded_date = today
            reason = f"WORKTREE: uncommitted content differs from HEAD {head[:8]}"
        elif setting_commit is not None:
            seeded_date, subject = metadata[setting_commit]
            reason = f"{setting_commit[:8]} {subject}"
        else:
            raise PageDateError(f"{path}: no available content-setting commit in full history")
        checked_date(seeded_date.isoformat(), path, today)
        dates[path] = {"date": seeded_date.isoformat(), "hash": current}
        table.append(f"| {path} | {seeded_date} | {reason.replace('|', '/')} |")
    return write_outputs(render_outputs(root, registry, dates)), table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-outputs", action="store_true", help="List every writable file, one per line, without writing")
    parser.add_argument("--seed", action="store_true", help="Replay full git history for initial content dates")
    parser.add_argument("--force-seed", action="store_true", help="Permit --seed to replace page-dates.json")
    args = parser.parse_args(argv)
    if args.list_outputs:
        if args.seed or args.force_seed:
            parser.error("--list-outputs cannot be combined with seed options")
        print("\n".join(["page-dates.json", "sitemap.xml", *(spec.file for spec in REGISTRY.values())]))
        return 0
    if args.force_seed and not args.seed:
        parser.error("--force-seed requires --seed")
    try:
        if args.seed:
            changed, table = seed(force=args.force_seed)
            print("\n".join(table))
        else:
            changed = run()
        print(f"page_dates: {changed} files changed")
    except (PageDateError, OSError) as exc:
        print(f"page_dates: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
