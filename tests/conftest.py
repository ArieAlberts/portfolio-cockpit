import socket

import pytest


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch, request):
    """Ordinary tests are deterministic and offline."""
    if request.node.get_closest_marker("network"):
        return

    def blocked(*args, **kwargs):
        raise RuntimeError("NETWORK_ACCESS_BLOCKED_IN_UNIT_TEST")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
