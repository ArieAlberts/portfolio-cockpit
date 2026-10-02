from __future__ import annotations


BASELINE_DRIFT_SCORE = 50.0


def initial_quality_drift() -> float:
    return BASELINE_DRIFT_SCORE


def drift_from_weighted_signals(weighted_signal: float) -> float:
    """
    weighted_signal is expected in [-1, +1].
    -1 -> 0
     0 -> 50
    +1 -> 100

    Price data must never be used as an input to this function.
    """
    weighted_signal = max(-1.0, min(1.0, weighted_signal))
    return 50.0 + 50.0 * weighted_signal
