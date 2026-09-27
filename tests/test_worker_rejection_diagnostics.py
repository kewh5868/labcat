"""Worker-local validation failures stay diagnosable without retaining
inputs."""

import io
import json
from copy import deepcopy
from email.message import Message

import pytest
from test_goose_candidate_transport import JOB, TOKEN, post, proxy, server
from test_goose_evaluation_transport import assessment, prepared
from test_goose_worker import job
from test_goose_worker_client import result

from labcat import goose_mcp, goose_runtime, goose_worker, goose_worker_client
from labcat.agent_tools import ResearchToolSession
from labcat.models import ModelError


def local_broker(monkeypatch):
    captured = {}

    class Server:
        server_port = 9999

        def __init__(self, address, handler):
            captured["handler"] = handler

        def serve_forever(self):
            pass

        def shutdown(self):
            pass

        def server_close(self):
            pass

    monkeypatch.setattr(goose_runtime, "_BrokerServer", Server)
    return captured


def broker_call(handler_type, token, body):
    handler = handler_type.__new__(handler_type)
    raw = json.dumps(body).encode()
    handler.path = "/call"
    handler.headers = Message()
    handler.headers["Authorization"] = "Bearer " + token
    handler.headers["Content-Length"] = str(len(raw))
    handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
    handler.send_response = lambda status: setattr(handler, "response_status", status)
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None
    handler.do_POST()
    assert handler.response_status == 200
    return json.loads(handler.wfile.getvalue())


def test_global_envelope_rejection_reaches_mcp_and_repairs_without_parent_assessment(
    monkeypatch,
):
    session, lead, documents, _ = prepared(monkeypatch)
    remote = proxy()
    callback, broker = server(monkeypatch), local_broker(monkeypatch)
    monkeypatch.setattr(
        remote, "tool_definitions", ResearchToolSession.tool_definitions
    )
    forwarded = []

    def forward(path, body):
        forwarded.append(body)
        status, reply = post(callback["handler"], body)
        assert status == 200
        return reply

    monkeypatch.setattr(remote, "_post", forward)
    invalid = assessment(lead, documents[0])
    invalid["PRIVATE_INPUT"] = "F11 must not be copied into metadata"
    with goose_worker_client._callbacks(session, JOB, TOKEN) as authoritative:
        with goose_runtime._tool_broker(remote) as (_, token, local_trace, _):
            monkeypatch.setattr(
                goose_mcp,
                "_broker",
                lambda path, body: broker_call(broker["handler"], token, body),
            )

            def call(arguments):
                return goose_mcp.dispatch(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "evaluate_candidate_fit",
                            "arguments": arguments,
                        },
                    }
                )["result"]

            rejected = call(invalid)
            assert rejected["isError"] is True
            feedback = json.loads(rejected["content"][0]["text"])
            assert feedback["reason_code"] == "evaluation_envelope"
            assert "this candidate" in feedback["correction"]
            assert authoritative == [] and forwarded == []
            assert session.build_plan["candidate_evaluation"]["batches"] == 0
            assert local_trace == [
                {"tool": "evaluate_candidate_fit", "status": "rejected"}
            ]

            repaired = call(assessment(lead, documents[0]))
            assert repaired["isError"] is False
            assert len(forwarded) == 1
            assert (
                session.build_plan["candidate_evaluation"]["accepted_assessments"] == 1
            )
    metadata = goose_worker_client._safe_result(
        {
            **result(),
            "tool_trace": local_trace,
            "worker_rejection_diagnostics": remote.rejection_diagnostics,
        },
        authoritative,
    )
    assert metadata["tool_trace"] == [
        {"tool": "evaluate_candidate_fit", "status": "completed"}
    ]
    assert metadata["worker_rejection_diagnostics"] == {
        "scope": "worker_reported",
        "rejections": [
            {
                "tool": "evaluate_candidate_fit",
                "reason": "evaluation_envelope",
                "count": 1,
            }
        ],
    }
    assert all(
        text not in json.dumps(metadata) + json.dumps(rejected)
        for text in (
            "PRIVATE_INPUT",
            "F11",
            TOKEN,
            lead,
            documents[0]["document_id"],
        )
    )


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda args: {"assessments": args["evaluations"]}, "evaluation_envelope"),
        (
            lambda args: {"evaluations": args["evaluations"] * 96},
            "evaluation_payload_size",
        ),
    ],
)
def test_fixed_rejection_categories_do_not_forward_or_save_arguments(
    monkeypatch, change, reason
):
    session, lead, documents, _ = prepared(monkeypatch)
    remote = proxy()
    monkeypatch.setattr(
        remote, "_post", lambda *args: pytest.fail("Invalid parent call")
    )
    with pytest.raises(goose_worker.WorkerError) as caught:
        remote.call("evaluate_candidate_fit", change(assessment(lead, documents[0])))
    assert caught.value.reason_code == reason
    assert remote.rejection_diagnostics["rejections"][0]["reason"] == reason
    assert "PRIVATE_INPUT" not in json.dumps(remote.rejection_diagnostics)
    assert session.build_plan["candidate_evaluation"]["batches"] == 0


