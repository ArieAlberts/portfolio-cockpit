import json
from pathlib import Path

from portfolio_cockpit.scoring.peer_data import eligible_metric_set

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data/peers/ASR/2026-10-02.json"


def load_data():
    return json.loads(DATA.read_text(encoding="utf-8"))


def test_aviva_is_solvency_uk_and_not_eu_solvency_ii_eligible():
    m=load_data()["companies"]["AV.L"]["metrics"]["solvency_ratio_pct"]
    assert m["comparison_class"]=="SOLVENCY_UK_RATIO"
    assert m["score_eligible"] is False


def test_asr_solvency_ii_now_has_only_three_eligible_peers_and_is_blocked():
    metric=eligible_metric_set(load_data(),"solvency_ratio_pct",min_peers=4)
    assert metric.status=="INSUFFICIENT_ALIGNED_PEERS"
    assert set(metric.peer_tickers)=={"NN.AS","AGS.BR","SAMPO.HE"}


def test_zurich_sst_remains_excluded():
    m=load_data()["companies"]["ZURN.SW"]["metrics"]["solvency_ratio_pct"]
    assert m["comparison_class"]=="SWISS_SOLVENCY_TEST_RATIO"
    assert m["score_eligible"] is False


def test_operating_earnings_growth_still_has_four_plus_peers():
    metric=eligible_metric_set(load_data(),"operating_earnings_growth_pct",min_peers=4)
    assert metric.status=="READY"


def test_capital_generation_does_not_meet_four_peer_minimum():
    metric=eligible_metric_set(load_data(),"operating_capital_generation_growth_pct",min_peers=4)
    assert metric.status=="INSUFFICIENT_ALIGNED_PEERS"


def test_asr_roe_remains_blocked_until_harmonized():
    assert load_data()["companies"]["ASR"]["metrics"]["reported_roe_pct"]["score_eligible"] is False
