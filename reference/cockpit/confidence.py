"""DATA CONFIDENCE-module.

Ieder fundamenteel datapunt draagt provenance (DataPoint). data_confidence 0-100
combineert completeness, source quality, freshness en consistency.
Onder de drempel (decision.yaml) => DATA_CHECK en geen waarderings- of
portefeuilleconclusie.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Optional

STALE_DATA = "STALE_DATA"
SOURCE_CONFLICT = "SOURCE_CONFLICT"
UNSUITABLE_METRIC = "UNSUITABLE_METRIC"
MISSING_DATA = "MISSING_DATA"
CALCULATION_ANOMALY = "CALCULATION_ANOMALY"
WARNING_CODES = (STALE_DATA, SOURCE_CONFLICT, UNSUITABLE_METRIC, MISSING_DATA, CALCULATION_ANOMALY)


@dataclass(frozen=True)
class DataPoint:
    ticker: str
    metric_name: str
    raw_value: float
    source: str
    source_type: str
    filing_id: Optional[str]
    as_of_date: date
    retrieved_at: datetime
    currency: Optional[str]
    period: Optional[str]
    calculation_method: Optional[str]
    kind: str = "FUNDAMENTAL"  # FUNDAMENTAL | MARKET | ASSESSMENT

    def to_dict(self):
        d = asdict(self)
        d["as_of_date"] = str(self.as_of_date)
        d["retrieved_at"] = self.retrieved_at.isoformat()
        return d


@dataclass
class ConfidenceResult:
    data_confidence: float
    components: dict[str, float]
    warnings: list[str]


def _freshness_factor(age_days: int, max_age: int, floor: float) -> float:
    if age_days <= max_age:
        return 1.0
    # lineair aflopend tot floor bij 2x max_age
    over = min(1.0, (age_days - max_age) / max_age)
    return max(floor, 1.0 - over)


def compute_confidence(
    datapoints: list[DataPoint],
    as_of: date,
    quality_coverage: float,
    valuation_applicable_weight: float,
    cfg: dict,
    extra_warnings: list[str] | None = None,
) -> ConfidenceResult:
    warnings: list[str] = list(extra_warnings or [])
    fcfg = cfg["freshness"]
    sq = cfg["source_quality"]

    # completeness
    min_cov = cfg["min_required_quality_coverage"]
    completeness = 0.5 * quality_coverage + 0.5 * valuation_applicable_weight
    hard_missing = False
    if quality_coverage < min_cov:
        warnings.append(f"{MISSING_DATA}:quality_coverage={quality_coverage:.2f}<{min_cov}")
        hard_missing = True
    if valuation_applicable_weight == 0:
        warnings.append(f"{MISSING_DATA}:no_applicable_valuation_metric")
        hard_missing = True

    # source quality
    if datapoints:
        source_quality = sum(sq.get(dp.source_type, sq["UNKNOWN"]) for dp in datapoints) / len(datapoints)
    else:
        source_quality = 0.0

    # freshness (per meest recent datapunt per metric)
    latest: dict[str, DataPoint] = {}
    for dp in datapoints:
        cur = latest.get(dp.metric_name)
        if cur is None or dp.as_of_date > cur.as_of_date:
            latest[dp.metric_name] = dp
    fresh_scores = []
    stale_fundamentals = 0
    n_fundamentals = 0
    for dp in latest.values():
        max_age = fcfg["valuation_max_age_days"] if dp.kind == "MARKET" else fcfg["fundamental_max_age_days"]
        age = (as_of - dp.as_of_date).days
        f = _freshness_factor(age, max_age, fcfg["stale_penalty_floor"])
        if dp.kind != "MARKET":
            n_fundamentals += 1
        if f < 1.0:
            warnings.append(f"{STALE_DATA}:{dp.metric_name}:{age}d>{max_age}d")
            if dp.kind != "MARKET":
                stale_fundamentals += 1
        fresh_scores.append(f)
    stale_share = stale_fundamentals / n_fundamentals if n_fundamentals else 0.0
    freshness = sum(fresh_scores) / len(fresh_scores) if fresh_scores else 0.0

    # consistency: conflicterende bronnen voor dezelfde metric+periode
    tol = cfg["consistency"]["conflict_tolerance_rel"]
    groups: dict[tuple, list[DataPoint]] = defaultdict(list)
    for dp in datapoints:
        groups[(dp.metric_name, dp.period)].append(dp)
    conflicts = 0
    multi = 0
    for (metric, period), dps in groups.items():
        sources = {dp.source for dp in dps}
        if len(sources) < 2:
            continue
        multi += 1
        vals = [dp.raw_value for dp in dps]
        ref = max(abs(v) for v in vals) or 1.0
        if (max(vals) - min(vals)) / ref > tol:
            conflicts += 1
            warnings.append(f"{SOURCE_CONFLICT}:{metric}:{period}:{sorted(sources)}")
    consistency = 1.0 - (conflicts / max(1, len(groups)))
    # calculation anomaly: onwaarschijnlijke sprong tussen twee opeenvolgende waarden
    ccfg = cfg["consistency"]
    by_metric: dict[str, list[DataPoint]] = defaultdict(list)
    for dp in datapoints:
        if dp.metric_name in ccfg["anomaly_check_metrics"]:
            by_metric[dp.metric_name].append(dp)
    anomalies = 0
    for metric, dps in by_metric.items():
        dates = sorted({dp.as_of_date for dp in dps})
        if len(dates) < 2:
            continue
        prev = [dp.raw_value for dp in dps if dp.as_of_date == dates[-2]][-1]
        cur = [dp.raw_value for dp in dps if dp.as_of_date == dates[-1]][-1]
        if prev != 0 and abs(cur / prev - 1) > ccfg["anomaly_rel_jump"]:
            anomalies += 1
            warnings.append(f"{CALCULATION_ANOMALY}:{metric}:{prev}->{cur}")
    if anomalies:
        consistency = min(consistency, 0.5)

    w = cfg["component_weights"]
    components = {
        "completeness": round(completeness, 4),
        "source_quality": round(source_quality, 4),
        "freshness": round(freshness, 4),
        "consistency": round(consistency, 4),
    }
    score = 100 * sum(w[k] * components[k] for k in w)
    caps = cfg.get("caps", {})
    if hard_missing:
        score = min(score, caps.get("missing_data", 60))
    if conflicts:
        score = min(score, caps.get("source_conflict", 100))
    if anomalies:
        score = min(score, caps.get("calculation_anomaly", 100))
    if stale_share > fcfg["max_stale_fundamental_share"]:
        score = min(score, caps.get("stale_fundamentals", 100))
    return ConfidenceResult(round(score, 2), components, warnings)
