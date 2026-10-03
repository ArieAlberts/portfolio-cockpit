from portfolio_cockpit.scoring.readiness import evaluate_readiness


def _dataset():
    companies = {
        "X": {
            "period_alignment": "ALIGNED",
            "metrics": {
                "m": {
                    "value": 10.0,
                    "score_eligible": True,
                    "comparison_class": "M",
                }
            },
        }
    }
    for i, value in enumerate((8.0, 9.0, 11.0, 12.0), start=1):
        companies[f"P{i}"] = {
            "role": "PEER",
            "period_alignment": "ALIGNED",
            "metrics": {
                "m": {
                    "value": value,
                    "score_eligible": True,
                    "comparison_class": "M",
                }
            },
        }
    return {
        "target_ticker": "X",
        "peer_universe_status": "VALID",
        "rules": {"eligible_period_alignments": ["ALIGNED"]},
        "companies": companies,
    }


def test_unstable_never_becomes_display_ready():
    result = evaluate_readiness(
        dataset=_dataset(),
        company_type="TEST",
        component_weights={"c": 1.0},
        component_metric_aliases={"c": ["m"]},
        required_components=("c",),
        data_confidence_score=100.0,
        peer_input_confidence_score=100.0,
        stability_flag="UNSTABLE",
    )
    assert result.production_ready is False
    assert "UNSTABLE" in result.warnings


def test_only_stable_can_pass_sensitivity_gate():
    result = evaluate_readiness(
        dataset=_dataset(),
        company_type="TEST",
        component_weights={"c": 1.0},
        component_metric_aliases={"c": ["m"]},
        required_components=("c",),
        data_confidence_score=100.0,
        peer_input_confidence_score=100.0,
        stability_flag="STABLE",
    )
    assert result.production_ready is True
