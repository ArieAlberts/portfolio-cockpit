from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from portfolio_cockpit.config import (
    component_metric_aliases,
    component_metric_slots,
    load_config,
    metric_directions,
)

from .normalization import calculate_fundamental_quality
from .peer_confidence import peer_metric_confidence
from .peer_data import EligibleMetricSet, eligible_metric_set
from .readiness import evaluate_readiness


# Peer-universe config is hashed because validation can block a scoring build.
CONFIG_FILES = (
    "config/portfolio.yaml",
    "config/company_types.yaml",
    "config/readiness.yaml",
    "config/scoring.yaml",
    "config/score_metrics.yaml",
    "config/peer_universes.yaml",
)

CODE_FILES = (
    "src/portfolio_cockpit/config.py",
    "src/portfolio_cockpit/scoring/pipeline.py",
    "src/portfolio_cockpit/scoring/normalization.py",
    "src/portfolio_cockpit/scoring/peer_data.py",
    "src/portfolio_cockpit/scoring/peer_confidence.py",
    "src/portfolio_cockpit/scoring/readiness.py",
    "src/portfolio_cockpit/scoring/quality.py",
)


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle_hash(root: Path, relative_paths: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    hashes = {p: _sha256(root / p) for p in relative_paths}
    canonical = json.dumps(hashes, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), hashes


def _git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "UNKNOWN"


def _latest_confidence_path(root: Path) -> Path:
    candidates = sorted(
        p for p in (root / "data/confidence").glob("????-??-??.json")
        if p.is_file()
    )
    if not candidates:
        raise FileNotFoundError("No dated target-confidence snapshot found.")
    return candidates[-1]


def _hard_blocked(status: str, tokens: list[str]) -> bool:
    return any(token in status for token in tokens)


def _select_component_metrics(
    *,
    dataset: dict[str, Any],
    company_type: str,
    component_weights: dict[str, float],
    slots: dict[str, dict[str, dict[str, Any]]],
    directions: dict[str, str],
    minimum_peers: int,
    minimum_component_metric_weight_coverage: float,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    selected: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for component, component_weight in component_weights.items():
        chosen_metrics: list[dict[str, Any]] = []
        covered_slot_weight = 0.0

        for slot_name, slot_cfg in slots.get(component, {}).items():
            slot_weight = float(slot_cfg["weight"])
            chosen: tuple[str, EligibleMetricSet] | None = None

            for metric_name in slot_cfg.get("aliases", ()):
                metric_set = eligible_metric_set(
                    dataset,
                    metric_name,
                    min_peers=minimum_peers,
                )
                if metric_set.status == "READY":
                    chosen = (metric_name, metric_set)
                    break

            if chosen is None:
                continue

            metric_name, metric_set = chosen
            direction = directions.get(metric_name)
            if direction not in {"higher_is_better", "lower_is_better"}:
                warnings.append(f"MISSING_DIRECTION:{company_type}:{metric_name}")
                continue

            covered_slot_weight += slot_weight
            chosen_metrics.append(
                {
                    "slot_name": slot_name,
                    "metric_name": metric_name,
                    "direction": direction,
                    "configured_metric_weight": slot_weight,
                    "comparison_class": metric_set.comparison_class,
                    "target_value": metric_set.target_value,
                    "peer_values": list(metric_set.peer_values),
                    "peer_tickers": list(metric_set.peer_tickers),
                }
            )

        if covered_slot_weight + 1e-12 < minimum_component_metric_weight_coverage:
            if chosen_metrics:
                warnings.append(
                    "COMPONENT_METRIC_COVERAGE_BELOW_THRESHOLD:"
                    f"{company_type}:{component}:{covered_slot_weight:.6f}"
                )
            continue

        for item in chosen_metrics:
            normalized = float(item["configured_metric_weight"]) / covered_slot_weight
            item["effective_metric_weight_within_component"] = normalized
            item["effective_component_weight"] = float(component_weight) * normalized

        selected[component] = {
            "component_weight": float(component_weight),
            "metric_weight_coverage": covered_slot_weight,
            "minimum_metric_weight_coverage": minimum_component_metric_weight_coverage,
            "metrics": chosen_metrics,
        }

    return selected, warnings


def _selected_metric_items(
    selected: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        metric
        for component in selected.values()
        for metric in component.get("metrics", ())
    ]


def _peer_set_overlap_warning(selected: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    metric_items = _selected_metric_items(selected)
    peer_sets = [set(v["peer_tickers"]) for v in metric_items if v["peer_tickers"]]
    if len(peer_sets) < 2:
        return None
    union = set().union(*peer_sets)
    intersection = set.intersection(*peer_sets)
    if not union:
        return None
    overlap = len(intersection) / len(union)
    if overlap >= 0.75:
        return None
    return {
        "code": "PEER_SET_VARIES_BY_METRIC",
        "intersection_over_union": round(overlap, 6),
        "common_peers": sorted(intersection),
        "all_used_peers": sorted(union),
    }


def _candidate_score(
    *,
    selected: dict[str, dict[str, Any]],
    clip_z: float,
    minimum_peers: int,
    stable_width: float,
    unstable_width: float,
) -> Any | None:
    metric_items = _selected_metric_items(selected)
    if not metric_items:
        return None

    target_metrics: dict[str, float] = {}
    peer_metrics: dict[str, list[float]] = {}
    peer_labels: dict[str, list[str]] = {}
    directions: dict[str, str] = {}
    weights: dict[str, float] = {}

    for item in metric_items:
        metric = item["metric_name"]
        target_metrics[metric] = float(item["target_value"])
        peer_metrics[metric] = list(item["peer_values"])
        peer_labels[metric] = list(item["peer_tickers"])
        directions[metric] = item["direction"]
        weights[metric] = float(item["effective_component_weight"])

    return calculate_fundamental_quality(
        target_metrics=target_metrics,
        peer_metrics=peer_metrics,
        peer_labels=peer_labels,
        metric_directions=directions,
        metric_weights=weights,
        min_metric_coverage=0.0,
        clip_z=clip_z,
        minimum_peer_values=minimum_peers,
        stable_band_width_points=stable_width,
        unstable_band_width_points=unstable_width,
    )


def _metric_output(
    selected: dict[str, dict[str, Any]],
    candidate: Any | None,
    peer_confidences: dict[str, float],
) -> dict[str, Any]:
    by_name = {
        score.metric_name: score
        for score in (candidate.metric_scores if candidate is not None else ())
    }
    result: dict[str, Any] = {}

    for component, component_item in selected.items():
        component_output = {
            "component_weight": component_item["component_weight"],
            "metric_weight_coverage": component_item["metric_weight_coverage"],
            "minimum_metric_weight_coverage": component_item[
                "minimum_metric_weight_coverage"
            ],
            "metrics": {},
        }

        for item in component_item["metrics"]:
            metric = item["metric_name"]
            score = by_name.get(metric)
            metric_output = {
                **item,
                "peer_input_confidence": peer_confidences.get(metric),
            }
            if score is not None:
                metric_output.update(
                    {
                        "peer_mean": score.peer_mean,
                        "peer_sample_std": score.peer_std,
                        "unclipped_z_score": score.unclipped_z_score,
                        "clipped_z_score": score.z_score,
                    }
                )
            component_output["metrics"][item["slot_name"]] = metric_output

        result[component] = component_output

    return result

def build_score_snapshot(
    *,
    root: Path,
    code_version: str | None = None,
    confidence_path: Path | None = None,
) -> dict[str, Any]:
    config = load_config(root)
    portfolio = config["portfolio"]
    company_types = config["company_types"]
    readiness_cfg = config["readiness"]
    scoring_cfg = config["scoring"]
    peer_index_path = root / "data/peers/index.json"
    peer_index = _read_json(peer_index_path)

    confidence_path = confidence_path or _latest_confidence_path(root)
    confidence = _read_json(confidence_path)

    fq_cfg = scoring_cfg["fundamental_quality"]
    confidence_threshold = float(scoring_cfg["data_confidence"]["decision_threshold"])
    minimum_peers = int(fq_cfg["minimum_peer_values_per_metric"])
    minimum_coverage = float(fq_cfg["minimum_metric_coverage"])
    minimum_component_metric_coverage = float(
        fq_cfg["minimum_component_metric_weight_coverage"]
    )
    clip_z = float(fq_cfg["clip_z_score"])
    stable_width = float(fq_cfg["sensitivity"]["stable_band_width_points"])
    unstable_width = float(fq_cfg["sensitivity"]["unstable_band_width_points"])
    hard_tokens = list(readiness_cfg["hard_block_status_contains"])

    config_hash, config_hashes = _bundle_hash(root, CONFIG_FILES)
    code_hash, code_hashes = _bundle_hash(root, CODE_FILES)
    code_version = code_version or _git_head(root)

    scores: dict[str, Any] = {}
    blocked: dict[str, Any] = {}
    peer_dataset_hashes: dict[str, str] = {}

    for ticker, position in portfolio["positions"].items():
        dataset_relative = peer_index["datasets"][ticker]
        dataset_path = root / dataset_relative
        dataset = _read_json(dataset_path)
        dataset_hash = _sha256(dataset_path)
        peer_dataset_hashes[ticker] = dataset_hash
        dataset_rules = dataset.get("rules", {})
        dataset_min_peers = dataset_rules.get(
            "minimum_peer_values_per_metric",
            dataset_rules.get("min_peer_values_per_metric"),
        )
        dataset_rule_consistent = (
            dataset_min_peers is None or int(dataset_min_peers) == minimum_peers
        )
        company_type = position["company_type"]
        type_cfg = company_types[company_type]
        component_weights = {
            k: float(v) for k, v in type_cfg["quality_components"].items()
        }
        required_components = tuple(type_cfg.get("required_components", ()))
        aliases = component_metric_aliases(config, company_type)
        slots = component_metric_slots(config, company_type)
        directions = metric_directions(config, company_type)

        selected, selection_warnings = _select_component_metrics(
            dataset=dataset,
            company_type=company_type,
            component_weights=component_weights,
            slots=slots,
            directions=directions,
            minimum_peers=minimum_peers,
            minimum_component_metric_weight_coverage=minimum_component_metric_coverage,
        )

        peer_confidences: dict[str, float] = {}
        peer_confidence_warnings: list[str] = []
        selected_metric_items = _selected_metric_items(selected)
        for item in selected_metric_items:
            metric = item["metric_name"]
            try:
                c = peer_metric_confidence(
                    dataset=dataset,
                    metric_name=metric,
                    minimum_peer_values=minimum_peers,
                )
                peer_confidences[metric] = c.score
            except (KeyError, ValueError) as exc:
                peer_confidence_warnings.append(
                    f"PEER_INPUT_CONFIDENCE_ERROR:{metric}:{exc}"
                )

        overall_peer_confidence = (
            min(peer_confidences.values())
            if peer_confidences
            and len(peer_confidences) == len(selected_metric_items)
            else None
        )

        candidate = _candidate_score(
            selected=selected,
            clip_z=clip_z,
            minimum_peers=minimum_peers,
            stable_width=stable_width,
            unstable_width=unstable_width,
        )
        stability_flag = (
            candidate.sensitivity.stability_flag
            if candidate is not None and candidate.sensitivity is not None
            else None
        )

        target_confidence = confidence.get("results", {}).get(ticker, {}).get(
            "data_confidence_score"
        )

        readiness = evaluate_readiness(
            dataset=dataset,
            company_type=company_type,
            component_weights=component_weights,
            component_metric_aliases=aliases,
            required_components=required_components,
            minimum_peer_values_per_metric=minimum_peers,
            minimum_weighted_component_coverage=minimum_coverage,
            hard_block_status_contains=tuple(hard_tokens),
            data_confidence_score=target_confidence,
            data_confidence_threshold=confidence_threshold,
            peer_input_confidence_score=overall_peer_confidence,
            peer_input_confidence_threshold=confidence_threshold,
            stability_flag=stability_flag,
            covered_components_override=tuple(selected),
            ready_metrics_override=tuple(
                item["metric_name"] for item in selected_metric_items
            ),
        )

        overlap_warning = _peer_set_overlap_warning(selected)
        warnings = list(readiness.warnings) + selection_warnings + peer_confidence_warnings
        if overlap_warning:
            warnings.append(overlap_warning["code"])
        if not dataset_rule_consistent:
            warnings.append(
                f"DATASET_MIN_PEERS_MISMATCH:{dataset_min_peers}!={minimum_peers}"
            )

        provenance = {
            "peer_dataset": {
                "path": dataset_relative,
                "sha256": dataset_hash,
            },
            "target_confidence": {
                "path": str(confidence_path.relative_to(root)),
                "sha256": _sha256(confidence_path),
            },
            "code_version": code_version,
            "config_hash": config_hash,
        }

        base = {
            "company_type": company_type,
            "peer_reference_period": dataset.get("strict_reference_period"),
            "peer_universe_status": dataset.get("peer_universe_status"),
            "dataset_minimum_peer_values": dataset_min_peers,
            "dataset_rule_consistent": dataset_rule_consistent,
            "weighted_component_coverage": readiness.weighted_component_coverage,
            "covered_components": list(readiness.covered_components),
            "missing_required_components": list(readiness.missing_required_components),
            "target_data_confidence": target_confidence,
            "peer_input_confidence": overall_peer_confidence,
            "selected_metrics": _metric_output(selected, candidate, peer_confidences),
            "peer_set_overlap": overlap_warning,
            "warnings": sorted(set(warnings)),
            "provenance": provenance,
            "execution_effect": "NONE",
        }

        if candidate is not None:
            base["diagnostic_candidate"] = {
                "score": candidate.score,
                "weighted_z": candidate.weighted_z,
                "sensitivity": (
                    asdict(candidate.sensitivity)
                    if candidate.sensitivity is not None
                    else None
                ),
                "normalization_warnings": list(candidate.warnings),
            }

        if readiness.production_ready and dataset_rule_consistent and candidate is not None:
            scores[ticker] = {
                **base,
                "status": "DISPLAY_READY",
                "fundamental_quality_score": candidate.score,
                "display_score": round(candidate.score, 1),
            }
        else:
            blocked[ticker] = {
                **base,
                "status": "DATA_CHECK",
                "production_ready": False,
            }

    peer_index_hash = _sha256(peer_index_path)
    confidence_hash = _sha256(confidence_path)
    reproducibility_material = {
        "pipeline_code_hash": code_hash,
        "config_hash": config_hash,
        "peer_index_hash": peer_index_hash,
        "target_confidence_hash": confidence_hash,
        "peer_dataset_hashes": peer_dataset_hashes,
    }
    reproducibility_hash = hashlib.sha256(
        json.dumps(
            reproducibility_material,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return {
        "schema_version": 4,
        "pipeline_version": 2,
        "as_of": confidence["as_of"],
        "reproducibility_hash": reproducibility_hash,
        "methodology": {
            "peer_method": fq_cfg["peer_method"],
            "score_formula": fq_cfg["score_formula"],
            "minimum_peer_values_per_metric": minimum_peers,
            "minimum_weighted_component_coverage": minimum_coverage,
            "minimum_component_metric_weight_coverage": minimum_component_metric_coverage,
            "metric_slot_weighting": True,
            "required_components_enforced": True,
            "dataset_rule_consistency_required": True,
            "sensitivity_method": fq_cfg["sensitivity"]["method"],
            "stable_band_width_points": stable_width,
            "unstable_band_width_points": unstable_width,
            "data_confidence_threshold": confidence_threshold,
            "peer_input_confidence_threshold": confidence_threshold,
        },
        "provenance": {
            "run_git_commit": code_version,
            "pipeline_code_hash": code_hash,
            "config_hash": config_hash,
            "code_files": {
                path: {"sha256": sha}
                for path, sha in code_hashes.items()
            },
            "config_files": {
                path: {"sha256": sha}
                for path, sha in config_hashes.items()
            },
            "peer_index": {
                "path": "data/peers/index.json",
                "sha256": peer_index_hash,
            },
            "target_confidence": {
                "path": str(confidence_path.relative_to(root)),
                "sha256": confidence_hash,
            },
            "peer_dataset_hashes": peer_dataset_hashes,
        },
        "summary": {
            "portfolio_companies": len(portfolio["positions"]),
            "display_ready": len(scores),
            "data_check": len(blocked),
        },
        "scores": scores,
        "blocked": blocked,
        "note": (
            "Generated deterministically from repository peer datasets and config. "
            "No score can trigger live execution."
        ),
    }


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_immutable_snapshot(
    *,
    root: Path,
    payload: dict[str, Any],
    output_dir: Path | None = None,
) -> Path:
    output_dir = output_dir or root / "data/scoring"
    output_dir.mkdir(parents=True, exist_ok=True)
    as_of = payload["as_of"]
    body = _canonical_json(payload)

    reproducibility_hash = payload.get("reproducibility_hash")
    if reproducibility_hash:
        for existing in sorted(output_dir.glob(f"fundamental_quality_{as_of}*.json")):
            try:
                existing_payload = json.loads(existing.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if existing_payload.get("reproducibility_hash") == reproducibility_hash:
                return existing

    base = output_dir / f"fundamental_quality_{as_of}.json"
    candidates = [base]
    revision = 2
    while True:
        path = candidates[-1]
        if not path.exists():
            path.write_text(body, encoding="utf-8")
            return path
        if path.read_text(encoding="utf-8") == body:
            return path
        candidates.append(output_dir / f"fundamental_quality_{as_of}_r{revision}.json")
        revision += 1


def update_current_pointer(
    *,
    root: Path,
    snapshot_path: Path,
    payload: dict[str, Any],
) -> None:
    # If write_immutable_snapshot reused an existing semantically identical
    # snapshot, anchor the pointer metadata to that immutable snapshot rather
    # than to the current workflow HEAD. This keeps no-op rebuilds byte-stable.
    snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    source = snapshot_payload if snapshot_payload.get("reproducibility_hash") else payload

    current = {
        "schema_version": 2,
        "as_of": source["as_of"],
        "current_fundamental_quality": str(snapshot_path.relative_to(root)),
        "generated_by_pipeline": True,
        "pipeline_version": source["pipeline_version"],
        "run_git_commit": source["provenance"]["run_git_commit"],
        "pipeline_code_hash": source["provenance"]["pipeline_code_hash"],
        "config_hash": source["provenance"]["config_hash"],
        "reproducibility_hash": source["reproducibility_hash"],
        "execution_effect": "NONE",
    }
    path = root / "data/scoring/current.json"
    path.write_text(_canonical_json(current), encoding="utf-8")


def _repo_root_from_module() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic Fundamental Quality snapshot from repository inputs."
    )
    parser.add_argument("--root", type=Path, default=_repo_root_from_module())
    parser.add_argument("--confidence", type=Path)
    parser.add_argument("--code-version")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    confidence_path = args.confidence
    if confidence_path is not None and not confidence_path.is_absolute():
        confidence_path = root / confidence_path

    payload = build_score_snapshot(
        root=root,
        code_version=args.code_version,
        confidence_path=confidence_path,
    )

    if not args.write:
        print(_canonical_json(payload), end="")
        return 0

    output_dir = args.output_dir
    if output_dir is not None and not output_dir.is_absolute():
        output_dir = root / output_dir
    path = write_immutable_snapshot(
        root=root,
        payload=payload,
        output_dir=output_dir,
    )
    if output_dir is None or output_dir.resolve() == (root / "data/scoring").resolve():
        update_current_pointer(root=root, snapshot_path=path, payload=payload)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
