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
