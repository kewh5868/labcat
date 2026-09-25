"""Synthetic policy boundary values, never scientific source
fixtures/results."""

from copy import deepcopy

import pytest

from labcat.config import load_config
from labcat.science.evidence_comparison import (
    MAX_COMPARISON_PAIRS,
    MAX_COMPARISON_RECORDS,
    compare_and_select_records,
    compare_observations,
    evidence_method,
    experimental_range_from_records,
    experimental_scope_key,
)
from labcat.science.ranking import rank_records


def observation(index, value, experimental, **raw_changes):
    raw = {
        "system_id": 42,
        "is_experimental": experimental,
        "property": "band gap (fundamental)",
        "sample_type": "single crystal",
        "crystal_system": "cubic",
        "space_group": "Pm-3m",
        "subset_label": "phase alpha",
        "conditions": [
            {"property": "Temperature", "value": 300, "uncertainty": None, "unit": "K"}
        ],
        "band_gap_ev": value,
        **raw_changes,
    }
    return {
        "material_id": f"hybrid3:42:dataset{index}:subset{index}",
        "formula": "CsSnI3",
        "elements": ["Cs", "I", "Sn"],
        "band_gap_ev": value,
        "band_gap_kind": raw["property"],
        "source_mode": "live_hybrid3",
        "issues": [],
        "provenance": {
            "raw_fields": raw,
            "raw_fields_sha256": f"{index:064x}",
            "response_sha256": "f" * 64,
            "source_url": (
                f"https://materials.hybrid3.duke.edu/materials/dataset/{index}"
            ),
        },
    }


def rank(records, **preferences):
    return rank_records(
        records, load_config(), importance={"band_gap": 1}, **preferences
    )


def test_experimental_record_selected_before_score_and_preserves_both_observations():
    experiment, computed = observation(1, 1, True), observation(2, 8, False)
    original = deepcopy([computed, experiment])
    selected, audit = rank([computed, experiment])
    assert [row["material_id"] for row in selected] == [experiment["material_id"]]
    assert selected[0]["band_gap_ev"] == 1
    assert selected[0]["score"] == pytest.approx(1 / 8)
    comparison = selected[0]["evidence_comparison"]
    assert comparison["experimental_precedence_applied"] is True
    assert comparison["comparisons"][0]["delta_computed_minus_experimental"] == 7
    assert comparison["comparisons"][0]["computed"]["value"] == 8
    assert set(audit["comparison_record_ids"]) == {
        experiment["material_id"],
        computed["material_id"],
    }
    assert [computed, experiment] == original


def test_failed_experimental_minimum_cannot_be_evaded_with_computed_alternative():
    experiment, computed = observation(1, 1, True), observation(2, 8, False)
    selected, audit = rank([computed, experiment], minimum_band_gap_ev=2)
    assert selected == []
    assert len(audit["excluded_records"]) == 2
    assert len(audit["comparison_record_ids"]) == 2
    assert len(audit["evidence_comparisons"]) == 2
    assert any(
        "below the saved screening minimum" in " ".join(row["reasons"])
        for row in audit["excluded_records"]
    )


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"system_id": 43}, "system differs"),
        ({"system_id": True}, "system is missing"),
        ({"system_id": "42"}, "system is missing"),
        ({"conditions": []}, "conditions is missing"),
        ({"sample_type": None}, "sample type is missing"),
        ({"sample_type": "unknown"}, "sample type is missing"),
        ({"sample_type": "powder"}, "sample type differs"),
        ({"subset_label": None}, "phase label is missing"),
        ({"subset_label": "phase beta"}, "phase label differs"),
        ({"space_group": "P4mm"}, "space group differs"),
        ({"property": "band gap (optical, theory)"}, "property differs"),
        (
            {
                "conditions": [
                    {
                        "property": "Temperature",
                        "value": 400,
                        "uncertainty": None,
                        "unit": "K",
                    }
                ]
            },
            "conditions differs",
        ),
    ],
)
def test_unknown_or_different_context_does_not_invent_comparability(change, reason):
    experiment, computed = observation(1, 1, True), observation(2, 8, False, **change)
    selected, audit = compare_and_select_records([computed, experiment])
    assert len(selected) == 2
    pair = audit["evidence_comparisons"][0]["comparisons"][0]
    assert pair["status"] == "not_comparable"
    assert pair["delta_computed_minus_experimental"] is None
    assert reason in " ".join(pair["reasons"])


