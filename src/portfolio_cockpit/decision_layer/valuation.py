"""Valuation engine — market-price dependent and independent of Quality Drift.

valuation_score 0-100: 50 ~ fair versus reference (own history + peers);
higher = more attractive, lower = more expensive.

Rules:
* Only economically meaningful metrics per company_type (config).
* Unusable metric => value None, status NOT_APPLICABLE.
* A negative P/E or EV/EBITDA is never read as cheap: zero/negative
  denominator => NOT_APPLICABLE.
* Never scored without a reference => NO_REFERENCE.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from portfolio_cockpit.config import load_config

from .config import load_decision_config
from .formulas import FORMULAS, MARKET_FIELDS
from .io import (
    bundle_hash,
    canonical_json,
    git_head,
    sha256_file,
    sha256_json,
    update_current_pointer,
    write_immutable_snapshot,
)


PIPELINE_VERSION = 1
OUTPUT_DIR = "data/valuation"
PREFIX = "valuation"
POINTER_KEY = "current_valuation"

CONFIG_FILES = ("config/valuation.yaml", "config/portfolio.yaml", "config/company_types.yaml")
CODE_FILES = (
    "src/portfolio_cockpit/decision_layer/valuation.py",
    "src/portfolio_cockpit/decision_layer/formulas.py",
    "src/portfolio_cockpit/decision_layer/config.py",
    "src/portfolio_cockpit/decision_layer/io.py",
)

OK = "OK"
NOT_APPLICABLE = "NOT_APPLICABLE"
MISSING_INPUT = "MISSING_INPUT"
NO_REFERENCE = "NO_REFERENCE"

STATUS_OK = "OK"
STATUS_NO_MARKET_DATA = "NO_MARKET_DATA"
STATUS_DATA_CHECK = "VALUATION_DATA_CHECK"

PROVENANCE_FIELDS = ("as_of_date", "retrieved_at")
SOURCE_FIELDS = ("source_type", "title")


class MarketDataError(ValueError):
    """Raised when a market or valuation-reference file violates its contract."""


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _iso(value: Any) -> bool:
    try:
        date.fromisoformat(str(value))
        return True
    except ValueError:
        return False


def _check_datapoint(label: str, item: Any, errors: list[str]) -> None:
    """A datapoint is {value, as_of_date, retrieved_at, source{...}}; value null = not supplied."""
    if not isinstance(item, dict) or "value" not in item:
        errors.append(f"{label} must be a mapping with a value")
        return
    if item["value"] is None:
        return
    if not _is_number(item["value"]):
        errors.append(f"{label}.value must be a number or null")
    for key in PROVENANCE_FIELDS:
        if not item.get(key):
            errors.append(f"{label}.{key} is required when value is set")
    if item.get("as_of_date") and not _iso(item["as_of_date"]):
        errors.append(f"{label}.as_of_date must be an ISO date")
    source = item.get("source") or {}
    for key in SOURCE_FIELDS:
        if not source.get(key):
            errors.append(f"{label}.source.{key} is required when value is set")


def validate_market_file(payload: dict[str, Any], tickers: set[str], path: Path | str) -> None:
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not _iso(payload.get("as_of")):
        errors.append("as_of must be an ISO date")
    entries = payload.get("tickers")
    if not isinstance(entries, dict):
        errors.append("tickers must be a mapping")
        entries = {}
    unknown = sorted(set(entries) - tickers)
    if unknown:
        errors.append(f"tickers not in portfolio.yaml: {unknown}")
    for ticker, entry in entries.items():
        if not isinstance(entry, dict):
            errors.append(f"{ticker} must be a mapping")
            continue
        extra = sorted(set(entry) - set(MARKET_FIELDS) - {"currency"})
        if extra:
            errors.append(f"{ticker} has unknown fields: {extra}")
        for name in MARKET_FIELDS:
            if name in entry:
                _check_datapoint(f"{ticker}.{name}", entry[name], errors)
        price = entry.get("price") or {}
        if price.get("value") is not None and not entry.get("currency"):
            errors.append(f"{ticker}.currency is required when a price is set")
    if errors:
        raise MarketDataError(f"{path}: " + "; ".join(errors))


def validate_reference_file(
    payload: dict[str, Any],
    ticker: str,
    metric_names: set[str],
    path: Path | str,
) -> None:
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if payload.get("ticker") != ticker:
        errors.append(f"ticker must be {ticker}")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("metrics must be a mapping")
        metrics = {}
    unknown = sorted(set(metrics) - metric_names)
    if unknown:
        errors.append(f"unknown valuation metrics: {unknown}")
    for name, refs in metrics.items():
        if not isinstance(refs, dict):
            errors.append(f"{name} must be a mapping")
            continue
        extra = sorted(set(refs) - {"own_history", "peers"})
        if extra:
            errors.append(f"{name} has unknown reference kinds: {extra}")
        for kind in ("own_history", "peers"):
            if kind not in refs:
                continue
            item = refs[kind]
            _check_datapoint(f"{name}.{kind}", item, errors)
            if isinstance(item, dict) and item.get("value") is not None and not item.get("method"):
                errors.append(f"{name}.{kind}.method is required when value is set")
    if errors:
        raise MarketDataError(f"{path}: " + "; ".join(errors))


def latest_market_file(root: Path, as_of: str) -> Path | None:
    candidates = sorted(
        p for p in (root / "data/market").glob("????-??-??.json") if p.stem <= as_of
    )
    return candidates[-1] if candidates else None


def load_references(root: Path, ticker: str, metric_names: set[str]) -> tuple[Path | None, dict[str, Any]]:
    path = root / "data/valuation_refs" / f"{ticker}.json"
    if not path.is_file():
        return None, {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_reference_file(payload, ticker, metric_names, path)
    return path, payload.get("metrics", {})


def label_for(score: float | None, cfg: dict[str, Any]) -> str | None:
    if score is None:
        return None
    labels = cfg["labels"]
    if score >= labels["attractive_min"]:
        return "Attractive"
    if score >= labels["fair_min"]:
        return "Fair"
    return "Expensive"


def combine_reference(refs: dict[str, Any] | None, cfg: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    """Weighted own-history/peer reference; weights renormalize over present positive values."""
    used: dict[str, Any] = {}
    if not refs:
        return None, used
    num = den = 0.0
    for kind, weight in cfg["reference_weights"].items():
        item = refs.get(kind) or {}
        value = item.get("value")
        if _is_number(value) and value > 0:
            num += float(weight) * value
            den += float(weight)
            used[kind] = {**item, "weight": weight}
    return (num / den if den else None), used


def compute_metric(
    *,
    name: str,
    company_type: str,
    inputs: dict[str, Any],
    refs: dict[str, Any] | None,
    cfg: dict[str, Any],
    price_as_of: str | None,
) -> dict[str, Any]:
    metric_cfg = cfg["metrics"][name]
    profile = cfg["profiles"][company_type]
    weight = float(profile["weights"].get(name, 0.0))
    needed, fn, method = FORMULAS[metric_cfg["formula"]]
    values = {k: (inputs.get(k) or {}).get("value") for k in needed}
    if "minorities" in inputs:
        values["minorities"] = (inputs["minorities"] or {}).get("value")
    raw_inputs = {
        k: {
            "value": v,
            "as_of_date": (inputs.get(k) or {}).get("as_of_date"),
            "source": (inputs.get(k) or {}).get("source"),
        }
        for k, v in values.items()
    }
    out = {
        "metric": name,
        "value": None,
        "status": None,
        "score": None,
        "weight": weight,
        "reference_value": None,
        "reference": {},
        "source": (inputs.get("price") or {}).get("source"),
        "as_of_date": price_as_of,
        "calculation_method": method,
        "raw_inputs": raw_inputs,
        "note": "",
    }
    if name in profile.get("not_applicable", []):
        out.update(status=NOT_APPLICABLE, weight=0.0, note=f"not economically meaningful for {company_type}")
        return out
    if any(values[k] is None for k in needed):
        out.update(status=MISSING_INPUT, note="missing input: " + ", ".join(k for k in needed if values[k] is None))
        return out
    numerator, denominator = fn(values)
    if denominator == 0 or (metric_cfg["requires_positive_denominator"] and denominator < 0):
        out.update(status=NOT_APPLICABLE, note="zero or negative denominator; never read as cheap")
        return out
    if metric_cfg["requires_positive_denominator"] and numerator <= 0:
        out.update(status=NOT_APPLICABLE, note="non-positive numerator (e.g. negative EV); not interpretable")
        return out
    value = numerator / denominator
    out["value"] = round(value, 6)
    reference, used = combine_reference(refs, cfg)
    out["reference"] = used
    if reference is None:
        out.update(status=NO_REFERENCE, note="no own-history or peer reference")
        return out
    relative = value / reference - 1.0
    signal = clamp(relative / float(metric_cfg["full_scale"]), -1.0, 1.0)
    score = 50.0 - 50.0 * signal if metric_cfg["cheaper_when"] == "lower" else 50.0 + 50.0 * signal
    out.update(status=OK, score=round(score, 4), reference_value=round(reference, 6))
    return out


def build_ticker_valuation(
    *,
    ticker: str,
    company_type: str,
    entry: dict[str, Any] | None,
    refs: dict[str, Any],
    cfg: dict[str, Any],
    as_of: str,
) -> dict[str, Any]:
    profile = cfg["profiles"][company_type]
    names = list(profile["weights"]) + [m for m in profile.get("not_applicable", []) if m in cfg["metrics"]]
    base = {"company_type": company_type, "execution_effect": "NONE"}
    price = (entry or {}).get("price") or {}
    if not entry or price.get("value") is None:
        return {
            **base,
            "status": STATUS_NO_MARKET_DATA,
            "valuation_score": None,
            "diagnostic_valuation_score": None,
            "label": None,
            "price": None,
            "currency": None,
            "price_as_of": None,
            "price_age_days": None,
            "metric_weight_coverage": 0.0,
            "metrics": [],
            "warnings": [f"MISSING_DATA:market:{ticker}"],
        }

    price_as_of = str(price["as_of_date"])
    metrics = [
        compute_metric(
            name=n, company_type=company_type, inputs=entry, refs=refs.get(n), cfg=cfg, price_as_of=price_as_of
        )
        for n in names
    ]
    warnings: list[str] = []
    num = den = 0.0
    for m in metrics:
        if m["status"] == OK:
            num += m["weight"] * m["score"]
            den += m["weight"]
        elif m["status"] == NOT_APPLICABLE and m["weight"] > 0:
            warnings.append(f"UNSUITABLE_METRIC:{m['metric']}")
        elif m["status"] == MISSING_INPUT:
            warnings.append(f"MISSING_DATA:valuation:{m['metric']}")
        elif m["status"] == NO_REFERENCE:
            warnings.append(f"MISSING_DATA:reference:{m['metric']}")
    score = num / den if den else None

    age = (date.fromisoformat(as_of) - date.fromisoformat(price_as_of)).days
    stale = age > int(cfg["max_price_age_days"])
    if stale:
        warnings.append(f"STALE_DATA:price:{age}d")
    if age < 0:
        warnings.append("CALCULATION_ANOMALY:price_date_after_as_of")

    if score is None or den + 1e-12 < float(cfg["minimum_metric_weight_coverage"]) or stale or age < 0:
        status = STATUS_DATA_CHECK
        if score is not None and den + 1e-12 < float(cfg["minimum_metric_weight_coverage"]):
            warnings.append(f"VALUATION_COVERAGE_BELOW_THRESHOLD:{den:.3f}")
    else:
        status = STATUS_OK
    published = status == STATUS_OK
    return {
        **base,
        "status": status,
        "valuation_score": round(score, 4) if published else None,
        "diagnostic_valuation_score": round(score, 4) if score is not None else None,
        "label": label_for(score, cfg) if published else None,
        "price": price["value"],
        "currency": entry.get("currency"),
        "price_as_of": price_as_of,
        "price_age_days": age,
        "metric_weight_coverage": round(den, 6),
        "metrics": metrics,
        "warnings": sorted(set(warnings)),
    }


def build_valuation_snapshot(
    *,
    root: Path,
    as_of: str | None = None,
    code_version: str | None = None,
) -> dict[str, Any]:
    repo_cfg = load_config(root)
    cfg = load_decision_config(root)["valuation"]
    as_of = as_of or datetime.now(timezone.utc).date().isoformat()
    tickers = set(repo_cfg["portfolio"]["positions"])
    metric_names = set(cfg["metrics"])

    market_path = latest_market_file(root, as_of)
    market: dict[str, Any] = {}
    if market_path is not None:
        market = json.loads(market_path.read_text(encoding="utf-8"))
        validate_market_file(market, tickers, market_path)

    results: dict[str, Any] = {}
    reference_hashes: dict[str, str] = {}
    for ticker, position in repo_cfg["portfolio"]["positions"].items():
        ref_path, refs = load_references(root, ticker, metric_names)
        if ref_path is not None:
            reference_hashes[ref_path.relative_to(root).as_posix()] = sha256_file(ref_path)
        results[ticker] = build_ticker_valuation(
            ticker=ticker,
            company_type=position["company_type"],
            entry=(market.get("tickers") or {}).get(ticker),
            refs=refs,
            cfg=cfg,
            as_of=as_of,
        )

    config_hash, config_hashes = bundle_hash(root, CONFIG_FILES)
    code_hash, code_hashes = bundle_hash(root, CODE_FILES)
    market_info = (
        {"path": market_path.relative_to(root).as_posix(), "sha256": sha256_file(market_path)}
        if market_path is not None
        else None
    )
    reproducibility_hash = sha256_json(
        {
            "as_of": as_of,
            "config_hash": config_hash,
            "code_hash": code_hash,
            "market": market_info,
            "references": reference_hashes,
        }
    )
    statuses = [r["status"] for r in results.values()]
    return {
        "schema_version": 1,
        "pipeline_version": PIPELINE_VERSION,
        "axis": "VALUATION",
        "as_of": as_of,
        "reproducibility_hash": reproducibility_hash,
        "methodology": {
            "score_scale": "50 ~ fair versus reference; higher = more attractive",
            "reference_weights": cfg["reference_weights"],
            "labels": cfg["labels"],
            "max_price_age_days": cfg["max_price_age_days"],
            "minimum_metric_weight_coverage": cfg["minimum_metric_weight_coverage"],
            "negative_denominator_rule": "NOT_APPLICABLE; never read as cheap",
        },
        "provenance": {
            "run_git_commit": code_version or git_head(root),
            "code_hash": code_hash,
            "config_hash": config_hash,
            "code_files": code_hashes,
            "config_files": config_hashes,
            "market_file": market_info,
            "reference_hashes": reference_hashes,
        },
        "summary": {
            "portfolio_companies": len(results),
            **{s: statuses.count(s) for s in (STATUS_OK, STATUS_NO_MARKET_DATA, STATUS_DATA_CHECK)},
        },
        "results": results,
        "execution_effect": "NONE",
    }


def write_valuation_snapshot(root: Path, payload: dict[str, Any]) -> Path:
    output_dir = root / OUTPUT_DIR
    path = write_immutable_snapshot(payload=payload, output_dir=output_dir, prefix=PREFIX)
    update_current_pointer(
        root=root, snapshot_path=path, payload=payload, output_dir=output_dir, pointer_key=POINTER_KEY
    )
    return path


def _repo_root_from_module() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Valuation from data/market and data/valuation_refs. Never touches Quality Drift."
    )
    parser.add_argument("--root", type=Path, default=_repo_root_from_module())
    parser.add_argument("--as-of", help="ISO date; default is today (UTC)")
    parser.add_argument("--code-version")
    parser.add_argument("--write", action="store_true", help="write an immutable revision to data/valuation/")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    payload = build_valuation_snapshot(root=root, as_of=args.as_of, code_version=args.code_version)
    if not args.write:
        print(canonical_json(payload), end="")
        return 0
    print(write_valuation_snapshot(root, payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
