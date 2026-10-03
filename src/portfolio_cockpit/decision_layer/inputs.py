"""Owner-input checker: says exactly what is still missing or invalid.

Covers config/positions.yaml, config/thesis_status.yaml, data/market/,
data/valuation_refs/ and data/observations/. Never fills in values.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from portfolio_cockpit.config import load_config

from .config import DecisionConfigError, load_decision_config, missing_owner_inputs
from .drift import ObservationError, load_observations
from .formulas import FORMULAS
from .valuation import MarketDataError, latest_market_file, load_references, validate_market_file


def check_inputs(root: Path, as_of: str | None = None) -> dict[str, Any]:
    as_of = as_of or datetime.now(timezone.utc).date().isoformat()
    report: dict[str, Any] = {"as_of": as_of, "errors": [], "blocking": [], "missing": {}, "info": []}
    try:
        cfg = load_decision_config(root)
    except DecisionConfigError as exc:
        report["errors"].append(str(exc))
        report["blocking"].append("config is invalid")
        return report
    repo_cfg = load_config(root)
    positions = repo_cfg["portfolio"]["positions"]
    valuation = cfg["valuation"]

    owner = missing_owner_inputs(cfg)
    report["missing"]["config/positions.yaml"] = owner["positions"]
    report["missing"]["config/thesis_status.yaml"] = owner["thesis_status"]
    if owner["positions"]:
        report["blocking"].append("config/positions.yaml is incomplete")
    if owner["thesis_status"]:
        report["blocking"].append("config/thesis_status.yaml is incomplete")

    if not owner["positions"]:
        sectors = {item["sector"] for item in cfg["positions"]["positions"].values()}
        for name, scenario in cfg["risk_scenarios"]["scenarios"].items():
            parts = scenario.get("components", [scenario])
            for part in parts:
                if part.get("type") == "sector" and part["sector"] not in sectors:
                    report["info"].append(
                        f"risk scenario {name}: sector {part['sector']!r} matches no position sector"
                    )

    market_path = latest_market_file(root, as_of)
    market_missing: list[str] = []
    entries: dict[str, Any] = {}
    if market_path is None:
        market_missing.append("no data/market/<date>.json on or before as_of")
        report["blocking"].append("no market data")
    else:
        try:
            payload = json.loads(market_path.read_text(encoding="utf-8"))
            validate_market_file(payload, set(positions), market_path.relative_to(root))
            entries = payload.get("tickers") or {}
        except MarketDataError as exc:
            report["errors"].append(str(exc))
    report["market_file"] = market_path.relative_to(root).as_posix() if market_path else None

    refs_missing: list[str] = []
    for ticker, position in positions.items():
        try:
            if not load_observations(root, ticker):
                report["info"].append(f"{ticker}: no observation after baseline yet (drift stays 50.0)")
        except ObservationError as exc:
            report["errors"].append(str(exc))

        profile = valuation["profiles"][position["company_type"]]
        entry = entries.get(ticker) or {}
        if market_path is not None:
            if (entry.get("price") or {}).get("value") is None:
                market_missing.append(f"{ticker}.price")
            elif not entry.get("currency"):
                market_missing.append(f"{ticker}.currency")
            needed = sorted(
                {f for m in profile["weights"] for f in FORMULAS[valuation["metrics"][m]["formula"]][0]} - {"price"}
            )
            for name in needed:
                if (entry.get(name) or {}).get("value") is None:
                    market_missing.append(f"{ticker}.{name}")
        try:
            ref_path, refs = load_references(root, ticker, set(valuation["metrics"]))
        except MarketDataError as exc:
            report["errors"].append(str(exc))
            continue
        if ref_path is None:
            refs_missing.append(f"{ticker}: no data/valuation_refs/{ticker}.json")
            continue
        for metric in profile["weights"]:
            item = refs.get(metric) or {}
            if all((item.get(k) or {}).get("value") is None for k in ("own_history", "peers")):
                refs_missing.append(f"{ticker}.{metric}")

    report["missing"]["data/market"] = market_missing
    report["missing"]["data/valuation_refs"] = refs_missing
    if report["errors"]:
        report["blocking"].append("invalid input files")
    report["ready_for_decisions"] = not report["blocking"]
    return report


def format_report(report: dict[str, Any]) -> str:
    lines = [f"Owner-input check (as_of {report['as_of']})"]
    for error in report["errors"]:
        lines.append(f"ERROR  {error}")
    for path, items in report["missing"].items():
        if items:
            lines.append(f"MISSING in {path} ({len(items)}):")
            lines.extend(f"  - {item}" for item in items)
        else:
            lines.append(f"OK     {path}")
    for item in report["info"]:
        lines.append(f"INFO   {item}")
    lines.append(
        "READY  decision engine can run" if report["ready_for_decisions"]
        else "BLOCKED " + "; ".join(report["blocking"])
    )
    return "\n".join(lines)


def _repo_root_from_module() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List exactly which owner inputs are missing or invalid.")
    parser.add_argument("--root", type=Path, default=_repo_root_from_module())
    parser.add_argument("--as-of", help="ISO date; default is today (UTC)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit 1 when anything blocks the decision engine")
    args = parser.parse_args(argv)
    report = check_inputs(args.root.resolve(), args.as_of)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else format_report(report))
    return 1 if args.strict and not report["ready_for_decisions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
