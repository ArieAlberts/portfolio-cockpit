from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

import yaml


VALID_DIRECTIONS = {"higher_is_better", "lower_is_better"}
PRICE_TOKENS = {
    "price",
    "share_price",
    "market_price",
    "market_value",
    "valuation",
    "pe_ratio",
    "p_e",
}


class AbsoluteAnchorConfigError(ValueError):
    """Raised when absolute-anchor configuration is inconsistent."""


@dataclass(frozen=True)
class AnchorMetricResult:
    metric_name: str
    state: str
    value: float | None
    threshold: float
    direction: str
    required: bool
    source_path: str


@dataclass(frozen=True)
class AbsoluteAnchorResult:
    ticker: str
    profile: str | None
    status: str
    required_anchors_met: bool | None
    configured_metrics: int
    observed_metrics: int
    metrics_met: int
    metrics_missed: int
    metrics_missing: int
    metric_results: tuple[AnchorMetricResult, ...]
    execution_effect: str = "NONE"


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AbsoluteAnchorConfigError(f"{path}: expected a YAML mapping")
    return data


def validate_absolute_anchor_config(config: dict[str, Any]) -> None:
    errors: list[str] = []

    if config.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    policy = config.get("policy", {})
    if policy.get("alters_fundamental_quality") is not False:
        errors.append("absolute anchors must not alter Fundamental Quality")
    if policy.get("decision_gate") is not False:
        errors.append("absolute anchors v1 must not be a Decision Engine gate")
    if policy.get("price_inputs_allowed") is not False:
        errors.append("price inputs must remain forbidden")
    if policy.get("execution_effect") != "NONE":
        errors.append("execution_effect must remain NONE")

    assignments = config.get("assignments", {})
    profiles = config.get("profiles", {})
    if not isinstance(assignments, dict):
        errors.append("assignments must be a mapping")
        assignments = {}
    if not isinstance(profiles, dict) or not profiles:
        errors.append("profiles must be a non-empty mapping")
        profiles = {}

    for ticker, profile_name in assignments.items():
        if profile_name not in profiles:
            errors.append(f"{ticker}: unknown absolute-anchor profile {profile_name!r}")

    for profile_name, profile in profiles.items():
        metrics = profile.get("metrics", {})
        if not isinstance(metrics, dict) or not metrics:
            errors.append(f"{profile_name}: metrics must be a non-empty mapping")
            continue

        if not any(bool(cfg.get("required", False)) for cfg in metrics.values()):
            errors.append(f"{profile_name}: at least one metric must be required")

        for metric_name, metric_cfg in metrics.items():
            direction = metric_cfg.get("direction")
            if direction not in VALID_DIRECTIONS:
                errors.append(
                    f"{profile_name}:{metric_name}: invalid direction {direction!r}"
                )

            try:
                threshold = float(metric_cfg["threshold"])
            except (KeyError, TypeError, ValueError):
                errors.append(f"{profile_name}:{metric_name}: invalid threshold")
            else:
                if not isfinite(threshold):
                    errors.append(
                        f"{profile_name}:{metric_name}: threshold must be finite"
                    )

            source_path = str(metric_cfg.get("source_path", ""))
            if not source_path:
                errors.append(f"{profile_name}:{metric_name}: source_path is required")
            path_tokens = {part.lower() for part in source_path.split(".")}
            if path_tokens.intersection(PRICE_TOKENS):
                errors.append(
                    f"{profile_name}:{metric_name}: price/valuation inputs are forbidden"
                )

            if not isinstance(metric_cfg.get("required"), bool):
                errors.append(
                    f"{profile_name}:{metric_name}: required must be boolean"
                )

    if errors:
        raise AbsoluteAnchorConfigError(
            "Absolute-anchor configuration validation failed:\n- "
            + "\n- ".join(errors)
        )


def load_absolute_anchor_config(root: Path) -> dict[str, Any]:
    config = _read_yaml(root / "config/absolute_anchors.yaml")
    validate_absolute_anchor_config(config)
    return config


def _value_at_path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _metric_state(value: float, *, threshold: float, direction: str) -> str:
    if direction == "higher_is_better":
        return "MEETS_ANCHOR" if value >= threshold else "MISSES_ANCHOR"
    if direction == "lower_is_better":
        return "MEETS_ANCHOR" if value <= threshold else "MISSES_ANCHOR"
    raise ValueError(f"Unsupported direction: {direction}")


def evaluate_absolute_anchors(
    *,
    ticker: str,
    baseline: dict[str, Any],
    config: dict[str, Any],
) -> AbsoluteAnchorResult:
    validate_absolute_anchor_config(config)
    profile_name = config.get("assignments", {}).get(ticker)
    if profile_name is None:
        return AbsoluteAnchorResult(
            ticker=ticker,
            profile=None,
            status="NOT_CONFIGURED",
            required_anchors_met=None,
            configured_metrics=0,
            observed_metrics=0,
            metrics_met=0,
            metrics_missed=0,
            metrics_missing=0,
            metric_results=(),
        )

    profile = config["profiles"][profile_name]
    results: list[AnchorMetricResult] = []
    required_states: list[str] = []

    for metric_name, metric_cfg in profile["metrics"].items():
        raw = _value_at_path(baseline, str(metric_cfg["source_path"]))
        required = bool(metric_cfg["required"])
        threshold = float(metric_cfg["threshold"])
        direction = str(metric_cfg["direction"])

        if raw is None:
            state = "MISSING"
            numeric = None
        else:
            numeric = float(raw)
            if not isfinite(numeric):
                state = "MISSING"
                numeric = None
            else:
                state = _metric_state(
                    numeric,
                    threshold=threshold,
                    direction=direction,
                )

        if required:
            required_states.append(state)

        results.append(
            AnchorMetricResult(
                metric_name=metric_name,
                state=state,
                value=numeric,
                threshold=threshold,
                direction=direction,
                required=required,
                source_path=str(metric_cfg["source_path"]),
            )
        )

    missing_required = any(state == "MISSING" for state in required_states)
    required_anchors_met = (
        None
        if missing_required
        else all(state == "MEETS_ANCHOR" for state in required_states)
    )
    status = (
        "DATA_CHECK"
        if missing_required
        else "ANCHORS_MET"
        if required_anchors_met
        else "ANCHOR_MISS"
    )

    return AbsoluteAnchorResult(
        ticker=ticker,
        profile=profile_name,
        status=status,
        required_anchors_met=required_anchors_met,
        configured_metrics=len(results),
        observed_metrics=sum(r.state != "MISSING" for r in results),
        metrics_met=sum(r.state == "MEETS_ANCHOR" for r in results),
        metrics_missed=sum(r.state == "MISSES_ANCHOR" for r in results),
        metrics_missing=sum(r.state == "MISSING" for r in results),
        metric_results=tuple(results),
    )
