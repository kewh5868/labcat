"""Local navigation search never performs research or crosses saved
ownership."""

import json
import sqlite3
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from labcat.config import load_config
from labcat.workspace import SEARCH_SNIPPET_LIMIT, WorkspaceStore
from labcat.workspace_api import create_router


@pytest.fixture
def store(tmp_path):
    return WorkspaceStore(tmp_path / "workspace.sqlite3")


def saved_text(
    store, chat, content, *, summary=None, technical="", timestamp="2026-01-01"
):
    """Insert text-only navigation fixtures, not scientific evidence or
    model output."""
    message_id, report_id = uuid4().hex, None
    with store._connection(write=True) as connection:
        scope = store._scope_for_chat(connection, chat["id"])
        connection.execute(
            "INSERT INTO messages VALUES (?,?,?,?,?,?)",
            (message_id, scope, chat["id"], "assistant", content, timestamp),
        )
        if summary is not None:
            report_id = uuid4().hex
            connection.execute(
                "INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    report_id,
                    scope,
                    chat["id"],
                    message_id,
                    "Fixture report",
                    "partial",
                    summary,
                    technical,
                    timestamp,
                ),
            )
    return message_id, report_id


def route_client(store, *, research_workflow=None, config_reader=None):
    app = FastAPI()
    app.include_router(
        create_router(
            store,
            load_config(),
            research_workflow=research_workflow,
            config_reader=config_reader,
        )
    )
    return TestClient(app)


def test_project_names_descriptions_and_chat_titles_use_standard_safe_records(store):
    project = store.create_project("Solar coatings", "Transparent windows")
    other = store.create_project("Electronics", "Solar materials research")
    chat = store.create_global_chat("Solar coating notes", project["id"])
    general = store.create_global_chat("Solar standalone")
    result = store.search("  SoLaR  ")
    assert result["query"] == "SoLaR"
    assert result["has_more"] is False
    assert [item["project"]["id"] for item in result["projects"]] == [
        project["id"],
        other["id"],
    ]
    assert [item["match_field"] for item in result["projects"]] == [
        "name",
        "description",
    ]
    assert result["projects"][0]["project"] == next(
        item for item in store.list_projects() if item["id"] == project["id"]
    )
    by_chat = {item["chat"]["id"]: item for item in result["chats"]}
    assert by_chat[chat["id"]]["project_name"] == "Solar coatings"
    assert by_chat[general["id"]]["project_name"] is None
    assert by_chat[general["id"]]["chat"]["project_id"] is None
    assert by_chat[general["id"]]["chat"] == general
    assert by_chat[chat["id"]]["message_id"] is None
    assert by_chat[chat["id"]]["report_id"] is None
    assert by_chat[chat["id"]]["match_field"] == "title"


def test_message_and_both_report_views_return_matching_owned_ids_and_bounded_excerpt(
    store,
):
    message_chat = store.create_global_chat("Discussion")
    message_id, _ = saved_text(
        store, message_chat, "prefix " * 150 + "target phrase" + " suffix" * 150
    )
    summary_chat = store.create_global_chat("Summary")
    summary_message, summary_report = saved_text(
        store, summary_chat, "unrelated", summary="Summary target phrase details"
    )
    technical_chat = store.create_global_chat("Technical")
    technical_message, technical_report = saved_text(
        store,
        technical_chat,
        "unrelated",
        summary="No summary match",
        technical="Technical target phrase details",
    )
    matches = {
        item["chat"]["id"]: item for item in store.search("target phrase")["chats"]
    }
    assert set(matches) == {
        message_chat["id"],
        summary_chat["id"],
        technical_chat["id"],
    }
    assert matches[message_chat["id"]]["match_field"] == "message"
    assert matches[message_chat["id"]]["message_id"] == message_id
    assert matches[message_chat["id"]]["report_id"] is None
    for chat, message, report in (
        (summary_chat, summary_message, summary_report),
        (technical_chat, technical_message, technical_report),
    ):
        assert matches[chat["id"]]["match_field"] == "report"
        assert matches[chat["id"]]["message_id"] == message
        assert matches[chat["id"]]["report_id"] == report
    for match in matches.values():
        assert "target phrase" in match["snippet"]
        assert len(match["snippet"]) <= SEARCH_SNIPPET_LIMIT
        assert "content" not in match and "result" not in match


