import pytest
import json
from pathlib import Path
import yaml

from portfolio_cockpit.scoring.peer_data import eligible_metric_set
from portfolio_cockpit.scoring.peer_confidence import peer_metric_confidence
from portfolio_cockpit.scoring.readiness import evaluate_readiness

ROOT=Path(__file__).resolve().parents[1]


def load_wkl():
    return json.loads((ROOT/"data/peers/WKL/2026-10-02.json").read_text(encoding="utf-8"))


def test_spgi_h1_fcf_margin_uses_consistent_reported_basis():
    d=load_wkl()
    m=d["companies"]["SPGI"]["metrics"]["free_cash_flow_margin_pct"]
    assert m["score_eligible"] is True
    assert m["value"] == pytest.approx(2249/8318*100, abs=1e-6)
    assert "as-reported" in m["source_definition"]


def test_wkl_fcf_margin_now_has_four_aligned_peers():
    r=eligible_metric_set(load_wkl(),"free_cash_flow_margin_pct",min_peers=4)
    assert r.status=="READY"
    assert set(r.peer_tickers)=={"TRI.TO","VRSK","SPGI","MCO"}


def test_wkl_fcf_peer_input_confidence_clears_80():
    r=peer_metric_confidence(dataset=load_wkl(),metric_name="free_cash_flow_margin_pct",minimum_peer_values=4)
    assert r.score >= 80


def test_wkl_weighted_coverage_is_50_percent_and_still_blocked():
    portfolio=yaml.safe_load((ROOT/"config/portfolio.yaml").read_text(encoding="utf-8"))
    types=yaml.safe_load((ROOT/"config/company_types.yaml").read_text(encoding="utf-8"))
    cfg=yaml.safe_load((ROOT/"config/readiness.yaml").read_text(encoding="utf-8"))
    typ=portfolio["positions"]["WKL"]["company_type"]
    r=evaluate_readiness(
        dataset=load_wkl(),
        company_type=typ,
        component_weights=types[typ]["quality_components"],
        component_metric_aliases=cfg["component_metric_aliases"][typ],
        minimum_peer_values_per_metric=cfg["minimum_peer_values_per_metric"],
        minimum_weighted_component_coverage=cfg["minimum_weighted_component_coverage"],
        hard_block_status_contains=tuple(cfg["hard_block_status_contains"]),
        data_confidence_score=97.0,
        peer_input_confidence_score=97.5,
    )
    assert r.weighted_component_coverage == pytest.approx(0.50)
    assert r.peer_coverage_pass is False
    assert r.production_ready is False
