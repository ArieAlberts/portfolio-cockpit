from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .anchors import evaluate_absolute_anchors, load_absolute_anchor_config


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _repo_root_from_module() -> Path:
    return Path(__file__).resolve().parents[3]


def build_absolute_anchor_snapshot(*, root: Path) -> dict[str, Any]:
    config = load_absolute_anchor_config(root)
    portfolio = yaml.safe_load(
        (root / "config/portfolio.yaml").read_text(encoding="utf-8")
    )
    baseline_index = _read_json(root / "data/baselines/index.json")

    results: dict[str, Any] = {}
    for ticker in portfolio["positions"]:
        baseline_relative = baseline_index["baselines"][ticker]
        baseline = _read_json(root / baseline_relative)
        result = evaluate_absolute_anchors(
            ticker=ticker,
            baseline=baseline,
            config=config,
        )
        item = asdict(result)
        item["metric_results"] = {
            metric["metric_name"]: metric
            for metric in item["metric_results"]
        }
        item["baseline_path"] = baseline_relative
        item["baseline_date"] = baseline["baseline_date"]
        results[ticker] = item

    assigned = [v for v in results.values() if v["status"] != "NOT_CONFIGURED"]
    return {
        "schema_version": 1,
        "as_of": baseline_index["generated_on"],
        "policy": dict(config["policy"]),
        "summary": {
            "portfolio_companies": len(results),
            "configured_companies": len(assigned),
            "anchors_met": sum(v["status"] == "ANCHORS_MET" for v in assigned),
            "anchor_miss": sum(v["status"] == "ANCHOR_MISS" for v in assigned),
            "data_check": sum(v["status"] == "DATA_CHECK" for v in assigned),
            "not_configured": sum(
                v["status"] == "NOT_CONFIGURED" for v in results.values()
            ),
        },
        "results": results,
        "execution_effect": "NONE",
        "note": (
            "Absolute anchors are diagnostic guardrails only. They do not alter "
            "Fundamental Quality, Decision Engine state or execution."
        ),
    }


def write_immutable_snapshot(
    *,
    root: Path,
    payload: dict[str, Any],
    output_dir: Path | None = None,
) -> Path:
    output_dir = output_dir or root / "data/anchors"
    output_dir.mkdir(parents=True, exist_ok=True)
    body = _canonical_json(payload)
    base = output_dir / f"absolute_anchors_{payload['as_of']}.json"
    candidates = [base]
    revision = 2
    while True:
        path = candidates[-1]
        if not path.exists():
            path.write_text(body, encoding="utf-8")
            return path
        if path.read_text(encoding="utf-8") == body:
            return path
        candidates.append(
            output_dir / f"absolute_anchors_{payload['as_of']}_r{revision}.json"
        )
        revision += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate configured absolute quality anchors without changing peer scores."
    )
    parser.add_argument("--root", type=Path, default=_repo_root_from_module())
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    payload = build_absolute_anchor_snapshot(root=args.root)
    if args.write:
        write_immutable_snapshot(
            root=args.root,
            payload=payload,
            output_dir=args.output_dir,
        )
    print(_canonical_json(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