def test_title_matches_precede_content_then_recency_and_results_are_deduplicated(store):
    title = store.create_global_chat("Priority material")
    old = store.create_global_chat("Older discussion")
    newer = store.create_global_chat("Newer discussion")
    saved_text(store, title, "Priority message", summary="Priority summary")
    first, _ = saved_text(store, newer, "Priority first", timestamp="2026-01-01")
    latest, _ = saved_text(store, newer, "Priority latest", timestamp="2026-01-02")
    saved_text(store, old, "Unrelated", summary="Priority report")
    with store._connection(write=True) as connection:
        for chat, stamp in (
            (title, "2026-01-01"),
            (old, "2026-01-02"),
            (newer, "2026-01-03"),
        ):
            connection.execute(
                "UPDATE chats SET updated_at=? WHERE id=?", (stamp, chat["id"])
            )
    results = store.search("Priority")["chats"]
    assert [item["chat"]["id"] for item in results] == [
        title["id"],
        newer["id"],
        old["id"],
    ]
    assert results[0]["match_field"] == "title"
    assert results[1]["message_id"] == latest != first
    assert results == store.search("Priority")["chats"]


@pytest.mark.parametrize(
    ("text", "query"),
    [
        ("Straße coating", "STRASSE"),
        ("Électrolyte", "e\u0301LECTROLYTE"),
        ("氧化材料", "氧化"),
        ("SiO₂ notes", "sio2"),
        ("100%_rate", "%_"),
        ("A [literal] (sample)", "[literal] ("),
        ("alpha\n  beta", "alpha beta"),
    ],
)
def test_unicode_whitespace_and_sql_metacharacters_are_literal(store, text, query):
    chat = store.create_global_chat("Notes")
    saved_text(store, chat, "padding " * 80 + text + " ending" * 80)
    results = store.search(query)["chats"]
    assert [item["chat"]["id"] for item in results] == [chat["id"]]
    assert " ".join(text.split()) in results[0]["snippet"]
    assert len(results[0]["snippet"]) <= SEARCH_SNIPPET_LIMIT


def test_sql_wildcards_and_injection_do_not_broaden_matches(store):
    plain = store.create_global_chat("ordinary material")
    special = store.create_global_chat("Literal 100%_coverage")
    assert [item["chat"]["id"] for item in store.search("%_")["chats"]] == [
        special["id"]
    ]
    assert store.search("' OR 1=1 --")["chats"] == []
    assert store.get_global_chat(plain["id"])["chat"]["title"] == "ordinary material"


def test_removed_projects_chats_and_private_standalone_scopes_are_excluded(store):
    project = store.create_project("Needle project", "Needle description")
    nested = store.create_global_chat("Needle nested", project["id"])
    individually_removed = store.create_global_chat("Needle removed")
    general = store.create_global_chat("Needle general")
    for chat in (nested, individually_removed, general):
        saved_text(store, chat, "Needle message", summary="Needle report")
    store.archive_chat(individually_removed["id"])
    store.archive_project(project["id"])
    with store._connection(write=True) as connection:
        connection.execute(
            "UPDATE projects SET name='Private scope marker',"
            "description='Private scope marker' WHERE is_internal=1"
        )
    results = store.search("Needle")
    assert results["projects"] == []
    assert [item["chat"]["id"] for item in results["chats"]] == [general["id"]]
    assert results["chats"][0]["chat"]["project_id"] is None
    assert results["chats"][0]["project_name"] is None
    assert store.search("Private scope marker")["projects"] == []
    assert store.search("Private scope marker")["chats"] == []


