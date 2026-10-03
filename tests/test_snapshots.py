from pathlib import Path

from portfolio_cockpit.monitoring.snapshots import (
    SnapshotConflictError,
    append_snapshot_index,
    create_immutable_snapshot,
)


def test_snapshot_is_immutable_and_chained(tmp_path: Path):
    root=tmp_path/"snapshots"
    first=create_immutable_snapshot(
        root=root,ticker="WKL",reporting_period="Q3_2026",
        observed_at="2026-10-03T12:00:00Z",
        normalized_fundamentals={"revenue":1},
        source_event_ids=["evt-1"],previous_snapshot_id=None,
    )
    same=create_immutable_snapshot(
        root=root,ticker="WKL",reporting_period="Q3_2026",
        observed_at="2026-10-03T12:00:00Z",
        normalized_fundamentals={"revenue":1},
        source_event_ids=["evt-1"],previous_snapshot_id=None,
    )
    assert first == same

    index=tmp_path/"index.json"
    append_snapshot_index(index,first,"WKL")
    text=index.read_text()
    assert first.snapshot_id in text
    assert '"WKL"' in text


def test_snapshot_has_no_execution_effect(tmp_path: Path):
    rec=create_immutable_snapshot(
        root=tmp_path,ticker="X",reporting_period="Q1",
        observed_at="2026-10-03T12:00:00Z",
        normalized_fundamentals={"x":1},
        source_event_ids=[],previous_snapshot_id=None,
    )
    content=Path(rec.path).read_text()
    assert '"execution_effect":"NONE"' in content
    assert '"score_update_allowed":false' in content
