#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

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


def event_path(events_root: Path, observed_at: datetime, ticker: str, source_id: str) -> Path:
    day = observed_at.strftime("%Y-%m-%d")
    stamp = observed_at.strftime("%H%M%SZ")
    return events_root / day / f"{ticker}-{source_id}-{stamp}.json"


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

    state = load_json(state_path, {"schema_version": 1, "sources": {}})
    status = load_json(status_path, {"schema_version": 1, "companies": {}})
    now = utc_now()
    observed_at = iso_z(now)
    errors = 0
    observations = 0

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
            },
        )
        ticker_errors = []

        baseline_age = (now.date() - date.fromisoformat(company["baseline_date"])).days
        if baseline_age > int(company["stale_after_days"]) and ticker_status["fundamental_status"] == "CURRENT":
            ticker_status["fundamental_status"] = "STALE_DATA"
            ticker_status["review_required"] = True
            ticker_status["warnings"] = ["BASELINE_OLDER_THAN_STALE_THRESHOLD"]

        for source in company["sources"]:
            key = f"{ticker}:{source['id']}"
            try:
                observation = observe_source(
                    source,
                    user_agent=defaults["user_agent"],
                    timeout=int(defaults["timeout_seconds"]),
                )
                observations += 1
            except Exception as exc:
                errors += 1
                ticker_errors.append(f"{source['id']}: {type(exc).__name__}: {exc}")
                continue

            previous = state["sources"].get(key)
            current = {
                "ticker": ticker,
                "source_id": source["id"],
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
                if ticker_status["fundamental_status"] == "NOT_YET_POLLED":
                    ticker_status["fundamental_status"] = "CURRENT"
                    ticker_status["warnings"] = []
                continue

            if previous.get("fingerprint") != observation.fingerprint:
                path = event_path(events_root, now, ticker, source["id"])
                event = {
                    "schema_version": 1,
                    "event_id": path.stem,
                    "ticker": ticker,
                    "source_id": source["id"],
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
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                ticker_status["fundamental_status"] = "NEW_DATA_DETECTED"
                ticker_status["review_required"] = True
                ticker_status["last_source_change_at"] = observed_at
                ticker_status["last_event_path"] = str(path.relative_to(ROOT))
                ticker_status["warnings"] = []
                state["sources"][key] = current
            else:
                state["sources"][key] = current

        if ticker_errors:
            ticker_status["warnings"] = sorted(set(ticker_status.get("warnings", []) + ticker_errors))
            if ticker_status["fundamental_status"] == "NOT_YET_POLLED":
                ticker_status["fundamental_status"] = "SOURCE_ERROR"

    dump_if_changed(state_path, state)
    dump_if_changed(status_path, status)

    print(json.dumps({
        "observed_at": observed_at,
        "successful_source_observations": observations,
        "source_errors": errors,
        "companies": len(registry["companies"]),
    }, indent=2))

    if args.fail_if_all_error and observations == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
