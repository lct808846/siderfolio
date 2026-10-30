"""Verify the Windows listener check against a real local TCP socket."""

import os
import socket

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows IP Helper API")
def test_listener_table_detects_open_socket_and_ignores_closed_connection():
    from scripts.windows_tcp_listeners import listeners

    server = socket.socket()
    client = None
    peer = None
    try:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert any(item["pid"] == os.getpid() for item in listeners(port))
        client = socket.create_connection(("127.0.0.1", port))
        peer, _ = server.accept()
    finally:
        if peer:
            peer.close()
        if client:
            client.close()
        server.close()
    assert listeners(port) == []
