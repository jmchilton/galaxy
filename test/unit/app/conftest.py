import socket

import pytest

LOCAL_TEST_HOST = "internal.example"


@pytest.fixture
def fake_dns(monkeypatch):
    """Resolve LOCAL_TEST_HOST to loopback and every other host to a public address."""

    def getaddrinfo(host, port, *args, **kwargs):
        ip = "127.0.0.1" if host == LOCAL_TEST_HOST else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 443))]

    monkeypatch.setattr("galaxy.files.uris.socket.getaddrinfo", getaddrinfo)
