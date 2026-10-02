import pytest

from portfolio_cockpit.future.order_manager import OrderManager


def test_phase1_cannot_place_orders():
    with pytest.raises(RuntimeError):
        OrderManager().place_order()
