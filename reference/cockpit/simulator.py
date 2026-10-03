"""PORTFOLIO ADJUSTMENT SIMULATION — uitsluitend paper / dry-run.

* Plaatst nooit orders; er is geen broker-interface in dit pakket.
* base_target_weight is de harde strategische basis en wordt niet gewijzigd.
* Ieder signaal wordt gelogd (signal_log) zodat later kan worden onderzocht
  of ADD_CANDIDATE / HOLD / REVIEW_REDUCE voorspellende waarde hadden.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict

from .decision import ADD_CANDIDATE, REVIEW_REDUCE, THESIS_REVIEW, DATA_CHECK
from .risk import portfolio_impact_pp


@dataclass
class SimulationRow:
    ticker: str
    decision_state: str
    current_weight: float
    base_target_weight: float
    suggested_review_direction: str
    difference: float              # base_target - current (fractie)
    portfolio_impact_now_pp: float
    portfolio_impact_at_target_pp: float
    sector: str
    sector_weight_now: float
    sector_weight_after: float
    cash_impact: float             # in valuta; negatief = kas zou dalen
    dry_run: bool = True

    def to_dict(self):
        return asdict(self)


def _direction(state: str, diff: float) -> str:
    if state == DATA_CHECK:
        return "NONE (DATA_CHECK)"
    if state == THESIS_REVIEW:
        return "REVIEW_THESIS"
    if state == REVIEW_REDUCE:
        return "REVIEW_DOWN"
    if state == ADD_CANDIDATE and diff > 0:
        return "REVIEW_UP_TO_TARGET"
    return "NONE"


def simulate(rows: list[dict], portfolio_value: float, shock: float = -0.30) -> list[SimulationRow]:
    """rows: dicts met ticker, decision_state, current_weight, base_target_weight, sector."""
    sector_now: dict[str, float] = defaultdict(float)
    for r in rows:
        sector_now[r["sector"]] += r["current_weight"]
    out = []
    for r in rows:
        diff = r["base_target_weight"] - r["current_weight"]
        direction = _direction(r["decision_state"], diff)
        # Alleen bij een review-richting rekenen we het effect van "naar basisgewicht" door.
        moved = diff if direction in ("REVIEW_UP_TO_TARGET",) else (
            min(0.0, diff) if direction == "REVIEW_DOWN" else 0.0)
        out.append(SimulationRow(
            ticker=r["ticker"], decision_state=r["decision_state"],
            current_weight=r["current_weight"], base_target_weight=r["base_target_weight"],
            suggested_review_direction=direction, difference=round(diff, 6),
            portfolio_impact_now_pp=portfolio_impact_pp(r["current_weight"], shock),
            portfolio_impact_at_target_pp=portfolio_impact_pp(r["current_weight"] + moved, shock),
            sector=r["sector"], sector_weight_now=round(sector_now[r["sector"]], 6),
            sector_weight_after=round(sector_now[r["sector"]] + moved, 6),
            cash_impact=round(-moved * portfolio_value, 2) + 0.0,
        ))
    return out


def evaluate_signals(signal_rows: list[dict], prices_later: dict[str, float]) -> dict[str, dict]:
    """Forward-rendement per decision_state. signal_rows uit repo.signal_log()."""
    agg: dict[str, list[float]] = defaultdict(list)
    for s in signal_rows:
        p0, p1 = s["price_at_signal"], prices_later.get(s["ticker"])
        if p0 and p1:
            agg[s["decision_state"]].append(p1 / p0 - 1)
    return {k: {"n": len(v), "mean_forward_return": round(sum(v) / len(v), 6)} for k, v in agg.items()}
