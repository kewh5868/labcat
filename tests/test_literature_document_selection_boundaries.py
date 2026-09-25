"""Synthetic document-selection boundaries; no scientific material
assertions."""

from copy import deepcopy

import pytest
from test_candidate_leads import reference

from labcat.science.candidate_leads import (
    discovery_documents,
    validate_candidate_leads,
)
from labcat.science.literature_evaluation import (
    _bindings,
    evaluate_candidates,
    validate_evaluation,
)

MENTION = "TESTONLY-Alpha is discussed as an insulating film in this study."
PROPERTY = "TESTONLY-Alpha has a measured low density in this solid sample."


@pytest.fixture
def selected():
    refs = [reference(1, text=MENTION)] + [
        reference(index, text="TESTONLY separate source background discussion.")
        for index in range(2, 30)
    ]
    refs.append(reference(30, text=PROPERTY))
    anchor = discovery_documents([refs[0]])[0]
    target = discovery_documents([refs[-1]])[0]
    documents = discovery_documents(
        refs,
        preferred_document_ids=[anchor["document_id"], target["document_id"]],
    )
    profile = {"importance": {"density": 1}}
    leads = validate_candidate_leads(
        [
            {
                "document_id": anchor["document_id"],
                "name": "TESTONLY-Alpha",
                "quote": MENTION,
            }
        ],
        documents,
        refs,
        profile["importance"],
    )
    assert len(leads) == 1 and len(documents) == 24
    return refs, documents, leads, profile, anchor, target


def row(selected, document=None):
    _, _, leads, _, _, target = selected
    return {
        "lead_id": leads[0]["id"],
        "criterion_id": "density",
        "document_id": (document or target)["document_id"],
        "quote": PROPERTY,
        "judgment": "supports",
        "interpretation": "The synthetic passage describes density in its sample.",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", "TESTONLY forged body text."),
        ("title", "TESTONLY forged title"),
        ("source_id", "arxiv"),
        ("record_id", "W9999999"),
        ("url", "https://example.invalid/unapproved"),
        ("response_sha256", "0" * 64),
        ("document_id", "doc-" + "f" * 24),
    ],
)
def test_selected_source_id_does_not_authorize_changed_snapshot(selected, field, value):
    refs, documents, leads, _, _, _ = selected
    changed = deepcopy(documents)
    changed[1][field] = value
    with pytest.raises(ValueError):
        _bindings(leads, refs, [], changed)


def test_missing_document_field_cannot_be_filled_from_source(selected):
    refs, documents, leads, _, _, _ = selected
    changed = deepcopy(documents)
    del changed[1]["text"]
    with pytest.raises(ValueError):
        _bindings(leads, refs, [], changed)


@pytest.mark.parametrize(
    "identity", [None, [], {}, 2, True, "bad-id", "doc-" + "0" * 23]
)
def test_malformed_selected_id_gives_validation_error(selected, identity):
    refs, documents, leads, _, _, _ = selected
    changed = deepcopy(documents)
    changed[1]["document_id"] = identity
    with pytest.raises(ValueError):
        _bindings(leads, refs, [], changed)


@pytest.mark.parametrize("document", [None, [], "TESTONLY not a document"])
def test_malformed_document_is_not_an_evidence_selector(selected, document):
    refs, documents, leads, _, _, _ = selected
    changed = deepcopy(documents)
    changed[1] = document
    with pytest.raises(ValueError):
        _bindings(leads, refs, [], changed)


@pytest.mark.parametrize("container", [tuple, lambda docs: {"documents": docs}])
def test_explicit_documents_require_list(selected, container):
    refs, documents, leads, _, _, _ = selected
    with pytest.raises(ValueError):
        _bindings(leads, refs, [], container(documents))


def test_duplicate_ids_reject_even_when_identical_and_within_cap(selected):
    refs, _, leads, _, anchor, target = selected
    with pytest.raises(ValueError):
        _bindings(leads, refs, [], [anchor, target, deepcopy(target)])


def test_repeated_documents_cannot_extend_document_cap(selected):
    refs, documents, leads, _, _, _ = selected
    with pytest.raises(ValueError):
        _bindings(leads, refs, [], [*documents, documents[0]])


def test_proposal_and_supplied_document_union_cannot_exceed_cap(selected):
    refs, documents, leads, profile, _, _ = selected
    omitted = discovery_documents([refs[24]])[0]
    assert omitted["document_id"] not in {d["document_id"] for d in documents}
    with pytest.raises(ValueError, match="document limit"):
        evaluate_candidates(
            {"evaluations": [row(selected, omitted)]},
            leads,
            refs,
            profile,
            documents=documents,
        )


