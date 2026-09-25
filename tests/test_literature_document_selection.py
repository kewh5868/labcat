"""Explicit parent document selections keep their bounded, verified
snapshots."""

from copy import deepcopy

import pytest
from test_candidate_leads import reference

from labcat.agent_tools import ResearchToolSession
from labcat.config import load_config
from labcat.science.candidate_leads import (
    MAX_DOCUMENTS,
    discovery_documents,
    validate_candidate_leads,
)
from labcat.science.literature_evaluation import (
    evaluate_candidates,
    validate_evaluation,
)

NAME = "TESTONLY-Alpha"
MENTION = f"{NAME} is discussed for lightweight polymer components."
PROPERTY = f"{NAME} has low density in the described specimen."


def public_reference(index, text):
    item = reference(index, text=text)
    item["metadata"].update(
        record_type="open_access_publication",
        open_access_reported=True,
        oa_status="provider_reported",
        version="publishedVersion",
        full_text_read=False,
    )
    return item


@pytest.fixture
def selected():
    references = [public_reference(1, MENTION)] + [
        public_reference(index, "TEST ONLY background without candidate claims.")
        for index in range(2, MAX_DOCUMENTS + 2)
    ]
    followup = public_reference(99, PROPERTY)
    profile = {"importance": {"density": 1.0}}
    documents = discovery_documents(references)
    anchor = documents[0]
    lead = validate_candidate_leads(
        [{"document_id": anchor["document_id"], "name": NAME, "quote": MENTION}],
        documents,
        references,
        profile["importance"],
    )[0]
    target = discovery_documents([followup])[0]
    all_references = [*references, followup]
    supplied = discovery_documents(
        all_references,
        preferred_document_ids=[anchor["document_id"], target["document_id"]],
    )
    default_ids = {d["document_id"] for d in discovery_documents(all_references)}
    assert target["document_id"] not in default_ids
    assert len(supplied) == MAX_DOCUMENTS
    return {
        "initial": references,
        "followup": followup,
        "references": all_references,
        "documents": supplied,
        "anchor": anchor,
        "target": target,
        "lead": lead,
        "profile": profile,
    }


def general_row(data):
    return {
        "lead_id": data["lead"]["id"],
        "criterion_id": "application_fit",
        "document_id": data["anchor"]["document_id"],
        "quote": MENTION,
        "judgment": "unknown",
        "interpretation": "This naming passage does not establish suitability.",
    }


def evaluate(data, rows, documents):
    return evaluate_candidates(
        {"evaluations": rows},
        [data["lead"]],
        data["references"],
        data["profile"],
        documents=documents,
        admission_checks=True,
    )


def test_authentic_uncited_followup_does_not_invalidate_general_assessment(selected):
    before = deepcopy(selected)
    row = general_row(selected)
    explicit = evaluate(selected, [row], selected["documents"])
    historical = evaluate(selected, [row], None)
    assert explicit == historical
    assert explicit["accepted_proposals"] == [row]
    assert selected == before


def test_parent_followup_selection_accepts_general_then_property_batches(selected):
    session = ResearchToolSession(
        "Compare polymer materials for lightweight components.",
        load_config(),
        ranking_profile=selected["profile"],
    )
    session._discovery = {"sources": selected["initial"], "result": {}}
    session._attribute_outcome = {
        "sources": [selected["followup"]],
        "result": {
            "attribute_research": {
                "attributes": [
                    {
                        "attribute_id": "density",
                        "abstract_source_urls": [selected["followup"]["url"]],
                    }
                ]
            }
        },
    }
    session._accepted_leads = [selected["lead"]]
    session._lead_proposals = [
        {
            "name": NAME,
            "document_id": selected["anchor"]["document_id"],
            "quote": MENTION,
        }
    ]
    assert session._assessment_documents() == selected["documents"]
    general = general_row(selected)
    session._evaluate({"evaluations": [general]}, "general")
    assert session._evaluation_proposals == [general]
    attribute = {
        **general,
        "document_id": selected["target"]["document_id"],
        "criterion_id": "density",
        "quote": PROPERTY,
        "judgment": "supports",
        "interpretation": "The reported specimen supports the density preference.",
    }
    session._evaluate({"evaluations": [attribute]}, "attribute")
    assert len(session._evaluation_proposals) == 2
    bundle = session._evaluation
    row = bundle["ranked_candidates"][0]
    assert row["coverage"] == row["observed_fit"] == 1.0
    assert (
        validate_evaluation(
            bundle,
            [selected["lead"]],
            selected["references"],
            selected["profile"],
        )
        == bundle
    )


