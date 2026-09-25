"""Bounded recovery from weak source results, without inventing
evidence."""

from copy import deepcopy

import pytest

from labcat.agent_tools import AgentToolError, ResearchToolSession
from labcat.config import load_config
from labcat.source_preferences import default_source_preferences


def reference(index, name):
    return {
        "source_id": "arxiv",
        "record_id": f"2601.{index:05}",
        "title": "SYNTHETIC TEST ONLY comparison",
        "url": f"https://arxiv.org/abs/2601.{index:05}",
        "source_name": "arXiv",
        "access_scope": "public",
        "provenance_status": "verified",
        "kind": "discovery_reference",
        "is_material_evidence": False,
        "metadata": {
            "abstract_read": True,
            "abstract": f"TEST ONLY {name} is discussed in this synthetic fixture.",
        },
        "provenance": {"response_sha256": str(index) * 64},
    }


def make_session(monkeypatch, batches, limit=3):
    calls = []

    def search(topic, sources, maximum, **options):
        calls.append((topic, sources, maximum, options))
        return {"references": deepcopy(batches[len(calls) - 1])}

    monkeypatch.setattr("labcat.public_sources.search_public_sources", search)
    monkeypatch.setattr("labcat.research._add_attribute_research", lambda *a: None)
    session = ResearchToolSession(
        "Find polymers for flexible optoelectronic devices.",
        load_config(),
        source_preferences={
            **default_source_preferences(),
            "enabled_sources": ["arxiv"],
            "max_results_per_source": limit,
            "materials_project_mode": "off",
        },
    )
    session.call("assess_research_intent", {"decision": "materials_research"})
    return session, calls


def proposal(document, name):
    return {
        "document_id": document["document_id"],
        "name": name,
        "quote": document["text"],
    }


def test_feedback_allows_one_correction_and_retains_only_exact_source_names(
    monkeypatch,
):
    session, _ = make_session(monkeypatch, [[reference(1, "TESTONLY-Alpha")]])
    doc = session.call(
        "search_public_references", {"topic": "polymers optoelectronics"}
    )["public_documents"][0]
    wrong = proposal(doc, "UNSUPPORTED-CANARY")
    feedback = session.call("propose_candidate_leads", {"proposals": [wrong]})
    assert feedback["candidate_lead_count"] == 0
    assert feedback["proposal_feedback"] == [
        {
            "proposal_index": 0,
            "status": "rejected",
            "reason": "not_an_exact_supported_mention",
        }
    ]
    assert "UNSUPPORTED-CANARY" not in str(feedback)
    assert feedback["correction_available"] is True
    repeated = session.call("propose_candidate_leads", {"proposals": [wrong]})
    assert repeated["correction_available"] is True
    assert (
        session.build_plan["stages"]["propose_candidate_leads"]["execution_count"] == 1
    )
    corrected = session.call(
        "propose_candidate_leads", {"proposals": [proposal(doc, "TESTONLY-Alpha")]}
    )
    assert corrected["candidate_lead_count"] == 1
    assert corrected["correction_available"] is False
    with pytest.raises(AgentToolError):
        session.call("propose_candidate_leads", {"proposals": []})
    result = session.finalize()["result"]
    assert [lead["name"] for lead in result["candidate_leads"]] == ["TESTONLY-Alpha"]
    assert result["candidate_leads"][0]["properties_verified"] is False
    assert result["candidates"] == []


