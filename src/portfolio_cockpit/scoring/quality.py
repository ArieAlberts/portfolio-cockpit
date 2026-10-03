from __future__ import annotations


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def z_to_quality_score(weighted_z: float) -> float:
    """Convert a peer-normalized weighted z-score to a 0–100 score.

    Under the mean/sample-standard-deviation method, 50 corresponds to the
    peer mean (z=0), not the peer median.
    """
    return clamp(50.0 + 25.0 * weighted_z)
