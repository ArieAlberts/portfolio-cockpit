from datetime import date

from portfolio_cockpit.scoring.confidence_inputs import (
    freshness_score,
    minimum_consistency_needed,
    source_quality_score,
    weighted_baseline_completeness,
)


def test_weighted_completeness_uses_component_weights():
    baseline = {"metrics": {"balance_sheet": {}, "growth_stability": {}}}
    score = weighted_baseline_completeness(
        baseline=baseline,
        component_weights={
            "balance_sheet": 0.25,
            "profitability_capital_efficiency": 0.25,
            "cashflow_quality": 0.20,
            "growth_stability": 0.15,
            "value_per_share": 0.15,
        },
    )
    assert score == 40.0


def test_fresh_primary_source_scores_100():
    assert source_quality_score("SEC_FILING", {"SEC_FILING": 100, "UNKNOWN": 0}) == 100
    score = freshness_score(
        as_of=date(2026, 10, 3),
        source_date=date(2026, 8, 5),
        bands=[{"max_age_days": 120, "score": 100}],
    )
    assert score == 100


def test_minimum_consistency_needed_for_55_completeness():
    needed = minimum_consistency_needed(
        completeness=55,
        source_quality=100,
        freshness=100,
        threshold=80,
    )
    assert needed == 67.5
