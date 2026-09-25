"""Saved query snapshots retain their own time, ranking and source
version.

Scientific names and body passages below are explicit synthetic test
fixtures. No model or public network is called.
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_report_source_versions import assert_replays, outcome, report_with_sources

from labcat import research, workspace
from labcat.config import load_config
from labcat.intake import decision
from labcat.intake import outcome as intake_outcome
from labcat.research import ResearchWorkflow
from labcat.web import create_app
from labcat.workspace import WorkspaceStore


@pytest.mark.parametrize("project_chat", [False, True])
def test_followup_queries_keep_timestamped_report_and_source_snapshots(
    tmp_path, monkeypatch, project_chat
):
    initial = datetime(2026, 9, 23, 12, tzinfo=UTC)
    monkeypatch.setattr(workspace, "_now", lambda: initial.isoformat())
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY") if project_chat else None
    chat = store.create_global_chat("TEST ONLY", project["id"] if project else None)
    scope, _ = store.research_inputs(chat["id"])
    snapshots = []
    query_times = []
    for version in range(3):
        submitted = initial + timedelta(minutes=version * 5 + 1)
        completed = submitted + timedelta(minutes=2)
        monkeypatch.setattr(
            workspace, "_now", lambda value=completed: value.isoformat()
        )
        detail = store.append_research(
            chat["id"],
            scope,
            f"TEST ONLY query {version}",
            outcome(version),
            submitted_at=submitted.isoformat(),
        )
        snapshots.append(deepcopy(detail["reports"][-1]))
        query_times.append(submitted.isoformat(timespec="microseconds"))
    # Reopening the store exercises persisted history, not in-memory responses.
    reopened = WorkspaceStore(store.path)
    detail = reopened.get_global_chat(chat["id"])
    assert len(detail["reports"]) == 3
    assert len(detail["messages"]) == 6
    for version, before in enumerate(snapshots):
        user, assistant = detail["messages"][version * 2 : version * 2 + 2]
        assert user["role"] == "user"
        assert user["content"] == f"TEST ONLY query {version}"
        assert user["created_at"] == query_times[version]
        assert assistant["role"] == "assistant"
        assert assistant["report_id"] == before["id"]
        assert assistant["created_at"] == before["created_at"]
        assert datetime.fromisoformat(user["created_at"]) < datetime.fromisoformat(
            assistant["created_at"]
        )
        saved = report_with_sources(reopened, chat["id"], before["id"])
        for key in (
            "message_id",
            "created_at",
            "pi_summary",
            "technical_audit",
            "result",
            "source_ids",
        ):
            assert saved[key] == before[key]
        assert_replays(saved)
    assert len({tuple(report["source_ids"]) for report in detail["reports"]}) == 3
    # Each follow-up changed the assessment; the old ranking was not overwritten.
    evaluations = [item["result"]["literature_evaluation"] for item in snapshots]
    assert evaluations[0] != evaluations[1] != evaluations[2]


@pytest.mark.parametrize("kind", ["report", "clarification", "refusal"])
def test_workflow_uses_accepted_run_time_for_user_and_completion_for_response(
    tmp_path, monkeypatch, kind
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("TEST ONLY")
    workflow = ResearchWorkflow(store, None)
    observed = {}

    def finish_research(*args, **kwargs):
        observed.update(workflow.progress.snapshot(chat["id"]))
        completed = datetime.fromisoformat(observed["started_at"]) + timedelta(
            minutes=2
        )
        monkeypatch.setattr(workspace, "_now", lambda: completed.isoformat())
        if kind == "report":
            return outcome(1)
        status, reason = (
            ("clarification_required", "assessment_missing")
            if kind == "clarification"
            else ("refused", "model_declined")
        )
        return intake_outcome(decision(status, reason))

    monkeypatch.setattr(research, "research", finish_research)
    monkeypatch.setattr(research, "_require_research_setup", lambda *_: None)
    detail = workflow.respond(
        chat["id"],
        "TEST ONLY request",
        load_config(),
        search_reference_structures=False,
    )
    user, assistant = detail["messages"]
    assert observed["status"] == "running"
    assert user["created_at"] == datetime.fromisoformat(
        observed["started_at"]
    ).isoformat(timespec="microseconds")
    assert datetime.fromisoformat(assistant["created_at"]) > datetime.fromisoformat(
        user["created_at"]
    )
    assert bool(detail["reports"]) == (kind == "report")
    if detail["reports"]:
        assert detail["reports"][0]["created_at"] == assistant["created_at"]
    assert (
        WorkspaceStore(store.path).get_global_chat(chat["id"])["messages"]
        == detail["messages"]
    )


@pytest.mark.parametrize("field", ["submitted_at", "created_at", "started_at"])
def test_api_cannot_override_query_timestamps(tmp_path, field):
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    with TestClient(app, base_url="http://localhost") as client:
        chat = client.post("/api/chats", json={"title": "TEST ONLY"}).json()
        path = f"/api/chats/{chat['id']}"
        response = client.post(
            path + "/messages",
            json={"content": "TEST ONLY", field: "2000-01-01T00:00:00+00:00"},
        )
        assert response.status_code == 422
        assert client.get(path).json()["messages"] == []


@pytest.mark.parametrize("submitted", [False, {}, "bad", "2026-09-23T12:00:00"])
def test_invalid_internal_timestamp_cannot_partially_save_an_exchange(
    tmp_path, submitted
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("TEST ONLY")
    scope, _ = store.research_inputs(chat["id"])
    with pytest.raises(ValueError, match="submission timestamp"):
        store.append_research(
            chat["id"], scope, "TEST ONLY", outcome(0), submitted_at=submitted
        )
    detail = store.get_global_chat(chat["id"])
    assert detail["messages"] == detail["reports"] == detail["sources"] == []
