"""ANS-CNT-103: dates describe content changes, not pipeline runs."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import pytest

from etl.pages import page_dates as pd

ROOT = Path(__file__).resolve().parents[2]
VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
MONTHS = "January February March April May June July August September October November December"
MONTH = "(?:" + "|".join(MONTHS.split()) + ")"
LABELLED_DATE = re.compile(
    r"(last updated|last reviewed|last modified|updated|reviewed|modified)( on)?\s*:?\s*"
    rf"({MONTH} \d{{1,2}}, \d{{4}}|\d{{1,2}} {MONTH} \d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})",
    re.I,
)


class VisibleBody(HTMLParser):
    """Independent port of the auditor: own-markup hiding removes a subtree."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        hidden = (
            tag in {"script", "style", "template", "svg", "noscript", "head"}
            or "hidden" in attributes
            or (attributes.get("aria-hidden") or "").lower() == "true"
            or bool(re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important\s*)?(?:;|$)", attributes.get("style") or "", re.I))
            or bool(self.stack and self.stack[-1][1])
        )
        if tag not in VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if any(tag == "body" for tag, _ in self.stack) and not self.stack[-1][1]:
            self.text.append(data)


def first_visible_date(html: str) -> str:
    parser = VisibleBody()
    parser.feed(html)
    text = re.sub(r"\s+", " ", " ".join(parser.text)).strip()
    match = LABELLED_DATE.search(text)
    if not match:
        raise ValueError("No visible labelled date")
    value = match[3]
    for fmt in ("%B %d, %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Invalid first labelled date: {value}")


def sitemap_dates(root: Path) -> dict[str, str]:
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    result: dict[str, str] = {}
    for node in ET.fromstring((root / "sitemap.xml").read_bytes()).findall("s:url", ns):
        loc = node.findtext("s:loc", namespaces=ns)
        assert loc is not None
        assert loc not in result, f"Duplicate sitemap URL: {loc}"
        result[loc] = node.findtext("s:lastmod", namespaces=ns) or ""
    return result


@pytest.fixture
def fixture_tree(tmp_path: Path) -> tuple[Path, dict[str, pd.PageSpec]]:
    (tmp_path / "sample").mkdir()
    (tmp_path / "sample/index.html").write_text(
        '<html><head><title>Fixture</title></head><body><header>Site</header>'
        '<main><h1>Sample</h1><nav>Old navigation</nav>'
        '<div data-election-banner><span>Old banner</span></div>'
        '<p>Real content</p></main><footer>Footer</footer></body></html>', encoding="utf-8"
    )
    (tmp_path / "sample/data.json").write_text(
        '{"value":1,"generated_at":"old","source":{"fetched_at":"old"},'
        '"rows":[{"run_at":"old","period":"2025"}]}', encoding="utf-8"
    )
    (tmp_path / "sitemap.xml").write_text(
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://firststatelens.com/sample/</loc><lastmod>2020-01-01</lastmod></url>'
        '<!-- Keep this comment --><url><loc>https://firststatelens.com/other/</loc>'
        '<lastmod>2020-01-01</lastmod></url></urlset>', encoding="utf-8"
    )
    registry = {"/sample/": pd.PageSpec(
        file="sample/index.html", data=("sample/data.json",),
        volatile={"sample/data.json": ("generated_at", "source.fetched_at", "rows.*.run_at")},
    )}
    pd.run(root=tmp_path, registry=registry, today=date(2026, 1, 2))
    return tmp_path, registry


def test_ans_cnt_103_committed_state_is_current() -> None:
    stored = json.loads((ROOT / "page-dates.json").read_bytes())
    assert len(stored) == len(pd.REGISTRY) == 18
    assert set(stored) == set(pd.REGISTRY)
    for path, spec in pd.REGISTRY.items():
        assert pd.canonical_hash(ROOT, spec) == stored[path]["hash"], path


def test_ans_cnt_103_first_visible_date_matches_sitemap_and_store() -> None:
    stored = json.loads((ROOT / "page-dates.json").read_bytes())
    sitemap = sitemap_dates(ROOT)
    for path, spec in pd.REGISTRY.items():
        assert first_visible_date((ROOT / spec.file).read_text()) == stored[path]["date"] == sitemap[pd.SITE + path], path


def test_ans_cnt_103_no_future_dates() -> None:
    today = datetime.now(ZoneInfo("America/New_York")).date()
    for path, entry in json.loads((ROOT / "page-dates.json").read_bytes()).items():
        assert date.fromisoformat(entry["date"]) <= today, path


