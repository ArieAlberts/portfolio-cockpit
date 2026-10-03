import json
from pathlib import Path

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
    assert "capital_strength" in data["blocked"]["ASR"]["missing_required_components"]


def test_current_pointer_is_reproducibility_backed():
    current,data=_current_payload()
    assert current["execution_effect"]=="NONE"
    assert len(current["config_hash"])==64
    if "reproducibility_hash" in current:
        assert current["reproducibility_hash"]==data["reproducibility_hash"]
    else:
        # Pipeline v1 historical pointer; next generated snapshot upgrades this.
        assert current["pipeline_version"]==1
