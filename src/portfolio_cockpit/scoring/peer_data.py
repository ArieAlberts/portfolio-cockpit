from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EligibleMetricSet:
    comparison_class: str
    target_value: float | None
    peer_values: tuple[float, ...]
    peer_tickers: tuple[str, ...]
    status: str


def eligible_metric_set(dataset: dict, metric_name: str, min_peers: int = 3) -> EligibleMetricSet:
    target_ticker = dataset["target_ticker"]
    target_metric = dataset["companies"][target_ticker]["metrics"].get(metric_name)

    if not target_metric or not target_metric.get("score_eligible") or target_metric.get("value") is None:
        return EligibleMetricSet("", None, (), (), "TARGET_DATA_CHECK")

    comparison_class = target_metric["comparison_class"]
    peers: list[tuple[str, float]] = []

    for ticker, company in dataset["companies"].items():
        if ticker == target_ticker:
            continue
        if company.get("period_alignment") != "ALIGNED_H1":
            continue
        metric = company.get("metrics", {}).get(metric_name)
        if not metric or not metric.get("score_eligible"):
            continue
        if metric.get("comparison_class") != comparison_class:
            continue
        value = metric.get("value")
        if value is None:
            continue
        peers.append((ticker, float(value)))

    if len(peers) < min_peers:
        return EligibleMetricSet(
            comparison_class,
            float(target_metric["value"]),
            tuple(v for _, v in peers),
            tuple(t for t, _ in peers),
            "INSUFFICIENT_ALIGNED_PEERS",
        )

    return EligibleMetricSet(
        comparison_class,
        float(target_metric["value"]),
        tuple(v for _, v in peers),
        tuple(t for t, _ in peers),
        "READY",
    )
