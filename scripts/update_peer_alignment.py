#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from portfolio_cockpit.monitoring.peer_alignment import evaluate_peer_alignment


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--reporting-period", required=True)
    parser.add_argument("--peer-index", default="data/peers/index.json")
    parser.add_argument("--status", default="data/monitoring/peer_alignment_status.json")
    args = parser.parse_args()

    index = json.loads((ROOT / args.peer_index).read_text(encoding="utf-8"))
    relative = index.get("datasets", {}).get(args.ticker)
    dataset = None
    if relative and (ROOT / relative).exists():
        dataset = json.loads((ROOT / relative).read_text(encoding="utf-8"))

    result = evaluate_peer_alignment(
        target_reporting_period=args.reporting_period,
        peer_dataset=dataset,
    )

    status_path = ROOT / args.status
    if status_path.exists():
        status = json.loads(status_path.read_text(encoding="utf-8"))
    else:
        status = {"schema_version": 1, "targets": {}}

    status["targets"][args.ticker] = {
        **result.__dict__,
        "execution_effect": "NONE",
    }
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status["targets"][args.ticker], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
