"""Synthetic aggregate diagnostics; no adapters, model or network
calls."""

import json
import socket
from copy import deepcopy

import pytest
from test_candidate_leads import reference

from labcat import assessment_completion as completion
from labcat.agent_tools import AgentToolError, ResearchToolSession
from labcat.config import load_config
from labcat.science import literature_evaluation as evaluator
from labcat.science.candidate_leads import (
    discovery_documents,
    validate_candidate_leads,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No network or model is allowed in this private test.")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def prepared(*, extra_documents=0, session_type=ResearchToolSession):
    refs = [
        reference(
            i + 1,
            text=f"TESTONLY-{name} has a measured low density and a measured band gap "
            "under the stated laboratory conditions.",
        )
        for i, name in enumerate(("Alpha", "Beta"))
    ]
    refs += [
        reference(i + 3, text="Additional unrelated synthetic public context.")
        for i in range(extra_documents)
    ]
    docs = discovery_documents(refs)
    proposals = [
        {
            "document_id": docs[i]["document_id"],
            "name": "TESTONLY-" + name,
            "quote": refs[i]["metadata"]["abstract"],
        }
        for i, name in enumerate(("Alpha", "Beta"))
    ]
    profile = {"importance": {"density": 0.5, "band_gap": 0.5}}
    leads = validate_candidate_leads(proposals, docs, refs, profile["importance"])
    session = session_type(
        "Compare oxide ceramics for a lightweight insulating component.",
        load_config(),
        ranking_profile=profile,
    )
    session._discovery = {"sources": deepcopy(refs), "note": {}}
    session._accepted_leads = deepcopy(leads)
    session._lead_proposals = deepcopy(proposals)
    session._offered_document_ids = {doc["document_id"] for doc in docs}
    initial = {
        "evaluations": [
            {
                "lead_id": lead["id"],
                "criterion_id": "application_fit",
                "document_id": lead["citations"][0]["document_id"],
                "quote": lead["citations"][0]["quote"],
                "judgment": "unknown",
                "interpretation": "The requested application remains unresolved.",
            }
            for lead in leads
        ]
    }
    # Exercise only the existing pure parent admission method; no intent,
    # retrieval, worker, follow-up or reply-generation tool is invoked.
    ResearchToolSession._evaluate(session, initial, "initial")
    tasks = session._review_tasks()
    assert len(tasks) == 4
    session._offered_review_keys = {session._review_key(task) for task in tasks}
    session._offered_completion_keys = frozenset(session._offered_review_keys)
    session._assessment_completion = completion.CompletionObserver()
    return session, tasks


def row(task, judgment="unknown"):
    return {
        **{key: task[key] for key in ("lead_id", "criterion_id", "document_id")},
        "quote": task["quote_anchor"],
        "judgment": judgment,
        "interpretation": "The stated conditions require scientific review.",
    }


def state(session):
    return deepcopy(
        {
            "sources": session._assessment_references(),
            "documents": session._assessment_documents(),
            "leads": session._accepted_leads,
            "batches": session._evaluation_batches,
            "feedback": session._evaluation_batch_feedback,
            "proposals": session._evaluation_proposals,
            "evaluation": session._evaluation,
            "calls": session._calls,
        }
    )


def safe(observer):
    result = observer.export()
    assert completion.validate_assessment_completion(result) == result
    serialized = json.dumps(result)
    for marker in ("PRIVATE_CANARY", "lead-", "doc-", "TESTONLY", "http"):
        assert marker not in serialized
    return result


def project(session, arguments, *, feedback=None, status="processed"):
    capture = completion.capture(
        arguments,
        session._offered_completion_keys,
        frozenset(session._offered_document_ids),
    )
    observer = completion.CompletionObserver()
    if feedback is None and status == "processed":
        session._evaluate(arguments, "test")
        feedback = session._evaluation_batch_feedback["test"]
    observer.finish(capture, feedback, status=status)
    return safe(observer)["records"][0]


def test_mixed_batch_preserves_admission_and_separates_rejection_from_omission():
    actual, tasks = prepared()
    original, _ = prepared()
    args = {
        "evaluations": [
            row(tasks[0]),
            row(tasks[1], "supports"),
            row(tasks[2]) | {"quote": "PRIVATE_CANARY is absent from the source."},
            row(tasks[0]) | {"interpretation": "PRIVATE_CANARY 12"},
            row(tasks[2]) | {"lead_id": "lead-" + "f" * 24},
            row(tasks[0]),
            row(tasks[0]) | {"criterion_id": "application_fit"},
        ]
    }
    untouched = deepcopy(args)
    # Removing diagnostic capture does not change sources, accepted state or scores.
    original._offered_completion_keys = frozenset()
    original._evaluate(args, "test")
    actual._evaluate(args, "test")
    assert state(actual) == state(original)
    assert args == untouched
    record = safe(actual._assessment_completion)["records"][0]
    assert record["context"] == "captured"
    assert record["submission"] == {
        "offered_tasks": 4,
        "rows": 7,
        "matched_rows": 5,
        "matched_tasks": 3,
        "unmatched_rows": 2,
        "unsubmitted_tasks": 1,
    }
    outcome = record["outcomes"]
    assert outcome["matched_rows"]["accepted_unknown"] == 2
    assert outcome["matched_rows"]["accepted_nonunknown"] == 1
    assert outcome["matched_rows"]["already_retained"] == 1
    assert outcome["matched_rows"]["rejections"] == {
        "format": 1,
        "selector": 0,
        "quote_binding": 1,
        "criterion": 0,
        "method": 0,
        "goal": 0,
    }
    assert outcome["all_rows"]["rejections"]["selector"] == 1
    assert outcome["tasks"] == {
        "accepted_unknown": 1,
        "accepted_nonunknown": 1,
        "accepted": 2,
        "rejected": 2,
        "submitted_without_acceptance": 1,
    }
    assert actual.build_plan["candidate_evaluation"]["task_completion"] == safe(
        actual._assessment_completion
    )
    # Diagnostics omit selectors/text; source-bound state remains accepted-only.
    assert "PRIVATE_CANARY" not in json.dumps(actual._evaluation_batches)
    assert len(actual._evaluation_batches) == 2


@pytest.mark.parametrize("judgment", evaluator.JUDGMENTS)
def test_unknown_nonunknown_counts_are_not_evidence(judgment):
    session, tasks = prepared()
    diagnostic = project(session, {"evaluations": [row(tasks[0], judgment)]})
    field = "accepted_unknown" if judgment == "unknown" else "accepted_nonunknown"
    assert diagnostic["outcomes"]["tasks"][field] == 1
    if judgment == "unknown":
        assert all(r["coverage"] == 0 for r in session._evaluation["ranked_candidates"])


@pytest.mark.parametrize(
    "change",
    [
        {"lead_id": "lead-" + "e" * 24},
        {"lead_id": "PRIVATE_CANARY"},
        {"document_id": "doc-" + "e" * 24},
        {"document_id": {"PRIVATE_CANARY": 1}},
        {"criterion_id": "bulk_modulus"},
        {"criterion_id": "PRIVATE_CANARY"},
    ],
)
def test_unknown_selectors_never_count_as_offered(change):
    session, tasks = prepared()
    record = project(session, {"evaluations": [row(tasks[0]) | change]})
    assert record["submission"]["matched_rows"] == 0
    assert record["submission"]["unsubmitted_tasks"] == 4
    assert record["outcomes"]["tasks"]["accepted"] == 0


def test_duplicate_occurrences_do_not_inflate_tasks():
    session, tasks = prepared()
    record = project(session, {"evaluations": [row(tasks[0])] * 3})
    assert record["submission"]["matched_rows"] == 3
    assert record["submission"]["matched_tasks"] == 1
    assert record["outcomes"]["matched_rows"]["already_retained"] == 2
    assert record["outcomes"]["tasks"]["accepted"] == 1


def test_capture_is_immutable_and_does_not_retain_inputs():
    session, tasks = prepared()
    args = {"evaluations": [row(tasks[0])]}
    captured = completion.capture(
        args, session._offered_completion_keys, frozenset(session._offered_document_ids)
    )
    assert "lead-" not in repr(captured) and "TESTONLY" not in repr(captured)
    args["evaluations"][0].update(lead_id="PRIVATE_CANARY", judgment="supports")
    session._offered_completion_keys = frozenset()
    observer = completion.CompletionObserver()
    observer.finish(
        captured,
        [{"index": 0, "status": "accepted", "reason": "source_bound_interpretation"}],
    )
    assert safe(observer)["records"][0]["outcomes"]["tasks"]["accepted_unknown"] == 1


def test_undelivered_parent_context_has_no_guessed_completion():
    session, tasks = prepared()
    session._offered_document_ids.clear()
    record = project(session, {"evaluations": [row(tasks[0])]})
    assert record == {
        "status": "processed",
        "context": "invalid",
        "submission": None,
        "outcomes": None,
    }


def test_binding_failure_retains_submissions_without_fabricating_row_outcomes():
    session, tasks = prepared(extra_documents=22)
    before = state(session)
    arguments = {
        "evaluations": [
            row(tasks[0]),
            row(tasks[1]) | {"document_id": "doc-" + "f" * 24},
        ]
    }
    with pytest.raises(AgentToolError) as error:
        session._evaluate(arguments, "test")
    assert error.value.reason_code == "evaluation_binding_failed"
    assert state(session) == before
    record = safe(session._assessment_completion)["records"][0]
    assert record["status"] == "binding_failed" and record["context"] == "captured"
    assert record["submission"]["matched_tasks"] == 1
    assert record["outcomes"] is None


@pytest.mark.parametrize("reason", tuple(completion.REASONS))
def test_fixed_rejection_categories(reason):
    session, tasks = prepared()
    record = project(
        session,
        {"evaluations": [row(tasks[0])]},
        feedback=[{"index": 0, "status": "rejected", "reason": reason}],
    )
    assert (
        record["outcomes"]["matched_rows"]["rejections"][completion.REASONS[reason]]
        == 1
    )


@pytest.mark.parametrize(
    "feedback",
    [
        [],
        [{"index": 0, "status": "accepted", "reason": "PRIVATE_CANARY"}],
        [{"index": True, "status": "rejected", "reason": "invalid_row_format"}],
        [{"index": 1, "status": "rejected", "reason": "invalid_row_format"}],
        [{"index": 0, "status": "rejected", "reason": "PRIVATE_CANARY"}],
        [
            {
                "index": 0,
                "status": "rejected",
                "reason": "invalid_row_format",
                "quote": "PRIVATE_CANARY",
            }
        ],
    ],
)
def test_malformed_feedback_invalidates_diagnostic_only(feedback):
    session, tasks = prepared()
    record = project(session, {"evaluations": [row(tasks[0])]}, feedback=feedback)
    assert record == {
        "status": "processed",
        "context": "invalid",
        "submission": None,
        "outcomes": None,
    }


def test_record_cap_and_returned_copies():
    observer = completion.CompletionObserver()
    for _ in range(8):
        observer.note_uninspected("batch_limit")
    exact = safe(observer)
    assert len(exact["records"]) == 8 and not exact["records_saturated"]
    observer.note_uninspected("transport_rejected")
    result = safe(observer)
    assert result["records_saturated"] and len(result["records"]) == 8
    result["records"][0]["status"] = "PRIVATE_CANARY"
    assert safe(observer)["records"][0]["status"] == "batch_limit"


@pytest.mark.parametrize("count", [192, 193])
def test_exact_task_cap(count):
    keys = frozenset(
        (f"lead-{i:024x}", "density", f"doc-{i:024x}") for i in range(count)
    )
    documents = frozenset(key[2] for key in keys)
    captured = completion.capture({"evaluations": []}, keys, documents)
    if count == 193:
        assert captured is None
    else:
        assert captured.offered_tasks == 192
        observer = completion.CompletionObserver()
        observer.finish(captured, [])
        assert safe(observer)["records"][0]["submission"]["unsubmitted_tasks"] == 192


def test_schema_rejects_untrusted_keys_types_and_contradictory_counts():
    session, tasks = prepared()
    project(session, {"evaluations": [row(tasks[0])]})
    value = safe(session._assessment_completion)
    mutations = [
        lambda v: v.update(extra="PRIVATE_CANARY"),
        lambda v: v.update(version="PRIVATE_CANARY"),
        lambda v: v.update(is_evidence=True),
        lambda v: v.update(record_limit=True),
        lambda v: v.update(records_saturated=True),
        lambda v: v.update(records=v["records"] * 9),
        lambda v: v["records"][0].update(context="stable"),
        lambda v: v["records"][0]["submission"].update(rows=True),
        lambda v: v["records"][0]["submission"].update(matched_rows=2),
        lambda v: v["records"][0]["outcomes"]["all_rows"]["rejections"].update(extra=1),
        lambda v: v["records"][0]["outcomes"]["tasks"].update(accepted=2),
    ]
    for mutate in mutations:
        changed = deepcopy(value)
        mutate(changed)
        with pytest.raises(
            ValueError, match="^Invalid assessment completion diagnostics[.]$"
        ):
            completion.validate_assessment_completion(changed)
    assert completion.validate_assessment_completion(value) == value


def test_real_reply_delivery_and_idempotent_tool_call_have_no_model_context_growth(
    monkeypatch,
):
    from test_candidate_assessment_completion import (
        assessments,
    )
    from test_candidate_assessment_completion import (
        prepared as live_prepared,
    )

    session = live_prepared(monkeypatch)
    assert "task_completion" not in session.build_plan["candidate_evaluation"]
    first = session.call("evaluate_candidate_fit", assessments(session))
    offered = frozenset(
        session._review_key(task) for task in first["attribute_review"]["tasks"]
    )
    assert session._offered_completion_keys == offered
    assert "task_completion" not in json.dumps(first)
    assert len(session._assessment_completion.export()["records"]) == 1
    before = session._assessment_completion.export()
    session.call("evaluate_candidate_fit", assessments(session))
    assert session._assessment_completion.export() == before
    assert len(session._evaluation_batches) == 1
    # Original valid report content is untouched, diagnostics only live in the plan.
    assert "task_completion" not in json.dumps(session._evaluation)


@pytest.mark.parametrize(
    "arguments",
    [
        {"evaluations": [{"PRIVATE_CANARY": "x" * 24_001}]},
        {"evaluations": [None] * 97},
        {"evaluations": [], "PRIVATE_CANARY": "unknown"},
        {"evaluations": "PRIVATE_CANARY"},
    ],
)
def test_real_transport_rejections_do_not_inspect_unbounded_rows(
    monkeypatch, arguments
):
    from test_candidate_assessment_completion import prepared as live_prepared

    session = live_prepared(monkeypatch)
    before = len(session._evaluation_batches)
    with pytest.raises(AgentToolError) as error:
        session.call("evaluate_candidate_fit", arguments)
    assert error.value.reason_code == "evaluation_arguments"
    assert len(session._evaluation_batches) == before
    assert safe(session._assessment_completion)["records"] == [
        {
            "status": "transport_rejected",
            "context": "not_inspected",
            "submission": None,
            "outcomes": None,
        }
    ]


def test_real_third_batch_does_not_evaluate_or_add_permission(monkeypatch):
    from test_candidate_assessment_completion import (
        assessments,
    )
    from test_candidate_assessment_completion import (
        prepared as live_prepared,
    )

    session = live_prepared(monkeypatch)
    session._tool_limit = 12
    session.call("evaluate_candidate_fit", assessments(session, first_only=True))
    session.call("evaluate_candidate_fit", assessments(session))
    before = state(session)
    with pytest.raises(AgentToolError) as error:
        session.call("evaluate_candidate_fit", {"evaluations": []})
    assert error.value.reason_code == "evaluation_batch_limit"
    after = state(session)
    assert after.pop("calls") == before.pop("calls") + 1
    assert after == before
    assert safe(session._assessment_completion)["records"][-1] == {
        "status": "batch_limit",
        "context": "not_inspected",
        "submission": None,
        "outcomes": None,
    }


@pytest.mark.parametrize(
    "value",
    [
        completion.Submission(True, (), ()),
        completion.Submission(193, (), ()),
        completion.Submission(1, (True,), ("unknown",)),
        completion.Submission(1, (1,), ("unknown",)),
        completion.Submission(1, (0,), ("PRIVATE_CANARY",)),
        completion.Submission(1, (0,), ()),
    ],
)
def test_invalid_temporary_projection_cannot_make_completion_claims(value):
    observer = completion.CompletionObserver()
    observer.finish(
        value,
        [{"index": 0, "status": "accepted", "reason": "source_bound_interpretation"}],
    )
    assert safe(observer)["records"][0] == {
        "status": "processed",
        "context": "invalid",
        "submission": None,
        "outcomes": None,
    }


def test_rows_are_bounded_at_exact_existing_transport_limit():
    session, tasks = prepared()
    args = {"evaluations": [row(tasks[0])] * evaluator.MAX_EVALUATIONS}
    captured = completion.capture(
        args, session._offered_completion_keys, frozenset(session._offered_document_ids)
    )
    assert captured is not None and len(captured.row_ordinals) == 96
    args["evaluations"].append(row(tasks[0]))
    assert (
        completion.capture(
            args,
            session._offered_completion_keys,
            frozenset(session._offered_document_ids),
        )
        is None
    )


def test_failed_reply_never_adds_completion_selectors(monkeypatch):
    from test_preassessment_attribute_evidence import prepare

    from labcat import agent_tools

    session, _, _, _ = prepare(monkeypatch, {"band_gap": 1})
    session._offered_document_ids.clear()
    session._offered_review_keys.clear()
    session._offered_completion_keys = frozenset()
    assert session.build_plan["attribute_review"]["offered_document_count"] == 0
    session._attribute_evaluation_context()
    assert session._offered_completion_keys == frozenset()
    monkeypatch.setattr(agent_tools, "MAX_TOOL_REPLY_BYTES", 1)
    with pytest.raises(AgentToolError, match="response exceeded"):
        session._reply("evaluate_candidate_fit")
    assert session._offered_completion_keys == frozenset()


def test_followup_and_withheld_documents_cannot_backfill_previous_batch(monkeypatch):
    from test_preassessment_attribute_evidence import PARAGRAPHS, prepare

    paragraphs = tuple(text + " αβγ" * 780 for text in PARAGRAPHS)
    session, reply, calls, _ = prepare(
        monkeypatch,
        {"band_gap": 0.8, "density": 0.2},
        paragraphs=paragraphs,
    )
    first = safe(session._assessment_completion)["records"][0]
    # Follow-up was fetched after the first batch. It must not become earlier work.
    assert first["submission"]["offered_tasks"] == 0
    assert reply["attribute_review"]["reviewable_task_count"] == 4
    assert reply["attribute_review"]["offered_task_count"] == 2
    expected = frozenset(
        session._review_key(task) for task in reply["attribute_review"]["tasks"]
    )
    assert session._offered_completion_keys == expected
    before_calls = deepcopy(calls)
    session.call("evaluate_candidate_fit", {"evaluations": []})
    second = safe(session._assessment_completion)["records"][1]
    assert second["submission"]["offered_tasks"] == 2
    assert second["submission"]["unsubmitted_tasks"] == 2
    assert safe(session._assessment_completion)["records"][0] == first
    assert calls == before_calls