def test_optical_computation_and_optical_measurement_preserve_method_labels():
    experiment = observation(1, 2, True, property="band gap (optical, transmission)")
    computed = observation(2, 4, False, property="band gap (optical, theory)")
    selected, _ = rank([computed, experiment])
    pair = selected[0]["evidence_comparison"]["comparisons"][0]
    assert pair["status"] == "comparable"
    assert pair["experimental"]["property_kind"] == experiment["band_gap_kind"]
    assert pair["computed"]["property_kind"] == computed["band_gap_kind"]


def test_multiple_experiments_cannot_cherry_pick_the_best_target_match():
    records = [
        observation(1, 2, True),
        observation(2, 1, True),
        observation(3, 2, False),
    ]
    selected, audit = rank(records, target_band_gap_ev=2)
    assert selected[0]["band_gap_ev"] == 1
    values = selected[0]["evidence_comparison"]["experimental_range"]
    assert values["minimum"] == 1 and values["maximum"] == 2 and values["count"] == 2
    assert rank(list(reversed(records)), target_band_gap_ev=2)[0] == selected
    assert set(values["record_ids"]) <= set(audit["comparison_record_ids"])


def test_any_failed_experiment_dominates_an_even_worse_target_fit_above_minimum():
    records = [
        observation(1, 1, True),
        observation(2, 9, True),
        observation(3, 2, False),
    ]
    selected, _ = rank(records, minimum_band_gap_ev=1.5, target_band_gap_ev=2)
    assert selected == []


def test_prose_cannot_reclassify_unknown_source_or_override_explicit_flag():
    unknown = {
        **observation(1, 2, True),
        "source_mode": "live_nomad",
        "method": "experimental measured from an important paper",
    }
    assert evidence_method(unknown) == "unknown"
    assert (
        evidence_method({**unknown, "source_mode": "live_materials_project"})
        == "computed"
    )
    assert evidence_method(observation(1, 2, "true")) == "unknown"
    explicit = {**observation(1, 2, False), "method": "experimental"}
    assert evidence_method(explicit) == "computed"


def test_cross_source_formula_and_space_group_match_do_not_merge():
    experiment = observation(1, 1, True)
    computed = {**observation(2, 8, False), "source_mode": "live_materials_project"}
    selected, audit = compare_and_select_records([experiment, computed])
    assert len(selected) == 2
    assert (
        "Cross-source"
        in audit["evidence_comparisons"][0]["comparisons"][0]["reasons"][0]
    )


def test_computed_only_unrelated_properties_are_not_silently_merged_into_experiment():
    experiment = observation(1, 1, True)
    computed = {**observation(2, 8, False), "dielectric_total": 50}
    selected, _ = rank_records(
        [experiment, computed],
        load_config(),
        importance={"band_gap": 0.5, "dielectric_total": 0.5},
    )
    assert selected[0].get("dielectric_total") is None
    assert selected[0]["criterion_available"]["dielectric_total"] is False
    assert "not merged" in selected[0]["evidence_comparison"]["selection_reason"]


def test_display_limits_never_truncate_the_experiment_set_before_preference():
    records = [observation(index, 2, True) for index in range(1, 241)]
    records[-1]["band_gap_ev"] = 0.5
    records += [observation(index, 8, False) for index in range(241, 481)]
    selected, audit = rank(records, minimum_band_gap_ev=1)
    assert selected == []
    policy = audit["evidence_comparison_policy"]
    assert policy["displayed_pairs"] <= MAX_COMPARISON_PAIRS
    assert policy["displayed_pairs"] + policy["omitted_pairs"] == 240 * 240
    assert len(audit["comparison_record_ids"]) <= MAX_COMPARISON_RECORDS
    assert all(
        "raw_fields" not in row.get("provenance", {})
        for row in audit["excluded_records"][:-1]
    )


def test_duplicate_identity_still_rejected_even_if_preference_would_suppress_it():
    record = observation(1, 2, False)
    with pytest.raises(ValueError, match="duplicate material identity"):
        rank([record, deepcopy(record), observation(2, 1, True)])


