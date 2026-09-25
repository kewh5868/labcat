"""Independent finite-delivery checks using synthetic source text, never
live calls."""

import json
from copy import deepcopy

import pytest
from test_attribute_review_worklist import task_rows
from test_preassessment_attribute_evidence import PARAGRAPHS, prepare

from labcat import agent_tools
from labcat.agent_tools import AgentToolError


def _restore_first_delivery(session, originals):
    """Replay a first reply before any follow-up document/task was
    delivered."""
    session._offered_document_ids = {row["document_id"] for row in originals}
    session._offered_review_keys.clear()


def _assert_final(reply):
    assert reply["evaluation_phase"] == "final_assessment"
    assert reply["remaining_evaluation_batches"] == 1
    assert "first generic batch before expanding" not in reply["assessment_guidance"]
    tasks = reply["attribute_review"]["tasks"]
    gaps = reply["candidate_assessment_gaps"]
    general_count = sum(len(row["missing_criteria"]) for row in gaps)
    assert reply["assessment_work"] == {
        "general_pairs_remaining": general_count,
        "attribute_tasks_in_reply": len(tasks),
        "combined_rows_in_reply": general_count + len(tasks),
        "row_guidance": 24,
        "is_evidence": False,
    }
    assert set(reply["priority_criteria"]) == {
        *(item for row in gaps for item in row["missing_criteria"]),
        *(row["criterion_id"] for row in tasks),
    }


def test_final_guidance_includes_remaining_general_and_delivered_attributes(
    monkeypatch,
):
    session, _, _, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    # Synthetic replay of a possible first accepted subset: missing general
    # judgments cannot defer already offered attributes to a third batch.
    session._evaluation_proposals = session._evaluation_proposals[:1]
    reply = session._reply("evaluate_candidate_fit")
    _assert_final(reply)
    assert {"application_fit", "demonstrated_use", "band_gap", "density"} <= set(
        reply["priority_criteria"]
    )
    assert len(reply["attribute_review"]["tasks"]) == 4


def test_body_trimming_cannot_require_a_never_delivered_criterion(monkeypatch):
    paragraphs = (
        "TESTONLY-Alpha has a measured band gap for insulating films.",
        "TESTONLY-Beta has a measured density for lightweight designs." + " αβγ" * 780,
    )
    session, full, _, originals = prepare(
        monkeypatch, {"band_gap": 0.8, "density": 0.2}, paragraphs=paragraphs
    )
    _restore_first_delivery(session, originals)
    assert full["attribute_documents_shown"] == 2
    # Make this a delivery-budget test independent of incidental text length.
    # No production cap is changed outside this synthetic fixture.
    monkeypatch.setattr(
        agent_tools, "MAX_TOOL_REPLY_BYTES", len(json.dumps(full).encode()) - 100
    )
    reply = session._reply("evaluate_candidate_fit")
    _assert_final(reply)
    assert reply["attribute_documents_shown"] == 1
    assert {row["criterion_id"] for row in reply["attribute_review"]["tasks"]} == {
        "band_gap"
    }
    assert "band_gap" in reply["priority_criteria"]
    assert "density" not in reply["priority_criteria"]
    assert reply["attribute_review"]["withheld_task_count"] == 1
    assert reply["attribute_review"]["unoffered_document_task_count"] == 1


def test_delivered_document_without_a_delivered_task_is_not_required(monkeypatch):
    session, _, _, originals = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    _restore_first_delivery(session, originals)
    monkeypatch.setattr(agent_tools, "MAX_ATTRIBUTE_REVIEW_TASK_BYTES", 2)
    reply = session._reply("evaluate_candidate_fit")
    _assert_final(reply)
    assert len(reply["attribute_documents"]) == 2
    assert reply["attribute_review"]["tasks"] == []
    assert reply["attribute_review"]["offered_task_count"] == 0
    assert not {"band_gap", "density"} & set(reply["priority_criteria"])
    assert session._offered_review_keys == set()


