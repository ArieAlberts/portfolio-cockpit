#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import yaml

from portfolio_cockpit.monitoring.reliability import (
    deterministic_event_path,
    source_health_failure,
    source_health_success,
    write_event_once,
)
from portfolio_cockpit.monitoring.source_monitor import iso_z, observe_source, utc_now


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
    parser.add_argument("--registry", default="config/source_registry.yaml")
    parser.add_argument("--state", default="data/monitoring/source_state.json")
    parser.add_argument("--status", default="data/monitoring/status.json")
    parser.add_argument("--events", default="data/source_events")
    parser.add_argument("--fail-if-all-error", action="store_true")
    args = parser.parse_args()

    registry = yaml.safe_load((ROOT / args.registry).read_text(encoding="utf-8"))
    defaults = registry["defaults"]
    state_path = ROOT / args.state
    status_path = ROOT / args.status
    events_root = ROOT / args.events
    user_agent = os.getenv("COCKPIT_USER_AGENT", "").strip() or defaults["user_agent"]

    state = load_json(state_path, {"schema_version": 1, "sources": {}})
    status = load_json(status_path, {"schema_version": 1, "companies": {}})
    now = utc_now()
    observed_at = iso_z(now)
    errors = 0
    observations = 0
    changes = 0
    breaker_threshold = int(defaults.get("circuit_breaker_failure_threshold", 3))

    for ticker, company in registry["companies"].items():
        ticker_status = status["companies"].setdefault(
            ticker,
            {
                "fundamental_status": "NOT_YET_POLLED",
                "review_required": False,
                "latest_baseline_date": company["baseline_date"],
                "last_source_change_at": None,
                "last_event_path": None,
                "warnings": [],
                "source_health": {},
            },
        )
        ticker_status.setdefault("source_health", {})

        baseline_age = (now.date() - date.fromisoformat(company["baseline_date"])).days
        is_stale = baseline_age > int(company["stale_after_days"])
        ticker_status["baseline_age_days"] = baseline_age
        ticker_status["data_age_status"] = "STALE" if is_stale else "CURRENT"
        warnings = [w for w in ticker_status.get("warnings", []) if w != "BASELINE_OLDER_THAN_STALE_THRESHOLD"]
        if is_stale:
            warnings.append("BASELINE_OLDER_THAN_STALE_THRESHOLD")
            if ticker_status["fundamental_status"] in {"CURRENT", "NOT_YET_POLLED"}:
                ticker_status["fundamental_status"] = "STALE_DATA"
                ticker_status["review_required"] = True
        ticker_status["warnings"] = warnings

        for source in company["sources"]:
            source_id = source["id"]
            source_entry = dict(source)
            if source_entry["mode"] == "HTML_PAGE":
                source_entry.setdefault(
                    "fingerprint_mode",
                    defaults.get("html_fingerprint_mode", "RELEVANT_LINKS"),
                )
                source_entry.setdefault("link_patterns", defaults.get("html_link_patterns"))

            key = f"{ticker}:{source_id}"
            prior_health = ticker_status["source_health"].get(source_id)
            try:
                observation = observe_source(
                    source_entry,
                    user_agent=user_agent,
                    timeout=int(defaults["timeout_seconds"]),
                    retry_attempts=int(defaults.get("retry_attempts", 3)),
                    retry_base_seconds=float(defaults.get("retry_base_seconds", 1.0)),
                )
                observations += 1
                ticker_status["source_health"][source_id] = source_health_success(
                    prior_health, observed_at
                )
            except Exception as exc:
                errors += 1
                error_text = f"{type(exc).__name__}: {exc}"
                health = source_health_failure(
                    prior_health,
                    observed_at=observed_at,
                    error=error_text,
                    failure_threshold=breaker_threshold,
                )
                ticker_status["source_health"][source_id] = health
                ticker_status["warnings"] = sorted(
                    set(ticker_status.get("warnings", []) + [f"{source_id}: {error_text}"])
                )
                if health["circuit_state"] == "OPEN" and ticker_status["fundamental_status"] != "NEW_DATA_DETECTED":
                    ticker_status["fundamental_status"] = "SOURCE_DEGRADED"
                    ticker_status["review_required"] = True
                elif ticker_status["fundamental_status"] == "NOT_YET_POLLED":
                    ticker_status["fundamental_status"] = "SOURCE_ERROR"
                continue

            previous = state["sources"].get(key)
            current = {
                "ticker": ticker,
                "source_id": source_id,
                "mode": source["mode"],
                "url": source["url"],
                "fingerprint": observation.fingerprint,
                "etag": observation.etag,
                "last_modified": observation.last_modified,
                "summary": observation.summary,
                "last_observed_change_at": observed_at if previous is None or previous.get("fingerprint") != observation.fingerprint else previous.get("last_observed_change_at"),
            }

            if previous is None:
                state["sources"][key] = current
                if ticker_status["fundamental_status"] in {"NOT_YET_POLLED", "SOURCE_ERROR", "SOURCE_DEGRADED"}:
                    ticker_status["fundamental_status"] = "STALE_DATA" if is_stale else "CURRENT"
                    ticker_status["review_required"] = is_stale
                continue

            if previous.get("fingerprint") != observation.fingerprint:
                changes += 1
                event_id, path = deterministic_event_path(
                    events_root,
                    entity=ticker,
                    source_id=source_id,
                    old_fingerprint=previous.get("fingerprint"),
                    new_fingerprint=observation.fingerprint,
                )
                event = {
                    "schema_version": 2,
                    "event_id": event_id,
                    "ticker": ticker,
                    "source_id": source_id,
                    "detected_at": observed_at,
                    "url": source["url"],
                    "old_fingerprint": previous.get("fingerprint"),
                    "new_fingerprint": observation.fingerprint,
                    "old_summary": previous.get("summary"),
                    "new_summary": observation.summary,
                    "status": "NEW_DATA_DETECTED",
                    "requires_standardization": True,
                    "score_update_allowed": False,
                    "execution_effect": "NONE",
                }
                write_event_once(path, event)
                ticker_status["fundamental_status"] = "NEW_DATA_DETECTED"
                ticker_status["review_required"] = True
                ticker_status["last_source_change_at"] = observed_at
                ticker_status["last_event_path"] = str(path.relative_to(ROOT))

            state["sources"][key] = current

    dump_if_changed(state_path, state)
    dump_if_changed(status_path, status)

    print(json.dumps({
        "observed_at": observed_at,
        "successful_source_observations": observations,
        "source_errors": errors,
        "source_changes": changes,
        "companies": len(registry["companies"]),
    }, indent=2))

    if args.fail_if_all_error and observations == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
