import pytest

from portfolio_cockpit.scoring.pipeline import _select_component_metrics


def _metric(value):
    return {
        "value": value,
        "score_eligible": True,
        "comparison_class": "TEST",
    }


def _dataset(*, include_primary=True, include_secondary=True):
    companies = {
        "X": {"period_alignment": "ALIGNED", "metrics": {}},
    }
    if include_primary:
        companies["X"]["metrics"]["primary"] = _metric(10.0)
    if include_secondary:
        companies["X"]["metrics"]["secondary"] = _metric(20.0)

    for i in range(1, 5):
        metrics = {}
        if include_primary:
            metrics["primary"] = _metric(8.0 + i)
        if include_secondary:
            metrics["secondary"] = _metric(18.0 + i)
        companies[f"P{i}"] = {
            "role": "PEER",
            "period_alignment": "ALIGNED",
            "metrics": metrics,
        }

    return {
        "target_ticker": "X",
        "peer_universe_status": "VALID",
        "rules": {"eligible_period_alignments": ["ALIGNED"]},
        "companies": companies,
    }


SLOTS = {
    "quality": {
        "primary_signal": {"weight": 0.75, "aliases": ["primary"]},
        "secondary_signal": {"weight": 0.25, "aliases": ["secondary"]},
    }
}
DIRECTIONS = {
    "primary": "higher_is_better",
    "secondary": "higher_is_better",
}


def test_multiple_ready_slots_preserve_configured_split():
    selected, warnings = _select_component_metrics(
        dataset=_dataset(),
        company_type="TEST",
        component_weights={"quality": 0.40},
        slots=SLOTS,
        directions=DIRECTIONS,
        minimum_peers=4,
        minimum_component_metric_weight_coverage=0.50,
    )
    assert warnings == []
    component = selected["quality"]
    assert component["metric_weight_coverage"] == pytest.approx(1.0)
    by_slot = {m["slot_name"]: m for m in component["metrics"]}
    assert by_slot["primary_signal"]["configured_metric_weight"] == pytest.approx(0.75)
    assert by_slot["secondary_signal"]["configured_metric_weight"] == pytest.approx(0.25)
    assert by_slot["primary_signal"]["effective_component_weight"] == pytest.approx(0.30)
    assert by_slot["secondary_signal"]["effective_component_weight"] == pytest.approx(0.10)


def test_available_weight_is_renormalized_only_after_minimum_coverage_passes():
    selected, warnings = _select_component_metrics(
        dataset=_dataset(include_secondary=False),
        company_type="TEST",
        component_weights={"quality": 0.40},
        slots=SLOTS,
        directions=DIRECTIONS,
        minimum_peers=4,
        minimum_component_metric_weight_coverage=0.50,
    )
    assert warnings == []
    component = selected["quality"]
    assert component["metric_weight_coverage"] == pytest.approx(0.75)
    metric = component["metrics"][0]
    assert metric["configured_metric_weight"] == pytest.approx(0.75)
    assert metric["effective_metric_weight_within_component"] == pytest.approx(1.0)
    assert metric["effective_component_weight"] == pytest.approx(0.40)


def test_component_is_not_scored_when_only_low_weight_slot_is_available():
    selected, warnings = _select_component_metrics(
        dataset=_dataset(include_primary=False),
        company_type="TEST",
        component_weights={"quality": 0.40},
        slots=SLOTS,
        directions=DIRECTIONS,
        minimum_peers=4,
        minimum_component_metric_weight_coverage=0.50,
    )
    assert "quality" not in selected
    assert any(
        warning.startswith("COMPONENT_METRIC_COVERAGE_BELOW_THRESHOLD:TEST:quality:0.250000")
        for warning in warnings
    )