def test_prior_offered_tasks_do_not_inflate_current_reply_completion_counts(
    monkeypatch,
):
    session, _, _, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    earlier = set(session._offered_review_keys)
    monkeypatch.setattr(agent_tools, "MAX_ATTRIBUTE_REVIEW_TASK_BYTES", 2)
    reply = session._reply("evaluate_candidate_fit")
    _assert_final(reply)
    assert reply["attribute_review"]["tasks"] == []
    assert reply["attribute_review"]["offered_task_count"] == 4
    assert reply["attribute_review"]["unattempted_task_count"] == 4
    assert reply["assessment_work"]["attribute_tasks_in_reply"] == 0
    assert session._offered_review_keys == earlier


def test_whole_reply_task_trimming_recomputes_final_contract(monkeypatch):
    session, _, _, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    envelope = session._evaluation_context()
    session._finish_reply(envelope, review=True)
    full_size = len(json.dumps(envelope, allow_nan=False).encode())
    assert len(envelope["attribute_review"]["tasks"]) == 4
    session._offered_review_keys.clear()
    # All context documents were sent earlier. This forces the inner task-only
    # truncation path rather than dropping any newly supplied body document.
    monkeypatch.setattr(agent_tools, "MAX_TOOL_REPLY_BYTES", full_size - 550)
    trimmed = session._evaluation_context()
    session._finish_reply(trimmed, review=True)
    _assert_final(trimmed)
    assert 0 < len(trimmed["attribute_review"]["tasks"]) < 4
    assert len(json.dumps(trimmed, allow_nan=False).encode()) <= full_size - 550
    assert session._offered_review_keys == {
        session._review_key(row) for row in trimmed["attribute_review"]["tasks"]
    }


def test_failed_final_reply_has_no_offered_state_or_assessment_side_effect(
    monkeypatch,
):
    session, _, _, originals = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    _restore_first_delivery(session, originals)
    before = deepcopy(
        (
            session._offered_document_ids,
            session._offered_review_keys,
            session._evaluation_proposals,
            session._evaluation_batches,
            session._calls,
        )
    )
    monkeypatch.setattr(agent_tools, "MAX_TOOL_REPLY_BYTES", 1)
    with pytest.raises(AgentToolError) as caught:
        session._reply("evaluate_candidate_fit")
    assert caught.value.reason_code == "tool_reply_limit"
    assert before == (
        session._offered_document_ids,
        session._offered_review_keys,
        session._evaluation_proposals,
        session._evaluation_batches,
        session._calls,
    )


def test_partial_final_rows_preserve_valid_judgments_without_filling_omissions(
    monkeypatch,
):
    session, reply, calls, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    original_rows = deepcopy(session._evaluation_proposals)
    offered = reply["attribute_review"]["tasks"]
    valid = task_rows(offered[:1])[0]
    forged = task_rows(offered[1:2])[0]
    forged["quote"] = "REJECTED_QUOTE_CANARY absent from the cited document."
    malformed = {"secret": "REJECTED_ROW_CANARY"}
    feedback = session.call(
        "evaluate_candidate_fit", {"evaluations": [valid, forged, malformed]}
    )
    assert [row["status"] for row in feedback["evaluation_feedback"]] == [
        "accepted",
        "rejected",
        "rejected",
    ]
    expected = sorted(
        [*original_rows, valid], key=lambda row: json.dumps(row, sort_keys=True)
    )
    assert (
        sorted(
            session._evaluation_proposals,
            key=lambda row: json.dumps(row, sort_keys=True),
        )
        == expected
    )
    assert feedback["attribute_review"]["reviewed_task_count"] == 1
    assert feedback["attribute_review"]["unattempted_task_count"] == 3
    assert feedback["evaluation_phase"] == "report_completion"
    assert feedback["remaining_evaluation_batches"] == 0
    assert feedback["attribute_review"]["tasks"] == []
    assert len(session._evaluation_batches) == 2
    assert "REJECTED_" not in json.dumps(feedback)
    assert "REJECTED_" not in json.dumps(session._evaluation_batches)
    outcome = session.finalize()
    assert (
        sorted(
            outcome["result"]["literature_evaluation"]["proposals"],
            key=lambda row: json.dumps(row, sort_keys=True),
        )
        == expected
    )
    assert all(
        row["coverage"] == 0 and row["priority_score"] == 0.225
        for row in outcome["result"]["literature_evaluation"]["ranked_candidates"]
    )
    assert len(calls["queries"]) == len(calls["articles"]) == 2


