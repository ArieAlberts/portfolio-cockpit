from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

import yaml


BASELINE_DRIFT_SCORE = 50.0


class QualityDriftConfigError(ValueError):
    """Raised when Quality Drift configuration is internally inconsistent."""


@dataclass(frozen=True)
class QualityDriftResult:
    score: float | None
    weighted_signal: float | None
    signal_coverage: float
    status: str
    applied_components: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise QualityDriftConfigError(f"{path}: expected a YAML mapping")
    return data


def validate_quality_drift_config(config: dict[str, Any]) -> None:
    errors: list[str] = []

    if config.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    baseline = float(config.get("baseline_score", -1))
    scale_min = float(config.get("scale_min", 0))
    scale_max = float(config.get("scale_max", 100))
    if not scale_min < baseline < scale_max:
        errors.append("baseline_score must lie strictly inside the score scale")
    if abs(baseline - BASELINE_DRIFT_SCORE) > 1e-12:
        errors.append("baseline_score must remain exactly 50.0")

    signal_min = float(config.get("signal_min", 0))
    signal_max = float(config.get("signal_max", 0))
    if (signal_min, signal_max) != (-1.0, 1.0):
        errors.append("signal bounds must remain exactly [-1, +1]")

    minimum_confidence = float(config.get("minimum_update_confidence", -1))
    if not 0 <= minimum_confidence <= 100:
        errors.append("minimum_update_confidence must be in [0, 100]")

    triggers = tuple(config.get("allowed_update_triggers", ()))
    if not triggers:
        errors.append("allowed_update_triggers must not be empty")
    forbidden_trigger_tokens = {"price", "market_price", "technical_signal"}
    if forbidden_trigger_tokens.intersection({str(t).lower() for t in triggers}):
        errors.append("market-price or technical triggers are forbidden for Quality Drift")

    profiles = config.get("profiles", {})
    if not profiles:
        errors.append("profiles must not be empty")
    for company_type, weights in profiles.items():
        if not isinstance(weights, dict) or not weights:
            errors.append(f"{company_type}: drift profile must be a non-empty mapping")
            continue
        numeric = {name: float(weight) for name, weight in weights.items()}
        if any(weight <= 0 for weight in numeric.values()):
            errors.append(f"{company_type}: all drift weights must be positive")
        total = sum(numeric.values())
        if abs(total - 1.0) > 1e-9:
            errors.append(
                f"{company_type}: drift component weights sum to {total}, not 1.0"
            )

    if errors:
        raise QualityDriftConfigError(
            "Quality Drift configuration validation failed:\n- "
            + "\n- ".join(errors)
        )


def load_quality_drift_config(root: Path) -> dict[str, Any]:
    config = _read_yaml(root / "config/quality_drift.yaml")
    validate_quality_drift_config(config)
    return config


def profile_weights(
    config: dict[str, Any],
    company_type: str,
) -> dict[str, float]:
    validate_quality_drift_config(config)
    try:
        profile = config["profiles"][company_type]
    except KeyError as exc:
        raise QualityDriftConfigError(
            f"No Quality Drift profile for company type {company_type!r}"
        ) from exc
    return {name: float(weight) for name, weight in profile.items()}


def initial_quality_drift() -> float:
    return BASELINE_DRIFT_SCORE


def drift_from_weighted_signals(weighted_signal: float) -> float:
    """
    weighted_signal is expected in [-1, +1].
    -1 -> 0
     0 -> 50
    +1 -> 100

    Price data must never be used as an input to this function.
    """
    weighted_signal = max(-1.0, min(1.0, float(weighted_signal)))
    return 50.0 + 50.0 * weighted_signal


def calculate_quality_drift(
    *,
    component_signals: Mapping[str, float],
    component_weights: Mapping[str, float],
) -> QualityDriftResult:
    """Calculate drift versus an immutable baseline from normalized evidence.

    Missing components are neutral (signal 0); available components are never
    reweighted to 100%. This prevents sparse evidence from dominating drift.
    """
    weights = {name: float(weight) for name, weight in component_weights.items()}
    if not weights:
        raise ValueError("component_weights must not be empty")
    if any(weight <= 0 for weight in weights.values()):
        raise ValueError("component weights must be positive")
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-9:
        raise ValueError("component weights must sum to 1.0")

    unknown = set(component_signals) - set(weights)
    if unknown:
        raise ValueError(f"Unknown Quality Drift components: {sorted(unknown)}")

    if not component_signals:
        return QualityDriftResult(
            score=BASELINE_DRIFT_SCORE,
            weighted_signal=0.0,
            signal_coverage=0.0,
            status="BASELINE",
            applied_components=(),
        )

    normalized: dict[str, float] = {}
    for component, value in component_signals.items():
        numeric = float(value)
        if not isfinite(numeric) or not -1.0 <= numeric <= 1.0:
            raise ValueError(
                f"{component}: Quality Drift signal must be finite and in [-1, +1]"
            )
        normalized[component] = numeric

    weighted_signal = sum(weights[name] * signal for name, signal in normalized.items())
    coverage = sum(weights[name] for name in normalized)
    return QualityDriftResult(
        score=drift_from_weighted_signals(weighted_signal),
        weighted_signal=weighted_signal,
        signal_coverage=coverage,
        status="UPDATED",
        applied_components=tuple(sorted(normalized)),
    )


def evaluate_quality_drift_update(
    *,
    component_signals: Mapping[str, float],
    component_weights: Mapping[str, float],
    trigger: str | None,
    source_validated: bool,
    source_confidence_score: float | None,
    config: dict[str, Any],
) -> QualityDriftResult:
    """Apply Quality Drift gates before a component-signal update is accepted."""
    validate_quality_drift_config(config)

    if not component_signals:
        return calculate_quality_drift(
            component_signals={},
            component_weights=component_weights,
        )

    allowed = {str(v) for v in config["allowed_update_triggers"]}
    if trigger not in allowed:
        return QualityDriftResult(
            score=None,
            weighted_signal=None,
            signal_coverage=0.0,
            status="DATA_CHECK",
            applied_components=(),
            warnings=("UPDATE_TRIGGER_NOT_ALLOWED",),
        )

    if not source_validated:
        return QualityDriftResult(
            score=None,
            weighted_signal=None,
            signal_coverage=0.0,
            status="DATA_CHECK",
            applied_components=(),
            warnings=("SOURCE_NOT_VALIDATED",),
        )

    threshold = float(config["minimum_update_confidence"])
    if source_confidence_score is None:
        return QualityDriftResult(
            score=None,
            weighted_signal=None,
            signal_coverage=0.0,
            status="DATA_CHECK",
            applied_components=(),
            warnings=("SOURCE_CONFIDENCE_PENDING",),
        )
    confidence = float(source_confidence_score)
    if not isfinite(confidence) or not 0 <= confidence <= 100:
        raise ValueError("source_confidence_score must be finite and in [0, 100]")
    if confidence < threshold:
        return QualityDriftResult(
            score=None,
            weighted_signal=None,
            signal_coverage=0.0,
            status="DATA_CHECK",
            applied_components=(),
            warnings=("SOURCE_CONFIDENCE_BELOW_THRESHOLD",),
        )

    return calculate_quality_drift(
        component_signals=component_signals,
        component_weights=component_weights,
    )
