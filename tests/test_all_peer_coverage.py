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


def test_abx_gold_peers_are_real_and_cost_position_uses_aisc():
    index=json.loads((ROOT/"data/peers/index.json").read_text(encoding="utf-8"))
    data=json.loads((ROOT/index["datasets"]["ABX"]).read_text(encoding="utf-8"))
    assert data["target_ticker"]=="ABX"
    assert data["companies"]["ABX"]["company"]=="Barrick Mining Corporation"
    # Only the four owner-approved gold majors; no placeholder or gate peers.
    peers={t for t,c in data["companies"].items() if c["role"]=="PEER"}
    assert peers=={"NEM","AEM","KGC","AU"}
    assert not any(c["role"]=="GATE" for c in data["companies"].values())
    # Gold producers never get a copper C1 cost; cost_position runs on gold AISC.
    assert all(
        c["metrics"]["c1_cash_cost_usd_per_lb"]["value"] is None
        for t,c in data["companies"].items() if t in peers
    )
    assert all(
        c["metrics"]["aisc_usd_per_oz"]["value"] is not None
        and c["metrics"]["aisc_usd_per_oz"]["comparison_class"]=="H1_GOLD_AISC_PER_OZ"
        for c in data["companies"].values()
    )
    # AEM's production-basis AISC is eligible only by owner decision and carries
    # a reduced definition confidence.
    aem=data["companies"]["AEM"]["metrics"]["aisc_usd_per_oz"]
    assert aem["score_eligible"] is True
    assert aem["definition_confidence"]<100
    assert "Owner decision" in aem["notes"]
    # Both required components meet the four-peer minimum with every real peer.
    assert data["rules"]["minimum_peer_values_per_metric"]==4
    for metric in ("aisc_usd_per_oz","net_debt_to_ebitda"):
        result=eligible_metric_set(data,metric,min_peers=4)
        assert result.status=="READY"
        assert set(result.peer_tickers)==peers
    assert "LIMITED" in data["peer_universe_status"]
    assert "INSUFFICIENT" not in data["peer_universe_status"]


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
