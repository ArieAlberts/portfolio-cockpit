from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from .drift import (
    evaluate_quality_drift_update,
    load_quality_drift_config,
    profile_weights,
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _repo_root_from_module() -> Path:
    return Path(__file__).resolve().parents[3]


def _latest_confidence_path(root: Path) -> Path:
    candidates = sorted(
        p for p in (root / "data/confidence").glob("????-??-??.json")
        if p.is_file()
    )
    if not candidates:
        raise FileNotFoundError("No dated confidence snapshot found.")
    return candidates[-1]


def build_drift_snapshot(
    *,
    root: Path,
    signals_dir: Path | None = None,
) -> dict[str, Any]:
    config = load_quality_drift_config(root)
    baseline_index = _read_json(root / "data/baselines/index.json")
    portfolio_cfg = yaml.safe_load(
        (root / "config/portfolio.yaml").read_text(encoding="utf-8")
    )
    confidence_path = _latest_confidence_path(root)
    confidence = _read_json(confidence_path)
    signals_dir = signals_dir or root / "data/drift/signals"

    results: dict[str, Any] = {}
    for ticker, baseline_relative in baseline_index["baselines"].items():
        baseline_path = root / baseline_relative
        baseline = _read_json(baseline_path)
        company_type = portfolio_cfg["positions"][ticker]["company_type"]
        weights = profile_weights(config, company_type)
        signal_path = signals_dir / f"{ticker}.json"

        signal_payload: dict[str, Any] | None = None
        if signal_path.exists():
            signal_payload = _read_json(signal_path)
            if signal_payload.get("ticker") != ticker:
                raise ValueError(
                    f"{signal_path}: ticker mismatch "
                    f"{signal_payload.get('ticker')!r} != {ticker!r}"
                )

        if signal_payload is None:
            result = evaluate_quality_drift_update(
                component_signals={},
                component_weights=weights,
                trigger=None,
                source_validated=False,
                source_confidence_score=None,
                config=config,
            )
            item_as_of = confidence["as_of"]
            evidence = None
        else:
            result = evaluate_quality_drift_update(
                component_signals=signal_payload.get("component_signals", {}),
                component_weights=weights,
                trigger=signal_payload.get("trigger"),
                source_validated=bool(signal_payload.get("source_validated", False)),
                source_confidence_score=signal_payload.get("source_confidence_score"),
                config=config,
            )
            item_as_of = str(signal_payload.get("as_of") or confidence["as_of"])
            evidence = {
                "path": str(signal_path.relative_to(root)),
                "trigger": signal_payload.get("trigger"),
                "source_validated": bool(signal_payload.get("source_validated", False)),
                "source_confidence_score": signal_payload.get("source_confidence_score"),
            }

        results[ticker] = {
            "ticker": ticker,
            "company_type": company_type,
            "baseline_company_type": baseline.get("company_type"),
            "baseline_date": baseline["baseline_date"],
            "baseline_path": baseline_relative,
            "quality_drift_score": result.score,
            "weighted_signal": result.weighted_signal,
            "signal_coverage": result.signal_coverage,
            "status": result.status,
            "applied_components": list(result.applied_components),
            "warnings": list(result.warnings),
            "evidence": evidence,
            "target_data_confidence": confidence.get("results", {})
            .get(ticker, {})
            .get("data_confidence_score"),
            "execution_effect": "NONE",
            "as_of": item_as_of,
        }

    return {
        "schema_version": 1,
        "as_of": confidence["as_of"],
        "methodology": {
            "baseline_score": config["baseline_score"],
            "signal_range": [config["signal_min"], config["signal_max"]],
            "minimum_update_confidence": config["minimum_update_confidence"],
            "allowed_update_triggers": list(config["allowed_update_triggers"]),
            "price_changes_affect_score": False,
            "missing_components_are_neutral": True,
        },
        "summary": {
            "portfolio_companies": len(results),
            "baseline": sum(v["status"] == "BASELINE" for v in results.values()),
            "updated": sum(v["status"] == "UPDATED" for v in results.values()),
            "data_check": sum(v["status"] == "DATA_CHECK" for v in results.values()),
        },
        "results": results,
        "execution_effect": "NONE",
    }


def write_immutable_snapshot(
    *,
    root: Path,
    payload: dict[str, Any],
    output_dir: Path | None = None,
) -> Path:
    output_dir = output_dir or root / "data/drift"
    output_dir.mkdir(parents=True, exist_ok=True)
    body = _canonical_json(payload)
    base = output_dir / f"quality_drift_{payload['as_of']}.json"

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
            output_dir / f"quality_drift_{payload['as_of']}_r{revision}.json"
        )
        revision += 1


def update_current_pointer(*, root: Path, snapshot_path: Path) -> None:
    current = {
        "schema_version": 1,
        "as_of": json.loads(snapshot_path.read_text(encoding="utf-8"))["as_of"],
        "current_quality_drift": str(snapshot_path.relative_to(root)),
        "execution_effect": "NONE",
    }
    path = root / "data/drift/current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical_json(current), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build portfolio Quality Drift from immutable baselines and validated signals."
    )
    parser.add_argument("--root", type=Path, default=_repo_root_from_module())
    parser.add_argument("--signals-dir", type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    payload = build_drift_snapshot(root=args.root, signals_dir=args.signals_dir)
    if args.write:
        snapshot = write_immutable_snapshot(
            root=args.root,
            payload=payload,
            output_dir=args.output_dir,
        )
        update_current_pointer(root=args.root, snapshot_path=snapshot)
    print(_canonical_json(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
