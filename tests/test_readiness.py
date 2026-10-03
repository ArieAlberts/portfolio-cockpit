import json
from pathlib import Path
import yaml

from portfolio_cockpit.scoring.readiness import evaluate_readiness

ROOT=Path(__file__).resolve().parents[1]


def load_yaml(path):
    return yaml.safe_load((ROOT/path).read_text(encoding="utf-8"))


def load_dataset(ticker):
    idx=json.loads((ROOT/"data/peers/index.json").read_text(encoding="utf-8"))
    return json.loads((ROOT/idx["datasets"][ticker]).read_text(encoding="utf-8"))


def run(ticker):
    portfolio=load_yaml("config/portfolio.yaml")
    types=load_yaml("config/company_types.yaml")
    cfg=load_yaml("config/readiness.yaml")
    company_type=portfolio["positions"][ticker]["company_type"]
    return evaluate_readiness(
        dataset=load_dataset(ticker),
        company_type=company_type,
        component_weights=types[company_type]["quality_components"],
        required_components=tuple(types[company_type]["required_components"]),
        component_metric_aliases=cfg["component_metric_aliases"][company_type],
        minimum_peer_values_per_metric=cfg["minimum_peer_values_per_metric"],
        minimum_weighted_component_coverage=cfg["minimum_weighted_component_coverage"],
        hard_block_status_contains=tuple(cfg["hard_block_status_contains"]),
        data_confidence_score=None,
    )


def test_asr_is_blocked_after_solvency_regime_and_profitability_corrections():
    r=run("ASR")
    assert r.weighted_component_coverage == 0.35
    assert r.peer_coverage_pass is False
    assert r.required_components_pass is False
    assert r.missing_required_components==("capital_strength",)
    assert r.production_ready is False


def test_plmr_70_percent_is_not_enough_without_required_capital_strength():
    r=run("PLMR")
    assert r.weighted_component_coverage >= 0.70
    assert r.peer_coverage_pass is True
    assert r.required_components_pass is False
    assert r.missing_required_components==("capital_strength",)
    assert r.production_ready is False


def test_wkl_remains_blocked():
    assert run("WKL").production_ready is False


def test_abx_is_hard_blocked():
    r=run("ABX")
    assert r.hard_blocked is True
    assert r.production_ready is False
