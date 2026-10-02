import json
from pathlib import Path

from portfolio_cockpit.scoring.peer_data import eligible_metric_set


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/peers/ASR/2026-10-02.json"


def load_data():
    return json.loads(DATA.read_text(encoding="utf-8"))


def test_asr_solvency_has_four_aligned_solvent_ii_peers():
    metric = eligible_metric_set(load_data(), "solvency_ratio_pct")
    assert metric.status == "READY"
    assert len(metric.peer_values) >= 4
    assert "ZURN.SW" not in metric.peer_tickers


def test_zurich_sst_is_not_treated_as_solvency_ii():
    data = load_data()
    z = data["companies"]["ZURN.SW"]["metrics"]["solvency_ratio_pct"]
    assert z["comparison_class"] == "SWISS_SOLVENCY_TEST_RATIO"
    assert z["score_eligible"] is False


def test_operating_earnings_growth_has_enough_peers():
    metric = eligible_metric_set(load_data(), "operating_earnings_growth_pct")
    assert metric.status == "READY"
    assert len(metric.peer_values) >= 3


def test_capital_generation_growth_has_enough_peers():
    metric = eligible_metric_set(load_data(), "operating_capital_generation_growth_pct")
    assert metric.status == "READY"
    assert len(metric.peer_values) >= 3


def test_roe_is_blocked_until_definitions_are_harmonized():
    data = load_data()
    assert data["companies"]["ASR"]["metrics"]["reported_roe_pct"]["score_eligible"] is False
    assert data["companies"]["AV.L"]["metrics"]["reported_roe_pct"]["score_eligible"] is False


def test_combined_ratio_keeps_scope_notes():
    data = load_data()
    for ticker in ["ASR","NN.AS","AGS.BR","SAMPO.HE","AV.L","ZURN.SW"]:
        metric = data["companies"][ticker]["metrics"]["combined_ratio_pct"]
        assert metric["source_definition"]
