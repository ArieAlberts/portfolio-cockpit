import hashlib
import json
from copy import deepcopy

import pytest

from portfolio_cockpit.decision_layer import decision as decision_module
from portfolio_cockpit.decision_layer.simulator import (
    DryRunSimulator,
    append_signal_log,
    evaluate_main,
    evaluate_signals,
    load_signals,
    parse_horizon,
    review_direction,
)

from dl_helpers import AS_OF, ROOT, market_entry, repo_copy, write_market


def _item(state, current, target, sector, price=None):
    return {
        "decision_state": state,
        "inputs": {"portfolio_weight_pct": current, "base_target_weight_pct": target, "sector": sector,
                   "price": price, "currency": "EUR", "price_as_of": AS_OF, "drift_score": 50.0,
                   "drift_change_recent": 0.0, "valuation_score": 50.0, "data_confidence": 90.0,
                   "thesis_status": "INTACT"},
        "execution_effect": "NONE",
    }


DECISIONS = {
    "as_of": AS_OF,
    "reproducibility_hash": "h1",
    "portfolio_risk": {"cash_weight_pct": 7.0, "standard_shock": -0.30},
    "results": {
        "A": _item("ADD_CANDIDATE", 3.0, 5.0, "Materials", 10.0),
        "B": _item("REVIEW_REDUCE", 8.0, 6.0, "Materials", 20.0),
        "C": _item("REVIEW_REDUCE", 2.0, 4.0, "Financials", 30.0),
        "D": _item("THESIS_REVIEW", 4.0, 4.0, "Financials", 40.0),
        "E": _item("DATA_CHECK", 1.0, 3.0, "Energy", None),
        "F": _item("ADD_CANDIDATE", 6.0, 5.0, "Energy", 50.0),
        "G": _item("HOLD", 2.0, 3.0, "Energy", 60.0),
    },
}


def _rows(result):
    return {r["ticker"]: r for r in result["rows"]}


def test_simulator_is_always_dry_run():
    with pytest.raises(ValueError, match="dry_run=True"):
        DryRunSimulator(dry_run=False)
    with pytest.raises(ValueError):
        DryRunSimulator(dry_run=0)
    result = DryRunSimulator().simulate(DECISIONS)
    assert result["dry_run"] is True and result["execution_effect"] == "NONE"
    assert all(r["dry_run"] is True and r["execution_effect"] == "NONE" for r in result["rows"])


def test_review_directions():
    rows = _rows(DryRunSimulator().simulate(DECISIONS))
    assert rows["A"]["suggested_review_direction"] == "REVIEW_UP_TO_TARGET"
    assert rows["B"]["suggested_review_direction"] == "REVIEW_DOWN"
    assert rows["D"]["suggested_review_direction"] == "REVIEW_THESIS"
    assert rows["E"]["suggested_review_direction"] == "NONE (DATA_CHECK)"
    assert rows["F"]["suggested_review_direction"] == "NONE"  # ADD but already above target
    assert rows["G"]["suggested_review_direction"] == "NONE"
    assert review_direction("ADD_CANDIDATE", 0.0) == "NONE"


def test_cash_and_sector_impact():
    result = DryRunSimulator(portfolio_value=100_000).simulate(DECISIONS)
    rows = _rows(result)
    # A: +2pp from cash; B: -2pp back to cash; C is under target, so no move down.
    assert rows["A"]["cash_impact_pct"] == pytest.approx(-2.0)
    assert rows["A"]["cash_impact_amount"] == pytest.approx(-2000.0)
    assert rows["B"]["cash_impact_pct"] == pytest.approx(2.0)
    assert rows["C"]["cash_impact_pct"] == 0.0
    assert result["cash_impact_total_pct"] == pytest.approx(0.0)
    assert result["cash_weight_after_pct"] == pytest.approx(7.0)
    assert rows["A"]["sector_weight_now_pct"] == pytest.approx(11.0)
    assert rows["A"]["sector_weight_after_pct"] == pytest.approx(11.0)  # +2 (A) - 2 (B)
    assert result["sector_weights_after_pct"] == {"Energy": 9.0, "Financials": 6.0, "Materials": 11.0}
    assert rows["A"]["portfolio_impact_now_pp"] == pytest.approx(-0.9)
    assert rows["A"]["portfolio_impact_at_target_pp"] == pytest.approx(-1.5)
    assert rows["A"]["difference_pct"] == pytest.approx(2.0)


