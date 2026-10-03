import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_current_scoring_snapshot_blocks_asr():
    data=json.loads((ROOT/"data/scoring/fundamental_quality_2026-10-03_r2.json").read_text(encoding="utf-8"))
    assert "ASR" not in data["scores"]
    assert data["blocked"]["ASR"]["status"]=="DATA_CHECK"
    assert "capital_strength" in data["blocked"]["ASR"]["missing_required_components"]


def test_previous_asr_score_is_explicitly_superseded():
    current=json.loads((ROOT/"data/scoring/current.json").read_text(encoding="utf-8"))
    assert current["previous_score_snapshot_status"]=="SUPERSEDED_RESEARCH_ONLY"
