"""Portfolio Risk — weights x shocks only. Analytical, never execution.

PORTFOLIO IMPACT -30%: impact_pp = weight x -0.30 x 100
(e.g. 7% x -30% = -2.1 percentage points of the total portfolio).

Current weights, sector and beta come from config/positions.yaml (owner
input). Target weights come from config/portfolio.yaml and are only read.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from portfolio_cockpit.scoring.portfolio_risk import portfolio_impact

from .config import missing_owner_inputs


class PositionsIncompleteError(ValueError):
    """Raised when config/positions.yaml is still (partly) an empty template."""


@dataclass(frozen=True)
class Position:
    ticker: str
    weight_pct: float
    sector: str
    beta: float | None = None


def impact_pp(weight_pct: float, shock: float) -> float:
    """Impact on the total portfolio in percentage points."""
    return round(portfolio_impact(weight_pct / 100.0, shock) * 100.0, 6) + 0.0  # no -0.0


def load_positions(cfg: dict[str, dict[str, Any]]) -> tuple[list[Position], float]:
    missing = missing_owner_inputs(cfg)["positions"]
    if missing:
        raise PositionsIncompleteError(
            "config/positions.yaml is incomplete; fill in: " + ", ".join(missing)
        )
    positions_cfg = cfg["positions"]
    positions = [
        Position(
            ticker=ticker,
            weight_pct=float(item["weight_pct"]),
            sector=str(item["sector"]),
            beta=float(item["beta"]) if item.get("beta") is not None else None,
        )
        for ticker, item in positions_cfg["positions"].items()
    ]
    return positions, float(positions_cfg["cash_weight_pct"])


def sector_weights(positions: list[Position]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for p in positions:
        out[p.sector] += p.weight_pct
    return {k: round(v, 6) for k, v in sorted(out.items())}


def _component_impact(positions: list[Position], component: dict[str, Any]) -> dict[str, float]:
    kind = component["type"]
    shock = float(component["shock"])
    if kind == "market":
        return {
            p.ticker: impact_pp(
                p.weight_pct, shock * (p.beta if component.get("use_beta") and p.beta is not None else 1.0)
            )
            for p in positions
        }
    if kind == "sector":
        return {p.ticker: impact_pp(p.weight_pct, shock) for p in positions if p.sector == component["sector"]}
    if kind == "single_stock":
        target = component.get("target", "largest")
        if target == "largest":
            chosen = max(positions, key=lambda p: (p.weight_pct, p.ticker))
        else:
            chosen = next(p for p in positions if p.ticker == target)
        return {chosen.ticker: impact_pp(chosen.weight_pct, shock)}
    raise ValueError(f"unknown scenario type {kind}")


def run_scenario(positions: list[Position], scenario: dict[str, Any]) -> dict[str, Any]:
    components = scenario["components"] if scenario["type"] == "combined" else [scenario]
    per_ticker: dict[str, float] = defaultdict(float)
    for component in components:
        for ticker, value in _component_impact(positions, component).items():
            per_ticker[ticker] += value
    return {
        "description": scenario.get("description", ""),
        "type": scenario["type"],
        "per_ticker_pp": {k: round(v, 6) for k, v in sorted(per_ticker.items())},
        "total_pp": round(sum(per_ticker.values()), 6),
    }


def build_risk_report(cfg: dict[str, dict[str, Any]], target_weights: dict[str, float]) -> dict[str, Any]:
    risk_cfg = cfg["risk_scenarios"]
    positions, cash = load_positions(cfg)
    shock = float(risk_cfg["standard_shock"])
    sectors = sector_weights(positions)
    per_ticker = {
        p.ticker: {
            "portfolio_weight_pct": p.weight_pct,
            "base_target_weight_pct": float(target_weights[p.ticker]),
            "sector": p.sector,
            "sector_weight_pct": sectors[p.sector],
            "beta": p.beta,
            "portfolio_impact_pp": impact_pp(p.weight_pct, shock),
        }
        for p in positions
    }
    return {
        "label": risk_cfg["standard_label"],
        "standard_shock": shock,
        "as_of": str(cfg["positions"]["as_of"]),
        "cash_weight_pct": cash,
        "invested_weight_pct": round(sum(p.weight_pct for p in positions), 6),
        "sector_weights_pct": sectors,
        "positions": per_ticker,
        "scenarios": {
            name: run_scenario(positions, scenario) for name, scenario in risk_cfg["scenarios"].items()
        },
        "execution_effect": "NONE",
    }
