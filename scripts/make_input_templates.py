#!/usr/bin/env python3
"""Generate empty owner-input templates under data/templates/.

Templates contain only nulls: the system never invents numbers. Copy a
template to its real location (see data/templates/README.md), fill it in,
then run `cockpit-check-inputs` to see exactly what is still missing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from portfolio_cockpit.config import load_config  # noqa: E402
from portfolio_cockpit.decision_layer.config import load_decision_config  # noqa: E402
from portfolio_cockpit.decision_layer.formulas import FORMULAS  # noqa: E402


def _datapoint() -> dict:
    return {
        "value": None,
        "as_of_date": None,
        "retrieved_at": None,
        "source": {"source_type": None, "title": None, "url": None},
    }


def _reference() -> dict:
    return {**_datapoint(), "method": None}


def _dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build(root: Path) -> list[Path]:
    repo_cfg = load_config(root)
    valuation = load_decision_config(root)["valuation"]
    out = root / "data/templates"
    written: list[Path] = []

    market: dict = {"schema_version": 1, "as_of": None, "tickers": {}}
    for ticker, position in repo_cfg["portfolio"]["positions"].items():
        profile = valuation["profiles"][position["company_type"]]
        fields: set[str] = set()
        for metric in profile["weights"]:
            fields.update(FORMULAS[valuation["metrics"][metric]["formula"]][0])
        entry = {"currency": None, **{f: _datapoint() for f in sorted(fields)}}
        market["tickers"][ticker] = entry

        refs = {
            "schema_version": 1,
            "ticker": ticker,
            "metrics": {
                metric: {"own_history": _reference(), "peers": _reference()}
                for metric in profile["weights"]
            },
        }
        path = out / "valuation_refs" / f"{ticker}.json"
        _dump(path, refs)
        written.append(path)

    path = out / "market.json"
    _dump(path, market)
    written.append(path)

    # Peer-alternatives: per peer the multiples of the position's valuation
    # profile (or the raw inputs, like market.json). Units as in market.json;
    # yields as fractions (0.05 = 5%).
    market_peers: dict = {"schema_version": 1, "as_of": None, "tickers": {}}
    for ticker, universe in sorted(repo_cfg["peer_universes"]["universes"].items()):
        profile = valuation["profiles"][repo_cfg["portfolio"]["positions"][ticker]["company_type"]]
        for peer in universe.get("peers") or []:
            entry = market_peers["tickers"].setdefault(peer, {"currency": None, "multiples": {}})
            for metric in profile["weights"]:
                entry["multiples"][metric] = _reference()
    path = out / "market_peers.json"
    _dump(path, market_peers)
    written.append(path)

    observation = {
        "schema_version": 1,
        "ticker": "<TICKER>",
        "update_trigger": "<one of quality_drift.yaml evidence_gate.allowed_update_triggers>",
        "source_confidence": None,
        "observation_date": None,
        "reporting_period_end": None,
        "metrics": {
            "<component>": {
                "<metric_name_as_in_baseline>": {
                    "value": None,
                    "period": None,
                    "period_basis": None,
                    "source": {
                        "source_type": "OFFICIAL_COMPANY_REPORT",
                        "title": None,
                        "url": None,
                        "publication_date": None,
                        "report_id": None,
                    },
                    "retrieved_at": None,
                    "currency": None,
                    "calculation_method": "reported",
                }
            }
        },
    }
    path = out / "observation.json"
    _dump(path, observation)
    written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    for path in build(args.root.resolve()):
        print(path.relative_to(args.root.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