def test_mismatched_saved_message_and_report_ownership_cannot_leak_search_hits(store):
    first = store.create_global_chat("First")
    second = store.create_global_chat("Second")
    foreign_message, _ = saved_text(store, second, "Unrelated")
    with sqlite3.connect(store.path) as connection:
        scopes = dict(connection.execute("SELECT id,project_id FROM chats"))
        connection.execute(
            "INSERT INTO messages VALUES (?,?,?,?,?,?)",
            (
                uuid4().hex,
                scopes[second["id"]],
                first["id"],
                "user",
                "Mismatch",
                "2026",
            ),
        )
        connection.execute(
            "INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                scopes[first["id"]],
                first["id"],
                foreign_message,
                "Fixture",
                "partial",
                "Mismatch",
                "Mismatch",
                "2026",
            ),
        )
    assert store.search("Mismatch")["chats"] == []


def test_sources_execution_and_settings_json_are_not_searched_or_returned(store):
    project = store.create_project("Project")
    chat = store.create_global_chat("Conversation", project["id"])
    _, report_id = saved_text(store, chat, "Navigation needle", summary="Unrelated")
    with store._connection(write=True) as connection:
        connection.execute(
            "INSERT INTO research_runs VALUES (?,?,?)",
            (report_id, project["id"], '{"internal":"private marker"}'),
        )
        connection.execute(
            "INSERT INTO app_settings VALUES (1,?)", ('{"internal":"private marker"}',)
        )
        connection.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                project["id"],
                "private marker",
                "https://example.invalid/private-marker",
                "private marker",
                "test_fixture",
                "unverified",
                "2026",
            ),
        )
    assert store.search("private marker")["chats"] == []
    assert store.search("private marker")["projects"] == []
    assert "private marker" not in json.dumps(store.search("needle"))


def test_limits_apply_per_kind_and_has_more_is_true_only_for_omitted_matches(store):
    for index in range(3):
        store.create_project(f"Match project {index}")
        store.create_global_chat(f"Match chat {index}")
    limited = store.search("Match", limit=2)
    assert len(limited["projects"]) == len(limited["chats"]) == 2
    assert limited["has_more"] is True
    full = store.search("Match", limit=3)
    assert len(full["projects"]) == len(full["chats"]) == 3
    assert full["has_more"] is False
    assert store.search("Match project", limit=1)["has_more"] is True
    assert store.search("Match chat", limit=1)["has_more"] is True
    assert store.search("missing", limit=1)["has_more"] is False


def test_blank_query_is_empty_and_search_does_not_write_to_database(store):
    store.create_global_chat("Needle")
    before = store.path.read_bytes()
    for query in ("", " \n\t "):
        assert store.search(query) == {
            "query": "",
            "projects": [],
            "chats": [],
            "has_more": False,
        }
    assert store.search("Needle")["chats"]
    assert store.path.read_bytes() == before


@pytest.mark.parametrize(
    "query,limit", [("x" * 201, 20), (None, 20), ("x", 0), ("x", 51), ("x", True)]
)
def test_direct_store_validation(store, query, limit):
    with pytest.raises(ValueError):
        store.search(query, limit)


def test_route_contract_validation_and_no_model_or_configuration_access(store):
    def unexpected(*args, **kwargs):
        pytest.fail("Saved workspace search must not read model config or run research")

    class NoResearch:
        respond = unexpected

    chat = store.create_global_chat("Needle")
    with route_client(
        store, research_workflow=NoResearch(), config_reader=unexpected
    ) as client:
        response = client.get("/api/workspace/search", params={"q": " Needle "})
        assert response.status_code == 200
        assert response.json() == store.search(" Needle ")
        assert response.json()["chats"][0]["chat"]["id"] == chat["id"]
        assert client.get("/api/workspace/search").json()["chats"] == []
        for params in ({"q": "x" * 201}, {"limit": 0}, {"limit": 51}, {"limit": "bad"}):
            assert client.get("/api/workspace/search", params=params).status_code == 422


def test_search_storage_errors_do_not_expose_private_details(store, monkeypatch):
    def fail(*args):
        raise sqlite3.OperationalError("PRIVATE_DATABASE_PATH")

    monkeypatch.setattr(store, "search", fail)
    with route_client(store) as client:
        response = client.get("/api/workspace/search", params={"q": "query"})
    assert response.status_code == 503
    assert "PRIVATE_DATABASE_PATH" not in response.text
