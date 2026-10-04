import ast
import shutil
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from portfolio_cockpit.config import load_config
from portfolio_cockpit.decision_layer.config import load_decision_config
from portfolio_cockpit.decision_layer.decision import (
    DecisionInputError,
    DecisionInputs,
    FORBIDDEN_OUTPUT_KEYS,
    build_decision_snapshot,
    decide,
    write_decision_snapshot,
)
from portfolio_cockpit.decision_layer.drift import build_drift_snapshot, write_drift_snapshot
from portfolio_cockpit.decision_layer.valuation import build_valuation_snapshot, write_valuation_snapshot

from dl_helpers import (
    AS_OF, ROOT, filled_owner_config, market_entry, observation_from_baseline, reference, repo_copy,
    write_market, write_observation, write_owner_config, write_refs,
)

REPO_CFG = load_config(ROOT)
CFG = load_decision_config(ROOT)
DECISION_CFG = CFG["decision"]
TARGET_CFG = CFG["target_adjustment"]

BASE = DecisionInputs(
    ticker="X", drift_score=50.0, drift_change_recent=0.0, drift_status="OK",
    valuation_score=50.0, valuation_status="OK", data_confidence=90.0, thesis_status="INTACT",
    current_weight_pct=4.0, base_target_weight_pct=4.0, score_adjusted_target_pct=4.0,
    sector_weight_pct=10.0, portfolio_impact_pp=-1.2, role="CORE", valuation_label="Fair",
    quality_multiplier_applied=1.0, fq_status="DATA_CHECK", fq_score=None,
)


def _decide(**changes):
    return decide(replace(BASE, **changes), DECISION_CFG, TARGET_CFG)


@pytest.mark.parametrize(
    ("changes", "state", "reason"),
    [
        ({"data_confidence": 70.0}, "DATA_CHECK", "DATA_CONFIDENCE_BELOW_80"),
        ({"drift_status": "DRIFT_DATA_CHECK", "drift_score": None}, "DATA_CHECK", "DRIFT_DRIFT_DATA_CHECK"),
        ({"valuation_status": "NO_MARKET_DATA", "valuation_score": None}, "DATA_CHECK", "VALUATION_NO_MARKET_DATA"),
        ({"thesis_status": "BROKEN"}, "THESIS_REVIEW", "THESIS_BROKEN"),
        ({"role": "EXIT", "score_adjusted_target_pct": 0.0, "current_weight_pct": 1.0}, "EXIT_REVIEW", None),
        ({"role": "EXIT", "score_adjusted_target_pct": 0.0, "current_weight_pct": 0.0}, "HOLD", "WITHIN_BAND"),
        ({"drift_score": 40.0}, "REVIEW_REDUCE", None),
        ({"drift_score": 52.0, "drift_change_recent": -10.0}, "REVIEW_REDUCE", None),
        ({"current_weight_pct": 5.0}, "TRIM_CANDIDATE", "PRICE_ONLY"),
        ({"current_weight_pct": 6.0, "score_adjusted_target_pct": 4.4, "quality_multiplier_applied": 1.1},
         "TRIM_CANDIDATE", "ABOVE_SUPPORTED_WEIGHT"),
        ({"current_weight_pct": 3.0}, "ADD_CANDIDATE", None),
        ({"current_weight_pct": 3.0, "valuation_label": "Expensive"}, "NO_ADD", "VALUATION_EXPENSIVE"),
        ({"valuation_label": "Expensive"}, "NO_ADD", "WITHIN_BAND"),
        ({}, "HOLD", "WITHIN_BAND"),
        ({"current_weight_pct": 4.79}, "HOLD", "WITHIN_BAND"),
        ({"current_weight_pct": 3.21}, "HOLD", "WITHIN_BAND"),
        ({"thesis_status": "WATCH", "current_weight_pct": 3.0}, "ADD_CANDIDATE", None),
    ],
)
def test_every_branch_of_the_decision_matrix(changes, state, reason):
    result = _decide(**changes)
    assert result.decision_state == state
    assert result.reasons
    if reason:
        assert any(r.startswith(reason) for r in result.reasons), result.reasons


def test_data_check_precedes_everything():
    result = _decide(data_confidence=50.0, thesis_status="BROKEN", drift_score=10.0, role="EXIT")
    assert result.decision_state == "DATA_CHECK"
    assert "DATA_CONFIDENCE_BELOW_80" in result.reasons


def test_trim_with_neutral_multiplier_is_price_only():
    result = _decide(current_weight_pct=5.0, score_adjusted_target_pct=4.0, quality_multiplier_applied=1.0)
    assert result.decision_state == "TRIM_CANDIDATE"
    assert "PRICE_ONLY" in result.reasons
    assert "TARGET_REDUCED_BY_DRIFT" not in result.reasons
    assert "ABOVE_SUPPORTED_WEIGHT" not in result.reasons


