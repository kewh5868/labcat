"""Coverage notices derive from source-bound judgments, not provider
success."""

from copy import deepcopy

import pytest
from test_literature_evaluation_reporting import evaluated_report
from test_preliminary_ranking_reporting import preliminary_report

from labcat.report_exports import prepare_presentation
from labcat.science.literature_evaluation import evaluate_candidates


@pytest.mark.parametrize("provider_completed", [False, True])
def test_missing_general_assessments_are_visible_even_after_provider_completion(
    provider_completed,
):
    report = preliminary_report()
    if provider_completed:
        report["result"]["execution"]["agent"] = {"status": "completed"}
    # Historical v2 data lacks completion metadata; derive from valid proposals.
    assert "build_plan" not in report["result"]["execution"]
    original = deepcopy(report)
    prepared = prepare_presentation(report)
    for field in ("pi_summary", "technical_audit"):
        text = prepared[field]
        assert "Candidate assessment:" in text
        assert (
            "24 application relevance or demonstrated use judgments are missing" in text
        )
        assert "across 12 of 12 candidates" in text
        assert ("The provider run completed" in text) is provider_completed
        assert "Model-led research stopped" not in text
        assert "Candidate shortlist:" in text
    assert report == original


def test_missing_counts_ignore_untrusted_cached_completion_claims():
    report = preliminary_report(assessed=True)
    report["result"]["build_plan"] = {
        "candidate_evaluation": {
            "status": "assessed",
            "general_judgments_missing": 0,
            "candidates_missing_general_judgments": 0,
        }
    }
    prepared = prepare_presentation(report)
    for field in ("pi_summary", "technical_audit"):
        assert (
            "12 application relevance or demonstrated use judgments are missing"
            in prepared[field]
        )


def test_retained_unknown_judgments_are_assessed_but_not_validated_properties():
    report = preliminary_report()
    result = report["result"]
    proposals = [
        {
            "lead_id": lead["id"],
            "criterion_id": criterion,
            "document_id": lead["citations"][0]["document_id"],
            "quote": lead["citations"][0]["quote"],
            "judgment": "unknown",
            "interpretation": (
                "TEST ONLY: the cited excerpt does not establish this criterion."
            ),
        }
        for lead in result["candidate_leads"]
        for criterion in ("application_fit", "demonstrated_use")
    ]
    result["literature_evaluation"] = evaluate_candidates(
        {"evaluations": proposals},
        result["candidate_leads"],
        report["sources"],
        result["execution"]["ranking_profile"],
    )["evaluation"]
    result["execution"]["agent"] = {"status": "completed"}
    prepared = prepare_presentation(report)
    for field in ("pi_summary", "technical_audit"):
        assert "Candidate assessment:" not in prepared[field]
        assert "Candidate shortlist:" in prepared[field]
    assert result["literature_evaluation"]["properties_verified"] is False
    assert all(
        row["priority_score"] == 0.225
        for row in result["literature_evaluation"]["ranked_candidates"]
    )


def test_historical_v1_has_no_new_general_assessment_requirement():
    report = evaluated_report()
    original = deepcopy(report)
    prepared = prepare_presentation(report)
    for field in ("pi_summary", "technical_audit"):
        assert "Candidate assessment:" not in prepared[field]
    assert report == original
