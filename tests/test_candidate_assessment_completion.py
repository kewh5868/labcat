"""Bounded completion attempts use synthetic source-bound judgments
only."""

import pytest
from test_preliminary_screening_pipeline import prepared_session

from labcat.agent_tools import AgentToolError


def assessments(session, *, first_only=False):
    rows = []
    for lead in session._accepted_leads[:1] if first_only else session._accepted_leads:
        citation = lead["citations"][0]
        for criterion in ("application_fit", "demonstrated_use"):
            rows.append(
                {
                    "lead_id": lead["id"],
                    "criterion_id": criterion,
                    "document_id": citation["document_id"],
                    "quote": citation["quote"],
                    "judgment": "unknown",
                    "interpretation": (
                        "The synthetic passage does not establish this criterion."
                    ),
                }
            )
    return {"evaluations": rows}


def prepared(monkeypatch):
    return prepared_session(
        monkeypatch, "Suggest polymers for flexible packaging.", "packaging"
    )[0]


def test_sparse_first_batch_reports_each_remaining_gap_and_allows_one_completion(
    monkeypatch,
):
    session = prepared(monkeypatch)
    reply = session.call(
        "evaluate_candidate_fit", assessments(session, first_only=True)
    )
    assert len(reply["candidate_assessment_gaps"]) == 2
    assert all(
        row["missing_criteria"] == ["application_fit", "demonstrated_use"]
        for row in reply["candidate_assessment_gaps"]
    )
    reminder = session.call("generate_ranked_report", {})
    assert reminder["evaluation_required"] is True
    reply = session.call("evaluate_candidate_fit", assessments(session))
    assert reply["candidate_assessment_gaps"] == []
    assert reply["correction_available"] is False
    report = session.finalize()
    assert len(report["result"]["literature_evaluation"]["ranked_candidates"]) == 3
    assert len(report["result"]["literature_evaluation"]["proposals"]) == 6
    assert all(
        row["priority_score"] == 0.225
        for row in report["result"]["literature_evaluation"]["ranked_candidates"]
    )


def test_explicit_unknowns_finish_attempt_without_demanding_supported_evidence(
    monkeypatch,
):
    session = prepared(monkeypatch)
    session.call("evaluate_candidate_fit", assessments(session))
    reply = session.call("generate_ranked_report", {})
    assert not reply.get("evaluation_required")
    assert reply["status"] == "completed"


def test_rejected_judgments_do_not_satisfy_completion_and_reminder_is_finite(
    monkeypatch,
):
    session = prepared(monkeypatch)
    invalid = assessments(session)
    for row in invalid["evaluations"]:
        row["quote"] = "Forged text absent from every retained source."
    reply = session.call("evaluate_candidate_fit", invalid)
    assert len(reply["candidate_assessment_gaps"]) == 3
    assert session.call("generate_ranked_report", {})["evaluation_required"]
    # An unresponsive model cannot cause a reminder loop or invented judgments.
    assert session.call("generate_ranked_report", {})["status"] == "completed"
    assert session.finalize()["result"]["literature_evaluation"]["proposals"] == []


def test_last_available_call_finalizes_instead_of_requesting_impossible_completion(
    monkeypatch,
):
    session = prepared(monkeypatch)
    session._tool_limit = 5
    session.call("evaluate_candidate_fit", assessments(session, first_only=True))
    reply = session.call("generate_ranked_report", {})
    assert reply["status"] == "completed"
    assert not reply.get("evaluation_required")
    with pytest.raises(AgentToolError, match="tool-call limit"):
        session.call("evaluate_candidate_fit", assessments(session))
    assert len(session.finalize()["result"]["literature_evaluation"]["proposals"]) == 2


def test_followup_receives_bound_leads_and_scope_before_report_is_rendered(monkeypatch):
    prompt = "Suggest polymers for flexible packaging in humid air."
    captured = []

    def followup(outcome, prompt, config, preferences, controls, *, semantic_scope):
        captured.append((outcome["result"]["candidate_leads"], semantic_scope))

    session, _ = prepared_session(
        monkeypatch,
        prompt,
        "packaging",
        followup=followup,
        intent={
            "material_class": "polymers",
            "application": "unknown",
            "identity_scope": "molecular",
            "target_spans": ["polymers"],
            "application_spans": ["flexible packaging"],
            "environment_spans": ["humid air"],
            "processing_spans": [],
            "goals": [],
        },
    )
    assert len(captured) == 0
    session.call("evaluate_candidate_fit", assessments(session))
    assert len(captured) == 1
    report = session.finalize()
    assert len(captured) == 1
    leads, scope = captured[0]
    assert leads == report["result"]["candidate_leads"]
    assert len(leads) == 3 and all(lead["citations"] for lead in leads)
    assert scope["application_spans"] == ["flexible packaging"]
    assert scope["environment_spans"] == ["humid air"]
    assert scope["is_evidence"] is False