def test_trim_with_reduced_multiplier_is_only_target_reduced_by_drift():
    result = _decide(current_weight_pct=5.0, score_adjusted_target_pct=3.6, quality_multiplier_applied=0.9)
    assert result.decision_state == "TRIM_CANDIDATE"
    assert "TARGET_REDUCED_BY_DRIFT" in result.reasons
    assert "PRICE_ONLY" not in result.reasons
    assert "ABOVE_SUPPORTED_WEIGHT" not in result.reasons


def test_trim_with_raised_multiplier_is_above_supported_weight():
    result = _decide(current_weight_pct=6.0, score_adjusted_target_pct=4.4, quality_multiplier_applied=1.1)
    assert result.decision_state == "TRIM_CANDIDATE"
    assert "ABOVE_SUPPORTED_WEIGHT" in result.reasons
    assert "PRICE_ONLY" not in result.reasons and "TARGET_REDUCED_BY_DRIFT" not in result.reasons


@pytest.mark.parametrize(
    ("changes", "flag"),
    [
        ({"current_weight_pct": 10.0, "score_adjusted_target_pct": 13.0}, "POSITION_LIMIT"),
        ({"sector_weight_pct": 30.0}, "SECTOR_LIMIT"),
        ({"portfolio_impact_pp": -3.3}, "IMPACT_LIMIT"),
    ],
)
def test_limits_block_add(changes, flag):
    result = _decide(**{"current_weight_pct": 3.0, **changes})
    assert result.decision_state == "HOLD"
    assert "ADD_BLOCKED_BY_LIMIT" in result.reasons
    assert any(f.startswith(flag) for f in result.limit_flags)


def test_fq_floor_only_applies_when_display_ready():
    below = {"current_weight_pct": 3.0}
    not_ready = _decide(**below, fq_status="DATA_CHECK", fq_score=None)
    assert not_ready.decision_state == "ADD_CANDIDATE"
    assert "FQ_NOT_DISPLAY_READY" in not_ready.reasons
    low = _decide(**below, fq_status="DISPLAY_READY", fq_score=20.0)
    assert low.decision_state == "HOLD"
    assert any(r.startswith("FQ_BELOW_FLOOR") for r in low.reasons)
    ok = _decide(**below, fq_status="DISPLAY_READY", fq_score=50.0)
    assert ok.decision_state == "ADD_CANDIDATE"
    assert "FQ_NOT_DISPLAY_READY" not in ok.reasons


def test_unknown_thesis_status_is_refused():
    with pytest.raises(DecisionInputError):
        _decide(thesis_status="GREAT")


def test_template_owner_inputs_refuse_to_run():
    with pytest.raises(DecisionInputError, match="cockpit-check-inputs"):
        build_decision_snapshot(root=ROOT, as_of=AS_OF)


def _end_to_end_root(tmp_path):
    root = repo_copy(tmp_path)
    write_owner_config(root, filled_owner_config(CFG, REPO_CFG))
    drift_cfg = CFG["quality_drift"]
    write_observation(root, observation_from_baseline("ASR", drift_cfg, overrides={"solvency_ii_ratio_pct": 260}))
    write_refs(root, "ASR", {"pe": reference(10.0, 11.0), "price_to_book": reference(1.4, 1.6),
                             "shareholder_yield": reference(0.08, 0.07)})
    write_market(root, {"ASR": market_entry(price=45.0, shares_outstanding=210.0, eps_ttm=6.0, bvps=40.0,
                                            distributions_ttm=1100.0)})
    write_drift_snapshot(root, build_drift_snapshot(root=root, as_of=AS_OF, code_version="t"))
    write_valuation_snapshot(root, build_valuation_snapshot(root=root, as_of=AS_OF, code_version="t"))
    return root


