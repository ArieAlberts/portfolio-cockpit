"""Orkestratie: draait de vijf modules strikt gescheiden en schrijft de audit trail.

QUALITY ontvangt alleen fundamentele datapunten (kind FUNDAMENTAL/ASSESSMENT).
VALUATION ontvangt marktdata + fundamentele inputs.
DATA CONFIDENCE beoordeelt de provenance.
PORTFOLIO RISK rekent alleen met gewichten/sectoren/beta.
DECISION ENGINE combineert de uitkomsten tot een decision_state — nooit een order.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from .config import Config
from .confidence import DataPoint, compute_confidence, UNSUITABLE_METRIC
from .decision import DecisionInputs, decide, DATA_CHECK
from .quality import Observation, compute_quality
from .repository import Repository
from .risk import Position, portfolio_impact_pp, sector_weights, run_all_scenarios
from .simulator import simulate
from .valuation import compute_valuation

FUNDAMENTAL_KINDS = ("FUNDAMENTAL", "ASSESSMENT")


@dataclass
class RunResult:
    run_id: str
    as_of: date
    rows: list[dict]
    scenarios: dict
    simulation: list


def _latest(dps: list[DataPoint], kinds: tuple[str, ...] | None, sq: dict) -> dict[str, DataPoint]:
    """Laatste datapunt per metric; bij gelijke datum wint de hoogste bronkwaliteit."""
    out: dict[str, DataPoint] = {}
    for dp in dps:
        if kinds and dp.kind not in kinds:
            continue
        cur = out.get(dp.metric_name)
        key = (dp.as_of_date, sq.get(dp.source_type, 0))
        if cur is None or key >= (cur.as_of_date, sq.get(cur.source_type, 0)):
            out[dp.metric_name] = dp
    return out


def run(repo: Repository, cfg: Config, as_of: date, portfolio_value: float = 100_000.0) -> RunResult:
    run_id = f"{as_of.isoformat()}-{uuid.uuid4().hex[:8]}"
    sq = cfg.confidence["source_quality"]
    secs = repo.securities()
    positions = [Position(s["ticker"], s["weight"], s["sector"], s["beta"]) for s in secs]
    sec_w = sector_weights(positions)
    shock = cfg.risk["standard_shock"]
    rows = []

    for s in secs:
        t, ctype = s["ticker"], s["company_type"]
        profile = cfg.quality[ctype]
        dps = repo.datapoints(t, as_of)

        # ---- 1. QUALITY (alleen fundamentele data) ----
        baseline_rows = repo.baseline(t)
        baseline = {k: r["baseline_value"] for k, r in baseline_rows.items()}
        fund = _latest(dps, FUNDAMENTAL_KINDS, sq)
        obs = {k: Observation(k, dp.raw_value, dp.source, dp.as_of_date) for k, dp in fund.items()
               if k in profile.metrics}
        q = compute_quality(profile, baseline, obs)
        prev_obs = repo.last_signal_by_metric(t, as_of)
        extra_warn = [f"{UNSUITABLE_METRIC}:quality:{m}" for m in fund if m in profile.excluded_metrics]

        # ---- 2. VALUATION (los van quality) ----
        all_latest = _latest(dps, None, sq)
        inputs = {k: dp.raw_value for k, dp in all_latest.items()}
        market = {k: dp for k, dp in all_latest.items() if dp.kind == "MARKET"}
        price_dp = market.get("price")
        v = compute_valuation(ctype, inputs, repo.references(t, as_of), cfg.valuation,
                              source=price_dp.source if price_dp else None,
                              as_of=str(price_dp.as_of_date) if price_dp else None)

        # ---- 3. DATA CONFIDENCE ----
        c = compute_confidence(dps, as_of, q.coverage, v.applicable_weight, cfg.confidence,
                               extra_warnings=extra_warn + v.warnings)

        # ---- 4. PORTFOLIO RISK ----
        impact = portfolio_impact_pp(s["weight"], shock)

        # ---- 5. DECISION ----
        prev = repo.last_score(t, as_of)
        recent = round(q.quality_score - prev["quality_score"], 2) if prev else None
        d = decide(DecisionInputs(t, q.quality_score, recent, v.valuation_score, c.data_confidence,
                                  s["thesis_status"], s["weight"], s["base_target_weight"],
                                  sec_w.get(s["sector"], 0.0), impact), cfg.decision)

        # ---- audit trail ----
        explanation = {
            "quality": [
                {**cb.to_dict(),
                 "previous_value": prev_obs.get(cb.metric_name, {}).get("raw_value"),
                 "previous_date": prev_obs.get(cb.metric_name, {}).get("observation_date"),
                 "baseline_source": baseline_rows[cb.metric_name]["source"] if cb.metric_name in baseline_rows else None,
                 "baseline_date": baseline_rows[cb.metric_name]["baseline_date"] if cb.metric_name in baseline_rows else None}
                for cb in q.contributions],
            "quality_coverage": q.coverage,
            "valuation": [m.to_dict() for m in v.metrics],
            "confidence_components": c.components,
            "limit_flags": d.limit_flags,
        }
        fund_dates = [dp.as_of_date for dp in fund.values()]
        row = {
            "run_id": run_id, "score_date": str(as_of), "ticker": t,
            "price": price_dp.raw_value if price_dp else None,
            "quality_score": q.quality_score,
            "quality_change_since_baseline": q.quality_change_since_baseline,
            "quality_change_recent": recent,
            "valuation_score": v.valuation_score,
            # Bij DATA_CHECK geen waarderingsconclusie (score blijft voor audit bewaard)
            "valuation_label": None if d.decision_state == DATA_CHECK else v.label,
            "data_confidence": c.data_confidence,
            "warnings": c.warnings,
            "thesis_status": s["thesis_status"],
            "decision_state": d.decision_state,
            "decision_reasons": d.reasons,
            "portfolio_weight": s["weight"],
            "base_target_weight": s["base_target_weight"],
            "sector_weight": round(sec_w.get(s["sector"], 0.0), 6),
            "portfolio_impact_pp": impact,
            "last_fundamental_update": str(max(fund_dates)) if fund_dates else None,
            "last_valuation_update": str(price_dp.as_of_date) if price_dp else None,
            "explanation": explanation,
        }
        repo.insert_quality_observations(run_id, t, as_of, q.contributions)
        repo.insert_valuation_metrics(run_id, t, as_of, v.metrics)
        repo.insert_score_history(row)
        rows.append({**row, "company_name": s["company_name"], "company_type": ctype, "sector": s["sector"]})

    # ---- 8. SIMULATIE (dry-run) + signal log ----
    sim = simulate([{"ticker": r["ticker"], "decision_state": r["decision_state"],
                     "current_weight": r["portfolio_weight"], "base_target_weight": r["base_target_weight"],
                     "sector": r["sector"]} for r in rows], portfolio_value, shock)
    prices = {r["ticker"]: r["price"] for r in rows}
    for srow in sim:
        repo.insert_signal(run_id, as_of, prices.get(srow.ticker), srow)

    scenarios = run_all_scenarios(positions, cfg.risk) if positions else {}
    return RunResult(run_id, as_of, rows, scenarios, sim)
