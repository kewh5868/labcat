"""The direct CLI applies the same workspace deployment and source
limits."""

import importlib
import json

import pytest

from labcat.cli import main
from labcat.developer_settings import DeveloperSettingsStore, defaults
from labcat.source_preferences import (
    SourcePreferencesStore,
    default_source_preferences,
)
from labcat.workspace import WorkspaceStore


def saved_workspace(path, manager):
    workspace = WorkspaceStore(path)
    controls = DeveloperSettingsStore(workspace, manager)
    sources = SourcePreferencesStore(workspace)
    controls.initialize()
    sources.initialize()
    controls.save({**defaults(), "reference_search": False, "allow_preprints": False})
    sources.save(
        {
            **default_source_preferences(),
            "enabled_sources": [],
            "materials_project_mode": "off",
        }
    )
    return workspace


def test_direct_cli_applies_workspace_controls_and_source_selections(
    tmp_path, monkeypatch, capsys, authenticated_model_factory
):
    path = tmp_path / "workspace.sqlite3"
    manager = authenticated_model_factory(path)
    saved_workspace(path, manager)
    monkeypatch.setattr("labcat.connections.ConnectionManager", lambda path: manager)
    module = importlib.import_module("labcat.research")
    monkeypatch.setattr(
        module,
        "_add_public_discovery",
        lambda *args: pytest.fail("Disabled references were requested by the CLI"),
    )
    assert (
        main(
            [
                "research",
                "Compare oxide materials",
                "--connections",
                str(path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)["result"]
    execution = result["execution"]
    assert execution["research_controls"]["reference_search"] is False
    assert execution["source_preferences"]["search_public_references"] is False
    assert execution["source_preferences"]["enabled_sources"] == []
    assert execution["source_preferences"]["materials_project_mode"] == "off"
    assert result["attribute_research"]["status"] == "disabled"


@pytest.mark.parametrize("table", ["developer_settings", "source_preferences"])
def test_direct_cli_fails_closed_on_corrupt_workspace_controls(
    tmp_path, monkeypatch, capsys, authenticated_model_factory, table
):
    path = tmp_path / "workspace.sqlite3"
    manager = authenticated_model_factory(path)
    workspace = saved_workspace(path, manager)
    with workspace._connection(write=True) as connection:
        connection.execute(f"UPDATE {table} SET value='{{}}'")
    monkeypatch.setattr("labcat.connections.ConnectionManager", lambda path: manager)
    monkeypatch.setattr(
        "labcat.research.research",
        lambda *args, **kwargs: pytest.fail("Corrupt controls allowed research"),
    )
    with pytest.raises(SystemExit) as failure:
        main(["research", "Compare materials", "--connections", str(path)])
    assert failure.value.code == 2
    assert (
        "Saved workspace research settings are unavailable" in capsys.readouterr().err
    )
