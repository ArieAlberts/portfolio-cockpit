import ast
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from portfolio_cockpit.config import load_config
from portfolio_cockpit.decision_layer.config import (
    DecisionConfigError,
    load_decision_config,
    validate_decision_config,
)
from portfolio_cockpit.decision_layer.drift import (
    ObservationError,
    build_drift_snapshot,
    build_ticker_drift,
    normalize,
    write_drift_snapshot,
)

from dl_helpers import AS_OF, ROOT, load_baseline, observation_from_baseline, repo_copy, write_observation


REPO_CFG = load_config(ROOT)
CFG = load_decision_config(ROOT)
DRIFT_CFG = CFG["quality_drift"]
TICKERS = list(REPO_CFG["portfolio"]["positions"])


def _drift(ticker, observations=(), drift_cfg=DRIFT_CFG, as_of=AS_OF):
    rel, baseline = load_baseline(ticker)
    return build_ticker_drift(
        ticker=ticker,
        company_type=REPO_CFG["portfolio"]["positions"][ticker]["company_type"],
        drift_cfg=drift_cfg,
        baseline=baseline,
        baseline_rel=rel,
        observations=[(f"data/observations/{ticker}/{i}.json", o) for i, o in enumerate(observations)],
        as_of=as_of,
    )


def test_real_repo_drift_is_exactly_50_for_all_23():
    snapshot = build_drift_snapshot(root=ROOT, as_of=AS_OF, code_version="test")
    assert len(snapshot["results"]) == 23
    for ticker, result in snapshot["results"].items():
        assert result["drift_score"] == 50.0, ticker
        assert result["drift_change_since_baseline"] == 0.0
        assert result["status"] == "NO_NEW_FUNDAMENTALS"
        assert not any(w.startswith("BASELINE_MISSING_REQUIRED") for w in result["warnings"])
    assert snapshot["execution_effect"] == "NONE"
    assert snapshot["methodology"]["price_inputs"] == "NONE"


@pytest.mark.parametrize("ticker", TICKERS)
def test_observation_equal_to_baseline_gives_50(ticker):
    result = _drift(ticker, [observation_from_baseline(ticker, DRIFT_CFG)])
    assert result["status"] == "OK", result["warnings"]
    assert result["drift_score"] == 50.0
    assert result["drift_change_recent"] == 0.0
    assert result["coverage"] == pytest.approx(1.0)


def test_metric_output_has_full_explanation():
    obs = observation_from_baseline("ASR", DRIFT_CFG, overrides={"solvency_ii_ratio_pct": 237})
    result = _drift("ASR", [obs])
    solvency = next(m for m in result["metrics"] if m["metric"] == "solvency_ii_ratio_pct")
    for key in (
        "baseline_value", "baseline_date", "baseline_source", "previous_value", "raw_value",
        "delta", "normalized_signal", "contribution_points", "source",
    ):
        assert key in solvency
    assert solvency["delta"] == 15
    # (15 - 0 dead band applied only within band) / 30 full scale
    assert solvency["normalized_signal"] == pytest.approx(0.5)
    assert solvency["source"]["publication_date"] == "2026-09-30"
    total = sum(m["contribution_points"] for m in result["metrics"])
    assert result["drift_score"] == pytest.approx(50.0 + total)


def test_improvement_and_deterioration_follow_direction():
    better = observation_from_baseline("PLMR", DRIFT_CFG, overrides={"combined_ratio_pct": 70, "adjusted_combined_ratio_pct": 70})
    worse = observation_from_baseline("PLMR", DRIFT_CFG, overrides={"combined_ratio_pct": 95, "adjusted_combined_ratio_pct": 95})
    assert _drift("PLMR", [better])["drift_score"] > 50.0
    assert _drift("PLMR", [worse])["drift_score"] < 50.0


def test_clamp_to_0_and_100():
    _, baseline = load_baseline("ERO")
    up = {m: (v * 10 if "cost" not in m and "debt" not in m else v / 10)
          for c in baseline["metrics"].values() for m, v in c.items()}
    down = {m: (v / 10 if "cost" not in m and "debt" not in m else v * 10)
            for c in baseline["metrics"].values() for m, v in c.items()}
    assert _drift("ERO", [observation_from_baseline("ERO", DRIFT_CFG, overrides=up)])["drift_score"] == 100.0
    assert _drift("ERO", [observation_from_baseline("ERO", DRIFT_CFG, overrides=down)])["drift_score"] == 0.0


