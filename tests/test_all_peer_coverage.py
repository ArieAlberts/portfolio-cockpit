import json
from pathlib import Path
import yaml

from portfolio_cockpit.scoring.peer_data import eligible_metric_set

ROOT=Path(__file__).resolve().parents[1]


def test_all_23_portfolio_companies_have_peer_dataset():
    portfolio=yaml.safe_load((ROOT/"config/portfolio.yaml").read_text(encoding="utf-8"))
    index=json.loads((ROOT/"data/peers/index.json").read_text(encoding="utf-8"))
    assert set(portfolio["positions"])==set(index["datasets"])
    assert len(index["datasets"])==23
    for ticker,relative_path in index["datasets"].items():
        path=ROOT/relative_path
        assert path.exists(), f"Missing peer dataset for {ticker}"
        data=json.loads(path.read_text(encoding="utf-8"))
        assert data["target_ticker"]==ticker
        assert data["peer_universe_status"]


def test_abx_remains_blocked_without_fake_peers():
    data=json.loads((ROOT/"data/peers/ABX/2026-10-03.json").read_text(encoding="utf-8"))
    assert data["peer_universe_status"]=="INSUFFICIENT_DIRECT_PUBLIC_PEERS"


def test_tmdx_has_three_broad_peer_observations_but_not_four_peer_score_readiness():
    data=json.loads((ROOT/"data/peers/TMDX/2026-10-03.json").read_text(encoding="utf-8"))
    diagnostic=eligible_metric_set(data,"revenue_growth_pct",min_peers=3)
    production=eligible_metric_set(data,"revenue_growth_pct",min_peers=4)
    assert diagnostic.status=="READY"
    assert len(diagnostic.peer_values)>=3
    assert production.status=="INSUFFICIENT_ALIGNED_PEERS"
    assert "LOW_CONFIDENCE" in data["peer_universe_status"]


def test_oklo_contains_no_earnings_multiple_quality_metrics():
    data=json.loads((ROOT/"data/peers/OKLO/2026-10-03.json").read_text(encoding="utf-8"))
    blob=json.dumps(data).lower()
    assert '"p_e"' not in blob
    assert "ev_ebitda" not in blob
    assert "price_earnings" not in blob


def test_peer_alignment_is_dataset_configurable_without_overriding_four_peer_gate():
    data=json.loads((ROOT/"data/peers/TMDX/2026-10-03.json").read_text(encoding="utf-8"))
    diagnostic=eligible_metric_set(data,"operating_margin_pct",min_peers=3)
    production=eligible_metric_set(data,"operating_margin_pct",min_peers=4)
    assert diagnostic.status=="READY"
    assert set(diagnostic.peer_tickers)>={"PODD","DXCM","INSP"}
    assert production.status=="INSUFFICIENT_ALIGNED_PEERS"
