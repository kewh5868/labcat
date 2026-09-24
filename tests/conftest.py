"""Block real provider network transport in isolated unit tests.

Transport tests replace their own opener or AWS session explicitly.
"""

import pytest


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
