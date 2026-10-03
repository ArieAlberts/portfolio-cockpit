from copy import deepcopy
from pathlib import Path

import pytest

from portfolio_cockpit.scoring.drift import (
    QualityDriftConfigError,
    calculate_quality_drift,
    evaluate_quality_drift_update,
    initial_quality_drift,
    load_quality_drift_config,
    profile_weights,
    validate_quality_drift_config,
)


ROOT = Path(__file__).resolve().parents[1]


def test_all_drift_profiles_are_normalized_and_baseline_is_exactly_50():
    config = load_quality_drift_config(ROOT)
    assert initial_quality_drift() == 50.0
    for company_type in config["profiles"]:
        weights = profile_weights(config, company_type)
        assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_full_positive_and_negative_evidence_map_to_scale_ends():
    weights = {"a": 0.6, "b": 0.4}
    positive = calculate_quality_drift(
        component_signals={"a": 1.0, "b": 1.0},
        component_weights=weights,
    )
    negative = calculate_quality_drift(
        component_signals={"a": -1.0, "b": -1.0},
        component_weights=weights,
    )
    assert positive.score == 100.0
    assert negative.score == 0.0


def test_missing_components_are_neutral_not_reweighted():
    result = calculate_quality_drift(
        component_signals={"a": 1.0},
        component_weights={"a": 0.25, "b": 0.75},
    )
    assert result.score == 62.5
    assert result.weighted_signal == 0.25
    assert result.signal_coverage == 0.25


def test_no_new_evidence_remains_exactly_at_baseline():
    result = calculate_quality_drift(
        component_signals={},
        component_weights={"a": 1.0},
    )
    assert result.status == "BASELINE"
    assert result.score == 50.0


def test_invalid_or_unvalidated_updates_do_not_receive_a_score():
    config = load_quality_drift_config(ROOT)
    weights = profile_weights(config, "GENERAL_OPERATING_COMPANY")

    bad_trigger = evaluate_quality_drift_update(
        component_signals={"balance_sheet": 0.5},
        component_weights=weights,
        trigger="market_price",
        source_validated=True,
        source_confidence_score=100,
        config=config,
    )
    assert bad_trigger.status == "DATA_CHECK"
    assert bad_trigger.score is None
    assert "UPDATE_TRIGGER_NOT_ALLOWED" in bad_trigger.warnings

    unvalidated = evaluate_quality_drift_update(
        component_signals={"balance_sheet": 0.5},
        component_weights=weights,
        trigger="official_results",
        source_validated=False,
        source_confidence_score=100,
        config=config,
    )
    assert unvalidated.score is None
    assert "SOURCE_NOT_VALIDATED" in unvalidated.warnings


def test_valid_update_is_accepted_only_above_confidence_gate():
    config = load_quality_drift_config(ROOT)
    weights = profile_weights(config, "GENERAL_OPERATING_COMPANY")

    low = evaluate_quality_drift_update(
        component_signals={"balance_sheet": 0.5},
        component_weights=weights,
        trigger="official_results",
        source_validated=True,
        source_confidence_score=79.9,
        config=config,
    )
    assert low.status == "DATA_CHECK"
    assert low.score is None

    ok = evaluate_quality_drift_update(
        component_signals={"balance_sheet": 0.5},
        component_weights=weights,
        trigger="official_results",
        source_validated=True,
        source_confidence_score=80,
        config=config,
    )
    assert ok.status == "UPDATED"
    assert ok.score == 56.25


def test_signal_outside_normalized_range_is_rejected():
    with pytest.raises(ValueError, match=r"\[-1, \+1\]"):
        calculate_quality_drift(
            component_signals={"a": 1.01},
            component_weights={"a": 1.0},
        )


def test_config_rejects_price_as_drift_trigger():
    config = load_quality_drift_config(ROOT)
    broken = deepcopy(config)
    broken["allowed_update_triggers"].append("price")
    with pytest.raises(QualityDriftConfigError, match="market-price"):
        validate_quality_drift_config(broken)
