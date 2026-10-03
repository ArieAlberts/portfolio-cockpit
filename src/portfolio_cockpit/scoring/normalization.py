from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import mean, stdev


@dataclass(frozen=True)
class MetricScore:
    metric_name: str
    target_value: float
    peer_count: int
    peer_mean: float
    peer_std: float
    unclipped_z_score: float
    z_score: float
    weight: float
    direction: str


@dataclass(frozen=True)
class SensitivityResult:
    score_low: float
    score_high: float
    most_influential_metric: str
    most_influential_peer: str | None
    most_influential_peer_index: int
    largest_score_shift: float
    stability_flag: str
    scenarios_evaluated: int


@dataclass(frozen=True)
class FundamentalQualityResult:
    score: float | None
    status: str
    weighted_z: float | None
    coverage: float
    metric_scores: tuple[MetricScore, ...]
    sensitivity: SensitivityResult | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetricZDetails:
    clipped_z: float
    unclipped_z: float
    peer_mean: float
    peer_std: float
    peer_count: int


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _finite(values):
    return [float(v) for v in values if v is not None and isfinite(float(v))]


def metric_z_details(
    *,
    target_value: float,
    peer_values: list[float],
    direction: str,
    clip_z: float = 3.0,
    minimum_peer_values: int = 4,
) -> MetricZDetails:
    peers = _finite(peer_values)
    if len(peers) < minimum_peer_values:
        raise ValueError("INSUFFICIENT_PEER_METRIC_DATA")

    mu = mean(peers)
    sigma = stdev(peers)
    if sigma == 0:
        raise ValueError("ZERO_PEER_VARIANCE")

    raw_z = (float(target_value) - mu) / sigma
    if direction == "lower_is_better":
        raw_z = -raw_z
    elif direction != "higher_is_better":
        raise ValueError(f"Unsupported metric direction: {direction}")

    return MetricZDetails(
        clipped_z=clamp(raw_z, -clip_z, clip_z),
        unclipped_z=raw_z,
        peer_mean=mu,
        peer_std=sigma,
        peer_count=len(peers),
    )


def metric_z_score(
    *,
    target_value: float,
    peer_values: list[float],
    direction: str,
    clip_z: float = 3.0,
    minimum_peer_values: int = 4,
) -> tuple[float, float, float, int]:
    """Backward-compatible compact result using sample standard deviation."""
    d = metric_z_details(
        target_value=target_value,
        peer_values=peer_values,
        direction=direction,
        clip_z=clip_z,
        minimum_peer_values=minimum_peer_values,
    )
    return d.clipped_z, d.peer_mean, d.peer_std, d.peer_count


def _score_from_metric_scores(metric_scores: list[MetricScore]) -> tuple[float, float]:
    used_weight = sum(m.weight for m in metric_scores)
    if used_weight <= 0:
        raise ValueError("NO_SCOREABLE_METRICS")
    weighted_z = sum(m.weight * m.z_score for m in metric_scores) / used_weight
    return clamp(50.0 + 25.0 * weighted_z, 0.0, 100.0), weighted_z


def _leave_one_out_sensitivity(
    *,
    base_score: float,
    target_metrics: dict[str, float],
    peer_metrics: dict[str, list[float]],
    peer_labels: dict[str, list[str]] | None,
    metric_directions: dict[str, str],
    metric_weights: dict[str, float],
    used_metric_names: set[str],
    clip_z: float,
    minimum_sensitivity_peers: int = 3,
) -> SensitivityResult | None:
    scenarios: list[tuple[float, str, int, str | None]] = []

    for changed_metric in used_metric_names:
        values = list(peer_metrics.get(changed_metric, []))
        labels = (peer_labels or {}).get(changed_metric, [])
        if len(values) <= minimum_sensitivity_peers:
            continue

        for drop_index in range(len(values)):
            scenario_scores: list[MetricScore] = []
            valid = True
            for metric_name in used_metric_names:
                scenario_values = list(peer_metrics.get(metric_name, []))
                if metric_name == changed_metric:
                    scenario_values.pop(drop_index)
                try:
                    d = metric_z_details(
                        target_value=target_metrics[metric_name],
                        peer_values=scenario_values,
                        direction=metric_directions[metric_name],
                        clip_z=clip_z,
                        minimum_peer_values=minimum_sensitivity_peers,
                    )
                except ValueError:
                    valid = False
                    break
                scenario_scores.append(
                    MetricScore(
                        metric_name=metric_name,
                        target_value=float(target_metrics[metric_name]),
                        peer_count=d.peer_count,
                        peer_mean=d.peer_mean,
                        peer_std=d.peer_std,
                        unclipped_z_score=d.unclipped_z,
                        z_score=d.clipped_z,
                        weight=float(metric_weights[metric_name]),
                        direction=metric_directions[metric_name],
                    )
                )
            if not valid:
                continue
            score, _ = _score_from_metric_scores(scenario_scores)
            peer = labels[drop_index] if drop_index < len(labels) else None
            scenarios.append((score, changed_metric, drop_index, peer))

    if not scenarios:
        return None

    low = min(score for score, *_ in scenarios)
    high = max(score for score, *_ in scenarios)
    influential = max(scenarios, key=lambda row: abs(row[0] - base_score))
    width = high - low
    return SensitivityResult(
        score_low=low,
        score_high=high,
        most_influential_metric=influential[1],
        most_influential_peer=influential[3],
        most_influential_peer_index=influential[2],
        largest_score_shift=influential[0] - base_score,
        stability_flag="STABLE" if width < 10.0 else "PEER_SENSITIVE",
        scenarios_evaluated=len(scenarios),
    )


