"""manifest.json builder — lightweight freshness cousin of datapackage.json.

The full Frictionless datapackage.json (written in S+3 by etl/outputs/)
is the authoritative public contract. The manifest is a smaller,
faster-to-read companion meant for:

  - Dashboard frontend "as of" date display
  - CI freshness assertions ("any source older than N days fails")
  - Cycle 5 status flag (pending vs published)

Schema:
{
  "generated_at": "<ISO8601 UTC>",
  "etl_version": "<semver>",
  "cycle_5_status": "pending" | "published",
  "sources": {
    "<source_name>": {
      "url": "<canonical URL>",
      "last_fetched": "<ISO8601 UTC>",
      "http_status": 200,
      "sha256": "<hex>",
      "raw_path": "etl/raw/<file>",
      "size_bytes": <int>,
      "warnings": []
    },
    ...
  }
}

S+1: builder + serializer + load-from-disk helper. The orchestrator wires
pullers' FetchResult instances into this at run end.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
from pathlib import Path
from typing import Optional

from .atomic_io import atomic_write_text
from .fetch import FetchResult


@dataclasses.dataclass
class SourceEntry:
    url: str
    last_fetched: str
    http_status: int
    sha256: str
    raw_path: str
    size_bytes: int
    warnings: list[str]

    @classmethod
    def from_fetch_result(
        cls, result: FetchResult, raw_path: str
    ) -> "SourceEntry":
        return cls(
            url=result.url,
            last_fetched=result.last_fetched,
            http_status=result.http_status,
            sha256=result.sha256,
            raw_path=raw_path,
            size_bytes=len(result.body),
            warnings=list(result.warnings),
        )


@dataclasses.dataclass
class Manifest:
    etl_version: str
    cycle_5_status: str = "pending"
    sources: dict[str, SourceEntry] = dataclasses.field(default_factory=dict)
    generated_at: Optional[str] = None

    def add_source(self, name: str, entry: SourceEntry) -> None:
        self.sources[name] = entry

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at or _utc_now_iso(),
            "etl_version": self.etl_version,
            "cycle_5_status": self.cycle_5_status,
            "sources": {
                name: dataclasses.asdict(entry)
                for name, entry in self.sources.items()
            },
        }

    def write(self, target: Path) -> Path:
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True)
        return atomic_write_text(target, payload + "\n")


def _utc_now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_manifest(path: Path) -> Manifest:
    """Load an existing manifest.json (used by freshness checks in CI)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    m = Manifest(
        etl_version=data.get("etl_version", "0.0.0"),
        cycle_5_status=data.get("cycle_5_status", "pending"),
        generated_at=data.get("generated_at"),
    )
    for name, entry in data.get("sources", {}).items():
        m.sources[name] = SourceEntry(**entry)
    return m
