"""Unit tests do not silently contact live scientific services.

Adapter tests replace the transport explicitly. Live endpoint
verification runs separately; an empty test transport is never used by
the application.
"""

import pytest


@pytest.fixture
def authenticated_model_factory(monkeypatch):
    """Explicit simulated authentication/planning, never live provider
    credentials."""
    from labcat.connections import DEFAULT_PROFILE, ConnectionManager
    from labcat.models import Plan

    monkeypatch.setattr(
        "labcat.connections.request_json",
        lambda *args, **kwargs: {"data": [{"id": "fixture-model"}]},
    )
    monkeypatch.setattr(
        "labcat.connections.plan_with_model", lambda *args, **kwargs: Plan()
    )

    def configure(manager):
        manager.configure(
            {
                "profile": {
                    **DEFAULT_PROFILE,
                    "provider": "openai",
                    "model": "fixture-model",
                    "allow_paid_inference": True,
                },
                "secret_storage": "session",
                "secrets": {"openai": "fixture-never-a-live-credential"},
            }
        )
        return manager

    def factory(path):
        return configure(ConnectionManager(path))

    factory.configure = configure
    return factory


@pytest.fixture
def authenticated_app_models(monkeypatch, authenticated_model_factory):
    """Persistence/UI integrations use an explicitly simulated connected
    model."""
    from labcat.connections import ConnectionManager

    original = ConnectionManager.__init__

    def initialize(manager, path):
        original(manager, path)
        authenticated_model_factory.configure(manager)

    monkeypatch.setattr(ConnectionManager, "__init__", initialize)


@pytest.fixture
def authenticated_research(monkeypatch, request, tmp_path, authenticated_model_factory):
    """Bind source/persistence unit tests to their explicit simulated
    account."""
    from functools import partial

    from labcat.research import research

    manager = authenticated_model_factory(tmp_path / "fixture-model.sqlite3")
    monkeypatch.setattr(
        request.module, "research", partial(research, connections=manager)
    )


@pytest.fixture
def historical_property_fixture(monkeypatch):
    """Explicit public-data fixture for positive integrations; never app
    fallback."""
    from copy import deepcopy

    import labcat.science as science

    historical = science.load_snapshot()
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda filters=None: deepcopy(historical)
    )
    return deepcopy(historical)


@pytest.fixture(autouse=True)
def offline_public_sources(monkeypatch, request):
    from labcat import property_research, public_sources
    from labcat.science import dielectric, hybrid3, nomad, structure_identity

    def unavailable(*args, **kwargs):
        raise public_sources.PublicSourceError(
            "External network disabled in unit tests."
        )

    monkeypatch.setattr(structure_identity, "_fetch", unavailable)

    if request.module.__name__.split(".")[-1] != "test_dielectric":
        monkeypatch.setattr(dielectric, "_download", unavailable)

    if request.module.__name__.split(".")[-1] != "test_property_research":
        monkeypatch.setattr(property_research, "_fetch_full_text", unavailable)
    if request.module.__name__.split(".")[-1] == "test_public_sources":
        # This module exercises the real transport with its own socket and DNS
        # blockers. Stubbing _fetch here would bypass the code those tests verify.
        return
    monkeypatch.setattr(public_sources, "_fetch", unavailable)
    monkeypatch.setattr(nomad, "_fetch", unavailable)
    monkeypatch.setattr(hybrid3, "_fetch", unavailable)


@pytest.fixture(autouse=True)
def empty_default_material_query(monkeypatch):
    import labcat.science as science

    monkeypatch.setattr(
        science,
        "retrieve_nomad",
        lambda filters=None: (
            [],
            {
                "mode": "live_nomad",
                "records_retrieved": 0,
                "caveats": ["Test transport returned no entries."],
            },
        ),
    )
