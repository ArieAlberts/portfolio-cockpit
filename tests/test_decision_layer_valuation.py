import ast
import json
from copy import deepcopy

import pytest

from portfolio_cockpit.config import load_config
from portfolio_cockpit.decision_layer.config import (
    DecisionConfigError,
    load_decision_config,
    validate_decision_config,
)
from portfolio_cockpit.decision_layer.drift import build_drift_snapshot
from portfolio_cockpit.decision_layer.valuation import (
    MarketDataError,
    build_ticker_valuation,
    build_valuation_snapshot,
    validate_market_file,
    validate_reference_file,
    write_valuation_snapshot,
)

from dl_helpers import (
    AS_OF, ROOT, market_entry, observation_from_baseline, reference, repo_copy,
    write_market, write_observation, write_refs,
)


REPO_CFG = load_config(ROOT)
CFG = load_decision_config(ROOT)
VAL_CFG = CFG["valuation"]


def _val(ticker, entry, refs=None, as_of=AS_OF):
    return build_ticker_valuation(
        ticker=ticker,
        company_type=REPO_CFG["portfolio"]["positions"][ticker]["company_type"],
        entry=entry,
        refs=refs or {},
        cfg=VAL_CFG,
        as_of=as_of,
    )


def _metric(result, name):
    return next(m for m in result["metrics"] if m["metric"] == name)


ASR_ENTRY = dict(price=60.0, shares_outstanding=210.0, net_debt=0.0, eps_ttm=6.0, bvps=40.0,
                 distributions_ttm=1100.0, ebitda=2000.0, ebit=1800.0, fcf=1500.0)
ASR_REFS = {"pe": reference(10.0, 11.0), "price_to_book": reference(1.4, 1.6),
            "shareholder_yield": reference(0.08, 0.07)}


def test_real_repo_has_no_market_data_yet():
    snapshot = build_valuation_snapshot(root=ROOT, as_of=AS_OF, code_version="test")
    assert snapshot["summary"]["NO_MARKET_DATA"] == 23
    for result in snapshot["results"].values():
        assert result["valuation_score"] is None
        assert any(w.startswith("MISSING_DATA:market") for w in result["warnings"])


def test_insurer_never_uses_ev_ebitda_ebit_or_fcf():
    for ticker in ("ASR", "PLMR"):
        result = _val(ticker, market_entry(**ASR_ENTRY), ASR_REFS)
        for name in ("ev_ebitda", "ev_ebit", "fcf_yield"):
            metric = _metric(result, name)
            assert metric["status"] == "NOT_APPLICABLE"
            assert metric["value"] is None and metric["score"] is None and metric["weight"] == 0.0
        assert result["status"] == "OK"
        assert result["label"] in {"Attractive", "Fair", "Expensive"}


def test_pre_revenue_has_no_pe_interpretation():
    entry = market_entry(currency="USD", price=80.0, shares_outstanding=185.0, eps_ttm=-0.9, forward_eps=0.5,
                         navps=None, risked_npv=None)
    result = _val("OKLO", entry)
    for name in ("pe", "forward_pe", "ev_ebitda", "ev_ebit", "fcf_yield"):
        metric = _metric(result, name)
        assert metric["status"] == "NOT_APPLICABLE"
        assert metric["value"] is None
    assert result["valuation_score"] is None


@pytest.mark.parametrize(
    ("ticker", "entry", "metric"),
    [
        ("ASR", {**ASR_ENTRY, "eps_ttm": -2.0}, "pe"),
        ("WKL", dict(price=70.0, shares_outstanding=225.0, net_debt=4000.0, forward_eps=-1.0, ebit=-50.0, fcf=1300.0), "forward_pe"),
        ("WKL", dict(price=70.0, shares_outstanding=225.0, net_debt=4000.0, forward_eps=-1.0, ebit=-50.0, fcf=1300.0), "ev_ebit"),
        ("ERO", dict(price=20.0, shares_outstanding=100.0, net_debt=-5000.0, normalized_ebitda=500.0, navps=25.0, fcf=50.0), "ev_normalized_ebitda"),
    ],
)
def test_negative_multiple_is_never_cheap(ticker, entry, metric):
    refs = {m: reference(10.0, 10.0) for m in VAL_CFG["profiles"][REPO_CFG["portfolio"]["positions"][ticker]["company_type"]]["weights"]}
    result = _val(ticker, market_entry(**entry), refs)
    item = _metric(result, metric)
    assert item["status"] == "NOT_APPLICABLE"
    assert item["score"] is None
    assert f"UNSUITABLE_METRIC:{metric}" in result["warnings"]


def test_no_reference_means_no_score():
    result = _val("ASR", market_entry(**ASR_ENTRY))
    for name in ("pe", "price_to_book", "shareholder_yield"):
        metric = _metric(result, name)
        assert metric["status"] == "NO_REFERENCE"
        assert metric["value"] is not None and metric["score"] is None
    assert result["valuation_score"] is None
    assert result["status"] == "VALUATION_DATA_CHECK"


def test_provenance_fields_present():
    result = _val("ASR", market_entry(**ASR_ENTRY), ASR_REFS)
    pe = _metric(result, "pe")
    for key in ("value", "status", "score", "reference_value", "source", "as_of_date",
                "calculation_method", "raw_inputs"):
        assert key in pe
    assert pe["value"] == pytest.approx(10.0)
    assert pe["reference_value"] == pytest.approx(0.6 * 10 + 0.4 * 11)
    assert pe["raw_inputs"]["price"]["source"]["source_type"] == "MANUAL_ENTRY"
    assert set(pe["reference"]) == {"own_history", "peers"}


