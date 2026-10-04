"""Dry-run portfolio adjustment simulator and append-only signal log.

* Always a dry run: the simulator refuses ``dry_run=False``. There is no
  broker interface and no order output anywhere in this package.
* base_target_weight is the strategic anchor and is never changed; the
  simulation moves towards the score-adjusted target.
* Every decision signal is logged to data/signal_log/<as_of>.jsonl so the
  forward return per decision_state can later be evaluated.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .decision import ADD_CANDIDATE, DATA_CHECK, EXIT_REVIEW, REVIEW_REDUCE, THESIS_REVIEW, TRIM_CANDIDATE
from .risk import impact_pp


SIGNAL_LOG_DIR = "data/signal_log"


@dataclass(frozen=True)
class SimulationRow:
    ticker: str
    decision_state: str
    current_weight_pct: float
    base_target_weight_pct: float
    score_adjusted_target_pct: float
    suggested_review_direction: str
    difference_pct: float  # score_adjusted_target - current, percentage points
    simulated_weight_pct: float
    portfolio_impact_now_pp: float
    portfolio_impact_at_target_pp: float
    sector: str
    sector_weight_now_pct: float
    sector_weight_after_pct: float
    cash_impact_pct: float  # negative = cash would fall
    cash_impact_amount: float | None
    dry_run: bool = True
    execution_effect: str = "NONE"


def review_direction(state: str, difference_pct: float) -> str:
    if state == DATA_CHECK:
        return "NONE (DATA_CHECK)"
    if state == THESIS_REVIEW:
        return "REVIEW_THESIS"
    if state == EXIT_REVIEW:
        return "REVIEW_EXIT"
    if state == REVIEW_REDUCE:
        return "REVIEW_DOWN"
    if state == TRIM_CANDIDATE and difference_pct < 0:
        return "REVIEW_DOWN_TO_TARGET"
    if state == ADD_CANDIDATE and difference_pct > 0:
        return "REVIEW_UP_TO_TARGET"
    return "NONE"


class DryRunSimulator:
    """Simulates moving towards base target weights. Never executes anything."""

    def __init__(self, *, shock: float = -0.30, portfolio_value: float | None = None, dry_run: bool = True):
        if dry_run is not True:
            raise ValueError("DryRunSimulator only supports dry_run=True; live execution does not exist here")
        self.dry_run = True
        self.shock = shock
        self.portfolio_value = portfolio_value

    def simulate(self, decisions: dict[str, Any]) -> dict[str, Any]:
        results = decisions["results"]
        sector_now: dict[str, float] = defaultdict(float)
        for item in results.values():
            sector_now[item["inputs"]["sector"]] += float(item["inputs"]["current_weight_pct"])

        moves: dict[str, float] = {}
        rows: list[SimulationRow] = []
        for ticker, item in results.items():
            inputs = item["inputs"]
            current = float(inputs["current_weight_pct"])
            base = float(inputs["base_target_weight_pct"])
            target = float(inputs.get("score_adjusted_target_pct", base))
            difference = round(target - current, 6)
            direction = review_direction(item["decision_state"], difference)
            if direction in ("REVIEW_UP_TO_TARGET", "REVIEW_DOWN_TO_TARGET"):
                moved = difference
            elif direction == "REVIEW_DOWN":
                moved = min(0.0, difference)
            elif direction == "REVIEW_EXIT":
                moved = -current
            else:
                moved = 0.0
            moves[ticker] = moved
            rows.append(
                SimulationRow(
                    ticker=ticker,
                    decision_state=item["decision_state"],
                    current_weight_pct=current,
                    base_target_weight_pct=base,
                    score_adjusted_target_pct=target,
                    suggested_review_direction=direction,
                    difference_pct=difference,
                    simulated_weight_pct=round(current + moved, 6),
                    portfolio_impact_now_pp=impact_pp(current, self.shock),
                    portfolio_impact_at_target_pp=impact_pp(current + moved, self.shock),
                    sector=inputs["sector"],
                    sector_weight_now_pct=round(sector_now[inputs["sector"]], 6),
                    sector_weight_after_pct=0.0,  # filled below once all moves are known
                    cash_impact_pct=round(-moved, 6) + 0.0,
                    cash_impact_amount=(
                        round(-moved / 100.0 * self.portfolio_value, 2) + 0.0
                        if self.portfolio_value is not None
                        else None
                    ),
                )
            )

        sector_after: dict[str, float] = dict(sector_now)
        for row in rows:
            sector_after[row.sector] += moves[row.ticker]
        rows = [
            SimulationRow(**{**asdict(r), "sector_weight_after_pct": round(sector_after[r.sector], 6)}) for r in rows
        ]
        total_cash = sum(r.cash_impact_pct for r in rows)
        risk = decisions.get("portfolio_risk") or {}
        cash_now = risk.get("cash_weight_pct")
        return {
            "dry_run": True,
            "execution_effect": "NONE",
            "as_of": decisions["as_of"],
            "decision_snapshot_hash": decisions.get("reproducibility_hash"),
            "cash_weight_now_pct": cash_now,
            "cash_impact_total_pct": round(total_cash, 6) + 0.0,
            "cash_weight_after_pct": round(cash_now + total_cash, 6) if cash_now is not None else None,
            "sector_weights_after_pct": {k: round(v, 6) for k, v in sorted(sector_after.items())},
            "rows": [asdict(r) for r in rows],
        }


# ---------------------------------------------------------------- signal log


def signal_records(decisions: dict[str, Any], snapshot_rel: str) -> list[dict[str, Any]]:
    records = []
    for ticker, item in sorted(decisions["results"].items()):
        inputs = item["inputs"]
        records.append(
            {
                "as_of": decisions["as_of"],
                "ticker": ticker,
                "decision_state": item["decision_state"],
                "price": inputs.get("price"),
                "currency": inputs.get("currency"),
                "price_as_of": inputs.get("price_as_of"),
                "inputs": {
                    k: inputs.get(k)
                    for k in (
                        "drift_score",
                        "drift_change_recent",
                        "valuation_score",
                        "data_confidence",
                        "thesis_status",
                        "current_weight_pct",
                        "base_target_weight_pct",
                        "score_adjusted_target_pct",
                    )
                },
                "decision_snapshot": snapshot_rel,
                "decision_reproducibility_hash": decisions.get("reproducibility_hash"),
                "execution_effect": "NONE",
            }
        )
    return records


def append_signal_log(root: Path, decisions: dict[str, Any], snapshot_path: Path) -> Path:
    """Append-only; a decision snapshot already logged is not logged again."""
    directory = root / SIGNAL_LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{decisions['as_of']}.jsonl"
    existing: set[tuple[str, str]] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                existing.add((record["decision_reproducibility_hash"], record["ticker"]))
    new = [
        r
        for r in signal_records(decisions, snapshot_path.relative_to(root).as_posix())
        if (r["decision_reproducibility_hash"], r["ticker"]) not in existing
    ]
    if new:
        with path.open("a", encoding="utf-8") as handle:
            for record in new:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def load_signals(root: Path) -> list[dict[str, Any]]:
    signals = []
    for path in sorted((root / SIGNAL_LOG_DIR).glob("????-??-??.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                signals.append(json.loads(line))
    return signals


def parse_horizon(text: str) -> int:
    match = re.fullmatch(r"(\d+)d", text.strip())
    if not match or int(match[1]) <= 0:
        raise ValueError("horizon must look like '90d'")
    return int(match[1])


def _market_prices(root: Path) -> list[tuple[str, dict[str, float]]]:
    out = []
    for path in sorted((root / "data/market").glob("????-??-??.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        prices = {
            t: float(e["price"]["value"])
            for t, e in (payload.get("tickers") or {}).items()
            if isinstance(e, dict) and (e.get("price") or {}).get("value") is not None
        }
        out.append((path.stem, prices))
    return out


def evaluate_signals(
    signals: list[dict[str, Any]],
    market: list[tuple[str, dict[str, float]]],
    *,
    horizon_days: int,
    tolerance_days: int,
) -> dict[str, Any]:
    """Forward return per decision_state versus the mean of all evaluated signals.

    The later price is the first market file dated on or after signal date +
    horizon, within ``tolerance_days``. Signals without both prices are skipped.
    """
    returns: dict[str, list[float]] = defaultdict(list)
    evaluated: list[float] = []
    skipped = 0
    seen: set[tuple[str, str]] = set()
    for signal in signals:
        key = (signal["as_of"], signal["ticker"])
        if key in seen:
            continue  # one evaluation per ticker per signal date (latest revisions repeat it)
        seen.add(key)
        p0 = signal.get("price")
        target = date.fromisoformat(signal["as_of"]) + timedelta(days=horizon_days)
        p1 = None
        for day, prices in market:
            d = date.fromisoformat(day)
            if d >= target and (d - target).days <= tolerance_days and signal["ticker"] in prices:
                p1 = prices[signal["ticker"]]
                break
        if not p0 or p1 is None:
            skipped += 1
            continue
        r = p1 / float(p0) - 1.0
        returns[signal["decision_state"]].append(r)
        evaluated.append(r)
    portfolio_mean = sum(evaluated) / len(evaluated) if evaluated else None
    by_state = {
        state: {
            "n": len(values),
            "mean_forward_return": round(sum(values) / len(values), 6),
            "excess_vs_portfolio": (
                round(sum(values) / len(values) - portfolio_mean, 6) if portfolio_mean is not None else None
            ),
        }
        for state, values in sorted(returns.items())
    }
    return {
        "horizon_days": horizon_days,
        "evaluated_signals": len(evaluated),
        "skipped_signals": skipped,
        "portfolio_mean_forward_return": round(portfolio_mean, 6) if portfolio_mean is not None else None,
        "by_decision_state": by_state,
        "execution_effect": "NONE",
    }


def _repo_root_from_module() -> Path:
    return Path(__file__).resolve().parents[3]


def evaluate_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate logged decision signals: forward return per decision_state vs portfolio mean."
    )
    parser.add_argument("--root", type=Path, default=_repo_root_from_module())
    parser.add_argument("--horizon", default="90d", help="e.g. 90d")
    parser.add_argument("--tolerance-days", type=int, default=7)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report = evaluate_signals(
        load_signals(root),
        _market_prices(root),
        horizon_days=parse_horizon(args.horizon),
        tolerance_days=args.tolerance_days,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def simulate_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run simulation towards base target weights from the current decisions. Never executes."
    )
    parser.add_argument("--root", type=Path, default=_repo_root_from_module())
    parser.add_argument("--portfolio-value", type=float, help="optional, to express cash impact as an amount")
    args = parser.parse_args(argv)
    from .io import read_current

    root = args.root.resolve()
    found = read_current(root, root / "data/decisions", "current_decisions")
    if found is None:
        parser.exit(2, "cockpit-simulate: data/decisions/current.json is missing; run `cockpit-decide --write`\n")
    _, decisions = found
    shock = float((decisions.get("portfolio_risk") or {}).get("standard_shock", -0.30))
    result = DryRunSimulator(shock=shock, portfolio_value=args.portfolio_value).simulate(decisions)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
