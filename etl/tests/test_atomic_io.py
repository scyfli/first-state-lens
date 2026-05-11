"""Smoke tests for etl.lib.atomic_io."""

from __future__ import annotations

from pathlib import Path

import pytest

from etl.lib.atomic_io import atomic_write_bytes, atomic_write_text


def test_atomic_write_bytes_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "subdir" / "out.bin"
    written = atomic_write_bytes(target, b"\x00\x01\x02\x03")
    assert written == target
    assert target.exists()
    assert target.read_bytes() == b"\x00\x01\x02\x03"


def test_atomic_write_text_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    payload = "hello,\nworld\n— ünîcôdé"
    atomic_write_text(target, payload)
    assert target.read_text(encoding="utf-8") == payload


def test_atomic_write_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "first")
    atomic_write_text(target, "second")
    assert target.read_text(encoding="utf-8") == "second"


def test_no_stale_tmp_files(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    atomic_write_bytes(target, b"x")
    siblings = list(tmp_path.iterdir())
    # Only the target should remain — no leftover .tmp files.
    assert siblings == [target], f"unexpected siblings: {siblings}"


def test_failed_write_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a write failure; verify no temp file is left behind."""
    target = tmp_path / "out.bin"

    # Force os.replace to fail so the success path isn't taken.
    import os

    original_replace = os.replace

    def failing_replace(*args, **kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(OSError):
        atomic_write_bytes(target, b"x")

    # No file at target, no leftover .tmp.
    assert not target.exists()
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftovers == [], f"leftover temp files: {leftovers}"

    # Restore monkeypatch automatically at fixture teardown.
    monkeypatch.setattr(os, "replace", original_replace)
