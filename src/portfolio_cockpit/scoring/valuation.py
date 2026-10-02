from __future__ import annotations


def valuation_score_from_weighted_z(weighted_attractiveness_z: float) -> float:
    """
    50 = peer/historical neutral valuation.
    Higher = more attractive/cheaper, subject to economically valid metrics.
    """
    return max(0.0, min(100.0, 50.0 + 25.0 * weighted_attractiveness_z))