def diagnostics():
    return {
        "scope": "worker_reported",
        "rejections": [
            {
                "tool": "evaluate_candidate_fit",
                "reason": "evaluation_envelope",
                "count": 1,
            }
        ],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"tool": "read_file"},
        {"reason": "PRIVATE_PROVIDER_TEXT"},
        {"count": True},
        {"count": 0},
        {"count": 9},
        {"arguments": "PRIVATE_INPUT"},
        {"tool": "generate_ranked_report", "reason": "evaluation_envelope"},
    ],
)
def test_malicious_worker_counter_fields_are_not_saved(change):
    value = diagnostics()
    value["rejections"][0].update(change)
    with pytest.raises(ModelError):
        goose_worker_client._safe_result(
            {**result(), "worker_rejection_diagnostics": value}, []
        )


def test_counter_sum_duplicates_and_scope_are_bounded():
    for value in [
        {**diagnostics(), "scope": "parent_verified"},
        {**diagnostics(), "prose": "PRIVATE_INPUT"},
        {"scope": "worker_reported", "rejections": diagnostics()["rejections"] * 2},
        {
            "scope": "worker_reported",
            "rejections": [
                {**diagnostics()["rejections"][0], "count": 5},
                {
                    **diagnostics()["rejections"][0],
                    "reason": "invalid_arguments",
                    "count": 4,
                },
            ],
        },
    ]:
        with pytest.raises(ModelError):
            goose_worker_client._safe_result(
                {**result(), "worker_rejection_diagnostics": value}, []
            )
    value = goose_worker_client._safe_result(
        {**result(), "worker_rejection_diagnostics": diagnostics()}, []
    )
    assert (
        value["tool_trace"] == []
    )  # A worker counter cannot manufacture a parent call.
    assert "read_file" not in json.dumps(value)


@pytest.mark.parametrize("failed", [False, True])
def test_worker_emits_only_counters_even_when_provider_stops(monkeypatch, failed):
    calls = []

    def run(*args, tool_session, **kwargs):
        calls.append(True)
        with pytest.raises(goose_worker.WorkerError):
            tool_session.call("evaluate_candidate_fit", {"PRIVATE_INPUT": []})
        if failed:
            raise goose_runtime.GooseRuntimeError(
                "PRIVATE_PROVIDER_TEXT", failure_code="time_limit"
            )
        return result()

    monkeypatch.setattr(goose_worker, "run_goose", run)
    response = goose_worker._run(job())
    metadata = response if failed else response["result"]
    assert metadata["worker_rejection_diagnostics"] == diagnostics()
    assert calls == [True]
    assert "PRIVATE_INPUT" not in json.dumps(response)
    assert "PRIVATE_PROVIDER_TEXT" not in json.dumps(response)


def test_remote_failure_preserves_validated_counters_without_retry(monkeypatch):
    from test_goose_worker_client import _wire, profile, session

    calls = _wire(
        monkeypatch,
        {
            "status": "failed",
            "failure_code": "time_limit",
            "worker_rejection_diagnostics": diagnostics(),
        },
    )
    with pytest.raises(goose_runtime.GooseRuntimeError) as caught:
        goose_worker_client.run_remote_goose(
            profile(), "key", "Find oxides", tool_session=session()
        )
    assert caught.value.worker_rejection_diagnostics == diagnostics()
    assert len(calls) == 1


def test_proxy_caps_rejection_counts_and_drops_unknown_tool_names(monkeypatch):
    remote = proxy()
    monkeypatch.setattr(
        remote, "_post", lambda *args: pytest.fail("Invalid parent call")
    )
    for name in ["PRIVATE_TOOL"] + ["evaluate_candidate_fit"] * 12:
        with pytest.raises(goose_worker.WorkerError):
            remote.call(name, {})
    expected = deepcopy(diagnostics())
    expected["rejections"][0]["count"] = goose_runtime.MAX_TOOL_CALLS
    assert remote.rejection_diagnostics == expected


