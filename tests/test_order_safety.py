import pytest

from portfolio_cockpit.future.order_manager import (
    LiveExecutionForbidden,
    ProposedOrderTicketBuilder,
    assert_live_execution_forbidden,
)


def test_can_build_non_executable_proposed_ticket():
    ticket = ProposedOrderTicketBuilder().build(
        ticker="WKL",
        side="BUY",
        quantity=10,
        order_type="LMT",
        limit_price=65.0,
        rationale="Example only",
    )
    assert ticket.ticker == "WKL"
    assert ticket.side == "BUY"


def test_live_execution_is_permanently_forbidden():
    with pytest.raises(LiveExecutionForbidden):
        assert_live_execution_forbidden()


def test_no_live_place_order_method_exists():
    builder = ProposedOrderTicketBuilder()
    assert not hasattr(builder, "place_order")
    assert not hasattr(builder, "submit_order")
    assert not hasattr(builder, "cancel_order")