def test_end_to_end_decisions_for_all_23(tmp_path):
    root = _end_to_end_root(tmp_path)
    payload = build_decision_snapshot(root=root, as_of=AS_OF, code_version="t")
    assert len(payload["results"]) == 23
    asr = payload["results"]["ASR"]
    assert asr["inputs"]["drift_score"] > 55
    assert asr["inputs"]["valuation_label"] == "Attractive"
    # One improving observation is not enough to raise the target (needs 2),
    # so the adjusted target stays at base and 7% current is within the band.
    assert asr["decision_state"] == "HOLD", asr
    assert asr["score_adjusted_target_pct"] == 7.0
    assert asr["quality_multiplier_raw"] > 1.0 and asr["quality_multiplier_applied"] == 1.0
    assert "AWAITING_CONFIRMATION" in asr["target_gates"]
    for key in ("base_target_weight_pct", "quality_multiplier_raw", "quality_multiplier_applied",
                "score_adjusted_target_pct", "current_weight_pct", "gap_pct", "binding_constraint", "reasons"):
        assert key in asr
    msm = payload["results"]["MSM"]
    assert msm["score_adjusted_target_pct"] == 0.0 and msm["binding_constraint"] == "EXIT_ROLE"
    assert payload["results"]["WKL"]["decision_state"] == "DATA_CHECK"
    assert "VALUATION_NO_MARKET_DATA" in payload["results"]["WKL"]["reasons"]
    assert payload["portfolio_risk"]["label"] == "PORTFOLIO IMPACT -30%"
    for item in payload["results"].values():
        assert item["execution_effect"] == "NONE"
        assert {w["code"] for w in item["warnings"]} <= {
            "STALE_DATA", "SOURCE_CONFLICT", "UNSUITABLE_METRIC", "MISSING_DATA",
            "CALCULATION_ANOMALY", "PERIOD_MISMATCH",
        }
    assert payload["provenance"]["sources"]["drift"]["sha256"]


def _keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _keys(v)


def test_output_never_contains_order_fields(tmp_path):
    root = _end_to_end_root(tmp_path)
    payload = build_decision_snapshot(root=root, as_of=AS_OF, code_version="t")
    assert not set(_keys(payload)) & FORBIDDEN_OUTPUT_KEYS
    assert payload["execution_effect"] == "NONE"


def test_decision_layer_imports_no_broker_sdk():
    forbidden = ("ib_insync", "ibapi", "ib_async", "alpaca", "ccxt", "degiro", "saxo", "order_manager", "requests")
    for path in sorted((ROOT / "src/portfolio_cockpit/decision_layer").glob("*.py")):
        tree = ast.parse(path.read_text())
        modules = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        modules += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not [m for m in modules if any(f in m for f in forbidden)], path.name


def test_base_target_weight_unchanged_after_run(tmp_path):
    root = _end_to_end_root(tmp_path)
    before = hashlib.sha256((root / "config/portfolio.yaml").read_bytes()).hexdigest()
    write_decision_snapshot(root, build_decision_snapshot(root=root, as_of=AS_OF, code_version="t"))
    assert hashlib.sha256((root / "config/portfolio.yaml").read_bytes()).hexdigest() == before
    assert before == hashlib.sha256((ROOT / "config/portfolio.yaml").read_bytes()).hexdigest()


def test_historical_decisions_are_preserved(tmp_path):
    root = _end_to_end_root(tmp_path)
    first = write_decision_snapshot(root, build_decision_snapshot(root=root, as_of=AS_OF, code_version="a"))
    body = first.read_bytes()
    again = write_decision_snapshot(root, build_decision_snapshot(root=root, as_of=AS_OF, code_version="b"))
    assert again == first
    write_market(root, {"ASR": market_entry(price=90.0, shares_outstanding=210.0, eps_ttm=6.0, bvps=40.0,
                                            distributions_ttm=1100.0)})
    write_valuation_snapshot(root, build_valuation_snapshot(root=root, as_of=AS_OF, code_version="c"))
    second = write_decision_snapshot(root, build_decision_snapshot(root=root, as_of=AS_OF, code_version="c"))
    assert second.name == f"decisions_{AS_OF}_r2.json"
    assert first.read_bytes() == body
    assert json.loads(first.read_text())["results"]["ASR"]["decision_state"] == "HOLD"
    assert json.loads(second.read_text())["results"]["ASR"]["decision_state"] == "NO_ADD"


def test_missing_drift_snapshot_gives_clear_error(tmp_path):
    root = repo_copy(tmp_path)
    # main now carries generated drift revisions; remove them to test the error.
    shutil.rmtree(root / "data/drift", ignore_errors=True)
    write_owner_config(root, filled_owner_config(CFG, REPO_CFG))
    with pytest.raises(DecisionInputError, match="cockpit-drift --write"):
        build_decision_snapshot(root=root, as_of=AS_OF)


def test_decide_cli_write_logs_signals(tmp_path, capsys):
    from portfolio_cockpit.decision_layer.decision import main

    root = _end_to_end_root(tmp_path)
    assert main(["--root", str(root), "--as-of", AS_OF, "--write", "--code-version", "t"]) == 0
    log = root / f"data/signal_log/{AS_OF}.jsonl"
    lines = log.read_text().splitlines()
    assert len(lines) == 23
    assert main(["--root", str(root), "--as-of", AS_OF, "--write", "--code-version", "u"]) == 0
    assert log.read_text().splitlines() == lines
    asr = next(json.loads(line) for line in lines if json.loads(line)["ticker"] == "ASR")
    assert asr["price"] == 45.0
