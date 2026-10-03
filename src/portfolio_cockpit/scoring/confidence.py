from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataConfidenceResult:
    score: float | None
    status: str
    missing_components: tuple[str, ...] = ()


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


def data_confidence_result(
    *,
    completeness: float | None,
    source_quality: float | None,
    freshness: float | None,
    consistency: float | None,
    threshold: float = 80.0,
) -> DataConfidenceResult:
    components = {
        "completeness": completeness,
        "source_quality": source_quality,
        "freshness": freshness,
        "consistency": consistency,
    }
    missing = tuple(name for name, value in components.items() if value is None)
    if missing:
        return DataConfidenceResult(
            score=None,
            status="DATA_CHECK",
            missing_components=missing,
        )

    score = data_confidence(
        completeness=float(completeness),
        source_quality=float(source_quality),
        freshness=float(freshness),
        consistency=float(consistency),
    )
    return DataConfidenceResult(
        score=score,
        status="OK" if score >= threshold else "DATA_CHECK",
    )


def decision_data_state(score: float | None, threshold: float = 80.0) -> str:
    if score is None:
        return "DATA_CHECK"
    return "OK" if score >= threshold else "DATA_CHECK"
