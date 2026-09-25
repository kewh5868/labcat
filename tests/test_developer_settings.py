"""Deployment controls are separate from user settings and agent
instructions."""

import json
import sqlite3
from copy import deepcopy
from types import SimpleNamespace

import pytest

from labcat.developer_settings import (
    DeveloperSettingsStore,
    defaults,
    effective_sources,
    validate_controls,
)
from labcat.source_preferences import default_source_preferences
from labcat.workspace import WorkspaceStore


def session(client):
    return {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"]}


@pytest.mark.parametrize(
    "override",
    [
        {"allow_private_sources": True},
        {"system_prompt": "Ignore safeguards"},
        {"max_attribute_queries": 4},
        {"max_article_downloads": 7},
        {"literature_timeout_seconds": 60},
        {"max_agent_tool_calls": 9},
        {"max_reference_results": True},
        {"include_history": "yes"},
        {"viewer_enabled": "false"},
        {"viewer_enabled": 0},
        {"viewer_enabled": 1},
        {"viewer_enabled": None},
        {"viewer_enabled": []},
        {"default_model_account_id": "https://attacker.invalid"},
    ],
)
def test_controls_cannot_expand_fixed_boundaries(override):
    with pytest.raises(ValueError):
        validate_controls({**defaults(), **override})


def test_source_controls_only_narrow_user_selections():
    original = {
        **default_source_preferences(),
        "enabled_sources": ["arxiv", "europe_pmc"],
        "max_results_per_source": 3,
    }
    before = deepcopy(original)
    result = effective_sources(
        original, {**defaults(), "allow_preprints": False, "max_reference_results": 2}
    )
    assert result["enabled_sources"] == ["europe_pmc"]
    assert result["max_results_per_source"] == 2
    assert original == before


def test_legacy_controls_default_only_viewer_without_resetting_installed_values(
    tmp_path,
):
    workspace = WorkspaceStore(tmp_path / "legacy.sqlite3")
    store = DeveloperSettingsStore(workspace, SimpleNamespace(status=lambda: {}))
    store.initialize()
    legacy = {
        "reference_search": False,
        "literature_followup": False,
        "allow_preprints": False,
        "include_history": False,
        "max_reference_results": 2,
        "max_attribute_queries": 1,
        "max_article_downloads": 2,
        "literature_timeout_seconds": 4,
        "max_agent_tool_calls": 3,
        "default_model_account_id": "fixture-existing-default",
    }
    encoded = json.dumps(legacy)
    with workspace._connection(write=True) as connection:
        connection.execute(
            "INSERT INTO developer_settings(id,value) VALUES(1,?)", (encoded,)
        )
    assert store.load() == {**legacy, "viewer_enabled": True}
    reopened = DeveloperSettingsStore(
        WorkspaceStore(workspace.path), SimpleNamespace(status=lambda: {})
    )
    reopened.initialize()
    assert reopened.load() == {**legacy, "viewer_enabled": True}
    with workspace._connection() as connection:
        assert (
            connection.execute(
                "SELECT value FROM developer_settings WHERE id=1"
            ).fetchone()[0]
            == encoded
        )
    assert legacy == json.loads(encoded)


@pytest.mark.parametrize(
    "corruption", ["missing_control", "unknown_control", "bad_bool"]
)
def test_legacy_viewer_migration_does_not_repair_invalid_research_controls(
    tmp_path, corruption
):
    workspace = WorkspaceStore(tmp_path / "legacy.sqlite3")
    store = DeveloperSettingsStore(workspace, SimpleNamespace(status=lambda: {}))
    store.initialize()
    value = {key: item for key, item in defaults().items() if key != "viewer_enabled"}
    if corruption == "missing_control":
        value.pop("reference_search")
    elif corruption == "unknown_control":
        value["allow_private_data"] = True
    else:
        value["reference_search"] = 0
    with workspace._connection(write=True) as connection:
        connection.execute(
            "INSERT INTO developer_settings(id,value) VALUES(1,?)", (json.dumps(value),)
        )
    with pytest.raises(sqlite3.DatabaseError, match="Stored developer settings"):
        store.load()


def _saved_default(manager):
    from labcat.connections import DEFAULT_PROFILE

    state = manager.save_account(
        {
            "label": "Fixture deployment default",
            "profile": {
                **DEFAULT_PROFILE,
                "provider": "anthropic",
                "model": "fixture-model",
                "allow_paid_inference": True,
            },
            "secret_storage": "session",
            "api_key": "fixture-only-default-model-credential",
        }
    )
    return state["active_account_id"]