def test_third_distinct_batch_stays_rejected_after_partial_final_batch(monkeypatch):
    session, reply, _, _ = prepare(monkeypatch, {"band_gap": 1})
    session._tool_limit = 8
    rows = task_rows(reply["attribute_review"]["tasks"])
    session.call("evaluate_candidate_fit", {"evaluations": rows[:1]})
    accepted = deepcopy(session._evaluation_proposals)
    with pytest.raises(AgentToolError) as caught:
        session.call("evaluate_candidate_fit", {"evaluations": rows[1:]})
    assert caught.value.reason_code == "evaluation_batch_limit"
    assert session._calls == 6 and session._tool_limit == 8
    assert len(session._evaluation_batches) == 2
    assert session._evaluation_proposals == accepted
    assert session.call("generate_ranked_report", {})["report_retained"] is True


def test_empty_final_batch_is_not_replaced_with_parent_authored_unknowns(monkeypatch):
    session, _, _, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    accepted = deepcopy(session._evaluation_proposals)
    reply = session.call("evaluate_candidate_fit", {"evaluations": []})
    assert reply["evaluation_feedback"] == []
    assert reply["attribute_review"]["reviewed_task_count"] == 0
    assert reply["attribute_review"]["unattempted_task_count"] == 4
    assert session._evaluation_proposals == accepted
    assert len(session._evaluation_batches) == 2
    final = session.finalize()
    assert final["result"]["literature_evaluation"]["proposals"] == accepted


def test_last_available_tool_call_retains_final_partial_without_another_call(
    monkeypatch,
):
    session, reply, _, _ = prepare(monkeypatch, {"band_gap": 1})
    session._tool_limit = 8
    session._calls = 7
    valid = task_rows(reply["attribute_review"]["tasks"][:1])
    final = session.call("evaluate_candidate_fit", {"evaluations": valid})
    assert final["evaluation_phase"] == "report_completion"
    assert final["next_step"] is None
    assert final["attribute_review"]["tasks"] == []
    assert "assessment_work" not in final
    assert session._calls == 8 and len(session._evaluation_batches) == 2
    with pytest.raises(AgentToolError) as caught:
        session.call("evaluate_candidate_fit", {"evaluations": []})
    assert caught.value.reason_code == "tool_call_limit"
    assert session._calls == 8
    retained = session.finalize()["result"]["literature_evaluation"]["proposals"]
    assert valid[0] in retained
    assert len(retained) == 5  # Four general rows plus the one submitted unknown.


def test_final_reply_read_is_idempotent_and_never_scores_task_anchors(monkeypatch):
    session, _, _, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    before = deepcopy((session._evaluation_proposals, session._evaluation))
    first = session._reply("evaluate_candidate_fit")
    counts = (session._calls, len(session._evaluation_batches))
    for _ in range(3):
        assert session._reply("evaluate_candidate_fit") == first
    assert (session._calls, len(session._evaluation_batches)) == counts == (4, 1)
    assert (session._evaluation_proposals, session._evaluation) == before
    assert all(row["coverage"] == 0 for row in session._evaluation["ranked_candidates"])
    assert PARAGRAPHS[0] in first["attribute_documents"][0]["text"]
