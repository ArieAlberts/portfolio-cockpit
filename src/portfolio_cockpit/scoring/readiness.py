from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .peer_data import eligible_metric_set


@dataclass(frozen=True)
class ReadinessResult:
    ticker: str
    weighted_component_coverage: float
    peer_coverage_pass: bool
    hard_blocked: bool
    production_ready: bool
    covered_components: tuple[str, ...]
    blocked_components: tuple[str, ...]
    ready_metrics: tuple[str, ...]
    warnings: tuple[str, ...]


def evaluate_readiness(
    *,
    dataset: dict,
    company_type: str,
    component_weights: Mapping[str, float],
    component_metric_aliases: Mapping[str, list[str]],
    minimum_peer_values_per_metric: int = 4,
    minimum_weighted_component_coverage: float = 0.70,
    hard_block_status_contains: tuple[str, ...] = (),
    data_confidence_score: float | None = None,
    data_confidence_threshold: float = 80.0,
    peer_input_confidence_score: float | None = None,
    peer_input_confidence_threshold: float = 80.0,
) -> ReadinessResult:
    target = dataset["target_ticker"]
    status = str(dataset.get("peer_universe_status", ""))
    hard_blocked = any(token in status for token in hard_block_status_contains)
    covered_components, blocked_components, ready_metrics, warnings = [], [], [], []

    for component in component_weights:
        component_ready = False
        for metric_name in component_metric_aliases.get(component, []):
            result = eligible_metric_set(dataset, metric_name, min_peers=minimum_peer_values_per_metric)
            if result.status == "READY":
                component_ready = True
                ready_metrics.append(metric_name)
        (covered_components if component_ready else blocked_components).append(component)

    coverage = sum(component_weights[c] for c in covered_components)
    peer_coverage_pass = coverage >= minimum_weighted_component_coverage

    if hard_blocked:
        warnings.append("HARD_PEER_UNIVERSE_BLOCK")
    if not peer_coverage_pass:
        warnings.append("INSUFFICIENT_WEIGHTED_COMPONENT_COVERAGE")
    if data_confidence_score is None:
        warnings.append("DATA_CONFIDENCE_PENDING")
    elif data_confidence_score < data_confidence_threshold:
        warnings.append("DATA_CONFIDENCE_BELOW_THRESHOLD")
    if peer_input_confidence_score is None:
        warnings.append("PEER_INPUT_CONFIDENCE_PENDING")
    elif peer_input_confidence_score < peer_input_confidence_threshold:
        warnings.append("PEER_INPUT_CONFIDENCE_BELOW_THRESHOLD")

    production_ready = (
        peer_coverage_pass and not hard_blocked
        and data_confidence_score is not None and data_confidence_score >= data_confidence_threshold
        and peer_input_confidence_score is not None and peer_input_confidence_score >= peer_input_confidence_threshold
    )

    return ReadinessResult(
        ticker=target,
        weighted_component_coverage=coverage,
        peer_coverage_pass=peer_coverage_pass,
        hard_blocked=hard_blocked,
        production_ready=production_ready,
        covered_components=tuple(covered_components),
        blocked_components=tuple(blocked_components),
        ready_metrics=tuple(sorted(set(ready_metrics))),
        warnings=tuple(warnings),
    )
