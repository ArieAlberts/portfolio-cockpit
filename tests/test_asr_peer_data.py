import json
from pathlib import Path

from portfolio_cockpit.scoring.peer_data import eligible_metric_set

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data/peers/ASR/2026-10-03.json"


def load_data():
    return json.loads(DATA.read_text(encoding="utf-8"))


def test_aviva_is_solvency_uk_and_not_eu_solvency_ii_eligible():
    m=load_data()["companies"]["AV.L"]["metrics"]["solvency_ratio_pct"]
    assert m["comparison_class"]=="SOLVENCY_UK_RATIO"
    assert m["score_eligible"] is False


def test_asr_solvency_ii_has_four_eu_regime_peers_and_is_ready():
    metric=eligible_metric_set(load_data(),"solvency_ratio_pct",min_peers=4)
    assert metric.status=="READY"
    assert set(metric.peer_tickers)=={"NN.AS","AGS.BR","SAMPO.HE","G.MI"}


def test_generali_is_eu_solvency_ii_eligible():
    m=load_data()["companies"]["G.MI"]["metrics"]["solvency_ratio_pct"]
    assert m["comparison_class"]=="SOLVENCY_II_RATIO"
    assert m["value"]==216
    assert m["score_eligible"] is True


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


def test_harmonized_ifrs_common_equity_roe_is_ready_with_five_peers():
    metric=eligible_metric_set(
        load_data(),"annualized_ifrs_common_equity_roe_pct",min_peers=4
    )
    assert metric.status=="READY"
    assert set(metric.peer_tickers)=={
        "NN.AS","AGS.BR","SAMPO.HE","AV.L","G.MI"
    }


def test_company_defined_roe_remains_blocked():
    data=load_data()
    assert data["companies"]["ASR"]["metrics"]["reported_roe_pct"]["score_eligible"] is False
    assert data["companies"]["AV.L"]["metrics"]["reported_roe_pct"]["score_eligible"] is False


def test_share_count_series_is_ready_without_ageas():
    metric=eligible_metric_set(load_data(),"share_count_change_pct",min_peers=4)
    assert metric.status=="READY"
    assert set(metric.peer_tickers)=={"NN.AS","SAMPO.HE","AV.L","G.MI"}
    ageas=load_data()["companies"]["AGS.BR"]["metrics"]["share_count_change_pct"]
    assert ageas["value"] is None
    assert ageas["score_eligible"] is False


def test_derived_ifrs_eps_growth_is_diagnostic_only():
    data=load_data()
    assert data["companies"]["ASR"]["metrics"]["gaap_eps_growth_pct"]["score_eligible"] is False
    assert eligible_metric_set(data,"gaap_eps_growth_pct",min_peers=4).status=="TARGET_DATA_CHECK"
