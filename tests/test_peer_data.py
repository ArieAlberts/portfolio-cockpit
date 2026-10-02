import json
from pathlib import Path

from portfolio_cockpit.scoring.peer_data import eligible_metric_set


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/peers/WKL/2026-10-02.json"


def load_data():
    return json.loads(DATA.read_text(encoding="utf-8"))


def test_all_companies_have_primary_source_and_period():
    data = load_data()
    for company in data["companies"].values():
        assert company["period"]
        assert company["period_end"]
        assert company["source"]["url"].startswith("https://")


def test_factset_full_year_is_not_used_in_strict_h1_score():
    data = load_data()
    assert data["companies"]["FDS"]["period_alignment"] == "NON_ALIGNED_LATEST_FY"
    metric = eligible_metric_set(data, "organic_like_revenue_growth_pct")
    assert "FDS" not in metric.peer_tickers


def test_margin_types_are_not_forced_equal():
    data = load_data()
    metric = eligible_metric_set(data, "reported_margin_pct")
    assert "TRI.TO" not in metric.peer_tickers
    assert "VRSK" not in metric.peer_tickers
    assert metric.comparison_class == "ADJUSTED_OPERATING_MARGIN"


def test_spgi_fcf_margin_is_blocked_due_to_basis_mismatch():
    data = load_data()
    assert data["companies"]["SPGI"]["metrics"]["free_cash_flow_margin_pct"]["score_eligible"] is False


def test_organic_growth_has_enough_aligned_peers():
    metric = eligible_metric_set(load_data(), "organic_like_revenue_growth_pct")
    assert metric.status == "READY"
    assert len(metric.peer_values) >= 3


def test_adjusted_eps_growth_has_enough_aligned_peers():
    metric = eligible_metric_set(load_data(), "adjusted_eps_growth_pct")
    assert metric.status == "READY"
    assert len(metric.peer_values) >= 3


def test_leverage_is_blocked_until_more_peer_values_exist():
    metric = eligible_metric_set(load_data(), "net_debt_to_ebitda")
    assert metric.status == "INSUFFICIENT_ALIGNED_PEERS"
