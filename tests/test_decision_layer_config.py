import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from portfolio_cockpit.config import load_config
from portfolio_cockpit.decision_layer.config import (
    DecisionConfigError,
    load_decision_config,
    missing_owner_inputs,
    validate_decision_config,
)
from portfolio_cockpit.scoring.pipeline import CODE_FILES, CONFIG_FILES


ROOT = Path(__file__).resolve().parents[1]

# Fundamental Quality hash scope. The decision layer must never edit these.
FQ_HASHED_FILES = {
    "config/portfolio.yaml",
    "config/company_types.yaml",
    "config/readiness.yaml",
    "config/scoring.yaml",
    "config/score_metrics.yaml",
    "config/peer_universes.yaml",
    "src/portfolio_cockpit/config.py",
    "src/portfolio_cockpit/scoring/pipeline.py",
    "src/portfolio_cockpit/scoring/normalization.py",
    "src/portfolio_cockpit/scoring/peer_data.py",
    "src/portfolio_cockpit/scoring/peer_confidence.py",
    "src/portfolio_cockpit/scoring/readiness.py",
    "src/portfolio_cockpit/scoring/quality.py",
}


@pytest.fixture()
def cfg():
    return load_decision_config(ROOT)


@pytest.fixture()
def repo_cfg():
    return load_config(ROOT)


def test_repository_decision_config_validates(cfg):
    assert cfg["decision"]["data_confidence_min"] == 80
    assert cfg["risk_scenarios"]["standard_label"] == "PORTFOLIO IMPACT -30%"


def test_owner_templates_cover_every_portfolio_ticker(cfg, repo_cfg):
    tickers = set(repo_cfg["portfolio"]["positions"])
    assert set(cfg["positions"]["positions"]) == tickers
    assert set(cfg["thesis_status"]["positions"]) == tickers


def test_missing_owner_inputs_reports_empty_template_fields(cfg):
    filled = deepcopy(cfg)
    filled["positions"]["as_of"] = "2026-10-03"
    filled["positions"]["cash_weight_pct"] = 7
    for item in filled["positions"]["positions"].values():
        item.update(weight_pct=1.0, sector="Industrials")
    for item in filled["thesis_status"]["positions"].values():
        item.update(status="INTACT", as_of="2026-10-03")
    assert missing_owner_inputs(filled) == {"positions": [], "thesis_status": []}

    filled["positions"]["positions"]["ASR"]["sector"] = None
    filled["thesis_status"]["positions"]["OKLO"]["status"] = None
    assert missing_owner_inputs(filled) == {
        "positions": ["ASR.sector"],
        "thesis_status": ["OKLO.status"],
    }


def test_decision_layer_is_outside_fq_hash_scope():
    assert set(CONFIG_FILES) | set(CODE_FILES) == FQ_HASHED_FILES
    assert not any("decision_layer" in path for path in CODE_FILES)
    for name in ("quality_drift", "valuation", "decision", "risk_scenarios", "positions", "thesis_status"):
        assert f"config/{name}.yaml" not in CONFIG_FILES


def test_branch_does_not_modify_fq_hashed_files():
    try:
        base = subprocess.check_output(
            ["git", "merge-base", "HEAD", "origin/main"],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
        changed = subprocess.check_output(
            ["git", "diff", "--name-only", base],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("origin/main is not available in this checkout")
    assert not set(changed) & FQ_HASHED_FILES


@pytest.mark.parametrize(
    ("section", "path", "value", "match"),
    [
        ("quality_drift", ("schema_version",), 2, "quality_drift.schema_version"),
        ("quality_drift", ("neutral_score",), 51.0, "neutral_score"),
        ("quality_drift", ("period_rule",), "any", "period_rule"),
        ("valuation", ("reference_weights", "peers"), 0.5, "sum to 1.0"),
        ("valuation", ("labels", "fair_min"), 70, "fair_min must be below"),
        ("decision", ("data_confidence_min",), 70, "data_confidence_min must equal"),
        ("decision", ("drift", "deteriorated_score_max"), 50, "deteriorated_score_max <"),
        ("decision", ("drift", "deteriorated_recent_change_max"), 5, "deteriorated_recent_change_max"),
        ("decision", ("thesis_status_values",), ["INTACT"], "thesis_status_values"),
        ("risk_scenarios", ("standard_shock",), -0.2, "standard_shock must be -0.30"),
        ("risk_scenarios", ("scenarios", "sector_shock", "type"), "crash", "sector_shock.type"),
        ("positions", ("positions", "ASR", "weight_pct"), "seven", "ASR.weight_pct must be a number"),
        ("positions", ("positions", "ASR", "weight_pct"), 101, "ASR.weight_pct must be <="),
        ("positions", ("as_of",), "03-10-2026", "positions.as_of must be an ISO date"),
        ("positions", ("source",), "ibkr", "positions.source"),
        ("thesis_status", ("positions", "ASR", "status"), "GOOD", "ASR.status must be one of"),
    ],
)
def test_validator_rejects_invalid_values(cfg, repo_cfg, section, path, value, match):
    broken = deepcopy(cfg)
    target = broken[section]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(DecisionConfigError, match=match):
        validate_decision_config(broken, repo_cfg)


def test_validator_rejects_missing_and_unknown_tickers(cfg, repo_cfg):
    broken = deepcopy(cfg)
    del broken["positions"]["positions"]["ASR"]
    broken["thesis_status"]["positions"]["XYZ"] = {"status": None, "as_of": None, "note": None}
    with pytest.raises(DecisionConfigError) as exc:
        validate_decision_config(broken, repo_cfg)
    assert "missing tickers: ['ASR']" in str(exc.value)
    assert "not in portfolio.yaml: ['XYZ']" in str(exc.value)


def test_validator_rejects_weights_above_hundred_percent(cfg, repo_cfg):
    broken = deepcopy(cfg)
    broken["positions"]["cash_weight_pct"] = 10
    for item in broken["positions"]["positions"].values():
        item["weight_pct"] = 5
    with pytest.raises(DecisionConfigError, match="above 100%"):
        validate_decision_config(broken, repo_cfg)


def test_validator_requires_all_scenarios(cfg, repo_cfg):
    broken = deepcopy(cfg)
    del broken["risk_scenarios"]["scenarios"]["combined_scenario"]
    with pytest.raises(DecisionConfigError, match="combined_scenario is required"):
        validate_decision_config(broken, repo_cfg)


def test_missing_config_file_fails_fast(tmp_path):
    for rel in ("config",):
        (tmp_path / rel).mkdir()
    with pytest.raises(DecisionConfigError, match="missing config file"):
        load_decision_config(tmp_path)
