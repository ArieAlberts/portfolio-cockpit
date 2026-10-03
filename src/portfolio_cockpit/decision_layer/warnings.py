"""Fixed Data Confidence warning contract for the decision layer.

Every raw warning emitted by drift, valuation or the existing target
confidence maps to exactly one ``WarningCode``. An unknown raw warning is a
contract violation and raises, so new warnings cannot slip through unmapped.

The existing confidence calculation (``scoring/confidence.py`` and
``data/confidence/<date>.json``) is read, never changed.
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any


class WarningCode(str, Enum):
    STALE_DATA = "STALE_DATA"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    UNSUITABLE_METRIC = "UNSUITABLE_METRIC"
    MISSING_DATA = "MISSING_DATA"
    CALCULATION_ANOMALY = "CALCULATION_ANOMALY"
    PERIOD_MISMATCH = "PERIOD_MISMATCH"


# Raw warning prefix (text before the first ':') -> contract code.
RAW_PREFIX_MAP: dict[str, WarningCode] = {
    "STALE_DATA": WarningCode.STALE_DATA,
    "SOURCE_CONFLICT": WarningCode.SOURCE_CONFLICT,
    "UNSUITABLE_METRIC": WarningCode.UNSUITABLE_METRIC,
    "MISSING_DATA": WarningCode.MISSING_DATA,
    "CALCULATION_ANOMALY": WarningCode.CALCULATION_ANOMALY,
    "PERIOD_MISMATCH": WarningCode.PERIOD_MISMATCH,
    # Quality Drift coverage outcomes.
    "MISSING_REQUIRED_COMPONENT": WarningCode.MISSING_DATA,
    "BASELINE_MISSING_REQUIRED_COMPONENT": WarningCode.MISSING_DATA,
    "DRIFT_COVERAGE_BELOW_THRESHOLD": WarningCode.MISSING_DATA,
    "COMPONENT_SLOT_COVERAGE_LOW": WarningCode.MISSING_DATA,
    "BASELINE_PROFILE_COVERAGE_LOW": WarningCode.MISSING_DATA,
    # Valuation coverage outcome.
    "VALUATION_COVERAGE_BELOW_THRESHOLD": WarningCode.MISSING_DATA,
}

AXES = ("drift", "valuation", "confidence")


class WarningContractError(ValueError):
    """Raised for a raw warning that has no contract mapping."""


def classify(raw: str) -> WarningCode:
    prefix = raw.split(":", 1)[0]
    try:
        return RAW_PREFIX_MAP[prefix]
    except KeyError:
        raise WarningContractError(f"unmapped warning: {raw}") from None


def contract_warnings(axis: str, raws: list[str]) -> list[dict[str, str]]:
    if axis not in AXES:
        raise ValueError(f"unknown axis {axis}")
    return [{"code": classify(r).value, "axis": axis, "detail": r} for r in sorted(set(raws))]


# ----------------------------------------------------------- target confidence


def latest_confidence_path(root: Path) -> Path | None:
    candidates = sorted(p for p in (root / "data/confidence").glob("????-??-??.json") if p.is_file())
    return candidates[-1] if candidates else None


def _crosschecks(root: Path, confidence_path: Path) -> dict[str, Any]:
    path = confidence_path.with_name(f"crosschecks_{confidence_path.name}")
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("entries", {})


def confidence_raw_warnings(result: dict[str, Any] | None, crosscheck: dict[str, Any] | None) -> list[str]:
    """Map an existing target-confidence result onto raw contract warnings.

    freshness < 100 -> STALE_DATA; completeness < 100 -> MISSING_DATA;
    a cross-check result reporting a conflict -> SOURCE_CONFLICT;
    no confidence result at all -> MISSING_DATA.
    """
    if result is None or result.get("data_confidence_score") is None:
        return ["MISSING_DATA:confidence:no_target_confidence"]
    raws: list[str] = []
    if (result.get("freshness") or 0) < 100:
        raws.append(f"STALE_DATA:confidence_freshness:{result.get('freshness')}")
    if (result.get("completeness") or 0) < 100:
        raws.append(f"MISSING_DATA:confidence_completeness:{result.get('completeness')}")
    outcome = str((crosscheck or {}).get("result", ""))
    if "CONFLICT" in outcome and not outcome.startswith("NO_"):
        raws.append(f"SOURCE_CONFLICT:crosscheck:{outcome}")
    return raws


def load_target_confidence(root: Path) -> tuple[Path | None, dict[str, dict[str, Any]]]:
    """Per-ticker data confidence from the latest data/confidence/<date>.json (read-only)."""
    path = latest_confidence_path(root)
    if path is None:
        return None, {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    crosschecks = _crosschecks(root, path)
    out: dict[str, dict[str, Any]] = {}
    for ticker, result in payload.get("results", {}).items():
        out[ticker] = {
            "data_confidence": result.get("data_confidence_score"),
            "status": result.get("status"),
            "components": {
                k: result.get(k) for k in ("completeness", "source_quality", "freshness", "consistency")
            },
            "raw_warnings": confidence_raw_warnings(result, crosschecks.get(ticker)),
        }
    return path, out


def data_state(
    *,
    data_confidence: float | None,
    threshold: float,
    drift_status: str | None,
    valuation_status: str | None,
) -> tuple[str, list[str]]:
    """DATA_CHECK when confidence < threshold or drift/valuation cannot publish."""
    reasons: list[str] = []
    if data_confidence is None:
        reasons.append("DATA_CONFIDENCE_MISSING")
    elif data_confidence < threshold:
        reasons.append(f"DATA_CONFIDENCE_BELOW_{threshold:g}")
    if drift_status is None or drift_status == "DRIFT_DATA_CHECK":
        reasons.append(f"DRIFT_{drift_status or 'MISSING'}")
    if valuation_status != "OK":
        reasons.append(f"VALUATION_{valuation_status or 'MISSING'}")
    return ("DATA_CHECK" if reasons else "OK"), reasons
