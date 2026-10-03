import json
from pathlib import Path
import pytest
import yaml

from portfolio_cockpit.scoring.peer_data import eligible_metric_set
from portfolio_cockpit.scoring.peer_confidence import peer_metric_confidence
from portfolio_cockpit.scoring.readiness import evaluate_readiness

ROOT=Path(__file__).resolve().parents[1]


def load_esi():
    return json.loads((ROOT/"data/peers/ESI/2026-10-03.json").read_text(encoding="utf-8"))


def test_esi_reported_growth_is_not_quality_eligible():
    m=load_esi()["companies"]["ESI"]["metrics"]["reported_revenue_growth_pct"]
    assert m["score_eligible"] is False
    assert "acquisition" in m["notes"].lower()


def test_esi_fcf_has_four_aligned_peers():
    r=eligible_metric_set(load_esi(),"free_cash_flow_margin_pct",min_peers=4)
    assert r.status=="READY"
    assert set(r.peer_tickers)=={"ENTG","MKSI","DD","ASH"}


def test_esi_adjusted_eps_has_five_aligned_peers():
    r=eligible_metric_set(load_esi(),"adjusted_eps_growth_pct",min_peers=4)
    assert r.status=="READY"
    assert set(r.peer_tickers)=={"ENTG","MKSI","KWR","DD","ASH"}


def test_esi_peer_confidence_clears_threshold():
    d=load_esi()
    for metric in ["adjusted_ebitda_margin_pct","free_cash_flow_margin_pct","adjusted_eps_growth_pct"]:
        r=peer_metric_confidence(dataset=d,metric_name=metric,minimum_peer_values=4)
        assert r.score >= 80


def test_esi_weighted_coverage_is_60_percent_and_remains_blocked():
    portfolio=yaml.safe_load((ROOT/"config/portfolio.yaml").read_text(encoding="utf-8"))
    types=yaml.safe_load((ROOT/"config/company_types.yaml").read_text(encoding="utf-8"))
    cfg=yaml.safe_load((ROOT/"config/readiness.yaml").read_text(encoding="utf-8"))
    typ=portfolio["positions"]["ESI"]["company_type"]
    r=evaluate_readiness(
        dataset=load_esi(),
        company_type=typ,
        component_weights=types[typ]["quality_components"],
        component_metric_aliases=cfg["component_metric_aliases"][typ],
        minimum_peer_values_per_metric=cfg["minimum_peer_values_per_metric"],
        minimum_weighted_component_coverage=cfg["minimum_weighted_component_coverage"],
        hard_block_status_contains=tuple(cfg["hard_block_status_contains"]),
        data_confidence_score=93.5,
        peer_input_confidence_score=93.75,
    )
    assert r.weighted_component_coverage == pytest.approx(0.60)
    assert r.peer_coverage_pass is False
    assert r.production_ready is False
