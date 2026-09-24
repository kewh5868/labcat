"""Offline unit tests never silently contact scientific or model
services."""

import socket

import pytest


@pytest.fixture(autouse=True)
def offline_network(monkeypatch):
    def unavailable(*args, **kwargs):
        pytest.fail("Unit test attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", unavailable)
    monkeypatch.setattr(socket, "getaddrinfo", unavailable)


@pytest.fixture(autouse=True)
def offline_provider_transport(monkeypatch):
    def unavailable(*args, **kwargs):
        raise AssertionError("External network disabled in unit tests.")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", unavailable)
    try:
        from botocore.httpsession import URLLib3Session
    except ImportError:
        return
    monkeypatch.setattr(URLLib3Session, "send", unavailable)
