"""Unit tests Portfolio Cockpit v2 (sectie 9 van de specificatie + aanvullend)."""
import ast
import sqlite3
from dataclasses import fields, replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from cockpit import demo, pipeline
from cockpit.config import ConfigError, load_config, DEFAULT_CONFIG_DIR
from cockpit.confidence import DataPoint, compute_confidence
from cockpit.decision import (DecisionInputs, DecisionResult, decide, ADD_CANDIDATE, HOLD, NO_ADD,
                              REVIEW_REDUCE, THESIS_REVIEW, DATA_CHECK)
from cockpit.quality import Observation, compute_quality, normalize
from cockpit.repository import BaselineImmutableError
from cockpit.risk import Position, portfolio_impact_pp, run_scenario, PORTFOLIO_IMPACT_LABEL
from cockpit.simulator import simulate, evaluate_signals
from cockpit.valuation import compute_valuation, NOT_APPLICABLE

PKG = Path(__file__).resolve().parent.parent / "cockpit"


def _obs_from(values: dict, d=date(2026, 1, 1)):
    return {k: Observation(k, v, "test", d) for k, v in values.items()}


# ---------------------------------------------------------------- QUALITY
@pytest.mark.parametrize("ticker", list(demo.BASELINE))
def test_baseline_is_exact_50(cfg, ticker):
    ctype = next(s[2] for s in demo.SECURITIES if s[0] == ticker)
    base = demo.BASELINE[ticker]
    q = compute_quality(cfg.quality[ctype], base, _obs_from(base))
    assert q.quality_score == 50.0
    assert q.quality_change_since_baseline == 0.0
    assert all(c.normalized_signal == 0.0 for c in q.contributions)


def test_baseline_is_exact_50_in_pipeline(cfg, seeded):
    res = pipeline.run(seeded, cfg, demo.D0)
    assert all(r["quality_score"] == 50.0 for r in res.rows)


def test_quality_formula_and_clamp(cfg):
    prof = cfg.quality["GENERAL_OPERATING_COMPANY"]
    base = demo.BASELINE["DEMO-OPCO"]
    huge = {k: v + 1000 if prof.metrics[k].direction == "higher_better" else v - 1000 for k, v in base.items()}
    assert compute_quality(prof, base, _obs_from(huge)).quality_score == 100.0
    awful = {k: v - 1000 if prof.metrics[k].direction == "higher_better" else v + 1000 for k, v in base.items()}
    assert compute_quality(prof, base, _obs_from(awful)).quality_score == 0.0


def test_normalized_signal_bounds_and_direction(cfg):
    spec = cfg.quality["GENERAL_OPERATING_COMPANY"].metrics["net_debt_to_ebitda"]
    _, s_up = normalize(1.8, 3.3, spec)     # meer schuld = slechter
    _, s_down = normalize(1.8, 1.2, spec)
    assert -1 <= s_up < 0 < s_down <= 1
    _, s_noise = normalize(1.8, 1.85, spec)  # binnen dead band
    assert s_noise == 0.0


def test_price_move_alone_changes_valuation_but_not_quality(cfg, seeded):
    r0 = {r["ticker"]: r for r in pipeline.run(seeded, cfg, demo.D0).rows}
    d1 = demo.D0 + timedelta(days=1)
    seeded.add_datapoint(DataPoint("DEMO-OPCO", "price", 130.0, "test", "SAMPLE", None, d1,
                                   datetime(2026, 4, 2, 18), "EUR", None, None, "MARKET"))
    r1 = {r["ticker"]: r for r in pipeline.run(seeded, cfg, d1).rows}
    assert r1["DEMO-OPCO"]["quality_score"] == r0["DEMO-OPCO"]["quality_score"] == 50.0
    assert r1["DEMO-OPCO"]["valuation_score"] < r0["DEMO-OPCO"]["valuation_score"]


