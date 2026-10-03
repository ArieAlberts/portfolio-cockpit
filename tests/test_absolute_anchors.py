import json
from copy import deepcopy
from pathlib import Path

import pytest

from portfolio_cockpit.scoring.anchor_pipeline import build_absolute_anchor_snapshot
from portfolio_cockpit.scoring.anchors import (
    AbsoluteAnchorConfigError,
    evaluate_absolute_anchors,
    load_absolute_anchor_config,
    validate_absolute_anchor_config,
)
from portfolio_cockpit.scoring.pipeline import build_score_snapshot


ROOT = Path(__file__).resolve().parents[1]


def load_wkl_baseline():
    return json.loads(
        (ROOT / "data/baselines/WKL/2026-08-05.json").read_text(encoding="utf-8")
    )


def test_wkl_meets_all_configured_absolute_guardrails():
    config=load_absolute_anchor_config(ROOT)
    result=evaluate_absolute_anchors(
        ticker="WKL",
        baseline=load_wkl_baseline(),
        config=config,
    )
    assert result.profile=="PROFESSIONAL_INFORMATION_SERVICES"
    assert result.status=="ANCHORS_MET"
    assert result.required_anchors_met is True
    assert result.configured_metrics==7
    assert result.observed_metrics==7
    assert result.metrics_met==7
    assert result.metrics_missed==0
    assert result.metrics_missing==0
    assert result.execution_effect=="NONE"


def test_anchor_snapshot_is_separate_and_only_wkl_is_configured_in_v1():
    payload=build_absolute_anchor_snapshot(root=ROOT)
    assert payload["summary"]["portfolio_companies"]==23
    assert payload["summary"]["configured_companies"]==1
    assert payload["summary"]["anchors_met"]==1
    assert payload["summary"]["anchor_miss"]==0
    assert payload["summary"]["data_check"]==0
    assert payload["summary"]["not_configured"]==22
    assert payload["results"]["WKL"]["status"]=="ANCHORS_MET"
    assert payload["execution_effect"]=="NONE"


def test_absolute_anchors_do_not_change_wkl_relative_score_or_readiness():
    payload=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    assert "WKL" in payload["blocked"]
    wkl=payload["blocked"]["WKL"]
    assert wkl["diagnostic_candidate"]["score"] == pytest.approx(16.4960426160)
    assert wkl["weighted_component_coverage"] == pytest.approx(0.50)
    assert wkl["status"]=="DATA_CHECK"
    assert "absolute_anchors" not in wkl


def test_anchor_config_forbids_price_or_valuation_inputs():
    config=load_absolute_anchor_config(ROOT)
    broken=deepcopy(config)
    broken["profiles"]["PROFESSIONAL_INFORMATION_SERVICES"]["metrics"][
        "net_debt_to_ebitda"
    ]["source_path"]="metrics.market_price"

    with pytest.raises(AbsoluteAnchorConfigError, match="price/valuation inputs"):
        validate_absolute_anchor_config(broken)


def test_anchor_policy_cannot_become_decision_or_execution_gate():
    config=load_absolute_anchor_config(ROOT)
    assert config["policy"]["alters_fundamental_quality"] is False
    assert config["policy"]["decision_gate"] is False
    assert config["policy"]["price_inputs_allowed"] is False
    assert config["policy"]["execution_effect"]=="NONE"
