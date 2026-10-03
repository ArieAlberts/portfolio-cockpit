import json
from pathlib import Path

from portfolio_cockpit.scoring.peer_data import eligible_metric_set


ROOT = Path(__file__).resolve().parents[1]


def load_adm():
    return json.loads((ROOT / "data/peers/ADM.L/2026-10-03.json").read_text(encoding="utf-8"))


def load_plmr():
    return json.loads((ROOT / "data/peers/PLMR/2026-10-03.json").read_text(encoding="utf-8"))


def test_admiral_is_blocked_for_insufficient_direct_peers():
    data = load_adm()
    assert data["peer_universe_status"] == "INSUFFICIENT_DIRECT_PEERS"
    metric = eligible_metric_set(data, "solvency_ratio_pct")
    assert metric.status == "INSUFFICIENT_ALIGNED_PEERS"


def test_saga_is_context_only_after_underwriter_sale():
    data = load_adm()
    assert data["companies"]["SAGA.L"]["role"] == "CONTEXT_ONLY"
    assert data["companies"]["SAGA.L"]["score_eligible"] is False


def test_palomar_combined_ratio_has_enough_peers():
    metric = eligible_metric_set(load_plmr(), "combined_ratio_pct")
    assert metric.status == "READY"
    assert len(metric.peer_values) >= 3


def test_palomar_gwp_growth_has_enough_peers():
    metric = eligible_metric_set(load_plmr(), "gross_written_premium_growth_pct")
    assert metric.status == "READY"
    assert len(metric.peer_values) >= 3


def test_palomar_operating_roe_has_enough_peers():
    metric = eligible_metric_set(load_plmr(), "operating_roe_pct")
    assert metric.status == "READY"
    assert len(metric.peer_values) >= 3


def test_hci_gross_loss_ratio_is_not_mixed_with_net_loss_ratio():
    data = load_plmr()
    metric = data["companies"]["HCI"]["metrics"]["loss_ratio_pct"]
    assert metric["comparison_class"] == "GROSS_LOSS_RATIO"
    assert metric["score_eligible"] is False
