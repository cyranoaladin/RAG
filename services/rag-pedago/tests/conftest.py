"""Fail-closed hermeticity guard for rag-pedago tests."""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def block_network_sockets(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject socket creation unless a test explicitly declares network access."""
    if request.node.get_closest_marker("network") or request.node.get_closest_marker("e2e"):
        return

    original_socket = socket.socket

    def reject_socket(family: int = socket.AF_INET, *args: object, **kwargs: object) -> socket.socket:
        if family in (socket.AF_INET, socket.AF_INET6):
            raise RuntimeError("réseau interdit dans un test hermétique")
        return original_socket(family, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", reject_socket)
