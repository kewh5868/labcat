"""Synthetic source passages exercise class-independent review priority
only."""

import json
from copy import deepcopy
from pathlib import Path
from random import Random

import pytest
from test_candidate_leads import reference

from labcat.ranking_profiles import ATTRIBUTE_IDS
from labcat.science.candidate_leads import (
    discovery_documents,
    validate_candidate_leads,
)
from labcat.science.literature_evaluation import (
    GENERAL_CRITERIA,
    evaluate_candidates,
    evaluation_context,
    evaluation_schema,
    validate_evaluation,
)


def data_for(entries, *, importance=None):
    refs = [
        reference(index + 1, text=quote, title=f"TEST ONLY work {index + 1}")
        for index, (_, quote) in enumerate(entries)
    ]
    data = {
        "entries": entries,
        "references": refs,
        "profile": {"importance": importance or {"density": 1}},
    }
    rebind(data)
    return data


def rebind(data):
    docs = discovery_documents(data["references"])
    by_record = {(doc["source_id"], doc["record_id"]): doc for doc in docs}
    data["documents"] = [
        by_record[(ref["source_id"], ref["record_id"])] for ref in data["references"]
    ]
    data["leads"] = validate_candidate_leads(
        [
            {"document_id": doc["document_id"], "name": name, "quote": quote}
            for (name, quote), doc in zip(
                data["entries"], data["documents"], strict=True
            )
        ],
        docs,
        data["references"],
        data["profile"]["importance"],
    )


def propose(data, index, criterion="application_fit", judgment="supports"):
    name, quote = data["entries"][index]
    lead = next(item for item in data["leads"] if item["name"] == name)
    return {
        "lead_id": lead["id"],
        "criterion_id": criterion,
        "document_id": data["documents"][index]["document_id"],
        "quote": quote,
        "judgment": judgment,
        "interpretation": "The passage addresses this candidate "
        "under its stated conditions.",
    }


def run(data, proposals=()):
    result = evaluate_candidates(
        {"evaluations": list(proposals)},
        data["leads"],
        data["references"],
        data["profile"],
    )
    assert (
        validate_evaluation(
            result["evaluation"], data["leads"], data["references"], data["profile"]
        )
        == result["evaluation"]
    )
    return result


def test_general_criteria_are_available_without_changing_attribute_weights():
    context = evaluation_context({"importance": {"band_gap": 0.8, "density": 0.2}})
    by_id = {item["criterion_id"]: item for item in context}
    assert set(GENERAL_CRITERIA).isdisjoint(ATTRIBUTE_IDS)
    for key in GENERAL_CRITERIA:
        assert by_id[key]["weight"] == by_id[key]["importance"] == 0
    assert by_id["application_fit"]["goal"]["relation"] == "consider"
    assert by_id["demonstrated_use"]["goal"]["relation"] == "maximize"
    assert by_id["band_gap"]["weight"] == 0.8
    assert by_id["density"]["weight"] == 0.2
    enum = evaluation_schema()["properties"]["evaluations"]["items"]["properties"][
        "criterion_id"
    ]["enum"]
    assert set(GENERAL_CRITERIA) <= set(enum)


@pytest.mark.parametrize(
    "name",
    [
        "TESTONLY-Perovskite",
        "TESTONLY-Alloy",
        "TESTONLY-OrganicBlend",
        "TESTONLY-QuantumDot",
        "TESTONLY-Ceramic",
        "TESTONLY-Polymer",
        "TESTONLY-Catalyst",
        "TESTONLY-Membrane",
        "TESTONLY-BatterySalt",
    ],
)
def test_every_retained_class_neutral_lead_gets_explicit_unknown_review_prior(name):
    data = data_for([(name, f"{name} is mentioned without attribute information.")])
    bundle = run(data)["evaluation"]
    assert bundle["version"] == "literature-fit-v2"
    assert bundle["unranked_candidates"] == []
    assert bundle["proposals"] == []
    (row,) = bundle["ranked_candidates"]
    assert row["rank"] == 1
    assert row["preliminary_score"] == row["priority_score"] == 0.225
    assert row["observed_fit"] is None and row["coverage"] == 0
    assert row["fit_lower_bound"] == 0 and row["fit_upper_bound"] == 1
    assert row["ranking_basis"] == "preliminary" and row["priority_tier"] == 0
    assert row["general_evidence"]["application_fit"] == "unknown"
    assert row["general_evidence"]["demonstrated_use"] == "unknown"
    assert row["general_evidence"]["corroborating_work_count"] == 0
    assert len(row["stability_unknown"]) == 3
    assert all(not criterion["assessments"] for criterion in row["criteria"])
    assert not bundle["properties_verified"] and not bundle["is_material_evidence"]


