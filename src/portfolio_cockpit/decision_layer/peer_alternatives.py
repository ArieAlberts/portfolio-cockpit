"""Peer-alternatives signal — analysis only, ``execution_effect`` NONE.

Per position, flags a peer from ``config/peer_universes.yaml`` that is
fundamentally stronger and/or cheaper, so the owner can consider it in place
of the current position. Never edits ``portfolio.yaml`` or ``positions.yaml``
and never proposes an order.

* Fundamental Quality: position = published DISPLAY_READY score; peer = the
  same pipeline with the peer as target (``peer_quality.py``). A peer that
  cannot be scored is INSUFFICIENT and never alerts on quality.
* Valuation: position and peer are both scored against the same peer median
  (``data/valuation_refs/<position>.json`` -> ``metrics.<m>.peers``), on the
  metrics both can be scored on. Peer inputs come from
  ``data/market_peers/<date>.json``.
* Alert types (thresholds in ``config/peer_alternatives.yaml``):
  STRONGER_PEER, CHEAPER_PEER, BETTER_PEER (both). Position without
  Fundamental Quality: CHEAPER_PEER only, labelled VALUATION_ONLY.
* Only when data confidence of both >= the minimum and nothing is stale.
* Persistence: CANDIDATE until present in N consecutive runs (ISO weeks),
  then ACTIVE.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from portfolio_cockpit.config import load_config
from portfolio_cockpit.scoring.confidence_inputs import freshness_score
from portfolio_cockpit.scoring.pipeline import CODE_FILES as FQ_CODE_FILES

from .config import load_decision_config
from .decision import _assert_no_order_fields, _fundamental_quality
from .formulas import MARKET_FIELDS
from .io import (
    bundle_hash,
    canonical_json,
    git_head,
    read_current,
    sha256_file,
    sha256_json,
    update_current_pointer,
    write_immutable_snapshot,
)
from .peer_quality import QualityResult, candidate_peers, score_peer
from .valuation import (
    OK,
    MarketDataError,
    _check_datapoint,
    _iso,
    clamp,
    combine_reference,
    compute_metric,
    latest_market_file,
    load_references,
)
from .warnings import load_target_confidence

PIPELINE_VERSION = 1
CONFIG_PATH = "config/peer_alternatives.yaml"
OUTPUT_DIR = "data/alerts"
PREFIX = "peer_alternatives"
POINTER_KEY = "current_peer_alternatives"
MARKET_PEERS_DIR = "data/market_peers"

CONFIG_FILES = (
    CONFIG_PATH,
    "config/valuation.yaml",
    "config/confidence.yaml",
    "config/peer_universes.yaml",
    "config/portfolio.yaml",
    "config/company_types.yaml",
    "config/scoring.yaml",
    "config/score_metrics.yaml",
    "config/readiness.yaml",
)
CODE_FILES = (
    "src/portfolio_cockpit/decision_layer/peer_alternatives.py",
    "src/portfolio_cockpit/decision_layer/peer_quality.py",
    "src/portfolio_cockpit/decision_layer/valuation.py",
    "src/portfolio_cockpit/decision_layer/formulas.py",
    "src/portfolio_cockpit/decision_layer/io.py",
    *FQ_CODE_FILES,
)

STRONGER = "STRONGER_PEER"
CHEAPER = "CHEAPER_PEER"
BETTER = "BETTER_PEER"
ACTIVE = "ACTIVE"
CANDIDATE = "CANDIDATE"
BASIS_FULL = "QUALITY_AND_VALUATION"
BASIS_VALUATION_ONLY = "VALUATION_ONLY"

REVISION_RE = re.compile(rf"^{PREFIX}_(?P<date>\d{{4}}-\d{{2}}-\d{{2}})(?:_r(?P<rev>\d+))?\.json$")


class PeerAlternativesConfigError(ValueError):
    """Raised when config/peer_alternatives.yaml is invalid."""


# ------------------------------------------------------------------- config


def _number(errors: list[str], label: str, value: Any, *, minimum: float = 0.0, maximum: float | None = None,
            integer: bool = False) -> None:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if integer:
        ok = ok and isinstance(value, int)
    if not ok or value < minimum or (maximum is not None and value > maximum):
        bound = f">= {minimum}" + (f" and <= {maximum}" if maximum is not None else "")
        errors.append(f"{label} must be {'an integer' if integer else 'a number'} {bound}")


def validate_peer_alternatives_config(cfg: Any) -> None:
    errors: list[str] = []
    if not isinstance(cfg, dict):
        raise PeerAlternativesConfigError(f"{CONFIG_PATH}: expected a YAML mapping")
    if cfg.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    _number(errors, "minimum_data_confidence", cfg.get("minimum_data_confidence"), maximum=100)
    rules = cfg.get("rules") or {}
    expected = {STRONGER: ("min_fq_advantage", "max_valuation_disadvantage"),
                CHEAPER: ("min_valuation_advantage", "max_fq_disadvantage")}
    if set(rules) != set(expected):
        errors.append(f"rules must define exactly {sorted(expected)}")
    for name, keys in expected.items():
        for key in keys:
            _number(errors, f"rules.{name}.{key}", (rules.get(name) or {}).get(key), maximum=100)
    vo = cfg.get("valuation_only") or {}
    for key in ("enabled", "require_peer_fundamental_quality"):
        if not isinstance(vo.get(key), bool):
            errors.append(f"valuation_only.{key} must be true or false")
    persistence = cfg.get("persistence") or {}
    _number(errors, "persistence.required_consecutive_runs", persistence.get("required_consecutive_runs"),
            minimum=1, integer=True)
    if persistence.get("run_period") != "iso_week":
        errors.append("persistence.run_period must be 'iso_week'")
    _number(errors, "valuation_comparison.minimum_common_metric_weight_coverage",
            (cfg.get("valuation_comparison") or {}).get("minimum_common_metric_weight_coverage"), maximum=1)
    _number(errors, "staleness.minimum_fundamental_freshness_score",
            (cfg.get("staleness") or {}).get("minimum_fundamental_freshness_score"), maximum=100)
    _number(errors, "output.top_metric_differences", (cfg.get("output") or {}).get("top_metric_differences"),
            minimum=1, integer=True)
    if errors:
        raise PeerAlternativesConfigError(f"{CONFIG_PATH}: " + "; ".join(errors))


def load_peer_alternatives_config(root: Path) -> dict[str, Any]:
    path = root / CONFIG_PATH
    if not path.is_file():
        raise PeerAlternativesConfigError(f"{CONFIG_PATH}: missing config file")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    validate_peer_alternatives_config(cfg)
    return cfg


# -------------------------------------------------------------- market peers


def latest_market_peers_file(root: Path, as_of: str) -> Path | None:
    candidates = sorted(p for p in (root / MARKET_PEERS_DIR).glob("????-??-??.json") if p.stem <= as_of)
    return candidates[-1] if candidates else None


def validate_market_peers_file(
    payload: dict[str, Any], known_peers: set[str], metric_names: set[str], path: Path | str
) -> None:
    """Same datapoint format as data/market; per peer the inputs and/or direct multiples."""
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not _iso(payload.get("as_of")):
        errors.append("as_of must be an ISO date")
    entries = payload.get("tickers")
    if not isinstance(entries, dict):
        errors.append("tickers must be a mapping")
        entries = {}
    unknown = sorted(set(entries) - known_peers)
    if unknown:
        errors.append(f"tickers not a peer in config/peer_universes.yaml: {unknown}")
    for ticker, entry in entries.items():
        if not isinstance(entry, dict):
            errors.append(f"{ticker} must be a mapping")
            continue
        extra = sorted(set(entry) - set(MARKET_FIELDS) - {"currency", "multiples"})
        if extra:
            errors.append(f"{ticker} has unknown fields: {extra}")
        for name in MARKET_FIELDS:
            if name in entry:
                _check_datapoint(f"{ticker}.{name}", entry[name], errors)
        price = entry.get("price") or {}
        if price.get("value") is not None and not entry.get("currency"):
            errors.append(f"{ticker}.currency is required when a price is set")
        multiples = entry.get("multiples") or {}
        if not isinstance(multiples, dict):
            errors.append(f"{ticker}.multiples must be a mapping")
            continue
        bad = sorted(set(multiples) - metric_names)
        if bad:
            errors.append(f"{ticker}.multiples has unknown valuation metrics: {bad}")
        for name, item in multiples.items():
            _check_datapoint(f"{ticker}.multiples.{name}", item, errors)
            if isinstance(item, dict) and item.get("value") is not None and not item.get("method"):
                errors.append(f"{ticker}.multiples.{name}.method is required when value is set")
    if errors:
        raise MarketDataError(f"{path}: " + "; ".join(errors))


# ----------------------------------------------------------------- valuation


def _direct_metric(name: str, item: dict[str, Any], ref: dict[str, Any] | None, cfg: dict[str, Any],
                   weight: float) -> dict[str, Any]:
    """Score a directly supplied multiple exactly like ``compute_metric`` scores a computed one."""
    metric_cfg = cfg["metrics"][name]
    value = float(item["value"])
    out = {"metric": name, "value": value, "status": None, "score": None, "weight": weight,
           "reference_value": None, "as_of_date": item.get("as_of_date"), "source": item.get("source"),
           "calculation_method": item.get("method"), "input": "direct_multiple"}
    if metric_cfg["requires_positive_denominator"] and value <= 0:
        out["status"] = "NOT_APPLICABLE"
        return out
    reference, _ = combine_reference({"peers": ref} if ref else None, cfg)
    if reference is None:
        out["status"] = "NO_REFERENCE"
        return out
    signal = clamp((value / reference - 1.0) / float(metric_cfg["full_scale"]), -1.0, 1.0)
    score = 50.0 - 50.0 * signal if metric_cfg["cheaper_when"] == "lower" else 50.0 + 50.0 * signal
    out.update(status=OK, score=round(score, 4), reference_value=round(reference, 6))
    return out


def company_valuation_metrics(
    *, entry: dict[str, Any] | None, company_type: str, peer_refs: dict[str, Any], cfg: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Per profile metric: value and score against the position's peer median only."""
    profile = cfg["profiles"][company_type]
    entry = entry or {}
    price_as_of = (entry.get("price") or {}).get("as_of_date")
    out: dict[str, dict[str, Any]] = {}
    for name, weight in profile["weights"].items():
        ref = peer_refs.get(name)
        direct = (entry.get("multiples") or {}).get(name) or {}
        if direct.get("value") is not None:
            out[name] = _direct_metric(name, direct, ref, cfg, float(weight))
            continue
        result = compute_metric(
            name=name, company_type=company_type, inputs=entry,
            refs={"peers": ref} if ref else None, cfg=cfg, price_as_of=price_as_of,
        )
        out[name] = {
            "metric": name, "value": result["value"], "status": result["status"], "score": result["score"],
            "weight": result["weight"], "reference_value": result["reference_value"],
            "as_of_date": price_as_of, "source": result["source"],
            "calculation_method": result["calculation_method"], "input": "computed",
        }
    return out