def test_an_empty_assessment_batch_can_rebind_the_supplied_parent_set(selected):
    output = evaluate(selected, [], selected["documents"])
    assert output["accepted_proposals"] == []
    assert output["evaluation"]["ranked_candidates"][0]["coverage"] == 0
    assert output == evaluate(selected, [], None)


def test_full_shared_union_keeps_valid_unavailable_selector_as_row_feedback(selected):
    # Twenty-three supplied snapshots plus one absent assessment selector fit
    # the existing union cap. Authenticating it does not deliver or use it.
    documents = [
        d
        for d in selected["documents"]
        if d["document_id"] != selected["target"]["document_id"]
    ]
    rows = [general_row(selected)]
    rows.append(
        {
            **rows[0],
            "document_id": selected["target"]["document_id"],
            "quote": PROPERTY,
        }
    )
    output = evaluate(selected, rows, documents)
    assert output["accepted_proposals"] == rows[:1]
    assert output["feedback"][1]["reason"] == "unavailable_document"


def test_explicit_empty_selection_does_not_resurrect_candidate_documents(selected):
    with pytest.raises(ValueError, match="candidate does not match"):
        evaluate(selected, [], [])


def test_explicit_selection_never_silently_adds_a_missing_candidate_anchor(selected):
    documents = [d for d in selected["documents"] if d != selected["anchor"]]
    with pytest.raises(ValueError, match="candidate does not match"):
        evaluate(selected, [general_row(selected)], documents)


def test_historical_selection_does_not_prioritize_an_unrequested_tail_source(selected):
    arguments = {"evaluations": [general_row(selected)]}
    before = evaluate_candidates(
        arguments, [selected["lead"]], selected["initial"], selected["profile"]
    )
    after = evaluate_candidates(
        arguments, [selected["lead"]], selected["references"], selected["profile"]
    )
    assert before == after


@pytest.fixture
def body_selection(selected):
    body = reference(130, provider="europe_pmc", text="TEST ONLY public abstract.")
    body["metadata"].update(
        full_text_read=True,
        full_text_scope="body paragraphs only",
        full_text_provenance={
            "full_text_request_url": (
                "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC130/fullTextXML"
            ),
            "full_text_response_sha256": "b" * 64,
        },
        assessment_passages=[
            {
                "text": PROPERTY,
                "locator": "body/sec[1]/p[1]",
                "section": "TEST ONLY results",
                "article_id": "PMC130",
                "response_sha256": "b" * 64,
                "candidate_ids": [selected["lead"]["id"]],
                "paragraph_complete": True,
            }
        ],
    )
    document = next(d for d in discovery_documents([body]) if d["text"] == PROPERTY)
    selected["references"] = [*selected["initial"], body]
    selected["documents"] = discovery_documents(
        selected["references"],
        preferred_document_ids=[
            selected["anchor"]["document_id"],
            document["document_id"],
        ],
    )
    selected["body"] = body
    selected["body_row"] = {
        **general_row(selected),
        "document_id": document["document_id"],
        "criterion_id": "density",
        "quote": PROPERTY,
        "judgment": "supports",
        "interpretation": "The reported specimen supports the density preference.",
    }
    return selected


def test_explicit_body_snapshot_keeps_hash_bound_source_and_canonical_replay(
    body_selection,
):
    data = body_selection
    output = evaluate(data, [data["body_row"]], data["documents"])
    assert output["accepted_proposals"] == [data["body_row"]]
    bundle = output["evaluation"]
    criterion = next(
        c
        for c in bundle["ranked_candidates"][0]["criteria"]
        if c["criterion_id"] == "density"
    )
    assessment = criterion["assessments"][0]
    assert (
        assessment["response_sha256"] == data["body"]["provenance"]["response_sha256"]
    )
    assert assessment["document_id"] == data["body_row"]["document_id"]
    assert assessment["url"] == data["body"]["url"]
    assert (
        validate_evaluation(bundle, [data["lead"]], data["references"], data["profile"])
        == bundle
    )


@pytest.mark.parametrize("change", ["hash", "text", "incomplete", "locator"])
def test_changed_body_context_cannot_authenticate_an_old_explicit_snapshot(
    body_selection,
    change,
):
    data = body_selection
    metadata = data["body"]["metadata"]
    passage = metadata["assessment_passages"][0]
    if change == "hash":
        metadata["full_text_provenance"]["full_text_response_sha256"] = "c" * 64
    elif change == "text":
        passage["text"] = "TESTONLY-Beta has low density in another specimen."
    elif change == "incomplete":
        passage["paragraph_complete"] = False
    else:
        passage["locator"] = "body/sec[2]/p[1]"
    with pytest.raises(ValueError, match="documents do not match"):
        evaluate(data, [data["body_row"]], data["documents"])
