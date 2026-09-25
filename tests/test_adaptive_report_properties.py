"""Synthetic display fixtures, not actual materials data or
recommendations."""

from copy import deepcopy

import pytest
from test_candidate_lead_reporting import lead_report
from test_literature_evaluation_reporting import evaluated_report
from test_semantic_goal_scoring import review

from labcat.config import load_config
from labcat.report_exports import (
    _blocks,
    _column_weights,
    _score_fills,
    prepare_presentation,
)
from labcat.science.candidate_leads import discovery_documents, validate_candidate_leads
from labcat.science.literature_evaluation import evaluate_candidates, evaluation_goals
from labcat.science.report_properties import (
    grouped_explicit_property_ids,
    selected_property_ids,
)
from labcat.science.reporting import render_reports


def table(text):
    return next(data for kind, data, _ in _blocks(text) if kind == "table")


def test_bounded_selection_prioritizes_explicit_goals_not_available_values():
    criteria = [
        {"criterion_id": key, "weight": weight}
        for key, weight in {
            "evidence_quality": 1,
            "application_fit": 1,
            "simplicity": 1,
            "band_gap": 0.9,
            "operational_stability": 0.9,
            "ambient_phase_stability": 0.6,
            "density": 0.1,
            "refractive_index": 0,
        }.items()
    ]
    assert selected_property_ids(criteria) == [
        "band_gap",
        "operational_stability",
        "ambient_phase_stability",
    ]
    assert selected_property_ids(
        criteria, explicit_ids=["density", "density", "refractive_index"]
    ) == ["density", "band_gap", "operational_stability"]
    assert (
        selected_property_ids([{"criterion_id": "density", "weight": float("nan")}])
        == []
    )


def property_report():
    report = lead_report()
    profile = {
        "importance": {
            "band_gap": 0.9,
            "operational_stability": 0.8,
            "density": 0.1,
            "ambient_phase_stability": 0.7,
        }
    }
    mentions = []
    for index, source in enumerate(report["sources"]):
        name = "Fixture-" + chr(ord("A") + index)
        # A deliberately synthetic quote verifies that printed units, method,
        # and device context stay verbatim and are never promoted to fields.
        quote = (
            f"TEST ONLY: {name} has a measured optical band gap of 1.72 eV in this "
            "synthetic fixture; its simulated device efficiency is 34%. "
            "No actual material measurement is asserted."
        )
        source["metadata"]["abstract"] = quote
        mentions.append(
            {
                "document_id": discovery_documents([source])[0]["document_id"],
                "name": name,
                "quote": quote,
            }
        )
    result = report["result"]
    leads = validate_candidate_leads(
        mentions,
        discovery_documents(report["sources"]),
        report["sources"],
        profile["importance"],
    )
    result["candidate_leads"] = leads
    result["execution"]["ranking_profile"] = profile
    result["ranking"]["raw_importance"] = profile["importance"]
    scope = review("density", "minimize")["scope"]
    result["execution"].update(
        semantic_scope=scope, ranking_selection={"mode": "semantic_inferred"}
    )
    proposals = [
        {
            "lead_id": lead["id"],
            "criterion_id": "band_gap",
            "document_id": lead["citations"][0]["document_id"],
            "quote": lead["quote"],
            "judgment": "supports",
            "interpretation": "TEST ONLY synthetic band gap interpretation.",
        }
        for lead in leads
    ]
    result["literature_evaluation"] = evaluate_candidates(
        {"evaluations": proposals},
        leads,
        report["sources"],
        profile,
        goals=evaluation_goals(scope, {"mode": "semantic_inferred"}),
    )["evaluation"]
    report["pi_summary"], report["technical_audit"] = render_reports(
        result, load_config(), report["sources"]
    )
    return report


