"""DECISION ENGINE.

Produceert UITSLUITEND een decision_state met redenen. Deze module bevat geen
broker-koppeling, geen ordertypes en geen functie die een order kan plaatsen.
base_target_weight wordt alleen gelezen, nooit gewijzigd.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

ADD_CANDIDATE = "ADD_CANDIDATE"
HOLD = "HOLD"
NO_ADD = "NO_ADD"
REVIEW_REDUCE = "REVIEW_REDUCE"
THESIS_REVIEW = "THESIS_REVIEW"
DATA_CHECK = "DATA_CHECK"
DECISION_STATES = (ADD_CANDIDATE, HOLD, NO_ADD, REVIEW_REDUCE, THESIS_REVIEW, DATA_CHECK)


@dataclass(frozen=True)
class DecisionInputs:
    ticker: str
    quality_score: float
    quality_change: Optional[float]   # recente verandering t.o.v. vorige meting (punten)
    valuation_score: Optional[float]
    data_confidence: float
    thesis_status: str                # INTACT | WATCH | BROKEN
    portfolio_weight: float
    base_target_weight: float
    sector_weight: float
    portfolio_impact_pp: float        # PORTFOLIO IMPACT -30%


@dataclass
class DecisionResult:
    ticker: str
    decision_state: str
    reasons: list[str] = field(default_factory=list)
    limit_flags: list[str] = field(default_factory=list)
    # Bewust geen velden als 'order', 'quantity', 'side' of 'limit_price'.


def _limit_flags(i: DecisionInputs, lim: dict) -> list[str]:
    flags = []
    if i.portfolio_weight >= lim["max_position_weight"]:
        flags.append(f"POSITION_LIMIT: {i.portfolio_weight:.1%} >= max {lim['max_position_weight']:.1%}")
    if i.portfolio_weight >= i.base_target_weight * (1 + lim["overweight_tolerance"]):
        flags.append(f"ABOVE_TARGET_BAND: {i.portfolio_weight:.1%} vs basis {i.base_target_weight:.1%}")
    if i.sector_weight >= lim["max_sector_weight"]:
        flags.append(f"SECTOR_LIMIT: {i.sector_weight:.1%} >= max {lim['max_sector_weight']:.1%}")
    if abs(i.portfolio_impact_pp) > lim["max_single_position_impact_pp"]:
        flags.append(f"IMPACT_LIMIT: {i.portfolio_impact_pp:.2f}pp > {lim['max_single_position_impact_pp']}pp")
    return flags


def decide(i: DecisionInputs, cfg: dict) -> DecisionResult:
    q, v, lim = cfg["quality"], cfg["valuation"], cfg["limits"]
    if i.thesis_status not in cfg["thesis_status_values"]:
        return DecisionResult(i.ticker, DATA_CHECK, [f"onbekende thesis_status '{i.thesis_status}'"])

    if i.data_confidence < cfg["data_confidence_min"]:
        return DecisionResult(i.ticker, DATA_CHECK,
                              [f"data_confidence {i.data_confidence:.0f} < {cfg['data_confidence_min']}: "
                               "geen waarderings- of portefeuilleconclusie"])

    if i.thesis_status == "BROKEN":
        return DecisionResult(i.ticker, THESIS_REVIEW, ["thesis_status = BROKEN"])

    deteriorated_reasons = []
    if i.quality_score <= q["materially_deteriorated_score"]:
        deteriorated_reasons.append(f"quality {i.quality_score:.0f} <= {q['materially_deteriorated_score']}")
    if i.quality_change is not None and i.quality_change <= q["materially_deteriorated_change"]:
        deteriorated_reasons.append(f"quality-verandering {i.quality_change:+.0f} <= {q['materially_deteriorated_change']}")
    if deteriorated_reasons:
        return DecisionResult(i.ticker, REVIEW_REDUCE, deteriorated_reasons)

    flags = _limit_flags(i, lim)
    if v is not None and i.valuation_score is not None:
        if i.quality_score >= q["strong_score"] and i.valuation_score >= v["attractive_score"]:
            reasons = [f"quality {i.quality_score:.0f} sterk", f"valuation {i.valuation_score:.0f} aantrekkelijk"]
            if flags:
                return DecisionResult(i.ticker, HOLD, reasons + ["ADD geblokkeerd door limiet"], flags)
            return DecisionResult(i.ticker, ADD_CANDIDATE, reasons, flags)
        if i.quality_score >= q["acceptable_score"] and i.valuation_score < v["expensive_score"]:
            return DecisionResult(i.ticker, NO_ADD,
                                  [f"quality {i.quality_score:.0f} acceptabel",
                                   f"valuation {i.valuation_score:.0f} duur"], flags)
    return DecisionResult(i.ticker, HOLD, ["geen trigger voor andere status"], flags)
