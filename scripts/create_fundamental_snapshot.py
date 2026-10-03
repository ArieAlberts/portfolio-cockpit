#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from portfolio_cockpit.monitoring.snapshots import append_snapshot_index, create_immutable_snapshot
from portfolio_cockpit.monitoring.peer_alignment import evaluate_peer_alignment


ROOT = Path(__file__).resolve().parents[1]


def _update_peer_alignment(ticker: str, reporting_period: str) -> None:
    peer_index_path = ROOT / "data/peers/index.json"
    alignment_path = ROOT / "data/monitoring/peer_alignment_status.json"
    peer_index = json.loads(peer_index_path.read_text(encoding="utf-8"))
    relative = peer_index.get("datasets", {}).get(ticker)
    peer_dataset = None
    if relative and (ROOT / relative).exists():
        peer_dataset = json.loads((ROOT / relative).read_text(encoding="utf-8"))

    result = evaluate_peer_alignment(
        target_reporting_period=reporting_period,
        peer_dataset=peer_dataset,
    )

    if alignment_path.exists():
        status = json.loads(alignment_path.read_text(encoding="utf-8"))
    else:
        status = {"schema_version": 1, "targets": {}}

    status["targets"][ticker] = {**result.__dict__, "execution_effect": "NONE"}
    alignment_path.parent.mkdir(parents=True, exist_ok=True)
    alignment_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an immutable validated fundamental snapshot.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--reporting-period", required=True)
    parser.add_argument("--observed-at", required=True, help="UTC ISO timestamp, e.g. 2026-10-03T14:00:00Z")
    parser.add_argument("--input", required=True, help="JSON file containing normalized_fundamentals")
    parser.add_argument("--source-event", action="append", default=[])
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    payload = json.loads(input_path.read_text(encoding="utf-8"))

    index_path = ROOT / "data/snapshots/index.json"
    previous = None
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        previous = index.get("latest", {}).get(args.ticker)

    record = create_immutable_snapshot(
        root=ROOT / "data/snapshots",
        ticker=args.ticker,
        reporting_period=args.reporting_period,
        observed_at=args.observed_at,
        normalized_fundamentals=payload,
        source_event_ids=args.source_event,
        previous_snapshot_id=previous,
    )
    append_snapshot_index(index_path, record, args.ticker)
    _update_peer_alignment(args.ticker, args.reporting_period)
    print(json.dumps(record.__dict__, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
