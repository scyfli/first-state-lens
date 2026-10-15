"""Exercise publishing against disposable local Git repositories, without network."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from etl.pages import page_dates as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = "schools/data/schools-summary.json"


@dataclass
class Repositories:
    root: Path
    origin: Path
    job: Path
    other: Path
    env: dict[str, str]

    def run(self, cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        # Never allow a test command to write in the source checkout.
        assert cwd.resolve().is_relative_to(self.root.resolve())
        result = subprocess.run(args, cwd=cwd, env=self.env, capture_output=True,
                                text=True, timeout=60)
        if check:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    def git(self, cwd: Path, *args: str) -> str:
        return self.run(cwd, "git", *args).stdout.strip()

    def publish(self, *paths: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.run(self.job, "bash", "scripts/publish-refresh.sh",
                        "Refresh with literal $(touch injected) and `touch injected-too`",
                        *(paths or (DATA,)), check=check)

    def commit_other(self) -> str:
        self.run(self.other, "python", "-m", "etl.pages.page_dates")
        self.git(self.other, "add", ".")
        self.git(self.other, "commit", "-m", "Concurrent refresh")
        self.git(self.other, "push", "origin", "HEAD:main")
        return self.git(self.other, "rev-parse", "HEAD")

    def assert_origin_consistent(self) -> Path:
        fresh = self.root / "fresh"
        self.git(self.root, "clone", str(self.origin), str(fresh))
        result = self.run(fresh, "python", "-m", "etl.pages.page_dates")
        assert result.stdout == "page_dates: 0 files changed\n"
        assert self.git(fresh, "status", "--porcelain") == ""
        stored = json.loads((fresh / "page-dates.json").read_text())
        for url, spec in pd.REGISTRY.items():
            assert stored[url]["hash"] == pd.canonical_hash(fresh, spec)
        return fresh


@pytest.fixture
def repos(tmp_path: Path) -> Repositories:
    # Isolate identity/config and prohibit every transport except local files.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_") and key not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update({
        "GIT_AUTHOR_NAME": "Refresh Test", "GIT_COMMITTER_NAME": "Refresh Test",
        "GIT_AUTHOR_EMAIL": "refresh@example.test", "GIT_COMMITTER_EMAIL": "refresh@example.test",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ALLOW_PROTOCOL": "file", "GIT_TERMINAL_PROMPT": "0",
        "GIT_EDITOR": "true", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1",
    })
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python").symlink_to(sys.executable)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    r = Repositories(tmp_path, tmp_path / "origin.git", tmp_path / "job", tmp_path / "other", env)
    template = tmp_path / "empty-template"
    template.mkdir()
    r.git(tmp_path, "init", "--bare", "--initial-branch=main", f"--template={template}", str(r.origin))
    r.git(tmp_path, "clone", str(r.origin), str(r.job))
    shutil.copytree(ROOT / "etl", r.job / "etl",
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "raw"))
    outputs = r.run(r.job, "python", "-m", "etl.pages.page_dates", "--list-outputs").stdout.splitlines()
    files = {*outputs, *(file for spec in pd.REGISTRY.values() for file in spec.data),
             "scripts/publish-refresh.sh"}
    for file in sorted(files):
        target = r.job / file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / file, target)
    r.git(r.job, "add", ".")
    r.git(r.job, "commit", "-m", "Fixture baseline")
    r.git(r.job, "push", "origin", "HEAD:main")
    r.git(tmp_path, "clone", str(r.origin), str(r.other))
    return r


def change_enrollment(root: Path, increment: int, *, remote_note: bool = False) -> int:
    file = root / DATA
    data = json.loads(file.read_text())
    data["state"]["enrollment"] += increment
    if remote_note:
        # Far from enrollment, so this survives a textual conflict in that field.
        data["source_updated"]["publish_refresh_test"] = "concurrent change"
    file.write_text(json.dumps(data, indent=2) + "\n")
    return data["state"]["enrollment"]


def test_publish_rebases_conflict_and_recomputes_dates(repos: Repositories) -> None:
    change_enrollment(repos.other, 1, remote_note=True)
    upstream = repos.commit_other()
    expected = change_enrollment(repos.job, 2)
    before_rebase_hash = pd.canonical_hash(repos.job, pd.REGISTRY["/schools/"])

    result = repos.publish()

    assert result.stdout.count("rebasing onto origin/main") == 1
    assert "[rejected]" in result.stderr
    changes = re.findall(r"page_dates: (\d+) files changed", result.stdout)
    assert len(changes) == 2 and all(int(count) > 0 for count in changes)
    assert repos.git(repos.job, "rev-parse", "HEAD^") == upstream
    assert repos.git(repos.job, "status", "--porcelain") == ""
    assert not (repos.job / "injected").exists()
    assert not (repos.job / "injected-too").exists()
    fresh = repos.assert_origin_consistent()
    merged = json.loads((fresh / DATA).read_text())
    assert merged["state"]["enrollment"] == expected
    assert merged["source_updated"]["publish_refresh_test"] == "concurrent change"
    assert pd.canonical_hash(fresh, pd.REGISTRY["/schools/"]) != before_rebase_hash


def test_publish_no_changes_creates_no_commit(repos: Repositories) -> None:
    before = repos.git(repos.job, "rev-parse", "HEAD")
    result = repos.publish()
    assert result.stdout == "page_dates: 0 files changed\nNo changes.\n"
    assert result.stderr == ""
    assert repos.git(repos.job, "rev-parse", "HEAD") == before
    assert repos.git(repos.origin, "rev-parse", "main") == before


def test_publish_stages_page_outputs_and_paths_with_spaces(repos: Repositories) -> None:
    change_enrollment(repos.job, 1)
    extra = repos.job / "refresh note.txt"
    extra.write_text("Refresh output\n")
    # Stale stamps must be repaired and staged even outside the supplied paths.
    for file in ("schools/index.html", "sitemap.xml"):
        target = repos.job / file
        target.write_text(target.read_text().replace("2026-", "2025-"))
    result = repos.publish(DATA, extra.name)
    assert "rebasing" not in result.stdout
    fresh = repos.assert_origin_consistent()
    assert (fresh / extra.name).read_text() == "Refresh output\n"


def test_publish_page_date_failure_does_not_commit(repos: Repositories) -> None:
    before = repos.git(repos.job, "rev-parse", "HEAD")
    (repos.job / DATA).write_text("invalid JSON")
    result = repos.publish(check=False)
    assert result.returncode == 1
    assert "::error::Page dates failed; refusing to publish." in result.stderr
    assert repos.git(repos.job, "rev-parse", "HEAD") == before
    assert repos.git(repos.origin, "rev-parse", "main") == before
    assert repos.git(repos.job, "diff", "--cached", "--name-only") == ""


def test_publish_aborts_unresolved_rebase(repos: Repositories) -> None:
    # A modify/delete conflict is not resolved by the textual -X theirs strategy.
    repos.git(repos.other, "rm", DATA)
    repos.git(repos.other, "commit", "-m", "Remove data concurrently")
    repos.git(repos.other, "push", "origin", "HEAD:main")
    upstream = repos.git(repos.other, "rev-parse", "HEAD")
    change_enrollment(repos.job, 1)
    result = repos.publish(check=False)
    assert result.returncode == 1
    assert "::error::Rebase failed; aborted and refusing to publish." in result.stderr
    assert not (repos.job / ".git/rebase-merge").exists()
    assert not (repos.job / ".git/rebase-apply").exists()
    assert repos.git(repos.job, "status", "--porcelain") == ""
    assert repos.git(repos.origin, "rev-parse", "main") == upstream


def test_publish_stops_after_three_rejected_pushes(repos: Repositories) -> None:
    before = repos.git(repos.origin, "rev-parse", "main")
    hooks = repos.origin / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-receive"
    hook.write_text('#!/bin/sh\necho attempt >> "$GIT_DIR/rejected-attempts"\nexit 1\n')
    hook.chmod(0o755)
    change_enrollment(repos.job, 1)
    result = repos.publish(check=False)
    assert result.returncode == 1
    assert "::error::Publish failed after 3 push attempts." in result.stderr
    assert (repos.origin / "rejected-attempts").read_text().splitlines() == ["attempt"] * 3
    assert repos.git(repos.origin, "rev-parse", "main") == before
