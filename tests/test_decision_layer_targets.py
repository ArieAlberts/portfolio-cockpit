import hashlib
from copy import deepcopy
from dataclasses import replace

import pytest
from hypothesis import given, settings, strategies as st

from portfolio_cockpit.config import load_config
from portfolio_cockpit.decision_layer.config import DecisionConfigError, load_decision_config, validate_decision_config
from portfolio_cockpit.decision_layer.decision import (
    DecisionInputs,
    FORBIDDEN_OUTPUT_KEYS,
    build_decision_snapshot,
    decide,
    write_decision_snapshot,
)
from portfolio_cockpit.decision_layer.targets import TargetInput, compute_targets, quality_multiplier

from dl_helpers import AS_OF, ROOT, filled_owner_config, repo_copy, write_owner_config

REPO_CFG = load_config(ROOT)
CFG = load_decision_config(ROOT)
TARGET_CFG = CFG["target_adjustment"]
LIMITS = CFG["decision"]["limits"]

ITEM = TargetInput(
    ticker="X", base_target_weight_pct=4.0, role="CORE", sector="S",
    drift_score=50.0, drift_status="OK", drift_change_recent=0.0, observation_count=2,
    data_confidence=90.0, thesis_status="INTACT", valuation_label="Fair", valuation_status="OK",
)


def _targets(items, target_cfg=TARGET_CFG, limits=LIMITS):
    results, warnings = compute_targets(
        items, target_cfg=target_cfg, limits=limits, data_confidence_min=80.0, standard_shock=-0.30
    )
    return results, warnings


def _one(**changes):
    item = replace(ITEM, **changes)
    return _targets([item])[0][item.ticker]


def test_multiplier_points_and_dead_band():
    assert quality_multiplier(25, TARGET_CFG) == 0.5
    assert quality_multiplier(10, TARGET_CFG) == 0.5
    assert quality_multiplier(75, TARGET_CFG) == 1.5
    assert quality_multiplier(90, TARGET_CFG) == 1.5
    assert quality_multiplier(35, TARGET_CFG) == pytest.approx(0.75)
    assert quality_multiplier(65, TARGET_CFG) == pytest.approx(1.25)
    assert quality_multiplier(45, TARGET_CFG) == 1.0
    assert quality_multiplier(55, TARGET_CFG) == 1.0


@pytest.mark.parametrize("drift", [45.0, 48.0, 50.0, 53.0, 55.0])
def test_drift_50_or_dead_band_gives_base(drift):
    result = _one(drift_score=drift)
    assert result.quality_multiplier_raw == 1.0
    assert result.score_adjusted_target_pct == 4.0
    assert result.binding_constraint is None


@settings(max_examples=80, deadline=None)
@given(a=st.floats(min_value=0, max_value=100), b=st.floats(min_value=0, max_value=100),
       other=st.floats(min_value=0, max_value=100))
def test_higher_drift_never_gives_lower_target(a, b, other):
    lo, hi = sorted((a, b))
    neighbours = [replace(ITEM, ticker=f"N{i}", base_target_weight_pct=9.0, drift_score=other) for i in range(10)]
    t_lo = _targets([replace(ITEM, drift_score=lo)] + neighbours)[0]["X"].score_adjusted_target_pct
    t_hi = _targets([replace(ITEM, drift_score=hi)] + neighbours)[0]["X"].score_adjusted_target_pct
    assert t_hi >= t_lo - 1e-9


@pytest.mark.parametrize(
    "changes",
    [
        {"drift_score": 80.0, "data_confidence": 70.0},
        {"drift_score": 80.0, "data_confidence": None},
        {"drift_score": None, "drift_status": "DRIFT_DATA_CHECK"},
        {"drift_score": 80.0, "drift_status": "DRIFT_DATA_CHECK"},
        {"drift_score": 50.0, "drift_status": "NO_NEW_FUNDAMENTALS"},
        {"drift_score": None, "drift_status": None},
    ],
)
def test_data_check_or_missing_drift_never_raises_target(changes):
    result = _one(**changes)
    assert result.quality_multiplier_applied == 1.0
    assert result.score_adjusted_target_pct == 4.0


