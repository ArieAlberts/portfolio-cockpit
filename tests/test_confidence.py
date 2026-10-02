from portfolio_cockpit.scoring.confidence import (
    data_confidence,
    decision_data_state,
)


def test_high_confidence_is_ok():
    score = data_confidence(
        completeness=100,
        source_quality=100,
        freshness=100,
        consistency=100,
    )
    assert score == 100
    assert decision_data_state(score) == "OK"


def test_low_confidence_triggers_data_check():
    score = data_confidence(
        completeness=50,
        source_quality=70,
        freshness=50,
        consistency=50,
    )
    assert decision_data_state(score) == "DATA_CHECK"
