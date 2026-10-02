from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class CompanyType(str, Enum):
    GENERAL_OPERATING_COMPANY = "GENERAL_OPERATING_COMPANY"
    INSURER = "INSURER"
    CYCLICAL_MINING = "CYCLICAL_MINING"
    PRE_REVENUE_DEVELOPMENT = "PRE_REVENUE_DEVELOPMENT"
    FINANCIAL_SERVICES = "FINANCIAL_SERVICES"


class ThesisStatus(str, Enum):
    INTACT = "INTACT"
    WATCH = "WATCH"
    BROKEN = "BROKEN"


@dataclass(frozen=True)
class MetricProvenance:
    source: str
    source_type: str
    source_date: date
    retrieved_at: datetime
    period: str
    calculation_method: str
    confidence: float


@dataclass(frozen=True)
class MetricObservation:
    ticker: str
    metric_name: str
    raw_value: float
    unit: str
    currency: Optional[str]
    observation_date: date
    provenance: MetricProvenance


@dataclass(frozen=True)
class CompanyBaseline:
    ticker: str
    company_type: CompanyType
    baseline_date: date
    quality_drift_score: float = 50.0


@dataclass(frozen=True)
class ScoreSnapshot:
    ticker: str
    calculated_at: datetime
    fundamental_quality_score: float
    quality_drift_score: float
    valuation_score: float
    data_confidence_score: float
    thesis_status: ThesisStatus
    explanations: tuple[str, ...] = field(default_factory=tuple)