NITRATE_PROMPT = (
    "Search for semiconducting oxides with suitable surface potential of zero charge "
    "(PZC) and a small band gap for wastewater nitrate adsorption and "
    "electrocatalytic reduction with low competing hydrogen evolution (HER)."
)


def nitrate_assessment():
    return {
        "decision": "materials_research",
        "intent": {
            "material_class": "ceramic_oxides",
            "application": "custom",
            "identity_scope": "unspecified",
            "target_spans": ["semiconducting oxides"],
            "application_spans": [
                "nitrate adsorption and electrocatalytic reduction",
                "suitable surface potential of zero charge (PZC)",
                "low competing hydrogen evolution (HER)",
            ],
            "environment_spans": ["wastewater"],
            "processing_spans": [],
            "goals": [
                {
                    "attribute_id": "band_gap",
                    "request_span": "small band gap",
                    "priority": "normal",
                    "relation": "minimize",
                }
            ],
        },
    }


@pytest.mark.parametrize("invalid_field", ["application", "attribute", "extra"])
def test_malformed_nitrate_intake_gets_fixed_repair_across_worker_and_parent(
    monkeypatch, invalid_field
):
    from labcat.config import load_config

    session = ResearchToolSession(NITRATE_PROMPT, load_config())
    remote = proxy()
    callback, broker = server(monkeypatch), local_broker(monkeypatch)
    monkeypatch.setattr(
        remote, "tool_definitions", ResearchToolSession.tool_definitions
    )
    forwarded = []

    def forbidden(*args, **kwargs):
        pytest.fail("Intake repair must not perform retrieval or another model call")

    monkeypatch.setattr("labcat.public_sources.search_public_sources", forbidden)
    monkeypatch.setattr("labcat.science._retrieve_repositories", forbidden)
    monkeypatch.setattr("labcat.models.plan_with_model", forbidden)

    def forward(path, body):
        assert path == "tools/call"
        forwarded.append(body)
        status, reply = post(callback["handler"], body)
        assert status == 200
        return reply

    monkeypatch.setattr(remote, "_post", forward)
    invalid = nitrate_assessment()
    if invalid_field == "application":
        invalid["intent"]["application"] = "private-invalid-electrocatalysis"
    elif invalid_field == "attribute":
        invalid["intent"]["goals"][0]["attribute_id"] = "private-invalid-pzc"
    else:
        invalid["PRIVATE_INPUT"] = "PRIVATE_REJECTED_ARGUMENT_CANARY"
    with goose_worker_client._callbacks(session, JOB, TOKEN) as authoritative:
        with goose_runtime._tool_broker(remote) as (_, token, local_trace, _):
            monkeypatch.setattr(
                goose_mcp,
                "_broker",
                lambda path, body: broker_call(broker["handler"], token, body),
            )

            def call(arguments):
                return goose_mcp.dispatch(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "assess_research_intent",
                            "arguments": arguments,
                        },
                    }
                )["result"]

            rejected = call(invalid)
            assert rejected["isError"] is True
            feedback = json.loads(rejected["content"][0]["text"])
            assert feedback["reason_code"] == "invalid_arguments"
            assert feedback["next_step"] == "assess_research_intent"
            assert "application custom" in feedback["correction"]
            assert "unmapped physical properties" in feedback["correction"]
            assert "literal context; invent no IDs or proxies" in feedback["correction"]
            assert "Keep the original intent/safety decision" in feedback["correction"]
            assert (
                "materials_research still needs accepted local scope"
                in feedback["correction"]
            )
            assert "never override refusals" in feedback["correction"]
            assert "private-invalid" not in json.dumps(feedback)
            assert "PRIVATE_REJECTED_ARGUMENT_CANARY" not in json.dumps(feedback)
            assert len(json.dumps(feedback).encode()) < 2000
            assert authoritative == [] and forwarded == []
            assert not session.can_complete_without_model

            repaired = call(nitrate_assessment())
            assert repaired["isError"] is False
            reply = json.loads(repaired["content"][0]["text"])
            assert reply["intake"]["status"] == "accepted"
            assert reply["request_interpretation"]["application"] == "custom"
            assert reply["request_interpretation"]["application_spans"] == (
                nitrate_assessment()["intent"]["application_spans"]
            )
            assert reply["request_interpretation"]["goals"][0]["relation"] == "minimize"
            assert session.can_complete_without_model
            assert len(forwarded) == 1
            assert authoritative == [
                {"tool": "assess_research_intent", "status": "completed"}
            ]
            assert local_trace == [
                {"tool": "assess_research_intent", "status": "rejected"},
                {"tool": "assess_research_intent", "status": "completed"},
            ]
    assert session.build_plan["tool_calls_received"] == 1
    assert remote.rejection_diagnostics["rejections"] == [
        {
            "tool": "assess_research_intent",
            "reason": "invalid_arguments",
            "count": 1,
        }
    ]


