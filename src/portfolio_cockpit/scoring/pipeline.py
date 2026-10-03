from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .normalization import calculate_fundamental_quality
from .peer_confidence import peer_metric_confidence
from .peer_data import EligibleMetricSet, eligible_metric_set
from .readiness import evaluate_readiness


CONFIG_FILES = (
    "config/portfolio.yaml",
    "config/company_types.yaml",
    "config/readiness.yaml",
    "config/scoring.yaml",
    "config/score_metrics.yaml",
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
    aliases: dict[str, list[str]],
    directions: dict[str, str],
    minimum_peers: int,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    selected: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for component in component_weights:
        chosen: tuple[str, EligibleMetricSet] | None = None
        for metric_name in aliases.get(component, []):
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

        selected[component] = {
            "metric_name": metric_name,
            "direction": direction,
            "component_weight": float(component_weights[component]),
            "comparison_class": metric_set.comparison_class,
            "target_value": metric_set.target_value,
            "peer_values": list(metric_set.peer_values),
            "peer_tickers": list(metric_set.peer_tickers),
        }

    return selected, warnings


def _peer_set_overlap_warning(selected: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    peer_sets = [set(v["peer_tickers"]) for v in selected.values() if v["peer_tickers"]]
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
) -> Any | None:
    if not selected:
        return None

    target_metrics: dict[str, float] = {}
    peer_metrics: dict[str, list[float]] = {}
    peer_labels: dict[str, list[str]] = {}
    directions: dict[str, str] = {}
    weights: dict[str, float] = {}

    for item in selected.values():
        metric = item["metric_name"]
        target_metrics[metric] = float(item["target_value"])
        peer_metrics[metric] = list(item["peer_values"])
        peer_labels[metric] = list(item["peer_tickers"])
        directions[metric] = item["direction"]
        weights[metric] = float(item["component_weight"])

    return calculate_fundamental_quality(
        target_metrics=target_metrics,
        peer_metrics=peer_metrics,
        peer_labels=peer_labels,
        metric_directions=directions,
        metric_weights=weights,
        min_metric_coverage=0.0,
        clip_z=clip_z,
        minimum_peer_values=minimum_peers,
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
    for component, item in selected.items():
        metric = item["metric_name"]
        score = by_name.get(metric)
        result[component] = {
            **item,
            "peer_input_confidence": peer_confidences.get(metric),
        }
        if score is not None:
            result[component].update(
                {
                    "peer_mean": score.peer_mean,
                    "peer_sample_std": score.peer_std,
                    "unclipped_z_score": score.unclipped_z_score,
                    "clipped_z_score": score.z_score,
                }
            )
    return result


def build_score_snapshot(
    *,
    root: Path,
    code_version: str | None = None,
    confidence_path: Path | None = None,
) -> dict[str, Any]:
    portfolio = _read_yaml(root / "config/portfolio.yaml")
    company_types = _read_yaml(root / "config/company_types.yaml")
    readiness_cfg = _read_yaml(root / "config/readiness.yaml")
    scoring_cfg = _read_yaml(root / "config/scoring.yaml")
    metric_cfg = _read_yaml(root / "config/score_metrics.yaml")
    peer_index_path = root / "data/peers/index.json"
    peer_index = _read_json(peer_index_path)

    confidence_path = confidence_path or _latest_confidence_path(root)
    confidence = _read_json(confidence_path)

    fq_cfg = scoring_cfg["fundamental_quality"]
    confidence_threshold = float(scoring_cfg["data_confidence"]["decision_threshold"])
    minimum_peers = int(fq_cfg["minimum_peer_values_per_metric"])
    minimum_coverage = float(fq_cfg["minimum_metric_coverage"])
    clip_z = float(fq_cfg["clip_z_score"])
    stable_width = float(fq_cfg["sensitivity"]["stable_band_width_points"])
    hard_tokens = list(readiness_cfg["hard_block_status_contains"])

    config_hash, config_hashes = _bundle_hash(root, CONFIG_FILES)
    code_version = code_version or _git_head(root)

    scores: dict[str, Any] = {}
    blocked: dict[str, Any] = {}

    for ticker, position in portfolio["positions"].items():
        dataset_relative = peer_index["datasets"][ticker]
        dataset_path = root / dataset_relative
        dataset = _read_json(dataset_path)
        company_type = position["company_type"]
        type_cfg = company_types[company_type]
        component_weights = {
            k: float(v) for k, v in type_cfg["quality_components"].items()
        }
        required_components = tuple(type_cfg.get("required_components", ()))
        aliases = readiness_cfg["component_metric_aliases"][company_type]
        directions = metric_cfg["metric_directions"][company_type]

        selected, selection_warnings = _select_component_metrics(
            dataset=dataset,
            company_type=company_type,
            component_weights=component_weights,
            aliases=aliases,
            directions=directions,
            minimum_peers=minimum_peers,
        )

        peer_confidences: dict[str, float] = {}
        peer_confidence_warnings: list[str] = []
        for item in selected.values():
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
            if peer_confidences and len(peer_confidences) == len(selected)
            else None
        )

        candidate = _candidate_score(
            selected=selected,
            clip_z=clip_z,
            minimum_peers=minimum_peers,
        )
        stability_flag = (
            candidate.sensitivity.stability_flag
            if candidate is not None and candidate.sensitivity is not None
            else None
        )

        # Enforce the configured stability threshold in one place even if the
        # lower-level helper's default is changed later.
        if candidate is not None and candidate.sensitivity is not None:
            width = candidate.sensitivity.score_high - candidate.sensitivity.score_low
            stability_flag = "STABLE" if width < stable_width else "PEER_SENSITIVE"

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
        )

        overlap_warning = _peer_set_overlap_warning(selected)
        warnings = list(readiness.warnings) + selection_warnings + peer_confidence_warnings
        if overlap_warning:
            warnings.append(overlap_warning["code"])

        provenance = {
            "peer_dataset": {
                "path": dataset_relative,
                "sha256": _sha256(dataset_path),
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

        if readiness.production_ready and candidate is not None:
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

    return {
        "schema_version": 3,
        "pipeline_version": 1,
        "as_of": confidence["as_of"],
        "methodology": {
            "peer_method": fq_cfg["peer_method"],
            "score_formula": fq_cfg["score_formula"],
            "minimum_peer_values_per_metric": minimum_peers,
            "minimum_weighted_component_coverage": minimum_coverage,
            "required_components_enforced": True,
            "sensitivity_method": fq_cfg["sensitivity"]["method"],
            "stable_band_width_points": stable_width,
            "data_confidence_threshold": confidence_threshold,
            "peer_input_confidence_threshold": confidence_threshold,
        },
        "provenance": {
            "code_version": code_version,
            "config_hash": config_hash,
            "config_files": {
                path: {"sha256": sha}
                for path, sha in config_hashes.items()
            },
            "peer_index": {
                "path": "data/peers/index.json",
                "sha256": _sha256(peer_index_path),
            },
            "target_confidence": {
                "path": str(confidence_path.relative_to(root)),
                "sha256": _sha256(confidence_path),
            },
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
    current = {
        "schema_version": 2,
        "as_of": payload["as_of"],
        "current_fundamental_quality": str(snapshot_path.relative_to(root)),
        "generated_by_pipeline": True,
        "pipeline_version": payload["pipeline_version"],
        "code_version": payload["provenance"]["code_version"],
        "config_hash": payload["provenance"]["config_hash"],
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
