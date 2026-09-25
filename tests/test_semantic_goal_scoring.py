"""Preference-direction arithmetic and approved synthetic adapter report
fixtures."""

from copy import deepcopy

import pytest
from test_evidence_comparison_workflow import adapter_record
from test_ranking_evidence import row
from test_semantic_source_scope import scope

from labcat import science
from labcat.config import load_config
from labcat.science.ranking import rank_records
from labcat.science.reporting import render_reports


def review(attribute, relation, *, authority="inferred", request=None):
    request = request or f"{relation} {attribute.replace('_', ' ')}"
    prompt = "Find semiconductors and " + request + "."
    selection = scope("semiconductors", material_class="semiconductors")
    selection["goals"] = [
        {
            "attribute_id": attribute,
            "request_span": request,
            "priority": "primary",
            "relation": relation,
        }
    ]
    return {"scope": selection, "prompt": prompt, "authority": authority}


@pytest.mark.parametrize(
    "attribute,relation,properties",
    [
        ("density", "maximize", {"density_g_cm3": 6.0}),
        ("dielectric_total", "minimize", {"dielectric_total": 20.0}),
        ("band_gap", "minimize", {"band_gap_ev": 1.4}),
        ("bulk_modulus", "target", {"bulk_modulus_gpa": 100.0}),
    ],
)
def test_unsupported_inferred_direction_does_not_apply_opposite_default_utility(
    attribute, relation, properties
):
    record = row(**properties)
    before = deepcopy(record)
    importance = {attribute: 1, "simplicity": 1}
    baseline, baseline_audit = rank_records(
        [record], load_config(), importance=importance
    )
    candidates, audit = rank_records(
        [record],
        load_config(),
        importance=importance,
        goal_review=review(attribute, relation),
    )
    selected = candidates[0]
    assert (
        selected["score_components"][attribute]
        == selected["score_contributions"][attribute]
        == 0
    )
    assert selected["criterion_evidence_available"][attribute] is True
    assert selected["criterion_available"][attribute] is False
    assert selected["missing_measurement_criteria"] == []
    assert selected["unscored_goal_reasons"][attribute]
    assert audit["raw_importance"] == baseline_audit["raw_importance"] == importance
    assert audit["weights"] == baseline_audit["weights"]
    assert audit["algorithm"] == "public-materials-utility-v9"
    assert audit["goal_review"]["requested_goals"][0]["relation"] == relation
    assert baseline[0]["score"] > selected["score"]
    assert all(selected[key] == value for key, value in properties.items())
    assert record == before


@pytest.mark.parametrize(
    "attribute,relation,properties",
    [
        ("density", "minimize", {"density_g_cm3": 6.0}),
        ("band_gap", "maximize", {"band_gap_ev": 1.4}),
        ("stability", "maximize", {"energy_above_hull_ev_atom": 0.1}),
        ("dielectric_total", "consider", {"dielectric_total": 20.0}),
    ],
)
def test_compatible_requests_keep_existing_scores(attribute, relation, properties):
    record = row(**properties)
    baseline, old_audit = rank_records(
        [record], load_config(), importance={attribute: 1}
    )
    candidates, audit = rank_records(
        [record],
        load_config(),
        importance={attribute: 1},
        goal_review=review(attribute, relation),
    )
    assert candidates[0]["score"] == baseline[0]["score"]
    assert candidates[0]["score_components"] == baseline[0]["score_components"]
    assert audit["weights"] == old_audit["weights"]
    assert audit["goal_review"]["review_only_attributes"] == []


def test_selected_profile_authority_preserves_utilities_and_screening():
    records = [row(band_gap_ev=1.4)]
    args = {"importance": {"band_gap": 1, "simplicity": 1}, "target_band_gap_ev": 2.0}
    baseline, old_audit = rank_records(records, load_config(), **args)
    candidates, audit = rank_records(
        records,
        load_config(),
        **args,
        goal_review=review("band_gap", "minimize", authority="profile"),
    )
    for key in (
        "score",
        "score_components",
        "score_contributions",
        "criterion_available",
        "score_analysis",
    ):
        assert candidates[0][key] == baseline[0][key]
    for key in ("weights", "raw_importance", "screening_preferences", "normalization"):
        assert audit[key] == old_audit[key]
    assert audit["goal_review"]["review_only_attributes"]
    assert audit["goal_review"]["unscored_attributes"] == []


@pytest.mark.parametrize("target,supported", [(1.8, True), (2.5, False)])
def test_target_direction_requires_literal_target_matching_saved_parameters(
    target, supported
):
    candidates, audit = rank_records(
        [row(band_gap_ev=1.8)],
        load_config(),
        importance={"band_gap": 1, "simplicity": 1},
        target_band_gap_ev=target,
        goal_review=review("band_gap", "target", request="band gap around 1.8 eV"),
    )
    assert candidates[0]["criterion_available"]["band_gap"] is supported
    assert bool(audit["goal_review"]["unscored_attributes"]) is not supported
    assert candidates[0]["band_gap_ev"] == 1.8


