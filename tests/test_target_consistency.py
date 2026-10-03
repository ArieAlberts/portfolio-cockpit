import json
from pathlib import Path

from portfolio_cockpit.scoring.readiness import evaluate_readiness

ROOT = Path(__file__).resolve().parents[1]


def test_all_target_confidence_scores_are_explicit_and_pass_threshold():
    data = json.loads((ROOT / "data/confidence/2026-10-03.json").read_text(encoding="utf-8"))
    assert len(data["results"]) == 23
    assert all(r["data_confidence_score"] is not None for r in data["results"].values())
    assert all(r["status"] == "OK" for r in data["results"].values())


def test_production_requires_peer_input_confidence():
    dataset = {
        "target_ticker": "X",
        "peer_universe_status": "VALID",
        "rules": {"eligible_period_alignments": ["ALIGNED"]},
        "companies": {
            "X": {"period_alignment": "ALIGNED", "metrics": {"m": {"value": 10, "score_eligible": True, "comparison_class": "M"}}},
            "P1": {"role": "PEER", "period_alignment": "ALIGNED", "metrics": {"m": {"value": 9, "score_eligible": True, "comparison_class": "M"}}},
            "P2": {"role": "PEER", "period_alignment": "ALIGNED", "metrics": {"m": {"value": 8, "score_eligible": True, "comparison_class": "M"}}},
            "P3": {"role": "PEER", "period_alignment": "ALIGNED", "metrics": {"m": {"value": 11, "score_eligible": True, "comparison_class": "M"}}},
            "P4": {"role": "PEER", "period_alignment": "ALIGNED", "metrics": {"m": {"value": 12, "score_eligible": True, "comparison_class": "M"}}},
        },
    }
    result = evaluate_readiness(
        dataset=dataset,
        company_type="T",
        component_weights={"c": 1.0},
        component_metric_aliases={"c": ["m"]},
        data_confidence_score=95,
        peer_input_confidence_score=None,
    )
    assert result.peer_coverage_pass is True
    assert result.production_ready is False
    assert "PEER_INPUT_CONFIDENCE_PENDING" in result.warnings
