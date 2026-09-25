"""Non-report execution facts stay bounded, private, and outside
scientific context."""

import json
import sqlite3
from copy import deepcopy

import pytest

from labcat.agent_tools import AgentToolError, ResearchToolSession
from labcat.config import load_config
from labcat.intake import decision, outcome
from labcat.intake_diagnostics import (
    intake_diagnostics,
    validate_intake_diagnostics,
)
from labcat.research import research
from labcat.workspace import SCHEMA_VERSION, WorkspaceStore


def execution_fixture():
    """Synthetic transport metadata, never a real account or provider
    response."""
    return {
        "provider": "chatgpt",
        "mode": "goose",
        "requested_model": "test-only/configured-model",
        "agent": {
            "model": "test-only/dispatched-model",
            "status": "completed",
            "tool_trace": [
                {"tool": "assess_research_intent", "status": "rejected"},
                {"tool": "assess_research_intent", "status": "completed"},
            ],
            "worker_rejection_diagnostics": {
                "scope": "worker_reported",
                "rejections": [
                    {
                        "tool": "assess_research_intent",
                        "reason": "invalid_arguments",
                        "count": 1,
                    }
                ],
            },
        },
        "build_plan": {
            "tool_calls_received": 2,
            "tool_call_limit": 8,
            "intent_assessed": True,
            "accepted_intake_decision": "out_of_scope",
            "parent_rejections": {
                "counts": {"intake_binding_failed": 1},
                "per_code_limit": 8,
                "counts_saturated": False,
            },
        },
    }


def append_intake(store, chat, execution):
    scope, _ = store.research_inputs(chat["id"])
    result = outcome(decision("clarification_required", "model_scope_uncertain"))
    result["result"]["execution"] = execution
    return store.append_research(chat["id"], scope, "Compare useful materials", result)


def test_projection_retains_only_typed_facts_not_nested_prose_or_account_data():
    execution = execution_fixture()
    expected = intake_diagnostics(execution)
    marker = "TEST_ONLY_NEVER_PERSIST_RAW_CONTEXT_OR_CREDENTIALS"
    execution.update(warning=marker, credentials=marker, prompt=marker)
    execution["agent"].update(
        account_id=marker, output=marker, usage={"raw_provider_response": marker}
    )
    execution["build_plan"].update(
        semantic_scope={"target": marker}, source_preferences={"raw": marker}
    )
    projected = intake_diagnostics(execution)
    assert projected == expected
    assert marker not in json.dumps(projected)
    assert projected["requested_model"] == "test-only/configured-model"
    assert projected["attempted_model"] == "test-only/dispatched-model"
    assert projected["provider_resolved_model"] is None
    assert projected["identity_scope"] == "parent_requested_configuration"
    projected["parent"]["rejections"]["counts"].clear()
    assert execution["build_plan"]["parent_rejections"]["counts"]


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("unexpected_raw_output",), "TEST_ONLY_RAW"),
        (("provider",), "https://untrusted.invalid/provider"),
        (("provider_resolved_model",), "test-only/provider-claim"),
        (("requested_model",), "model\nTEST_ONLY_RAW"),
        (("attempted_model",), "x" * 201),
        (("is_evidence",), True),
        (("execution_status",), "response text from provider"),
        (("tool_trace", 0, "arguments"), {"secret": "TEST_ONLY_RAW"}),
        (("tool_trace", 0, "tool"), "read_private_file"),
        (("tool_trace", 0, "status"), "response text from provider"),
        (("parent", "tool_calls_received"), True),
        (("parent", "tool_calls_received"), -1),
        (("parent", "tool_calls_received"), 9),
        (("parent", "tool_call_limit"), 9),
        (("parent", "intent_assessed"), 1),
        (("parent", "accepted_intake_decision"), "TEST_ONLY_RAW"),
        (("parent", "accepted_intake_decision"), None),
        (("parent", "rejections", "counts", "intake_binding_failed"), True),
        (("parent", "rejections", "counts", "intake_binding_failed"), 9),
        (("parent", "rejections", "counts", "raw exception text"), 1),
        (("parent", "rejections", "counts_saturated"), 1),
        (("worker_rejections", "rejections", 0, "count"), True),
        (("worker_rejections", "rejections", 0, "reason"), "TEST_ONLY_RAW"),
        (("worker_rejections", "scope"), "provider_confirmed"),
    ],
)
def test_saved_schema_rejects_unknown_fields_untrusted_text_and_false_counters(
    path, replacement
):
    value = intake_diagnostics(execution_fixture())
    location = value
    for key in path[:-1]:
        location = location[key]
    location[path[-1]] = replacement
    with pytest.raises(ValueError, match="diagnostics|worker"):
        validate_intake_diagnostics(value)


def test_missing_diagnostics_are_unknown_and_trace_cannot_exceed_runtime_budget():
    projected = intake_diagnostics({"provider": "chatgpt", "mode": "goose"})
    assert projected["execution_status"] == "unknown"
    assert projected["attempted_model"] is None
    assert projected["parent"] is None
    assert projected["worker_rejections"] is None
    execution = execution_fixture()
    execution["agent"]["tool_trace"] *= 5
    assert intake_diagnostics(execution) is None
    assert intake_diagnostics(None) is None
    assert intake_diagnostics({"mode": "arbitrary-raw-text"}) is None