def pair_valuation(
    position: dict[str, dict[str, Any]], peer: dict[str, dict[str, Any]], minimum_coverage: float
) -> dict[str, Any] | None:
    """Weighted scores of both on the metrics both can be scored on; None below the coverage floor."""
    common = [m for m in position if position[m]["status"] == OK and peer.get(m, {}).get("status") == OK]
    weight = sum(position[m]["weight"] for m in common)
    if not common or weight + 1e-12 < minimum_coverage:
        return None

    def score(side: dict[str, dict[str, Any]]) -> float:
        return round(sum(side[m]["weight"] * side[m]["score"] for m in common) / weight, 4)

    return {"metrics": common, "weight_coverage": round(weight, 6),
            "position_score": score(position), "peer_score": score(peer)}


def market_age_days(metrics: dict[str, dict[str, Any]], as_of: str) -> int | None:
    dates = [m["as_of_date"] for m in metrics.values() if m["status"] == OK and m.get("as_of_date")]
    if not dates:
        return None
    return max((date.fromisoformat(as_of) - date.fromisoformat(str(d)[:10])).days for d in dates)


# ------------------------------------------------------------ classification


def classify(
    *, position_fq: float | None, peer_fq: float | None, position_valuation: float, peer_valuation: float,
    cfg: dict[str, Any],
) -> tuple[str | None, str]:
    """Return (alert type or None, basis). Pure: thresholds come from ``cfg``."""
    rules = cfg["rules"]
    cheaper_val = peer_valuation >= position_valuation + float(rules[CHEAPER]["min_valuation_advantage"])
    if position_fq is None:
        vo = cfg["valuation_only"]
        if not vo["enabled"] or (vo["require_peer_fundamental_quality"] and peer_fq is None):
            return None, BASIS_VALUATION_ONLY
        return (CHEAPER if cheaper_val else None), BASIS_VALUATION_ONLY
    if peer_fq is None:
        return None, BASIS_FULL
    stronger = (
        peer_fq >= position_fq + float(rules[STRONGER]["min_fq_advantage"])
        and peer_valuation >= position_valuation - float(rules[STRONGER]["max_valuation_disadvantage"])
    )
    cheaper = cheaper_val and peer_fq >= position_fq - float(rules[CHEAPER]["max_fq_disadvantage"])
    if stronger and cheaper:
        return BETTER, BASIS_FULL
    if stronger:
        return STRONGER, BASIS_FULL
    if cheaper:
        return CHEAPER, BASIS_FULL
    return None, BASIS_FULL


