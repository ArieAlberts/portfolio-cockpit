import json
from pathlib import Path

import yaml

from portfolio_cockpit.config import load_config
from portfolio_cockpit.scoring.pipeline import build_score_snapshot


ROOT = Path(__file__).resolve().parents[1]


def test_plmr_uses_us_p_and_c_company_type():
    portfolio = yaml.safe_load((ROOT / "config/portfolio.yaml").read_text(encoding="utf-8"))
    assert portfolio["positions"]["PLMR"]["company_type"] == "INSURER_US_P&C"


def test_plmr_capital_registry_excludes_eu_solvency():
    config = load_config(ROOT)
    aliases = config["score_metrics"]["component_metric_aliases"]["INSURER_US_P&C"][
        "capital_strength"
    ]
    assert aliases == ["rbc_ratio_pct", "net_written_premium_to_surplus_ratio"]
    assert "solvency_ratio_pct" not in aliases


def test_plmr_capital_policy_requires_fy2025_statutory_same_period_basis():
    data = json.loads(
        (ROOT / "data/peers/PLMR/2026-10-03.json").read_text(encoding="utf-8")
    )
    policy = data["rules"]["capital_strength_policy"]
    basis = policy["premium_to_surplus_measurement_basis"]

    assert policy["metric_family"] == "US_P&C_STATUTORY_CAPITAL"
    assert policy["status"] == "FY2025_STATUTORY_COLLECTION_IN_PROGRESS"
    assert policy["preferred_reference_period"] == "FY_2025"
    assert policy["prohibit_eu_or_uk_solvency_substitution"] is True
    assert policy["prohibit_h1_premium_annualization_as_ttm_substitute"] is True

    assert basis["numerator"] == "FY_NET_WRITTEN_PREMIUM"
    assert basis["denominator"] == "FY_PERIOD_END_POLICYHOLDERS_SURPLUS"
    assert basis["accounting_basis"] == "US_STATUTORY_ACCOUNTING"
    assert basis["period_alignment"] == "SAME_FISCAL_YEAR"


def test_plmr_stays_blocked_until_statutory_capital_is_populated():
    payload = build_score_snapshot(root=ROOT, code_version="TEST-COMMIT")
    plmr = payload["scores"].get("PLMR") or payload["blocked"]["PLMR"]
    assert plmr["company_type"] == "INSURER_US_P&C"
    assert "capital_strength" in plmr["missing_required_components"]
    assert "capital_strength" not in plmr["covered_components"]
    assert plmr["status"] == "DATA_CHECK"
    assert plmr["execution_effect"] == "NONE"
