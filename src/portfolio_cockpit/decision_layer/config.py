"""Fail-fast loading and validation of decision-layer configuration.

The decision layer reads the Fundamental Quality config (portfolio,
company types, score metrics, scoring) but never writes it. Its own
thresholds live in separate YAML files so that nothing here touches the
Fundamental Quality hash scope.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from portfolio_cockpit.config import load_config


DECISION_CONFIG_FILES = {
    "quality_drift": "config/quality_drift.yaml",
    "valuation": "config/valuation.yaml",
    "decision": "config/decision.yaml",
    "risk_scenarios": "config/risk_scenarios.yaml",
    "positions": "config/positions.yaml",
    "thesis_status": "config/thesis_status.yaml",
}

VALID_PERIOD_RULES = {"like_for_like"}
VALID_DRIFT_MODES = {"relative", "absolute", "direct"}
VALID_DIRECTIONS = {"higher_is_better", "lower_is_better"}
VALID_SCENARIO_TYPES = {"market", "sector", "single_stock", "combined"}
REQUIRED_SCENARIOS = (
    "market_shock",
    "sector_shock",
    "single_stock_shock",
    "combined_scenario",
)


class DecisionConfigError(ValueError):
    """Raised when decision-layer configuration is invalid."""


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise DecisionConfigError(f"{path}: missing config file")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DecisionConfigError(f"{path}: expected a YAML mapping")
    return data


def load_decision_config(root: Path) -> dict[str, dict[str, Any]]:
    """Load and validate all decision-layer config against the repo config."""
    cfg = {name: _read_yaml(root / rel) for name, rel in DECISION_CONFIG_FILES.items()}
    validate_decision_config(cfg, load_config(root))
    return cfg


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_number(
    errors: list[str],
    label: str,
    value: Any,
    *,
    lo: float | None = None,
    hi: float | None = None,
) -> None:
    if not _is_number(value):
        errors.append(f"{label} must be a number")
        return
    if lo is not None and value < lo:
        errors.append(f"{label} must be >= {lo}")
    if hi is not None and value > hi:
        errors.append(f"{label} must be <= {hi}")


def _check_iso_date(errors: list[str], label: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, date):
        return
    try:
        date.fromisoformat(str(value))
    except ValueError:
        errors.append(f"{label} must be an ISO date (YYYY-MM-DD) or empty")


def _validate_schema_versions(cfg: dict[str, dict[str, Any]], errors: list[str]) -> None:
    for name in DECISION_CONFIG_FILES:
        if cfg[name].get("schema_version") != 1:
            errors.append(f"{name}.schema_version must be 1")


def _validate_quality_drift(
    drift: dict[str, Any],
    repo_cfg: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    _check_number(errors, "quality_drift.neutral_score", drift.get("neutral_score"), lo=50, hi=50)
    _check_number(
        errors,
        "quality_drift.minimum_component_weight_coverage",
        drift.get("minimum_component_weight_coverage"),
        lo=0.0,
        hi=1.0,
    )
    _check_number(
        errors,
        "quality_drift.minimum_slot_weight_coverage",
        drift.get("minimum_slot_weight_coverage"),
        lo=0.0,
        hi=1.0,
    )
    _check_number(
        errors, "quality_drift.max_observation_age_days", drift.get("max_observation_age_days"), lo=1
    )
    if drift.get("period_rule") not in VALID_PERIOD_RULES:
        errors.append(f"quality_drift.period_rule must be one of {sorted(VALID_PERIOD_RULES)}")

    bases = drift.get("valid_period_bases")
    if not isinstance(bases, list) or "POINT_IN_TIME" not in bases:
        errors.append("quality_drift.valid_period_bases must be a list including POINT_IN_TIME")
        bases = []
    period_cfg = drift.get("baseline_period_basis") or {}
    by_ticker = period_cfg.get("by_ticker") or {}
    tickers = set(repo_cfg["portfolio"]["positions"])
    if set(by_ticker) != tickers:
        errors.append(
            "quality_drift.baseline_period_basis.by_ticker must cover exactly the portfolio tickers"
        )
    for ticker, basis in by_ticker.items():
        if basis not in bases:
            errors.append(f"quality_drift.baseline_period_basis.by_ticker.{ticker}: invalid basis {basis!r}")
    for i, pattern in enumerate(period_cfg.get("metric_name_patterns") or []):
        if not isinstance(pattern.get("contains"), str) or pattern.get("basis") not in bases:
            errors.append(f"quality_drift.baseline_period_basis.metric_name_patterns[{i}] is invalid")

    excluded = drift.get("excluded_metric_patterns")
    if not isinstance(excluded, list) or not all(isinstance(p, str) for p in excluded):
        errors.append("quality_drift.excluded_metric_patterns must be a list of strings")
        excluded = []

    profiles = drift.get("profiles")
    if not isinstance(profiles, dict):
        errors.append("quality_drift.profiles must be a mapping")
        return
    company_types = set(repo_cfg["company_types"])
    if set(profiles) != company_types:
        errors.append(
            "quality_drift.profiles must define exactly the company types in company_types.yaml: "
            f"missing={sorted(company_types - set(profiles))} unknown={sorted(set(profiles) - company_types)}"
        )
    all_directions = repo_cfg["score_metrics"]["metric_directions"]
    for company_type, profile in profiles.items():
        _validate_drift_profile(
            company_type,
            profile,
            all_directions.get(company_type, {}),
            excluded,
            errors,
        )


def _validate_drift_profile(
    company_type: str,
    profile: dict[str, Any],
    directions: dict[str, str],
    excluded_patterns: list[str],
    errors: list[str],
) -> None:
    label = f"quality_drift.profiles.{company_type}"
    components = profile.get("components")
    if not isinstance(components, dict) or not components:
        errors.append(f"{label}.components must be a non-empty mapping")
        return
    required = profile.get("required_components") or []
    unknown_required = sorted(set(required) - set(components))
    if not required or unknown_required:
        errors.append(f"{label}.required_components must be non-empty components: {unknown_required}")

    weights = [c.get("weight") for c in components.values()]
    if not all(_is_number(w) and w > 0 for w in weights):
        errors.append(f"{label}: component weights must be positive numbers")
    elif abs(sum(weights) - 1.0) > 1e-9:
        errors.append(f"{label}: component weights sum to {sum(weights)}, not 1.0")

    seen_aliases: dict[str, str] = {}
    for component, comp_cfg in components.items():
        clabel = f"{label}.{component}"
        sources = comp_cfg.get("source_components", [component])
        if not isinstance(sources, list) or not sources:
            errors.append(f"{clabel}.source_components must be a non-empty list")
        slots = comp_cfg.get("slots")
        if not isinstance(slots, dict) or not slots:
            errors.append(f"{clabel}.slots must be a non-empty mapping")
            continue
        slot_weights = [s.get("weight") for s in slots.values()]
        if not all(_is_number(w) and w > 0 for w in slot_weights):
            errors.append(f"{clabel}: slot weights must be positive numbers")
        elif abs(sum(slot_weights) - 1.0) > 1e-9:
            errors.append(f"{clabel}: slot weights sum to {sum(slot_weights)}, not 1.0")
        for slot_name, slot in slots.items():
            slabel = f"{clabel}.{slot_name}"
            if slot.get("mode") not in VALID_DRIFT_MODES:
                errors.append(f"{slabel}.mode must be one of {sorted(VALID_DRIFT_MODES)}")
            direction = slot.get("direction")
            if direction not in VALID_DIRECTIONS:
                errors.append(f"{slabel}.direction must be one of {sorted(VALID_DIRECTIONS)}")
            full_scale = slot.get("full_scale")
            dead_band = slot.get("dead_band")
            if not _is_number(full_scale) or full_scale <= 0:
                errors.append(f"{slabel}.full_scale must be > 0")
            if not _is_number(dead_band) or dead_band < 0:
                errors.append(f"{slabel}.dead_band must be >= 0")
            elif _is_number(full_scale) and dead_band >= full_scale:
                errors.append(f"{slabel}.dead_band must be below full_scale")
            if not isinstance(slot.get("point_in_time", False), bool):
                errors.append(f"{slabel}.point_in_time must be a boolean")
            aliases = slot.get("aliases")
            if not isinstance(aliases, list) or not aliases or not all(isinstance(a, str) for a in aliases):
                errors.append(f"{slabel}.aliases must be a non-empty list of metric names")
                continue
            for alias in aliases:
                if any(p in alias for p in excluded_patterns):
                    errors.append(f"{slabel}: alias {alias} matches an excluded pattern")
                if alias in seen_aliases:
                    errors.append(f"{slabel}: alias {alias} already used in {seen_aliases[alias]}")
                seen_aliases[alias] = slabel
                canonical = directions.get(alias)
                if canonical is not None and canonical != direction:
                    errors.append(
                        f"{slabel}: direction {direction} for {alias} conflicts with "
                        f"score_metrics.yaml ({canonical})"
                    )


def _validate_valuation(valuation: dict[str, Any], errors: list[str]) -> None:
    _check_number(errors, "valuation.max_price_age_days", valuation.get("max_price_age_days"), lo=1)
    labels = valuation.get("labels") or {}
    _check_number(errors, "valuation.labels.attractive_min", labels.get("attractive_min"), lo=0, hi=100)
    _check_number(errors, "valuation.labels.fair_min", labels.get("fair_min"), lo=0, hi=100)
    if _is_number(labels.get("attractive_min")) and _is_number(labels.get("fair_min")):
        if labels["fair_min"] >= labels["attractive_min"]:
            errors.append("valuation.labels.fair_min must be below attractive_min")
    ref = valuation.get("reference_weights") or {}
    if set(ref) != {"own_history", "peers"}:
        errors.append("valuation.reference_weights must define own_history and peers")
    elif all(_is_number(v) for v in ref.values()):
        if abs(sum(ref.values()) - 1.0) > 1e-9:
            errors.append("valuation.reference_weights must sum to 1.0")
    else:
        errors.append("valuation.reference_weights values must be numbers")
    if not isinstance(valuation.get("profiles"), dict):
        errors.append("valuation.profiles must be a mapping")


def _validate_decision(
    decision: dict[str, Any],
    repo_cfg: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    threshold = repo_cfg["scoring"]["data_confidence"]["decision_threshold"]
    _check_number(errors, "decision.data_confidence_min", decision.get("data_confidence_min"), lo=0, hi=100)
    if decision.get("data_confidence_min") != threshold:
        errors.append(
            "decision.data_confidence_min must equal scoring.yaml "
            f"data_confidence.decision_threshold ({threshold})"
        )

    drift = decision.get("drift") or {}
    for key in ("deteriorated_score_max", "strong_score_min", "acceptable_score_min"):
        _check_number(errors, f"decision.drift.{key}", drift.get(key), lo=0, hi=100)
    _check_number(
        errors,
        "decision.drift.deteriorated_recent_change_max",
        drift.get("deteriorated_recent_change_max"),
        hi=0,
    )
    if all(_is_number(drift.get(k)) for k in ("deteriorated_score_max", "acceptable_score_min", "strong_score_min")):
        if not drift["deteriorated_score_max"] < drift["acceptable_score_min"] <= drift["strong_score_min"]:
            errors.append(
                "decision.drift thresholds must satisfy "
                "deteriorated_score_max < acceptable_score_min <= strong_score_min"
            )

    valuation = decision.get("valuation") or {}
    _check_number(errors, "decision.valuation.attractive_score_min", valuation.get("attractive_score_min"), lo=0, hi=100)
    _check_number(errors, "decision.valuation.expensive_score_below", valuation.get("expensive_score_below"), lo=0, hi=100)
    if _is_number(valuation.get("attractive_score_min")) and _is_number(valuation.get("expensive_score_below")):
        if valuation["expensive_score_below"] > valuation["attractive_score_min"]:
            errors.append("decision.valuation.expensive_score_below must not exceed attractive_score_min")

    limits = decision.get("limits") or {}
    _check_number(errors, "decision.limits.max_position_weight_pct", limits.get("max_position_weight_pct"), lo=0, hi=100)
    _check_number(errors, "decision.limits.overweight_tolerance", limits.get("overweight_tolerance"), lo=0)
    _check_number(errors, "decision.limits.max_sector_weight_pct", limits.get("max_sector_weight_pct"), lo=0, hi=100)
    _check_number(
        errors, "decision.limits.max_single_position_impact_pp", limits.get("max_single_position_impact_pp"), lo=0
    )

    fq = decision.get("fundamental_quality") or {}
    _check_number(errors, "decision.fundamental_quality.fq_add_floor", fq.get("fq_add_floor"), lo=0, hi=100)

    if decision.get("thesis_status_values") != ["INTACT", "WATCH", "BROKEN"]:
        errors.append("decision.thesis_status_values must be [INTACT, WATCH, BROKEN]")


def _validate_risk_scenarios(risk: dict[str, Any], errors: list[str]) -> None:
    _check_number(errors, "risk_scenarios.standard_shock", risk.get("standard_shock"), lo=-1, hi=0)
    if risk.get("standard_label") != "PORTFOLIO IMPACT -30%":
        errors.append("risk_scenarios.standard_label must be 'PORTFOLIO IMPACT -30%'")
    elif risk.get("standard_shock") != -0.30:
        errors.append("risk_scenarios.standard_shock must be -0.30 to match its label")

    scenarios = risk.get("scenarios")
    if not isinstance(scenarios, dict):
        errors.append("risk_scenarios.scenarios must be a mapping")
        return
    for name in REQUIRED_SCENARIOS:
        if name not in scenarios:
            errors.append(f"risk_scenarios.scenarios.{name} is required")

    def check_component(label: str, item: dict[str, Any], *, allow_combined: bool) -> None:
        kind = item.get("type")
        allowed = VALID_SCENARIO_TYPES if allow_combined else VALID_SCENARIO_TYPES - {"combined"}
        if kind not in allowed:
            errors.append(f"{label}.type must be one of {sorted(allowed)}")
            return
        if kind == "combined":
            parts = item.get("components")
            if not isinstance(parts, list) or not parts:
                errors.append(f"{label}.components must be a non-empty list")
                return
            for i, part in enumerate(parts):
                check_component(f"{label}.components[{i}]", part, allow_combined=False)
            return
        _check_number(errors, f"{label}.shock", item.get("shock"), lo=-1, hi=1)
        if kind == "sector" and not isinstance(item.get("sector"), str):
            errors.append(f"{label}.sector must be a string")
        if kind == "single_stock" and not isinstance(item.get("target"), str):
            errors.append(f"{label}.target must be a ticker or 'largest'")

    for name, item in scenarios.items():
        if not isinstance(item, dict):
            errors.append(f"risk_scenarios.scenarios.{name} must be a mapping")
            continue
        check_component(f"risk_scenarios.scenarios.{name}", item, allow_combined=True)


def _validate_ticker_set(
    label: str,
    positions: Any,
    expected: set[str],
    errors: list[str],
) -> bool:
    if not isinstance(positions, dict):
        errors.append(f"{label}.positions must be a mapping")
        return False
    missing = sorted(expected - set(positions))
    unknown = sorted(set(positions) - expected)
    if missing:
        errors.append(f"{label}.positions is missing tickers: {missing}")
    if unknown:
        errors.append(f"{label}.positions has tickers not in portfolio.yaml: {unknown}")
    return True


def _validate_positions(positions_cfg: dict[str, Any], tickers: set[str], errors: list[str]) -> None:
    if positions_cfg.get("source") != "manual":
        errors.append("positions.source must be 'manual'")
    _check_iso_date(errors, "positions.as_of", positions_cfg.get("as_of"))
    cash = positions_cfg.get("cash_weight_pct")
    if cash is not None:
        _check_number(errors, "positions.cash_weight_pct", cash, lo=0, hi=100)

    positions = positions_cfg.get("positions")
    if not _validate_ticker_set("positions", positions, tickers, errors):
        return
    for ticker, item in positions.items():
        if not isinstance(item, dict):
            errors.append(f"positions.{ticker} must be a mapping")
            continue
        unknown = set(item) - {"weight_pct", "sector", "beta"}
        if unknown:
            errors.append(f"positions.{ticker} has unknown fields: {sorted(unknown)}")
        if item.get("weight_pct") is not None:
            _check_number(errors, f"positions.{ticker}.weight_pct", item["weight_pct"], lo=0, hi=100)
        if item.get("sector") is not None and not isinstance(item["sector"], str):
            errors.append(f"positions.{ticker}.sector must be a string")
        if item.get("beta") is not None:
            _check_number(errors, f"positions.{ticker}.beta", item["beta"], lo=0)

    weights = [
        item.get("weight_pct")
        for item in positions.values()
        if isinstance(item, dict) and _is_number(item.get("weight_pct"))
    ]
    total = sum(weights) + (cash if _is_number(cash) else 0)
    if total > 100.0 + 0.5:
        errors.append(f"positions weights plus cash sum to {total:.2f}%, above 100%")


def _validate_thesis_status(
    thesis_cfg: dict[str, Any],
    tickers: set[str],
    allowed: list[str],
    errors: list[str],
) -> None:
    positions = thesis_cfg.get("positions")
    if not _validate_ticker_set("thesis_status", positions, tickers, errors):
        return
    for ticker, item in positions.items():
        if not isinstance(item, dict):
            errors.append(f"thesis_status.{ticker} must be a mapping")
            continue
        unknown = set(item) - {"status", "as_of", "note"}
        if unknown:
            errors.append(f"thesis_status.{ticker} has unknown fields: {sorted(unknown)}")
        status = item.get("status")
        if status is not None and status not in allowed:
            errors.append(f"thesis_status.{ticker}.status must be one of {allowed}")
        _check_iso_date(errors, f"thesis_status.{ticker}.as_of", item.get("as_of"))
        if item.get("note") is not None and not isinstance(item["note"], str):
            errors.append(f"thesis_status.{ticker}.note must be a string")


def validate_decision_config(
    cfg: dict[str, dict[str, Any]],
    repo_cfg: dict[str, dict[str, Any]],
) -> None:
    """Validate structure and cross-file consistency; raise on any error.

    Empty owner-supplied values in positions.yaml and thesis_status.yaml are
    allowed here (they are templates). Use ``missing_owner_inputs`` to list
    what still needs to be filled before the decision engine can run.
    """
    errors: list[str] = []
    missing = sorted(set(DECISION_CONFIG_FILES) - set(cfg))
    if missing:
        raise DecisionConfigError(f"missing decision config sections: {missing}")

    tickers = set(repo_cfg["portfolio"]["positions"])
    _validate_schema_versions(cfg, errors)
    _validate_quality_drift(cfg["quality_drift"], repo_cfg, errors)
    _validate_valuation(cfg["valuation"], errors)
    _validate_decision(cfg["decision"], repo_cfg, errors)
    _validate_risk_scenarios(cfg["risk_scenarios"], errors)
    _validate_positions(cfg["positions"], tickers, errors)
    _validate_thesis_status(
        cfg["thesis_status"],
        tickers,
        list(cfg["decision"].get("thesis_status_values") or []),
        errors,
    )

    if errors:
        raise DecisionConfigError("; ".join(errors))


def missing_owner_inputs(cfg: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """List empty owner-supplied fields, per config file. Beta is optional."""
    positions_cfg = cfg["positions"]
    positions_missing = [
        key for key in ("as_of", "cash_weight_pct") if positions_cfg.get(key) is None
    ]
    for ticker, item in (positions_cfg.get("positions") or {}).items():
        for key in ("weight_pct", "sector"):
            if (item or {}).get(key) is None:
                positions_missing.append(f"{ticker}.{key}")

    thesis_missing = [
        f"{ticker}.{key}"
        for ticker, item in (cfg["thesis_status"].get("positions") or {}).items()
        for key in ("status", "as_of")
        if (item or {}).get(key) is None
    ]
    return {"positions": positions_missing, "thesis_status": thesis_missing}
