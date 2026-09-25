"""Synthetic source-only pipeline regressions; not live scientific
validation."""

import json
from copy import deepcopy

import pytest
from test_goose_candidate_transport import source

from labcat import public_sources, science
from labcat.agent_tools import ResearchToolSession
from labcat.config import load_config
from labcat.science.sources import load_snapshot
from labcat.source_preferences import default_source_preferences


def prepared_session(
    monkeypatch,
    prompt,
    application,
    *,
    source_observer=None,
    intent=None,
    followup=None,
):
    calls = {"search": 0}
    names = ("TESTONLY-Alpha", "TESTONLY-Beta", "TESTONLY-Gamma")
    passages = [
        f"{name} is discussed as a candidate for {application} "
        "in this synthetic test fixture."
        for name in names
    ]
    references = [
        source(index + 1, text=passage) for index, passage in enumerate(passages)
    ]

    def search(*args, **kwargs):
        calls["search"] += 1
        return {
            "references": deepcopy(references),
            "source_statuses": [],
            "caveats": [],
        }

    monkeypatch.setattr(public_sources, "search_public_sources", search)
    monkeypatch.setattr(
        "labcat.research._add_attribute_research",
        followup or (lambda *args, **kwargs: None),
    )
    session = ResearchToolSession(
        prompt,
        load_config(),
        # Deliberately unavailable selected attributes must not erase the
        # application discussion. This test does not test class inference.
        ranking_profile={
            "importance": {"density": 0.4, "solution_processability": 0.6}
        },
        source_preferences={
            **default_source_preferences(),
            "materials_project_mode": "off",
            "enabled_sources": ["openalex"],
        },
        source_observer=source_observer,
    )
    assessment = {"decision": "materials_research"}
    if intent is not None:
        assessment["intent"] = intent
    session.call("assess_research_intent", assessment)
    documents = session.call("search_public_references", {})["public_documents"]
    session.call(
        "propose_candidate_leads",
        {
            "proposals": [
                {
                    "document_id": document["document_id"],
                    "name": name,
                    "quote": passage,
                }
                for document, name, passage in zip(
                    documents, names, passages, strict=True
                )
            ]
        },
    )
    return session, calls


def assert_preliminary_only(report):
    assert report["stage"] == "partial"
    evaluation = report["result"]["literature_evaluation"]
    assert evaluation["version"] == "literature-fit-v2"
    assert evaluation["proposals"] == []
    assert evaluation["unranked_candidates"] == []
    assert evaluation["is_material_evidence"] is False
    rows = evaluation["ranked_candidates"]
    assert len(rows) == len(report["result"]["candidate_leads"]) == 3
    for row in rows:
        assert row["rank"] == 1
        assert row["ranking_basis"] == "preliminary"
        assert row["observed_fit"] is None
        assert row["coverage"] == 0
        assert row["priority_score"] == row["preliminary_score"]
        assert all(item["judgment"] == "unknown" for item in row["criteria"])
        assert all(not item["assessments"] for item in row["criteria"])
        assert set(row["stability_unknown"]) == {
            "stability",
            "ambient_phase_stability",
            "operational_stability",
        }
    assert (
        "No scored material shortlist was generated" not in report["result"]["summary"]
    )


@pytest.mark.parametrize(
    "prompt,application,material_class,target,identity_scope",
    [
        (
            "What perovskites could I try in a solar cell?",
            "solar cells",
            "perovskites",
            "perovskites",
            "bulk",
        ),
        (
            "Suggest some metals for a lightweight bicycle frame.",
            "bicycle frames",
            "metals_metal_alloys",
            "metals",
            "bulk",
        ),
        (
            "I need an organic material for a flexible solar panel.",
            "flexible solar panels",
            "organic_electronic_materials",
            "organic material",
            "molecular",
        ),
        (
            "Which quantum dots might work in a display?",
            "displays",
            "semiconductor_nanocrystals",
            "quantum dots",
            "nanoscale",
        ),
        (
            "Help me compare plastics for transparent food packaging.",
            "transparent food packaging",
            "polymers",
            "plastics",
            "molecular",
        ),
    ],
)
def test_diverse_plain_requests_keep_named_candidates_without_attributes(
    monkeypatch, prompt, application, material_class, target, identity_scope
):
    # Simulate the model's closed semantic assessment. No fixed phrase detector
    # must independently recognize a lay term such as "plastics" to admit it.
    session, calls = prepared_session(
        monkeypatch,
        prompt,
        application,
        intent={
            "material_class": material_class,
            "application": "unknown",
            "identity_scope": identity_scope,
            "target_spans": [target],
            "application_spans": [],
            "environment_spans": [],
            "processing_spans": [],
            "goals": [],
        },
    )
    report = session.finalize()
    assert_preliminary_only(report)
    assert not report["result"]["candidates"]
    assert report == session.finalize()
    assert calls == {"search": 1}
    assert (
        session.build_plan["stages"]["evaluate_candidate_fit"]["execution_count"] == 0
    )


