"""Synthetic evidence contexts; these tests do not assert model
understanding."""

from copy import deepcopy

import pytest
from test_candidate_leads import reference

from labcat.science.candidate_leads import (
    discovery_documents,
    validate_candidate_leads,
)
from labcat.science.literature_evaluation import (
    evaluate_candidate_batches,
    evaluate_candidates,
    validate_evaluation,
)


def case(text, *, title="TEST ONLY source", quote=None, criterion="band_gap"):
    refs = [reference(text=text, title=title)]
    docs = discovery_documents(refs)
    quoted = quote or text or title
    profile = {"importance": {"band_gap": 1}}
    leads = validate_candidate_leads(
        [
            {
                "document_id": docs[0]["document_id"],
                "name": "TESTONLY-Alpha",
                "quote": quoted,
            }
        ],
        docs,
        refs,
        profile["importance"],
    )
    assert len(leads) == 1
    row = {
        "lead_id": leads[0]["id"],
        "criterion_id": criterion,
        "document_id": docs[0]["document_id"],
        "quote": quoted,
        "judgment": "supports",
        "interpretation": "The source describes the criterion for this sample.",
    }
    return refs, leads, profile, row


def assess(data, *, admission=True, judgment="supports"):
    refs, leads, profile, row = data
    result = evaluate_candidates(
        {"evaluations": [{**row, "judgment": judgment}]},
        leads,
        refs,
        profile,
        admission_checks=admission,
    )
    assert (
        validate_evaluation(result["evaluation"], leads, refs, profile)
        == result["evaluation"]
    )
    return result


@pytest.mark.parametrize(
    "body", [None, "TESTONLY-Alpha has a band gap used as a simulation parameter."]
)
def test_title_only_property_claim_keeps_lead_but_does_not_supply_attribute_fit(body):
    title = "TESTONLY-Alpha with a band gap of 1.8 eV"
    data = case(body, title=title, quote=title)
    result = assess(data)
    assert result["feedback"][0]["reason"] == "attribute_requires_source_context"
    assert len(result["evaluation"]["ranked_candidates"]) == 1
    assert result["evaluation"]["ranked_candidates"][0]["coverage"] == 0
    assert assess(data, judgment="unknown")["feedback"][0]["status"] == "accepted"


@pytest.mark.parametrize("judgment", ["supports", "mixed", "concern"])
@pytest.mark.parametrize(
    "qualifier",
    [
        "was assumed in the device model",
        "was a model input",
        "was a simulation parameter",
    ],
)
def test_trimming_input_qualifier_does_not_make_an_observation(qualifier, judgment):
    quote = "TESTONLY-Alpha has a band gap of 1.8 eV"
    data = case(f"{quote}, which {qualifier}.", quote=quote)
    result = assess(data, judgment=judgment)
    assert result["feedback"][0]["reason"] == "model_input_not_observation"
    assert result["accepted_proposals"] == []


@pytest.mark.parametrize(
    "text",
    [
        "TESTONLY-Alpha has a measured optical band gap of 1.8 eV in this sample.",
        "TESTONLY-Alpha has a calculated band gap of 1.8 eV "
        "using the stated approximation.",
        "TESTONLY-Alpha has a measured band gap of 1.8 eV "
        "with the heater set to the stated temperature.",
        "TESTONLY-Alpha has a measured band gap of 1.8 eV. "
        "Another compound uses an assumed input parameter.",
    ],
)
def test_observed_or_calculated_claim_not_rejected_as_model_input(text):
    quote = text.split(". Another")[0]
    assert assess(case(text, quote=quote))["feedback"][0]["status"] == "accepted"


@pytest.mark.parametrize("judgment", ["supports", "mixed"])
@pytest.mark.parametrize(
    "text",
    [
        "TESTONLY-Alpha is a promising possibility for the requested role.",
        "TESTONLY-Alpha was simulated to demonstrate device performance.",
        "TESTONLY-Alpha is proposed for the application in a review.",
        "An experimental device using TESTONLY-Alpha is proposed for later testing.",
    ],
)
def test_prospective_use_does_not_earn_demonstration_credit(text, judgment):
    result = assess(case(text, criterion="demonstrated_use"), judgment=judgment)
    assert result["feedback"][0]["status"] == "rejected"
    assert (
        result["evaluation"]["ranked_candidates"][0]["general_evidence"][
            "demonstrated_use"
        ]
        == "unknown"
    )