def test_general_public_context_produces_priority_without_attribute_coverage():
    data = data_for(
        [
            (
                "TESTONLY-Alpha",
                "TESTONLY-Alpha was tested and used for the requested application.",
            ),
            (
                "TESTONLY-Beta",
                "TESTONLY-Beta is proposed for this application in a review.",
            ),
            (
                "TESTONLY-Gamma",
                "TESTONLY-Gamma is mentioned without useful properties.",
            ),
        ]
    )
    bundle = run(
        data,
        [
            propose(data, 0),
            propose(data, 0, "demonstrated_use"),
            propose(data, 1),
            propose(data, 1, "demonstrated_use", "mixed"),
        ],
    )["evaluation"]
    alpha, beta, gamma = bundle["ranked_candidates"]
    assert alpha["name"] == "TESTONLY-Alpha"
    assert alpha["priority_score"] == pytest.approx(0.7 + 0.2 + 0.1 / 3)
    assert beta["priority_score"] == pytest.approx(0.7 + 0.1 + 0.1 / 3)
    assert gamma["priority_score"] == 0.225
    assert all(
        row["observed_fit"] is None and row["coverage"] == 0
        for row in (alpha, beta, gamma)
    )
    assert [row["rank"] for row in (alpha, beta, gamma)] == [1, 2, 3]


@pytest.mark.parametrize(
    "description",
    [
        "is proposed in a review",
        "was simulated to demonstrate an application",
        "could be used in an application",
        "is mentioned without context",
    ],
)
def test_demonstration_support_needs_local_applied_language(description):
    name = "TESTONLY-Alpha"
    data = data_for([(name, f"{name} {description}.")])
    result = run(data, [propose(data, 0, "demonstrated_use")])
    assert result["feedback"][0]["reason"] == "criterion_context_missing"
    assert result["evaluation"]["ranked_candidates"][0]["priority_score"] == 0.225
    result = run(data, [propose(data, 0, "demonstrated_use", "mixed")])
    assert result["feedback"][0]["status"] == "accepted"


def test_later_candidate_sentence_can_bind_a_demonstration_without_cross_attribution():
    name = "TESTONLY-Alpha"
    for quote, expected in [
        (
            f"{name} is introduced first. {name} was tested in the application.",
            "accepted",
        ),
        (f"{name} is introduced first. Another material was tested.", "rejected"),
    ]:
        data = data_for([(name, quote)])
        result = run(data, [propose(data, 0, "demonstrated_use")])
        assert result["feedback"][0]["status"] == expected


def test_sparse_attributes_refine_baseline_and_complete_attributes_can_reverse_it():
    data = data_for(
        [
            (
                "TESTONLY-Alpha",
                "TESTONLY-Alpha is used in the application but has density "
                "and solution processing limitations.",
            ),
            (
                "TESTONLY-Beta",
                "TESTONLY-Beta has favorable density and solution processing "
                "in the stated sample.",
            ),
        ],
        importance={"density": 0.2, "solution_processability": 0.8},
    )
    general = [propose(data, 0), propose(data, 0, "demonstrated_use")]
    before = run(data, general)["evaluation"]["ranked_candidates"]
    sparse = run(
        data,
        general
        + [
            propose(data, 0, "density", "concern"),
            propose(data, 1, "density"),
        ],
    )["evaluation"]["ranked_candidates"]
    full = run(
        data,
        general
        + [
            propose(data, 0, "density", "concern"),
            propose(data, 1, "density"),
            propose(data, 0, "solution_processability", "concern"),
            propose(data, 1, "solution_processability"),
        ],
    )["evaluation"]["ranked_candidates"]
    assert before[0]["name"] == sparse[0]["name"] == "TESTONLY-Alpha"
    assert full[0]["name"] == "TESTONLY-Beta"
    assert full[0]["priority_score"] == 1 and full[1]["priority_score"] == 0
    for row in sparse:
        assert row["coverage"] == 0.2 and row["ranking_basis"] == "blended"
        assert row["priority_score"] == pytest.approx(
            0.8 * row["preliminary_score"] + 0.2 * row["observed_fit"]
        )
    assert all(row["ranking_basis"] == "attribute" for row in full)