def test_cheaper_multiple_scores_higher_and_labels():
    cheap = _val("ASR", market_entry(**{**ASR_ENTRY, "price": 40.0}), ASR_REFS)
    dear = _val("ASR", market_entry(**{**ASR_ENTRY, "price": 90.0}), ASR_REFS)
    assert cheap["valuation_score"] > dear["valuation_score"]
    assert cheap["label"] == "Attractive"
    assert dear["label"] == "Expensive"


def test_stale_price_warns_and_blocks():
    entry = market_entry(price_date="2026-09-20", **ASR_ENTRY)
    result = _val("ASR", entry, ASR_REFS)
    assert "STALE_DATA:price:13d" in result["warnings"]
    assert result["status"] == "VALUATION_DATA_CHECK"
    assert result["valuation_score"] is None
    assert result["diagnostic_valuation_score"] is not None


def test_price_change_moves_valuation_but_not_drift(tmp_path):
    root = repo_copy(tmp_path)
    drift_cfg = CFG["quality_drift"]
    write_observation(root, observation_from_baseline("ASR", drift_cfg, overrides={"solvency_ii_ratio_pct": 240}))
    write_refs(root, "ASR", ASR_REFS)

    write_market(root, {"ASR": market_entry(**ASR_ENTRY)})
    drift_before = build_drift_snapshot(root=root, as_of=AS_OF, code_version="x")
    val_before = build_valuation_snapshot(root=root, as_of=AS_OF, code_version="x")

    write_market(root, {"ASR": market_entry(**{**ASR_ENTRY, "price": 45.0})})
    drift_after = build_drift_snapshot(root=root, as_of=AS_OF, code_version="x")
    val_after = build_valuation_snapshot(root=root, as_of=AS_OF, code_version="x")

    assert drift_after == drift_before
    assert val_after["results"]["ASR"]["valuation_score"] != val_before["results"]["ASR"]["valuation_score"]
    assert val_after["reproducibility_hash"] != val_before["reproducibility_hash"]


def test_valuation_history_is_preserved(tmp_path):
    root = repo_copy(tmp_path)
    write_refs(root, "ASR", ASR_REFS)
    write_market(root, {"ASR": market_entry(**ASR_ENTRY)})
    first = write_valuation_snapshot(root, build_valuation_snapshot(root=root, as_of=AS_OF, code_version="a"))
    body = first.read_bytes()
    again = write_valuation_snapshot(root, build_valuation_snapshot(root=root, as_of=AS_OF, code_version="b"))
    assert again == first
    write_market(root, {"ASR": market_entry(**{**ASR_ENTRY, "price": 50.0})})
    second = write_valuation_snapshot(root, build_valuation_snapshot(root=root, as_of=AS_OF, code_version="c"))
    assert second.name == f"valuation_{AS_OF}_r2.json"
    assert first.read_bytes() == body
    current = json.loads((root / "data/valuation/current.json").read_text())
    assert current["current_valuation"].endswith("_r2.json")


def test_market_validator_requires_provenance():
    entry = market_entry(**ASR_ENTRY)
    del entry["price"]["source"]
    del entry["eps_ttm"]["as_of_date"]
    with pytest.raises(MarketDataError) as exc:
        validate_market_file({"schema_version": 1, "as_of": AS_OF, "tickers": {"ASR": entry, "XYZ": {}}},
                             set(REPO_CFG["portfolio"]["positions"]), "m.json")
    msg = str(exc.value)
    assert "ASR.price.source.source_type is required" in msg
    assert "ASR.eps_ttm.as_of_date is required" in msg
    assert "XYZ" in msg


def test_templates_are_valid_and_empty():
    tickers = set(REPO_CFG["portfolio"]["positions"])
    market = json.loads((ROOT / "data/templates/market.json").read_text())
    assert set(market["tickers"]) == tickers
    validate_market_file({**market, "as_of": AS_OF}, tickers, "template")
    for ticker in tickers:
        payload = json.loads((ROOT / f"data/templates/valuation_refs/{ticker}.json").read_text())
        validate_reference_file(payload, ticker, set(VAL_CFG["metrics"]), "template")
    text = (ROOT / "data/templates/market.json").read_text()
    assert '"value": null' in text and not any(c.isdigit() for c in text.replace("schema_version\": 1", ""))


def test_valuation_uses_formula_registry_without_eval():
    for name in ("valuation.py", "formulas.py"):
        tree = ast.parse((ROOT / "src/portfolio_cockpit/decision_layer" / name).read_text())
        calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert not calls & {"eval", "exec", "compile"}
        imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not any("drift" in m for m in imports)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda v: v["profiles"]["INSURER"]["weights"].update(ev_ebitda=0.1), "both weighted and NOT_APPLICABLE|sum to"),
        (lambda v: v["profiles"]["INSURER"]["weights"].update(pe=0.5), "sum to"),
        (lambda v: v["metrics"]["pe"].update(formula="eval"), "whitelisted FORMULAS"),
        (lambda v: v["metrics"]["pe"].update(requires_positive_denominator=False), "multiples must require"),
        (lambda v: v["profiles"].pop("FINANCIAL_SERVICES"), "exactly the company types"),
        (lambda v: v["reference_weights"].update(peers=0.5), "sum to 1.0"),
    ],
)
def test_valuation_config_validator_rejects(mutate, match):
    broken = deepcopy(CFG)
    mutate(broken["valuation"])
    with pytest.raises(DecisionConfigError, match=match):
        validate_decision_config(broken, REPO_CFG)
