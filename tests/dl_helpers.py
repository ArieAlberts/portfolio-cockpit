"""Shared helpers for decision-layer tests."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-10-03"


def repo_copy(tmp_path: Path) -> Path:
    """Copy the inputs a decision-layer run needs into an isolated root."""
    root = tmp_path / "repo"
    for rel in ("config", "data", "src"):
        shutil.copytree(ROOT / rel, root / rel, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def load_baseline(ticker: str, root: Path = ROOT) -> tuple[str, dict[str, Any]]:
    index = json.loads((root / "data/baselines/index.json").read_text(encoding="utf-8"))
    rel = index["baselines"][ticker]
    return rel, json.loads((root / rel).read_text(encoding="utf-8"))


def observation_from_baseline(
    ticker: str,
    drift_cfg: dict[str, Any],
    *,
    observation_date: str = "2026-09-30",
    overrides: dict[str, Any] | None = None,
    period_basis: dict[str, str] | None = None,
    drop: tuple[str, ...] = (),
    root: Path = ROOT,
) -> dict[str, Any]:
    """Observation that repeats the baseline values with full provenance.

    ``overrides``/``period_basis``/``drop`` are keyed by metric name.
    """
    from portfolio_cockpit.decision_layer.drift import baseline_period_basis

    _, baseline = load_baseline(ticker, root)
    overrides = overrides or {}
    period_basis = period_basis or {}
    metrics: dict[str, dict[str, Any]] = {}
    for component, values in baseline["metrics"].items():
        for metric, value in values.items():
            if metric in drop:
                continue
            metrics.setdefault(component, {})[metric] = {
                "value": overrides.get(metric, value),
                "period": "TEST",
                "period_basis": period_basis.get(
                    metric, baseline_period_basis(drift_cfg, ticker, metric)
                ),
                "source": {
                    "source_type": "OFFICIAL_COMPANY_REPORT",
                    "title": "test observation",
                    "url": "https://example.invalid/report",
                    "publication_date": observation_date,
                    "report_id": "TEST",
                },
                "retrieved_at": f"{observation_date}T09:00:00Z",
                "currency": "N/A",
                "calculation_method": "reported",
            }
    return {
        "schema_version": 1,
        "ticker": ticker,
        "observation_date": observation_date,
        "reporting_period_end": observation_date,
        "metrics": metrics,
    }


def write_observation(root: Path, payload: dict[str, Any], name: str | None = None) -> Path:
    directory = root / "data/observations" / payload["ticker"]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name or f"{payload['observation_date']}.json")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def datapoint(value: Any, as_of_date: str = AS_OF) -> dict[str, Any]:
    return {
        "value": value,
        "as_of_date": as_of_date,
        "retrieved_at": f"{as_of_date}T18:00:00Z",
        "source": {"source_type": "MANUAL_ENTRY", "title": "test market data", "url": None},
    }


def market_entry(currency: str = "EUR", price_date: str = AS_OF, **values: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"currency": currency}
    for name, value in values.items():
        entry[name] = datapoint(value, price_date if name == "price" else AS_OF)
    return entry


def reference(own: float | None, peers: float | None) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    if own is not None:
        refs["own_history"] = {**datapoint(own), "method": "5y median"}
    if peers is not None:
        refs["peers"] = {**datapoint(peers), "method": "peer median"}
    return refs


def write_market(root: Path, entries: dict[str, Any], as_of: str = AS_OF) -> Path:
    path = root / "data/market" / f"{as_of}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "as_of": as_of, "tickers": entries}, indent=2), encoding="utf-8")
    return path


def write_refs(root: Path, ticker: str, metrics: dict[str, Any]) -> Path:
    path = root / "data/valuation_refs" / f"{ticker}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "ticker": ticker, "metrics": metrics}, indent=2), encoding="utf-8")
    return path


SECTORS = {
    "ASR": "Financials", "ADM.L": "Financials", "PLMR": "Financials", "ABX": "Financials",
    "ERO": "Materials", "CRDA.L": "Materials", "EMN": "Materials", "FUL": "Materials",
    "IMCD": "Materials", "ESI": "Materials", "LEU": "Energy", "OKLO": "Utilities",
    "TMDX": "Health Care", "WSM": "Consumer", "DKS": "Consumer", "TXRH": "Consumer",
}


def filled_owner_config(cfg: dict[str, Any], repo_cfg: dict[str, Any]) -> dict[str, Any]:
    """Test-only filled copy of the owner templates: current weight = target weight."""
    from copy import deepcopy

    filled = deepcopy(cfg)
    filled["positions"]["as_of"] = AS_OF
    filled["positions"]["cash_weight_pct"] = float(repo_cfg["portfolio"]["cash_weight_pct"])
    for ticker, item in filled["positions"]["positions"].items():
        item["weight_pct"] = float(repo_cfg["portfolio"]["positions"][ticker]["weight_pct"])
        item["sector"] = SECTORS.get(ticker, "Industrials")
    for item in filled["thesis_status"]["positions"].values():
        item.update(status="INTACT", as_of=AS_OF, note="test")
    return filled


def write_owner_config(root: Path, filled: dict[str, Any]) -> None:
    import yaml

    for name in ("positions", "thesis_status"):
        (root / f"config/{name}.yaml").write_text(yaml.safe_dump(filled[name], sort_keys=False), encoding="utf-8")
