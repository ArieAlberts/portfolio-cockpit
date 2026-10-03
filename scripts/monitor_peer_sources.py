#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from portfolio_cockpit.monitoring.peer_monitor import (
    build_peer_source_specs,
    fetch_sec_ticker_map,
    observe_peer_source,
)
from portfolio_cockpit.monitoring.source_monitor import iso_z, utc_now


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump_if_changed(path: Path, payload: dict) -> bool:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--peer-index", default="data/peers/index.json")
    parser.add_argument("--config", default="config/peer_monitoring.yaml")
    parser.add_argument("--state", default="data/monitoring/peer_source_state.json")
    parser.add_argument("--status", default="data/monitoring/peer_status.json")
    parser.add_argument("--target-status", default="data/monitoring/status.json")
    parser.add_argument("--events", default="data/peer_source_events")
    parser.add_argument("--fail-if-all-error", action="store_true")
    args = parser.parse_args()

    cfg = yaml.safe_load((ROOT / args.config).read_text(encoding="utf-8"))
    peer_index = json.loads((ROOT / args.peer_index).read_text(encoding="utf-8"))
    state_path = ROOT / args.state
    status_path = ROOT / args.status
    target_status_path = ROOT / args.target_status
    events_root = ROOT / args.events

    state = load_json(state_path, {"schema_version": 1, "sources": {}})
    status = load_json(status_path, {"schema_version": 1, "peers": {}, "targets": {}})
    target_status = load_json(target_status_path, {"schema_version": 1, "companies": {}})

    sec_map = {}
    sec_map_error = None
    if cfg["defaults"].get("resolve_sec_tickers", True):
        try:
            sec_map = fetch_sec_ticker_map(
                user_agent=cfg["defaults"]["user_agent"],
                timeout=int(cfg["defaults"]["timeout_seconds"]),
            )
        except Exception as exc:
            sec_map_error = f"{type(exc).__name__}: {exc}"

    specs = build_peer_source_specs(
        root=ROOT,
        peer_index=peer_index,
        sec_ticker_map=sec_map,
        discovery_overrides=cfg.get("discovery_overrides", {}),
    )

    now = utc_now()
    observed_at = iso_z(now)
    observations = 0
    errors = 0
    changes = 0

    for spec in specs:
        peer_status = status["peers"].setdefault(
            spec.peer_ticker,
            {
                "status": "NOT_YET_POLLED",
                "source_quality": spec.source_quality,
                "dependent_targets": list(spec.dependent_targets),
                "last_source_change_at": None,
                "last_event_path": None,
                "warnings": [],
            },
        )
        key = spec.peer_ticker

        try:
            observation = observe_peer_source(
                spec,
                user_agent=cfg["defaults"]["user_agent"],
                timeout=int(cfg["defaults"]["timeout_seconds"]),
            )
            observations += 1
        except Exception as exc:
            errors += 1
            peer_status["warnings"] = [f"{type(exc).__name__}: {exc}"]
            if peer_status["status"] == "NOT_YET_POLLED":
                peer_status["status"] = "SOURCE_ERROR"
            continue

        previous = state["sources"].get(key)
        current = {
            "peer_ticker": spec.peer_ticker,
            "mode": spec.mode,
            "url": spec.url,
            "source_quality": spec.source_quality,
            "dependent_targets": list(spec.dependent_targets),
            "fingerprint": observation.fingerprint,
            "etag": observation.etag,
            "last_modified": observation.last_modified,
            "summary": observation.summary,
            "last_observed_change_at": (
                observed_at
                if previous is None or previous.get("fingerprint") != observation.fingerprint
                else previous.get("last_observed_change_at")
            ),
        }

        if previous is None:
            state["sources"][key] = current
            peer_status["status"] = "CURRENT"
            peer_status["source_quality"] = spec.source_quality
            peer_status["dependent_targets"] = list(spec.dependent_targets)
            peer_status["warnings"] = (
                ["DISCOVERY_SOURCE_IS_STATIC_OR_FALLBACK"]
                if spec.source_quality == "FALLBACK_STATIC_OR_IR_PAGE"
                else []
            )
            continue

        if previous.get("fingerprint") != observation.fingerprint:
            changes += 1
            day = now.strftime("%Y-%m-%d")
            stamp = now.strftime("%H%M%SZ")
            path = events_root / day / f"{spec.peer_ticker}-{stamp}.json"
            event = {
                "schema_version": 1,
                "event_id": path.stem,
                "peer_ticker": spec.peer_ticker,
                "dependent_targets": list(spec.dependent_targets),
                "detected_at": observed_at,
                "url": spec.url,
                "source_quality": spec.source_quality,
                "old_fingerprint": previous.get("fingerprint"),
                "new_fingerprint": observation.fingerprint,
                "old_summary": previous.get("summary"),
                "new_summary": observation.summary,
                "status": "PEER_SOURCE_CHANGED",
                "requires_peer_standardization": True,
                "score_update_allowed": False,
                "execution_effect": "NONE",
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            peer_status["status"] = "PEER_SOURCE_CHANGED"
            peer_status["last_source_change_at"] = observed_at
            peer_status["last_event_path"] = str(path.relative_to(ROOT))
            peer_status["warnings"] = []

            for target in spec.dependent_targets:
                t = status["targets"].setdefault(
                    target,
                    {
                        "peer_status": "CURRENT_BASELINE_PEERS",
                        "peer_review_required": False,
                        "changed_peers": [],
                    },
                )
                t["peer_status"] = "PEER_UPDATE_DETECTED"
                t["peer_review_required"] = True
                t["changed_peers"] = sorted(set(t.get("changed_peers", []) + [spec.peer_ticker]))

                target_row = target_status.get("companies", {}).get(target)
                if target_row is not None:
                    target_row["peer_status"] = "PEER_UPDATE_DETECTED"
                    target_row["peer_review_required"] = True

        state["sources"][key] = current

    if sec_map_error:
        status["global_warnings"] = [f"SEC_TICKER_MAP_ERROR: {sec_map_error}"]
    else:
        status.pop("global_warnings", None)

    for target in peer_index["datasets"]:
        status["targets"].setdefault(
            target,
            {
                "peer_status": "CURRENT_BASELINE_PEERS",
                "peer_review_required": False,
                "changed_peers": [],
            },
        )

    dump_if_changed(state_path, state)
    dump_if_changed(status_path, status)
    dump_if_changed(target_status_path, target_status)

    print(json.dumps({
        "observed_at": observed_at,
        "peer_sources": len(specs),
        "successful_source_observations": observations,
        "source_errors": errors,
        "peer_source_changes": changes,
    }, indent=2))

    if args.fail_if_all_error and observations == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
