from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SnapshotConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotRecord:
    snapshot_id: str
    path: str
    content_sha256: str


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def create_immutable_snapshot(
    *,
    root: Path,
    ticker: str,
    reporting_period: str,
    observed_at: str,
    normalized_fundamentals: dict[str, Any],
    source_event_ids: list[str],
    previous_snapshot_id: str | None,
) -> SnapshotRecord:
    body = {
        "schema_version": 1,
        "ticker": ticker,
        "reporting_period": reporting_period,
        "observed_at": observed_at,
        "previous_snapshot_id": previous_snapshot_id,
        "source_event_ids": source_event_ids,
        "normalized_fundamentals": normalized_fundamentals,
        "score_update_allowed": False,
        "execution_effect": "NONE",
    }
    content = _canonical_bytes(body)
    sha = hashlib.sha256(content).hexdigest()
    stamp = observed_at.replace("-", "").replace(":", "").replace("Z", "Z")
    snapshot_id = f"{ticker}-{reporting_period}-{stamp}-{sha[:10]}"
    path = root / ticker / reporting_period / f"{snapshot_id}.json"

    if path.exists():
        if path.read_bytes() != content:
            raise SnapshotConflictError(f"Immutable snapshot conflict: {path}")
        return SnapshotRecord(snapshot_id=snapshot_id, path=str(path), content_sha256=sha)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return SnapshotRecord(snapshot_id=snapshot_id, path=str(path), content_sha256=sha)


def append_snapshot_index(index_path: Path, record: SnapshotRecord, ticker: str) -> None:
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = {"schema_version": 1, "latest": {}, "snapshots": {}}

    if record.snapshot_id in index["snapshots"]:
        existing = index["snapshots"][record.snapshot_id]
        if existing["content_sha256"] != record.content_sha256:
            raise SnapshotConflictError(f"Snapshot index conflict: {record.snapshot_id}")
        return

    index["snapshots"][record.snapshot_id] = {
        "ticker": ticker,
        "path": record.path,
        "content_sha256": record.content_sha256,
    }
    index["latest"][ticker] = record.snapshot_id
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
