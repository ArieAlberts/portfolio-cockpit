from portfolio_cockpit.scoring.drift import (
    drift_from_weighted_signals,
    initial_quality_drift,
)


def test_baseline_is_exactly_50():
    assert initial_quality_drift() == 50.0


def test_zero_fundamental_change_stays_50():
    assert drift_from_weighted_signals(0.0) == 50.0


def test_positive_change_moves_above_50():
    assert drift_from_weighted_signals(0.2) == 60.0


def test_negative_change_moves_below_50():
    assert drift_from_weighted_signals(-0.2) == 40.0