def calculate_fundamental_quality(
    *,
    target_metrics: dict[str, float],
    peer_metrics: dict[str, list[float]],
    metric_directions: dict[str, str],
    metric_weights: dict[str, float],
    min_metric_coverage: float = 0.70,
    clip_z: float = 3.0,
    minimum_peer_values: int = 4,
    peer_labels: dict[str, list[str]] | None = None,
) -> FundamentalQualityResult:
    """
    Calculate a peer-normalized Fundamental Quality score.

    Reference dispersion uses the sample standard deviation (n-1).
    Score conversion:
        score = clamp(50 + 25 * weighted_z, 0, 100)
    """
    total_configured_weight = sum(metric_weights.values())
    if total_configured_weight <= 0:
        raise ValueError("Metric weights must sum to a positive value.")

    used: list[MetricScore] = []
    warnings: list[str] = []
    used_weight = 0.0

    for metric_name, weight in metric_weights.items():
        if weight <= 0:
            continue

        target = target_metrics.get(metric_name)
        peers = peer_metrics.get(metric_name, [])
        direction = metric_directions.get(metric_name)

        if target is None:
            warnings.append(f"MISSING_TARGET:{metric_name}")
            continue
        if direction is None:
            warnings.append(f"MISSING_DIRECTION:{metric_name}")
            continue

        try:
            d = metric_z_details(
                target_value=target,
                peer_values=peers,
                direction=direction,
                clip_z=clip_z,
                minimum_peer_values=minimum_peer_values,
            )
        except ValueError as exc:
            warnings.append(f"{exc}:{metric_name}")
            continue

        if abs(d.unclipped_z) > clip_z:
            warnings.append(f"Z_CLIPPED:{metric_name}:{d.unclipped_z:.6f}")

        used.append(
            MetricScore(
                metric_name=metric_name,
                target_value=float(target),
                peer_count=d.peer_count,
                peer_mean=d.peer_mean,
                peer_std=d.peer_std,
                unclipped_z_score=d.unclipped_z,
                z_score=d.clipped_z,
                weight=float(weight),
                direction=direction,
            )
        )
        used_weight += weight

    coverage = used_weight / total_configured_weight

    if coverage < min_metric_coverage or used_weight == 0:
        return FundamentalQualityResult(
            score=None,
            status="PEER_DATA_CHECK",
            weighted_z=None,
            coverage=coverage,
            metric_scores=tuple(used),
            sensitivity=None,
            warnings=tuple(warnings),
        )

    score, weighted_z = _score_from_metric_scores(used)
    sensitivity = _leave_one_out_sensitivity(
        base_score=score,
        target_metrics=target_metrics,
        peer_metrics=peer_metrics,
        peer_labels=peer_labels,
        metric_directions=metric_directions,
        metric_weights=metric_weights,
        used_metric_names={m.metric_name for m in used},
        clip_z=clip_z,
    )

    return FundamentalQualityResult(
        score=score,
        status="OK",
        weighted_z=weighted_z,
        coverage=coverage,
        metric_scores=tuple(used),
        sensitivity=sensitivity,
        warnings=tuple(warnings),
    )
