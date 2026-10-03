"""PORTFOLIO RISK-module — gescheiden van quality_score en valuation_score.

De oude kolom "STRESS -30%" heet voortaan "PORTFOLIO IMPACT -30%":
    portfolio_impact = position_weight * -30%
    bv. 7% * -30% = -2.1 procentpunt
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

PORTFOLIO_IMPACT_LABEL = "PORTFOLIO IMPACT -30%"


@dataclass(frozen=True)
class Position:
    ticker: str
    weight: float          # fractie van totale portefeuille (0.07 = 7%)
    sector: str
    beta: float | None = None


def portfolio_impact_pp(position_weight: float, shock: float = -0.30) -> float:
    """Impact op de totale portefeuille in procentpunt."""
    return round(position_weight * shock * 100, 4)


def sector_weights(positions: list[Position]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for p in positions:
        out[p.sector] += p.weight
    return dict(out)


def _component_impact(positions: list[Position], comp: dict) -> dict[str, float]:
    t = comp["type"]
    res: dict[str, float] = {}
    if t == "market":
        for p in positions:
            beta = p.beta if (comp.get("use_beta") and p.beta is not None) else 1.0
            res[p.ticker] = portfolio_impact_pp(p.weight, comp["shock"] * beta)
    elif t == "sector":
        for p in positions:
            if p.sector == comp["sector"]:
                res[p.ticker] = portfolio_impact_pp(p.weight, comp["shock"])
    elif t == "single_stock":
        target = comp.get("target", "largest")
        if target == "largest":
            p = max(positions, key=lambda x: x.weight)
        else:
            p = next(x for x in positions if x.ticker == target)
        res[p.ticker] = portfolio_impact_pp(p.weight, comp["shock"])
    else:
        raise ValueError(f"onbekend scenario-type {t}")
    return res


def run_scenario(positions: list[Position], scenario: dict) -> dict:
    comps = scenario["components"] if scenario["type"] == "combined" else [scenario]
    per_ticker: dict[str, float] = defaultdict(float)
    for c in comps:
        for t, v in _component_impact(positions, c).items():
            per_ticker[t] += v
    return {
        "description": scenario.get("description", ""),
        "per_ticker_pp": {k: round(v, 4) for k, v in per_ticker.items()},
        "total_pp": round(sum(per_ticker.values()), 4),
    }


def run_all_scenarios(positions: list[Position], risk_cfg: dict) -> dict[str, dict]:
    return {name: run_scenario(positions, sc) for name, sc in risk_cfg["scenarios"].items()}