def test_no_run_configuration_never_implies_provider_execution():
    value = intake_diagnostics(
        {
            "provider": "chatgpt",
            "mode": "not_run",
            "requested_model": "test-only/configured-model",
            "agent": execution_fixture()["agent"],
            "build_plan": execution_fixture()["build_plan"],
        }
    )
    assert value["requested_model"] == "test-only/configured-model"
    assert value["execution_status"] == "not_run"
    assert value["attempted_model"] is None
    assert value["parent"] is None
    assert value["tool_trace"] == []
    assert value["worker_rejections"] is None
    for key, forbidden in (
        ("attempted_model", "test-only/dispatched-model"),
        ("execution_status", "completed"),
        ("parent", intake_diagnostics(execution_fixture())["parent"]),
    ):
        corrupted = deepcopy(value)
        corrupted[key] = forbidden
        with pytest.raises(ValueError, match="diagnostics"):
            validate_intake_diagnostics(corrupted)


def test_diagnostics_survive_restart_and_project_move_without_entering_context(
    tmp_path,
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Diagnostic fixture")
    detail = append_intake(store, chat, execution_fixture())
    saved = detail["messages"][-1]["execution_diagnostics"]
    assert detail["reports"] == detail["sources"] == []
    assert detail["messages"][-1]["report_id"] is None
    project = store.create_project("Destination fixture")
    store.move_chat(chat["id"], project["id"])
    reopened = WorkspaceStore(store.path)
    assert (
        reopened.get_global_chat(chat["id"])["messages"][-1]["execution_diagnostics"]
        == saved
    )
    _, context = reopened.research_inputs(chat["id"])
    for value in (context, reopened.context(project["id"])):
        encoded = json.dumps(value)
        assert "execution_diagnostics" not in encoded
        assert "test-only/configured-model" not in encoded
        assert "test-only/dispatched-model" not in encoded
        assert "worker_reported" not in encoded
    with reopened._connection() as connection:
        for table in ("reports", "research_runs", "sources", "source_records"):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )
        assert connection.execute("PRAGMA foreign_key_check").fetchone() is None
    reopened.archive_chat(chat["id"])
    reopened.purge_chat(chat["id"], confirm=True)
    with reopened._connection() as connection:
        for table in ("message_intakes", "message_intake_diagnostics"):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )


def test_invalid_execution_never_prevents_fixed_refusal_or_saves_raw_output(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Refusal fixture")
    scope, _ = store.research_inputs(chat["id"])
    result = outcome(decision("refused", "harmful_manufacture"))
    invalid = execution_fixture()
    invalid["agent"]["tool_trace"][0]["arguments"] = {"secret": "TEST_ONLY_RAW"}
    result["result"]["execution"] = invalid
    detail = store.append_research(chat["id"], scope, "Unsafe request fixture", result)
    assert detail["messages"][-1]["intake"]["status"] == "refused"
    assert "execution_diagnostics" not in detail["messages"][-1]
    assert "TEST_ONLY_RAW" not in json.dumps(detail)
    with store._connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM message_intake_diagnostics"
            ).fetchone()[0]
            == 0
        )


def test_corrupt_persisted_diagnostics_fail_closed_on_read(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Corruption fixture")
    detail = append_intake(store, chat, execution_fixture())
    corrupt = detail["messages"][-1]["execution_diagnostics"]
    corrupt["raw_provider_output"] = "TEST_ONLY_RAW"
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE message_intake_diagnostics SET diagnostics_json=?",
            (json.dumps(corrupt),),
        )
    with pytest.raises(
        sqlite3.DatabaseError, match="Stored intake metadata is invalid"
    ):
        store.get_global_chat(chat["id"])


