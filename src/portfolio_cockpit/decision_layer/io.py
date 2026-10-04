"""Immutable snapshot writing for decision-layer outputs.

Same write-once pattern as ``scoring/pipeline.py`` (copied, not imported, so
that the Fundamental Quality hash scope stays untouched):

* ``<prefix>_<as_of>.json``, then ``_r2``, ``_r3`` ... — never overwritten;
* a snapshot with the same ``reproducibility_hash`` is reused, so a no-op
  rebuild writes nothing new and the pointer stays byte-stable.

Payload contract: top-level ``as_of``, ``pipeline_version``,
``reproducibility_hash`` and ``provenance`` with ``run_git_commit``,
``code_hash`` and ``config_hash``.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_json(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def bundle_hash(root: Path, relative_paths: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    hashes = {p: sha256_file(root / p) for p in relative_paths}
    return sha256_json(hashes), hashes


def git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "UNKNOWN"


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_immutable_snapshot(
    *,
    payload: dict[str, Any],
    output_dir: Path,
    prefix: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    as_of = payload["as_of"]
    body = canonical_json(payload)

    reproducibility_hash = payload.get("reproducibility_hash")
    if reproducibility_hash:
        for existing in sorted(output_dir.glob(f"{prefix}_{as_of}*.json")):
            try:
                existing_payload = json.loads(existing.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if existing_payload.get("reproducibility_hash") == reproducibility_hash:
                return existing

    candidates = [output_dir / f"{prefix}_{as_of}.json"]
    revision = 2
    while True:
        path = candidates[-1]
        if not path.exists():
            path.write_text(body, encoding="utf-8")
            return path
        if path.read_text(encoding="utf-8") == body:
            return path
        candidates.append(output_dir / f"{prefix}_{as_of}_r{revision}.json")
        revision += 1


def update_current_pointer(
    *,
    root: Path,
    snapshot_path: Path,
    payload: dict[str, Any],
    output_dir: Path,
    pointer_key: str,
    pointer_name: str = "current.json",
) -> Path:
    # Anchor pointer metadata to a reused snapshot rather than to the
    # current run, so no-op rebuilds stay byte-stable.
    snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    source = snapshot_payload if snapshot_payload.get("reproducibility_hash") else payload

    current = {
        "schema_version": 1,
        "as_of": source["as_of"],
        pointer_key: snapshot_path.resolve().relative_to(root.resolve()).as_posix(),
        "generated_by_pipeline": True,
        "pipeline_version": source["pipeline_version"],
        "run_git_commit": source["provenance"]["run_git_commit"],
        "code_hash": source["provenance"]["code_hash"],
        "config_hash": source["provenance"]["config_hash"],
        "reproducibility_hash": source.get("reproducibility_hash"),
        "execution_effect": "NONE",
    }
    path = output_dir / pointer_name
    path.write_text(canonical_json(current), encoding="utf-8")
    return path


def read_current(root: Path, output_dir: Path, pointer_key: str) -> tuple[Path, dict[str, Any]] | None:
    """Return (snapshot path, payload) referenced by ``current.json``, if any."""
    pointer = output_dir / "current.json"
    if not pointer.is_file():
        return None
    current = json.loads(pointer.read_text(encoding="utf-8"))
    path = root / current[pointer_key]
    return path, json.loads(path.read_text(encoding="utf-8"))