def test_admission_prioritizes_generic_assessment_without_removing_selected_criteria(
    monkeypatch,
):
    session = prepared(monkeypatch)
    reply = session._reply("propose_candidate_leads")
    assert reply["next_step"] == "evaluate_candidate_fit"
    assert reply["evaluation_phase"] == "application_screening"
    assert reply["priority_criteria"] == ["application_fit", "demonstrated_use"]
    assert reply["remaining_evaluation_batches"] == 2
    preferences = {
        item["criterion_id"]: item for item in reply["evaluation_preferences"]
    }
    assert preferences["density"]["importance"] == 0.4
    assert preferences["solution_processability"]["importance"] == 0.6
    assert session._evaluation_batches == {}

    refined = session.call("evaluate_candidate_fit", assessments(session))
    assert refined["evaluation_phase"] == "final_assessment"
    assert refined["next_step"] == "evaluate_candidate_fit"
    assert refined["remaining_evaluation_batches"] == 1
    # Selected preferences remain available, but no property task was delivered.
    assert refined["priority_criteria"] == []
    assert refined["evaluation_preferences"] == reply["evaluation_preferences"]


def test_generation_reminder_returns_before_repository_work(monkeypatch):
    session = prepared(monkeypatch)
    original_retrieve = session._retrieve
    monkeypatch.setattr(
        session, "_retrieve", lambda: pytest.fail("Reminder invoked repository work")
    )
    reminder = session.call("generate_ranked_report", {})
    assert reminder["evaluation_required"] is True
    assert reminder["next_step"] == "evaluate_candidate_fit"
    assert reminder["evaluation_phase"] == "application_screening"
    assert session._repository is None and session._report is None

    monkeypatch.setattr(session, "_retrieve", original_retrieve)
    session.call("evaluate_candidate_fit", assessments(session))
    assert session.call("generate_ranked_report", {})["status"] == "completed"
    assert session._repository is not None


def test_premature_report_is_an_actionable_mcp_error_without_losing_leads(monkeypatch):
    import json

    from labcat import goose_mcp

    session = prepared(monkeypatch)
    monkeypatch.setattr(
        goose_mcp,
        "_broker",
        lambda route, body: session.call(body["name"], body["arguments"]),
    )
    result = goose_mcp.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "generate_ranked_report", "arguments": {}},
        }
    )["result"]
    assert result["isError"] is True
    reminder = json.loads(result["content"][0]["text"])
    assert reminder["reason_code"] == "candidate_assessment_required"
    assert reminder["report_generated"] is False
    assert reminder["next_step"] == "evaluate_candidate_fit"
    assert session._report is None
    assert len(session._accepted_leads) == 3
    session.call("evaluate_candidate_fit", assessments(session))
    assert session.call("generate_ranked_report", {})["status"] == "completed"
    assert len(session.finalize()["result"]["candidate_leads"]) == 3


def test_last_evaluation_batch_guides_completion_without_new_calls(monkeypatch):
    session = prepared(monkeypatch)
    session.call("evaluate_candidate_fit", assessments(session, first_only=True))
    reply = session.call("evaluate_candidate_fit", assessments(session))
    assert reply["remaining_evaluation_batches"] == 0
    assert reply["evaluation_phase"] == "report_completion"
    assert reply["next_step"] == "generate_ranked_report"
    assert reply["correction_available"] is False
    assert session._calls == 5

    session._tool_limit = session._calls
    reply = session._reply("evaluate_candidate_fit")
    assert reply["next_step"] is None
    assert session._calls == 5


def test_plan_distinguishes_general_assessment_coverage_from_successful_tool_calls(
    monkeypatch,
):
    session = prepared(monkeypatch)
    pending = session.build_plan["candidate_evaluation"]
    assert pending["status"] == "pending"
    assert pending["completion_scope"] == "application_fit_and_demonstrated_use"
    assert pending["general_judgments_total"] == 6
    assert pending["general_judgments_retained"] == 0
    assert pending["general_judgments_missing"] == 6
    assert pending["candidates_missing_general_judgments"] == 3

    session.call("evaluate_candidate_fit", assessments(session, first_only=True))
    partial = session.build_plan["candidate_evaluation"]
    assert partial["status"] == "partial"
    assert partial["general_judgments_retained"] == 2
    assert partial["general_judgments_missing"] == 4
    assert partial["candidates_missing_general_judgments"] == 2

    session.call("evaluate_candidate_fit", assessments(session))
    assessed = session.build_plan["candidate_evaluation"]
    # All retained judgments are unknown: coverage is not scientific quality.
    assert assessed["status"] == "assessed"
    assert assessed["general_judgments_retained"] == 6
    assert assessed["general_judgments_missing"] == 0
    assert assessed["candidates_missing_general_judgments"] == 0
    assert assessed["model_interpretations_are_measurements"] is False


def test_rejected_proposals_do_not_claim_completed_general_assessment(monkeypatch):
    session = prepared(monkeypatch)
    arguments = assessments(session)
    for row in arguments["evaluations"]:
        row["quote"] = "TEST ONLY forged text is absent from the retained sources."
    session.call("evaluate_candidate_fit", arguments)
    completion = session.build_plan["candidate_evaluation"]
    assert completion["batches"] == 1
    assert completion["status"] == "pending"
    assert completion["general_judgments_retained"] == 0
    assert completion["general_judgments_missing"] == 6


def test_plan_with_no_admitted_candidates_does_not_claim_assessment(monkeypatch):
    from test_goose_candidate_transport import tools

    session, _ = tools(monkeypatch)
    completion = session.build_plan["candidate_evaluation"]
    assert completion["status"] == "no_candidates"
    assert completion["general_judgments_total"] == 0
    assert completion["general_judgments_retained"] == 0
    assert completion["general_judgments_missing"] == 0
    assert completion["candidates_missing_general_judgments"] == 0
