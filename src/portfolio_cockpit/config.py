from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


VALID_DIRECTIONS = {"higher_is_better", "lower_is_better"}
VALID_KINDS = {
    "ratio",
    "percentage",
    "currency",
    "currency_millions",
    "currency_per_unit",
    "physical_volume",
    "duration_months",
    "share_count_millions",
    "score",
    "amount",
    "count",
}


class ConfigValidationError(ValueError):
    """Raised when repository configuration is internally inconsistent."""


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigValidationError(f"{path}: expected a YAML mapping")
    return data


def load_config(root: Path) -> dict[str, dict[str, Any]]:
    config = {
        "portfolio": _read_yaml(root / "config/portfolio.yaml"),
        "company_types": _read_yaml(root / "config/company_types.yaml"),
        "readiness": _read_yaml(root / "config/readiness.yaml"),
        "scoring": _read_yaml(root / "config/scoring.yaml"),
        "score_metrics": _read_yaml(root / "config/score_metrics.yaml"),
        "peer_universes": _read_yaml(root / "config/peer_universes.yaml"),
    }
    validate_config(config)
    return config


def component_metric_aliases(
    config: dict[str, dict[str, Any]], company_type: str
) -> dict[str, list[str]]:
    return config["score_metrics"]["component_metric_aliases"][company_type]


def metric_directions(
    config: dict[str, dict[str, Any]], company_type: str
) -> dict[str, str]:
    return config["score_metrics"]["metric_directions"][company_type]


def component_metric_slots(
    config: dict[str, dict[str, Any]], company_type: str
) -> dict[str, dict[str, dict[str, Any]]]:
    return config["score_metrics"]["component_metric_slots"][company_type]


