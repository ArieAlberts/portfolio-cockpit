"""Score-adjusted target weight.

Three weights per position:

* base_target_weight_pct    config/portfolio.yaml; changed only by the owner.
* score_adjusted_target_pct base x quality multiplier, then gates, limits and
                            the portfolio budget (all numbers in
                            config/target_adjustment.yaml and decision.yaml).
* current_weight_pct        config/positions.yaml; broker data only.

The multiplier comes from Quality Drift only. Fundamental Quality and price
never move a target. Missing or unreliable data can never raise a target.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


GATE_DATA = "DATA_GATE"
GATE_THESIS_BROKEN = "THESIS_BROKEN"
GATE_EXIT = "EXIT_ROLE"
GATE_VALUATION_EXPENSIVE = "VALUATION_EXPENSIVE_CAP"
GATE_VALUATION_UNAVAILABLE = "VALUATION_UNAVAILABLE_CAP"
GATE_AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"

LIMIT_POSITION = "MAX_POSITION_WEIGHT"
LIMIT_IMPACT = "MAX_SINGLE_POSITION_IMPACT"
LIMIT_TICKER = "MAX_WEIGHT_TICKER"
LIMIT_SECTOR = "SECTOR_CAP"
LIMIT_BUDGET = "PORTFOLIO_BUDGET"


@dataclass(frozen=True)
class TargetInput:
    ticker: str
    base_target_weight_pct: float
    role: str
    sector: str
    drift_score: float | None
    drift_status: str | None
    drift_change_recent: float | None
    observation_count: int
    data_confidence: float | None
    thesis_status: str
    valuation_label: str | None
    valuation_status: str | None


@dataclass
class TargetResult:
    ticker: str
    base_target_weight_pct: float
    quality_multiplier_raw: float | None
    quality_multiplier_applied: float
    score_adjusted_target_pct: float
    gates: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    binding_constraint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_target_weight_pct": self.base_target_weight_pct,
            "quality_multiplier_raw": self.quality_multiplier_raw,
            "quality_multiplier_applied": self.quality_multiplier_applied,
            "score_adjusted_target_pct": self.score_adjusted_target_pct,
            "gates": list(self.gates),
            "constraints": list(self.constraints),
            "binding_constraint": self.binding_constraint,
        }


def quality_multiplier(drift: float, cfg: dict[str, Any]) -> float:
    """Piecewise-linear multiplier with a dead band; clamped outside the points."""
    qm = cfg["quality_multiplier"]
    band = qm["dead_band"]
    if float(band["low"]) <= drift <= float(band["high"]):
        return 1.0
    points = [(float(p["drift"]), float(p["multiplier"])) for p in qm["points"]]
    if drift <= points[0][0]:
        return points[0][1]
    if drift >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= drift <= x1:
            return y0 + (y1 - y0) * (drift - x0) / (x1 - x0)
    raise AssertionError("unreachable")


def _gated_multiplier(
    item: TargetInput,
    cfg: dict[str, Any],
    data_confidence_min: float,
) -> tuple[float | None, float, list[str]]:
    gates: list[str] = []
    raw = quality_multiplier(item.drift_score, cfg) if item.drift_score is not None else None
    applied = raw if raw is not None else 1.0

    # 1. Missing or unreliable data never raises (or lowers) a target.
    if (
        item.data_confidence is None
        or item.data_confidence < data_confidence_min
        or item.drift_status != "OK"
    ):
        if applied != 1.0 or raw is None:
            gates.append(GATE_DATA)
        applied = 1.0

    # 4. Valuation: an increase needs a usable, not-Expensive valuation.
    if applied > 1.0 and item.valuation_label == "Expensive":
        gates.append(GATE_VALUATION_EXPENSIVE)
        applied = 1.0
    elif applied > 1.0 and item.valuation_status != "OK":
        gates.append(GATE_VALUATION_UNAVAILABLE)
        applied = 1.0

    # 5. Asymmetry: an increase must be confirmed by consecutive observations;
    # a decrease applies immediately.
    needed = int(cfg["gates"]["min_consecutive_improvements"])
    if applied > 1.0 and needed > 1:
        previous = (
            item.drift_score - item.drift_change_recent
            if item.drift_score is not None and item.drift_change_recent is not None
            else None
        )
        previous_mult = quality_multiplier(previous, cfg) if previous is not None else None
        if item.observation_count < needed or previous_mult is None or previous_mult <= 1.0:
            gates.append(GATE_AWAITING_CONFIRMATION)
            applied = 1.0
        else:
            applied = min(applied, previous_mult)
    return raw, applied, gates


def _scale_increases(
    results: list[TargetResult],
    limit: float,
    constraint: str,
) -> bool:
    """Scale only the increases above base so the total fits ``limit``.

    Returns False when the base parts alone already exceed the limit.
    """
    total = sum(r.score_adjusted_target_pct for r in results)
    if total <= limit + 1e-9:
        return True
    increases = [r for r in results if r.score_adjusted_target_pct > r.base_target_weight_pct + 1e-12]
    fixed = total - sum(r.score_adjusted_target_pct - r.base_target_weight_pct for r in increases)
    increase_total = total - fixed
    room = max(0.0, limit - fixed)
    factor = room / increase_total if increase_total > 0 else 0.0
    for r in increases:
        r.score_adjusted_target_pct = r.base_target_weight_pct + (
            r.score_adjusted_target_pct - r.base_target_weight_pct
        ) * factor
        r.constraints.append(constraint)
        r.binding_constraint = constraint
    return fixed <= limit + 1e-9


def compute_targets(
    items: list[TargetInput],
    *,
    target_cfg: dict[str, Any],
    limits: dict[str, Any],
    data_confidence_min: float,
    standard_shock: float,
) -> tuple[dict[str, TargetResult], list[str]]:
    """Score-adjusted targets per ticker plus portfolio-level warnings."""
    results: dict[str, TargetResult] = {}
    caps = target_cfg.get("max_weight_pct") or {}
    impact_cap = float(limits["max_single_position_impact_pp"]) / abs(standard_shock)

    for item in items:
        base = float(item.base_target_weight_pct)
        raw, applied, gates = _gated_multiplier(item, target_cfg, data_confidence_min)

        # 2. Broken thesis: back to base; the decision is THESIS_REVIEW.
        if item.thesis_status == "BROKEN":
            gates.append(GATE_THESIS_BROKEN)
            applied = 1.0
        # 3. Exit position: target is zero.
        if item.role == "EXIT":
            gates.append(GATE_EXIT)
            result = TargetResult(item.ticker, base, raw, 0.0, 0.0, gates, [], GATE_EXIT)
            results[item.ticker] = result
            continue

        target = base * applied
        result = TargetResult(item.ticker, base, raw, applied, target, gates)
        if gates:
            result.binding_constraint = gates[-1]
        for name, cap in (
            (LIMIT_POSITION, float(limits["max_position_weight_pct"])),
            (LIMIT_IMPACT, impact_cap),
            (LIMIT_TICKER, float(caps[item.ticker]) if item.ticker in caps else None),
        ):
            if cap is not None and result.score_adjusted_target_pct > cap + 1e-12:
                result.score_adjusted_target_pct = cap
                result.constraints.append(name)
                result.binding_constraint = name
        results[item.ticker] = result

    warnings: list[str] = []
    by_sector: dict[str, list[TargetResult]] = {}
    for item in items:
        by_sector.setdefault(item.sector, []).append(results[item.ticker])
    sector_cap = float(limits["max_sector_weight_pct"])
    for sector, members in sorted(by_sector.items()):
        if not _scale_increases(members, sector_cap, LIMIT_SECTOR):
            warnings.append(f"SECTOR_BASE_ABOVE_CAP:{sector}")

    budget = 100.0 - float(target_cfg["budget"]["min_cash_pct"])
    if not _scale_increases(list(results.values()), budget, LIMIT_BUDGET):
        warnings.append("BASE_TARGETS_ABOVE_BUDGET")

    for r in results.values():
        r.score_adjusted_target_pct = round(r.score_adjusted_target_pct, 6)
        r.quality_multiplier_applied = round(r.quality_multiplier_applied, 6)
        if r.quality_multiplier_raw is not None:
            r.quality_multiplier_raw = round(r.quality_multiplier_raw, 6)
    return results, warnings