def test_reported_role_and_actual_use_do_not_require_missing_durability():
    text = (
        "TESTONLY-Alpha was fabricated and tested as the requested component; "
        "its service lifetime was not reported."
    )
    data = case(text, criterion="application_fit")
    assert assess(data)["feedback"][0]["status"] == "accepted"
    demonstration = assess(case(text, criterion="demonstrated_use"))
    assert demonstration["feedback"][0]["status"] == "accepted"
    row = assess(data)["evaluation"]["ranked_candidates"][0]
    assert len(row["stability_unknown"]) == 3
    assert row["coverage"] == 0


def test_computed_comparison_does_not_erase_explicit_actual_demonstration():
    text = (
        "TESTONLY-Alpha was fabricated and tested in a device, "
        "with simulated results retained for comparison."
    )
    assert (
        assess(case(text, criterion="demonstrated_use"))["feedback"][0]["status"]
        == "accepted"
    )


@pytest.mark.parametrize(
    "text",
    [
        "TESTONLY-Alpha was not fabricated or tested as a device.",
        "An experiment using TESTONLY-Alpha has yet to be performed.",
        "TESTONLY-Alpha was never deployed as a device.",
    ],
)
@pytest.mark.parametrize("judgment", ["supports", "mixed"])
def test_negated_or_unperformed_use_cannot_supply_positive_demonstration(
    text, judgment
):
    result = assess(case(text, criterion="demonstrated_use"), judgment=judgment)
    assert result["feedback"][0]["status"] == "rejected"
    assert result["accepted_proposals"] == []


def test_trimming_simulation_qualifier_does_not_make_demonstration():
    quote = "TESTONLY-Alpha was used in a device."
    data = case(
        "In the simulation, " + quote, quote=quote, criterion="demonstrated_use"
    )
    assert assess(data)["feedback"][0]["reason"] == "demonstration_not_established"


def test_semicolon_simulated_use_qualifier_cannot_be_trimmed():
    quote = "TESTONLY-Alpha was used in a device"
    data = case(
        quote + "; this use was only simulated.",
        quote=quote,
        criterion="demonstrated_use",
    )
    assert assess(data)["feedback"][0]["reason"] == "demonstration_not_established"


def test_testing_only_in_simulation_is_not_actual_demonstration():
    text = "TESTONLY-Alpha was tested only in a simulation."
    assert (
        assess(case(text, criterion="demonstrated_use"))["feedback"][0]["reason"]
        == "demonstration_not_established"
    )


@pytest.mark.parametrize(
    "text",
    [
        "We experimentally demonstrate TESTONLY-Alpha in a device "
        "and compare simulated predictions.",
        "TESTONLY-Alpha has been demonstrated experimentally, "
        "with simulated predictions for comparison.",
        "Measurements showed TESTONLY-Alpha operating in a device, "
        "unlike simulated predictions.",
    ],
)
def test_explicit_actual_use_survives_simulation_comparison(text):
    assert (
        assess(case(text, criterion="demonstrated_use"))["feedback"][0]["status"]
        == "accepted"
    )


def test_mixed_use_retains_actual_conditional_evidence():
    text = (
        "TESTONLY-Alpha was fabricated and tested as the requested component, "
        "but device operation failed in humid conditions."
    )
    result = assess(case(text, criterion="demonstrated_use"), judgment="mixed")
    assert result["feedback"][0]["status"] == "accepted"
    assert (
        result["evaluation"]["ranked_candidates"][0]["general_evidence"][
            "demonstrated_use"
        ]
        == "mixed"
    )


