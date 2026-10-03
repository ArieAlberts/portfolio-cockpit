import json
from pathlib import Path
import yaml

from portfolio_cockpit.scoring.peer_data import eligible_metric_set


ROOT = Path(__file__).resolve().parents[1]


def test_all_23_portfolio_companies_have_peer_dataset():
    portfolio = yaml.safe_load((ROOT / "config/portfolio.yaml").read_text(encoding="utf-8"))
    index = json.loads((ROOT / "data/peers/index.json").read_text(encoding="utf-8"))
    assert set(portfolio["positions"]) == set(index["datasets"])
    assert len(index["datasets"]) == 23
    for ticker, relative_path in index["datasets"].items():
        path = ROOT / relative_path
        assert path.exists(), f"Missing peer dataset for {ticker}"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["target_ticker"] == ticker
        assert data["peer_universe_status"]


def test_abx_remains_blocked_without_fake_peers():
    data = json.loads((ROOT / "data/peers/ABX/2026-10-03.json").read_text(encoding="utf-8"))
    assert data["peer_universe_status"] == "INSUFFICIENT_DIRECT_PUBLIC_PEERS"


def test_tmdx_revenue_growth_has_three_broad_peers_but_low_confidence_status():
    data = json.loads((ROOT / "data/peers/TMDX/2026-10-03.json").read_text(encoding="utf-8"))
    metric = eligible_metric_set(data, "revenue_growth_pct")
    assert metric.status == "READY"
    assert len(metric.peer_values) >= 3
    assert "LOW_CONFIDENCE" in data["peer_universe_status"]


def test_oklo_contains_no_earnings_multiple_quality_metrics():
    data = json.loads((ROOT / "data/peers/OKLO/2026-10-03.json").read_text(encoding="utf-8"))
    text = json.dumps(data).lower()
    assert '"p_e"' not in text
    assert "ev_ebitda" not in text
    assert "price_earnings" not in text


def test_peer_alignment_is_dataset_configurable():
    data = json.loads((ROOT / "data/peers/TMDX/2026-10-03.json").read_text(encoding="utf-8"))
    metric = eligible_metric_set(data, "operating_margin_pct")
    assert metric.status == "READY"
    assert set(metric.peer_tickers) >= {"PODD", "DXCM", "INSP"}
