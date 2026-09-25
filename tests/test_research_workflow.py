"""Public research results survive project reuse without trusting chat
text."""

import sqlite3
from copy import deepcopy

import pytest

from labcat.config import load_config
from labcat.research import research
from labcat.workspace import WorkspaceConflict, WorkspaceStore

pytestmark = pytest.mark.usefixtures(
    "authenticated_app_models", "authenticated_research"
)


PROMPT = "Find oxide dielectric candidates for thin-film experiments."


@pytest.fixture
def historical_property_fixture(monkeypatch):
    """Explicit test transport for persistence checks, never a
    production fallback."""
    from labcat import science

    historical = science.load_snapshot()
    monkeypatch.setattr(science, "retrieve_nomad", lambda filters: deepcopy(historical))


def test_move_reuses_destination_sources_and_preserves_research_audit(
    tmp_path, historical_property_fixture
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    projects = [store.create_project(name) for name in ("A", "B")]
    chats = [store.create_global_chat("Chat", p["id"]) for p in projects]
    outcome = research(PROMPT, load_config())
    for chat, project in zip(chats, projects, strict=True):
        store.append_research(chat["id"], project["id"], PROMPT, outcome)
    before = store.get_global_chat(chats[0]["id"])
    moved = store.move_chat(chats[0]["id"], projects[1]["id"])
    assert moved["reports"][0]["result"] == before["reports"][0]["result"]
    destination = store.get_global_chat(chats[1]["id"])
    assert {s["id"] for s in moved["sources"]} == {
        s["id"] for s in destination["sources"]
    }
    with pytest.raises(WorkspaceConflict):
        store.append_research(chats[0]["id"], projects[0]["id"], PROMPT, outcome)
    assert len(store.get_global_chat(chats[0]["id"])["messages"]) == 2


def test_v2_migration_retains_pins_then_accepts_scientific_results(
    tmp_path, historical_property_fixture
):
    path = tmp_path / "workspace.sqlite3"
    old = WorkspaceStore(path)
    p = old.create_project("Legacy")
    chat = old.create_chat(p["id"], "Preserve me")
    detail = old.append_message(p["id"], chat["id"], "Old request", load_config())
    old.set_pin(p["id"], "report", detail["reports"][0]["id"])
    # Reconstruct the actual earlier CHECK constraint without deleting dependents.
    with sqlite3.connect(path) as c:
        for view in ("visible_sources", "visible_reports", "visible_chats"):
            c.execute(f"DROP VIEW {view}")
        for table in ("manual_chat_titles", "archived_chats", "archived_projects"):
            c.execute(f"DROP TABLE {table}")
        definition = c.execute(
            "SELECT sql FROM sqlite_master WHERE name='reports'"
        ).fetchone()[0]
        definition = definition.replace(
            "CREATE TABLE reports", "CREATE TABLE legacy_reports"
        ).replace("'scaffold', 'complete', 'partial', 'blocked'", "'scaffold'")
        c.execute(definition)
        c.execute("INSERT INTO legacy_reports SELECT * FROM reports")
        c.execute("DROP TABLE research_runs")
        c.execute("DROP TABLE source_records")
        c.execute("DROP TABLE reports")
        c.execute("ALTER TABLE legacy_reports RENAME TO reports")
        c.execute("PRAGMA user_version=2")
    migrated = WorkspaceStore(path)
    assert migrated.contents(p["id"])["reports"][0]["pinned"]
    result = migrated.append_research(
        chat["id"], p["id"], PROMPT, research(PROMPT, load_config())
    )
    assert len(result["reports"]) == 2
    assert result["reports"][1]["result"]["candidates"]
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
