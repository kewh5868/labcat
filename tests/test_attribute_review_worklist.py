"""Synthetic source-linked review planning; no provider or public
requests."""

import json
from copy import deepcopy

import pytest
from test_candidate_assessment_completion import assessments, prepared
from test_goose_candidate_transport import source
from test_preassessment_attribute_evidence import NAMES, PARAGRAPHS, prepare

from labcat import agent_tools, public_sources
from labcat.agent_tools import AgentToolError, ResearchToolSession
from labcat.config import load_config
from labcat.research_intent import resolve_intent
from labcat.science.literature_evaluation import (
    evaluate_candidates,
    valid_evaluation_arguments,
)
from labcat.source_preferences import default_source_preferences


def test_report_retention_marker_requires_authoritative_completed_report(monkeypatch):
    session = prepared(monkeypatch)
    assert session.report_retained is False
    reminder = session.call("generate_ranked_report", {})
    assert reminder["report_generated"] is False
    assert "report_retained" not in reminder
    assert session.report_retained is False
    session.call("evaluate_candidate_fit", assessments(session))
    reply = session.call("generate_ranked_report", {})
    assert reply["status"] == "completed"
    assert reply["report_retained"] is True
    assert session.report_retained is True
    assert "report_retained" not in session._reply("evaluate_candidate_fit")


def test_failed_or_blocked_report_is_never_retained_completion(monkeypatch):
    session = prepared(monkeypatch)
    session._report = {"stage": "blocked"}
    for status in ("blocked", "failed", "completed"):
        session._stages["generate_ranked_report"]["status"] = status
        assert session.report_retained is False
        assert "report_retained" not in session._reply("generate_ranked_report")
    session._report = {"stage": "partial"}
    session._stages["generate_ranked_report"]["status"] = "failed"
    assert session.report_retained is False


def task_rows(tasks):
    return [
        {
            **{key: row[key] for key in ("lead_id", "criterion_id", "document_id")},
            "quote": row["quote_anchor"],
            "judgment": "unknown",
            "interpretation": "The requested conditions are not established.",
        }
        for row in tasks
    ]


def test_tasks_bind_exact_full_context_without_creating_assessments(monkeypatch):
    session, reply, calls, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    plan = reply["attribute_review"]
    assert len(plan["tasks"]) == 4
    assert {row["criterion_id"] for row in plan["tasks"]} == {"band_gap", "density"}
    assert [row["criterion_id"] for row in plan["tasks"][:2]] == ["band_gap"] * 2
    assert len({row["lead_id"] for row in plan["tasks"][:2]}) == 2
    assert len(session._evaluation_proposals) == 4  # General batch only.
    documents = {row["document_id"]: row for row in reply["attribute_documents"]}
    for task in plan["tasks"]:
        assert task["quote_anchor"] in documents[task["document_id"]]["text"]
        assert documents[task["document_id"]]["section"] == "Results"
        assert "judgment" not in task and "interpretation" not in task
    rows = task_rows(plan["tasks"])
    reviewed = evaluate_candidates(
        {"evaluations": rows},
        session._accepted_leads,
        session._assessment_references(),
        session._profile,
        documents=session._assessment_documents(),
        admission_checks=True,
    )
    assert all(row["status"] == "accepted" for row in reviewed["feedback"])
    assert plan["offered_task_count"] == plan["unattempted_task_count"] == 4
    assert plan["reviewed_task_count"] == 0
    assert plan["withheld_task_count"] == 0
    assert len(calls["queries"]) == len(calls["articles"]) == 2


def test_accepted_unknowns_count_as_reviewed_without_positive_support(monkeypatch):
    session, reply, _, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    rows = task_rows(reply["attribute_review"]["tasks"])
    response = session.call("evaluate_candidate_fit", {"evaluations": rows})
    assert all(row["status"] == "accepted" for row in response["evaluation_feedback"])
    counts = session.build_plan["attribute_review"]
    assert counts["reviewed_task_count"] == 4
    assert counts["unattempted_task_count"] == 0
    assert response["attribute_review"]["tasks"] == []
    assert all(row["coverage"] == 0 for row in session._evaluation["ranked_candidates"])
    assert len(session._evaluation_batches) == 2


