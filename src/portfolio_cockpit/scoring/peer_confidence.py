from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PeerMetricConfidence:
    metric_name: str
    score: float
    peer_count: int
    peers: tuple[str, ...]


def _source_score(source_type: str) -> float:
    if source_type in {
        "SEC_FILING", "SEC_FILING_EXHIBIT", "OFFICIAL_COMPANY_REPORT",
        "OFFICIAL_EXCHANGE_RELEASE", "OFFICIAL_COMPANY_RELEASE",
        "OFFICIAL_DIGITAL_REPORT", "OFFICIAL_COMPANY_REPORT_AND_SEC",
    }:
        return 100.0
    return 80.0


def _period_score(alignment: str) -> float:
    if alignment.startswith("ALIGNED") and "DERIVED" not in alignment:
        return 100.0
    if "DERIVED" in alignment:
        return 85.0
    return 60.0


def _role_score(role: str) -> float:
    if role in {"PEER", "DIRECT_PEER"}:
        return 100.0
    if role == "BROAD_PEER":
        return 70.0
    if role == "CONTEXT_PEER":
        return 40.0
    return 80.0


def peer_metric_confidence(
    *,
    dataset: dict,
    metric_name: str,
    minimum_peer_values: int = 4,
) -> PeerMetricConfidence:
    target = dataset["target_ticker"]
    target_metric = dataset["companies"][target]["metrics"][metric_name]
    comparison_class = target_metric["comparison_class"]
    target_alignment = dataset["companies"][target]["period_alignment"]
    configured = dataset.get("rules", {}).get("eligible_period_alignments")
    alignments = set(configured or [target_alignment])

    observations: list[tuple[str, float]] = []
    for ticker, company in dataset["companies"].items():
        if ticker == target:
            continue
        if company.get("role") in {"GATE", "CONTEXT_ONLY"}:
            continue
        if company.get("period_alignment") not in alignments:
            continue
        metric = company.get("metrics", {}).get(metric_name)
        if not metric or not metric.get("score_eligible") or metric.get("value") is None:
            continue
        if metric.get("comparison_class") != comparison_class:
            continue

        source = company.get("source", {})
        source_score = _source_score(str(source.get("type", "")))
        period_score = _period_score(str(company.get("period_alignment", "")))
        role_score = _role_score(str(company.get("role", "PEER")))
        definition_score = 100.0

        score = (
            0.35 * source_score
            + 0.25 * period_score
            + 0.25 * definition_score
            + 0.15 * role_score
        )
        observations.append((ticker, score))

    if len(observations) < minimum_peer_values:
        raise ValueError("INSUFFICIENT_PEER_INPUTS")

    # Conservative: the weakest included peer determines metric confidence.
    return PeerMetricConfidence(
        metric_name=metric_name,
        score=min(score for _, score in observations),
        peer_count=len(observations),
        peers=tuple(ticker for ticker, _ in observations),
    )
