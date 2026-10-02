from __future__ import annotations


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def z_to_quality_score(weighted_z: float) -> float:
    """
    Convert a peer-normalized weighted z-score to a 0–100 score.

    50 is the peer median (z=0).
    A z-score of +2 maps to 100; -2 maps to 0.
    Extreme values are clamped.

    Production code should calculate component z-scores from a validated
    peer universe and winsorize inputs before aggregation.
    """
    return clamp(50.0 + 25.0 * weighted_z)
