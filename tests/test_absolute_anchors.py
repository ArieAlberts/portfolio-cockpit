import yaml

from portfolio_cockpit.scoring.anchors import evaluate_absolute_anchor
from portfolio_cockpit.scoring.pipeline import (
    CODE_FILES,
    CONFIG_FILES,
    build_score_snapshot,
)


def _config():
    return yaml.safe_load(open("config/absolute_anchors.yaml", encoding="utf-8"))


def test_combined_ratio_break_even_boundary_is_strictly_below_100():
    cfg = _config()
    below = evaluate_absolute_anchor(
        metric_name="combined_ratio_pct",
        value=99.9,
        company_type="INSURER_US_P&C",
        anchors_config=cfg,
    )
    at = evaluate_absolute_anchor(
        metric_name="combined_ratio_pct",
        value=100.0,
        company_type="INSURER_US_P&C",
        anchors_config=cfg,
    )
    assert below["status"] == "MEETS_ANCHOR"
    assert at["status"] == "DOES_NOT_MEET_ANCHOR"
    assert below["score_effect"] == "NONE"
    assert at["score_effect"] == "NONE"


def test_solvency_scr_anchor_includes_100_percent_boundary():
    result = evaluate_absolute_anchor(
        metric_name="solvency_ratio_pct",
        value=100.0,
        company_type="INSURER",
        anchors_config=_config(),
    )
    assert result["status"] == "MEETS_ANCHOR"
    assert result["interpretation"] == "SCR_COVERED"


def test_us_p_and_c_premium_surplus_anchor_includes_three_to_one():
    result = evaluate_absolute_anchor(
        metric_name="net_written_premium_to_surplus_ratio",
        value=3.0,
        company_type="INSURER_US_P&C",
        anchors_config=_config(),
    )
    assert result["status"] == "MEETS_ANCHOR"


def test_anchor_does_not_apply_to_wrong_company_type():
    assert (
        evaluate_absolute_anchor(
            metric_name="solvency_ratio_pct",
            value=222.0,
            company_type="INSURER_US_P&C",
            anchors_config=_config(),
        )
        is None
    )


def test_pipeline_exposes_anchor_as_parallel_non_scoring_diagnostic():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    payload = build_score_snapshot(root=root, code_version="TEST-COMMIT")
    asr = payload["scores"].get("ASR") or payload["blocked"]["ASR"]
    solvency = asr["selected_metrics"]["capital_strength"]["metrics"]["solvency"]
    combined = asr["selected_metrics"]["underwriting_quality"]["metrics"]["combined_ratio"]

    assert solvency["absolute_anchor"]["status"] == "MEETS_ANCHOR"
    assert solvency["absolute_anchor"]["threshold"] == 100.0
    assert combined["absolute_anchor"]["status"] == "MEETS_ANCHOR"
    assert payload["methodology"]["absolute_anchors_score_effect"] == "NONE"
    assert "config/absolute_anchors.yaml" in CONFIG_FILES
    assert "src/portfolio_cockpit/scoring/anchors.py" in CODE_FILES
    assert payload["schema_version"] == 5
    assert payload["pipeline_version"] == 3
