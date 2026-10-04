"""Laden en valideren van configuratie. Alle drempels komen uit config/*.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

COMPANY_TYPES = (
    "GENERAL_OPERATING_COMPANY",
    "INSURER",
    "DEVELOPMENT_PRE_REVENUE",
    "CYCLICAL_MINING",
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class MetricSpec:
    name: str
    category: str
    weight: float  # effectief gewicht = categorie * metric
    mode: str
    direction: str
    full_scale: float
    dead_band: float


@dataclass(frozen=True)
class QualityProfile:
    company_type: str
    metrics: dict[str, MetricSpec]
    excluded_metrics: frozenset[str]


@dataclass(frozen=True)
class Config:
    quality: dict[str, QualityProfile]
    valuation: dict[str, Any]
    confidence: dict[str, Any]
    decision: dict[str, Any]
    risk: dict[str, Any]


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _build_quality(raw: dict) -> dict[str, QualityProfile]:
    forbidden = set(raw.get("forbidden_price_dependent_metrics", []))
    profiles: dict[str, QualityProfile] = {}
    for ctype, prof in raw["profiles"].items():
        if ctype not in COMPANY_TYPES:
            raise ConfigError(f"Onbekend company_type: {ctype}")
        cats = prof["categories"]
        cat_total = sum(c["weight"] for c in cats.values())
        if abs(cat_total - 1.0) > 1e-6:
            raise ConfigError(f"{ctype}: categoriegewichten tellen op tot {cat_total}, niet 1.0")
        excluded = frozenset(prof.get("excluded_metrics", []))
        metrics: dict[str, MetricSpec] = {}
        for cat_name, cat in cats.items():
            m_total = sum(m["weight"] for m in cat["metrics"].values())
            if abs(m_total - 1.0) > 1e-6:
                raise ConfigError(f"{ctype}.{cat_name}: metricgewichten tellen op tot {m_total}")
            for m_name, m in cat["metrics"].items():
                if m_name in forbidden:
                    raise ConfigError(
                        f"{ctype}: '{m_name}' is prijsafhankelijk en mag niet in QUALITY")
                if m_name in excluded:
                    raise ConfigError(f"{ctype}: '{m_name}' staat zowel in profiel als in excluded")
                if m["mode"] not in ("relative", "absolute", "direct"):
                    raise ConfigError(f"{ctype}.{m_name}: onbekende mode {m['mode']}")
                if m["direction"] not in ("higher_better", "lower_better"):
                    raise ConfigError(f"{ctype}.{m_name}: onbekende direction")
                if m["full_scale"] <= 0:
                    raise ConfigError(f"{ctype}.{m_name}: full_scale moet > 0 zijn")
                if m_name in metrics:
                    raise ConfigError(f"{ctype}: metric {m_name} dubbel gedefinieerd")
                metrics[m_name] = MetricSpec(
                    name=m_name, category=cat_name,
                    weight=cat["weight"] * m["weight"],
                    mode=m["mode"], direction=m["direction"],
                    full_scale=float(m["full_scale"]), dead_band=float(m.get("dead_band", 0.0)),
                )
        profiles[ctype] = QualityProfile(ctype, metrics, excluded)
    missing = set(COMPANY_TYPES) - set(profiles)
    if missing:
        raise ConfigError(f"Ontbrekende quality-profielen: {missing}")
    return profiles


def _validate_valuation(raw: dict) -> dict:
    for ctype, prof in raw["profiles"].items():
        total = sum(prof["weights"].values())
        if abs(total - 1.0) > 1e-6:
            raise ConfigError(f"valuation {ctype}: gewichten tellen op tot {total}")
        overlap = set(prof["weights"]) & set(prof.get("not_applicable", []))
        if overlap:
            raise ConfigError(f"valuation {ctype}: {overlap} zowel gewogen als NOT_APPLICABLE")
        for m in prof["weights"]:
            if m not in raw["metrics"]:
                raise ConfigError(f"valuation {ctype}: onbekende metric {m}")
    return raw


def load_config(config_dir: Path | str | None = None) -> Config:
    d = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    return Config(
        quality=_build_quality(_load_yaml(d / "quality_profiles.yaml")),
        valuation=_validate_valuation(_load_yaml(d / "valuation.yaml")),
        confidence=_load_yaml(d / "confidence.yaml"),
        decision=_load_yaml(d / "decision.yaml"),
        risk=_load_yaml(d / "risk.yaml"),
    )