def test_dead_band_counts_as_zero():
    # Solvency dead band is 3 points.
    inside = observation_from_baseline("ASR", DRIFT_CFG, overrides={"solvency_ii_ratio_pct": 225})
    outside = observation_from_baseline("ASR", DRIFT_CFG, overrides={"solvency_ii_ratio_pct": 226})
    assert _drift("ASR", [inside])["drift_score"] == 50.0
    assert _drift("ASR", [outside])["drift_score"] > 50.0


@settings(max_examples=60, deadline=None)
@given(
    base=st.floats(min_value=0.1, max_value=1e4),
    a=st.floats(min_value=-1e4, max_value=1e4),
    b=st.floats(min_value=-1e4, max_value=1e4),
    mode=st.sampled_from(["relative", "absolute"]),
    direction=st.sampled_from(["higher_is_better", "lower_is_better"]),
)
def test_normalize_is_monotonic_per_direction(base, a, b, mode, direction):
    lo, hi = sorted((a, b))
    kwargs = dict(baseline_value=base, mode=mode, direction=direction, full_scale=0.3, dead_band=0.02)
    _, s_lo = normalize(raw_value=lo, **kwargs)
    _, s_hi = normalize(raw_value=hi, **kwargs)
    assert -1.0 <= s_lo <= 1.0 and -1.0 <= s_hi <= 1.0
    if direction == "higher_is_better":
        assert s_hi >= s_lo
    else:
        assert s_hi <= s_lo


def test_period_mismatch_excludes_metric():
    # ASR baseline is H1; an FY operating ROE is not like-for-like.
    obs = observation_from_baseline(
        "ASR", DRIFT_CFG,
        overrides={"operating_roe_pct": 25.0},
        period_basis={"operating_roe_pct": "FY"},
    )
    result = _drift("ASR", [obs])
    assert "PERIOD_MISMATCH:operating_roe_pct" in result["warnings"]
    roe = next(m for m in result["metrics"] if m["metric"] == "operating_roe_pct")
    assert roe["status"] == "PERIOD_MISMATCH"
    assert roe["contribution_points"] == 0.0
    assert result["drift_score"] == 50.0


def test_point_in_time_metric_ignores_period_basis():
    obs = observation_from_baseline(
        "ASR", DRIFT_CFG,
        overrides={"solvency_ii_ratio_pct": 240},
        period_basis={"solvency_ii_ratio_pct": "FY"},
    )
    assert _drift("ASR", [obs])["drift_score"] > 50.0


def test_missing_required_component_gives_drift_data_check():
    obs = observation_from_baseline("ASR", DRIFT_CFG, drop=("solvency_ii_ratio_pct",))
    result = _drift("ASR", [obs])
    assert result["status"] == "DRIFT_DATA_CHECK"
    assert result["drift_score"] is None
    assert result["diagnostic_drift_score"] is not None
    assert "MISSING_REQUIRED_COMPONENT:capital_strength" in result["warnings"]


def test_low_coverage_gives_drift_data_check():
    _, baseline = load_baseline("ERO")
    keep = {"net_debt_usd_m", "copper_c1_cash_cost_usd_per_lb"}
    drop = tuple(m for c in baseline["metrics"].values() for m in c if m not in keep)
    result = _drift("ERO", [observation_from_baseline("ERO", DRIFT_CFG, drop=drop)])
    assert result["status"] == "DRIFT_DATA_CHECK"
    assert any(w.startswith("DRIFT_COVERAGE_BELOW_THRESHOLD") for w in result["warnings"])


def test_drift_change_recent_compares_with_previous_observation():
    first = observation_from_baseline("ASR", DRIFT_CFG, observation_date="2026-09-01",
                                      overrides={"solvency_ii_ratio_pct": 237})
    second = observation_from_baseline("ASR", DRIFT_CFG, observation_date="2026-09-30",
                                       overrides={"solvency_ii_ratio_pct": 207})
    one = _drift("ASR", [first])
    two = _drift("ASR", [first, second])
    assert two["drift_change_recent"] == pytest.approx(two["drift_score"] - one["drift_score"])
    solvency = next(m for m in two["metrics"] if m["metric"] == "solvency_ii_ratio_pct")
    assert solvency["previous_value"] == 237


def test_stale_fundamentals_warn():
    result = _drift("MSM", as_of="2027-06-01")
    assert any(w.startswith("STALE_DATA:last_fundamental_update") for w in result["warnings"])


def test_baselines_are_immutable():
    fixture = json.loads((ROOT / "tests/fixtures/baseline_hashes.json").read_text())
    index = ROOT / fixture["index"]["path"]
    assert hashlib.sha256(index.read_bytes()).hexdigest() == fixture["index"]["sha256"]
    listed = json.loads(index.read_text())["baselines"]
    assert set(listed) == set(fixture["baselines"])
    for ticker, item in fixture["baselines"].items():
        assert listed[ticker] == item["path"]
        assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"], ticker