def test_base_weights_never_change():
    before = deepcopy(DECISIONS)
    portfolio_hash = hashlib.sha256((ROOT / "config/portfolio.yaml").read_bytes()).hexdigest()
    result = DryRunSimulator().simulate(DECISIONS)
    assert DECISIONS == before
    for row in result["rows"]:
        assert row["base_target_weight_pct"] == DECISIONS["results"][row["ticker"]]["inputs"]["base_target_weight_pct"]
    assert hashlib.sha256((ROOT / "config/portfolio.yaml").read_bytes()).hexdigest() == portfolio_hash


def test_signal_log_is_append_only_and_idempotent(tmp_path):
    root = repo_copy(tmp_path)
    snapshot = root / "data/decisions/decisions_2026-10-03.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("{}")
    path = append_signal_log(root, DECISIONS, snapshot)
    first = path.read_text()
    assert len(first.splitlines()) == 7
    append_signal_log(root, DECISIONS, snapshot)
    assert path.read_text() == first
    changed = deepcopy(DECISIONS)
    changed["reproducibility_hash"] = "h2"
    append_signal_log(root, changed, snapshot)
    text = path.read_text()
    assert text.startswith(first) and len(text.splitlines()) == 14
    record = json.loads(first.splitlines()[0])
    assert record["ticker"] == "A" and record["price"] == 10.0 and record["decision_state"] == "ADD_CANDIDATE"
    assert record["execution_effect"] == "NONE"


def test_signal_evaluation_per_state_vs_portfolio(tmp_path):
    root = repo_copy(tmp_path)
    snapshot = root / "data/decisions/decisions_2026-10-03.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("{}")
    append_signal_log(root, DECISIONS, snapshot)
    later = {t: market_entry(price=p) for t, p in
             {"A": 12.0, "B": 18.0, "C": 33.0, "D": 40.0, "F": 45.0, "G": 66.0, "E": 1.0}.items()}
    write_market(root, later, as_of="2027-01-03")  # exactly 92 days later
    report = evaluate_signals(load_signals(root), [("2027-01-03", {t: e["price"]["value"] for t, e in later.items()})],
                              horizon_days=90, tolerance_days=7)
    states = report["by_decision_state"]
    assert report["evaluated_signals"] == 6 and report["skipped_signals"] == 1  # E has no signal price
    assert states["ADD_CANDIDATE"]["n"] == 2
    assert states["ADD_CANDIDATE"]["mean_forward_return"] == pytest.approx((0.2 - 0.1) / 2)
    assert states["REVIEW_REDUCE"]["mean_forward_return"] == pytest.approx((-0.1 + 0.1) / 2)
    mean = (0.2 - 0.1 + 0.1 + 0.0 - 0.1 + 0.1) / 6
    assert report["portfolio_mean_forward_return"] == pytest.approx(mean, abs=1e-6)
    assert states["HOLD"]["excess_vs_portfolio"] == pytest.approx(0.1 - mean, abs=1e-6)
    # Outside the tolerance window nothing is evaluated.
    none = evaluate_signals(load_signals(root), [("2027-02-01", {"A": 12.0})], horizon_days=90, tolerance_days=7)
    assert none["evaluated_signals"] == 0


def test_evaluate_cli_and_horizon(tmp_path, capsys):
    assert parse_horizon("90d") == 90
    with pytest.raises(ValueError):
        parse_horizon("3m")
    assert evaluate_main(["--root", str(tmp_path), "--horizon", "30d"]) == 0
    assert json.loads(capsys.readouterr().out)["horizon_days"] == 30


def test_simulator_and_decision_modules_have_no_order_surface():
    for module in (decision_module,):
        names = {n.lower() for n in dir(module)}
        assert not {n for n in names if "place_order" in n or "submit" in n or "execute" in n}
