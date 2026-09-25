"""Source filters select fixed adapters without changing evidence
safeguards."""

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from labcat.source_preferences import (
    SOURCE_IDS,
    SourcePreferencesStore,
    create_source_settings_router,
    default_source_preferences,
)
from labcat.workspace import WorkspaceStore


@pytest.fixture
def store(tmp_path):
    prefs = SourcePreferencesStore(WorkspaceStore(tmp_path / "workspace.sqlite3"))
    prefs.initialize()
    return prefs


def test_defaults_enable_discovery_and_saved_off_filters_survive_restart(store):
    from labcat.public_sources import catalog

    assert set(SOURCE_IDS) == {source["id"] for source in catalog()}
    assert store.load() == default_source_preferences()
    assert store.load()["search_public_references"] is True
    config = {
        "search_public_references": False,
        "enabled_sources": ["hybrid3", "arxiv"],
        "materials_project_mode": "snapshot",
        "max_results_per_source": 10,
    }
    assert store.save(config) == config
    reopened = SourcePreferencesStore(WorkspaceStore(store.workspace.path))
    reopened.initialize()
    assert reopened.load() == config


@pytest.mark.parametrize(
    "change",
    [
        {"url": "http://localhost/private"},
        {"allow_paywalled": True},
        {"enabled_sources": ["user_upload"]},
        {"enabled_sources": ["arxiv", "arxiv"]},
        {"enabled_sources": [True]},
        {"enabled_sources": "arxiv"},
        {"search_public_references": 1},
        {"search_public_references": "yes"},
        {"max_results_per_source": True},
        {"max_results_per_source": 0},
        {"max_results_per_source": 11},
        {"max_results_per_source": 1.5},
        {"materials_project_mode": "private"},
        {"materials_project_mode": {"url": "https://invalid.test/"}},
    ],
)
def test_settings_api_rejects_unknown_sources_urls_and_policy_fields(store, change):
    app = FastAPI()
    app.include_router(create_source_settings_router(store))
    with TestClient(app) as client:
        assert client.get("/api/source-settings").json() == default_source_preferences()
        assert (
            client.put(
                "/api/source-settings", json={**store.load(), **change}
            ).status_code
            == 422
        )
        assert client.get("/api/source-settings").json() == default_source_preferences()


def test_api_mode_cannot_be_saved_without_a_verified_connection(
    store,
):
    config = {**store.load(), "enabled_sources": [], "materials_project_mode": "api"}
    app = FastAPI()
    app.include_router(create_source_settings_router(store))
    with TestClient(app) as client:
        response = client.put("/api/source-settings", json=config)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "source_connection_required"
        assert store.load() == default_source_preferences()


def test_corrupt_source_preferences_are_not_silently_reset(store):
    with store.workspace._connection(write=True) as connection:
        connection.execute(
            "INSERT INTO source_preferences VALUES(1,?)",
            ("{corrupt-private-test-value",),
        )
    app = FastAPI()
    app.include_router(create_source_settings_router(store))
    with TestClient(app) as client:
        response = client.get("/api/source-settings")
        assert response.status_code == 503
        assert "private-test-value" not in response.text
    with store.workspace._connection() as connection:
        assert (
            connection.execute("SELECT value FROM source_preferences").fetchone()[0]
            == "{corrupt-private-test-value"
        )
    with pytest.raises(sqlite3.DatabaseError):
        store.load()