def test_absent_proposal_document_stays_unavailable_and_valid_sibling_survives(
    selected,
):
    refs, _, leads, profile, anchor, target = selected
    unknown = {**row(selected), "document_id": "doc-" + "f" * 24}
    output = evaluate_candidates(
        {"evaluations": [unknown, row(selected)]},
        leads,
        refs,
        profile,
        documents=[anchor, target],
    )
    assert output["feedback"][0] == {
        "index": 0,
        "status": "rejected",
        "reason": "unavailable_document",
    }
    assert output["accepted_proposals"] == [row(selected)]


def test_retained_but_unsupplied_proposal_document_is_not_added(selected):
    refs, _, leads, profile, anchor, _ = selected
    output = evaluate_candidates(
        {"evaluations": [row(selected)]},
        leads,
        refs,
        profile,
        documents=[anchor],
    )
    assert output["accepted_proposals"] == []
    assert output["feedback"][0]["reason"] == "unavailable_document"


def test_mandatory_lead_anchor_must_exist_in_explicit_documents(selected):
    refs, _, leads, _, _, target = selected
    with pytest.raises(ValueError, match="candidate does not match"):
        _bindings(leads, refs, [], [target])


@pytest.mark.parametrize(
    "field,value", [("name", "TESTONLY-Changed"), ("quote", "TESTONLY forged quote.")]
)
def test_document_selection_cannot_repair_altered_candidate(selected, field, value):
    refs, documents, leads, _, _, _ = selected
    changed = deepcopy(leads)
    if field == "quote":
        changed[0]["citations"][0][field] = value
    else:
        changed[0][field] = value
    with pytest.raises(ValueError):
        _bindings(changed, refs, [], documents)


def test_valid_source_beyond_reference_cutoff_cannot_be_preferred(selected):
    refs, _, _, _, anchor, _ = selected
    with pytest.raises(ValueError):
        _bindings([], [{}] * 80 + [refs[0]], [], [anchor])


def test_last_source_within_reference_cutoff_remains_available(selected):
    refs, _, _, _, anchor, _ = selected
    _, documents, _ = _bindings([], [{}] * 79 + [refs[0]], [], [anchor])
    assert documents == {anchor["document_id"]: anchor}


@pytest.mark.parametrize(
    "field,value",
    [
        ("access_scope", "private"),
        ("provenance_status", "unverified"),
        ("is_material_evidence", True),
        ("kind", "untrusted_excerpt"),
    ],
)
def test_selected_id_cannot_authorize_invalid_reference_envelope(
    selected, field, value
):
    refs, _, _, _, anchor, _ = selected
    changed = deepcopy(refs[0])
    changed[field] = value
    with pytest.raises(ValueError):
        _bindings([], [changed], [], [anchor])


@pytest.mark.parametrize("conflict", ["title", "hash"])
def test_preferred_id_cannot_choose_between_conflicting_source_snapshots(
    selected, conflict
):
    refs, _, _, _, anchor, _ = selected
    changed = deepcopy(refs[0])
    if conflict == "title":
        changed["title"] = "TESTONLY different title"
    else:
        changed["provenance"]["response_sha256"] = "b" * 64
    with pytest.raises(ValueError):
        _bindings([], [refs[0], changed], [], [anchor])


def test_identical_reference_duplicates_do_not_create_ambiguity(selected):
    refs, _, _, _, anchor, _ = selected
    _, documents, _ = _bindings([], [refs[0], deepcopy(refs[0])], [], [anchor])
    assert documents == {anchor["document_id"]: anchor}


@pytest.mark.parametrize("version", ["literature-fit-v1", "literature-fit-v2"])
def test_none_selection_and_canonical_replay_keep_exact_bundle(selected, version):
    refs, documents, leads, profile, anchor, target = selected
    before = deepcopy(selected)
    preferred = [anchor["document_id"], target["document_id"]]
    _, default, _ = _bindings(leads, refs, [row(selected)], None)
    assert list(default.values()) == discovery_documents(
        refs, preferred_document_ids=preferred
    )
    explicit = evaluate_candidates(
        {"evaluations": [row(selected)]},
        leads,
        refs,
        profile,
        documents=documents,
        version=version,
    )
    historical = evaluate_candidates(
        {"evaluations": [row(selected)]}, leads, refs, profile, version=version
    )
    assert explicit == historical
    assert (
        validate_evaluation(explicit["evaluation"], leads, refs, profile)
        == explicit["evaluation"]
    )
    assert selected == before
