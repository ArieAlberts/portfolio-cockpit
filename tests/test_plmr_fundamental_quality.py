import json
from pathlib import Path
import pytest

from portfolio_cockpit.scoring.normalization import calculate_fundamental_quality
from portfolio_cockpit.scoring.peer_confidence import peer_metric_confidence
from portfolio_cockpit.scoring.peer_data import eligible_metric_set

ROOT = Path(__file__).resolve().parents[1]


def load_plmr():
    return json.loads((ROOT / "data/peers/PLMR/2026-10-03.json").read_text(encoding="utf-8"))


def test_plmr_gaap_roe_has_four_aligned_peers():
    metric = eligible_metric_set(load_plmr(), "annualized_roe_pct", min_peers=4)
    assert metric.status == "READY"
    assert set(metric.peer_tickers) == {"KNSL", "SKWD", "HRTG", "HCI"}


def test_plmr_gaap_eps_growth_has_four_aligned_peers():
    metric = eligible_metric_set(load_plmr(), "gaap_eps_growth_pct", min_peers=4)
    assert metric.status == "READY"
    assert set(metric.peer_tickers) == {"KNSL", "SKWD", "HRTG", "RLI"}


def test_plmr_peer_confidence_clears_gate():
    data = load_plmr()
    for metric in ["combined_ratio_pct","annualized_roe_pct","gross_written_premium_growth_pct","gaap_eps_growth_pct"]:
        result = peer_metric_confidence(dataset=data, metric_name=metric, minimum_peer_values=4)
        assert result.score >= 80


def test_plmr_quality_snapshot_reproduces():
    result = calculate_fundamental_quality(
        target_metrics={
            "combined":83.8,
            "roe":19.9,
            "gwp":34.293922,
            "eps":8.333333,
        },
        peer_metrics={
            "combined":[76.4,90.0,72.9,85.8],
            "roe":[28.9,17.3,36.6,27.761428],
            "gwp":[-2.901624,12.802229,-4.143344,2.862101],
            "eps":[31.178311,10.447761,27.165354,19.211823],
        },
        metric_directions={
            "combined":"lower_is_better",
            "roe":"higher_is_better",
            "gwp":"higher_is_better",
            "eps":"higher_is_better",
        },
        metric_weights={
            "combined":0.25,
            "roe":0.20,
            "gwp":0.10,
            "eps":0.15,
        },
        min_metric_coverage=0.70,
        minimum_peer_values=4,
    )
    assert result.status == "OK"
    assert result.score == pytest.approx(40.1781, abs=0.002)


def test_plmr_has_no_execution_effect():
    data=json.loads((ROOT/"data/scoring/fundamental_quality_2026-10-03.json").read_text(encoding="utf-8"))
    assert data["scores"]["PLMR"]["execution_effect"] == "NONE"