def metric_differences(
    *, position_fq_metrics: dict[str, dict[str, Any]], peer_fq_metrics: dict[str, dict[str, Any]],
    position_val: dict[str, dict[str, Any]], peer_val: dict[str, dict[str, Any]], valuation_metrics: list[str],
    top: int,
) -> list[dict[str, Any]]:
    """Largest differences in score points: FQ metric = 25 x z difference; valuation = metric score difference."""
    diffs: list[dict[str, Any]] = []
    for name in sorted(set(position_fq_metrics) & set(peer_fq_metrics)):
        pz, qz = position_fq_metrics[name].get("clipped_z_score"), peer_fq_metrics[name].get("clipped_z_score")
        if pz is None or qz is None:
            continue
        diffs.append({"axis": "fundamental_quality", "metric": name,
                      "position_value": position_fq_metrics[name].get("value"),
                      "peer_value": peer_fq_metrics[name].get("value"),
                      "difference_points": round(25.0 * (qz - pz), 4)})
    for name in valuation_metrics:
        diffs.append({"axis": "valuation", "metric": name,
                      "position_value": position_val[name]["value"], "peer_value": peer_val[name]["value"],
                      "difference_points": round(peer_val[name]["score"] - position_val[name]["score"], 4)})
    diffs.sort(key=lambda d: (-abs(d["difference_points"]), d["axis"], d["metric"]))
    return diffs[:top]


