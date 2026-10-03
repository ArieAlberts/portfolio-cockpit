import json

from portfolio_cockpit.decision_layer.io import (
    read_current,
    update_current_pointer,
    write_immutable_snapshot,
)


def _payload(value, repro="r1", commit="abc"):
    return {
        "as_of": "2026-10-03",
        "pipeline_version": 1,
        "reproducibility_hash": repro,
        "provenance": {"run_git_commit": commit, "code_hash": "c", "config_hash": "k"},
        "value": value,
    }


def _write(root, payload):
    out = root / "data/drift"
    path = write_immutable_snapshot(payload=payload, output_dir=out, prefix="quality_drift")
    update_current_pointer(
        root=root, snapshot_path=path, payload=payload,
        output_dir=out, pointer_key="current_quality_drift",
    )
    return path


def test_first_write_and_pointer(tmp_path):
    path = _write(tmp_path, _payload(1))
    assert path.name == "quality_drift_2026-10-03.json"
    current = json.loads((tmp_path / "data/drift/current.json").read_text())
    assert current["current_quality_drift"] == "data/drift/quality_drift_2026-10-03.json"
    assert current["execution_effect"] == "NONE"
    _, payload = read_current(tmp_path, tmp_path / "data/drift", "current_quality_drift")
    assert payload["value"] == 1


def test_changed_payload_creates_revision_and_keeps_history(tmp_path):
    first = _write(tmp_path, _payload(1, repro="r1"))
    original = first.read_bytes()
    second = _write(tmp_path, _payload(2, repro="r2"))
    third = _write(tmp_path, _payload(3, repro="r3"))
    assert second.name == "quality_drift_2026-10-03_r2.json"
    assert third.name == "quality_drift_2026-10-03_r3.json"
    assert first.read_bytes() == original


def test_noop_rebuild_is_byte_stable(tmp_path):
    first = _write(tmp_path, _payload(1, repro="same", commit="abc"))
    pointer = (tmp_path / "data/drift/current.json").read_bytes()
    # A later run at another HEAD with identical inputs reuses the snapshot.
    again = _write(tmp_path, _payload(1, repro="same", commit="def"))
    assert again == first
    assert (tmp_path / "data/drift/current.json").read_bytes() == pointer
    assert sorted(p.name for p in (tmp_path / "data/drift").iterdir()) == [
        "current.json", "quality_drift_2026-10-03.json",
    ]


def test_read_current_without_pointer(tmp_path):
    assert read_current(tmp_path, tmp_path / "data/drift", "current_quality_drift") is None
