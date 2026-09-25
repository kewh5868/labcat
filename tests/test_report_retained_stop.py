"""A retained server report ends only the bounded model-process
lifecycle."""

import json
import sys
import threading
import time
from contextlib import contextmanager
from copy import deepcopy

import pytest
from test_goose_runtime import Tools, profile
from test_goose_worker_client import result as worker_result
from test_worker_rejection_diagnostics import broker_call, local_broker

from labcat import goose_runtime as runtime
from labcat import goose_worker_client as client
from labcat import science
from labcat.config import load_config
from labcat.models import ModelError
from labcat.research import research
from labcat.science.reporting import _research_completion_lines
from labcat.source_preferences import default_source_preferences
from labcat.workspace import WorkspaceStore


def execute_child(tmp_path, source, signal=None):
    return runtime._execute(
        [sys.executable, "-c", source], {}, tmp_path, b"", report_retained=signal
    )


def test_retained_report_stops_hanging_child_after_one_fixed_grace(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(runtime, "MAX_RUNTIME_SECONDS", 2)
    monkeypatch.setattr(runtime, "REPORT_EXIT_GRACE_SECONDS", 0.1)
    signal = runtime._ReportRetentionSignal()
    timer = threading.Timer(0.1, signal.mark)
    timer.start()
    started = time.monotonic()
    try:
        execution = execute_child(tmp_path, "import time; time.sleep(10)", signal)
    finally:
        timer.join()
    assert execution.stopped_after_report is True
    assert 0.15 <= time.monotonic() - started < 1.5
    retained_at = signal.retained_at
    signal.mark()
    assert signal.retained_at == retained_at  # Replays cannot extend the grace.


def test_retained_report_grace_is_clipped_to_original_runtime_limit(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(runtime, "MAX_RUNTIME_SECONDS", 0.15)
    signal = runtime._ReportRetentionSignal()
    signal.mark()
    started = time.monotonic()
    execution = execute_child(tmp_path, "import time; time.sleep(10)", signal)
    assert execution.stopped_after_report is True
    assert time.monotonic() - started < 1


@pytest.mark.parametrize("late_signal", [False, True])
def test_absent_or_late_report_does_not_turn_deadline_failure_into_success(
    monkeypatch, tmp_path, late_signal
):
    monkeypatch.setattr(runtime, "MAX_RUNTIME_SECONDS", 0.1)
    signal = runtime._ReportRetentionSignal()
    if late_signal:
        signal.retained_at = time.monotonic() + 10
        signal.event.set()
    with pytest.raises(runtime.GooseRuntimeError) as error:
        execute_child(tmp_path, "import time; time.sleep(10)", signal)
    assert error.value.failure_code == "time_limit"


def test_natural_exit_during_grace_retains_validated_final_usage(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "MAX_RUNTIME_SECONDS", 3)
    signal = runtime._ReportRetentionSignal()
    signal.mark()
    document = {
        "metadata": {
            "status": "completed",
            "input_tokens": 13,
            "output_tokens": 7,
            "total_tokens": 20,
        },
        "messages": [{"content": "UNTRUSTED MODEL WRAPUP"}],
    }
    execution = execute_child(tmp_path, f"print({json.dumps(document)!r})", signal)
    assert execution.stopped_after_report is False
    usage = runtime._usage(execution.raw)
    assert usage["input_tokens"] == 13 and usage["total_tokens"] == 20
    assert "UNTRUSTED" not in json.dumps(usage)


@pytest.mark.parametrize("failure", ["process_failed", "output_limit"])
def test_real_process_failures_are_not_hidden_by_retained_report(
    monkeypatch, tmp_path, failure
):
    signal = runtime._ReportRetentionSignal()
    signal.mark()
    monkeypatch.setattr(runtime, "MAX_OUTPUT_BYTES", 100)
    source = (
        "raise SystemExit(3)"
        if failure == "process_failed"
        else "print('PRIVATE' * 1000)"
    )
    with pytest.raises(runtime.GooseRuntimeError) as error:
        execute_child(tmp_path, source, signal)
    assert error.value.failure_code == failure
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize(
    "tool,status,marker,expected",
    [
        ("generate_ranked_report", "completed", True, True),
        ("generate_ranked_report", "rejected", True, False),
        ("generate_ranked_report", "blocked", True, False),
        ("generate_ranked_report", "completed", False, False),
        ("generate_ranked_report", "completed", 1, False),
        ("evaluate_candidate_fit", "completed", True, False),
    ],
)
def test_local_stop_signal_requires_exact_authenticated_generate_reply(
    monkeypatch, tool, status, marker, expected
):
    captured = local_broker(monkeypatch)

    class Session:
        def tool_definitions(self):
            return [
                {"name": name}
                for name in ("generate_ranked_report", "evaluate_candidate_fit")
            ]

        def call(self, name, arguments):
            return {"status": status, "report_retained": marker}

    with runtime._tool_broker(Session()) as (_, token, _, signal):
        broker_call(captured["handler"], token, {"name": tool, "arguments": {}})
        assert signal.event.is_set() is expected


def test_early_generation_with_unproposed_public_documents_does_not_stop_worker(
    monkeypatch,
):
    from test_agent_discovery_refinement import make_session, reference

    session, calls = make_session(monkeypatch, [[reference(1, "TESTONLY-Alpha")]])
    captured = local_broker(monkeypatch)
    with runtime._tool_broker(session) as (_, token, _, signal):
        reply = broker_call(
            captured["handler"],
            token,
            {"name": "generate_ranked_report", "arguments": {}},
        )
        assert calls and session._lead_documents()
        assert reply["status"] == "rejected"
        assert reply.get("report_retained") is not True
        assert session.report_retained is False
        assert signal.event.is_set() is False


def stopped_result():
    return {
        **worker_result(),
        "status": "stopped_after_report",
        "usage": None,
        "stop_reason": "server_report_retained",
    }


TRACE = [{"tool": "generate_ranked_report", "status": "completed"}]


def test_parent_validates_controlled_stop_without_using_worker_trace_or_prose():
    value = stopped_result()
    output = client._safe_result(value, TRACE, report_retained=True)
    assert output["status"] == "stopped_after_report"
    assert output["usage"] is None
    assert output["stop_reason"] == "server_report_retained"
    assert output["tool_trace"] == TRACE
    assert "read_file" not in json.dumps(output)


def test_remote_entry_checks_actual_parent_report_state(monkeypatch):
    from test_goose_worker_client import _wire, session

    calls = _wire(
        monkeypatch,
        {"status": "completed", "result": stopped_result()},
    )
    tool_session = session()
    assert tool_session.report_retained is False
    # The synthetic callback trace claims completion, but the real parent
    # session has retained no report. A worker cannot manufacture that state.
    with pytest.raises(ModelError):
        client.run_remote_goose(
            profile(), "test-key", "Find oxide candidates", tool_session=tool_session
        )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "patch,trace,retained",
    [
        ({}, TRACE, False),
        ({}, [], True),
        ({}, [{"tool": "generate_ranked_report", "status": "rejected"}], True),
        ({}, [{"tool": "evaluate_candidate_fit", "status": "completed"}], True),
        ({"stop_reason": "worker says so"}, TRACE, True),
        ({"usage": {"total_tokens": 0}}, TRACE, True),
        ({"status": "completed"}, TRACE, True),
        ({"status": ["stopped_after_report"]}, TRACE, True),
    ],
)
def test_worker_cannot_authorize_report_stop_or_manufacture_final_usage(
    patch, trace, retained
):
    with pytest.raises(ModelError):
        client._safe_result(
            {**stopped_result(), **patch}, trace, report_retained=retained
        )


def test_controlled_stop_uses_existing_token_recovery_and_discards_unfinished_usage(
    monkeypatch, tmp_path
):
    tokens = {
        "access_token": "test-access",
        "refresh_token": "test-refresh",
        "id_token": None,
        "account_id": "same",
        "expires_at": "2099-01-01T00:00:00Z",
    }

    @contextmanager
    def directory(_):
        yield tmp_path

    @contextmanager
    def broker(_):
        signal = runtime._ReportRetentionSignal()
        signal.mark()
        yield "http://127.0.0.1:2222", "t" * 43, TRACE, signal

    def execute(*args, **kwargs):
        assert kwargs["report_retained"].event.is_set()
        return runtime._ProcessResult(b"UNFINISHED PRIVATE MODEL OUTPUT", True)

    monkeypatch.setattr(runtime, "runtime_status", lambda: {"available": True})
    monkeypatch.setattr(runtime, "_runtime_directory", directory)
    monkeypatch.setattr(runtime, "_tool_broker", broker)
    monkeypatch.setattr(runtime, "_execute", execute)
    value = runtime.run_goose(
        profile("chatgpt"),
        None,
        "Find materials",
        tool_session=Tools(),
        chatgpt_tokens=tokens,
    )
    assert value.pop("refreshed_chatgpt_tokens") == tokens
    assert value["status"] == "stopped_after_report" and value["usage"] is None
    assert "PRIVATE" not in json.dumps(value)


def test_controlled_stop_keeps_ready_account_and_persists_honest_completion_metadata(
    monkeypatch, tmp_path, authenticated_model_factory
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    manager = authenticated_model_factory(tmp_path / "model.sqlite3")
    historical = science.load_snapshot()
    calls = []
    monkeypatch.setattr(science, "retrieve_nomad", lambda *a, **k: deepcopy(historical))
    monkeypatch.setattr("labcat.research._add_attribute_research", lambda *a, **k: None)

    def run_remote(profile, secret, prompt, *, tool_session, **kwargs):
        calls.append(prompt)
        tool_session.call("assess_research_intent", {"decision": "materials_research"})
        tool_session.call("search_public_references", {})
        reply = tool_session.call("generate_ranked_report", {})
        assert reply["report_retained"] is True and tool_session.report_retained
        return client._safe_result(stopped_result(), TRACE, report_retained=True)

    monkeypatch.setattr(client, "run_remote_goose", run_remote)
    prompt = "Find oxide dielectric candidates for thin-film experiments."
    outcome = research(
        prompt,
        load_config(),
        connections=manager,
        ranking_profile={
            "id": "test-explicit",
            "name": "Test profile only",
            "importance": {"dielectric_total": 1},
        },
        ranking_selection={"mode": "explicit"},
        source_preferences={
            **default_source_preferences(),
            "materials_project_mode": "off",
            "enabled_sources": ["nomad"],
            "search_public_references": False,
        },
    )
    assert len(calls) == 1
    assert manager.setup.status()["can_research"] is True
    execution = outcome["result"]["execution"]
    assert execution["model_stopped_after_report"] is True
    assert "model_interrupted" not in execution and execution["warning"] is None
    assert execution["agent"]["usage"] is None
    assert manager.agent.usage()["last_run"]["status"] == "stopped_after_report"
    for view in ("pi_summary", "technical_audit"):
        assert "retained this report, then stopped the model process" in outcome[view]
        assert "Model-led research stopped before completion" not in outcome[view]
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY controlled report stop")
    chat = store.create_global_chat("TEST ONLY controlled report stop", project["id"])
    store.append_research(chat["id"], project["id"], prompt, outcome)
    saved = WorkspaceStore(store.path).get_global_chat(chat["id"])["reports"][0]
    assert saved["result"]["execution"] == execution
    assert saved["result"]["candidates"] == outcome["result"]["candidates"]


def test_historical_completion_note_is_unchanged_without_controlled_stop_marker():
    old = {"execution": {"model_interrupted": True}}
    assert "The model connection stopped after the request was assessed." in " ".join(
        _research_completion_lines(old)
    )
    assert (
        _research_completion_lines({"execution": {"agent": {"status": "completed"}}})
        == []
    )
