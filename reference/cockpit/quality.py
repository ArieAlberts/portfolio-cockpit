"""QUALITY-module.

quality_score = clamp(50 + 50 * sum(metric_weight * normalized_signal), 0, 100)

50 = geen materiële fundamentele verandering t.o.v. de baseline.
Deze module krijgt bewust GEEN koers of marktdata binnen: een koersbeweging
kan de quality_score dus per constructie niet raken.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional

from .config import MetricSpec, QualityProfile


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True)
class Observation:
    metric_name: str
    raw_value: float
    source: str
    source_date: date
    confidence: float = 1.0


@dataclass
class MetricContribution:
    metric_name: str
    category: str
    metric_weight: float
    baseline_value: Optional[float]
    raw_value: Optional[float]
    delta_vs_baseline: Optional[float]
    normalized_signal: float
    contribution_points: float  # bijdrage aan quality_score in punten (50 * w * s)
    source: Optional[str]
    source_date: Optional[str]
    status: str  # OK | MISSING | NO_BASELINE

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QualityResult:
    quality_score: float
    quality_change_since_baseline: float
    coverage: float  # aandeel van het profielgewicht met bruikbare data
    contributions: list[MetricContribution]
    max_abs_signal: float


def normalize(baseline_value: float, raw_value: float, spec: MetricSpec) -> tuple[float, float]:
    """Vertaal verandering t.o.v. baseline naar (delta, normalized_signal in [-1, 1])."""
    if spec.mode == "relative":
        if baseline_value == 0:
            raise ZeroDivisionError(f"relative-mode met baseline 0 voor {spec.name}")
        delta = (raw_value - baseline_value) / abs(baseline_value)
    else:  # absolute en direct
        delta = raw_value - baseline_value
    effective = 0.0 if abs(delta) < spec.dead_band else delta
    signal = clamp(effective / spec.full_scale, -1.0, 1.0)
    if spec.direction == "lower_better":
        signal = -signal
    return delta, signal + 0.0  # +0.0 voorkomt -0.0


def compute_quality(
    profile: QualityProfile,
    baseline: dict[str, float],
    observations: dict[str, Observation],
) -> QualityResult:
    total = 0.0
    covered = 0.0
    contribs: list[MetricContribution] = []
    max_abs = 0.0
    for name, spec in profile.metrics.items():
        base = baseline.get(name)
        obs = observations.get(name)
        if base is None:
            contribs.append(MetricContribution(name, spec.category, spec.weight, None,
                                               obs.raw_value if obs else None, None, 0.0, 0.0,
                                               obs.source if obs else None,
                                               str(obs.source_date) if obs else None, "NO_BASELINE"))
            continue
        if obs is None:
            contribs.append(MetricContribution(name, spec.category, spec.weight, base, None, None,
                                               0.0, 0.0, None, None, "MISSING"))
            continue
        delta, signal = normalize(base, obs.raw_value, spec)
        total += spec.weight * signal
        covered += spec.weight
        max_abs = max(max_abs, abs(signal))
        contribs.append(MetricContribution(
            name, spec.category, spec.weight, base, obs.raw_value, delta, signal,
            round(50 * spec.weight * signal, 4), obs.source, str(obs.source_date), "OK"))
    score = clamp(50.0 + 50.0 * total, 0.0, 100.0)
    return QualityResult(
        quality_score=round(score, 2),
        quality_change_since_baseline=round(score - 50.0, 2),
        coverage=round(covered, 4),
        contributions=contribs,
        max_abs_signal=max_abs,
    )
