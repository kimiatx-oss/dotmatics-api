import socket

import pytest


@pytest.fixture(autouse=True)
def no_external_network(request, monkeypatch):
    """Unit tests cannot silently reach a deployment; transport tests use loopback."""
    if request.node.get_closest_marker("integration"):
        return
    original = socket.socket.connect
    loopback = bool(request.node.get_closest_marker("transport"))

    def connect(sock, address):
        if (
            loopback
            and isinstance(address, tuple)
            and address[0] in ("127.0.0.1", "::1")
        ):
            return original(sock, address)
        raise AssertionError("Network access is disabled in offline tests")

    monkeypatch.setattr(socket.socket, "connect", connect)