@pytest.mark.parametrize(
    "text",
    [
        "TESTONLY-Alpha has a measured band gap of 1.8 eV, not an assumed model input.",
        "TESTONLY-Alpha has a measured band gap of 1.8 eV, "
        "whereas another material uses an assumed band gap.",
        "The measured band gap of TESTONLY-Alpha was used as a model input.",
        "TESTONLY-Alpha has a calculated band gap using an assumed lattice constant.",
        "TESTONLY-Alpha has a band gap of 1.8 eV; "
        "another material has an assumed band gap.",
    ],
)
def test_property_observation_not_erased_by_other_or_negated_input_context(text):
    assert assess(case(text))["feedback"][0]["status"] == "accepted"


def test_explicit_gap_used_for_simulation_is_an_input_not_observation():
    text = "A band gap of 1.8 eV was used for TESTONLY-Alpha in the simulation."
    assert assess(case(text))["feedback"][0]["reason"] == "model_input_not_observation"


def test_not_measured_but_assumed_property_is_not_an_observation():
    quote = "TESTONLY-Alpha has a band gap of 1.8 eV"
    text = quote + ", which was not measured but assumed."
    assert assess(case(text, quote=quote))["feedback"][0]["reason"] == (
        "model_input_not_observation"
    )


def test_assumed_to_be_property_is_not_an_observation():
    text = "TESTONLY-Alpha has a band gap assumed to be 1.8 eV."
    assert assess(case(text))["feedback"][0]["reason"] == "model_input_not_observation"


def test_semicolon_input_qualifier_cannot_be_trimmed():
    quote = "TESTONLY-Alpha has a band gap of 1.8 eV"
    text = quote + "; this was an assumed input."
    assert assess(case(text, quote=quote))["feedback"][0]["reason"] == (
        "model_input_not_observation"
    )


@pytest.mark.parametrize("input_first", [True, False])
def test_repeated_property_quote_requires_disambiguating_context(input_first):
    quote = "TESTONLY-Alpha has a band gap of 1.8 eV"
    observed = "Measurements show " + quote + " in this sample."
    assumed = "In the simulation, " + quote + ", which was an assumed model input."
    text = " ".join([assumed, observed] if input_first else [observed, assumed])
    result = assess(case(text, quote=quote))
    assert result["feedback"][0]["reason"] == "model_input_not_observation"
    assert assess(case(text, quote=observed))["feedback"][0]["status"] == "accepted"


@pytest.mark.parametrize("input_first", [True, False])
def test_repeated_use_quote_cannot_select_only_the_favorable_occurrence(input_first):
    quote = "TESTONLY-Alpha was used in a device"
    observed = "In the experiment, " + quote + " and its output was measured."
    simulated = "In the simulation, " + quote + " to predict performance."
    text = " ".join([simulated, observed] if input_first else [observed, simulated])
    assert (
        assess(case(text, quote=quote, criterion="demonstrated_use"))["feedback"][0][
            "status"
        ]
        == "rejected"
    )
    assert (
        assess(case(text, quote=observed, criterion="demonstrated_use"))["feedback"][0][
            "status"
        ]
        == "accepted"
    )


def test_new_admission_does_not_rewrite_saved_prior_policy():
    data = case(
        "TESTONLY-Alpha is proposed for the application in a review.",
        criterion="demonstrated_use",
    )
    old = assess(data, admission=False, judgment="mixed")["evaluation"]
    before = deepcopy(old)
    assert assess(data, judgment="mixed")["feedback"][0]["status"] == "rejected"
    refs, leads, profile, _ = data
    assert validate_evaluation(old, leads, refs, profile) == before


def test_rejected_input_can_be_corrected_with_observation_in_second_batch():
    title = "TESTONLY-Alpha with a band gap of 1.8 eV"
    text = "TESTONLY-Alpha has a measured optical band gap in the stated sample."
    refs, leads, profile, row = case(text, title=title, quote=title)
    result = evaluate_candidate_batches(
        [{"evaluations": [row]}, {"evaluations": [{**row, "quote": text}]}],
        leads,
        refs,
        profile,
        admission_checks=True,
    )
    assert [item["status"] for item in result["feedback"]] == ["rejected", "accepted"]
    assert len(result["accepted_proposals"]) == 1
    assert (
        validate_evaluation(result["evaluation"], leads, refs, profile)
        == result["evaluation"]
    )