def test_expensive_blocks_increase_but_not_decrease():
    up = _one(drift_score=80.0, drift_change_recent=0.0, valuation_label="Expensive")
    assert up.score_adjusted_target_pct == 4.0
    assert "VALUATION_EXPENSIVE_CAP" in up.gates
    down = _one(drift_score=30.0, valuation_label="Expensive")
    assert down.score_adjusted_target_pct == pytest.approx(4.0 * 0.625)


def test_missing_valuation_also_blocks_increase():
    result = _one(drift_score=80.0, valuation_label=None, valuation_status="NO_MARKET_DATA")
    assert result.score_adjusted_target_pct == 4.0
    assert "VALUATION_UNAVAILABLE_CAP" in result.gates


def test_increase_needs_two_consecutive_improvements_decrease_is_direct():
    single = _one(drift_score=70.0, drift_change_recent=20.0, observation_count=1)
    assert single.score_adjusted_target_pct == 4.0
    assert "AWAITING_CONFIRMATION" in single.gates
    previous_neutral = _one(drift_score=70.0, drift_change_recent=20.0, observation_count=2)
    assert previous_neutral.score_adjusted_target_pct == 4.0
    confirmed = _one(drift_score=70.0, drift_change_recent=5.0, observation_count=2)
    # min(f(70)=1.375, f(65)=1.25)
    assert confirmed.quality_multiplier_applied == pytest.approx(1.25)
    assert confirmed.score_adjusted_target_pct == pytest.approx(5.0)
    decrease = _one(drift_score=30.0, drift_change_recent=-20.0, observation_count=1)
    assert decrease.score_adjusted_target_pct == pytest.approx(2.5)


def test_exit_role_targets_zero_and_broken_thesis_keeps_base():
    assert _one(role="EXIT", drift_score=80.0).score_adjusted_target_pct == 0.0
    broken = _one(thesis_status="BROKEN", drift_score=30.0)
    assert broken.score_adjusted_target_pct == 4.0
    assert "THESIS_BROKEN" in broken.gates


def test_position_impact_and_ticker_caps_are_respected():
    big = _one(base_target_weight_pct=9.0, drift_score=80.0)
    assert big.score_adjusted_target_pct == 10.0
    assert big.binding_constraint == "MAX_POSITION_WEIGHT"
    tight = dict(LIMITS, max_single_position_impact_pp=2.4)
    impact = _targets([replace(ITEM, base_target_weight_pct=7.0, drift_score=80.0)], limits=tight)[0]["X"]
    assert impact.score_adjusted_target_pct == pytest.approx(8.0)
    assert impact.binding_constraint == "MAX_SINGLE_POSITION_IMPACT"
    capped = dict(TARGET_CFG, max_weight_pct={"X": 4.5})
    ticker = _targets([replace(ITEM, drift_score=80.0)], target_cfg=capped)[0]["X"]
    assert ticker.score_adjusted_target_pct == 4.5
    assert ticker.binding_constraint == "MAX_WEIGHT_TICKER"


def test_sector_cap_scales_only_increases():
    items = [
        replace(ITEM, ticker="A", base_target_weight_pct=10.0, drift_score=80.0),
        replace(ITEM, ticker="B", base_target_weight_pct=10.0, drift_score=50.0),
        replace(ITEM, ticker="C", base_target_weight_pct=8.0, drift_score=30.0),  # x0.625 -> 5.0
        replace(ITEM, ticker="D", base_target_weight_pct=4.0, drift_score=80.0),
    ]
    results, _ = _targets(items)
    total = sum(r.score_adjusted_target_pct for r in results.values())
    assert total <= 30.0 + 1e-9
    assert results["B"].score_adjusted_target_pct == 10.0
    assert results["C"].score_adjusted_target_pct == pytest.approx(5.0)
    assert results["A"].score_adjusted_target_pct >= 10.0
    assert "SECTOR_CAP" in results["D"].constraints