def core_outcome(monkeypatch, *, authority="inferred", only_goal=False, count=1):
    preferences = review("band_gap", "minimize", authority=authority)
    records = (
        science.load_snapshot()[0][:count]
        if count > 1
        else [adapter_record(900, 1.4, True)]
    )
    calls = []

    def retrieve(*args, **kwargs):
        calls.append(kwargs)
        return deepcopy(records), {"status": "ok", "records_retrieved": len(records)}

    monkeypatch.setattr(science, "_retrieve_repositories", retrieve)
    outcome = science.run_research(
        preferences["prompt"],
        load_config(),
        semantic_scope=preferences["scope"],
        semantic_goal_authority=authority,
        importance={"band_gap": 1, **({} if only_goal else {"simplicity": 1})},
        minimum_band_gap_ev=3.0,
        target_band_gap_ev=3.5,
    )
    return outcome, calls, records


def test_known_unscored_value_stays_cited_and_is_not_called_missing(monkeypatch):
    outcome, calls, _ = core_outcome(monkeypatch)
    result = outcome["result"]
    assert calls[0]["minimum_band_gap_ev"] is None
    assert "band_gap_ev" not in calls[0]["required_fields"]
    assert result["candidates"][0]["band_gap_ev"] == 1.4
    cell = result["report_tables"]["technical"]["rows"][0]["properties"]["band_gap"]
    assert cell["value"] == 1.4 and cell["status"] == "available"
    assert cell["citation_ids"] and "Unscored goal:" in cell["display"]
    assert cell["contribution"] == cell["utility"] == 0
    for view in ("pi_summary", "technical_audit"):
        assert "Requested ranking goals:" in outcome[view]
        assert "Band gap: minimize" in outcome[view]
        assert "Band gap evidence" not in outcome[view]
        assert "supported requested utilities for Band gap" in outcome[view]
    assert "Missing selected criteria: None" in outcome["technical_audit"]
    assert "1.4" in outcome["technical_audit"] and "[R1]" in outcome["technical_audit"]


def test_all_unsupported_goals_retain_bounded_unranked_original_source_records(
    monkeypatch,
):
    outcome, _, records = core_outcome(monkeypatch, only_goal=True, count=15)
    result = outcome["result"]
    assert result["candidates"] == []
    assert len(result["review_records"]) == 12
    assert (
        len([source for source in outcome["sources"] if source.get("record_id")]) == 12
    )
    assert result["report_tables"]["technical"]["rows"] == []
    for actual, original in zip(result["review_records"], records, strict=False):
        assert {
            key: value for key, value in actual.items() if key != "source_ids"
        } == original
        assert not {"rank", "score", "utility"} & set(actual)
    for view in ("pi_summary", "technical_audit"):
        assert "Unscored material evidence:" in outcome[view]
        assert "1.73 eV" in outcome[view] and "[R1]" in outcome[view]


def test_missing_measurement_remains_unknown_without_fabricated_zero():
    candidates, _ = rank_records(
        [row()],
        load_config(),
        importance={"density": 1, "simplicity": 1},
        goal_review=review("density", "maximize"),
    )
    assert candidates[0]["density_g_cm3"] is None
    assert candidates[0]["missing_measurement_criteria"] == ["density"]


@pytest.mark.parametrize("mutation", ["authority", "span", "reason"])
def test_invalid_internal_goal_preferences_are_rejected(mutation):
    preferences = review("density", "maximize")
    if mutation == "authority":
        preferences["authority"] = []
    elif mutation == "span":
        preferences["scope"]["goals"][0][
            "request_span"
        ] = "invented unrelated preference"
    else:
        preferences["reason"] = "arbitrary model instruction"
    with pytest.raises(ValueError):
        rank_records(
            [row()],
            load_config(),
            importance={"simplicity": 1},
            goal_review=preferences,
        )


def test_saved_report_cannot_inject_goal_reason_or_provider_warning(monkeypatch):
    outcome, _, _ = core_outcome(monkeypatch)
    result = deepcopy(outcome["result"])
    result["execution"] = {
        "model_interrupted": True,
        "warning": "SECRET arbitrary provider diagnostic",
    }
    for text in render_reports(result, load_config(), outcome["sources"]):
        assert "Research completion:" in text
        assert "without another model call" in text
        assert "SECRET" not in text
    result["ranking"]["goal_review"]["review_only_attributes"][0][
        "reason"
    ] = "invented reason"
    with pytest.raises(ValueError, match="goal diagnostics"):
        render_reports(result, load_config(), outcome["sources"])