def test_unexpected_quantitative_failure_preserves_healthy_discovery_shortlist(
    monkeypatch,
):
    session, calls = prepared_session(
        monkeypatch, "Suggest some polymers for flexible packaging.", "packaging"
    )
    calls["repository"] = 0

    def unavailable(*args, **kwargs):
        calls["repository"] += 1
        raise RuntimeError("PRIVATE_REPOSITORY_FAILURE_CANARY")

    monkeypatch.setattr(science, "run_research", unavailable)
    report = session.finalize()
    assert_preliminary_only(report)
    assert not report["result"]["candidates"]
    assert len(report["sources"]) == 3
    assert "PRIVATE_REPOSITORY_FAILURE_CANARY" not in json.dumps(report)
    assert report == session.finalize()
    assert calls == {"search": 1, "repository": 1}


@pytest.mark.parametrize("marked_retrieval_failure", [True, False])
def test_only_explicitly_marked_source_failure_recovers_goose_public_shortlist(
    monkeypatch, marked_retrieval_failure
):
    session, calls = prepared_session(
        monkeypatch, "Suggest some polymers for flexible packaging.", "packaging"
    )
    calls["repository"] = 0

    def blocked(*args, **kwargs):
        calls["repository"] += 1
        outcome = science._blocked("The synthetic source request was blocked.")
        if marked_retrieval_failure:
            outcome["result"]["failure_stage"] = "material_retrieval"
        return outcome

    monkeypatch.setattr(science, "run_research", blocked)
    report = session.finalize()
    if marked_retrieval_failure:
        assert_preliminary_only(report)
        assert not report["result"]["candidates"]
    else:
        # A general block cannot be guessed to be an optional-source outage.
        assert report["stage"] == "blocked"
        assert not report["result"].get("literature_evaluation")
    assert report == session.finalize()
    assert calls == {"search": 1, "repository": 1}


def quantitative_fixture(monkeypatch):
    """Use an existing source fixture for preservation, never production
    fallback."""
    records, metadata = load_snapshot()
    monkeypatch.setattr(
        science,
        "retrieve_nomad",
        lambda *args, **kwargs: (
            deepcopy(records),
            {**deepcopy(metadata), "mode": "injected_test_fixture"},
        ),
    )
    report = science.run_research(
        "Find oxide dielectric candidates.",
        load_config(),
        importance={"band_gap": 1},
        materials_project_mode="off",
        allow_nomad=True,
        allow_hybrid3=False,
        allow_public_dielectric=False,
    )
    assert report["result"]["candidates"]
    calls = []

    def retrieve(*args, **kwargs):
        calls.append(True)
        return deepcopy(report)

    monkeypatch.setattr(science, "run_research", retrieve)
    return report, calls


def test_source_observer_failure_preserves_quantitative_and_preliminary_rows(
    monkeypatch,
):
    expected, repository_calls = quantitative_fixture(monkeypatch)
    observer_calls = []

    def observer(*args):
        observer_calls.append(True)
        raise RuntimeError("PRIVATE_OBSERVER_FAILURE_CANARY")

    session, calls = prepared_session(
        monkeypatch,
        "Find oxide materials for thin films.",
        "thin films",
        source_observer=observer,
    )
    report = session.finalize()
    assert_preliminary_only(report)
    assert report["result"]["candidates"] == expected["result"]["candidates"]
    assert "PRIVATE_OBSERVER_FAILURE_CANARY" not in json.dumps(report)
    assert report == session.finalize()
    assert calls == {"search": 1}
    assert observer_calls == repository_calls == [True]


def test_optional_attribute_followup_failure_preserves_both_shortlists(monkeypatch):
    expected, repository_calls = quantitative_fixture(monkeypatch)
    followup_calls = []

    def unavailable(outcome, *args, **kwargs):
        followup_calls.append(True)
        outcome["result"]["candidates"] = ["PRIVATE_PARTIAL_FOLLOWUP_CANARY"]
        raise RuntimeError("PRIVATE_FOLLOWUP_FAILURE_CANARY")

    session, calls = prepared_session(
        monkeypatch,
        "Find oxide materials for thin films.",
        "thin films",
        followup=unavailable,
    )
    report = session.finalize()
    assert_preliminary_only(report)
    assert report["result"]["candidates"] == expected["result"]["candidates"]
    assert "PRIVATE_FOLLOWUP_FAILURE_CANARY" not in json.dumps(report)
    assert "PRIVATE_PARTIAL_FOLLOWUP_CANARY" not in json.dumps(report)
    assert report == session.finalize()
    assert calls == {"search": 1}
    assert followup_calls == repository_calls == [True]


def test_quantitative_shortlist_does_not_suppress_literature_evaluation_reminder(
    monkeypatch,
):
    expected, repository_calls = quantitative_fixture(monkeypatch)
    session, calls = prepared_session(
        monkeypatch, "Find oxide materials for thin films.", "thin films"
    )
    reply = session.call("generate_ranked_report", {})
    assert reply["evaluation_required"] is True
    assert reply["next_step"] == "evaluate_candidate_fit"
    assert len(reply["admitted_candidates"]) == 3
    assert session.call("generate_ranked_report", {})["status"] == "completed"
    report = session.finalize()
    assert_preliminary_only(report)
    assert report["result"]["candidates"] == expected["result"]["candidates"]
    assert calls == {"search": 1}
    assert repository_calls == [True]
