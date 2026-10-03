import json
from pathlib import Path

from portfolio_cockpit.scoring.peer_data import eligible_metric_set

ROOT=Path(__file__).resolve().parents[1]


def load_adm():
    return json.loads((ROOT/"data/peers/ADM.L/2026-10-03.json").read_text(encoding="utf-8"))


def load_plmr():
    return json.loads((ROOT/"data/peers/PLMR/2026-10-03.json").read_text(encoding="utf-8"))


def test_admiral_is_blocked_for_insufficient_direct_peers():
    data=load_adm()
    assert data["peer_universe_status"]=="INSUFFICIENT_DIRECT_PEERS"
    assert eligible_metric_set(data,"solvency_ratio_pct").status=="INSUFFICIENT_ALIGNED_PEERS"


def test_saga_is_context_only_after_underwriter_sale():
    data=load_adm()
    assert data["companies"]["SAGA.L"]["role"]=="CONTEXT_ONLY"
    assert data["companies"]["SAGA.L"]["score_eligible"] is False


def test_palomar_combined_ratio_has_four_peers():
    assert eligible_metric_set(load_plmr(),"combined_ratio_pct").status=="READY"


def test_palomar_gwp_growth_has_four_peers():
    assert eligible_metric_set(load_plmr(),"gross_written_premium_growth_pct").status=="READY"


def test_palomar_operating_roe_is_not_ready_at_four_peer_minimum():
    assert eligible_metric_set(load_plmr(),"operating_roe_pct").status=="INSUFFICIENT_ALIGNED_PEERS"


def test_palomar_gaap_roe_has_four_peers():
    assert eligible_metric_set(load_plmr(),"annualized_roe_pct").status=="READY"


def test_hci_gross_loss_ratio_is_not_mixed_with_net_loss_ratio():
    metric=load_plmr()["companies"]["HCI"]["metrics"]["loss_ratio_pct"]
    assert metric["comparison_class"]=="GROSS_LOSS_RATIO"
    assert metric["score_eligible"] is False
