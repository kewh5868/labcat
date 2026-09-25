"""Independent synthetic scope checks; lexical relevance is not
scientific proof."""

from copy import deepcopy

import pytest
from test_candidate_leads import reference

from labcat.science.candidate_leads import (
    discovery_documents,
    validate_candidate_leads,
)
from labcat.science.literature_evaluation import (
    _criterion_relevant,
    evaluate_candidates,
    validate_evaluation,
)

NAME = "TESTONLY-Alpha"


@pytest.mark.parametrize(
    "text",
    [
        "TESTONLY-Alpha was characterized; TESTONLY-Beta was stable in humid air.",
        "TESTONLY-Alpha was characterized, whereas TESTONLY-Beta was stable "
        "under oxidative conditions.",
        "TESTONLY-Alpha was characterized WHILE TESTONLY-Beta was stable "
        "under moist conditions.",
        "TESTONLY-Alpha was characterized and TESTONLY-Beta was unstable "
        "under humid conditions.",
        "TESTONLY-Beta was unstable under oxidative conditions and "
        "TESTONLY-Alpha was characterized.",
        "TESTONLY-Alpha was characterized, but TESTONLY-Beta has limited "
        "stability under moist conditions.",
        "TESTONLY-Alpha was stable. TESTONLY-Beta was examined in humid air.",
        "TESTONLY-Alpha was examined in humid air. The apparatus was stable.",
        "TESTONLY-Alpha was stable; its apparatus operated in humid air.",
        "TESTONLY-Alpha underwent oxidative synthesis without a stability study.",
        "TESTONLY-Alpha was stable when synthesized in humid air.",
        "During oxidative synthesis, TESTONLY-Alpha was stable.",
        "TESTONLY-Alpha is thermodynamically stable under humid conditions.",
        "TESTONLY-Alpha has thermodynamic stability under moist conditions.",
        "TESTONLY-Alpha has stability according to convex hull calculations "
        "under moist conditions.",
        "TESTONLY-Alpha has a stable color without an environmental test.",
        "TESTONLY-Alpha was measured under oxidative conditions.",
    ],
)
def test_new_environment_context_does_not_transfer_from_other_subject_or_purpose(text):
    assert not _criterion_relevant(text, NAME, "operational_stability", "concern")


@pytest.mark.parametrize(
    "spelling", ["TESTONLY-Alpha-x", "TESTONLY-Alpha/TESTONLY-Beta", "α-TESTONLY-Alpha"]
)
def test_new_operating_context_preserves_exact_qualified_identity(spelling):
    text = f"{spelling} exhibited limited stability under humid conditions."
    assert not _criterion_relevant(text, NAME, "operational_stability", "concern")
    assert _criterion_relevant(text, spelling, "operational_stability", "concern")


@pytest.mark.parametrize(
    "text",
    [
        "TESTONLY-Alpha remained stable after exposure to humid air.",
        "TESTONLY-Alpha showed instability under oxidative conditions.",
        "TESTONLY-Alpha displayed limited stability under moist conditions.",
        "The study discusses processing TESTONLY-Alpha and limited stability "
        "of this candidate under humid and oxidative conditions.",
        "TESTONLY-Alpha was synthesized by the stated method. "
        "TESTONLY-Alpha was stable under humid operating conditions.",
        "TESTONLY-Alpha has thermodynamic stability in an equilibrium model. "
        "TESTONLY-Alpha exhibits instability under oxidative conditions.",
    ],
)
def test_bound_environment_context_remains_reviewable_without_new_judgment(text):
    assert _criterion_relevant(text, NAME, "operational_stability", "unknown")
    assert _criterion_relevant(text, NAME, "operational_stability", "concern")
    assert not _criterion_relevant(text, NAME, "ambient_phase_stability", "supports")


def evidence(text):
    refs = [reference(text=text)]
    docs = discovery_documents(refs)
    profile = {"importance": {"operational_stability": 1}}
    leads = validate_candidate_leads(
        [{"name": NAME, "document_id": docs[0]["document_id"], "quote": text}],
        docs,
        refs,
        profile["importance"],
    )
    assert len(leads) == 1
    row = {
        "lead_id": leads[0]["id"],
        "criterion_id": "operational_stability",
        "document_id": docs[0]["document_id"],
        "quote": text,
        "judgment": "concern",
        "interpretation": "The source reports a limitation in this setting.",
    }
    return refs, leads, profile, row


def test_new_relevance_neither_fabricates_adverse_assessment_nor_mutates_sources():
    text = "TESTONLY-Alpha displays limited stability under humid conditions."
    refs, leads, profile, row = evidence(text)
    before = deepcopy((refs, leads, profile, row))
    unknown = evaluate_candidates(
        {"evaluations": []},
        leads,
        refs,
        profile,
        admission_checks=True,
    )["evaluation"]
    assert unknown["ranked_candidates"][0]["coverage"] == 0
    result = evaluate_candidates(
        {"evaluations": [row]},
        leads,
        refs,
        profile,
        admission_checks=True,
    )
    assert result["feedback"][0]["status"] == "accepted"
    assert result["accepted_proposals"] == [row]
    assert validate_evaluation(result["evaluation"], leads, refs, profile) == (
        result["evaluation"]
    )
    assert (refs, leads, profile, row) == before
    assert all(source["is_material_evidence"] is False for source in refs)


def test_environment_words_do_not_override_exact_source_binding():
    text = "TESTONLY-Alpha exhibits limited stability under humid conditions."
    refs, leads, profile, row = evidence(text)
    forged = {**row, "quote": text.replace("limited stability", "high stability")}
    result = evaluate_candidates(
        {"evaluations": [forged]},
        leads,
        refs,
        profile,
        admission_checks=True,
    )
    assert result["feedback"][0]["reason"] == "quote_or_candidate_not_bound"
    assert not result["accepted_proposals"]