def test_distinct_cited_works_deduplicate_doi_and_title_and_cap_the_bonus():
    name = "TESTONLY-Alpha"
    quote = f"{name} is discussed for the requested application."
    data = data_for([(name, quote)] * 7)
    data["references"][0]["metadata"]["doi"] = "https://doi.org/10.1234/TEST"
    data["references"][1]["metadata"]["doi"] = " DOI:10.1234/test "
    data["references"][2]["title"] = "TEST ONLY: one shared work"
    data["references"][3]["title"] = "Test Only one shared work"
    rebind(data)
    proposals = [propose(data, index) for index in range(7)]
    (row,) = run(data, proposals)["evaluation"]["ranked_candidates"]
    assert row["general_evidence"]["corroborating_work_count"] == 5
    assert row["general_evidence"]["corroboration"] == 1
    assert row["priority_score"] == 0.85
    # Repeated assessments, reversed references and arrival order have no effect.
    expected = run(data, proposals)["evaluation"]
    Random(371).shuffle(proposals)
    shuffled = deepcopy(data)
    shuffled["references"].reverse()
    shuffled["leads"].reverse()
    assert run(shuffled, proposals + proposals[:2])["evaluation"] == expected


def test_wikipedia_background_does_not_count_as_corroboration():
    name = "TESTONLY-Alpha"
    quote = f"{name} is discussed for an application."
    data = data_for([(name, quote)])
    data["references"] = [reference(provider="wikipedia", text=quote)]
    rebind(data)
    (row,) = run(data, [propose(data, 0)])["evaluation"]["ranked_candidates"]
    assert row["general_evidence"]["corroborating_work_count"] == 0
    assert row["priority_score"] == 0.75


def test_cross_index_missing_doi_and_transitive_title_aliases_cannot_multiply_works():
    name = "TESTONLY-Alpha"
    quote = f"{name} is discussed for the requested application."
    data = data_for([(name, quote)] * 6)
    # A DOI-bearing record, a title-only copy, a differently titled DOI copy,
    # and a second title-only copy are one connected cited work.
    for index, title, doi in [
        (0, "TEST ONLY shared first title", "10.1234/first"),
        (1, "TEST ONLY shared first title", None),
        (2, "TEST ONLY shared second title", "https://doi.org/10.1234/FIRST"),
        (3, "TEST ONLY shared second title", None),
        (4, "TEST ONLY different work", "10.1234/second"),
        # A third DOI sharing the second title is conservatively the same
        # group; metadata disagreement cannot create a corroboration bonus.
        (5, "TEST ONLY shared second title", "10.1234/third"),
    ]:
        data["references"][index]["title"] = title
        if doi:
            data["references"][index]["metadata"]["doi"] = doi
    rebind(data)
    proposals = [propose(data, index) for index in range(6)]
    expected = run(data, proposals)["evaluation"]
    (row,) = expected["ranked_candidates"]
    assert row["general_evidence"]["corroborating_work_count"] == 2
    assert row["priority_score"] == pytest.approx(0.75 + 0.1 * 2 / 3)
    for seed in range(6):
        Random(seed).shuffle(proposals)
        shuffled = deepcopy(data)
        Random(seed + 10).shuffle(shuffled["references"])
        assert run(shuffled, proposals)["evaluation"] == expected