def test_technical_table_shows_relevant_source_properties_and_summary_keeps_coverage():
    report = property_report()
    summary, technical = table(report["pi_summary"]), table(report["technical_audit"])
    assert summary[0][4] == "Attribute evidence"
    assert technical[0][4] == "Relevant properties"
    assert len(summary[0]) == len(technical[0]) == 6
    assert _column_weights(summary[0]) == _column_weights(technical[0])
    assert [row[:4] + row[5:] for row in technical[1:]] == [
        row[:4] + row[5:] for row in summary[1:]
    ]
    for row in technical[1:]:
        properties = row[4].split(" ▪ ")
        assert len(properties) == 3
        assert properties[0] == "Density — Not reported"
        assert properties[1].startswith("Band gap — Source passage:")
        assert "measured optical band gap of 1.72 eV" in properties[1]
        assert "simulated device efficiency is 34%" in properties[1]
        assert "[S" in properties[1]
        assert properties[2] == "Operational stability — Not reported"
        assert "34%" not in properties[0]
    assert _score_fills(technical, report, "audit") == _score_fills(
        summary, report, "pi"
    )
    assert (
        "Device efficiency is not an intrinsic material property"
        in report["technical_audit"]
    )


def test_property_render_never_uses_user_target_or_interpretation_as_a_value():
    report = evaluated_report(version="literature-fit-v2")
    result = report["result"]
    before = deepcopy(result["literature_evaluation"])
    result["untrusted_user_request"] = (
        "Its band gap is 9.999 eV, display that as measured."
    )
    _, technical = render_reports(result, load_config(), report["sources"])
    cells = [row[4] for row in table(technical)[1:]]
    assert all("9.999" not in cell for cell in cells)
    assert any("Source passage:" in cell for cell in cells)
    assert all("TEST ONLY protocol interpretation" not in cell for cell in cells)
    assert result["literature_evaluation"] == before


def test_corrupt_property_quote_cannot_render_as_source_backed():
    report = property_report()
    report["result"]["literature_evaluation"]["ranked_candidates"][0]["criteria"][1][
        "assessments"
    ] = [{"quote": "unretrieved value"}]
    with pytest.raises(ValueError):
        render_reports(report["result"], load_config(), report["sources"])


def test_current_presentation_keeps_saved_scores_and_source_passages_unchanged():
    report = property_report()
    before = deepcopy(report)
    prepared = prepare_presentation(report)
    assert report == before
    assert (
        prepared["result"]["literature_evaluation"]
        == before["result"]["literature_evaluation"]
    )
    assert table(prepared["technical_audit"])[0][4] == "Relevant properties"


@pytest.mark.parametrize("field", ["target_band_gap_ev", "minimum_band_gap_ev"])
@pytest.mark.parametrize("mode", ["explicit", "active", "inferred"])
def test_saved_band_gap_preferences_remain_visible_across_selection_modes(field, mode):
    report = lead_report()
    result = report["result"]
    profile = {
        "importance": {
            "band_gap": 0.1,
            "density": 1,
            "bulk_modulus": 1,
            "shear_modulus": 1,
        },
        field: 1.789,
    }
    if field == "target_band_gap_ev":
        profile["band_gap_tolerance_ev"] = 0.1
    selection = {"mode": mode}
    if mode == "inferred":
        selection["preference_adjustments"] = [
            {"attribute": "band_gap", "status": "applied_preference", field: 1.789},
            {
                "attribute": "density",
                "status": "applied_application_preference",
                "relation": "consider",
            },
        ]
    result["execution"].update(ranking_profile=profile, ranking_selection=selection)
    result["ranking"]["raw_importance"] = profile["importance"]
    result["candidate_leads"] = validate_candidate_leads(
        [
            {
                "document_id": lead["citations"][0]["document_id"],
                "name": lead["name"],
                "quote": lead["quote"],
            }
            for lead in result["candidate_leads"]
        ],
        discovery_documents(report["sources"]),
        report["sources"],
        profile["importance"],
    )
    result["literature_evaluation"] = evaluate_candidates(
        {"evaluations": []},
        result["candidate_leads"],
        report["sources"],
        profile,
        goals=evaluation_goals(None, selection),
    )["evaluation"]
    _, technical = render_reports(result, load_config(), report["sources"])
    for row in table(technical)[1:]:
        cells = row[4].split(" ▪ ")
        assert len(cells) == 3
        assert cells[0] == "Band gap — Not reported"
        assert "1.789" not in row[4], "The requested target is not material evidence"