# --------------------------------------------------------------- persistence


def _iso_week(day: str) -> tuple[int, int]:
    year, week, _ = date.fromisoformat(day).isocalendar()
    return year, week


def previous_run(root: Path, as_of: str) -> tuple[Path | None, dict[str, Any]]:
    """Latest snapshot from an earlier ISO week (re-runs in the same week never advance alerts)."""
    best: tuple[str, int, Path] | None = None
    for path in (root / OUTPUT_DIR).glob(f"{PREFIX}_*.json"):
        m = REVISION_RE.match(path.name)
        if not m or _iso_week(m["date"]) >= _iso_week(as_of):
            continue
        key = (m["date"], int(m["rev"] or 1), path)
        if best is None or key[:2] > best[:2]:
            best = key
    if best is None:
        return None, {}
    return best[2], json.loads(best[2].read_text(encoding="utf-8"))


def apply_persistence(alerts: list[dict[str, Any]], previous: dict[str, Any], as_of: str, required: int) -> None:
    before = {(a["position"], a["peer"]): a for a in previous.get("alerts", [])}
    for alert in alerts:
        prior = before.get((alert["position"], alert["peer"]))
        alert["consecutive_runs"] = (int(prior["consecutive_runs"]) + 1) if prior else 1
        alert["first_seen"] = prior["first_seen"] if prior else as_of
        alert["status"] = ACTIVE if alert["consecutive_runs"] >= required else CANDIDATE