@pytest.mark.parametrize(
    "criterion,context",
    [
        ("application_fit", "application fit"),
        ("stability", "thermodynamic stability"),
        ("ambient_phase_stability", "room temperature phase stability"),
        ("operational_stability", "operational stability"),
    ],
)
def test_each_adverse_application_or_stability_assessment_takes_priority_over_score(
    criterion, context
):
    data = data_for(
        [
            (
                "TESTONLY-Alpha",
                "TESTONLY-Alpha was tested with favorable density "
                f"but has {context} concerns.",
            ),
            (
                "TESTONLY-Beta",
                f"TESTONLY-Beta has mixed {context} under the stated conditions.",
            ),
            (
                "TESTONLY-Gamma",
                "TESTONLY-Gamma is discussed without relevant attributes.",
            ),
        ]
    )
    bundle = run(
        data,
        [
            propose(data, 0, "density"),
            propose(data, 0, criterion, "concern"),
            propose(data, 0, criterion, "supports"),
            propose(data, 1, criterion, "mixed"),
        ],
    )["evaluation"]
    gamma, beta, alpha = bundle["ranked_candidates"]
    assert [row["priority_tier"] for row in (gamma, beta, alpha)] == [0, 1, 2]
    assert alpha["priority_score"] == 1 > gamma["priority_score"]
    assert alpha["name"] == "TESTONLY-Alpha"
    item = next(row for row in alpha["criteria"] if row["criterion_id"] == criterion)
    assert item["judgment"] == "mixed" and len(item["assessments"]) == 2


def test_equal_priorities_share_ranks_and_source_order_cannot_break_ties():
    data = data_for(
        [
            (name, f"{name} is mentioned for further study.")
            for name in ("TESTONLY-Gamma", "TESTONLY-Alpha", "TESTONLY-Beta")
        ]
    )
    expected = run(data)["evaluation"]
    assert [row["name"] for row in expected["ranked_candidates"]] == [
        "TESTONLY-Alpha",
        "TESTONLY-Beta",
        "TESTONLY-Gamma",
    ]
    assert [row["rank"] for row in expected["ranked_candidates"]] == [1, 1, 1]
    data["leads"].reverse()
    data["references"].reverse()
    assert run(data)["evaluation"] == expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("preliminary_score", 0.99),
        ("priority_score", 0.99),
        ("priority_tier", 2),
        ("ranking_basis", "attribute"),
        ("rank", 2),
        ("coverage", 1),
        ("observed_fit", 1),
        ("general_evidence", {"application_fit": "supports"}),
    ],
)
def test_saved_priority_cannot_be_forged(field, value):
    data = data_for([("TESTONLY-Alpha", "TESTONLY-Alpha is mentioned in this source.")])
    bundle = run(data)["evaluation"]
    bundle["ranked_candidates"][0][field] = value
    with pytest.raises(ValueError, match="does not match"):
        validate_evaluation(bundle, data["leads"], data["references"], data["profile"])


def test_generic_assessment_still_requires_exact_name_and_public_quote_bindings():
    data = data_for(
        [
            ("TESTONLY-Alpha", "TESTONLY-Alpha was used for this application."),
            ("TESTONLY-Beta", "TESTONLY-Beta was used for another application."),
        ]
    )
    original = propose(data, 0)
    result = run(
        data,
        [
            {
                **original,
                "quote": "TESTONLY-Alpha is excellent according to invented evidence.",
            },
            {**original, "document_id": data["documents"][1]["document_id"]},
            {**original, "lead_id": "lead-" + "f" * 24},
        ],
    )
    assert all(item["status"] == "rejected" for item in result["feedback"])
    assert all(
        row["priority_score"] == 0.225
        for row in result["evaluation"]["ranked_candidates"]
    )
    assert not result["accepted_proposals"]


def test_historical_v1_fixture_replays_without_score_rank_or_caution_changes():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/literature_fit_v1.json").read_text()
    )
    data, saved = fixture["inputs"], fixture["evaluation"]
    assert (
        validate_evaluation(saved, data["leads"], data["references"], data["profile"])
        == saved
    )
    replay = evaluate_candidates(
        {"evaluations": saved["proposals"]},
        data["leads"],
        data["references"],
        data["profile"],
        version="literature-fit-v1",
    )["evaluation"]
    assert replay == saved
    assert replay["unranked_candidates"] and len(replay["ranked_candidates"]) == 2
    assert "priority_score" not in replay["ranked_candidates"][0]
    changed = deepcopy(saved)
    changed["version"] = "literature-fit-v2"
    with pytest.raises(ValueError, match="does not match"):
        validate_evaluation(changed, data["leads"], data["references"], data["profile"])


def test_unknown_saved_version_is_rejected():
    data = data_for([("TESTONLY-Alpha", "TESTONLY-Alpha is mentioned in this source.")])
    bundle = run(data)["evaluation"]
    bundle["version"] = "literature-fit-v99"
    with pytest.raises(ValueError, match="version"):
        validate_evaluation(bundle, data["leads"], data["references"], data["profile"])