def test_drift_module_imports_no_market_or_valuation_code():
    source = (ROOT / "src/portfolio_cockpit/decision_layer/drift.py").read_text()
    modules = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    forbidden = ("valuation", "market", "price", "broker", "ibkr")
    assert not [m for m in modules if any(f in m.lower() for f in forbidden)]
    assert "data/market" not in source


def test_noop_rebuild_is_byte_stable(tmp_path):
    root = repo_copy(tmp_path)
    write_observation(root, observation_from_baseline("ASR", DRIFT_CFG, overrides={"solvency_ii_ratio_pct": 240}))
    first = write_drift_snapshot(root, build_drift_snapshot(root=root, as_of=AS_OF, code_version="a"))
    body = first.read_bytes()
    pointer = (root / "data/drift/current.json").read_bytes()
    second = write_drift_snapshot(root, build_drift_snapshot(root=root, as_of=AS_OF, code_version="b"))
    assert second == first
    assert first.read_bytes() == body
    assert (root / "data/drift/current.json").read_bytes() == pointer
    # A new observation creates a new revision; the old one is preserved.
    write_observation(root, observation_from_baseline("ASR", DRIFT_CFG, observation_date="2026-10-01",
                                                      overrides={"solvency_ii_ratio_pct": 200}))
    third = write_drift_snapshot(root, build_drift_snapshot(root=root, as_of=AS_OF, code_version="c"))
    assert third.name == f"quality_drift_{AS_OF}_r2.json"
    assert first.read_bytes() == body


def test_invalid_observation_fails_fast(tmp_path):
    root = repo_copy(tmp_path)
    obs = observation_from_baseline("ASR", DRIFT_CFG)
    del obs["metrics"]["capital_strength"]["solvency_ii_ratio_pct"]["source"]["publication_date"]
    write_observation(root, obs)
    with pytest.raises(ObservationError, match="source.publication_date is required"):
        build_drift_snapshot(root=root, as_of=AS_OF)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d["profiles"]["INSURER"]["components"]["capital_strength"].update(weight=0.5), "component weights sum"),
        (lambda d: d["profiles"]["INSURER"]["components"]["capital_strength"]["slots"]["solvency"].update(direction="lower_is_better"), "conflicts with score_metrics"),
        (lambda d: d["profiles"]["INSURER"]["components"]["capital_strength"]["slots"]["solvency"]["aliases"].append("solvency_ratio_prior_pct"), "excluded pattern"),
        (lambda d: d["profiles"].pop("CYCLICAL_MINING"), "exactly the company types"),
        (lambda d: d["profiles"]["INSURER"].update(required_components=["nope"]), "required_components"),
        (lambda d: d["baseline_period_basis"]["by_ticker"].update(ASR="H3"), "invalid basis"),
        (lambda d: d["profiles"]["INSURER"]["components"]["capital_strength"]["slots"]["solvency"].update(dead_band=40), "dead_band must be below"),
    ],
)
def test_drift_config_validator_rejects(mutate, match):
    broken = deepcopy(CFG)
    mutate(broken["quality_drift"])
    with pytest.raises(DecisionConfigError, match=match):
        validate_decision_config(broken, REPO_CFG)


def test_low_confidence_observation_is_rejected_and_reported(tmp_path):
    root = repo_copy(tmp_path)
    obs = observation_from_baseline("ASR", DRIFT_CFG, overrides={"solvency_ii_ratio_pct": 260})
    obs["source_confidence"] = 60
    write_observation(root, obs)
    result = build_drift_snapshot(root=root, as_of=AS_OF, code_version="t")["results"]["ASR"]
    assert result["drift_score"] == 50.0
    assert result["status"] == "NO_NEW_FUNDAMENTALS"
    assert any(w.startswith("OBSERVATION_REJECTED:") and "source_confidence:60<80" in w for w in result["warnings"])


def test_unknown_or_price_trigger_fails_fast(tmp_path):
    root = repo_copy(tmp_path)
    obs = observation_from_baseline("ASR", DRIFT_CFG)
    obs["update_trigger"] = "share_price_move"
    write_observation(root, obs)
    with pytest.raises(ObservationError, match="update_trigger 'share_price_move' is not allowed"):
        build_drift_snapshot(root=root, as_of=AS_OF)


