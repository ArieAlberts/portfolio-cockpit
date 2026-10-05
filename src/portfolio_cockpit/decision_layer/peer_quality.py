"""Fundamental Quality for a peer, scored exactly like a portfolio position.

The peer is made the target of the existing peer dataset
(``data/peers/<position>/...``); every other company in that dataset, the
current position included, becomes the reference group. Selection, slots,
aliases, normalization, the >= N peer values per metric rule, required
components, peer-input confidence, sensitivity and calculation validation are
the building blocks of ``scoring/pipeline.py``, imported and never modified,
so the Fundamental Quality hash scope stays untouched.

Two adaptations, both needed because the peer is not a portfolio position:

* the position takes the peer's role in the swapped dataset (if SOP.PA is a
  PEER of CAP.PA, CAP.PA is a PEER of SOP.PA), instead of keeping the
  role ``TARGET``;
* the target data confidence of a peer comes from its own datapoints in the
  dataset, using the peer-input confidence formula of
  ``scoring/peer_confidence.py`` (minimum over its score-eligible metrics).
  A position keeps its confidence from ``data/confidence/<date>.json``.

Analytical only: nothing here writes a Fundamental Quality snapshot.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from portfolio_cockpit.config import component_metric_aliases, component_metric_slots, metric_directions
from portfolio_cockpit.scoring.calculation_validation import validate_dataset_calculations
from portfolio_cockpit.scoring.peer_confidence import peer_metric_confidence
from portfolio_cockpit.scoring.pipeline import (
    _candidate_score,
    _select_component_metrics,
    _selected_metric_items,
)
from portfolio_cockpit.scoring.readiness import evaluate_readiness

EXCLUDED_ROLES = frozenset({"GATE", "CONTEXT_ONLY"})
SELF_KEY = "__SELF__"


@dataclass(frozen=True)
class QualityResult:
    ticker: str
    status: str  # DISPLAY_READY | INSUFFICIENT
    score: float | None
    diagnostic_score: float | None
    stability_flag: str | None
    data_confidence: float | None
    warnings: tuple[str, ...]
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)


def peer_datapoint_confidence(dataset: dict[str, Any], ticker: str) -> float | None:
    """Minimum peer-input confidence over the company's own score-eligible datapoints.

    Reuses ``peer_metric_confidence`` on a two-company dataset in which a stub
    target mirrors the company's metric, so the formula is never duplicated.
    """
    company = dataset["companies"][ticker]
    scores: list[float] = []
    for name, metric in sorted((company.get("metrics") or {}).items()):
        if not metric.get("score_eligible") or metric.get("value") is None:
            continue
        stub = {
            "target_ticker": SELF_KEY,
            "rules": {},
            "companies": {
                SELF_KEY: {"period_alignment": company.get("period_alignment"), "metrics": {name: metric}},
                ticker: company,
            },
        }
        try:
            scores.append(peer_metric_confidence(dataset=stub, metric_name=name, minimum_peer_values=1).score)
        except (KeyError, ValueError):
            continue
    return min(scores) if scores else None


def candidate_peers(dataset: dict[str, Any], universe_peers: list[str]) -> list[str]:
    """Universe peers that exist in the dataset with a role that may be scored."""
    companies = dataset.get("companies", {})
    return [
        t for t in universe_peers
        if t in companies and t != dataset["target_ticker"] and companies[t].get("role") not in EXCLUDED_ROLES
    ]


def swap_target(dataset: dict[str, Any], peer: str) -> dict[str, Any]:
    """Copy of the dataset with ``peer`` as target; the position takes the peer's role."""
    swapped = copy.deepcopy(dataset)
    position = dataset["target_ticker"]
    swapped["target_ticker"] = peer
    swapped["companies"][position]["role"] = dataset["companies"][peer].get("role", "PEER")
    return swapped


