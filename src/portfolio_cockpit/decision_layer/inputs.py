"""Owner-input checker: says exactly what is still missing or invalid.

Covers config/positions.yaml, config/thesis_status.yaml, data/market/,
data/valuation_refs/ and data/observations/. Never fills in values.

data/market_peers/ only feeds the peer-alternatives signal, so problems
there are warnings and never block the decision engine.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from portfolio_cockpit.config import ConfigValidationError, load_config

from .config import DecisionConfigError, load_decision_config, missing_owner_inputs
from .drift import ObservationError, evidence_gate, load_observations
from .formulas import FORMULAS
from .formulas import MARKET_FIELDS
from .peer_alternatives import latest_market_peers_file, validate_market_peers_file
from .valuation import MarketDataError, latest_market_file, load_references, validate_market_file


def check_inputs(root: Path, as_of: str | None = None) -> dict[str, Any]:
    as_of = as_of or datetime.now(timezone.utc).date().isoformat()
    report: dict[str, Any] = {
        "as_of": as_of,
        "errors": [],
        "blocking": [],
        "missing": {},
        "info": [],
        "warnings": [],
        "ready_for_decisions": False,
    }
    try:
        cfg = load_decision_config(root)
        repo_cfg = load_config(root)
    except (DecisionConfigError, ConfigValidationError) as exc:
        # One line per validation error, so the owner sees exactly what to fix.
        report["errors"].extend(part.strip() for part in str(exc).split("; ") if part.strip())
        report["blocking"].append("config is invalid")
        return report
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
            observations = load_observations(root, ticker)
            if not observations:
                report["info"].append(f"{ticker}: no observation after baseline yet (drift stays 50.0)")
            for path, payload in observations:
                reason = evidence_gate(payload, cfg["quality_drift"], path.relative_to(root))
                if reason is not None:
                    report["info"].append(f"{path.relative_to(root)}: not used for drift ({reason})")
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
    report["warnings"].extend(_market_peers_warnings(root, as_of, repo_cfg, valuation, market_path))
    report["missing"]["data/valuation_refs"] = refs_missing
    if report["errors"]:
        report["blocking"].append("invalid input files")
    report["ready_for_decisions"] = not report["blocking"]
    return report


def _datapoint_dates(entry: dict[str, Any]) -> list[str]:
    items = [entry.get(name) for name in MARKET_FIELDS] + list((entry.get("multiples") or {}).values())
    return [str(i["as_of_date"])[:10] for i in items if isinstance(i, dict) and i.get("value") is not None
            and i.get("as_of_date")]


def _market_peers_warnings(
    root: Path, as_of: str, repo_cfg: dict[str, Any], valuation: dict[str, Any], market_path: Path | None
) -> list[str]:
    """Peer market data that is missing, invalid, stale or behind data/market."""
    path = latest_market_peers_file(root, as_of)
    if path is None:
        return ["no data/market_peers/<date>.json on or before as_of: peer-alternatives has no valuation comparison"]
    rel = path.relative_to(root).as_posix()
    payload = json.loads(path.read_text(encoding="utf-8"))
    known = {p for u in repo_cfg["peer_universes"]["universes"].values() for p in (u.get("peers") or [])}
    try:
        validate_market_peers_file(payload, known, set(valuation["metrics"]), rel)
    except MarketDataError as exc:
        return [f"invalid peer market data, cockpit-peer-alternatives will fail: {exc}"]

    warnings: list[str] = []
    if market_path is not None and path.stem < market_path.stem:
        warnings.append(f"{rel} is older than {market_path.relative_to(root).as_posix()}: refresh peer market data "
                        "with every market update")
    max_age = int(valuation["max_price_age_days"])
    stale: list[str] = []
    for ticker, entry in sorted((payload.get("tickers") or {}).items()):
        dates = _datapoint_dates(entry or {})
        if dates:
            age = (date.fromisoformat(as_of) - date.fromisoformat(min(dates))).days
            if age > max_age:
                stale.append(f"{ticker} ({age}d)")
    if stale:
        warnings.append(f"{len(stale)} peer(s) in {rel} have datapoints older than {max_age} days "
                        f"(STALE_DATA, no peer alert): " + ", ".join(stale))
    return warnings


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
    for item in report.get("warnings", []):
        lines.append(f"WARN   {item}")
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