def test_unmatched_single_experiment_does_not_claim_preference_was_applied():
    selected, audit = compare_and_select_records([observation(1, 2, True)])
    metadata = selected[0]["evidence_comparison"]
    assert metadata["experimental_precedence_applied"] is False
    assert "no verified comparable calculation" in metadata["selection_reason"]
    assert audit["comparison_record_ids"] == []


def test_experiment_range_display_omissions_are_explicit_and_do_not_change_selection():
    records = []
    for group in range(24):
        for member, value in enumerate((1, 2)):
            records.append(
                observation(
                    group * 2 + member + 1,
                    value,
                    True,
                    subset_label=f"distinct source phase {group}",
                )
            )
    selected, audit = compare_and_select_records(records)
    assert len(selected) == 24
    assert all(row["band_gap_ev"] == 1 for row in selected)
    assert audit["evidence_comparison_policy"]["omitted_experimental_ranges"] == 6
    assert len(audit["comparison_record_ids"]) == MAX_COMPARISON_RECORDS


def test_saved_pair_status_and_delta_cannot_override_original_condition_mismatch():
    experiment = observation(1, 1, True)
    calculation = observation(2, 4, False, subset_label="a distinct phase")
    original = compare_observations(experiment, calculation)
    corrupted = {
        **original,
        "status": "comparable",
        "delta_computed_minus_experimental": 3,
    }
    recomputed = compare_observations(experiment, calculation)
    assert corrupted != recomputed
    assert recomputed["status"] == "not_comparable"
    assert recomputed["delta_computed_minus_experimental"] is None


@pytest.mark.parametrize(
    "side, mode, flag",
    [
        ("experiment", "live_nomad", True),
        ("experiment", "live_hybrid3", None),
        ("experiment", "live_hybrid3", False),
        ("calculation", "live_nomad", False),
        ("calculation", "live_hybrid3", True),
    ],
)
def test_saved_comparison_requires_strict_roles_in_original_records(side, mode, flag):
    experiment, calculation = observation(1, 1, True), observation(2, 4, False)
    record = experiment if side == "experiment" else calculation
    record["source_mode"] = mode
    record["provenance"]["raw_fields"]["is_experimental"] = flag
    with pytest.raises(ValueError, match="explicit experimental and computed"):
        compare_observations(experiment, calculation)


def test_saved_comparison_rejects_different_compositions_even_with_same_system_id():
    experiment, calculation = observation(1, 1, True), observation(2, 4, False)
    calculation["formula"] = "SiO2"
    with pytest.raises(ValueError, match="different material compositions"):
        compare_observations(experiment, calculation)


@pytest.mark.parametrize(
    "change",
    [
        {"is_experimental": False},
        {"is_experimental": None},
        {"subset_label": "a different phase"},
        {"conditions": []},
        {"property": "band gap (optical, transmission)"},
    ],
)
def test_saved_range_rejects_unknown_computed_or_different_scope_extrema(change):
    extrema = [observation(1, 1, True), observation(2, 3, True, **change)]
    with pytest.raises(ValueError, match="matching experimental scopes"):
        experimental_range_from_records(extrema)


def test_saved_range_rejects_nomad_experiment_label_and_different_context():
    experiment = observation(1, 1, True)
    unknown = {**experiment, "source_mode": "live_nomad"}
    assert experimental_scope_key(unknown) is None
    with pytest.raises(ValueError, match="matching experimental scopes"):
        experimental_range_from_records([unknown])
    with pytest.raises(ValueError, match="does not match its material context"):
        experimental_range_from_records(
            [experiment], context=observation(2, 4, False, subset_label="phase beta")
        )


def test_saved_range_recomputes_extrema_and_does_not_claim_unretained_count():
    first, second = observation(1, 1, True), observation(2, 3, True)
    result = experimental_range_from_records(
        [second, first], context=observation(3, 4, False)
    )
    assert result == {
        "minimum": 1,
        "maximum": 3,
        "unit": "eV",
        "record_ids": [first["material_id"], second["material_id"]],
    }
    assert "count" not in result
    with pytest.raises(ValueError, match="distinct identities"):
        experimental_range_from_records([first, deepcopy(first)])