def score_target(
    *,
    dataset: dict[str, Any],
    company_type: str,
    repo_config: dict[str, Any],
    target_data_confidence: float | None,
) -> QualityResult:
    """Score ``dataset['target_ticker']`` with the gates of ``scoring/pipeline.py``."""
    scoring_cfg = repo_config["scoring"]
    readiness_cfg = repo_config["readiness"]
    type_cfg = repo_config["company_types"][company_type]
    fq_cfg = scoring_cfg["fundamental_quality"]
    threshold = float(scoring_cfg["data_confidence"]["decision_threshold"])
    minimum_peers = int(fq_cfg["minimum_peer_values_per_metric"])
    calculation_cfg = scoring_cfg["calculation_validation"]

    calculation = validate_dataset_calculations(
        dataset=dataset,
        absolute_tolerance=float(calculation_cfg["absolute_tolerance"]),
        relative_tolerance=float(calculation_cfg["relative_tolerance"]),
    )
    rules = dataset.get("rules", {})
    dataset_min_peers = rules.get("minimum_peer_values_per_metric", rules.get("min_peer_values_per_metric"))
    rule_consistent = dataset_min_peers is None or int(dataset_min_peers) == minimum_peers

    component_weights = {k: float(v) for k, v in type_cfg["quality_components"].items()}
    selected, selection_warnings = _select_component_metrics(
        dataset=dataset,
        company_type=company_type,
        component_weights=component_weights,
        slots=component_metric_slots(repo_config, company_type),
        directions=metric_directions(repo_config, company_type),
        minimum_peers=minimum_peers,
        minimum_component_metric_weight_coverage=float(fq_cfg["minimum_component_metric_weight_coverage"]),
    )
    items = _selected_metric_items(selected)
    peer_confidences: dict[str, float] = {}
    for item in items:
        try:
            peer_confidences[item["metric_name"]] = peer_metric_confidence(
                dataset=dataset, metric_name=item["metric_name"], minimum_peer_values=minimum_peers
            ).score
        except (KeyError, ValueError):
            pass
    overall_peer_confidence = (
        min(peer_confidences.values()) if peer_confidences and len(peer_confidences) == len(items) else None
    )
    candidate = _candidate_score(
        selected=selected,
        clip_z=float(fq_cfg["clip_z_score"]),
        minimum_peers=minimum_peers,
        stable_width=float(fq_cfg["sensitivity"]["stable_band_width_points"]),
        unstable_width=float(fq_cfg["sensitivity"]["unstable_band_width_points"]),
    )
    stability = (
        candidate.sensitivity.stability_flag
        if candidate is not None and candidate.sensitivity is not None
        else None
    )
    readiness = evaluate_readiness(
        dataset=dataset,
        company_type=company_type,
        component_weights=component_weights,
        component_metric_aliases=component_metric_aliases(repo_config, company_type),
        required_components=tuple(type_cfg.get("required_components", ())),
        minimum_peer_values_per_metric=minimum_peers,
        minimum_weighted_component_coverage=float(fq_cfg["minimum_metric_coverage"]),
        hard_block_status_contains=tuple(readiness_cfg["hard_block_status_contains"]),
        data_confidence_score=target_data_confidence,
        data_confidence_threshold=threshold,
        peer_input_confidence_score=overall_peer_confidence,
        peer_input_confidence_threshold=threshold,
        stability_flag=stability,
        covered_components_override=tuple(selected),
        ready_metrics_override=tuple(item["metric_name"] for item in items),
    )
    warnings = list(readiness.warnings) + selection_warnings
    if not rule_consistent:
        warnings.append(f"DATASET_MIN_PEERS_MISMATCH:{dataset_min_peers}!={minimum_peers}")
    for issue in calculation["blocking_issues"]:
        warnings.append(f"CALCULATION_MISMATCH:{issue['ticker']}:{issue['metric_name']}")

    by_name = {m.metric_name: m for m in (candidate.metric_scores if candidate is not None else ())}
    metrics = {
        item["metric_name"]: {
            "slot": item["slot_name"],
            "value": item["target_value"],
            "direction": item["direction"],
            "clipped_z_score": by_name[item["metric_name"]].z_score if item["metric_name"] in by_name else None,
            "reference_tickers": list(item["peer_tickers"]),
        }
        for item in items
    }
    ready = (
        readiness.production_ready
        and rule_consistent
        and bool(calculation["integrity_pass"])
        and candidate is not None
    )
    return QualityResult(
        ticker=dataset["target_ticker"],
        status="DISPLAY_READY" if ready else "INSUFFICIENT",
        score=candidate.score if ready else None,
        diagnostic_score=candidate.score if candidate is not None else None,
        stability_flag=stability,
        data_confidence=target_data_confidence,
        warnings=tuple(sorted(set(warnings))),
        metrics=metrics,
    )


def score_peer(
    *,
    dataset: dict[str, Any],
    peer: str,
    company_type: str,
    repo_config: dict[str, Any],
) -> QualityResult:
    swapped = swap_target(dataset, peer)
    return score_target(
        dataset=swapped,
        company_type=company_type,
        repo_config=repo_config,
        target_data_confidence=peer_datapoint_confidence(dataset, peer),
    )
