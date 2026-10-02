import pytest

from portfolio_cockpit.scoring.normalization import (
    calculate_fundamental_quality,
    metric_z_score,
)


def test_peer_median_like_value_is_around_50():
    result = calculate_fundamental_quality(
        target_metrics={"roe": 10.0},
        peer_metrics={"roe": [8.0, 10.0, 12.0, 10.0]},
        metric_directions={"roe": "higher_is_better"},
        metric_weights={"roe": 1.0},
    )
    assert result.status == "OK"
    assert result.score == pytest.approx(50.0)


def test_higher_is_better_metric_rewards_stronger_target():
    result = calculate_fundamental_quality(
        target_metrics={"roe": 20.0},
        peer_metrics={"roe": [8.0, 10.0, 12.0, 14.0]},
        metric_directions={"roe": "higher_is_better"},
        metric_weights={"roe": 1.0},
    )
    assert result.score > 50


def test_lower_is_better_metric_rewards_lower_leverage():
    z, *_ = metric_z_score(
        target_value=1.0,
        peer_values=[2.0, 2.5, 3.0, 3.5],
        direction="lower_is_better",
    )
    assert z > 0


def test_insufficient_metric_coverage_blocks_score():
    result = calculate_fundamental_quality(
        target_metrics={"roe": 15.0},
        peer_metrics={"roe": [10.0, 12.0, 14.0, 16.0]},
        metric_directions={"roe": "higher_is_better", "leverage": "lower_is_better"},
        metric_weights={"roe": 0.4, "leverage": 0.6},
        min_metric_coverage=0.70,
    )
    assert result.score is None
    assert result.status == "PEER_DATA_CHECK"
    assert result.coverage == pytest.approx(0.4)


def test_zscore_is_clipped():
    z, *_ = metric_z_score(
        target_value=1000.0,
        peer_values=[1.0, 2.0, 3.0, 4.0],
        direction="higher_is_better",
        clip_z=3.0,
    )
    assert z == 3.0