def test_quality_module_has_no_price_input():
    src = (PKG / "quality.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "compute_quality":
            assert [a.arg for a in node.args.args] == ["profile", "baseline", "observations"]


def test_config_rejects_price_dependent_quality_metric(tmp_path):
    for f in DEFAULT_CONFIG_DIR.glob("*.yaml"):
        (tmp_path / f.name).write_text(f.read_text())
    raw = yaml.safe_load((tmp_path / "quality_profiles.yaml").read_text())
    raw["profiles"]["GENERAL_OPERATING_COMPANY"]["categories"]["growth"]["metrics"]["pe"] = \
        raw["profiles"]["GENERAL_OPERATING_COMPANY"]["categories"]["growth"]["metrics"].pop("revenue_growth_3y")
    (tmp_path / "quality_profiles.yaml").write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="prijsafhankelijk"):
        load_config(tmp_path)


def test_thresholds_live_in_config_not_code():
    for name in ("quality.py", "valuation.py", "decision.py", "confidence.py"):
        # Geen losse drempelwaarden als vergelijkingsliteral in de modules
        tree = ast.parse((PKG / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for c in [node.left, *node.comparators]:
                    if isinstance(c, ast.Constant) and isinstance(c.value, (int, float)):
                        assert c.value in (0, 1, 2), f"hardcoded drempel {c.value} in {name}"


# ---------------------------------------------------------------- VALUATION
def test_insurer_does_not_use_ev_ebitda_or_fcf(cfg):
    inputs = {"price": 40, "shares_outstanding": 200, "bvps": 30, "eps_ttm": 4.4, "distributions": 700,
              "ebitda": 1500, "fcf": 900, "net_debt": 100, "ebit": 1200}
    refs = {"ev_ebitda": {"own_history": 1, "peers": 1}, "fcf_yield": {"own_history": 0.01, "peers": 0.01},
            "price_to_book": {"own_history": 1.2, "peers": 1.3}, "pe": {"own_history": 9.5, "peers": 10},
            "shareholder_yield": {"own_history": 0.07, "peers": 0.065}}
    v = compute_valuation("INSURER", inputs, refs, cfg.valuation)
    by = {m.metric_name: m for m in v.metrics}
    for bad in ("ev_ebitda", "ev_ebit", "fcf_yield"):
        assert by[bad].status == NOT_APPLICABLE and by[bad].value is None and by[bad].score is None
    # en ook niet in quality
    q_metrics = set(cfg.quality["INSURER"].metrics)
    assert not q_metrics & {"fcf_to_net_income", "net_debt_to_ebitda", "fcf_yield", "ev_ebitda"}
    # score volledig gedragen door verzekeraar-metrics
    assert v.applicable_weight == pytest.approx(1.0)


def test_pre_revenue_gets_no_pe_interpretation(cfg):
    inputs = {"price": 5, "shares_outstanding": 100, "navps": 10, "risked_npv": 800, "eps_ttm": -0.3,
              "forward_eps": 0.01, "net_debt": -50, "ebitda": -20}
    refs = {"pe": {"own_history": 20, "peers": 20}, "forward_pe": {"own_history": 20, "peers": 20},
            "price_to_nav": {"own_history": 0.5, "peers": 0.55},
            "market_cap_to_funded_npv": {"own_history": 0.6, "peers": 0.6}}
    v = compute_valuation("DEVELOPMENT_PRE_REVENUE", inputs, refs, cfg.valuation)
    by = {m.metric_name: m for m in v.metrics}
    for bad in ("pe", "forward_pe", "ev_ebitda"):
        assert by[bad].status == NOT_APPLICABLE and by[bad].score is None
    assert "pe" not in cfg.quality["DEVELOPMENT_PRE_REVENUE"].metrics


def test_negative_pe_is_never_cheap(cfg):
    inputs = {"price": 40, "shares_outstanding": 200, "bvps": 30, "eps_ttm": -2.0, "distributions": 700}
    refs = {"pe": {"own_history": 9.5, "peers": 10}, "price_to_book": {"own_history": 1.2, "peers": 1.3},
            "shareholder_yield": {"own_history": 0.07, "peers": 0.065}}
    v = compute_valuation("INSURER", inputs, refs, cfg.valuation)
    pe = next(m for m in v.metrics if m.metric_name == "pe")
    assert pe.status == NOT_APPLICABLE and pe.score is None
    assert any(w.startswith("UNSUITABLE_METRIC:pe") for w in v.warnings)


def test_negative_ev_ebitda_is_never_cheap(cfg):
    inputs = {"price": 30, "shares_outstanding": 300, "net_debt": 1500, "navps": 32,
              "normalized_ebitda": -100, "fcf": 700}
    refs = {"ev_normalized_ebitda": {"own_history": 5.5, "peers": 6}}
    v = compute_valuation("CYCLICAL_MINING", inputs, refs, cfg.valuation)
    m = next(m for m in v.metrics if m.metric_name == "ev_normalized_ebitda")
    assert m.status == NOT_APPLICABLE and m.score is None


def test_valuation_metric_has_provenance(cfg, seeded):
    res = pipeline.run(seeded, cfg, demo.D0)
    vm = res.rows[0]["explanation"]["valuation"][0]
    for k in ("source", "as_of_date", "calculation_method", "raw_inputs"):
        assert k in vm


# ---------------------------------------------------------------- DATA CONFIDENCE
def test_missing_data_produces_data_check(cfg, repo):
    repo.add_security("X", "Leeg NV", "GENERAL_OPERATING_COMPANY", "Industrials", 0.05)
    repo.set_position("X", 0.04)
    base = demo.BASELINE["DEMO-OPCO"]
    repo.create_baseline("X", demo.D0, [{"metric_name": m, "baseline_value": v, "source": "t",
                                         "source_date": demo.D0} for m, v in base.items()])
    # alleen koers, geen fundamentele datapunten
    repo.add_datapoint(DataPoint("X", "price", 10, "t", "SAMPLE", None, demo.D0, datetime(2026, 4, 1),
                                 "EUR", None, None, "MARKET"))
    row = pipeline.run(repo, cfg, demo.D0).rows[0]
    assert row["data_confidence"] < cfg.decision["data_confidence_min"]
    assert row["decision_state"] == DATA_CHECK
    assert row["valuation_label"] is None  # geen waarderingsconclusie
    assert any(w.startswith("MISSING_DATA") for w in row["warnings"])


def test_stale_data_produces_warning(cfg, seeded):
    pipeline.run(seeded, cfg, demo.D0)
    demo.seed_later(seeded)
    rows = {r["ticker"]: r for r in pipeline.run(seeded, cfg, demo.D1).rows}
    assert any(w.startswith("STALE_DATA") for w in rows["DEMO-MIN"]["warnings"])
    assert not any(w.startswith("STALE_DATA") for w in rows["DEMO-OPCO"]["warnings"])


def test_source_conflict_warning(cfg):
    d = date(2026, 9, 1)
    dps = [DataPoint("X", "solvency_ratio", 190, "SFCR", "FILING", "f1", d, datetime(2026, 9, 1), None, "2026H1", None),
           DataPoint("X", "solvency_ratio", 170, "Nieuws", "NEWS", None, d, datetime(2026, 9, 1), None, "2026H1", None)]
    c = compute_confidence(dps, d, 1.0, 1.0, cfg.confidence)
    assert any(w.startswith("SOURCE_CONFLICT") for w in c.warnings)
    assert c.data_confidence < cfg.decision["data_confidence_min"]


def test_calculation_anomaly_warning(cfg):
    dps = [DataPoint("X", "shares_outstanding", 100, "a", "FILING", None, date(2026, 1, 1), datetime(2026, 1, 1), None, None, None),
           DataPoint("X", "shares_outstanding", 1000, "a", "FILING", None, date(2026, 6, 1), datetime(2026, 6, 1), None, None, None)]
    c = compute_confidence(dps, date(2026, 6, 2), 1.0, 1.0, cfg.confidence)
    assert any(w.startswith("CALCULATION_ANOMALY") for w in c.warnings)


# ---------------------------------------------------------------- PORTFOLIO RISK
def test_portfolio_impact_calculation():
    assert portfolio_impact_pp(0.07, -0.30) == pytest.approx(-2.1)
    assert portfolio_impact_pp(0.0, -0.30) == 0.0
    assert PORTFOLIO_IMPACT_LABEL == "PORTFOLIO IMPACT -30%"


def test_scenarios(cfg):
    pos = [Position("A", 0.10, "Financials", 1.0), Position("B", 0.05, "Materials", 2.0)]
    assert run_scenario(pos, cfg.risk["scenarios"]["sector_shock"])["total_pp"] == pytest.approx(-3.0)
    assert run_scenario(pos, cfg.risk["scenarios"]["market_shock"])["total_pp"] == pytest.approx(-2.0 - 2.0)
    comb = run_scenario(pos, cfg.risk["scenarios"]["combined_scenario"])
    assert comb["per_ticker_pp"]["B"] == pytest.approx(0.05 * -0.15 * 2 * 100 + 0.05 * -0.20 * 100)


# ---------------------------------------------------------------- DECISION ENGINE
BASE_IN = DecisionInputs("T", 60, 2, 65, 95, "INTACT", 0.05, 0.08, 0.15, -1.5)


@pytest.mark.parametrize("change,expected", [
    (dict(), ADD_CANDIDATE),
    (dict(data_confidence=79.9), DATA_CHECK),
    (dict(thesis_status="BROKEN"), THESIS_REVIEW),
    (dict(quality_score=38), REVIEW_REDUCE),
    (dict(quality_change=-12), REVIEW_REDUCE),
    (dict(valuation_score=40), NO_ADD),
    (dict(valuation_score=52), HOLD),
    (dict(valuation_score=None), HOLD),
])
def test_decision_states(cfg, change, expected):
    assert decide(replace(BASE_IN, **change), cfg.decision).decision_state == expected


def test_data_check_precedes_everything(cfg):
    r = decide(replace(BASE_IN, data_confidence=50, thesis_status="BROKEN", quality_score=10), cfg.decision)
    assert r.decision_state == DATA_CHECK


@pytest.mark.parametrize("change,flag", [
    (dict(portfolio_weight=0.11, base_target_weight=0.12), "POSITION_LIMIT"),
    (dict(portfolio_weight=0.08, base_target_weight=0.06), "ABOVE_TARGET_BAND"),
    (dict(sector_weight=0.31), "SECTOR_LIMIT"),
    (dict(portfolio_impact_pp=-3.3), "IMPACT_LIMIT"),
])
def test_sector_and_position_limits_respected(cfg, change, flag):
    r = decide(replace(BASE_IN, **change), cfg.decision)
    assert r.decision_state != ADD_CANDIDATE
    assert any(f.startswith(flag) for f in r.limit_flags)


def test_decision_engine_never_places_an_order(cfg, seeded):
    names = {f.name for f in fields(DecisionResult)}
    assert not names & {"order", "quantity", "side", "limit_price", "order_id"}
    for mod in PKG.glob("*.py"):
        tree = ast.parse(mod.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                assert not any(w in node.name.lower() for w in ("place_order", "submit_order", "execute_trade", "broker"))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] + ([node.module] if getattr(node, "module", None) else [])
                assert not any(m and any(b in m.lower() for b in ("ib_insync", "ibapi", "alpaca", "ccxt", "requests")) for m in mods)
    pipeline.run(seeded, cfg, demo.D0)
    assert all(s["dry_run"] == 1 for s in seeded.signal_log())
    with pytest.raises(sqlite3.IntegrityError):
        seeded.conn.execute("INSERT INTO signal_log (run_id, sim_date, ticker, decision_state, current_weight,"
                            " base_target_weight, suggested_review_direction, difference, portfolio_impact_now_pp,"
                            " portfolio_impact_at_target_pp, sector_weight_now, sector_weight_after, cash_impact, dry_run)"
                            " VALUES ('x','2026-01-01','T','HOLD',0,0,'NONE',0,0,0,0,0,0,0)")


def test_base_target_weight_never_changed(cfg, seeded):
    before = {s["ticker"]: s["base_target_weight"] for s in seeded.securities()}
    pipeline.run(seeded, cfg, demo.D0)
    demo.seed_later(seeded)
    pipeline.run(seeded, cfg, demo.D1)
    after = {s["ticker"]: s["base_target_weight"] for s in seeded.securities()}
    assert before == after


# ---------------------------------------------------------------- BASELINE & HISTORY
def test_baseline_snapshot_cannot_be_overwritten(seeded):
    with pytest.raises(BaselineImmutableError):
        seeded.create_baseline("DEMO-OPCO", date(2026, 9, 1),
                               [{"metric_name": "roic", "baseline_value": 99, "source": "x", "source_date": date(2026, 9, 1)}])
    with pytest.raises(sqlite3.IntegrityError):
        seeded.conn.execute("UPDATE baseline_snapshot SET baseline_value=99 WHERE ticker='DEMO-OPCO'")
    with pytest.raises(sqlite3.IntegrityError):
        seeded.conn.execute("DELETE FROM baseline_snapshot WHERE ticker='DEMO-OPCO'")
    with pytest.raises(sqlite3.IntegrityError):  # UNIQUE (ticker, metric_name)
        seeded.conn.execute("INSERT INTO baseline_snapshot (ticker, company_name, company_type, baseline_date,"
                            " metric_name, baseline_value, source, source_date)"
                            " VALUES ('DEMO-OPCO','x','x','2026-09-01','roic',99,'x','2026-09-01')")
    assert seeded.baseline("DEMO-OPCO")["roic"]["baseline_value"] == 18


def test_historical_scores_are_retained(cfg, seeded):
    pipeline.run(seeded, cfg, demo.D0)
    demo.seed_later(seeded)
    pipeline.run(seeded, cfg, demo.D1)
    h = seeded.score_history("DEMO-OPCO")
    assert [x["score_date"] for x in h] == [str(demo.D0), str(demo.D1)]
    assert h[0]["quality_score"] == 50.0 and h[1]["quality_score"] > 50.0
    assert h[1]["explanation"]["quality"][0]["source"] is not None
    for stmt in ("UPDATE score_history SET quality_score=0", "DELETE FROM score_history",
                 "UPDATE quality_observations SET normalized_signal=0", "DELETE FROM datapoints"):
        with pytest.raises(sqlite3.IntegrityError):
            seeded.conn.execute(stmt)
    assert len(seeded.score_history()) == 8


def test_explanation_shows_old_vs_new_and_source(cfg, seeded):
    pipeline.run(seeded, cfg, demo.D0)
    demo.seed_later(seeded)
    row = {r["ticker"]: r for r in pipeline.run(seeded, cfg, demo.D1).rows}["DEMO-INS"]
    cr = next(c for c in row["explanation"]["quality"] if c["metric_name"] == "combined_ratio")
    assert cr["baseline_value"] == 94 and cr["previous_value"] == 94 and cr["raw_value"] == 99
    assert cr["contribution_points"] < 0 and cr["source"] and cr["source_date"] == str(demo.D1)


# ---------------------------------------------------------------- SIMULATOR
def test_simulator_is_dry_run_and_respects_base_target():
    rows = [{"ticker": "A", "decision_state": ADD_CANDIDATE, "current_weight": 0.05, "base_target_weight": 0.08, "sector": "S"},
            {"ticker": "B", "decision_state": REVIEW_REDUCE, "current_weight": 0.10, "base_target_weight": 0.08, "sector": "S"},
            {"ticker": "C", "decision_state": DATA_CHECK, "current_weight": 0.02, "base_target_weight": 0.05, "sector": "T"}]
    out = {r.ticker: r for r in simulate(rows, 100_000)}
    assert all(r.dry_run for r in out.values())
    assert out["A"].suggested_review_direction == "REVIEW_UP_TO_TARGET"
    assert out["A"].cash_impact == pytest.approx(-3000)
    assert out["A"].portfolio_impact_at_target_pp == pytest.approx(-2.4)
    assert out["B"].suggested_review_direction == "REVIEW_DOWN" and out["B"].cash_impact == pytest.approx(2000)
    assert out["C"].suggested_review_direction.startswith("NONE") and out["C"].cash_impact == 0
    assert out["A"].sector_weight_now == pytest.approx(0.15)


def test_signal_evaluation():
    sig = [{"ticker": "A", "decision_state": ADD_CANDIDATE, "price_at_signal": 100},
           {"ticker": "B", "decision_state": HOLD, "price_at_signal": 50}]
    res = evaluate_signals(sig, {"A": 110, "B": 45})
    assert res[ADD_CANDIDATE]["mean_forward_return"] == pytest.approx(0.10)
    assert res[HOLD]["mean_forward_return"] == pytest.approx(-0.10)


# ---------------------------------------------------------------- DASHBOARD
def test_dashboard_renders_without_percentile(cfg, seeded):
    from cockpit.dashboard import render
    res = pipeline.run(seeded, cfg, demo.D0)
    html = render(seeded, res.scenarios)
    assert "PORTFOLIO IMPACT -30%" in html and "STRESS -30%" not in html
    assert "percentiel" not in html.lower() and "percentile" not in html.lower()
