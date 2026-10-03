import json
from pathlib import Path

from portfolio_cockpit.scoring.pipeline import build_score_snapshot

ROOT=Path(__file__).resolve().parents[1]


def _current_payload():
    current=json.loads((ROOT/"data/scoring/current.json").read_text(encoding="utf-8"))
    score_path=ROOT/current["current_fundamental_quality"]
    return current,json.loads(score_path.read_text(encoding="utf-8"))


def test_current_scoring_snapshot_blocks_asr():
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
        # Pipeline v1 historical pointer; next generated snapshot upgrades this.
        assert current["pipeline_version"]==1


def test_rebuilt_asr_recovers_required_capital_strength():
    data=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    asr=data["scores"].get("ASR") or data["blocked"]["ASR"]
    assert "capital_strength" in asr["covered_components"]
    assert "capital_strength" not in asr["missing_required_components"]
    capital=asr["selected_metrics"]["capital_strength"]["metrics"]["solvency"]
    assert set(capital["peer_tickers"])=={"NN.AS","AGS.BR","SAMPO.HE","G.MI"}
    assert asr["weighted_component_coverage"] == 0.55
