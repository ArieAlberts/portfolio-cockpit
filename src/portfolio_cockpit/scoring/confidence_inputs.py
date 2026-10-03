from __future__ import annotations

from datetime import date
from typing import Mapping


def weighted_baseline_completeness(
    *,
    baseline: dict,
    component_weights: Mapping[str, float],
    component_aliases: Mapping[str, list[str]] | None = None,
) -> float:
    metric_groups = set((baseline.get("metrics") or {}).keys())
    aliases = component_aliases or {}
    covered = 0.0

    for component, weight in component_weights.items():
        candidate_groups = aliases.get(component, [component])
        if any(group in metric_groups for group in candidate_groups):
            covered += float(weight)

    return max(0.0, min(100.0, covered * 100.0))


def source_quality_score(source_type: str, scores: Mapping[str, float]) -> float:
    return float(scores.get(source_type, scores.get("UNKNOWN", 0.0)))


def freshness_score(
    *,
    as_of: date,
    source_date: date,
    bands: list[dict],
) -> float:
    age_days = max(0, (as_of - source_date).days)
    for band in sorted(bands, key=lambda item: int(item["max_age_days"])):
        if age_days <= int(band["max_age_days"]):
            return float(band["score"])
    return 0.0


def minimum_consistency_needed(
    *,
    completeness: float,
    source_quality: float,
    freshness: float,
    threshold: float = 80.0,
) -> float:
    known = 0.30 * completeness + 0.30 * source_quality + 0.20 * freshness
    required = (threshold - known) / 0.20
    return max(0.0, min(100.0, required))
