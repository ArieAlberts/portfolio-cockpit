from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import mean, pstdev


@dataclass(frozen=True)
class MetricScore:
    metric_name: str
    target_value: float
    peer_count: int
    peer_mean: float
    peer_std: float
    z_score: float
    weight: float
    direction: str


@dataclass(frozen=True)
class FundamentalQualityResult:
    score: float | None
    status: str
    weighted_z: float | None
    coverage: float
    metric_scores: tuple[MetricScore, ...]
    warnings: tuple[str, ...] = ()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _finite(values):
    return [float(v) for v in values if v is not None and isfinite(float(v))]


def metric_z_score(
    *,
    target_value: float,
    peer_values: list[float],
    direction: str,
    clip_z: float = 3.0,
    minimum_peer_values: int = 3,
) -> tuple[float, float, float, int]:
    """
    Compare the target with a peer-only reference distribution.

    direction:
      - higher_is_better
      - lower_is_better

    The resulting z-score is clipped to reduce the influence of outliers.
    """
    peers = _finite(peer_values)
    if len(peers) < minimum_peer_values:
        raise ValueError("INSUFFICIENT_PEER_METRIC_DATA")

    mu = mean(peers)
    sigma = pstdev(peers)
    if sigma == 0:
        raise ValueError("ZERO_PEER_VARIANCE")

    z = (float(target_value) - mu) / sigma
    if direction == "lower_is_better":
        z = -z
    elif direction != "higher_is_better":
        raise ValueError(f"Unsupported metric direction: {direction}")

    return clamp(z, -clip_z, clip_z), mu, sigma, len(peers)


def calculate_fundamental_quality(
    *,
    target_metrics: dict[str, float],
    peer_metrics: dict[str, list[float]],
    metric_directions: dict[str, str],
    metric_weights: dict[str, float],
    min_metric_coverage: float = 0.70,
    clip_z: float = 3.0,
    minimum_peer_values: int = 3,
) -> FundamentalQualityResult:
    """
    Calculate a peer-normalized Fundamental Quality score.

    Score conversion:
        score = clamp(50 + 25 * weighted_z, 0, 100)

    Missing/invalid metrics are omitted, then remaining weights are
    re-normalized. A final score is blocked if weighted coverage is below
    min_metric_coverage.
    """
    total_configured_weight = sum(metric_weights.values())
    if total_configured_weight <= 0:
        raise ValueError("Metric weights must sum to a positive value.")

    used: list[MetricScore] = []
    warnings: list[str] = []
    used_weight = 0.0
    weighted_z_sum = 0.0

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
            z, mu, sigma, peer_count = metric_z_score(
                target_value=target,
                peer_values=peers,
                direction=direction,
                clip_z=clip_z,
                minimum_peer_values=minimum_peer_values,
            )
        except ValueError as exc:
            warnings.append(f"{exc}:{metric_name}")
            continue

        used.append(
            MetricScore(
                metric_name=metric_name,
                target_value=float(target),
                peer_count=peer_count,
                peer_mean=mu,
                peer_std=sigma,
                z_score=z,
                weight=float(weight),
                direction=direction,
            )
        )
        used_weight += weight
        weighted_z_sum += weight * z

    coverage = used_weight / total_configured_weight

    if coverage < min_metric_coverage or used_weight == 0:
        return FundamentalQualityResult(
            score=None,
            status="PEER_DATA_CHECK",
            weighted_z=None,
            coverage=coverage,
            metric_scores=tuple(used),
            warnings=tuple(warnings),
        )

    weighted_z = weighted_z_sum / used_weight
    score = clamp(50.0 + 25.0 * weighted_z, 0.0, 100.0)

    return FundamentalQualityResult(
        score=score,
        status="OK",
        weighted_z=weighted_z,
        coverage=coverage,
        metric_scores=tuple(used),
        warnings=tuple(warnings),
    )
