from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PeerUniverseValidation:
    valid: bool
    status: str
    peer_count: int
    minimum_peer_count: int
    confidence: str


def validate_peer_universe(config: dict) -> PeerUniverseValidation:
    peers = list(config.get("peers", []))
    status = str(config.get("status", "INSUFFICIENT"))
    confidence = str(config.get("confidence", "LOW"))
    minimum = int(config.get("minimum_peer_count", 4))

    if status == "INSUFFICIENT":
        return PeerUniverseValidation(
            valid=False,
            status="INSUFFICIENT",
            peer_count=len(peers),
            minimum_peer_count=minimum,
            confidence=confidence,
        )

    valid = len(peers) >= minimum
    return PeerUniverseValidation(
        valid=valid,
        status="VALID" if valid else "PEER_DATA_CHECK",
        peer_count=len(peers),
        minimum_peer_count=minimum,
        confidence=confidence,
    )
