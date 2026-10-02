from __future__ import annotations


def portfolio_impact(position_weight: float, shock: float) -> float:
    """
    Decimal inputs and output.

    Example:
        position_weight=0.05
        shock=-0.30
        result=-0.015  -> -1.5 percentage points
    """
    return position_weight * shock