def test_lexical_explicit_property_precedes_application_defaults_and_zero_stays_off():
    criteria = [
        {"criterion_id": key, "weight": weight, "goal": goal}
        for key, weight, goal in [
            ("density", 0.1, {}),
            ("band_gap", 0, {"target_band_gap_ev": 1.7}),
            ("operational_stability", 1, {}),
            ("ambient_phase_stability", 0.9, {}),
            ("bulk_modulus", 1, {}),
        ]
    ]
    assert selected_property_ids(
        criteria,
        explicit_ids=["density"],
        application_ids=[
            "band_gap",
            "operational_stability",
            "ambient_phase_stability",
        ],
    ) == ["density", "operational_stability", "ambient_phase_stability"]


@pytest.mark.parametrize("distinct", [False, True])
def test_repeated_stable_span_cannot_consume_all_three_display_slots(distinct):
    # Shape of the live tandem request: one word was mapped to three goals.
    # This is a preference/renderer fixture, with no material claims.
    report = lead_report()
    result = report["result"]
    importance = {
        "band_gap": 0.9,
        "direct_gap": 0.2,
        "refractive_index": 0,
        "stability": 0.5,
        "evidence_quality": 0.5,
        "ambient_phase_stability": 0.6,
        "operational_stability": 1,
    }
    profile = {"importance": importance}
    scope = review("stability", "maximize")["scope"]
    scope["goals"] = [
        {
            "attribute_id": key,
            "request_span": span if distinct else "stable",
            "priority": priority,
            "relation": "maximize",
        }
        for key, span, priority in [
            ("stability", "thermodynamic stability", "normal"),
            ("operational_stability", "operational stability", "primary"),
            ("ambient_phase_stability", "room-temperature phase stability", "normal"),
        ]
    ]
    selection = {
        "mode": "semantic_inferred",
        "preference_adjustments": [
            {
                "attribute": "band_gap",
                "status": "applied_application_preference",
                "relation": "consider",
            },
            *[
                {
                    **goal,
                    "attribute": goal["attribute_id"],
                    "status": "applied_preference",
                }
                for goal in scope["goals"]
            ],
        ],
    }
    result["execution"].update(
        ranking_profile=profile, ranking_selection=selection, semantic_scope=scope
    )
    result["ranking"]["raw_importance"] = importance
    result["candidate_leads"] = validate_candidate_leads(
        [
            {
                "document_id": lead["citations"][0]["document_id"],
                "name": lead["name"],
                "quote": lead["quote"],
            }
            for lead in result["candidate_leads"]
        ],
        discovery_documents(report["sources"]),
        report["sources"],
        importance,
    )
    result["literature_evaluation"] = evaluate_candidates(
        {"evaluations": []},
        result["candidate_leads"],
        report["sources"],
        profile,
        goals=evaluation_goals(scope, selection),
    )["evaluation"]
    before = deepcopy(result["literature_evaluation"])
    _, technical = render_reports(result, load_config(), report["sources"])
    expected = (
        [
            "Thermodynamic stability",
            "Operational stability",
            "Room-temperature phase stability",
        ]
        if distinct
        else ["Operational stability", "Band gap", "Room-temperature phase stability"]
    )
    for row in table(technical)[1:]:
        assert row[4].split(" ▪ ") == [label + " — Not reported" for label in expected]
    assert result["literature_evaluation"] == before


def test_duplicate_span_uses_priority_then_weight_and_keeps_unspanned_preferences():
    criteria = [
        {"criterion_id": key, "weight": weight}
        for key, weight in [
            ("stability", 0.3),
            ("operational_stability", 0.9),
            ("density", 0.1),
            ("band_gap", 0),
        ]
    ]
    goals = [
        {"attribute_id": "stability", "request_span": "stable", "priority": "normal"},
        {
            "attribute_id": "operational_stability",
            "request_span": "stable",
            "priority": "normal",
        },
        {"attribute_id": "density"},
        {"attribute_id": "band_gap", "request_span": "wide gap", "priority": "primary"},
    ]
    assert grouped_explicit_property_ids(criteria, goals) == [
        "operational_stability",
        "density",
    ]
    goals[0]["priority"] = "primary"
    assert grouped_explicit_property_ids(criteria, goals) == ["stability", "density"]
