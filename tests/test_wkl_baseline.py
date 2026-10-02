import json
from pathlib import Path


BASELINE = Path("data/baselines/WKL/2026-08-05.json")


def load_baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_wkl_baseline_is_validated_and_starts_at_50():
    data = load_baseline()
    assert data["ticker"] == "WKL"
    assert data["baseline_date"] == "2026-08-05"
    assert data["quality_drift_score"] == 50.0


def test_wkl_absolute_quality_is_not_invented_without_peers():
    data = load_baseline()
    assert data["fundamental_quality_score"] is None
    assert data["fundamental_quality_status"] == "PENDING_PEER_NORMALIZATION"


def test_wkl_baseline_contains_balance_and_value_per_share_metrics():
    data = load_baseline()
    assert data["metrics"]["balance_sheet"]["net_debt_to_ebitda"] == 2.0
    assert data["metrics"]["balance_sheet"]["net_cash_available_eur_m"] == 1211
    assert data["metrics"]["value_per_share"]["diluted_adjusted_eps_eur"] == 2.83
    assert data["metrics"]["value_per_share"]["diluted_share_count_change_pct"] == -3.7
