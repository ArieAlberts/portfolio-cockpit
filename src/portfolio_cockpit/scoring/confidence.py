from __future__ import annotations


def data_confidence(
    *,
    completeness: float,
    source_quality: float,
    freshness: float,
    consistency: float,
) -> float:
    values = (completeness, source_quality, freshness, consistency)
    if any(v < 0 or v > 100 for v in values):
        raise ValueError("Confidence components must be between 0 and 100.")

    return (
        0.30 * completeness
        + 0.30 * source_quality
        + 0.20 * freshness
        + 0.20 * consistency
    )


def decision_data_state(score: float, threshold: float = 80.0) -> str:
    return "OK" if score >= threshold else "DATA_CHECK"
