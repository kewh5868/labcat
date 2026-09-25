"""Final-batch instructions combine safe retained work, without new
calls."""

from copy import deepcopy

import pytest
from test_attribute_review_worklist import task_rows
from test_candidate_assessment_completion import assessments, prepared
from test_preassessment_attribute_evidence import prepare

from labcat.agent_tools import AgentToolError


@pytest.mark.parametrize("accepted_mask", range(4))
def test_final_batch_combines_general_gaps_and_delivered_properties(
    monkeypatch, accepted_mask
):
    session, _, _, _ = prepare(monkeypatch, {"band_gap": 0.8, "density": 0.2})
    application = [
        row
        for row in session._evaluation_proposals
        if row["criterion_id"] == "application_fit"
    ]
    # All subsets of the retained first generic judgments reproduce the defect.
    session._evaluation_proposals = [
        row for index, row in enumerate(application) if accepted_mask & (1 << index)
    ]
    before = deepcopy(session._evaluation_proposals)
    calls = session._calls
    reply = session._reply("evaluate_candidate_fit")
    assert reply["evaluation_phase"] == "final_assessment"
    assert reply["remaining_evaluation_batches"] == 1
    assert "same final call" in reply["assessment_guidance"]
    assert "first generic batch" not in reply["assessment_guidance"]
    assert "no third" in reply["assessment_guidance"]
    assert set(reply["priority_criteria"]) == {
        *(
            criterion
            for gap in reply["candidate_assessment_gaps"]
            for criterion in gap["missing_criteria"]
        ),
        *(task["criterion_id"] for task in reply["attribute_review"]["tasks"]),
    }
    assert reply["assessment_work"] == {
        "general_pairs_remaining": 4 - accepted_mask.bit_count(),
        "attribute_tasks_in_reply": 4,
        "combined_rows_in_reply": 8 - accepted_mask.bit_count(),
        "row_guidance": 24,
        "is_evidence": False,
    }
    assert session._evaluation_proposals == before and session._calls == calls


def test_rejected_general_corrections_do_not_defer_final_attribute_pass(monkeypatch):
    session = prepared(monkeypatch)
    args = assessments(session, first_only=True)
    args["evaluations"][0]["quote"] = "Fabricated quotation never in the source."
    reply = session.call("evaluate_candidate_fit", args)
    assert reply["evaluation_phase"] == "final_assessment"
    assert reply["correction_available"]
    assert "assessment_guidance" in reply["evaluation_input_guidance"]
    assert "Correct only the indexed" not in reply["evaluation_input_guidance"]
    assert len(session._evaluation_proposals) == 1
    final = session.call("evaluate_candidate_fit", assessments(session))
    assert final["evaluation_phase"] == "report_completion"
    assert not final["correction_available"]
    assert "assessment_work" not in final
    with pytest.raises(AgentToolError, match="candidate evaluation limit"):
        session.call("evaluate_candidate_fit", {"evaluations": []})


def test_unknown_final_tasks_remain_unknown_with_same_finite_budgets(monkeypatch):
    session, reply, _, _ = prepare(monkeypatch, {"band_gap": 1})
    before = deepcopy(session._evaluation)
    rows = task_rows(reply["attribute_review"]["tasks"])
    reply = session.call("evaluate_candidate_fit", {"evaluations": rows})
    assert reply["evaluation_phase"] == "report_completion"
    assert reply["remaining_evaluation_batches"] == 0
    assert len(session._evaluation_batches) == 2
    assert all(row["coverage"] == 0 for row in session._evaluation["ranked_candidates"])
    assert [
        row["priority_score"] for row in session._evaluation["ranked_candidates"]
    ] == [row["priority_score"] for row in before["ranked_candidates"]]
    assert session.call("generate_ranked_report", {})["report_retained"]


def test_first_batch_guidance_is_preserved(monkeypatch):
    session = prepared(monkeypatch)
    reply = session._reply("propose_candidate_leads")
    assert reply["evaluation_phase"] == "application_screening"
    assert reply["priority_criteria"] == ["application_fit", "demonstrated_use"]
    assert reply["remaining_evaluation_batches"] == 2
    assert "first generic batch" in reply["assessment_guidance"]
    assert "assessment_work" not in reply