def test_rejected_quote_does_not_count_as_review_or_refill_budget(monkeypatch):
    session, reply, _, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    rows = task_rows(reply["attribute_review"]["tasks"])
    for row in rows:
        row["quote"] = "A forged passage with no source binding."
    response = session.call("evaluate_candidate_fit", {"evaluations": rows})
    assert all(row["status"] == "rejected" for row in response["evaluation_feedback"])
    assert response["attribute_review"]["unattempted_task_count"] == 4
    assert response["attribute_review"]["reviewed_task_count"] == 0
    assert response["attribute_review"]["tasks"] == []
    assert session.call("generate_ranked_report", {})["report_retained"] is True
    assert len(session._evaluation_batches) == 2


def test_general_complete_still_gets_one_bounded_attribute_reminder(monkeypatch):
    session, reply, _, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    assert reply["candidate_assessment_gaps"] == []
    original = session._retrieve
    monkeypatch.setattr(session, "_retrieve", lambda: pytest.fail("Reminder retrieved"))
    reminder = session.call("generate_ranked_report", {})
    assert reminder["status"] == "rejected"
    assert reminder["report_generated"] is False
    assert len(reminder["attribute_review"]["tasks"]) == 4
    assert "report_retained" not in reminder
    monkeypatch.setattr(session, "_retrieve", original)
    # Ignoring the worklist cannot cause a new reminder or a made-up assessment.
    assert session.call("generate_ranked_report", {})["report_retained"] is True
    assert session.build_plan["attribute_review"]["unattempted_task_count"] == 4
    assert len(session._evaluation_proposals) == 4


def test_no_relevant_source_or_no_remaining_call_does_not_force_unknowns(monkeypatch):
    session, reply, _, _ = prepare(monkeypatch, {"band_gap": 1}, unavailable=True)
    assert reply["attribute_review"]["tasks"] == []
    assert reply["attribute_review"]["reviewable_task_count"] == 0
    assert session.call("generate_ranked_report", {})["status"] == "completed"
    session, reply, _, _ = prepare(monkeypatch, {"band_gap": 1})
    session._tool_limit = session._calls + 1
    assert session.call("generate_ranked_report", {})["status"] == "completed"
    assert session.build_plan["candidate_evaluation"]["reminder_requested"] is False


def test_truncated_multibyte_context_has_no_dangling_tasks_or_false_delivery(
    monkeypatch,
):
    paragraphs = tuple(text + " αβγ" * 780 for text in PARAGRAPHS)
    session, reply, _, originals = prepare(
        monkeypatch, {"band_gap": 0.8, "density": 0.2}, paragraphs=paragraphs
    )
    assert reply["attribute_documents_total"] == 2
    assert reply["attribute_documents_shown"] == 1
    delivered = {row["document_id"] for row in reply["attribute_documents"]}
    previous = {row["document_id"] for row in originals}
    assert (
        len(json.dumps(reply, allow_nan=False).encode())
        <= agent_tools.MAX_TOOL_REPLY_BYTES
    )
    plan = reply["attribute_review"]
    assert set(plan["offered_document_ids"]) == previous | delivered
    assert all(row["document_id"] in previous | delivered for row in plan["tasks"])
    assert plan["reviewable_task_count"] == 4
    assert plan["offered_task_count"] == 2
    assert plan["withheld_task_count"] == plan["unoffered_document_task_count"] == 2
    # Original documents, additional source titles and complete bodies remain.
    assert len(session._assessment_documents()) == 6


def test_reads_and_failed_reply_do_not_record_offered_context(monkeypatch):
    session, _, _, _ = prepare(monkeypatch, {"band_gap": 1})
    session._offered_document_ids.clear()
    session._offered_review_keys.clear()
    assert session.build_plan["attribute_review"]["retained_document_count"] == 6
    assert session.build_plan["attribute_review"]["offered_document_count"] == 0
    session._attribute_evaluation_context()
    assert session._offered_document_ids == set()
    monkeypatch.setattr(agent_tools, "MAX_TOOL_REPLY_BYTES", 1)
    with pytest.raises(AgentToolError, match="response exceeded"):
        session._reply("evaluate_candidate_fit")
    assert session._offered_document_ids == session._offered_review_keys == set()