def test_refinement_preserves_citations_replaces_weak_hits_and_keeps_source_cap(
    monkeypatch,
):
    alpha, beta, gamma = [
        reference(i, name)
        for i, name in enumerate(
            ["TESTONLY-Alpha", "TESTONLY-Beta", "TESTONLY-Gamma"], start=1
        )
    ]
    revised_alpha = reference(1, "CHANGED-SOURCE")
    session, calls = make_session(
        monkeypatch, [[alpha, beta], [revised_alpha, gamma]], limit=2
    )
    first = session.call(
        "search_public_references", {"topic": "polymers optoelectronics"}
    )
    assert first["refinement_available"] is True
    doc = first["public_documents"][0]
    session.call(
        "propose_candidate_leads", {"proposals": [proposal(doc, "TESTONLY-Alpha")]}
    )
    second = session.call(
        "search_public_references", {"topic": "conducting polymer films"}
    )
    assert second["reference_count"] == 2
    assert second["source_statuses"][0]["reference_count"] == 2
    assert second["refinement_available"] is False
    retained = {d["document_id"]: d for d in session._lead_documents()}
    assert [
        retained[d["document_id"]]["record_id"] for d in second["public_documents"]
    ] == [
        "2601.00001",
        "2601.00003",
    ]
    assert second["public_documents"][0] == doc
    assert second["candidate_lead_count"] == 1
    session.call("search_public_references", {"topic": "Conducting   polymer films"})
    with pytest.raises(AgentToolError):
        session.call("search_public_references", {"topic": "another query"})
    assert len(calls) == 2
    assert calls[0][3]["deadline"] == calls[1][3]["deadline"]
    assert all(call[3]["focused_topic"] is True for call in calls)
    assert (
        session.build_plan["stages"]["search_public_references"]["execution_count"] == 2
    )
    lead = session.finalize()["result"]["candidate_leads"][0]
    assert lead["name"] == "TESTONLY-Alpha"
    assert lead["citations"][0]["document_id"] == doc["document_id"]
    assert lead["citations"][0]["record_id"] == alpha["record_id"]
    assert lead["citations"][0]["title"] == alpha["title"]
    assert lead["citations"][0]["url"] == alpha["url"]


def test_refinement_never_runs_after_report_and_repeated_requests_are_cached(
    monkeypatch,
):
    session, calls = make_session(monkeypatch, [[reference(1, "TESTONLY-Alpha")]])
    session.call("search_public_references", {"topic": "polymers optoelectronics"})
    session.call("search_public_references", {})
    session.finalize()
    session.call("search_public_references", {"topic": "polymers optoelectronics"})
    with pytest.raises(AgentToolError):
        session.call("search_public_references", {"topic": "new polymer topic"})
    assert len(calls) == 1


def test_unknown_document_feedback_does_not_echo_untrusted_identity(monkeypatch):
    session, _ = make_session(monkeypatch, [[reference(1, "TESTONLY-Alpha")]])
    session.call("search_public_references", {})
    reply = session.call(
        "propose_candidate_leads",
        {
            "proposals": [
                {
                    "document_id": "UNKNOWN-DOCUMENT-CANARY",
                    "name": "TESTONLY-Alpha",
                    "quote": "TEST ONLY TESTONLY-Alpha is discussed in this "
                    "synthetic fixture.",
                }
            ]
        },
    )
    assert reply["proposal_feedback"][0]["reason"] == "unknown_document"
    assert "UNKNOWN-DOCUMENT-CANARY" not in str(reply)


def test_capacity_feedback_counts_only_retained_names(monkeypatch):
    names = ["TESTONLY-" + letter for letter in "ABCDEFGHIJKLMN"]
    row = reference(1, " and ".join(names))
    session, _ = make_session(monkeypatch, [[row]])
    doc = session.call("search_public_references", {})["public_documents"][0]
    first = [proposal(doc, name) for name in names[:7]]
    second = [proposal(doc, name) for name in names[7:]]
    session.call("propose_candidate_leads", {"proposals": first})
    reply = session.call("propose_candidate_leads", {"proposals": second})
    assert reply["candidate_lead_count"] == 12
    assert [item["status"] for item in reply["proposal_feedback"]] == [
        "accepted"
    ] * 5 + ["rejected"] * 2
    assert reply["proposal_feedback"][-1]["reason"] == "candidate_capacity_reached"
    assert len(session.finalize()["result"]["candidate_leads"]) == 12


def test_refinement_does_not_resolve_ambiguous_source_records(monkeypatch):
    first = reference(1, "TESTONLY-Alpha")
    conflicting = reference(1, "TESTONLY-Beta")
    refined = reference(2, "TESTONLY-Gamma")
    session, _ = make_session(monkeypatch, [[first, conflicting], [refined]])
    reply = session.call(
        "search_public_references", {"topic": "polymers optoelectronics"}
    )
    assert reply["public_documents"] == []
    reply = session.call(
        "search_public_references", {"topic": "conducting polymer films"}
    )
    retained = {doc["document_id"]: doc for doc in session._lead_documents()}
    assert [
        retained[doc["document_id"]]["record_id"] for doc in reply["public_documents"]
    ] == ["2601.00002"]
    assert set(retained) == {doc["document_id"] for doc in reply["public_documents"]}
    assert all(doc["record_id"] != "2601.00001" for doc in retained.values())
