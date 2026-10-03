import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_current_scoring_snapshot_blocks_plmr_without_capital_strength():
    data=json.loads((ROOT/"data/scoring/fundamental_quality_2026-10-03_r2.json").read_text(encoding="utf-8"))
    assert "PLMR" not in data["scores"]
    assert data["blocked"]["PLMR"]["status"]=="DATA_CHECK"
    assert data["blocked"]["PLMR"]["missing_required_components"]==["capital_strength"]


def test_plmr_peer_file_no_longer_claims_display_ready():
    data=json.loads((ROOT/"data/peers/PLMR/2026-10-03.json").read_text(encoding="utf-8"))
    assert data["rules"]["final_score_status"].startswith("DATA_CHECK")
