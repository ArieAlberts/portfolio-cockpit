from portfolio_cockpit.scoring.confidence import (
    data_confidence_result,
    decision_data_state,
)


def test_pending_confidence_component_blocks_publication():
    result = data_confidence_result(
        completeness=90,
        source_quality=100,
        freshness=100,
        consistency=None,
    )
    assert result.score is None
    assert result.status == "DATA_CHECK"
    assert result.missing_components == ("consistency",)


def test_none_score_is_data_check():
    assert decision_data_state(None) == "DATA_CHECK"