def validate_config(config: dict[str, dict[str, Any]]) -> None:
    errors: list[str] = []

    portfolio = config["portfolio"]
    company_types = config["company_types"]
    readiness = config["readiness"]
    scoring = config["scoring"]
    metric_cfg = config["score_metrics"]
    peer_universes = config["peer_universes"]

    if metric_cfg.get("schema_version") != 2:
        errors.append("score_metrics.schema_version must be 2")

    if "component_metric_aliases" in readiness:
        errors.append(
            "readiness.yaml must not define component_metric_aliases; "
            "score_metrics.yaml is canonical"
        )

    fq = scoring.get("fundamental_quality", {})
    if fq.get("peer_method") != "clipped_mean_sample_std_zscore":
        errors.append("fundamental_quality.peer_method is unsupported")

    peer_defaults = peer_universes.get("defaults", {})
    if peer_defaults.get("method") != fq.get("peer_method"):
        errors.append("peer_universes.defaults.method differs from scoring method")
    if abs(float(peer_defaults.get("clip_z", 0)) - float(fq.get("clip_z_score", 0))) > 1e-12:
        errors.append("peer_universes.defaults.clip_z differs from scoring clip_z")

    scoring_min_peers = int(fq.get("minimum_peer_values_per_metric", 0))
    readiness_min_peers = int(readiness.get("minimum_peer_values_per_metric", 0))
    if scoring_min_peers < 4:
        errors.append("minimum_peer_values_per_metric must be at least 4")
    if scoring_min_peers != readiness_min_peers:
        errors.append(
            "minimum_peer_values_per_metric differs between scoring.yaml and readiness.yaml"
        )

    scoring_coverage = float(fq.get("minimum_metric_coverage", -1))
    readiness_coverage = float(readiness.get("minimum_weighted_component_coverage", -2))
    if not 0 < scoring_coverage <= 1:
        errors.append("fundamental_quality.minimum_metric_coverage must be in (0, 1]")
    if abs(scoring_coverage - readiness_coverage) > 1e-12:
        errors.append(
            "minimum coverage differs between scoring.yaml and readiness.yaml"
        )

    clip_z = float(fq.get("clip_z_score", 0))
    if clip_z <= 0:
        errors.append("fundamental_quality.clip_z_score must be positive")

    sensitivity = fq.get("sensitivity", {})
    stable = float(sensitivity.get("stable_band_width_points", 0))
    unstable = float(sensitivity.get("unstable_band_width_points", 0))
    if not 0 < stable < unstable:
        errors.append(
            "sensitivity thresholds must satisfy 0 < stable_band_width_points "
            "< unstable_band_width_points"
        )
    if int(sensitivity.get("diagnostic_minimum_peer_values", 0)) < 3:
        errors.append("diagnostic_minimum_peer_values must be at least 3")
    if int(sensitivity.get("robust_method_reconsider_at_peer_count", 0)) < scoring_min_peers:
        errors.append(
            "robust_method_reconsider_at_peer_count must be >= production peer minimum"
        )

    aliases_by_type = metric_cfg.get("component_metric_aliases", {})
    directions_by_type = metric_cfg.get("metric_directions", {})
    slots_by_type = metric_cfg.get("component_metric_slots", {})
    kinds = metric_cfg.get("metric_kinds", {})

    for company_type, type_cfg in company_types.items():
        components = type_cfg.get("quality_components", {})
        if not components:
            errors.append(f"{company_type}: no quality_components")
            continue

        total = sum(float(v) for v in components.values())
        if abs(total - 1.0) > 1e-9:
            errors.append(f"{company_type}: component weights sum to {total}, not 1.0")

        required = set(type_cfg.get("required_components", ()))
        unknown_required = required - set(components)
        if unknown_required:
            errors.append(
                f"{company_type}: unknown required components {sorted(unknown_required)}"
            )

        aliases = aliases_by_type.get(company_type)
        directions = directions_by_type.get(company_type)
        slots = slots_by_type.get(company_type)
        if aliases is None:
            errors.append(f"{company_type}: missing component_metric_aliases")
            continue
        if directions is None:
            errors.append(f"{company_type}: missing metric_directions")
            continue
        if slots is None:
            errors.append(f"{company_type}: missing component_metric_slots")
            continue

        if set(aliases) != set(components):
            missing = sorted(set(components) - set(aliases))
            extra = sorted(set(aliases) - set(components))
            errors.append(
                f"{company_type}: component registry mismatch; missing={missing}, extra={extra}"
            )

        if set(slots) != set(components):
            missing = sorted(set(components) - set(slots))
            extra = sorted(set(slots) - set(components))
            errors.append(
                f"{company_type}: metric slot component mismatch; "
                f"missing={missing}, extra={extra}"
            )

        seen: dict[str, str] = {}
        for component, metric_names in aliases.items():
            if not metric_names:
                errors.append(f"{company_type}:{component}: empty metric alias list")
            for metric_name in metric_names:
                previous = seen.get(metric_name)
                if previous is not None and previous != component:
                    errors.append(
                        f"{company_type}:{metric_name}: assigned to both "
                        f"{previous} and {component}"
                    )
                seen[metric_name] = component

                direction = directions.get(metric_name)
                if direction not in VALID_DIRECTIONS:
                    errors.append(
                        f"{company_type}:{metric_name}: invalid or missing direction "
                        f"{direction!r}"
                    )
                kind = kinds.get(metric_name)
                if kind not in VALID_KINDS:
                    errors.append(
                        f"{company_type}:{metric_name}: invalid or missing kind {kind!r}"
                    )

            component_slots = slots.get(component, {})
            slot_weight_sum = sum(float(s.get("weight", 0)) for s in component_slots.values())
            if abs(slot_weight_sum - 1.0) > 1e-9:
                errors.append(
                    f"{company_type}:{component}: slot weights sum to "
                    f"{slot_weight_sum}, not 1.0"
                )

            slotted: list[str] = []
            for slot_name, slot_cfg in component_slots.items():
                weight = float(slot_cfg.get("weight", 0))
                if weight <= 0:
                    errors.append(
                        f"{company_type}:{component}:{slot_name}: slot weight must be positive"
                    )
                slot_aliases = list(slot_cfg.get("aliases", ()))
                if not slot_aliases:
                    errors.append(
                        f"{company_type}:{component}:{slot_name}: empty aliases"
                    )
                slotted.extend(slot_aliases)

            if len(slotted) != len(set(slotted)):
                errors.append(
                    f"{company_type}:{component}: metric alias appears in multiple slots"
                )
            if set(slotted) != set(metric_names):
                missing = sorted(set(metric_names) - set(slotted))
                extra = sorted(set(slotted) - set(metric_names))
                errors.append(
                    f"{company_type}:{component}: slot aliases mismatch; "
                    f"missing={missing}, extra={extra}"
                )

    component_metric_threshold = float(
        fq.get("minimum_component_metric_weight_coverage", 0)
    )
    if not 0 < component_metric_threshold <= 1:
        errors.append(
            "fundamental_quality.minimum_component_metric_weight_coverage "
            "must be in (0, 1]"
        )

    positions = portfolio.get("positions", {})
    if not positions:
        errors.append("portfolio.positions is empty")

    universes = peer_universes.get("universes", {})
    global_peer_minimum = int(peer_defaults.get("minimum_peer_count", scoring_min_peers))
    if global_peer_minimum != scoring_min_peers:
        errors.append("peer_universes default minimum differs from scoring minimum")

    for ticker, position in positions.items():
        company_type = position.get("company_type")
        if company_type not in company_types:
            errors.append(f"{ticker}: unknown company_type {company_type!r}")
        if company_type not in aliases_by_type:
            errors.append(f"{ticker}: no metric registry for {company_type!r}")
        if ticker not in universes:
            errors.append(f"{ticker}: missing peer universe")

    for ticker, universe in universes.items():
        status = str(universe.get("status", ""))
        peers = list(universe.get("peers", ()))
        declared_minimum = int(universe.get("minimum_peer_count", global_peer_minimum))
        if declared_minimum < scoring_min_peers and status not in {"LIMITED", "INSUFFICIENT"}:
            errors.append(
                f"{ticker}: minimum_peer_count {declared_minimum} below production minimum "
                f"{scoring_min_peers} without LIMITED/INSUFFICIENT status"
            )
        if status == "VALIDATE" and len(peers) < scoring_min_peers:
            errors.append(
                f"{ticker}: VALIDATE universe has only {len(peers)} peers; "
                f"minimum is {scoring_min_peers}"
            )

    if errors:
        raise ConfigValidationError(
            "Configuration validation failed:\n- " + "\n- ".join(errors)
        )
