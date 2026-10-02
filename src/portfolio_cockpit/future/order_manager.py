"""Permanent execution boundary.

This repository must never place, modify or cancel live brokerage orders.
It may only build proposed order tickets for human review or support
paper/simulated trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProposedOrderTicket:
    ticker: str
    side: str
    quantity: float
    order_type: str
    limit_price: Optional[float] = None
    rationale: str = ""


class ProposedOrderTicketBuilder:
    """Builds a non-executable trade proposal for human review."""

    def build(
        self,
        *,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str,
        limit_price: Optional[float] = None,
        rationale: str = "",
    ) -> ProposedOrderTicket:
        return ProposedOrderTicket(
            ticker=ticker,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            rationale=rationale,
        )


class LiveExecutionForbidden(RuntimeError):
    pass


def assert_live_execution_forbidden() -> None:
    raise LiveExecutionForbidden(
        "Live brokerage execution is permanently forbidden in this repository."
    )
