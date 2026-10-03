"""Quality Drift engine: change versus each company's own immutable baseline.

drift = clamp(50 + 50 * sum(w_c * s_c) / sum(w_c available), 0, 100)

Exactly 50.0 at the baseline. This module deliberately has no access to
market data or valuation: a price move cannot change Quality Drift.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from portfolio_cockpit.config import load_config

from .config import load_decision_config
from .io import (
    bundle_hash,
    canonical_json,
    git_head,
    sha256_file,
    sha256_json,
    update_current_pointer,
    write_immutable_snapshot,
)


PIPELINE_VERSION = 1
OUTPUT_DIR = "data/drift"
PREFIX = "quality_drift"
POINTER_KEY = "current_quality_drift"

CONFIG_FILES = (
    "config/quality_drift.yaml",
    "config/portfolio.yaml",
    "config/company_types.yaml",
    "config/score_metrics.yaml",
)
CODE_FILES = (
    "src/portfolio_cockpit/decision_layer/drift.py",
    "src/portfolio_cockpit/decision_layer/config.py",
    "src/portfolio_cockpit/decision_layer/io.py",
)

STATUS_OK = "OK"
STATUS_NO_NEW = "NO_NEW_FUNDAMENTALS"
STATUS_DATA_CHECK = "DRIFT_DATA_CHECK"

OBSERVATION_METRIC_FIELDS = ("value", "period", "period_basis", "source", "retrieved_at")
OBSERVATION_SOURCE_FIELDS = ("source_type", "title", "publication_date")


class ObservationError(ValueError):
    """Raised when an observation file violates the observation contract."""


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return None


def normalize(
    *,
    baseline_value: float,
    raw_value: float,
    mode: str,
    direction: str,
    full_scale: float,
    dead_band: float,
) -> tuple[float, float]:
    """Return (delta, normalized_signal in [-1, 1])."""
    if mode == "relative":
        if baseline_value == 0:
            raise ZeroDivisionError("relative mode with a zero baseline")
        delta = (raw_value - baseline_value) / abs(baseline_value)
    else:
        delta = raw_value - baseline_value
    effective = 0.0 if abs(delta) <= dead_band else delta
    signal = clamp(effective / full_scale, -1.0, 1.0)
    if direction == "lower_is_better":
        signal = -signal
    return delta, signal + 0.0


def baseline_period_basis(drift_cfg: dict[str, Any], ticker: str, metric: str) -> str:
    period_cfg = drift_cfg["baseline_period_basis"]
    for pattern in period_cfg.get("metric_name_patterns") or []:
        if pattern["contains"] in metric:
            return pattern["basis"]
    return period_cfg["by_ticker"][ticker]


def _find_metric(
    metrics: dict[str, Any],
    sources: list[str],
    metric: str,
) -> tuple[str, Any] | None:
    for component in sources:
        values = metrics.get(component) or {}
        if metric in values:
            return component, values[metric]
    return None


# ---------------------------------------------------------------- observations


def validate_observation(payload: dict[str, Any], *, ticker: str, path: Path) -> None:
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if payload.get("ticker") != ticker:
        errors.append(f"ticker must be {ticker}")
    for key in ("observation_date", "reporting_period_end"):
        try:
            date.fromisoformat(str(payload.get(key)))
        except ValueError:
            errors.append(f"{key} must be an ISO date")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        errors.append("metrics must be a non-empty mapping of component -> metric")
        metrics = {}
    for component, items in metrics.items():
        if not isinstance(items, dict):
            errors.append(f"metrics.{component} must be a mapping")
            continue
        for metric, item in items.items():
            label = f"metrics.{component}.{metric}"
            if not isinstance(item, dict):
                errors.append(f"{label} must be a mapping with value and provenance")
                continue
            for key in OBSERVATION_METRIC_FIELDS:
                if item.get(key) in (None, ""):
                    errors.append(f"{label}.{key} is required")
            if _as_number(item.get("value")) is None:
                errors.append(f"{label}.value must be numeric or boolean")
            source = item.get("source") or {}
            for key in OBSERVATION_SOURCE_FIELDS:
                if not source.get(key):
                    errors.append(f"{label}.source.{key} is required")
    if errors:
        raise ObservationError(f"{path}: " + "; ".join(errors))


def load_observations(root: Path, ticker: str) -> list[tuple[Path, dict[str, Any]]]:
    """Observations for one ticker, oldest first (observation_date, file name)."""
    directory = root / "data/observations" / ticker
    if not directory.is_dir():
        return []
    loaded = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_observation(payload, ticker=ticker, path=path)
        loaded.append((path, payload))
    loaded.sort(key=lambda item: (str(item[1]["observation_date"]), item[0].name))
    return loaded


# ---------------------------------------------------------------- evaluation


@dataclass
class Evaluation:
    score: float
    status: str
    coverage: float | None
    profile_coverage: float
    components: dict[str, Any]
    metrics: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


def _measurable_slots(
    baseline: dict[str, Any],
    comp_cfg: dict[str, Any],
    component: str,
) -> list[tuple[str, dict[str, Any], str, str, float]]:
    sources = comp_cfg.get("source_components", [component])
    result = []
    for slot_name, slot in comp_cfg["slots"].items():
        for alias in slot["aliases"]:
            found = _find_metric(baseline["metrics"], sources, alias)
            if found is None:
                continue
            value = _as_number(found[1])
            if value is None:
                continue
            result.append((slot_name, slot, alias, found[0], value))
            break
    return result


def evaluate(
    *,
    ticker: str,
    profile: dict[str, Any],
    drift_cfg: dict[str, Any],
    baseline: dict[str, Any],
    baseline_rel: str,
    observation: dict[str, Any] | None,
    observation_rel: str | None,
    previous: dict[str, Any] | None,
) -> Evaluation:
    """Score one observation against the baseline. ``observation=None`` is the baseline itself."""
    neutral = float(drift_cfg["neutral_score"])
    min_slot_cov = float(drift_cfg["minimum_slot_weight_coverage"])
    min_comp_cov = float(drift_cfg["minimum_component_weight_coverage"])
    required = list(profile["required_components"])

    warnings: list[str] = []
    metrics_out: list[dict[str, Any]] = []
    components_out: dict[str, Any] = {}
    component_signals: dict[str, float] = {}
    measurable_weight = 0.0
    total_weight = sum(float(c["weight"]) for c in profile["components"].values())

    for component, comp_cfg in profile["components"].items():
        comp_weight = float(comp_cfg["weight"])
        sources = comp_cfg.get("source_components", [component])
        measurable = _measurable_slots(baseline, comp_cfg, component)
        if not measurable:
            components_out[component] = {"weight": comp_weight, "status": "NOT_MEASURABLE"}
            if component in required:
                warnings.append(f"BASELINE_MISSING_REQUIRED_COMPONENT:{component}")
            continue
        measurable_weight += comp_weight

        measurable_slot_weight = sum(float(s[1]["weight"]) for s in measurable)
        used: list[tuple[dict[str, Any], float]] = []
        for slot_name, slot, metric, base_component, base_value in measurable:
            entry: dict[str, Any] = {
                "component": component,
                "slot": slot_name,
                "metric": metric,
                "path": f"{base_component}.{metric}",
                "direction": slot["direction"],
                "mode": slot["mode"],
                "full_scale": slot["full_scale"],
                "dead_band": slot["dead_band"],
                "baseline_value": base_value,
                "baseline_date": baseline["baseline_date"],
                "baseline_period_basis": (
                    "POINT_IN_TIME"
                    if slot.get("point_in_time")
                    else baseline_period_basis(drift_cfg, ticker, metric)
                ),
                "baseline_source": {**baseline.get("source", {}), "path": baseline_rel},
                "previous_value": base_value,
                "raw_value": None,
                "delta": None,
                "normalized_signal": None,
                "contribution_points": 0.0,
                "source": None,
                "status": "BASELINE",
            }
            if previous is not None:
                found = _find_metric(previous["metrics"], sources, metric)
                if found is not None:
                    entry["previous_value"] = _as_number(found[1]["value"])

            if observation is None:
                entry.update(raw_value=base_value, delta=0.0, normalized_signal=0.0)
                used.append((entry, float(slot["weight"])))
                metrics_out.append(entry)
                continue

            found = _find_metric(observation["metrics"], sources, metric)
            if found is None:
                entry["status"] = "MISSING_OBSERVATION"
                warnings.append(f"MISSING_DATA:{metric}")
                metrics_out.append(entry)
                continue
            item = found[1]
            raw = _as_number(item["value"])
            entry["raw_value"] = raw
            entry["source"] = {
                **item["source"],
                "path": observation_rel,
                "period": item["period"],
                "period_basis": item["period_basis"],
                "retrieved_at": item["retrieved_at"],
                "currency": item.get("currency"),
                "calculation_method": item.get("calculation_method"),
            }
            if not slot.get("point_in_time") and item["period_basis"] != entry["baseline_period_basis"]:
                entry["status"] = "PERIOD_MISMATCH"
                warnings.append(f"PERIOD_MISMATCH:{metric}")
                metrics_out.append(entry)
                continue
            try:
                delta, signal = normalize(
                    baseline_value=base_value,
                    raw_value=raw,
                    mode=slot["mode"],
                    direction=slot["direction"],
                    full_scale=float(slot["full_scale"]),
                    dead_band=float(slot["dead_band"]),
                )
            except ZeroDivisionError:
                entry["status"] = "CALCULATION_ANOMALY"
                warnings.append(f"CALCULATION_ANOMALY:{metric}:zero_baseline")
                metrics_out.append(entry)
                continue
            entry.update(delta=delta, normalized_signal=signal, status="OK")
            used.append((entry, float(slot["weight"])))
            metrics_out.append(entry)

        used_slot_weight = sum(w for _, w in used)
        slot_coverage = used_slot_weight / measurable_slot_weight
        comp_out = {
            "weight": comp_weight,
            "measurable_slot_weight": measurable_slot_weight,
            "slot_coverage": slot_coverage,
        }
        if not used or slot_coverage + 1e-12 < min_slot_cov:
            comp_out["status"] = "INSUFFICIENT_SLOT_COVERAGE"
            if used:
                warnings.append(f"COMPONENT_SLOT_COVERAGE_LOW:{component}:{slot_coverage:.3f}")
            for entry, _ in used:
                entry["status"] = "EXCLUDED_LOW_COMPONENT_COVERAGE"
            components_out[component] = comp_out
            continue
        signal = sum(e["normalized_signal"] * w for e, w in used) / used_slot_weight
        for entry, w in used:
            entry["_slot_share"] = w / used_slot_weight
        component_signals[component] = signal
        comp_out.update(status="OK", signal=signal)
        components_out[component] = comp_out

    available_weight = sum(float(profile["components"][c]["weight"]) for c in component_signals)
    coverage = available_weight / measurable_weight if measurable_weight else 0.0
    profile_coverage = measurable_weight / total_weight if total_weight else 0.0

    if available_weight > 0:
        weighted = sum(
            float(profile["components"][c]["weight"]) * s for c, s in component_signals.items()
        ) / available_weight
    else:
        weighted = 0.0
    score = clamp(neutral + 50.0 * weighted, 0.0, 100.0)

    for entry in metrics_out:
        share = entry.pop("_slot_share", None)
        if share is not None and entry["component"] in component_signals and available_weight:
            comp_share = float(profile["components"][entry["component"]]["weight"]) / available_weight
            entry["contribution_points"] = 50.0 * comp_share * share * entry["normalized_signal"]

    missing_required = [c for c in required if c not in component_signals]
    if observation is None:
        status = STATUS_NO_NEW
        score = neutral
    elif missing_required or coverage + 1e-12 < min_comp_cov:
        status = STATUS_DATA_CHECK
        for c in missing_required:
            warnings.append(f"MISSING_REQUIRED_COMPONENT:{c}")
        if coverage + 1e-12 < min_comp_cov:
            warnings.append(f"DRIFT_COVERAGE_BELOW_THRESHOLD:{coverage:.3f}")
    else:
        status = STATUS_OK

    return Evaluation(
        score=score,
        status=status,
        coverage=coverage if observation is not None else None,
        profile_coverage=profile_coverage,
        components=components_out,
        metrics=metrics_out,
        warnings=sorted(set(warnings)),
    )


def _days_between(later: str, earlier: str) -> int:
    return (date.fromisoformat(later) - date.fromisoformat(earlier)).days


def build_ticker_drift(
    *,
    ticker: str,
    company_type: str,
    drift_cfg: dict[str, Any],
    baseline: dict[str, Any],
    baseline_rel: str,
    observations: list[tuple[str, dict[str, Any]]],
    as_of: str,
) -> dict[str, Any]:
    profile = drift_cfg["profiles"][company_type]

    def run(index: int) -> Evaluation:
        obs_rel, obs = observations[index] if index >= 0 else (None, None)
        prev = observations[index - 1][1] if index >= 1 else None
        return evaluate(
            ticker=ticker,
            profile=profile,
            drift_cfg=drift_cfg,
            baseline=baseline,
            baseline_rel=baseline_rel,
            observation=obs,
            observation_rel=obs_rel,
            previous=prev,
        )

    latest = run(len(observations) - 1)
    previous = run(len(observations) - 2) if observations else latest
    neutral = float(drift_cfg["neutral_score"])

    warnings = list(latest.warnings)
    last_fundamental_date = (
        str(observations[-1][1]["observation_date"]) if observations else str(baseline["baseline_date"])
    )
    age_days = _days_between(as_of, last_fundamental_date)
    if age_days > int(drift_cfg["max_observation_age_days"]):
        warnings.append(f"STALE_DATA:last_fundamental_update:{age_days}d")
    if latest.profile_coverage + 1e-12 < float(drift_cfg["minimum_component_weight_coverage"]):
        warnings.append(f"BASELINE_PROFILE_COVERAGE_LOW:{latest.profile_coverage:.3f}")

    published = latest.status != STATUS_DATA_CHECK
    return {
        "company_type": company_type,
        "status": latest.status,
        "drift_score": round(latest.score, 4) if published else None,
        "diagnostic_drift_score": round(latest.score, 4),
        "drift_change_since_baseline": round(latest.score - neutral, 4) if published else None,
        "drift_change_recent": round(latest.score - previous.score, 4) if published else None,
        "coverage": latest.coverage,
        "profile_coverage": round(latest.profile_coverage, 6),
        "baseline": {
            "path": baseline_rel,
            "baseline_date": baseline["baseline_date"],
            "reporting_period_end": baseline.get("reporting_period_end"),
        },
        "latest_observation": observations[-1][0] if observations else None,
        "observation_count": len(observations),
        "last_fundamental_update": last_fundamental_date,
        "fundamental_age_days": age_days,
        "components": latest.components,
        "metrics": latest.metrics,
        "warnings": sorted(set(warnings)),
        "execution_effect": "NONE",
    }


def build_drift_snapshot(*, root: Path, as_of: str | None = None, code_version: str | None = None) -> dict[str, Any]:
    repo_cfg = load_config(root)
    cfg = load_decision_config(root)
    drift_cfg = cfg["quality_drift"]
    as_of = as_of or datetime.now(timezone.utc).date().isoformat()

    index_path = root / "data/baselines/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    results: dict[str, Any] = {}
    baseline_hashes: dict[str, str] = {}
    observation_hashes: dict[str, str] = {}

    for ticker, position in repo_cfg["portfolio"]["positions"].items():
        baseline_rel = index["baselines"][ticker]
        baseline_path = root / baseline_rel
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline_hashes[baseline_rel] = sha256_file(baseline_path)
        observations = []
        for path, payload in load_observations(root, ticker):
            if str(payload["observation_date"]) < str(baseline["baseline_date"]):
                raise ObservationError(f"{path}: observation_date precedes the baseline")
            if str(payload["observation_date"]) > as_of:
                continue
            rel = path.relative_to(root).as_posix()
            observation_hashes[rel] = sha256_file(path)
            observations.append((rel, payload))
        results[ticker] = build_ticker_drift(
            ticker=ticker,
            company_type=position["company_type"],
            drift_cfg=drift_cfg,
            baseline=baseline,
            baseline_rel=baseline_rel,
            observations=observations,
            as_of=as_of,
        )

    config_hash, config_hashes = bundle_hash(root, CONFIG_FILES)
    code_hash, code_hashes = bundle_hash(root, CODE_FILES)
    reproducibility_hash = sha256_json(
        {
            "as_of": as_of,
            "config_hash": config_hash,
            "code_hash": code_hash,
            "baseline_index": sha256_file(index_path),
            "baselines": baseline_hashes,
            "observations": observation_hashes,
        }
    )
    statuses = [r["status"] for r in results.values()]
    return {
        "schema_version": 1,
        "pipeline_version": PIPELINE_VERSION,
        "axis": "QUALITY_DRIFT",
        "as_of": as_of,
        "reproducibility_hash": reproducibility_hash,
        "methodology": {
            "formula": drift_cfg["formula"],
            "neutral_score": drift_cfg["neutral_score"],
            "minimum_component_weight_coverage": drift_cfg["minimum_component_weight_coverage"],
            "minimum_slot_weight_coverage": drift_cfg["minimum_slot_weight_coverage"],
            "period_rule": drift_cfg["period_rule"],
            "coverage_basis": "baseline_measurable_weight",
            "price_inputs": "NONE",
        },
        "provenance": {
            "run_git_commit": code_version or git_head(root),
            "code_hash": code_hash,
            "config_hash": config_hash,
            "code_files": code_hashes,
            "config_files": config_hashes,
            "baseline_index": {"path": "data/baselines/index.json", "sha256": sha256_file(index_path)},
            "baseline_hashes": baseline_hashes,
            "observation_hashes": observation_hashes,
        },
        "summary": {
            "portfolio_companies": len(results),
            **{s: statuses.count(s) for s in (STATUS_OK, STATUS_NO_NEW, STATUS_DATA_CHECK)},
        },
        "results": results,
        "execution_effect": "NONE",
    }


def _repo_root_from_module() -> Path:
    return Path(__file__).resolve().parents[3]


def write_drift_snapshot(root: Path, payload: dict[str, Any]) -> Path:
    output_dir = root / OUTPUT_DIR
    path = write_immutable_snapshot(payload=payload, output_dir=output_dir, prefix=PREFIX)
    update_current_pointer(
        root=root, snapshot_path=path, payload=payload, output_dir=output_dir, pointer_key=POINTER_KEY
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Quality Drift (change versus each company's own baseline). Never price-driven."
    )
    parser.add_argument("--root", type=Path, default=_repo_root_from_module())
    parser.add_argument("--as-of", help="ISO date; default is today (UTC)")
    parser.add_argument("--code-version")
    parser.add_argument("--write", action="store_true", help="write an immutable revision to data/drift/")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    payload = build_drift_snapshot(root=root, as_of=args.as_of, code_version=args.code_version)
    if not args.write:
        print(canonical_json(payload), end="")
        return 0
    print(write_drift_snapshot(root, payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