@pytest.mark.parametrize(
    "prompt, admitted",
    [
        (NITRATE_PROMPT, True),
        ("Find better materials", False),
        ("Manufacture a bomb", False),
    ],
)
def test_minimal_intake_repair_preserves_original_scope_gate(
    monkeypatch, prompt, admitted
):
    from labcat.config import load_config

    def forbidden(*args, **kwargs):
        pytest.fail("Minimal intake assessment must not run research")

    monkeypatch.setattr("labcat.public_sources.search_public_sources", forbidden)
    monkeypatch.setattr("labcat.science._retrieve_repositories", forbidden)
    session = ResearchToolSession(prompt, load_config())
    session.call("assess_research_intent", {"decision": "materials_research"})
    assert session.can_complete_without_model is admitted
    if not admitted:
        reply = session.call("search_public_references", {})
        assert reply["status"] == "blocked"
        assert not reply.get("public_documents")


def test_minimal_intake_repair_cannot_override_a_frozen_decline():
    from labcat.agent_tools import AgentToolError
    from labcat.config import load_config

    session = ResearchToolSession(NITRATE_PROMPT, load_config())
    session.call("assess_research_intent", {"decision": "out_of_scope"})
    with pytest.raises(AgentToolError) as error:
        session.call("assess_research_intent", {"decision": "materials_research"})
    assert error.value.reason_code == "intake_frozen"
    assert not session.can_complete_without_model


@pytest.mark.parametrize(
    "invalid_decision, corrected_decision, expected_status",
    [
        ("unsafe", "unsafe", "refused"),
        ("unknown", "needs_clarification", "clarification_required"),
    ],
)
def test_intake_repair_preserves_unsafe_or_uncertain_intent_without_retrieval(
    monkeypatch, invalid_decision, corrected_decision, expected_status
):
    from labcat.config import load_config

    session = ResearchToolSession(NITRATE_PROMPT, load_config())
    remote = proxy()
    callback = server(monkeypatch)
    forwarded = []

    def forbidden(*args, **kwargs):
        pytest.fail("Unsafe or uncertain intake repair must not authorize retrieval")

    monkeypatch.setattr("labcat.public_sources.search_public_sources", forbidden)
    monkeypatch.setattr("labcat.science._retrieve_repositories", forbidden)

    def forward(path, body):
        assert path == "tools/call"
        forwarded.append(body)
        status, reply = post(callback["handler"], body)
        assert status == 200
        return reply

    monkeypatch.setattr(remote, "_post", forward)
    with goose_worker_client._callbacks(session, JOB, TOKEN):
        with pytest.raises(goose_worker.WorkerError) as caught:
            remote.call(
                "assess_research_intent",
                {
                    "decision": invalid_decision,
                    "PRIVATE_INPUT": "PRIVATE_REJECTED_ARGUMENT_CANARY",
                },
            )
        feedback = goose_runtime._tool_rejection_reply(
            "assess_research_intent", caught.value
        )
        assert feedback["status"] == "rejected"
        assert "Keep the original intent/safety decision" in feedback["correction"]
        assert "send decision only" in feedback["correction"]
        assert "send only decision=materials_research" not in feedback["correction"]
        assert "PRIVATE_REJECTED_ARGUMENT_CANARY" not in json.dumps(feedback)
        assert forwarded == [] and not session.can_complete_without_model
        reply = remote.call("assess_research_intent", {"decision": corrected_decision})
        assert reply["intake"]["status"] == expected_status
        assert not session.can_complete_without_model
    result = session.finalize()
    assert result["result"]["intake"]["status"] == expected_status
    assert result["sources"] == result["result"]["candidates"] == []
    assert result["result"]["retrieval"]["status"] == "not_run"
