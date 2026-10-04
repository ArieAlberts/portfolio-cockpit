"""Decision Engine — produces only a decision_state with reasons.

No broker coupling, no order types, no order fields. Driven by Quality
Drift; Fundamental Quality is context only, and only when DISPLAY_READY.
base_target_weight is read from config/portfolio.yaml and never changed.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from portfolio_cockpit.config import load_config

from .config import load_decision_config, missing_owner_inputs
from .io import (
    bundle_hash,
    canonical_json,
    git_head,
    read_current,
    sha256_file,
    sha256_json,
    update_current_pointer,
    write_immutable_snapshot,
)
from .risk import build_risk_report
from .warnings import contract_warnings, data_state, load_target_confidence


PIPELINE_VERSION = 1
OUTPUT_DIR = "data/decisions"
PREFIX = "decisions"
POINTER_KEY = "current_decisions"

ADD_CANDIDATE = "ADD_CANDIDATE"
HOLD = "HOLD"
NO_ADD = "NO_ADD"
REVIEW_REDUCE = "REVIEW_REDUCE"
THESIS_REVIEW = "THESIS_REVIEW"
DATA_CHECK = "DATA_CHECK"
DECISION_STATES = (ADD_CANDIDATE, HOLD, NO_ADD, REVIEW_REDUCE, THESIS_REVIEW, DATA_CHECK)

FORBIDDEN_OUTPUT_KEYS = frozenset({"side", "quantity", "limit_price", "order_id"})

CONFIG_FILES = (
    "config/decision.yaml",
    "config/risk_scenarios.yaml",
    "config/positions.yaml",
    "config/thesis_status.yaml",
    "config/portfolio.yaml",
)
CODE_FILES = (
    "src/portfolio_cockpit/decision_layer/decision.py",
    "src/portfolio_cockpit/decision_layer/risk.py",
    "src/portfolio_cockpit/decision_layer/warnings.py",
    "src/portfolio_cockpit/decision_layer/config.py",
    "src/portfolio_cockpit/decision_layer/io.py",
)


class DecisionInputError(ValueError):
    """Raised when the decision engine cannot run on the available inputs."""


@dataclass(frozen=True)
class DecisionInputs:
    ticker: str
    drift_score: float | None
    drift_change_recent: float | None
    drift_status: str | None
    valuation_score: float | None
    valuation_status: str | None
    data_confidence: float | None
    thesis_status: str
    portfolio_weight_pct: float
    base_target_weight_pct: float
    sector_weight_pct: float
    portfolio_impact_pp: float
    fq_status: str | None = None
    fq_score: float | None = None


@dataclass
class DecisionResult:
    ticker: str
    decision_state: str
    reasons: list[str] = field(default_factory=list)
    limit_flags: list[str] = field(default_factory=list)
    # Deliberately no order, side, quantity or limit_price fields.


def limit_flags(i: DecisionInputs, limits: dict[str, Any]) -> list[str]:
    flags = []
    if i.portfolio_weight_pct >= float(limits["max_position_weight_pct"]):
        flags.append(f"POSITION_LIMIT:{i.portfolio_weight_pct:g}%>={limits['max_position_weight_pct']:g}%")
    band = i.base_target_weight_pct * (1.0 + float(limits["overweight_tolerance"]))
    if i.portfolio_weight_pct >= band:
        flags.append(f"ABOVE_TARGET_BAND:{i.portfolio_weight_pct:g}%>={band:g}%")
    if i.sector_weight_pct >= float(limits["max_sector_weight_pct"]):
        flags.append(f"SECTOR_LIMIT:{i.sector_weight_pct:g}%>={limits['max_sector_weight_pct']:g}%")
    if abs(i.portfolio_impact_pp) > float(limits["max_single_position_impact_pp"]):
        flags.append(
            f"IMPACT_LIMIT:{abs(i.portfolio_impact_pp):g}pp>{limits['max_single_position_impact_pp']:g}pp"
        )
    return flags


def decide(i: DecisionInputs, cfg: dict[str, Any]) -> DecisionResult:
    """Decision tree from docs/HANDOFF_DECISION_LAYER.md step 6; thresholds from config."""
    drift_cfg, val_cfg = cfg["drift"], cfg["valuation"]
    if i.thesis_status not in cfg["thesis_status_values"]:
        raise DecisionInputError(f"{i.ticker}: unknown thesis_status {i.thesis_status!r}")

    fq_reasons: list[str] = []
    fq_ready = i.fq_status == "DISPLAY_READY" and i.fq_score is not None
    if not fq_ready:
        fq_reasons.append("FQ_NOT_DISPLAY_READY")

    state, data_reasons = data_state(
        data_confidence=i.data_confidence,
        threshold=float(cfg["data_confidence_min"]),
        drift_status=i.drift_status,
        valuation_status=i.valuation_status,
    )
    if state == DATA_CHECK:
        return DecisionResult(i.ticker, DATA_CHECK, data_reasons + fq_reasons)

    if i.thesis_status == "BROKEN":
        return DecisionResult(i.ticker, THESIS_REVIEW, ["THESIS_BROKEN"] + fq_reasons)

    assert i.drift_score is not None and i.valuation_score is not None
    deteriorated = []
    if i.drift_score <= float(drift_cfg["deteriorated_score_max"]):
        deteriorated.append(f"DRIFT_DETERIORATED:{i.drift_score:g}<={drift_cfg['deteriorated_score_max']:g}")
    if i.drift_change_recent is not None and i.drift_change_recent <= float(
        drift_cfg["deteriorated_recent_change_max"]
    ):
        deteriorated.append(
            f"DRIFT_RECENT_DROP:{i.drift_change_recent:g}<={drift_cfg['deteriorated_recent_change_max']:g}"
        )
    if deteriorated:
        return DecisionResult(i.ticker, REVIEW_REDUCE, deteriorated + fq_reasons)

    flags = limit_flags(i, cfg["limits"])
    if i.drift_score >= float(drift_cfg["strong_score_min"]) and i.valuation_score >= float(
        val_cfg["attractive_score_min"]
    ):
        reasons = [f"DRIFT_STRONG:{i.drift_score:g}", f"VALUATION_ATTRACTIVE:{i.valuation_score:g}"] + fq_reasons
        floor = float(cfg["fundamental_quality"]["fq_add_floor"])
        if fq_ready and i.fq_score < floor:
            return DecisionResult(i.ticker, HOLD, reasons + [f"FQ_BELOW_FLOOR:{i.fq_score:g}<{floor:g}"], flags)
        if flags:
            return DecisionResult(i.ticker, HOLD, reasons + ["ADD_BLOCKED_BY_LIMIT"], flags)
        return DecisionResult(i.ticker, ADD_CANDIDATE, reasons, flags)
    if i.drift_score >= float(drift_cfg["acceptable_score_min"]) and i.valuation_score < float(
        val_cfg["expensive_score_below"]
    ):
        return DecisionResult(
            i.ticker,
            NO_ADD,
            [f"DRIFT_ACCEPTABLE:{i.drift_score:g}", f"VALUATION_EXPENSIVE:{i.valuation_score:g}"] + fq_reasons,
            flags,
        )
    return DecisionResult(i.ticker, HOLD, ["NO_OTHER_TRIGGER"] + fq_reasons, flags)


# ---------------------------------------------------------------- pipeline


def _load_current(root: Path, rel_dir: str, key: str, cli: str) -> tuple[Path, dict[str, Any]]:
    found = read_current(root, root / rel_dir, key)
    if found is None:
        raise DecisionInputError(f"{rel_dir}/current.json is missing; run `{cli} --write` first")
    return found


def _fundamental_quality(root: Path) -> tuple[Path | None, dict[str, Any]]:
    pointer = root / "data/scoring/current.json"
    if not pointer.is_file():
        return None, {}
    current = json.loads(pointer.read_text(encoding="utf-8"))
    path = root / current["current_fundamental_quality"]
    return path, json.loads(path.read_text(encoding="utf-8"))


def _fq_for(snapshot: dict[str, Any], ticker: str) -> dict[str, Any]:
    if ticker in snapshot.get("scores", {}):
        item = snapshot["scores"][ticker]
        return {"status": item["status"], "score": item["fundamental_quality_score"], "diagnostic_score": None}
    item = snapshot.get("blocked", {}).get(ticker)
    if item is None:
        return {"status": None, "score": None, "diagnostic_score": None}
    diagnostic = (item.get("diagnostic_candidate") or {}).get("score")
    sensitivity = (item.get("diagnostic_candidate") or {}).get("sensitivity") or {}
    return {
        "status": item["status"],
        "score": None,
        "diagnostic_score": diagnostic,
        "diagnostic_band": (
            [sensitivity.get("score_low"), sensitivity.get("score_high")] if sensitivity else None
        ),
        "stability_flag": sensitivity.get("stability_flag"),
    }


def _assert_no_order_fields(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_OUTPUT_KEYS:
                raise AssertionError(f"order field {key!r} in decision output at {path or '/'}")
            _assert_no_order_fields(item, f"{path}/{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _assert_no_order_fields(item, f"{path}/{i}")


def build_decision_snapshot(
    *,
    root: Path,
    as_of: str | None = None,
    code_version: str | None = None,
) -> dict[str, Any]:
    repo_cfg = load_config(root)
    cfg = load_decision_config(root)
    missing = missing_owner_inputs(cfg)
    if missing["positions"] or missing["thesis_status"]:
        raise DecisionInputError(
            "owner inputs are incomplete; run `cockpit-check-inputs`. Missing: "
            + ", ".join(
                [f"positions.{m}" for m in missing["positions"]]
                + [f"thesis_status.{m}" for m in missing["thesis_status"]]
            )
        )
    as_of = as_of or datetime.now(timezone.utc).date().isoformat()
    decision_cfg = cfg["decision"]

    drift_path, drift = _load_current(root, "data/drift", "current_quality_drift", "cockpit-drift")
    valuation_path, valuation = _load_current(root, "data/valuation", "current_valuation", "cockpit-valuation")
    fq_path, fq_snapshot = _fundamental_quality(root)
    confidence_path, confidence = load_target_confidence(root)

    targets = {t: float(p["weight_pct"]) for t, p in repo_cfg["portfolio"]["positions"].items()}
    risk = build_risk_report(cfg, targets)
    thesis = cfg["thesis_status"]["positions"]

    results: dict[str, Any] = {}
    for ticker in repo_cfg["portfolio"]["positions"]:
        d = drift["results"].get(ticker) or {}
        v = valuation["results"].get(ticker) or {}
        c = confidence.get(ticker) or {}
        r = risk["positions"][ticker]
        fq = _fq_for(fq_snapshot, ticker)
        inputs = DecisionInputs(
            ticker=ticker,
            drift_score=d.get("drift_score"),
            drift_change_recent=d.get("drift_change_recent"),
            drift_status=d.get("status"),
            valuation_score=v.get("valuation_score"),
            valuation_status=v.get("status"),
            data_confidence=c.get("data_confidence"),
            thesis_status=thesis[ticker]["status"],
            portfolio_weight_pct=r["portfolio_weight_pct"],
            base_target_weight_pct=r["base_target_weight_pct"],
            sector_weight_pct=r["sector_weight_pct"],
            portfolio_impact_pp=r["portfolio_impact_pp"],
            fq_status=fq["status"],
            fq_score=fq["score"],
        )
        result = decide(inputs, decision_cfg)
        warnings = (
            contract_warnings("drift", d.get("warnings", []))
            + contract_warnings("valuation", v.get("warnings", []))
            + contract_warnings("confidence", c.get("raw_warnings", ["MISSING_DATA:confidence:no_target_confidence"]))
        )
        results[ticker] = {
            "decision_state": result.decision_state,
            "reasons": result.reasons,
            "limit_flags": result.limit_flags,
            "inputs": {
                "drift_score": inputs.drift_score,
                "drift_change_since_baseline": d.get("drift_change_since_baseline"),
                "drift_change_recent": inputs.drift_change_recent,
                "drift_status": inputs.drift_status,
                "last_fundamental_update": d.get("last_fundamental_update"),
                "valuation_score": inputs.valuation_score,
                "valuation_label": v.get("label"),
                "valuation_status": inputs.valuation_status,
                "price": v.get("price"),
                "currency": v.get("currency"),
                "price_as_of": v.get("price_as_of"),
                "data_confidence": inputs.data_confidence,
                "thesis_status": inputs.thesis_status,
                "thesis_as_of": str(thesis[ticker].get("as_of")),
                "thesis_note": thesis[ticker].get("note"),
                "portfolio_weight_pct": inputs.portfolio_weight_pct,
                "base_target_weight_pct": inputs.base_target_weight_pct,
                "sector": r["sector"],
                "sector_weight_pct": inputs.sector_weight_pct,
                "portfolio_impact_pp": inputs.portfolio_impact_pp,
                "fundamental_quality": fq,
            },
            "warnings": warnings,
            "execution_effect": "NONE",
        }

    sources = {
        "drift": {"path": drift_path.relative_to(root).as_posix(), "sha256": sha256_file(drift_path)},
        "valuation": {"path": valuation_path.relative_to(root).as_posix(), "sha256": sha256_file(valuation_path)},
        "fundamental_quality": (
            {"path": fq_path.relative_to(root).as_posix(), "sha256": sha256_file(fq_path)} if fq_path else None
        ),
        "target_confidence": (
            {"path": confidence_path.relative_to(root).as_posix(), "sha256": sha256_file(confidence_path)}
            if confidence_path
            else None
        ),
    }
    config_hash, config_hashes = bundle_hash(root, CONFIG_FILES)
    code_hash, code_hashes = bundle_hash(root, CODE_FILES)
    reproducibility_hash = sha256_json(
        {"as_of": as_of, "config_hash": config_hash, "code_hash": code_hash, "sources": sources}
    )
    states = [r["decision_state"] for r in results.values()]
    payload = {
        "schema_version": 1,
        "pipeline_version": PIPELINE_VERSION,
        "axis": "DECISION",
        "as_of": as_of,
        "reproducibility_hash": reproducibility_hash,
        "methodology": {
            "driver": "QUALITY_DRIFT",
            "fundamental_quality_role": "context only; floor applies only when DISPLAY_READY",
            "decision_states": list(DECISION_STATES),
            "thresholds": decision_cfg,
        },
        "provenance": {
            "run_git_commit": code_version or git_head(root),
            "code_hash": code_hash,
            "config_hash": config_hash,
            "code_files": code_hashes,
            "config_files": config_hashes,
            "sources": sources,
        },
        "summary": {"portfolio_companies": len(results), **{s: states.count(s) for s in DECISION_STATES}},
        "portfolio_risk": risk,
        "results": results,
        "execution_effect": "NONE",
    }
    _assert_no_order_fields(payload)
    return payload


def write_decision_snapshot(root: Path, payload: dict[str, Any]) -> Path:
    output_dir = root / OUTPUT_DIR
    path = write_immutable_snapshot(payload=payload, output_dir=output_dir, prefix=PREFIX)
    update_current_pointer(
        root=root, snapshot_path=path, payload=payload, output_dir=output_dir, pointer_key=POINTER_KEY
    )
    return path


def _repo_root_from_module() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build decision states from the current drift, valuation and scoring snapshots. "
            "Analytical only: never places, modifies or cancels orders."
        )
    )
    parser.add_argument("--root", type=Path, default=_repo_root_from_module())
    parser.add_argument("--as-of", help="ISO date; default is today (UTC)")
    parser.add_argument("--code-version")
    parser.add_argument(
        "--write",
        action="store_true",
        help="write an immutable revision to data/decisions/ and append data/signal_log/<as_of>.jsonl",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        payload = build_decision_snapshot(root=root, as_of=args.as_of, code_version=args.code_version)
    except DecisionInputError as exc:
        parser.exit(2, f"cockpit-decide: {exc}\n")
    if not args.write:
        print(canonical_json(payload), end="")
        return 0
    from .simulator import append_signal_log

    path = write_decision_snapshot(root, payload)
    print(path)
    print(append_signal_log(root, json.loads(path.read_text(encoding="utf-8")), path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
