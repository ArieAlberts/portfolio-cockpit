from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from .decision import DecisionInputs, evaluate_decision, load_decision_config
from .drift_pipeline import build_drift_snapshot


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


def _load_fundamental_quality(root: Path) -> dict[str, Any]:
    current_path = root / "data/scoring/current.json"
    if not current_path.exists():
        return {"scores": {}, "blocked": {}}
    current = _read_json(current_path)
    relative = current.get("current_fundamental_quality")
    if not relative:
        return {"scores": {}, "blocked": {}}
    return _read_json(root / relative)


def _load_optional_score_map(path: Path, key: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = _read_json(path)
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{path}: {key} must be a mapping")
    return value


def build_decision_snapshot(
    *,
    root: Path,
    valuation_path: Path | None = None,
    thesis_path: Path | None = None,
    signals_dir: Path | None = None,
) -> dict[str, Any]:
    config = load_decision_config(root)
    portfolio = yaml.safe_load(
        (root / "config/portfolio.yaml").read_text(encoding="utf-8")
    )
    confidence = _read_json(_latest_confidence_path(root))
    drift = build_drift_snapshot(root=root, signals_dir=signals_dir)
    fundamental = _load_fundamental_quality(root)

    valuation_path = valuation_path or root / "data/valuation/current.json"
    thesis_path = thesis_path or root / "data/thesis/current.json"
    valuations = _load_optional_score_map(valuation_path, "scores")
    theses = _load_optional_score_map(thesis_path, "states")

    decisions: dict[str, Any] = {}
    for ticker, position in portfolio["positions"].items():
        drift_item = drift["results"][ticker]
        fq_item = fundamental.get("scores", {}).get(ticker)
        blocked_fq = fundamental.get("blocked", {}).get(ticker)

        valuation_item = valuations.get(ticker, {})
        if isinstance(valuation_item, dict):
            valuation_score = valuation_item.get("valuation_score")
        else:
            valuation_score = valuation_item

        thesis_item = theses.get(ticker, {})
        if isinstance(thesis_item, dict):
            thesis_status = str(thesis_item.get("thesis_status", "UNKNOWN"))
        else:
            thesis_status = str(thesis_item or "UNKNOWN")

        data_confidence = confidence.get("results", {}).get(ticker, {}).get(
            "data_confidence_score"
        )
        fq_score = fq_item.get("fundamental_quality_score") if fq_item else None

        result = evaluate_decision(
            DecisionInputs(
                quality_drift_score=drift_item["quality_drift_score"],
                valuation_score=valuation_score,
                data_confidence_score=data_confidence,
                thesis_status=thesis_status,
                fundamental_quality_score=fq_score,
            ),
            config,
        )

        fq_status = (
            fq_item.get("status")
            if fq_item
            else blocked_fq.get("status")
            if blocked_fq
            else "PENDING"
        )

        decisions[ticker] = {
            "ticker": ticker,
            "company": position["company"],
            "role": position["role"],
            "company_type": position["company_type"],
            "decision_state": result.state,
            "reasons": list(result.reasons),
            "quality_drift_score": drift_item["quality_drift_score"],
            "quality_drift_status": drift_item["status"],
            "valuation_score": valuation_score,
            "fundamental_quality_score": fq_score,
            "fundamental_quality_status": fq_status,
            "data_confidence_score": data_confidence,
            "thesis_status": thesis_status,
            "execution_effect": result.execution_effect,
        }

    counts = {
        state: sum(item["decision_state"] == state for item in decisions.values())
        for state in config["states"]
    }

    return {
        "schema_version": 1,
        "as_of": confidence["as_of"],
        "summary": {
            "portfolio_companies": len(decisions),
            "state_counts": counts,
            "valuation_source_present": valuation_path.exists(),
            "thesis_source_present": thesis_path.exists(),
        },
        "decisions": decisions,
        "execution_effect": "NONE",
        "note": (
            "Decision-support only. No state can place, modify or cancel a live order."
        ),
    }


def write_immutable_snapshot(
    *,
    root: Path,
    payload: dict[str, Any],
    output_dir: Path | None = None,
) -> Path:
    output_dir = output_dir or root / "data/decision"
    output_dir.mkdir(parents=True, exist_ok=True)
    body = _canonical_json(payload)
    base = output_dir / f"decision_{payload['as_of']}.json"

    candidates = [base]
    revision = 2
    while True:
        path = candidates[-1]
        if not path.exists():
            path.write_text(body, encoding="utf-8")
            return path
        if path.read_text(encoding="utf-8") == body:
            return path
        candidates.append(output_dir / f"decision_{payload['as_of']}_r{revision}.json")
        revision += 1


def update_current_pointer(*, root: Path, snapshot_path: Path) -> None:
    current = {
        "schema_version": 1,
        "as_of": json.loads(snapshot_path.read_text(encoding="utf-8"))["as_of"],
        "current_decision": str(snapshot_path.relative_to(root)),
        "execution_effect": "NONE",
    }
    path = root / "data/decision/current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical_json(current), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build deterministic portfolio decision-support states."
    )
    parser.add_argument("--root", type=Path, default=_repo_root_from_module())
    parser.add_argument("--valuation", type=Path)
    parser.add_argument("--thesis", type=Path)
    parser.add_argument("--signals-dir", type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    payload = build_decision_snapshot(
        root=args.root,
        valuation_path=args.valuation,
        thesis_path=args.thesis,
        signals_dir=args.signals_dir,
    )
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
