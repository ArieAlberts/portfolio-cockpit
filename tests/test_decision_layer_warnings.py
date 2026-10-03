import json

import pytest

from portfolio_cockpit.decision_layer.config import load_decision_config
from portfolio_cockpit.decision_layer.drift import build_drift_snapshot
from portfolio_cockpit.decision_layer.valuation import build_valuation_snapshot
from portfolio_cockpit.decision_layer.warnings import (
    WarningCode,
    WarningContractError,
    classify,
    confidence_raw_warnings,
    contract_warnings,
    data_state,
    load_target_confidence,
)

from dl_helpers import (
    AS_OF, ROOT, market_entry, observation_from_baseline, reference, repo_copy,
    write_market, write_observation, write_refs,
)

CFG = load_decision_config(ROOT)


def test_contract_has_exactly_six_codes():
    assert [c.value for c in WarningCode] == [
        "STALE_DATA", "SOURCE_CONFLICT", "UNSUITABLE_METRIC",
        "MISSING_DATA", "CALCULATION_ANOMALY", "PERIOD_MISMATCH",
    ]


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("STALE_DATA:price:9d", "STALE_DATA"),
        ("PERIOD_MISMATCH:operating_roe_pct", "PERIOD_MISMATCH"),
        ("UNSUITABLE_METRIC:pe", "UNSUITABLE_METRIC"),
        ("CALCULATION_ANOMALY:x:zero_baseline", "CALCULATION_ANOMALY"),
        ("MISSING_REQUIRED_COMPONENT:capital_strength", "MISSING_DATA"),
        ("DRIFT_COVERAGE_BELOW_THRESHOLD:0.5", "MISSING_DATA"),
        ("VALUATION_COVERAGE_BELOW_THRESHOLD:0.3", "MISSING_DATA"),
        ("SOURCE_CONFLICT:crosscheck:X", "SOURCE_CONFLICT"),
    ],
)
def test_raw_warnings_map_to_contract(raw, code):
    assert classify(raw).value == code


def test_unknown_warning_violates_contract():
    with pytest.raises(WarningContractError):
        classify("SOMETHING_NEW:x")


def test_existing_confidence_maps_onto_contract():
    path, confidence = load_target_confidence(ROOT)
    assert path.name == "2026-10-03.json"
    assert len(confidence) == 23
    asr = confidence["ASR"]
    assert asr["data_confidence"] == 89.5
    assert "MISSING_DATA:confidence_completeness:75" in asr["raw_warnings"]
    for item in confidence.values():
        contract_warnings("confidence", item["raw_warnings"])


def test_confidence_mapping_rules():
    full = {"data_confidence_score": 95, "freshness": 100, "completeness": 100}
    assert confidence_raw_warnings(full, {"result": "NO_MATERIAL_HEADLINE_CONFLICT_FOUND"}) == []
    stale = {**full, "freshness": 60}
    assert confidence_raw_warnings(stale, None) == ["STALE_DATA:confidence_freshness:60"]
    assert confidence_raw_warnings(full, {"result": "MATERIAL_CONFLICT"}) == ["SOURCE_CONFLICT:crosscheck:MATERIAL_CONFLICT"]
    assert confidence_raw_warnings(None, None) == ["MISSING_DATA:confidence:no_target_confidence"]


def test_every_emitted_warning_is_mapped(tmp_path):
    root = repo_copy(tmp_path)
    drift_cfg = CFG["quality_drift"]
    write_observation(root, observation_from_baseline(
        "ASR", drift_cfg, drop=("solvency_ii_ratio_pct",),
        period_basis={"operating_roe_pct": "FY"},
    ))
    write_refs(root, "ASR", {"pe": reference(10.0, 11.0)})
    write_market(root, {"ASR": market_entry(price_date="2026-09-01", price=60.0, eps_ttm=-1.0, bvps=40.0,
                                            shares_outstanding=210.0, distributions_ttm=900.0)})
    drift = build_drift_snapshot(root=root, as_of="2027-06-01", code_version="t")
    valuation = build_valuation_snapshot(root=root, as_of=AS_OF, code_version="t")
    codes = set()
    for result in drift["results"].values():
        codes |= {w["code"] for w in contract_warnings("drift", result["warnings"])}
    for result in valuation["results"].values():
        codes |= {w["code"] for w in contract_warnings("valuation", result["warnings"])}
    assert {"STALE_DATA", "MISSING_DATA", "PERIOD_MISMATCH", "UNSUITABLE_METRIC"} <= codes


def test_stale_thresholds_live_in_config():
    assert CFG["valuation"]["max_price_age_days"] == 7
    assert CFG["quality_drift"]["max_observation_age_days"] == 200


@pytest.mark.parametrize(
    ("confidence", "drift", "valuation", "state"),
    [
        (90, "OK", "OK", "OK"),
        (90, "NO_NEW_FUNDAMENTALS", "OK", "OK"),
        (79.9, "OK", "OK", "DATA_CHECK"),
        (None, "OK", "OK", "DATA_CHECK"),
        (90, "DRIFT_DATA_CHECK", "OK", "DATA_CHECK"),
        (90, "OK", "NO_MARKET_DATA", "DATA_CHECK"),
        (90, "OK", "VALUATION_DATA_CHECK", "DATA_CHECK"),
        (90, None, "OK", "DATA_CHECK"),
    ],
)
def test_missing_data_leads_to_data_check(confidence, drift, valuation, state):
    result, reasons = data_state(data_confidence=confidence, threshold=80, drift_status=drift,
                                 valuation_status=valuation)
    assert result == state
    assert bool(reasons) == (state == "DATA_CHECK")
