from statistics import mean, stdev

import pytest
from hypothesis import assume, given, strategies as st

from portfolio_cockpit.scoring.normalization import (
    calculate_fundamental_quality,
    metric_z_details,
)


peer_lists = st.lists(
    st.floats(
        min_value=-1_000,
        max_value=1_000,
        allow_nan=False,
        allow_infinity=False,
        width=32,
    ),
    min_size=4,
    max_size=12,
)


@given(peer_lists)
def test_peer_mean_maps_to_quality_50(peers):
    assume(stdev(peers) > 1e-6)
    result = calculate_fundamental_quality(
        target_metrics={"m": mean(peers)},
        peer_metrics={"m": peers},
        metric_directions={"m": "higher_is_better"},
        metric_weights={"m": 1.0},
        minimum_peer_values=4,
    )
    assert result.status == "OK"
    assert result.score == pytest.approx(50.0, abs=1e-9)


@given(
    peer_lists,
    st.floats(min_value=-2_000, max_value=2_000, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0, max_value=2_000, allow_nan=False, allow_infinity=False),
)
def test_higher_is_better_is_monotone(peers, start, increment):
    assume(stdev(peers) > 1e-6)
    lower = metric_z_details(
        target_value=start,
        peer_values=peers,
        direction="higher_is_better",
    )
    higher = metric_z_details(
        target_value=start + increment,
        peer_values=peers,
        direction="higher_is_better",
    )
    assert higher.clipped_z >= lower.clipped_z


@given(
    peer_lists,
    st.floats(min_value=-2_000, max_value=2_000, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0, max_value=2_000, allow_nan=False, allow_infinity=False),
)
def test_lower_is_better_is_monotone(peers, start, increment):
    assume(stdev(peers) > 1e-6)
    better = metric_z_details(
        target_value=start,
        peer_values=peers,
        direction="lower_is_better",
    )
    worse = metric_z_details(
        target_value=start + increment,
        peer_values=peers,
        direction="lower_is_better",
    )
    assert better.clipped_z >= worse.clipped_z


def test_z_score_is_clipped_but_raw_value_is_preserved():
    peers = [0.0, 1.0, 2.0, 3.0]
    high = metric_z_details(
        target_value=1_000_000.0,
        peer_values=peers,
        direction="higher_is_better",
        clip_z=3.0,
    )
    low = metric_z_details(
        target_value=-1_000_000.0,
        peer_values=peers,
        direction="higher_is_better",
        clip_z=3.0,
    )
    assert high.clipped_z == 3.0
    assert low.clipped_z == -3.0
    assert high.unclipped_z > 3.0
    assert low.unclipped_z < -3.0


def test_fewer_than_four_peers_never_scores():
    result = calculate_fundamental_quality(
        target_metrics={"m": 10.0},
        peer_metrics={"m": [8.0, 9.0, 11.0]},
        metric_directions={"m": "higher_is_better"},
        metric_weights={"m": 1.0},
        minimum_peer_values=4,
    )
    assert result.status == "PEER_DATA_CHECK"
    assert result.score is None
    assert result.coverage == 0.0