def test_budget_scales_only_increases_and_respects_min_cash():
    # Ten 9.5% bases fill the 95% budget (min_cash 5%): an increase has no room.
    items = [replace(ITEM, ticker=f"T{i}", sector=f"S{i}", base_target_weight_pct=9.5) for i in range(10)]
    items[0] = replace(items[0], drift_score=80.0)
    items[1] = replace(items[1], drift_score=80.0)
    results, warnings = _targets(items)
    total = sum(r.score_adjusted_target_pct for r in results.values())
    assert total <= 100 - TARGET_CFG["budget"]["min_cash_pct"] + 1e-9
    assert not warnings
    for t in ("T0", "T1"):
        assert results[t].score_adjusted_target_pct == pytest.approx(9.5)
        assert results[t].binding_constraint == "PORTFOLIO_BUDGET"
    for t in ("T3", "T9"):
        assert results[t].score_adjusted_target_pct == 9.5


def test_budget_room_from_a_decrease_funds_increases_without_touching_decreases():
    items = [replace(ITEM, ticker=f"T{i}", sector=f"S{i}", base_target_weight_pct=9.5) for i in range(10)]
    items[0] = replace(items[0], base_target_weight_pct=6.0, drift_score=80.0)
    items[1] = replace(items[1], base_target_weight_pct=6.0, drift_score=80.0)
    items[2] = replace(items[2], base_target_weight_pct=9.0, drift_score=30.0)
    # bases: 6+6+9+7*9.5 = 87.5; decrease frees 3.375; increases want 2*3 = 6 -> room 95-(87.5-3.375)
    results, _ = _targets(items)
    assert results["T2"].score_adjusted_target_pct == pytest.approx(9.0 * 0.625)
    assert results["T0"].score_adjusted_target_pct == pytest.approx(9.0)
    total = sum(r.score_adjusted_target_pct for r in results.values())
    assert total <= 95.0 + 1e-9
    # Tighter: four increases compete for the room and are scaled pro rata.
    # 11 x 8.5 = 93.5; T10 drops to 8.5 x 0.625 = 5.3125 (frees 3.1875); four increases
    # want +1.5 each (cap 10) = 6.0 but only 95 - 90.3125 = 4.6875 is left.
    items = [replace(ITEM, ticker=f"T{i}", sector=f"S{i}", base_target_weight_pct=8.5) for i in range(11)]
    for i in range(4):
        items[i] = replace(items[i], drift_score=80.0)
    items[10] = replace(items[10], drift_score=30.0)
    results, _ = _targets(items)
    total = sum(r.score_adjusted_target_pct for r in results.values())
    assert total == pytest.approx(95.0)
    assert results["T10"].score_adjusted_target_pct == pytest.approx(5.3125)
    assert results["T0"].binding_constraint == "PORTFOLIO_BUDGET"
    assert results["T0"].score_adjusted_target_pct == pytest.approx(8.5 + 1.5 * 4.6875 / 6.0)


def _decision(current, target_result, base=7.0):
    return decide(
        DecisionInputs(
            ticker="X", drift_score=60.0, drift_change_recent=0.0, drift_status="OK",
            valuation_score=50.0, valuation_status="OK", data_confidence=90.0, thesis_status="INTACT",
            current_weight_pct=current, base_target_weight_pct=base,
            score_adjusted_target_pct=target_result.score_adjusted_target_pct,
            sector_weight_pct=20.0, portfolio_impact_pp=-current * 0.3, role="CORE", valuation_label="Fair",
            quality_multiplier_applied=target_result.quality_multiplier_applied,
        ),
        CFG["decision"],
        TARGET_CFG,
    )


