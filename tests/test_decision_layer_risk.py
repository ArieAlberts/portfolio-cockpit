import shutil

import pytest

from portfolio_cockpit.config import load_config
from portfolio_cockpit.decision_layer.config import load_decision_config
from portfolio_cockpit.decision_layer.inputs import check_inputs, format_report
from portfolio_cockpit.decision_layer.risk import (
    Position,
    PositionsIncompleteError,
    build_risk_report,
    impact_pp,
    load_positions,
    run_scenario,
    sector_weights,
)

from dl_helpers import (
    AS_OF, ROOT, blank_owner_config, filled_owner_config, market_entry, repo_copy, write_market, write_owner_config,
)

REPO_CFG = load_config(ROOT)
CFG = load_decision_config(ROOT)
TARGETS = {t: p["weight_pct"] for t, p in REPO_CFG["portfolio"]["positions"].items()}

POSITIONS = [
    Position("A", 7.0, "Financials", 0.8),
    Position("B", 5.0, "Materials", 1.5),
    Position("C", 3.0, "Materials", None),
]


def test_seven_percent_times_minus_thirty_is_minus_2_1_pp():
    assert impact_pp(7.0, -0.30) == pytest.approx(-2.1)


def test_label_is_portfolio_impact_minus_30():
    report = build_risk_report(filled_owner_config(CFG, REPO_CFG), TARGETS)
    assert report["label"] == "PORTFOLIO IMPACT -30%"
    assert report["positions"]["ASR"]["portfolio_impact_pp"] == pytest.approx(-2.1)
    assert report["execution_effect"] == "NONE"


def test_sector_weights_sum_to_total_weight():
    report = build_risk_report(filled_owner_config(CFG, REPO_CFG), TARGETS)
    assert sum(report["sector_weights_pct"].values()) == pytest.approx(report["invested_weight_pct"])
    assert sum(sector_weights(POSITIONS).values()) == pytest.approx(15.0)


def test_market_shock_uses_beta_when_known():
    result = run_scenario(POSITIONS, {"type": "market", "shock": -0.20, "use_beta": True})
    assert result["per_ticker_pp"] == {"A": pytest.approx(-1.12), "B": pytest.approx(-1.5), "C": pytest.approx(-0.6)}
    plain = run_scenario(POSITIONS, {"type": "market", "shock": -0.20, "use_beta": False})
    assert plain["total_pp"] == pytest.approx(-3.0)


def test_sector_shock():
    result = run_scenario(POSITIONS, {"type": "sector", "sector": "Materials", "shock": -0.30})
    assert result["per_ticker_pp"] == {"B": pytest.approx(-1.5), "C": pytest.approx(-0.9)}


def test_single_stock_shock_targets_largest_or_named():
    assert run_scenario(POSITIONS, {"type": "single_stock", "target": "largest", "shock": -0.30})["per_ticker_pp"] == {"A": pytest.approx(-2.1)}
    assert run_scenario(POSITIONS, {"type": "single_stock", "target": "C", "shock": -0.50})["total_pp"] == pytest.approx(-1.5)


def test_combined_scenario_adds_components():
    scenario = {"type": "combined", "components": [
        {"type": "market", "shock": -0.15, "use_beta": False},
        {"type": "sector", "sector": "Materials", "shock": -0.20},
    ]}
    result = run_scenario(POSITIONS, scenario)
    assert result["per_ticker_pp"]["B"] == pytest.approx(-0.75 - 1.0)
    assert result["total_pp"] == pytest.approx(-2.25 - 1.6)


def test_all_configured_scenarios_run():
    report = build_risk_report(filled_owner_config(CFG, REPO_CFG), TARGETS)
    assert set(report["scenarios"]) == {"market_shock", "sector_shock", "single_stock_shock", "combined_scenario"}
    assert report["scenarios"]["single_stock_shock"]["per_ticker_pp"] == {"MOD": pytest.approx(-2.1)}


def test_template_positions_refuse_with_clear_error():
    with pytest.raises(PositionsIncompleteError, match="ASR.weight_pct"):
        load_positions(blank_owner_config(CFG))


def test_input_check_reports_missing_owner_data(tmp_path):
    root = repo_copy(tmp_path)
    write_owner_config(root, blank_owner_config(CFG))
    shutil.rmtree(root / "data/market", ignore_errors=True)
    report = check_inputs(root, AS_OF)
    assert not report["ready_for_decisions"]
    assert "ASR.weight_pct" in report["missing"]["config/positions.yaml"]
    assert "OKLO.status" in report["missing"]["config/thesis_status.yaml"]
    assert "no market data" in report["blocking"]
    assert "BLOCKED" in format_report(report)


def test_input_check_passes_owner_files_and_lists_market_gaps(tmp_path):
    root = repo_copy(tmp_path)
    write_owner_config(root, filled_owner_config(CFG, REPO_CFG))
    write_market(root, {"ASR": market_entry(price=60.0, eps_ttm=6.0)})
    report = check_inputs(root, AS_OF)
    assert report["missing"]["config/positions.yaml"] == []
    assert report["missing"]["config/thesis_status.yaml"] == []
    assert "ASR.bvps" in report["missing"]["data/market"]
    assert "WKL.price" in report["missing"]["data/market"]
    assert report["ready_for_decisions"]


def test_input_check_reports_invalid_config_without_crashing(tmp_path, capsys):
    from portfolio_cockpit.decision_layer.inputs import main

    root = repo_copy(tmp_path)
    path = root / "config/positions.yaml"
    text = path.read_text()
    path.write_text(text.replace("source: manual", "source: ibkr", 1))
    report = check_inputs(root, AS_OF)
    assert report["ready_for_decisions"] is False
    assert "config is invalid" in report["blocking"]
    assert "positions.source must be 'manual'" in report["errors"]
    assert main(["--root", str(root), "--as-of", AS_OF]) == 0
    out = capsys.readouterr().out
    assert "ERROR  positions.source must be 'manual'" in out
    assert "BLOCKED config is invalid" in out
    assert main(["--root", str(root), "--as-of", AS_OF, "--strict"]) == 1
