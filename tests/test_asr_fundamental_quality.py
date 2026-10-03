import json
from pathlib import Path

import pytest

from portfolio_cockpit.scoring.pipeline import build_score_snapshot

ROOT=Path(__file__).resolve().parents[1]


def _current_payload():
    current=json.loads((ROOT/"data/scoring/current.json").read_text(encoding="utf-8"))
    score_path=ROOT/current["current_fundamental_quality"]
    return current,json.loads(score_path.read_text(encoding="utf-8"))


def test_historical_current_snapshot_remains_immutable_r9_state():
    current,data=_current_payload()
    assert current["generated_by_pipeline"] is True
    assert "ASR" not in data["scores"]
    assert data["blocked"]["ASR"]["status"]=="DATA_CHECK"
    assert "capital_strength" in data["blocked"]["ASR"]["covered_components"]
    assert "capital_strength" not in data["blocked"]["ASR"]["missing_required_components"]
    assert data["blocked"]["ASR"]["weighted_component_coverage"] == 0.55


def test_current_pointer_is_reproducibility_backed():
    current,data=_current_payload()
    assert current["execution_effect"]=="NONE"
    assert len(current["config_hash"])==64
    if "reproducibility_hash" in current:
        assert current["reproducibility_hash"]==data["reproducibility_hash"]
    else:
        assert current["pipeline_version"]==1


def test_rebuilt_asr_becomes_display_ready_on_three_validated_components():
    data=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    assert "ASR" in data["scores"]
    asr=data["scores"]["ASR"]

    assert asr["status"]=="DISPLAY_READY"
    assert asr["weighted_component_coverage"] == pytest.approx(0.75)
    assert set(asr["covered_components"])=={
        "capital_strength","underwriting_quality","profitability"
    }
    assert asr["missing_required_components"]==[]
    assert asr["execution_effect"]=="NONE"

    capital=asr["selected_metrics"]["capital_strength"]["metrics"]["solvency"]
    assert set(capital["peer_tickers"])=={"NN.AS","AGS.BR","SAMPO.HE","G.MI"}

    roe=asr["selected_metrics"]["profitability"]["metrics"]["roe"]
    assert roe["metric_name"]=="annualized_ifrs_common_equity_roe_pct"
    assert set(roe["peer_tickers"])=={
        "NN.AS","AGS.BR","SAMPO.HE","AV.L","G.MI"
    }

    assert "value_per_share" not in asr["covered_components"]
    assert asr["fundamental_quality_score"] == pytest.approx(66.0636831295)
    assert asr["display_score"] == 66.1
    sensitivity=asr["diagnostic_candidate"]["sensitivity"]
    assert sensitivity["stability_flag"]=="STABLE"
    assert sensitivity["score_high"] - sensitivity["score_low"] < 10.0
    assert asr["peer_input_confidence"] >= 80
    assert asr["target_data_confidence"] >= 80