def test_price_rise_without_drift_improvement_is_price_only_trim():
    target = _one(base_target_weight_pct=7.0, drift_score=50.0)
    result = _decision(9.0, target)  # 7% grew to 9% on price; band upper 8.4%
    assert result.decision_state == "TRIM_CANDIDATE"
    assert "PRICE_ONLY" in result.reasons


def test_price_rise_with_supported_improvement_within_band_is_hold():
    target = _one(base_target_weight_pct=7.0, drift_score=65.0, drift_change_recent=2.0, observation_count=2)
    assert target.score_adjusted_target_pct == pytest.approx(7.0 * min(1.25, 1.2))
    result = _decision(9.0, target)
    assert result.decision_state == "HOLD"
    assert "WITHIN_BAND" in result.reasons


def _hash_tree(root):
    files = [root / "config/portfolio.yaml"] + sorted((root / "data/baselines").rglob("*.json"))
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def test_portfolio_and_baselines_are_byte_identical_after_run(tmp_path):
    from portfolio_cockpit.decision_layer.drift import build_drift_snapshot, write_drift_snapshot
    from portfolio_cockpit.decision_layer.valuation import build_valuation_snapshot, write_valuation_snapshot

    root = repo_copy(tmp_path)
    write_owner_config(root, filled_owner_config(CFG, REPO_CFG))
    before = _hash_tree(root)
    write_drift_snapshot(root, build_drift_snapshot(root=root, as_of=AS_OF, code_version="t"))
    write_valuation_snapshot(root, build_valuation_snapshot(root=root, as_of=AS_OF, code_version="t"))
    payload = build_decision_snapshot(root=root, as_of=AS_OF, code_version="t")
    write_decision_snapshot(root, payload)
    assert _hash_tree(root) == before

    def keys(value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from keys(v)
        elif isinstance(value, list):
            for v in value:
                yield from keys(v)

    assert not set(keys(payload)) & FORBIDDEN_OUTPUT_KEYS
    assert payload["adjusted_target_total_pct"] <= 100 - TARGET_CFG["budget"]["min_cash_pct"] + 1e-9


def _set_flat_segment(target_cfg, multiplier):
    for point in target_cfg["quality_multiplier"]["points"]:
        if 45 <= point["drift"] <= 55:
            point["multiplier"] = multiplier


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda t: t["quality_multiplier"]["points"].reverse(), "strictly increasing"),
        (lambda t: _set_flat_segment(t, 0.9), "drift 50 to multiplier 1.00"),
        (lambda t: t["quality_multiplier"]["dead_band"].update(low=51), "must contain 50"),
        (lambda t: t["gates"].update(min_consecutive_improvements=3), "must be 1 or 2"),
        (lambda t: t["budget"].update(min_cash_pct=10), "base targets already sum"),
        (lambda t: t.update(rebalance_band_pct=0), "rebalance_band_pct must be > 0"),
        (lambda t: t.update(max_weight_pct={"XYZ": 3}), "not in portfolio.yaml"),
    ],
)
def test_target_adjustment_validator_rejects(mutate, match):
    broken = deepcopy(CFG)
    mutate(broken["target_adjustment"])
    with pytest.raises(DecisionConfigError, match=match):
        validate_decision_config(broken, REPO_CFG)


def test_multiplier_sweep_is_continuous_monotonic_and_flat_in_dead_band():
    steps = [round(i * 0.1, 1) for i in range(0, 1001)]
    values = [quality_multiplier(d, TARGET_CFG) for d in steps]
    jumps = [b - a for a, b in zip(values, values[1:])]
    assert max(abs(j) for j in jumps) <= 0.01
    assert all(j >= -1e-12 for j in jumps)
    for d, v in zip(steps, values):
        if 45.0 <= d <= 55.0:
            assert v == 1.0, d
    assert values[0] == 0.5 and values[-1] == 1.5
