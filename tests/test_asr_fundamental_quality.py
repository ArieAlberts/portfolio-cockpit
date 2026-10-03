import json
from pathlib import Path
import pytest

from portfolio_cockpit.scoring.normalization import calculate_fundamental_quality
from portfolio_cockpit.scoring.peer_confidence import peer_metric_confidence

ROOT = Path(__file__).resolve().parents[1]


def load_asr():
    return json.loads((ROOT / "data/peers/ASR/2026-10-02.json").read_text(encoding="utf-8"))


def test_asr_peer_inputs_clear_confidence_gate():
    data = load_asr()
    for metric in ["solvency_ratio_pct", "combined_ratio_pct", "operating_earnings_growth_pct"]:
        result = peer_metric_confidence(dataset=data, metric_name=metric, minimum_peer_values=4)
        assert result.score >= 80


def test_asr_fundamental_quality_reproduces_snapshot():
    result = calculate_fundamental_quality(
        target_metrics={
            "solvency": 222,
            "combined": 91.6,
            "earnings_growth": 9.8,
        },
        peer_metrics={
            "solvency": [224,195,174,176],
            "combined": [90.5,95.2,83.6,93.3,92.7],
            "earnings_growth": [4.435204,6,9.924812,24,13],
        },
        metric_directions={
            "solvency": "higher_is_better",
            "combined": "lower_is_better",
            "earnings_growth": "higher_is_better",
        },
        metric_weights={
            "solvency": 0.30,
            "combined": 0.25,
            "earnings_growth": 0.20,
        },
        min_metric_coverage=0.70,
        minimum_peer_values=4,
    )
    assert result.status == "OK"
    assert result.score == pytest.approx(62.0917, abs=0.001)


def test_asr_snapshot_has_no_execution_effect():
    data = json.loads((ROOT / "data/scoring/fundamental_quality_2026-10-03.json").read_text(encoding="utf-8"))
    assert data["scores"]["ASR"]["execution_effect"] == "NONE"
