from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

import yaml


VALID_DECISION_STATES = {
    "ADD_CANDIDATE",
    "HOLD",
    "NO_ADD",
    "REVIEW_REDUCE",
    "THESIS_REVIEW",
    "DATA_CHECK",
}


class DecisionConfigError(ValueError):
    """Raised when Decision Engine configuration is internally inconsistent."""


@dataclass(frozen=True)
class DecisionInputs:
    quality_drift_score: float | None
    valuation_score: float | None
    data_confidence_score: float | None
    thesis_status: str = "UNKNOWN"
    fundamental_quality_score: float | None = None


@dataclass(frozen=True)
class DecisionResult:
    state: str
    reasons: tuple[str, ...]
    execution_effect: str = "NONE"


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DecisionConfigError(f"{path}: expected a YAML mapping")
    return data


def validate_decision_config(config: dict[str, Any]) -> None:
    errors: list[str] = []

    if config.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    states = set(config.get("states", ()))
    if states != VALID_DECISION_STATES:
        errors.append(
            f"states must equal {sorted(VALID_DECISION_STATES)}, got {sorted(states)}"
        )

    confidence = float(config.get("data_confidence_threshold", -1))
    if not 0 <= confidence <= 100:
        errors.append("data_confidence_threshold must be in [0, 100]")

    thresholds = config.get("thresholds", {})
    required = {
        "material_quality_deterioration_max",
        "strong_quality_drift_min",
        "acceptable_quality_drift_min",
        "attractive_valuation_min",
        "expensive_valuation_max",
        "fundamental_quality_add_floor_when_available",
    }
    missing = required - set(thresholds)
    if missing:
        errors.append(f"missing thresholds: {sorted(missing)}")
    else:
        values = {name: float(thresholds[name]) for name in required}
        if any(not 0 <= value <= 100 for value in values.values()):
            errors.append("all thresholds must be in [0, 100]")
        if not (
            values["material_quality_deterioration_max"]
            < values["acceptable_quality_drift_min"]
            <= values["strong_quality_drift_min"]
        ):
            errors.append(
                "quality thresholds must satisfy deterioration < acceptable <= strong"
            )
        if not (
            values["expensive_valuation_max"]
            < values["attractive_valuation_min"]
        ):
            errors.append("expensive valuation threshold must be below attractive")

    missing_valuation_state = str(config.get("missing_valuation_state", ""))
    if missing_valuation_state not in VALID_DECISION_STATES:
        errors.append("missing_valuation_state is not a valid decision state")

    if config.get("execution_effect") != "NONE":
        errors.append("execution_effect must remain NONE")

    if not config.get("broken_thesis_states"):
        errors.append("broken_thesis_states must not be empty")

    if errors:
        raise DecisionConfigError(
            "Decision configuration validation failed:\n- " + "\n- ".join(errors)
        )


def load_decision_config(root: Path) -> dict[str, Any]:
    config = _read_yaml(root / "config/decision.yaml")
    validate_decision_config(config)
    return config


def _validate_score(name: str, value: float | None) -> None:
    if value is None:
        return
    numeric = float(value)
    if not isfinite(numeric) or not 0 <= numeric <= 100:
        raise ValueError(f"{name} must be finite and in [0, 100]")


def evaluate_decision(
    inputs: DecisionInputs,
    config: dict[str, Any],
) -> DecisionResult:
    """Evaluate a deterministic decision-support state.

    The result is descriptive only. It has no execution capability and can
    never place, modify or cancel a brokerage order.
    """
    validate_decision_config(config)
    _validate_score("quality_drift_score", inputs.quality_drift_score)
    _validate_score("valuation_score", inputs.valuation_score)
    _validate_score("data_confidence_score", inputs.data_confidence_score)
    _validate_score("fundamental_quality_score", inputs.fundamental_quality_score)

    confidence_threshold = float(config["data_confidence_threshold"])
    thresholds = config["thresholds"]
    thesis = str(inputs.thesis_status or "UNKNOWN").upper()

    if (
        inputs.data_confidence_score is None
        or float(inputs.data_confidence_score) < confidence_threshold
        or inputs.quality_drift_score is None
    ):
        reasons = []
        if inputs.data_confidence_score is None:
            reasons.append("DATA_CONFIDENCE_PENDING")
        elif float(inputs.data_confidence_score) < confidence_threshold:
            reasons.append("DATA_CONFIDENCE_BELOW_THRESHOLD")
        if inputs.quality_drift_score is None:
            reasons.append("QUALITY_DRIFT_PENDING")
        return DecisionResult("DATA_CHECK", tuple(reasons))

    if thesis in {str(v).upper() for v in config["broken_thesis_states"]}:
        return DecisionResult("THESIS_REVIEW", ("THESIS_BROKEN",))

    drift = float(inputs.quality_drift_score)
    if drift <= float(thresholds["material_quality_deterioration_max"]):
        return DecisionResult(
            "REVIEW_REDUCE",
            ("MATERIAL_QUALITY_DETERIORATION",),
        )

    if inputs.valuation_score is None:
        return DecisionResult(
            str(config["missing_valuation_state"]),
            ("VALUATION_PENDING",),
        )

    valuation = float(inputs.valuation_score)
    if (
        drift >= float(thresholds["strong_quality_drift_min"])
        and valuation >= float(thresholds["attractive_valuation_min"])
    ):
        fq = inputs.fundamental_quality_score
        fq_floor = float(
            thresholds["fundamental_quality_add_floor_when_available"]
        )
        if fq is None or float(fq) >= fq_floor:
            reasons = ["STRONG_QUALITY_DRIFT", "ATTRACTIVE_VALUATION"]
            if fq is not None:
                reasons.append("FUNDAMENTAL_QUALITY_SUPPORTIVE")
            else:
                reasons.append("FUNDAMENTAL_QUALITY_PENDING")
            return DecisionResult("ADD_CANDIDATE", tuple(reasons))
        return DecisionResult(
            "HOLD",
            ("FUNDAMENTAL_QUALITY_BELOW_ADD_FLOOR",),
        )

    if (
        drift >= float(thresholds["acceptable_quality_drift_min"])
        and valuation <= float(thresholds["expensive_valuation_max"])
    ):
        return DecisionResult(
            "NO_ADD",
            ("VALUATION_EXPENSIVE", "QUALITY_NOT_MATERIALLY_DETERIORATED"),
        )

    return DecisionResult("HOLD", ("NO_HIGH_PRIORITY_DECISION_TRIGGER",))
