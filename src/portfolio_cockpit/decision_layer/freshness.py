"""Read-only freshness checks for immutable portfolio data.

Dates in a snapshot are evidence of their age, never proof that a price was
refreshed. Count trading weekdays (not market holidays) for conservative,
explicit warnings. This module never changes scores or places orders.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


# Trading-weekday tolerance; holidays can make a warning conservative.
MAX_SESSIONS = {
    "account": 1,
    "positions": 1,
    "market": 1,
    "valuation": 1,
    "decisions": 1,
    "peer_market": 5,
    "peer_alternatives": 5,
}
WARNING_KEYS = ("positions", "market", "valuation", "decisions")


def sessions_old(value: str | None, today: str) -> int | None:
    """Weekdays after the observation date through today; future dates invalid."""
    if not value:
        return None
    try:
        observed, current = date.fromisoformat(value), date.fromisoformat(today)
    except (TypeError, ValueError):
        return None
    if observed > current:
        return None
    days = (current - observed).days
    return sum((observed + timedelta(days=n)).weekday() < 5 for n in range(1, days + 1))


def age_status(value: str | None, today: str, allowed_sessions: int = 1) -> dict[str, Any]:
    lag = sessions_old(value, today)
    return {
        "as_of": value,
        "sessions_old": lag,
        "allowed_sessions": allowed_sessions,
        "status": "MISSING_OR_INVALID" if lag is None else ("STALE" if lag > allowed_sessions else "FRESH"),
    }


def _json_date(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return raw.get("as_of") if isinstance(raw, dict) and isinstance(raw.get("as_of"), str) else None


def _latest_date(root: Path, dirname: str) -> str | None:
    directory = root / dirname
    files = sorted(directory.glob("????-??-??.json")) if directory.is_dir() else []
    return _json_date(files[-1]) if files else None


def assess_freshness(root: Path, today: str | None = None) -> dict[str, dict[str, Any]]:
    """No data reads from a broker and no changes to portfolio snapshots."""
    today = today or datetime.now(timezone.utc).date().isoformat()
    positions_path = root / "config/positions.yaml"
    try:
        positions = yaml.safe_load(positions_path.read_text(encoding="utf-8")) or {}
        positions_date = positions.get("as_of") if isinstance(positions, dict) else None
        # yaml.safe_load converts unquoted ISO dates into datetime.date objects.
        positions_date = positions_date.isoformat() if isinstance(positions_date, date) else positions_date
    except (OSError, yaml.YAMLError):
        positions_date = None

    dates = {
        "account": _latest_date(root, "data/account"),
        "positions": positions_date,
        "market": _latest_date(root, "data/market"),
        "valuation": _json_date(root / "data/valuation/current.json"),
        "decisions": _json_date(root / "data/decisions/current.json"),
        "peer_market": _latest_date(root, "data/market_peers"),
        "peer_alternatives": _json_date(root / "data/alerts/current.json"),
    }
    return {key: age_status(value, today, MAX_SESSIONS[key]) for key, value in dates.items()}


def stale_inputs(status: dict[str, dict[str, Any]]) -> list[str]:
    return [key for key in WARNING_KEYS if status[key]["status"] != "FRESH"]


def freshness_report(status: dict[str, dict[str, Any]]) -> str:
    lines = ["Portfolio data freshness (business weekdays; market holidays excluded):"]
    for key, entry in status.items():
        lines.append(
            f"- {key}: {entry['status']} | as_of={entry['as_of'] or 'unknown'}"
            f" | sessions_old={entry['sessions_old']} | limit={entry['allowed_sessions']}"
        )
    stale = stale_inputs(status)
    lines.append("Portfolio data incomplete/stale: " + (", ".join(stale) if stale else "none"))
    lines.append("Broker updates and verified price imports require separate secure inputs.")
    return "\n".join(lines)
