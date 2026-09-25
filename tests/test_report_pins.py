"""Immutable report snapshots, live project pins and active-chat
context."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from labcat.config import load_config
from labcat.models import bounded_context
from labcat.workspace import (
    SCHEMA_VERSION,
    WorkspaceNotFound,
    WorkspacePinConflict,
    WorkspaceStore,
)
from labcat.workspace_api import create_router


@pytest.fixture
def workspace(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("Fixture project")
    chat = store.project_draft(project["id"])
    return store, project["id"], chat["id"]


def revision(store, project_id, chat_id, label, *, stage="complete"):
    """Test-only revision metadata; no real material facts or
    retrieval."""
    scope = project_id if project_id is not None else store.research_inputs(chat_id)[0]
    detail = store.append_research(
        chat_id,
        scope,
        label,
        {
            "stage": stage,
            "answer": "Fixture response",
            "pi_summary": f"Fixture summary {label}",
            "technical_audit": f"Fixture technical {label}",
            "sources": [],
            "result": {
                "stage": stage,
                "execution": {"presentation": load_config().to_dict()["presentation"]},
            },
        },
    )
    return detail["reports"][-1]


def source_fixture(store, scope, chat_id, *, verified=True):
    source_id = uuid4().hex
    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
            (
                source_id,
                scope,
                "Fixture source; not scientific evidence",
                "https://example.invalid/fixture",
                "Test adapter",
                "public",
                "verified" if verified else "unverified",
                "2026-01-01T00:00:00Z",
            ),
        )
        connection.execute(
            "INSERT INTO chat_sources VALUES (?,?,?)", (scope, chat_id, source_id)
        )
        connection.execute(
            "INSERT INTO source_records VALUES (?,?,?)",
            (scope, source_id, f"fixture:{source_id}"),
        )
    return source_id


def test_snapshot_stays_frozen_tracking_advances_and_new_snapshot_is_independent(
    workspace,
):
    store, project, chat = workspace
    first = revision(store, project, chat, "First")
    store.set_pin(project, "report", first["id"])
    frozen = store.contents(project)["reports"][0]
    from labcat.settings import SettingsStore, preferences

    settings = preferences(load_config())
    settings["presentation"]["layout"]["accent"] = "slate"
    SettingsStore(store, load_config()).save(settings)
    tracking = store.set_report_tracking(project, chat)
    assert store.set_report_tracking(project, chat) == tracking
    second = revision(store, project, chat, "Second", stage="partial")
    # Neither an unsuccessful research attempt nor changing global UI preferences
    # can redirect the live pin or alter an earlier report revision.
    revision(store, project, chat, "Blocked", stage="blocked")
    contents = store.contents(project)["reports"]
    snapshot, latest = contents
    assert snapshot["pin"] == frozen["pin"]
    assert snapshot["id"] == first["id"]
    assert snapshot["pi_summary"] == first["pi_summary"]
    assert snapshot["result"] == first["result"]
    assert latest["id"] == second["id"]
    assert latest["pin"]["id"] == tracking["id"]
    assert latest["pin"]["mode"] == "latest"
    assert store.get_global_chat(chat)["report_tracking"] == latest["pin"]
    assert store.get_global_chat(chat)["chat"]["pin_counts"]["reports"] == 2
    store.set_pin(project, "report", second["id"])
    contents = store.contents(project)["reports"]
    assert len(contents) == 3
    assert len({report["pin"]["id"] for report in contents}) == 3
    assert [report["id"] for report in contents].count(second["id"]) == 2
    assert store.list_projects()[0]["pin_counts"]["reports"] == 3
    reopened = WorkspaceStore(store.path)
    assert reopened.contents(project) == store.contents(project)


def test_update_snapshot_is_explicit_atomic_and_preserves_pin_identity(workspace):
    store, project, chat = workspace
    first = revision(store, project, chat, "First")
    store.set_pin(project, "report", first["id"])
    old = store.contents(project)["reports"][0]["pin"]
    second = revision(store, project, chat, "Second")
    updated = store.replace_report_snapshot(
        project, old["id"], expected_report_id=first["id"], report_id=second["id"]
    )
    assert updated["id"] == old["id"]
    assert updated["created_at"] == old["created_at"]
    assert updated["updated_at"] >= old["updated_at"]
    assert store.contents(project)["reports"][0]["id"] == second["id"]
    # Revisions remain available in chat history after a pin moves.
    assert [item["pi_summary"] for item in store.get_global_chat(chat)["reports"]] == [
        first["pi_summary"],
        second["pi_summary"],
    ]
    with pytest.raises(WorkspacePinConflict, match="changed"):
        store.replace_report_snapshot(
            project, old["id"], expected_report_id=first["id"], report_id=second["id"]
        )
    store.set_pin(project, "report", first["id"])
    with pytest.raises(WorkspacePinConflict, match="already has"):
        store.replace_report_snapshot(
            project, old["id"], expected_report_id=second["id"], report_id=first["id"]
        )
    assert store.contents(project)["reports"][0]["pin"] == updated


def test_concurrent_snapshot_replacements_have_exactly_one_winner(workspace):
    store, project, chat = workspace
    first = revision(store, project, chat, "First")
    store.set_pin(project, "report", first["id"])
    pin_id = store.contents(project)["reports"][0]["pin"]["id"]
    targets = [revision(store, project, chat, label)["id"] for label in ("A", "B")]
    barrier = Barrier(2)

    def replace(target):
        barrier.wait(timeout=5)
        try:
            return store.replace_report_snapshot(
                project, pin_id, expected_report_id=first["id"], report_id=target
            )
        except WorkspacePinConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(replace, targets))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert store.contents(project)["reports"][0]["pin"] == winners[0]
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_scope_and_completed_revision_checks_cannot_retarget_other_chats(workspace):
    store, project, chat = workspace
    with pytest.raises(WorkspacePinConflict, match="completed report"):
        store.set_report_tracking(project, chat)
    first = revision(store, project, chat, "First")
    store.set_pin(project, "report", first["id"])
    pin = store.contents(project)["reports"][0]["pin"]
    other_chat = store.create_chat(project, "Other")["id"]
    other = revision(store, project, other_chat, "Other report")
    blocked = revision(store, project, chat, "Failure", stage="blocked")
    foreign_project = store.create_project("Foreign")["id"]
    for target in (other["id"], blocked["id"], "missing"):
        with pytest.raises(WorkspaceNotFound):
            store.replace_report_snapshot(
                project, pin["id"], expected_report_id=first["id"], report_id=target
            )
    for target_project in (foreign_project, "missing"):
        with pytest.raises(WorkspaceNotFound):
            store.set_report_tracking(target_project, chat)
        with pytest.raises(WorkspaceNotFound):
            store.replace_report_snapshot(
                target_project,
                pin["id"],
                expected_report_id=first["id"],
                report_id=first["id"],
            )


@pytest.mark.parametrize("remove_project", [False, True])
def test_remove_restore_and_permanent_delete_cover_both_pin_modes(
    workspace, remove_project
):
    store, project, chat = workspace
    first = revision(store, project, chat, "First")
    store.set_pin(project, "report", first["id"])
    store.set_report_tracking(project, chat)
    before = store.contents(project)
    if remove_project:
        store.archive_project(project)
        assert store.removed_items()["projects"][0]["pin_counts"]["reports"] == 2
        with pytest.raises(WorkspaceNotFound):
            store.contents(project)
        store.restore_project(project)
    else:
        store.archive_chat(chat)
        assert store.contents(project)["reports"] == []
        assert store.context(project)["reports"] == []
        assert store.list_projects()[0]["pin_counts"]["reports"] == 0
        assert store.removed_items()["chats"][0]["pin_counts"]["reports"] == 2
        store.restore_chat(chat)
    assert store.contents(project) == before
    if remove_project:
        store.archive_project(project)
        store.purge_project(project, confirm=True)
    else:
        store.archive_chat(chat)
        store.purge_chat(chat, confirm=True)
    with sqlite3.connect(store.path) as connection:
        for table in ("report_pins", "report_pin_identities", "tracked_report_pins"):
            assert connection.execute(f"SELECT * FROM {table}").fetchall() == []
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_move_and_detach_remove_old_project_pins_without_moving_source_pin(workspace):
    store, project, chat = workspace
    report = revision(store, project, chat, "First")
    source = source_fixture(store, project, chat)
    store.set_pin(project, "source", source)
    store.set_pin(project, "report", report["id"])
    store.set_report_tracking(project, chat)
    destination = store.create_project("Destination")["id"]
    moved = store.move_chat(chat, destination)
    assert moved["reports"][0]["snapshot_pin"] is None
    assert moved["report_tracking"] is None
    assert store.contents(project)["reports"] == []
    assert store.contents(project)["sources"][0]["id"] == source
    store.set_report_tracking(destination, chat)
    store.move_chat(chat, None)
    assert store.contents(destination)["reports"] == []
    assert store.get_global_chat(chat)["report_tracking"] is None


def test_v4_migration_preserves_old_snapshot_content_date_and_idempotence(workspace):
    store, project, chat = workspace
    report = revision(store, project, chat, "Before migration")
    store.set_pin(project, "report", report["id"])
    with sqlite3.connect(store.path) as connection:
        before = connection.execute("SELECT * FROM report_pins").fetchall()
        connection.execute("DROP TABLE report_pin_identities")
        connection.execute("DROP TABLE tracked_report_pins")
        connection.execute("PRAGMA user_version=4")
    reopened = WorkspaceStore(store.path)
    snapshot = reopened.contents(project)["reports"][0]
    assert snapshot["id"] == report["id"]
    assert snapshot["pi_summary"] == report["pi_summary"]
    assert snapshot["pin"]["mode"] == "snapshot"
    assert WorkspaceStore(store.path).contents(project)["reports"][0] == snapshot
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT * FROM report_pins").fetchall() == before
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_api_contract_and_stale_snapshot_error(workspace):
    store, project, chat = workspace
    first = revision(store, project, chat, "First")
    second = revision(store, project, chat, "Second")
    app = FastAPI()
    app.include_router(create_router(store, load_config()))
    base = f"/api/projects/{project}"
    with TestClient(app) as client:
        assert (
            client.post(
                f"{base}/pins", json={"kind": "report", "target_id": first["id"]}
            ).status_code
            == 201
        )
        tracking = client.put(f"{base}/tracked-reports/{chat}", json={})
        assert tracking.status_code == 200
        assert tracking.json()["report_id"] == second["id"]
        contents = client.get(f"{base}/contents").json()
        pin = contents["reports"][0]["pin"]
        body = {"expected_report_id": first["id"], "report_id": second["id"]}
        assert (
            client.put(f"{base}/report-pins/{pin['id']}", json=body).status_code == 200
        )
        assert (
            client.put(f"{base}/report-pins/{pin['id']}", json=body).status_code == 409
        )
        assert (
            client.put(
                f"{base}/report-pins/{pin['id']}", json={**body, "prose": "overwrite"}
            ).status_code
            == 422
        )
        assert client.delete(f"{base}/tracked-reports/{chat}").status_code == 204
        assert len(client.get(f"{base}/contents").json()["reports"]) == 1


def test_active_chat_wins_over_recent_project_activity_without_creating_evidence(
    workspace,
):
    store, project, chat = workspace
    active_report = revision(store, project, chat, "ACTIVE_CONTEXT")
    active_source = source_fixture(store, project, chat)
    unverified = source_fixture(store, project, chat, verified=False)
    store.set_pin(project, "source", unverified)
    profile = {
        "id": "preset-fixture",
        "name": "Fixture preference",
        "importance": {"band_gap": 0.5},
    }
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE research_runs SET outcome_json=? "
            "WHERE report_id=? AND project_id=?",
            (
                json.dumps(
                    {
                        "execution": {"ranking_profile": profile},
                        "candidates": [{"must_not_copy": True}],
                    }
                ),
                active_report["id"],
                project,
            ),
        )
    other_chat = store.create_chat(project, "Other")["id"]
    for index in range(22):
        report = revision(store, project, other_chat, f"OTHER_CONTEXT_{index}")
        store.set_pin(project, "report", report["id"])
    foreign = store.create_global_chat("Foreign")
    store.append_global_message(foreign["id"], "FOREIGN_CONTEXT", load_config())
    scope, context = store.research_inputs(chat)
    assert scope == project
    assert context["messages"][-2]["content"] == "ACTIVE_CONTEXT"
    assert context["reports"][-1]["id"] == active_report["id"]
    assert context["sources"][-1]["id"] == active_source
    assert unverified not in json.dumps(context["active_chat"])
    assert "FOREIGN_CONTEXT" not in json.dumps(context)
    assert "must_not_copy" not in json.dumps(context)
    assert context["active_chat"]["ranking_profile"] == profile
    assert context["active_chat"]["source_hints"][0]["source_id"] == active_source
    assert (
        context["active_chat"]["source_hints"][0]["reuse_requires_adapter_validation"]
        is True
    )
    assert context["project_pins"]["reports"]
    assert all(
        item["is_evidence"] is False
        for item in context["messages"] + context["reports"] + context["sources"]
    )
    bounded = bounded_context(context)
    assert bounded["messages"][-2]["content"] == "ACTIVE_CONTEXT"
    assert bounded["reports"][-1]["id"] == active_report["id"]
    assert bounded["sources"][-1]["id"] == active_source
    assert "https://" not in json.dumps(bounded)
    assert "technical_audit" not in json.dumps(bounded)


def test_general_chat_retains_its_own_report_sources_and_bounded_history(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("General")
    scope, _ = store.research_inputs(chat["id"])
    first = revision(store, None, chat["id"], "Find oxide materials")
    source = source_fixture(store, scope, chat["id"])
    _, context = store.research_inputs(chat["id"])
    assert context["active_chat"]["latest_completed_report_id"] == first["id"]
    assert context["sources"][0]["id"] == source
    assert context["project_pins"]["reports"] == []
    assert context["intake_messages"][0]["content"] == "Find oxide materials"
    assert context["boundaries"]["user_context_is_evidence"] is False


def test_latest_report_material_source_wins_context_budget_and_private_hints_are_absent(
    workspace,
):
    store, project, chat = workspace
    report = revision(store, project, chat, "Current fixture report")
    material = source_fixture(store, project, chat)
    for _ in range(25):
        reference = source_fixture(store, project, chat)
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "INSERT INTO source_annotations VALUES (?,?,?)",
                (reference, project, json.dumps({"kind": "discovery_reference"})),
            )
    private = source_fixture(store, project, chat)
    store.set_pin(project, "source", private)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO report_sources VALUES (?,?,?)",
            (project, report["id"], material),
        )
        connection.execute(
            "UPDATE sources SET title='PRIVATE_FIXTURE',access_scope='private' "
            "WHERE id=?",
            (private,),
        )
    _, context = store.research_inputs(chat)
    assert len(context["sources"]) == 20
    assert context["sources"][-1]["id"] == material
    assert bounded_context(context)["sources"][-1]["id"] == material
    assert "PRIVATE_FIXTURE" not in json.dumps(context)
    assert private not in json.dumps(context["active_chat"]["source_hints"])