def test_explicit_goal_priority_and_conditions_are_preferences_not_evidence(
    monkeypatch,
):
    session, _, _, _ = prepare(monkeypatch, {"band_gap": 0.9, "density": 0.1})
    interpreted = resolve_intent(
        session._prompt,
        {
            "decision": "materials_research",
            "intent": {
                "material_class": "oxide_dielectrics",
                "application": "unknown",
                "identity_scope": "bulk",
                "target_spans": ["oxide materials"],
                "application_spans": ["insulating films"],
                "environment_spans": [],
                "processing_spans": [],
                "goals": [
                    {
                        "attribute_id": "density",
                        "request_span": "lightweight",
                        "priority": "primary",
                        "relation": "minimize",
                    }
                ],
            },
        },
        session._profile,
        session._selection,
    )
    session._semantic_scope = interpreted["scope"]
    profile = deepcopy(session._profile)
    reply = session._reply("evaluate_candidate_fit")
    plan = reply["attribute_review"]
    assert [row["criterion_id"] for row in plan["tasks"][:2]] == ["density"] * 2
    assert plan["request_preferences"]["is_evidence"] is False
    assert plan["request_preferences"]["application_spans"] == ["insulating films"]
    assert plan["request_preferences"]["requested_goal_spans"] == [
        {"attribute_id": "density", "request_span": "lightweight"}
    ]
    assert "Missing or different conditions are unknown" in plan["guidance"]
    assert "mixed requires actual conflicting evidence" in plan["guidance"]
    assert session._profile == profile  # Explicit values and utility unchanged.


def test_candidate_fairness_is_independent_of_proposal_order(monkeypatch):
    session, reply, _, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    before = reply["attribute_review"]["tasks"]
    session._accepted_leads.reverse()
    after = session._reply("evaluate_candidate_fit")["attribute_review"]["tasks"]
    assert after == before
    assert len({row["lead_id"] for row in before[:2]}) == 2


def test_long_valid_request_preferences_do_not_consume_task_selector_budget(
    monkeypatch,
):
    session, _, _, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    intent = {
        "material_class": "oxide_dielectrics",
        "application": "unknown",
        "identity_scope": "bulk",
    }
    spans = []
    for role in ("target", "application", "environment", "processing"):
        values = [f"{role} preference {index} " + "a" * 180 for index in range(3)]
        intent[role + "_spans"] = values
        spans.extend(values)
    intent["goals"] = [
        {
            "attribute_id": criterion,
            "request_span": criterion + " preference " + "α" * 120,
            "priority": "primary",
            "relation": "consider",
        }
        for criterion in (
            "band_gap",
            "density",
            "stability",
            "ambient_phase_stability",
            "operational_stability",
            "solution_processability",
            "dielectric_total",
            "dielectric_electronic",
        )
    ]
    session._prompt = "Find oxide materials. " + ". ".join(
        spans + [row["request_span"] for row in intent["goals"]]
    )
    session._semantic_scope = resolve_intent(
        session._prompt,
        {"decision": "materials_research", "intent": intent},
        session._profile,
        session._selection,
    )["scope"]
    reply = session._reply("evaluate_candidate_fit")
    plan = reply["attribute_review"]
    assert len(plan["tasks"]) == 4
    assert len(json.dumps(plan).encode()) > agent_tools.MAX_ATTRIBUTE_REVIEW_TASK_BYTES
    assert (
        len(json.dumps(plan["tasks"]).encode())
        <= agent_tools.MAX_ATTRIBUTE_REVIEW_TASK_BYTES
    )
    assert len(json.dumps(reply).encode()) <= agent_tools.MAX_TOOL_REPLY_BYTES
    preferences = plan["request_preferences"]
    assert preferences["identity_scope"] == "bulk"
    assert preferences["target_spans"] == intent["target_spans"]
    assert preferences["environment_spans"] == intent["environment_spans"]
    assert preferences["processing_spans"] == intent["processing_spans"]


def test_zero_weight_stability_not_selected_and_positive_stability_reserves_later_slot(
    monkeypatch,
):
    paragraphs = tuple(
        f"{name} has measured band gap, density, electrical conductivity and "
        "operational stability in the same experiment."
        for name in NAMES
    )
    monkeypatch.setattr(agent_tools, "MAX_ATTRIBUTE_REVIEW_TASKS", 3)
    session, reply, _, _ = prepare(
        monkeypatch,
        {"band_gap": 0.9, "density": 0.8},
        paragraphs=paragraphs,
    )
    assert all(
        row["criterion_id"] != "operational_stability"
        for row in reply["attribute_review"]["tasks"]
    )
    session, reply, _, _ = prepare(
        monkeypatch,
        {"band_gap": 0.9, "density": 0.8, "operational_stability": 0.1},
        paragraphs=paragraphs,
    )
    tasks = reply["attribute_review"]["tasks"]
    assert len(tasks) == 3
    assert [row["criterion_id"] for row in tasks[:2]] == ["band_gap"] * 2
    assert tasks[-1]["criterion_id"] == "operational_stability"


