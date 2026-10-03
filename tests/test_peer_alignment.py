from portfolio_cockpit.monitoring.peer_alignment import evaluate_peer_alignment


def test_new_target_period_waits_for_old_peer_period():
    result=evaluate_peer_alignment(
        target_reporting_period="Q3_2026",
        peer_dataset={
            "strict_reference_period":"H1_2026",
            "peer_universe_status":"VALIDATED",
        },
    )
    assert result.status=="PENDING_PEERS"
    assert result.score_recalculation_allowed is False


def test_aligned_period_moves_only_to_scoring_review():
    result=evaluate_peer_alignment(
        target_reporting_period="Q3_2026",
        peer_dataset={
            "strict_reference_period":"Q3_2026",
            "peer_universe_status":"VALIDATED",
        },
    )
    assert result.status=="PEERS_ALIGNED_FOR_SCORING_REVIEW"
    assert result.score_recalculation_allowed is False


def test_insufficient_peer_universe_stays_blocked():
    result=evaluate_peer_alignment(
        target_reporting_period="H1_2026",
        peer_dataset={
            "strict_reference_period":"H1_2026",
            "peer_universe_status":"INSUFFICIENT_DIRECT_PEERS",
        },
    )
    assert result.status=="PEER_UNIVERSE_BLOCKED"