@pytest.mark.parametrize("kind,moves", [
    ("data", True), ("volatile", False), ("stamp", False), ("banner", False),
    ("nav", False), ("main", True), ("outside", False), ("period", True),
])
def test_ans_cnt_103_only_content_changes_move_date(
    fixture_tree: tuple[Path, dict[str, pd.PageSpec]], kind: str, moves: bool,
) -> None:
    root, registry = fixture_tree
    page = root / "sample/index.html"
    data_file = root / "sample/data.json"
    if kind in {"data", "volatile", "period"}:
        data = json.loads(data_file.read_bytes())
        if kind == "data":
            data["value"] = 2
        elif kind == "volatile":
            data["generated_at"] = data["source"]["fetched_at"] = data["rows"][0]["run_at"] = "new"
        else:
            data["rows"][0]["period"] = "2026"
        data_file.write_text(json.dumps(data, indent=4))
    else:
        replacements = {
            "stamp": ("January 2, 2026", "January 1, 2020"),
            "banner": ("Old banner", "New banner"),
            "nav": ("Old navigation", "New navigation"),
            "main": ("Real content", "Changed content"),
            "outside": ("<header>Site</header>", "<header>New site</header>"),
        }
        old, new = replacements[kind]
        page.write_text(page.read_text().replace(old, new))
    pd.run(root=root, registry=registry, today=date(2026, 2, 3))
    expected = "2026-02-03" if moves else "2026-01-02"
    assert json.loads((root / "page-dates.json").read_bytes())["/sample/"]["date"] == expected
    assert first_visible_date(page.read_text()) == expected
    assert sitemap_dates(root)[pd.SITE + "/sample/"] == expected
    assert sitemap_dates(root)[pd.SITE + "/other/"] == "2020-01-01"


def test_ans_cnt_103_fixture_run_is_byte_idempotent(fixture_tree: tuple[Path, dict[str, pd.PageSpec]]) -> None:
    root, registry = fixture_tree
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
    assert pd.run(root=root, registry=registry, today=date(2026, 2, 3)) == 0
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}


def test_ans_cnt_103_real_run_would_change_no_bytes() -> None:
    for path, value in pd.plan_updates(root=ROOT).items():
        assert path.read_bytes() == value, path


@pytest.mark.parametrize("failure", ["data", "volatile", "marker", "duplicate-marker", "region", "json", "future", "missing-url", "duplicate-url"])
def test_ans_cnt_103_invalid_inputs_fail_before_any_write(
    fixture_tree: tuple[Path, dict[str, pd.PageSpec]], failure: str,
) -> None:
    root, registry = fixture_tree
    page = root / "sample/index.html"
    data_file = root / "sample/data.json"
    sitemap = root / "sitemap.xml"
    if failure == "data":
        data_file.unlink()
    elif failure == "volatile":
        data_file.write_text('{"value":1}')
    elif failure == "marker":
        page.write_text(page.read_text().replace("<!-- /page-date -->", ""))
    elif failure == "duplicate-marker":
        page.write_text(page.read_text() + "<!-- page-date -->")
    elif failure == "region":
        page.write_text(page.read_text().replace("<main>", "<section>").replace("</main>", "</section>"))
    elif failure == "json":
        data_file.write_text("{invalid")
    elif failure == "future":
        store = root / "page-dates.json"
        store.write_text(store.read_text().replace("2026-01-02", "2099-01-02"))
    elif failure == "missing-url":
        sitemap.write_text(sitemap.read_text().replace("/sample/", "/absent/"))
    else:
        sitemap.write_text(sitemap.read_text().replace("/other/", "/sample/"))
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(pd.PageDateError, match=r"sample|sitemap"):
        pd.run(root=root, registry=registry, today=date(2026, 2, 3))
    assert before == {p: p.read_bytes() for p in before}


@pytest.mark.parametrize("prefix", [
    '<div hidden>Updated January 1, 2000</div>',
    '<span aria-hidden="true">Updated January 1, 2000</span>',
    '<script>Updated January 1, 2000</script>',
    '<!-- Updated January 1, 2000 -->',
    '<style>Updated January 1, 2000</style><template>Updated January 1, 2000</template>',
    '<svg><text>Updated January 1, 2000</text></svg><noscript>Updated January 1, 2000</noscript>',
    '<div style="display: none !important"><b>Updated January 1, 2000</b></div>',
    '<div style="VISIBILITY: hidden">Updated January 1, 2000</div>',
    '<input hidden><br aria-hidden="true"><img hidden/><hr style="display:none">',
    '<div hidden><input><br>Updated January 1, 2000</div><br>',
])
def test_ans_cnt_103_auditor_removes_hidden_subtrees_and_handles_voids(prefix: str) -> None:
    assert first_visible_date('<html><head>Updated January 1, 2000</head><body>' + prefix +
                              '<p>Updated <time>October 3, 2026</time></p></body></html>') == "2026-10-03"