def test_combined_row_guidance_reserves_generic_repairs_with_existing_input_cap(
    monkeypatch,
):
    session, _, _, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    monkeypatch.setattr(
        session,
        "_evaluation_gaps",
        lambda: [{"missing_criteria": ["application_fit", "demonstrated_use"]}] * 11,
    )
    reply = session._reply("evaluate_candidate_fit")
    assert len(reply["attribute_review"]["tasks"]) == 2
    # Count guidance never replaces the actual 24 KB input envelope. In
    # particular, escaped Unicode must still pass the existing byte validator.
    rows = task_rows(reply["attribute_review"]["tasks"])
    assert valid_evaluation_arguments({"evaluations": rows})
    oversized = deepcopy(rows[0])
    oversized["quote"] = "α" * 480
    oversized["interpretation"] = "β" * 200
    assert not valid_evaluation_arguments({"evaluations": [oversized] * 24})


def unselected_session(monkeypatch):
    passage = "TESTONLY-Alpha is discussed for lightweight insulating films."
    calls = []

    def search(*args, **kwargs):
        calls.append(True)
        return {
            "references": [source(1, text=passage)],
            "source_statuses": [],
            "caveats": [],
        }

    monkeypatch.setattr(public_sources, "search_public_sources", search)
    monkeypatch.setattr(
        "labcat.research._add_attribute_research", lambda *args, **kwargs: None
    )
    session = ResearchToolSession(
        "Find oxide materials for lightweight insulating films.",
        load_config(),
        ranking_profile={"importance": {"band_gap": 1}},
        source_preferences={
            **default_source_preferences(),
            "materials_project_mode": "off",
            "enabled_sources": ["openalex"],
        },
    )
    session._tool_limit = 8
    session.call("assess_research_intent", {"decision": "materials_research"})
    return session, calls, passage


def test_repeated_early_generate_requires_selection_then_recovers_within_same_budget(
    monkeypatch,
):
    session, calls, passage = unselected_session(monkeypatch)
    for _ in range(2):
        reply = session.call("generate_ranked_report", {})
        assert reply["status"] == "rejected"
        assert reply["reason_code"] == "candidate_selection_required"
        assert reply["next_step"] == "propose_candidate_leads"
        assert reply["report_generated"] is False
        assert "report_retained" not in reply
        assert session.report_retained is False and session._report is None
    assert len(calls) == 1
    assert session._evaluation_reminded is False
    documents = session.call("search_public_references", {})["public_documents"]
    session.call(
        "propose_candidate_leads",
        {
            "proposals": [
                {
                    "document_id": documents[0]["document_id"],
                    "name": "TESTONLY-Alpha",
                    "quote": passage,
                }
            ]
        },
    )
    session.call("evaluate_candidate_fit", assessments(session))
    result = session.call("generate_ranked_report", {})
    assert result["report_retained"] is True
    assert result["status"] == "completed"
    assert session._calls == 7
    assert len(session._accepted_leads) == 1
    assert len(calls) == 1


def test_empty_selection_is_valid_attempt_without_inventing_candidates(monkeypatch):
    session, _, _ = unselected_session(monkeypatch)
    assert session.call("generate_ranked_report", {})["selection_required"]
    session.call("propose_candidate_leads", {"proposals": []})
    reply = session.call("generate_ranked_report", {})
    assert reply["report_retained"] is True
    assert session._accepted_leads == []
    assert len(session._proposal_batches) == 1


def test_ignored_selection_exhausts_budget_and_only_server_recovery_retains_incomplete(
    monkeypatch,
):
    session, calls, _ = unselected_session(monkeypatch)
    for _ in range(7):
        reply = session.call("generate_ranked_report", {})
        assert reply["status"] == "rejected"
        assert "report_retained" not in reply
    assert reply["next_step"] is None
    with pytest.raises(AgentToolError, match="tool-call limit"):
        session.call("generate_ranked_report", {})
    report = session.finalize()
    assert report["result"]["candidate_leads"] == []
    assert len(calls) == 1
    assert session.report_retained is False
    assert "report_retained" not in session._reply("generate_ranked_report")
