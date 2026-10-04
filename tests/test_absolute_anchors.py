import json
from copy import deepcopy
from pathlib import Path

import pytest

from portfolio_cockpit.config import ConfigValidationError, load_config, validate_config
from portfolio_cockpit.scoring.absolute_anchors import (
    classify_anchor,
    evaluate_absolute_anchors,
)
from portfolio_cockpit.scoring.pipeline import build_score_snapshot


ROOT = Path(__file__).resolve().parents[1]


def load_wkl():
    return json.loads(
        (ROOT / "data/peers/WKL/2026-10-02.json").read_text(encoding="utf-8")
    )


def test_anchor_classifier_respects_metric_direction():
    assert classify_anchor(
        value=25,
        direction="higher_is_better",
        strong_threshold=20,
        acceptable_threshold=10,
    ) == "STRONG"
    assert classify_anchor(
        value=15,
        direction="higher_is_better",
        strong_threshold=20,
        acceptable_threshold=10,
    ) == "ACCEPTABLE"
    assert classify_anchor(
        value=4,
        direction="higher_is_better",
        strong_threshold=20,
        acceptable_threshold=10,
    ) == "BELOW_ANCHOR"

    assert classify_anchor(
        value=2.0,
        direction="lower_is_better",
        strong_threshold=2.5,
        acceptable_threshold=3.5,
    ) == "STRONG"
    assert classify_anchor(
        value=3.0,
        direction="lower_is_better",
        strong_threshold=2.5,
        acceptable_threshold=3.5,
    ) == "ACCEPTABLE"


def test_wkl_is_strong_on_all_configured_absolute_anchors():
    config=load_config(ROOT)
    result=evaluate_absolute_anchors(
        dataset=load_wkl(),
        company_type="GENERAL_OPERATING_COMPANY",
        config=config["absolute_anchors"],
    )
    assert result["context_only"] is True
    assert result["calibration_status"] == "PILOT"
    assert result["affects_fundamental_quality_score"] is False
    assert result["affects_readiness"] is False
    assert result["affects_decision_engine"] is False
    assert result["configured_metrics"] == 7
    assert result["evaluated_metrics"] == 7
    assert result["counts"]["STRONG"] == 7
    assert result["counts"]["ACCEPTABLE"] == 0
    assert result["counts"]["BELOW_ANCHOR"] == 0
    assert result["counts"]["MISSING"] == 0
    assert result["execution_effect"] == "NONE"


def test_absolute_anchors_explain_wkl_without_changing_relative_score_or_gate():
    payload=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    assert "WKL" in payload["blocked"]
    wkl=payload["blocked"]["WKL"]

    assert wkl["diagnostic_candidate"]["score"] == pytest.approx(16.4960426160)
    assert wkl["weighted_component_coverage"] == pytest.approx(0.50)
    assert wkl["status"] == "DATA_CHECK"

    anchors=wkl["absolute_anchors"]
    assert anchors["counts"]["STRONG"] == 7
    assert anchors["affects_fundamental_quality_score"] is False
    assert anchors["affects_readiness"] is False
    assert anchors["affects_decision_engine"] is False
    assert anchors["execution_effect"] == "NONE"

    methodology=payload["methodology"]
    assert methodology["absolute_anchors_context_only"] is True
    assert methodology["absolute_anchors_affect_score"] is False
    assert methodology["absolute_anchors_affect_readiness"] is False
    assert methodology["absolute_anchors_affect_decision_engine"] is False


def test_unconfigured_company_type_gets_empty_context_not_a_fake_assessment():
    config=load_config(ROOT)
    asr=json.loads(
        (ROOT / "data/peers/ASR/2026-10-03.json").read_text(encoding="utf-8")
    )
    result=evaluate_absolute_anchors(
        dataset=asr,
        company_type="INSURER",
        config=config["absolute_anchors"],
    )
    assert result["configured_metrics"] == 0
    assert result["evaluated_metrics"] == 0
    assert result["counts"]["MISSING"] == 0


def test_config_rejects_anchor_direction_drift():
    config=load_config(ROOT)
    broken=deepcopy(config)
    broken["absolute_anchors"]["profiles"]["GENERAL_OPERATING_COMPANY"][
        "net_debt_to_ebitda"
    ]["direction"]="higher_is_better"

    with pytest.raises(ConfigValidationError, match="differs from canonical"):
        validate_config(broken)


def test_config_rejects_anchor_that_can_affect_decision_engine():
    config=load_config(ROOT)
    broken=deepcopy(config)
    broken["absolute_anchors"]["affects_decision_engine"]=True

    with pytest.raises(ConfigValidationError, match="must not affect Decision Engine"):
        validate_config(broken)
