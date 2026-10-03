from __future__ import annotations

from typing import Any


VALID_ANCHOR_STATUSES = {"STRONG", "ACCEPTABLE", "BELOW_ANCHOR"}


def classify_anchor(
    *,
    value: float,
    direction: str,
    strong_threshold: float,
    acceptable_threshold: float,
) -> str:
    value = float(value)
    strong = float(strong_threshold)
    acceptable = float(acceptable_threshold)

    if direction == "higher_is_better":
        if value >= strong:
            return "STRONG"
        if value >= acceptable:
            return "ACCEPTABLE"
        return "BELOW_ANCHOR"

    if direction == "lower_is_better":
        if value <= strong:
            return "STRONG"
        if value <= acceptable:
            return "ACCEPTABLE"
        return "BELOW_ANCHOR"

    raise ValueError(f"Unsupported anchor direction: {direction}")


def evaluate_absolute_anchors(
    *,
    dataset: dict[str, Any],
    company_type: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate target fundamentals against context-only absolute thresholds.

    Absolute anchors explain raw economic strength/weakness beside the relative
    peer score. They never modify Fundamental Quality, readiness or execution.
    """
    profile = config.get("profiles", {}).get(company_type, {})
    target = dataset["target_ticker"]
    target_metrics = dataset["companies"][target].get("metrics", {})

    results: dict[str, Any] = {}
    for metric_name, anchor in profile.items():
        metric = target_metrics.get(metric_name)
        if not metric or metric.get("value") is None:
            results[metric_name] = {
                "status": "MISSING",
                "value": None,
                "direction": anchor["direction"],
                "strong_threshold": float(anchor["strong_threshold"]),
                "acceptable_threshold": float(anchor["acceptable_threshold"]),
                "rationale": anchor.get("rationale"),
            }
            continue

        value = float(metric["value"])
        status = classify_anchor(
            value=value,
            direction=str(anchor["direction"]),
            strong_threshold=float(anchor["strong_threshold"]),
            acceptable_threshold=float(anchor["acceptable_threshold"]),
        )
        results[metric_name] = {
            "status": status,
            "value": value,
            "direction": anchor["direction"],
            "strong_threshold": float(anchor["strong_threshold"]),
            "acceptable_threshold": float(anchor["acceptable_threshold"]),
            "rationale": anchor.get("rationale"),
        }

    counts = {
        status: sum(item["status"] == status for item in results.values())
        for status in sorted(VALID_ANCHOR_STATUSES)
    }
    missing = sum(item["status"] == "MISSING" for item in results.values())

    return {
        "context_only": True,
        "affects_fundamental_quality_score": False,
        "affects_readiness": False,
        "configured_metrics": len(profile),
        "evaluated_metrics": len(profile) - missing,
        "counts": {**counts, "MISSING": missing},
        "metrics": results,
        "execution_effect": "NONE",
    }