def test_observation_requires_trigger_and_confidence(tmp_path):
    root = repo_copy(tmp_path)
    obs = observation_from_baseline("ASR", DRIFT_CFG)
    del obs["update_trigger"]
    obs["source_confidence"] = 120
    write_observation(root, obs)
    with pytest.raises(ObservationError) as exc:
        build_drift_snapshot(root=root, as_of=AS_OF)
    assert "update_trigger is required" in str(exc.value)
    assert "source_confidence must be a number in [0, 100]" in str(exc.value)


@pytest.mark.parametrize("trigger", ["market_price", "technical_signal", "price_breakout"])
def test_config_forbids_price_triggers(trigger):
    broken = deepcopy(CFG)
    broken["quality_drift"]["evidence_gate"]["allowed_update_triggers"].append(trigger)
    with pytest.raises(DecisionConfigError, match="price, market or technical triggers are forbidden"):
        validate_decision_config(broken, REPO_CFG)


def _write_rebaseline(root, ticker="ASR", date_str="2026-09-15", parent=None, name=None, **overrides):
    rel, baseline = load_baseline(ticker, root)
    payload = deepcopy(baseline)
    payload.update(
        baseline_date=date_str,
        rebaseline_of=parent or rel,
        rebaseline_reason="Owner changed base target from 7% to 6%",
        base_target_weight_pct=6.0,
        quality_drift_score=50,
    )
    payload.update(overrides)
    path = root / "data/baselines" / ticker / (name or f"{date_str}.json")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path.relative_to(root).as_posix(), payload


def test_rebaseline_adds_a_file_and_never_edits_the_old_one(tmp_path):
    root = repo_copy(tmp_path)
    old_rel, _ = load_baseline("ASR", root)
    old_bytes = (root / old_rel).read_bytes()
    index_bytes = (root / "data/baselines/index.json").read_bytes()
    new_rel, _ = _write_rebaseline(root)
    # An observation from before the new baseline belongs to the old period and is ignored.
    write_observation(root, observation_from_baseline("ASR", DRIFT_CFG, observation_date="2026-09-01",
                                                      overrides={"solvency_ii_ratio_pct": 300}, root=root))
    result = build_drift_snapshot(root=root, as_of=AS_OF, code_version="t")["results"]["ASR"]
    assert result["baseline"]["path"] == new_rel
    assert result["baseline"]["chain"] == [old_rel, new_rel]
    assert result["drift_score"] == 50.0 and result["status"] == "NO_NEW_FUNDAMENTALS"
    assert (root / old_rel).read_bytes() == old_bytes
    assert (root / "data/baselines/index.json").read_bytes() == index_bytes


def test_rebaseline_measures_drift_from_the_new_baseline(tmp_path):
    root = repo_copy(tmp_path)
    _write_rebaseline(root)
    obs = observation_from_baseline("ASR", DRIFT_CFG, observation_date="2026-09-30", root=root)
    write_observation(root, obs)
    result = build_drift_snapshot(root=root, as_of=AS_OF, code_version="t")["results"]["ASR"]
    assert result["status"] == "OK" and result["drift_score"] == 50.0


def test_future_rebaseline_is_not_active_yet(tmp_path):
    root = repo_copy(tmp_path)
    old_rel, _ = load_baseline("ASR", root)
    _write_rebaseline(root, date_str="2026-12-01")
    result = build_drift_snapshot(root=root, as_of=AS_OF, code_version="t")["results"]["ASR"]
    assert result["baseline"]["path"] == old_rel


def test_two_rebaselines_of_one_baseline_are_refused(tmp_path):
    from portfolio_cockpit.decision_layer.drift import BaselineError

    root = repo_copy(tmp_path)
    _write_rebaseline(root, date_str="2026-09-15")
    _write_rebaseline(root, date_str="2026-09-20")
    with pytest.raises(BaselineError, match="keep one chain"):
        build_drift_snapshot(root=root, as_of=AS_OF)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"quality_drift_score": 60}, "quality_drift_score must be 50"),
        ({"baseline_date": "2026-08-01"}, "must be after the baseline it replaces"),
        ({"rebaseline_reason": ""}, "rebaseline_reason is required"),
        ({"base_target_weight_pct": 140}, "base_target_weight_pct must be a number"),
    ],
)
def test_invalid_rebaseline_fails_fast(tmp_path, overrides, match):
    from portfolio_cockpit.decision_layer.drift import BaselineError

    root = repo_copy(tmp_path)
    _write_rebaseline(root, name="2026-09-15.json", **overrides)
    with pytest.raises(BaselineError, match=match):
        build_drift_snapshot(root=root, as_of=AS_OF)
