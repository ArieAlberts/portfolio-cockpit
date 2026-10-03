from __future__ import annotations

from typing import Any


VALID_ANCHOR_OPERATORS = {"lt", "le", "gt", "ge"}


def evaluate_absolute_anchor(
    *,
    metric_name: str,
    value: float,
    company_type: str,
    anchors_config: dict[str, Any],
) -> dict[str, Any] | None:
    """Evaluate an objective absolute threshold without affecting peer scoring."""
    anchor = anchors_config.get("anchors", {}).get(metric_name)
    if anchor is None:
        return None

    applies_to = tuple(anchor.get("applies_to", ()))
    if applies_to and company_type not in applies_to:
        return None

    operator = anchor["operator"]
    threshold = float(anchor["threshold"])
    numeric_value = float(value)

    comparisons = {
        "lt": numeric_value < threshold,
        "le": numeric_value <= threshold,
        "gt": numeric_value > threshold,
        "ge": numeric_value >= threshold,
    }
    met = comparisons[operator]

    return {
        "metric_name": metric_name,
        "value": numeric_value,
        "operator": operator,
        "threshold": threshold,
        "anchor_type": anchor["anchor_type"],
        "status": "MEETS_ANCHOR" if met else "DOES_NOT_MEET_ANCHOR",
        "interpretation": (
            anchor["label_if_met"] if met else anchor["label_if_not_met"]
        ),
        "rationale": anchor["rationale"],
        "source": dict(anchor["source"]),
        "score_effect": "NONE",
    }
