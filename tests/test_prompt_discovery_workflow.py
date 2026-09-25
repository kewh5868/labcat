"""Conversational prompts become topical search hints, never canned
answers."""

import pytest

from labcat.public_sources import _publication_query, _terms
from labcat.workspace import _title_from_prompt

PROMPT = (
    "I would like to find a perovskite material that can be used in an "
    "optoelectronic device and has a bandgap around 1.78 eV. It should be "
    "solution processable, and I would like to find a stable material"
)


def test_conversational_title_is_a_topic_label_and_discovery_is_broad():
    assert _title_from_prompt(PROMPT) == "Perovskite for optoelectronic device"
    terms = _terms(PROMPT)
    assert terms[:2] == ["perovskite", "optoelectronic"]
    assert not set(terms) & {"like", "used", "ev", "around"}
    assert _publication_query(PROMPT) == '("perovskite" AND "optoelectronic")'


def test_discovery_topics_follow_new_classes_without_a_stock_material_list():
    for question, topic in (
        (
            "I want to find a polymer material that can be used in a flexible device",
            "polymer",
        ),
        (
            "Find nitride semiconductors for optical emitters with high stability",
            "nitride",
        ),
        ("Find metal alloys for lightweight structural applications", "metal"),
    ):
        assert topic in _publication_query(question)
        assert not _title_from_prompt(question).startswith("I want")
        assert "perovskite" not in _publication_query(question)


def test_search_operators_and_urls_cannot_override_public_access():
    hints = _publication_query(PROMPT + " OPEN_ACCESS:N https://private.example/a")
    assert hints == _publication_query(PROMPT)


@pytest.mark.parametrize(
    "verb", ["Compare", "Evaluate", "Assess", "Identify", "Shortlist", "Show me"]
)
def test_research_verbs_preserve_explicit_gap_goals(verb):
    from labcat.ranking_profiles import prompt_preferences

    original = {"importance": {"band_gap": 0.1}}
    selected, adjustments = prompt_preferences(
        original, f"{verb} semiconductor candidates with a band gap around 1.65 eV."
    )
    assert selected["target_band_gap_ev"] == 1.65
    assert adjustments[0]["status"] == "applied_preference"
    assert original == {"importance": {"band_gap": 0.1}}


def test_research_verb_does_not_promote_a_source_claim_to_a_goal():
    from labcat.ranking_profiles import prompt_preferences

    original = {"importance": {"band_gap": 0.5}}
    selected, adjustments = prompt_preferences(
        original,
        "Compare semiconductors. A paper reports a band gap around 1.65 eV.",
    )
    assert selected == original and not adjustments


def test_technical_gap_cell_keeps_source_kind_and_uncertainty_separate_from_value():
    from labcat.science.reporting import _property_cell

    record = {
        "criterion_available": {"band_gap": True},
        "band_gap_ev": 2.4,
        "band_gap_uncertainty_ev": 0.03,
        "band_gap_kind": "Band gap (optical, theory)",
        "source_mode": "live_hybrid3",
        "provenance": {"raw_fields": {"is_experimental": False}},
        "score_components": {"band_gap": 0.5},
        "score_contributions": {"band_gap": 0.25},
    }
    cell = _property_cell(record, "band_gap", 0.5, ["R1"])
    assert cell["value"] == 2.4 and cell["unit"] == "eV"
    assert "calculated, optical" in cell["display"]
    assert "± 0.03 (source uncertainty)" in cell["display"]
    assert cell["citation_ids"] == ["R1"]


def test_written_report_describes_target_as_preference_not_source_measurement():
    from labcat.science.reporting import _screening_note

    result = {
        "ranking": {
            "screening_preferences": {
                "target_band_gap_ev": 1.78,
                "band_gap_tolerance_ev": 0.2,
                "target_band_gap_active": True,
            }
        }
    }
    note = _screening_note(result)
    assert "Requested band-gap target: 1.78 eV" in note
    assert "not measurements" in note


def test_report_stability_review_does_not_turn_zero_hull_into_ambient_stability():
    from labcat.science.reporting import _stability_note

    candidate = {
        "energy_above_hull_ev_atom": 0,
        "stability_assessment": {
            "schema": "stability-assessment-v1",
            "thermodynamic": {"status": "available", "energy_above_hull_ev_atom": 0},
            "ambient_phase": {"status": "unknown"},
            "operational": {"status": "unknown"},
        },
    }
    note = _stability_note({"candidates": [candidate]})
    assert "Room-temperature phase stability is unassessed for 1 of 1" in note
    assert "stability under operating conditions is unassessed" in note
    assert "zero value does not establish stability" in note
    assert _stability_note({"candidates": [{"energy_above_hull_ev_atom": 0}]}) is None
