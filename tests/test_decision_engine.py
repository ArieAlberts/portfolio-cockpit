from pathlib import Path

from portfolio_cockpit.scoring.decision import (
    DecisionInputs,
    evaluate_decision,
    load_decision_config,
)


ROOT = Path(__file__).resolve().parents[1]


def run(**kwargs):
    config = load_decision_config(ROOT)
    defaults = {
        "quality_drift_score": 50.0,
        "valuation_score": 50.0,
        "data_confidence_score": 90.0,
        "thesis_status": "INTACT",
        "fundamental_quality_score": None,
    }
    defaults.update(kwargs)
    return evaluate_decision(DecisionInputs(**defaults), config)


def test_confidence_gate_has_highest_priority():
    result = run(
        data_confidence_score=79.9,
        thesis_status="BROKEN",
        quality_drift_score=20,
    )
    assert result.state == "DATA_CHECK"
    assert result.execution_effect == "NONE"


def test_broken_thesis_precedes_quality_and_valuation_rules():
    result = run(thesis_status="BROKEN", quality_drift_score=20, valuation_score=90)
    assert result.state == "THESIS_REVIEW"


def test_material_quality_deterioration_requires_review_reduce():
    result = run(quality_drift_score=35, valuation_score=90)
    assert result.state == "REVIEW_REDUCE"


def test_strong_drift_and_attractive_valuation_create_add_candidate():
    result = run(quality_drift_score=60, valuation_score=70)
    assert result.state == "ADD_CANDIDATE"
    assert "FUNDAMENTAL_QUALITY_PENDING" in result.reasons


def test_display_ready_fundamental_quality_can_block_add_candidate():
    result = run(
        quality_drift_score=70,
        valuation_score=80,
        fundamental_quality_score=39.9,
    )
    assert result.state == "HOLD"
    assert result.reasons == ("FUNDAMENTAL_QUALITY_BELOW_ADD_FLOOR",)


def test_expensive_valuation_with_acceptable_quality_is_no_add():
    result = run(quality_drift_score=50, valuation_score=30)
    assert result.state == "NO_ADD"


def test_missing_valuation_is_explicit_but_not_data_check():
    result = run(valuation_score=None)
    assert result.state == "HOLD"
    assert result.reasons == ("VALUATION_PENDING",)


def test_neutral_case_is_hold():
    result = run(quality_drift_score=50, valuation_score=50)
    assert result.state == "HOLD"