# ------------------------------------------------------------------ snapshot


def _position_fq_metrics(item: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for component in ((item or {}).get("selected_metrics") or {}).values():
        for metric in (component.get("metrics") or {}).values():
            out[metric["metric_name"]] = {"value": metric.get("target_value"),
                                          "clipped_z_score": metric.get("clipped_z_score")}
    return out


def _quality_summary(q: QualityResult) -> dict[str, Any]:
    return {"status": q.status, "score": q.score, "diagnostic_score": q.diagnostic_score,
            "stability_flag": q.stability_flag, "data_confidence": q.data_confidence,
            "warnings": list(q.warnings)}


def build_peer_alternatives_snapshot(
    *, root: Path, as_of: str | None = None, code_version: str | None = None
) -> dict[str, Any]:
    cfg = load_peer_alternatives_config(root)
    repo_cfg = load_config(root)
    val_cfg = load_decision_config(root)["valuation"]
    confidence_cfg = yaml.safe_load((root / "config/confidence.yaml").read_text(encoding="utf-8"))
    universes = repo_cfg["peer_universes"]["universes"]
    as_of = as_of or datetime.now(timezone.utc).date().isoformat()
    minimum_confidence = float(cfg["minimum_data_confidence"])
    max_price_age = int(val_cfg["max_price_age_days"])
    min_fresh = float(cfg["staleness"]["minimum_fundamental_freshness_score"])
    min_cov = float(cfg["valuation_comparison"]["minimum_common_metric_weight_coverage"])
    top = int(cfg["output"]["top_metric_differences"])
    metric_names = set(val_cfg["metrics"])

    known_peers = {p for u in universes.values() for p in (u.get("peers") or [])}
    market_path = latest_market_file(root, as_of)
    market = json.loads(market_path.read_text(encoding="utf-8")) if market_path else {}
    peers_path = latest_market_peers_file(root, as_of)
    market_peers: dict[str, Any] = {}
    if peers_path is not None:
        market_peers = json.loads(peers_path.read_text(encoding="utf-8"))
        validate_market_peers_file(market_peers, known_peers, metric_names, peers_path)
    fq_path, fq_snapshot = _fundamental_quality(root)
    confidence_path, confidence = load_target_confidence(root)
    peer_index = json.loads((root / "data/peers/index.json").read_text(encoding="utf-8"))["datasets"]
    prev_path, prev = previous_run(root, as_of)

    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731
    alerts: list[dict[str, Any]] = []
    evaluations: dict[str, Any] = {}
    input_hashes: dict[str, str] = {}

    for ticker, position in repo_cfg["portfolio"]["positions"].items():
        company_type = position["company_type"]
        dataset_path = root / peer_index[ticker]
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        input_hashes[rel(dataset_path)] = sha256_file(dataset_path)
        ref_path, refs = load_references(root, ticker, metric_names)
        if ref_path is not None:
            input_hashes[rel(ref_path)] = sha256_file(ref_path)
        peer_refs = {m: r["peers"] for m, r in refs.items() if ((r or {}).get("peers") or {}).get("value") is not None}

        published = (fq_snapshot.get("scores") or {}).get(ticker)
        position_fq = published["fundamental_quality_score"] if published else None
        pos_conf = confidence.get(ticker, {})
        pos_entry = (market.get("tickers") or {}).get(ticker)
        pos_val = company_valuation_metrics(entry=pos_entry, company_type=company_type, peer_refs=peer_refs,
                                            cfg=val_cfg)
        pos_age = market_age_days(pos_val, as_of)
        pos_stale = [w for w in pos_conf.get("raw_warnings", []) if w.startswith("STALE_DATA")]
        if pos_age is not None and pos_age > max_price_age:
            pos_stale.append(f"STALE_DATA:position_market:{pos_age}d")

        peers_out: dict[str, Any] = {}
        for peer in candidate_peers(dataset, list(universes.get(ticker, {}).get("peers") or [])):
            quality = score_peer(dataset=dataset, peer=peer, company_type=company_type, repo_config=repo_cfg)
            peer_fq = quality.score if quality.status == "DISPLAY_READY" else None
            peer_company = dataset["companies"][peer]
            period_end = peer_company.get("period_end")
            freshness = (
                freshness_score(as_of=date.fromisoformat(as_of), source_date=date.fromisoformat(str(period_end)),
                                bands=confidence_cfg["freshness"])
                if period_end else None
            )
            peer_entry = (market_peers.get("tickers") or {}).get(peer)
            peer_val = company_valuation_metrics(entry=peer_entry, company_type=company_type,
                                                 peer_refs=peer_refs, cfg=val_cfg)
            peer_age = market_age_days(peer_val, as_of)
            pair = pair_valuation(pos_val, peer_val, min_cov)

            reasons: list[str] = []
            if pos_conf.get("data_confidence") is None or pos_conf["data_confidence"] < minimum_confidence:
                reasons.append("POSITION_DATA_CONFIDENCE_BELOW_MINIMUM")
            if quality.data_confidence is None or quality.data_confidence < minimum_confidence:
                reasons.append("PEER_DATA_CONFIDENCE_BELOW_MINIMUM")
            reasons += pos_stale
            if freshness is None or freshness < min_fresh:
                reasons.append(f"STALE_DATA:peer_fundamentals:{period_end}")
            if peer_age is not None and peer_age > max_price_age:
                reasons.append(f"STALE_DATA:peer_market:{peer_age}d")
            if peer_entry is None:
                reasons.append("NO_PEER_MARKET_DATA")
            if pair is None:
                reasons.append("NO_VALUATION_COMPARISON")
            if position_fq is not None and peer_fq is None:
                reasons.append("PEER_FUNDAMENTAL_QUALITY_INSUFFICIENT")

            alert_type, basis = (None, BASIS_FULL if position_fq is not None else BASIS_VALUATION_ONLY)
            if pair is not None:
                alert_type, basis = classify(position_fq=position_fq, peer_fq=peer_fq,
                                             position_valuation=pair["position_score"],
                                             peer_valuation=pair["peer_score"], cfg=cfg)
            blocked = bool(reasons)
            outcome = alert_type if alert_type and not blocked else ("BLOCKED" if reasons else "NO_SIGNAL")
            peers_out[peer] = {
                "role": peer_company.get("role"),
                "fundamental_quality": _quality_summary(quality),
                "comparison_valuation": pair,
                "fundamentals_period_end": period_end,
                "fundamentals_freshness_score": freshness,
                "market_age_days": peer_age,
                "basis": basis,
                "outcome": outcome,
                "reasons": sorted(set(reasons)),
            }
            if alert_type and not blocked:
                alerts.append({
                    "position": ticker,
                    "peer": peer,
                    "type": alert_type,
                    "basis": basis,
                    "position_fundamental_quality": position_fq,
                    "peer_fundamental_quality": peer_fq,
                    "position_comparison_valuation": pair["position_score"],
                    "peer_comparison_valuation": pair["peer_score"],
                    "position_data_confidence": pos_conf.get("data_confidence"),
                    "peer_data_confidence": quality.data_confidence,
                    "top_metric_differences": metric_differences(
                        position_fq_metrics=_position_fq_metrics(published) if basis == BASIS_FULL else {},
                        peer_fq_metrics=quality.metrics if basis == BASIS_FULL else {},
                        position_val=pos_val, peer_val=peer_val, valuation_metrics=pair["metrics"], top=top,
                    ),
                    "sources": {
                        "peer_dataset": rel(dataset_path),
                        "peer_fundamentals": peer_company.get("source"),
                        "peer_median_reference": rel(ref_path) if ref_path else None,
                        "peer_median_methods": {m: peer_refs[m].get("method") for m in pair["metrics"]},
                        "position_market": rel(market_path) if market_path else None,
                        "peer_market": rel(peers_path) if peers_path else None,
                        "peer_market_datapoints": {m: peer_val[m].get("source") for m in pair["metrics"]},
                        "fundamental_quality_snapshot": rel(fq_path) if fq_path else None,
                    },
                    "execution_effect": "NONE",
                })
        evaluations[ticker] = {
            "company_type": company_type,
            "position_fundamental_quality": position_fq,
            "position_fundamental_quality_status": "DISPLAY_READY" if published else "DATA_CHECK",
            "position_data_confidence": pos_conf.get("data_confidence"),
            "position_market_age_days": pos_age,
            "peers": peers_out,
        }

    apply_persistence(alerts, prev, as_of, int(cfg["persistence"]["required_consecutive_runs"]))
    alerts.sort(key=lambda a: (a["status"] != ACTIVE, a["position"], a["peer"]))

    config_hash, config_hashes = bundle_hash(root, CONFIG_FILES)
    code_hash, code_hashes = bundle_hash(root, CODE_FILES)
    files = {
        "market": market_path, "market_peers": peers_path, "fundamental_quality": fq_path,
        "target_confidence": confidence_path, "previous_run": prev_path,
    }
    file_info = {k: ({"path": rel(p), "sha256": sha256_file(p)} if p else None) for k, p in files.items()}
    reproducibility_hash = sha256_json({"as_of": as_of, "config_hash": config_hash, "code_hash": code_hash,
                                        "files": file_info, "inputs": input_hashes})
    payload = {
        "schema_version": 1,
        "pipeline_version": PIPELINE_VERSION,
        "axis": "PEER_ALTERNATIVES",
        "as_of": as_of,
        "reproducibility_hash": reproducibility_hash,
        "methodology": {
            "fundamental_quality": "peer as target of the position's peer dataset; same gates as scoring/pipeline.py",
            "valuation": "position and peer scored against the same peer median, on common metrics only",
            "rules": cfg["rules"],
            "minimum_data_confidence": minimum_confidence,
            "valuation_only": cfg["valuation_only"],
            "persistence": cfg["persistence"],
            "max_price_age_days": max_price_age,
        },
        "provenance": {
            "run_git_commit": code_version or git_head(root),
            "code_hash": code_hash,
            "config_hash": config_hash,
            "code_files": code_hashes,
            "config_files": config_hashes,
            "files": file_info,
            "inputs": input_hashes,
        },
        "summary": {
            "alerts": len(alerts),
            ACTIVE: sum(a["status"] == ACTIVE for a in alerts),
            CANDIDATE: sum(a["status"] == CANDIDATE for a in alerts),
            "peers_evaluated": sum(len(e["peers"]) for e in evaluations.values()),
            "peers_with_fundamental_quality": sum(
                p["fundamental_quality"]["status"] == "DISPLAY_READY"
                for e in evaluations.values() for p in e["peers"].values()
            ),
            "peers_with_market_data": len(market_peers.get("tickers") or {}),
        },
        "alerts": alerts,
        "evaluations": evaluations,
        "execution_effect": "NONE",
    }
    _assert_no_order_fields(payload)
    return payload


def write_peer_alternatives_snapshot(root: Path, payload: dict[str, Any]) -> Path:
    output_dir = root / OUTPUT_DIR
    path = write_immutable_snapshot(payload=payload, output_dir=output_dir, prefix=PREFIX)
    update_current_pointer(root=root, snapshot_path=path, payload=payload, output_dir=output_dir,
                           pointer_key=POINTER_KEY)
    return path


def read_current_alerts(root: Path) -> dict[str, Any] | None:
    found = read_current(root, root / OUTPUT_DIR, POINTER_KEY)
    return found[1] if found else None


def _repo_root_from_module() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Flag peers that are fundamentally stronger and/or cheaper than a position. "
            "Analysis only: never edits portfolio.yaml or positions.yaml and never places orders."
        )
    )
    parser.add_argument("--root", type=Path, default=_repo_root_from_module())
    parser.add_argument("--as-of", help="ISO date; default is today (UTC)")
    parser.add_argument("--code-version")
    parser.add_argument("--write", action="store_true", help="write an immutable revision to data/alerts/")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    payload = build_peer_alternatives_snapshot(root=root, as_of=args.as_of, code_version=args.code_version)
    if not args.write:
        print(canonical_json(payload), end="")
        return 0
    print(write_peer_alternatives_snapshot(root, payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