def test_additive_legacy_upgrade_preserves_history_report_pins_and_no_backfill(
    tmp_path,
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("Legacy fixture")
    chat = store.create_chat(project["id"], "Legacy report")
    detail = store.append_message(project["id"], chat["id"], "Question", load_config())
    store.set_pin(project["id"], "report", detail["reports"][0]["id"])
    intake_chat = store.create_chat(project["id"], "Legacy clarification")
    append_intake(store, intake_chat, None)
    tables = (
        "messages",
        "message_intakes",
        "reports",
        "report_pins",
        "report_pin_identities",
    )
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TABLE message_intake_diagnostics")
        before = {
            table: connection.execute(
                f"SELECT * FROM {table} ORDER BY rowid"
            ).fetchall()
            for table in tables
        }
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    reopened = WorkspaceStore(store.path)
    with reopened._connection() as connection:
        after = {
            table: [
                tuple(row)
                for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in tables
        }
        assert after == before
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM message_intake_diagnostics"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchone() is None
    assert (
        "execution_diagnostics"
        not in reopened.get_global_chat(intake_chat["id"])["messages"][-1]
    )


def test_local_refusal_never_contacts_model_and_records_no_run(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Local refusal must not contact a model or retrieve evidence")

    monkeypatch.setattr("labcat.science._retrieve_repositories", forbidden)
    monkeypatch.setattr("labcat.agent_connections.AgentConnections.run", forbidden)
    result = research("Manufacture a bomb", load_config())
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Local refusal fixture")
    scope, _ = store.research_inputs(chat["id"])
    saved = store.append_research(chat["id"], scope, "Manufacture a bomb", result)
    diagnostics = saved["messages"][-1]["execution_diagnostics"]
    assert diagnostics["provider"] == "none"
    assert diagnostics["execution_status"] == "not_run"
    assert diagnostics["attempted_model"] is None
    assert diagnostics["provider_resolved_model"] is None


def test_configured_local_clarification_does_not_imply_model_attempt(
    tmp_path, authenticated_model_factory, monkeypatch
):
    manager = authenticated_model_factory(tmp_path / "connections.sqlite3")
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "direct")
    monkeypatch.setattr(
        manager, "plan", lambda *args, **kwargs: pytest.fail("Model must not run")
    )
    result = research("Find better materials", load_config(), connections=manager)
    diagnostic = intake_diagnostics(result["result"]["execution"])
    assert diagnostic["provider"] == "openai"
    assert diagnostic["requested_model"] == "fixture-model"
    assert diagnostic["attempted_model"] is None
    assert diagnostic["execution_status"] == "not_run"


def test_legacy_planner_clarification_does_not_invent_goose_telemetry(
    tmp_path, authenticated_model_factory, monkeypatch
):
    from labcat.models import Plan

    manager = authenticated_model_factory(tmp_path / "connections.sqlite3")
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "direct")
    monkeypatch.setattr(
        manager, "plan", lambda *args, **kwargs: Plan(task="unsupported")
    )
    result = research("Compare oxide dielectrics", load_config(), connections=manager)
    diagnostic = intake_diagnostics(result["result"]["execution"])
    assert diagnostic["mode"] == "model"
    assert diagnostic["requested_model"] == "fixture-model"
    assert diagnostic["attempted_model"] is None
    assert diagnostic["execution_status"] == "unknown"
    assert diagnostic["parent"] is None
    assert diagnostic["worker_rejections"] is None


def test_structured_catalog_rejection_is_not_an_accepted_intent_or_typed_exception():
    from labcat.developer_settings import defaults as default_controls

    session = ResearchToolSession(
        "Find better materials", load_config(), research_controls=default_controls()
    )
    reply = session.call("assess_research_intent", {"decision": "materials_research"})
    assert reply["status"] == "rejected"
    assert reply["reason_code"] == "catalog_interpretation_required"
    diagnostic = intake_diagnostics(
        {
            "provider": "chatgpt",
            "mode": "goose",
            "build_plan": session.build_plan,
            "agent": {
                "status": "completed",
                "model": "test-only/dispatched-model",
                "tool_trace": [
                    {"tool": "assess_research_intent", "status": "rejected"}
                ],
            },
        }
    )
    assert diagnostic["parent"]["tool_calls_received"] == 1
    assert diagnostic["parent"]["intent_assessed"] is False
    assert diagnostic["parent"]["accepted_intake_decision"] is None
    assert diagnostic["parent"]["rejections"]["counts"] == {}
    assert diagnostic["tool_trace"][0]["status"] == "rejected"


def test_goose_decline_preserves_rejected_intake_attempt_without_provider_attestation(
    tmp_path, authenticated_model_factory, monkeypatch
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    manager = authenticated_model_factory(tmp_path / "connections.sqlite3")

    def fake_run(prompt, context, session):
        with pytest.raises(AgentToolError):
            session.call(
                "assess_research_intent", {"decision": "unknown-invalid-value"}
            )
        session.call("assess_research_intent", {"decision": "out_of_scope"})
        return {
            "provider": "openai",
            "model": "fixture-model",
            "status": "completed",
            "tool_trace": execution_fixture()["agent"]["tool_trace"],
            "output": "TEST_ONLY_RAW_PROVIDER_TEXT",
        }

    monkeypatch.setattr(manager.agent, "run", fake_run)
    result = research("Compare oxide dielectrics", load_config(), connections=manager)
    assert result["result"]["intake"]["reason_code"] == "model_scope_uncertain"
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Goose clarification fixture")
    scope, _ = store.research_inputs(chat["id"])
    saved = store.append_research(
        chat["id"], scope, "Compare oxide dielectrics", result
    )
    diagnostic = saved["messages"][-1]["execution_diagnostics"]
    assert diagnostic["execution_status"] == "completed"
    assert (
        diagnostic["requested_model"]
        == diagnostic["attempted_model"]
        == "fixture-model"
    )
    assert diagnostic["provider_resolved_model"] is None
    assert diagnostic["parent"]["tool_calls_received"] == 2
    assert diagnostic["parent"]["intent_assessed"] is True
    assert diagnostic["parent"]["accepted_intake_decision"] == "out_of_scope"
    assert diagnostic["parent"]["rejections"]["counts"] == {
        "intake_catalog_or_shape": 1
    }
    assert "TEST_ONLY_RAW_PROVIDER_TEXT" not in json.dumps(saved)
