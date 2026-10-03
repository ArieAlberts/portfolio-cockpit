from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PeerAlignmentResult:
    status: str
    target_reporting_period: str
    peer_dataset_period: str | None
    score_recalculation_allowed: bool
    reason: str


def evaluate_peer_alignment(
    *,
    target_reporting_period: str,
    peer_dataset: dict[str, Any] | None,
) -> PeerAlignmentResult:
    if peer_dataset is None:
        return PeerAlignmentResult(
            status="PENDING_PEERS",
            target_reporting_period=target_reporting_period,
            peer_dataset_period=None,
            score_recalculation_allowed=False,
            reason="NO_PEER_DATASET",
        )

    peer_period = peer_dataset.get("strict_reference_period")
    if peer_period != target_reporting_period:
        return PeerAlignmentResult(
            status="PENDING_PEERS",
            target_reporting_period=target_reporting_period,
            peer_dataset_period=peer_period,
            score_recalculation_allowed=False,
            reason="PEER_PERIOD_NOT_ALIGNED",
        )

    status_text = str(peer_dataset.get("peer_universe_status", ""))
    if "INSUFFICIENT" in status_text or "HARD" in status_text:
        return PeerAlignmentResult(
            status="PEER_UNIVERSE_BLOCKED",
            target_reporting_period=target_reporting_period,
            peer_dataset_period=peer_period,
            score_recalculation_allowed=False,
            reason="PEER_UNIVERSE_BLOCKED",
        )

    return PeerAlignmentResult(
        status="PEERS_ALIGNED_FOR_SCORING_REVIEW",
        target_reporting_period=target_reporting_period,
        peer_dataset_period=peer_period,
        score_recalculation_allowed=False,
        reason="PERIOD_ALIGNED_REQUIRES_SCORING_GATES",
    )
