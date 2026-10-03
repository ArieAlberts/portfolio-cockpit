#!/usr/bin/env python3
"""List every component.metric path in data/baselines/** per company_type.

Read-only helper used to build and audit config/quality_drift.yaml profiles.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def collect(root: Path) -> dict[str, dict[str, list[str]]]:
    index = json.loads((root / "data/baselines/index.json").read_text(encoding="utf-8"))
    result: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for ticker, rel in index["baselines"].items():
        baseline = json.loads((root / rel).read_text(encoding="utf-8"))
        for component, metrics in baseline.get("metrics", {}).items():
            for metric in metrics:
                result[baseline["company_type"]][f"{component}.{metric}"].append(ticker)
    return {ct: dict(paths) for ct, paths in result.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)
    data = collect(args.root.resolve())
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    for company_type in sorted(data):
        print(company_type)
        for path in sorted(data[company_type]):
            print(f"  {path}: {', '.join(sorted(data[company_type][path]))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
