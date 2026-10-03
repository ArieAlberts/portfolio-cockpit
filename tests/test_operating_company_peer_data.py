import json
from pathlib import Path

from portfolio_cockpit.scoring.peer_data import eligible_metric_set


ROOT = Path(__file__).resolve().parents[1]


def load_cap():
    return json.loads((ROOT / "data/peers/CAP.PA/2026-10-03.json").read_text(encoding="utf-8"))


def load_imcd():
    return json.loads((ROOT / "data/peers/IMCD/2026-10-03.json").read_text(encoding="utf-8"))


def test_cap_reported_growth_has_three_aligned_peers():
    metric = eligible_metric_set(load_cap(), "reported_revenue_growth_pct")
    assert metric.status == "READY"
    assert set(metric.peer_tickers) == {"CTSH", "SOP.PA", "EPAM"}


def test_cap_adjusted_margin_has_three_aligned_peers():
    metric = eligible_metric_set(load_cap(), "company_adjusted_operating_margin_pct")
    assert metric.status == "READY"
    assert len(metric.peer_values) == 3


def test_cap_adjusted_eps_growth_has_three_aligned_peers():
    metric = eligible_metric_set(load_cap(), "company_adjusted_eps_growth_pct")
    assert metric.status == "READY"
    assert len(metric.peer_values) == 3


def test_cap_non_aligned_fiscal_peers_are_context_only():
    data = load_cap()
    for ticker in ["ACN", "GIB.A.TO", "INFY"]:
        assert data["companies"][ticker]["period_alignment"].startswith("NON_ALIGNED")


def test_imcd_peer_universe_remains_limited():
    data = load_imcd()
    assert data["peer_universe_status"] == "LIMITED_MEDIUM_CONFIDENCE"


def test_dksh_margin_is_not_forced_equal_to_imcd_ebita_margin():
    data = load_imcd()
    metric = data["companies"]["DKSH.SW"]["metrics"]["adjusted_ebita_margin_pct"]
    assert metric["comparison_class"] == "H1_CORE_EBIT_MARGIN"
    assert metric["score_eligible"] is False


def test_brenntag_h1_is_explicitly_derived_from_quarters():
    data = load_imcd()
    assert data["companies"]["BNR.DE"]["period_alignment"] == "ALIGNED_H1_DERIVED"
