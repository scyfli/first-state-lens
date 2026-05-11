"""Atomic file writes and last_fetched stamping.

The ETL runs unattended in CI. Partial writes from a killed run must not
poison a subsequent dashboard deploy. We always write to a temporary file
in the destination directory, then rename — rename is atomic on POSIX and
on Windows when source and destination live on the same volume.

Usage:
    from etl.lib.atomic_io import atomic_write_bytes, atomic_write_text

    atomic_write_bytes(Path("etl/raw/usda-lila.geojson"), payload)
    atomic_write_text(Path("etl/raw/mmg.csv"), csv_text)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Union


PathLike = Union[str, os.PathLike]


def atomic_write_bytes(target: PathLike, data: bytes) -> Path:
    """Write `data` to `target` atomically. Returns the target path."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Use the same directory as target so the rename stays on one filesystem.
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception:
        # Best-effort cleanup of the temp file on any failure.
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    return target


def atomic_write_text(
    target: PathLike, text: str, encoding: str = "utf-8"
) -> Path:
    """Write `text` to `target` atomically. Returns the target path."""
    return atomic_write_bytes(target, text.encode(encoding))
