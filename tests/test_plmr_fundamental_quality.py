import json
from pathlib import Path

import pytest

from portfolio_cockpit.scoring.peer_data import eligible_metric_set

ROOT=Path(__file__).resolve().parents[1]


def load_current_score():
    current=json.loads((ROOT/"data/scoring/current.json").read_text(encoding="utf-8"))
    return json.loads((ROOT/current["current_fundamental_quality"]).read_text(encoding="utf-8"))


def load_plmr_peer_data():
    return json.loads((ROOT/"data/peers/PLMR/2026-10-03.json").read_text(encoding="utf-8"))


def test_current_scoring_snapshot_blocks_plmr_without_capital_strength():
    data=load_current_score()
    assert "PLMR" not in data["scores"]
    assert data["blocked"]["PLMR"]["status"]=="DATA_CHECK"
    assert data["blocked"]["PLMR"]["missing_required_components"]==["capital_strength"]


def test_plmr_peer_file_no_longer_claims_display_ready():
    data=load_plmr_peer_data()
    assert data["rules"]["final_score_status"].startswith("DATA_CHECK")


def test_plmr_capital_strength_is_locked_to_fy2025_statutory_basis():
    data=load_plmr_peer_data()
    policy=data["rules"]["capital_strength_policy"]
    basis=policy["premium_to_surplus_measurement_basis"]
    assert policy["preferred_reference_period"]=="FY_2025"
    assert basis["numerator"]=="FY_NET_WRITTEN_PREMIUM"
    assert basis["denominator"]=="FY_PERIOD_END_POLICYHOLDERS_SURPLUS"
    assert basis["accounting_basis"]=="US_STATUTORY_ACCOUNTING"
    assert basis["period_alignment"]=="SAME_FISCAL_YEAR"
    assert policy["prohibit_h1_premium_annualization_as_ttm_substitute"] is True


def test_two_verified_fy2025_capital_peers_are_stored_but_target_remains_blocked():
    data=load_plmr_peer_data()
    knsl=data["companies"]["KNSL"]["metrics"]["net_written_premium_to_surplus_ratio"]
    rli=data["companies"]["RLI"]["metrics"]["net_written_premium_to_surplus_ratio"]
    assert knsl["value"]==pytest.approx(83.615406)
    assert rli["value"]==88.0
    assert knsl["score_eligible"] is True
    assert rli["score_eligible"] is True
    assert knsl["comparison_class"]==rli["comparison_class"]=="FY_2025_STATUTORY_NET_PREMIUM_TO_SURPLUS"

    result=eligible_metric_set(data,"net_written_premium_to_surplus_ratio",min_peers=4)
    assert result.status=="TARGET_DATA_CHECK"


def test_interim_or_lower_bound_capital_disclosures_are_not_scored():
    data=load_plmr_peer_data()
    skwd=data["companies"]["SKWD"]["metrics"]["net_written_premium_to_surplus_ratio"]
    hrtg=data["companies"]["HRTG"]["metrics"]["rbc_ratio_pct"]
    assert skwd["value"] is None and skwd["score_eligible"] is False
    assert hrtg["value"] is None and hrtg["score_eligible"] is False