@pytest.mark.parametrize("label", ["Last updated on: 3 October 2026", "REVIEWED 2026-10-03", "last modified: October 3, 2026"])
def test_ans_cnt_103_auditor_date_formats_and_first_match(label: str) -> None:
    assert first_visible_date(f"<body>{label}<p>Updated October 4, 2026</p></body>") == "2026-10-03"


def test_ans_cnt_103_stamp_is_pure_insertion_and_banner_void_does_not_swallow() -> None:
    source = '<body><header>Top</header><h1>Title</h1><input data-election-banner><p>Text</p><footer>End</footer></body>'
    spec = pd.PageSpec(file="index.html", region="header-footer")
    rendered = pd.render_stamp(source, spec, "2026-01-02")
    assert pd.remove_stamp(rendered, spec.file) == source
    assert pd.canonical_page(source, spec) == '<h1>Title</h1><p>Text</p>'
    assert pd.canonical_page(rendered, spec) == pd.canonical_page(source, spec)
    for broken in (source.replace('</header>', ''), source.replace('<footer>', ''), source.replace('</header>', '</header><header></header>')):
        with pytest.raises(pd.PageDateError, match="index.html"):
            pd.canonical_page(broken, spec)


class ScriptSources(HTMLParser):
    """Read executable scripts, ignoring JSON-LD citations and download links."""

    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []
        self.scripts: list[str] = []
        self.executable = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            attributes = dict(attrs)
            self.executable = attributes.get("type", "") not in {"application/ld+json", "application/json"}
            if attributes.get("src"):
                self.sources.append(attributes["src"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.executable = False

    def handle_data(self, data: str) -> None:
        if self.executable:
            self.scripts.append(data)


def loaded_sources(root: Path, path: str, file: str) -> tuple[set[str], set[str]]:
    parser = ScriptSources()
    parser.feed((root / file).read_text())
    local: set[str] = set()
    remote: set[str] = set()
    scripts = parser.scripts.copy()
    for source in parser.sources:
        if urlsplit(source).netloc:
            remote.add(source)
        elif source.endswith(".js"):
            scripts.append((root / urlsplit(urljoin(pd.SITE + path, source)).path.lstrip("/")).read_text())
        else:
            local.add(urlsplit(urljoin(pd.SITE + path, source)).path.lstrip("/"))
    for script in scripts:
        # Remove comments without consuming // inside quoted URLs.
        tokens = re.findall(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`[^`]*`|/\*[\s\S]*?\*/|//[^\n]*|[^/"'`]+|/''', script)
        code = "".join(token for token in tokens if not token.startswith(("//", "/*")))
        prefix = re.search(r'''\bconst\s+DATA\s*=\s*["']([^"']+)["']''', code)
        literals = re.findall(r'''["']([^"'\n]+\.(?:json|geojson|csv)(?:\?[^"']*)?)["']''', code)
        for value in literals:
            if prefix and "/" not in value:
                value = prefix[1] + value
            resolved = urljoin(pd.SITE + path, value)
            if urlsplit(resolved).netloc != urlsplit(pd.SITE).netloc or urlsplit(resolved).path.startswith("/api/"):
                remote.add(value)
            else:
                local.add(urlsplit(resolved).path.lstrip("/"))
        for expression in re.findall(r"\bfetch\(\s*([^,)]+)", code):
            direct = re.fullmatch(r'''["']([^"']+)["']''', expression.strip())
            if direct:
                value = direct[1]
                if value.startswith("/api/") or urlsplit(value).netloc:
                    remote.add(value)
                else:
                    local.add(urlsplit(urljoin(pd.SITE + path, value)).path.lstrip("/"))
            else:
                # These three wrappers have their literal callers audited above.
                assert expression.strip() in {"url", "path", "DATA + f"}, f"Unresolved fetch in {file}: {expression}"
                assert literals, f"No literal callers for fetch in {file}: {expression}"
        remote.update(re.findall(r'''["'](https://[^"']+/\{z\}/\{x\}/\{y\}\.png)["']''', code))
    return local, remote


@pytest.mark.parametrize("path", ["/", "/vote/", "/candidates/", "/my-delaware/", "/candidates/us-house/", "/schools/", "/water/", "/spending/", "/federal/", "/childcare/", "/votes/", "/campaign-finance/", "/reassessment/", "/inspections/", "/offices/", "/road-safety/", "/dgi-food-access/", "/bill-tracker/"])
def test_ans_cnt_103_dependency_completeness(path: str) -> None:
    spec = pd.REGISTRY[path]
    local, remote = loaded_sources(ROOT, path, spec.file)
    assert local == set(spec.data), (path, local.symmetric_difference(spec.data))
    assert remote == set(pd.RUNTIME_ONLY_SOURCES.get(path, {})), (path, remote)
    assert all(pd.RUNTIME_ONLY_SOURCES.get(path, {}).values())


def test_ans_cnt_103_dependency_scanner_detects_new_loads(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        '<script>const DATA="./data/"; fetch(DATA + f); getJSON("one.geojson");'
        'fetch("/api/districts"); fetch("https://example.com/data.json");</script>'
        '<script src="/loader.js"></script>'
    )
    (tmp_path / "loader.js").write_text('fetch("./two.csv")')
    local, remote = loaded_sources(tmp_path, "/", "index.html")
    assert local == {"data/one.geojson", "two.csv"}
    assert remote == {"/api/districts", "https://example.com/data.json"}


def install_git_history(
    monkeypatch: pytest.MonkeyPatch, snapshots: list[dict[str, bytes]],
) -> None:
    """Replay git's wire protocol at the subprocess boundary; never write git."""
    import hashlib
    import subprocess

    commits = [f"{i:040x}" for i in range(1, len(snapshots) + 1)]
    objects: dict[str, bytes] = {}
    refs: dict[str, str] = {}
    for commit, snapshot in zip(commits, snapshots):
        for path, raw in snapshot.items():
            oid = hashlib.sha1(raw).hexdigest()
            objects[oid] = raw
            refs[f"{commit}:{path}"] = oid

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert kwargs["timeout"] == 120 and kwargs["check"] is True
        assert args[0] == "git"
        command = args[1:]
        if command == ["rev-parse", "--is-shallow-repository"]:
            result = b"false\n"
        elif command == ["rev-parse", "HEAD"]:
            result = commits[-1].encode() + b"\n"
        elif command[0] == "log":
            result = "".join(f"{commit}\0{2026}-01-{i + 1:02d}T01:00:00+00:00\0change {i}\n" for i, commit in enumerate(commits, 1)).encode()
        elif command[0] == "rev-list":
            assert all(option in command for option in ["--full-history", "--reverse", "--topo-order"])
            result = ("\n".join(commits) + "\n").encode()
        elif command == ["cat-file", "--batch-check"]:
            data = kwargs["input"]
            assert isinstance(data, bytes)
            lines = []
            for request in data.decode().splitlines():
                oid = refs.get(request)
                lines.append(f"{oid} blob {len(objects[oid])}" if oid else request + " missing")
            result = ("\n".join(lines) + "\n").encode()
        elif command == ["cat-file", "--batch"]:
            data = kwargs["input"]
            assert isinstance(data, bytes)
            result = b"".join(f"{oid} blob {len(objects[oid])}\n".encode() + objects[oid] + b"\n" for oid in data.decode().splitlines())
        else:
            raise AssertionError(f"Unexpected git command: {command}")
        return subprocess.CompletedProcess(args, 0, result, b"")

    monkeypatch.setattr(pd.subprocess, "run", fake_run)


@pytest.mark.parametrize("working_change,reappear", [(False, False), (True, False), (False, True)])
def test_ans_cnt_103_seed_replays_content_history_in_eastern_time(
    fixture_tree: tuple[Path, dict[str, pd.PageSpec]], monkeypatch: pytest.MonkeyPatch,
    working_change: bool, reappear: bool,
) -> None:
    root, registry = fixture_tree
    files = ["sample/index.html", "sample/data.json"]
    first = {file: (root / file).read_bytes() for file in files}
    changed = {**first, "sample/data.json": first["sample/data.json"].replace(b'"value":1', b'"value":2')}
    volatile = {**changed, "sample/data.json": changed["sample/data.json"].replace(b'"old"', b'"new"')}
    excluded = {**volatile, "sample/index.html": volatile["sample/index.html"].replace(b"Old navigation", b"New navigation").replace(b"Old banner", b"New banner").replace(b"January 2, 2026", b"January 1, 2000")}
    snapshots = [
        {"sample/index.html": first["sample/index.html"]},  # Missing data.
        {**first, "sample/index.html": b"<html><body>No region yet</body></html>"},
        first, changed, volatile, excluded,
    ]
    if reappear:
        snapshots.extend([{}, excluded])
    for file in files:
        (root / file).write_bytes(excluded[file])
    if working_change:
        (root / files[0]).write_bytes(excluded[files[0]].replace(b"Real content", b"Working content"))
    (root / "page-dates.json").unlink()
    install_git_history(monkeypatch, snapshots)
    changed_count, table = pd.seed(root=root, registry=registry, today=date(2026, 2, 3))
    expected = "2026-02-03" if working_change else "2026-01-08" if reappear else "2026-01-04"
    assert changed_count == 3
    assert first_visible_date((root / files[0]).read_text()) == expected
    stored = json.loads((root / "page-dates.json").read_bytes())["/sample/"]
    assert stored["date"] == expected
    assert stored["hash"] == pd.canonical_hash(root, registry["/sample/"])
    assert "WORKTREE" in table[-1] if working_change else f"change {8 if reappear else 4}" in table[-1]
    assert pd.run(root=root, registry=registry, today=date(2026, 2, 3)) == 0
    with pytest.raises(pd.PageDateError, match="already exists"):
        pd.seed(root=root, registry=registry, today=date(2026, 2, 3))
    assert pd.seed(root=root, registry=registry, today=date(2026, 2, 3), force=True)[0] == 0


@pytest.mark.parametrize("kind", ["csv", "binary", "json-order", "nested-missing", "wildcard-missing"])
def test_ans_cnt_103_canonical_data_formats(kind: str) -> None:
    if kind == "csv":
        assert pd.canonical_data(b"a,b\r\n1,2\r\n", "data.csv", ()) == b"a,b\n1,2\n"
    elif kind == "binary":
        assert pd.canonical_data(b"\xff\r\n", "data.bin", ()) == b"\xff\r\n"
    elif kind == "json-order":
        assert pd.canonical_data('{"z":1,"a":"é"}'.encode(), "data.json", ()) == '{"a":"é","z":1}'.encode()
    else:
        raw = b'{"source":{}}' if kind == "nested-missing" else b'{"rows":[{"stamp":1},{}]}'
        key = "source.fetched_at" if kind == "nested-missing" else "rows.*.stamp"
        with pytest.raises(pd.PageDateError, match="data.json.*absent"):
            pd.canonical_data(raw, "data.json", (key,))


def test_ans_cnt_103_git_failure_and_timeout_are_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import subprocess

    def failure(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(128, ["git", "log"], stderr=b"broken history")

    monkeypatch.setattr(pd.subprocess, "run", failure)
    with pytest.raises(pd.PageDateError, match="git log failed: broken history"):
        pd.git_read(tmp_path, ["log"])

    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(["git", "log"], 120)

    monkeypatch.setattr(pd.subprocess, "run", timeout)
    with pytest.raises(pd.PageDateError, match="git log failed"):
        pd.git_read(tmp_path, ["log"])


def test_ans_cnt_103_fallback_requires_exactly_one_of_each_anchor() -> None:
    spec = pd.PageSpec("index.html", region="header-footer")
    source = '<header>Top</header><h1>Title</h1><footer>'
    assert pd.canonical_page(source, spec) == '<h1>Title</h1>'
    for invalid in (source.replace('</header>', '</header></header>'), source + '<footer>', source.replace('<footer>', '')):
        with pytest.raises(pd.PageDateError, match='index.html.*anchor'):
            pd.canonical_page(invalid, spec)


def test_ans_cnt_103_cli_forwards_force_seed(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fake_seed(*, force: bool = False) -> tuple[int, list[str]]:
        assert force is True
        return 0, ["seed table"]

    monkeypatch.setattr(pd, "seed", fake_seed)
    assert pd.main(["--seed", "--force-seed"]) == 0
    assert capsys.readouterr().out == "seed table\npage_dates: 0 files changed\n"


def test_ans_cnt_103_cli_lists_all_outputs_without_writing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def refuse_writes(*args: object, **kwargs: object) -> None:
        pytest.fail("--list-outputs must not write or seed")

    monkeypatch.setattr(pd, "run", refuse_writes)
    monkeypatch.setattr(pd, "seed", refuse_writes)
    assert pd.main(["--list-outputs"]) == 0
    files = capsys.readouterr().out.splitlines()
    assert len(files) == len(set(files)) == 20
    assert set(files) == {str(path.relative_to(ROOT)) for path in pd.plan_updates()}


@pytest.mark.parametrize("flags", [["--seed"], ["--force-seed"], ["--seed", "--force-seed"]])
def test_ans_cnt_103_list_outputs_rejects_seed_options(flags: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        pd.main(["--list-outputs", *flags])
    assert exc.value.code == 2
