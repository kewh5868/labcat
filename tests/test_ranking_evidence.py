"""Arithmetic/policy boundary cases, never materials evidence or demo
results.

The synthetic values below deliberately probe utility anchors and
missing-data behavior. They are not measurements and are never exposed
by a source adapter.
"""

import copy
import math

import pytest

from labcat.config import load_config
from labcat.science.preferences import validate_formula
from labcat.science.ranking import rank_records


def row(identity="test-only-1", formula="SiO2", **properties):
    return {
        "material_id": identity,
        "formula": formula,
        "elements": validate_formula(formula),
        "band_gap_ev": None,
        "dielectric_total": None,
        "dielectric_electronic": None,
        "energy_above_hull_ev_atom": None,
        "density_g_cm3": None,
        "bulk_modulus_gpa": None,
        "shear_modulus_gpa": None,
        "nsites": None,
        "source_mode": "synthetic_arithmetic_test_only",
        "issues": [],
        **properties,
    }


def rank(records, weights, application="high_k_screening"):
    return rank_records(
        records, load_config(), importance=weights, application=application
    )


@pytest.mark.parametrize(
    "dielectric,utility",
    [(0, 0), (3.9, 0), (4, 0), (math.sqrt(4 * 50), 0.5), (50, 1), (500, 1)],
)
def test_high_k_log_utility_anchors_are_preferences_not_rewritten_source_values(
    dielectric, utility
):
    record = row(dielectric_total=dielectric)
    before = copy.deepcopy(record)
    ranked, metadata = rank([record], {"dielectric_total": 1})
    assert ranked[0]["score"] == pytest.approx(utility)
    assert ranked[0]["score_components"]["dielectric_total"] == pytest.approx(utility)
    assert ranked[0]["dielectric_total"] == dielectric
    assert record == before
    assert metadata["algorithm"] == "public-materials-utility-v8"
    assert metadata["required_comparison_criteria"] == ["dielectric_total"]
    assert "log(" in metadata["normalization"]["dielectric_total"]
    assert "preferences" in metadata["anchor_status"]
    assert "not measured" in metadata["anchor_status"]


def test_formula_names_cannot_override_evidence_or_supply_desired_order():
    first = row("test-a", "SiO2", band_gap_ev=4, dielectric_total=8)
    second = row("test-b", "BaTiO3", band_gap_ev=4, dielectric_total=30)
    ranked, _ = rank([first, second], {"band_gap": 1, "dielectric_total": 1})
    expected_ids = [record["material_id"] for record in ranked]
    expected_scores = [record["score"] for record in ranked]
    swapped = [
        {**first, "formula": second["formula"], "elements": second["elements"]},
        {**second, "formula": first["formula"], "elements": first["elements"]},
    ]
    again, _ = rank(swapped, {"band_gap": 1, "dielectric_total": 1})
    assert (
        [record["material_id"] for record in again]
        == expected_ids
        == ["test-b", "test-a"]
    )
    assert [record["score"] for record in again] == expected_scores


def test_missing_comparison_evidence_cannot_outrank_a_complete_lower_scoring_row():
    complete = row("complete", "Al2O3", band_gap_ev=0, dielectric_total=4)
    missing_gap = row("missing-gap", "SiO2", dielectric_total=50)
    missing_dielectric = row("missing-dielectric", "TiO2", band_gap_ev=8)
    ranked, metadata = rank(
        [missing_gap, missing_dielectric, complete],
        {"dielectric_total": 1, "band_gap": 1},
    )
    assert ranked[0]["material_id"] == "complete" and ranked[0]["score"] == 0
    assert all(record["score"] > ranked[0]["score"] for record in ranked[1:])
    assert ranked[0]["score_analysis"]["status"] == "comparable"
    assert ranked[1]["score_analysis"]["status"] == "needs_evidence"
    assert ranked[2]["score_analysis"]["status"] == "needs_evidence"
    assert set(metadata["required_comparison_criteria"]) == {
        "dielectric_total",
        "band_gap",
    }
    assert {
        record["material_id"]: record["score_analysis"]["missing_required_criteria"]
        for record in ranked
    } == {
        "complete": [],
        "missing-gap": ["band_gap"],
        "missing-dielectric": ["dielectric_total"],
    }
    assert all(
        "evidence-review lead" in " ".join(record["caveats"]) for record in ranked[1:]
    )


def test_zero_weight_gap_is_not_a_required_comparison_property():
    ranked, metadata = rank(
        [row(dielectric_total=50)], {"dielectric_total": 1, "band_gap": 0}
    )
    assert ranked[0]["score"] == 1
    assert metadata["required_comparison_criteria"] == ["dielectric_total"]
    assert ranked[0]["score_analysis"]["status"] == "comparable"
    assert "band_gap" not in ranked[0]["missing_selected_criteria"]


def test_partial_supported_score_fit_coverage_and_upper_bound_are_distinct():
    ranked, metadata = rank(
        [row(band_gap_ev=4)],
        {"band_gap": 0.5, "dielectric_total": 0.3, "stability": 0.2},
    )
    result = ranked[0]
    assert result["score"] == pytest.approx(0.25)
    assert result["score_analysis"]["observed_fit"] == pytest.approx(0.5)
    assert result["score_analysis"]["coverage"] == pytest.approx(0.5)
    assert result["score_analysis"]["possible_upper_score"] == pytest.approx(0.75)
    assert result["score_contributions"] == {
        "band_gap": 0.25,
        "dielectric_total": 0,
        "stability": 0,
    }
    assert result["criterion_available"] == {
        "band_gap": True,
        "dielectric_total": False,
        "stability": False,
    }
    assert "never used alone" in metadata["score_interpretation"]
    assert "not a confidence interval" in metadata["score_interpretation"]


def test_unsupported_weights_remain_in_denominator_and_upper_bound():
    ranked, _ = rank([row(band_gap_ev=8)], {"band_gap": 1, "refractive_index": 1})
    assert ranked[0]["score"] == 0.5
    assert ranked[0]["score_analysis"]["coverage"] == 0.5
    assert ranked[0]["score_analysis"]["observed_fit"] == 1
    assert ranked[0]["score_analysis"]["possible_upper_score"] == 1
    assert ranked[0]["missing_selected_criteria"] == ["refractive_index"]


def test_fully_supported_score_and_known_zero_have_no_missing_weight():
    for source, expected in [(row(band_gap_ev=8), 1), (row(band_gap_ev=0), 0)]:
        ranked, _ = rank([source], {"band_gap": 1})
        assert ranked[0]["score"] == expected
        analysis = ranked[0]["score_analysis"]
        assert analysis["coverage"] == 1
        assert analysis["observed_fit"] == analysis["possible_upper_score"] == expected


def test_no_supported_selected_evidence_means_no_score_or_invented_padding():
    ranked, metadata = rank([row()], {"band_gap": 1, "dielectric_total": 1})
    assert ranked == []
    assert len(metadata["excluded_records"]) == 1
    assert "No positively weighted" in metadata["excluded_records"][0]["reasons"][0]


@pytest.mark.parametrize(
    "application",
    [None, "thin_film_insulation", "property_exploration", "Custom application"],
)
def test_other_applications_keep_linear_dielectric_utility_and_no_high_k_gate(
    application,
):
    ranked, metadata = rank(
        [row(dielectric_total=10)], {"dielectric_total": 1}, application
    )
    assert ranked[0]["score"] == 0.2
    assert metadata["required_comparison_criteria"] == []
    assert "log(" not in metadata["normalization"]["dielectric_total"]
    assert ranked[0]["score_analysis"]["status"] == "comparable"


def test_same_composition_ratios_deduplicate_phases_without_merging_properties():
    records = [
        row("source-a", "SiO2", band_gap_ev=4),
        row("source-b", "O4Si2", band_gap_ev=8),
        row("source-c", "Al2O3", band_gap_ev=2),
    ]
    ranked, metadata = rank(records, {"band_gap": 1})
    assert [record["material_id"] for record in ranked] == ["source-b", "source-c"]
    assert ranked[0]["formula"] == "O4Si2"
    assert ranked[0]["band_gap_ev"] == 8
    assert metadata["alternative_phase_ids"] == ["source-a"]


def test_twelve_is_a_cap_not_a_required_number_of_results():
    # Synthetic arithmetic records probe distinct ratios, not proposed phases.
    records = [
        row(f"test-{count:02}", f"SiO{count}", band_gap_ev=4) for count in range(1, 15)
    ]
    ranked, metadata = rank(records, {"band_gap": 1})
    assert len(ranked) == metadata["shortlist_limit"] == 12
    assert [record["rank"] for record in ranked] == list(range(1, 13))
    assert [record["material_id"] for record in ranked] == [
        r["material_id"] for r in records[:12]
    ]
    small, _ = rank(records[:2], {"band_gap": 1})
    assert len(small) == 2
    assert rank([], {"band_gap": 1})[0] == []


def test_duplicate_source_identity_is_rejected_even_across_different_formulas():
    with pytest.raises(ValueError, match="duplicate material identity"):
        rank(
            [row("same", "SiO2", band_gap_ev=4), row("same", "Al2O3", band_gap_ev=5)],
            {"band_gap": 1},
        )


@pytest.mark.parametrize(
    "application",
    [False, 1, {}, [], "", " " * 3, "line\nbreak", "control\x00", "x" * 121],
)
def test_invalid_application_preferences_fail_before_scoring(application):
    with pytest.raises(ValueError, match="application"):
        rank([row(band_gap_ev=4)], {"band_gap": 1}, application)


def test_target_gap_scores_distance_not_larger_values_and_preserves_source_evidence():
    records = [
        row("target", "SiO2", band_gap_ev=1.78),
        row("above", "Al2O3", band_gap_ev=1.98),
        row("below", "ZrO2", band_gap_ev=1.58),
        row("large", "HfO2", band_gap_ev=8),
    ]
    before = copy.deepcopy(records)
    ranked, metadata = rank_records(
        records,
        load_config(),
        importance={"band_gap": 1},
        application="optoelectronics",
        target_band_gap_ev=1.78,
        band_gap_tolerance_ev=0.2,
    )
    indexed = {item["material_id"]: item for item in ranked}
    assert ranked[0]["material_id"] == "target"
    assert indexed["target"]["score"] == 1
    assert indexed["above"]["score"] == indexed["below"]["score"] == 0.5
    assert indexed["large"]["score"] < 0.01
    assert records == before
    assert all(item["selected_weight_coverage"] == 1 for item in ranked)
    assert metadata["screening_preferences"]["target_band_gap_ev"] == 1.78
    assert (
        "not a measured" in metadata["screening_preferences"]["target_interpretation"]
    )
    assert "source band gap" in metadata["normalization"]["band_gap"]


def test_target_missing_gap_is_unknown_and_comes_after_measured_comparison():
    records = [
        row("missing", "SiO2", band_gap_ev=None),
        row("distant", "Al2O3", band_gap_ev=20),
    ]
    ranked, metadata = rank_records(
        records,
        load_config(),
        importance={"band_gap": 0.5, "simplicity": 0.5},
        target_band_gap_ev=1.78,
    )
    assert [item["material_id"] for item in ranked] == ["distant", "missing"]
    assert ranked[1]["band_gap_ev"] is None
    assert ranked[1]["score_components"]["band_gap"] == 0
    assert ranked[1]["score_analysis"]["status"] == "needs_evidence"
    assert ranked[1]["score_analysis"]["coverage"] == 0.5
    assert ranked[1]["score_analysis"]["missing_required_criteria"] == ["band_gap"]
    assert metadata["screening_preferences"]["band_gap_tolerance_ev"] == 0.2
    assert metadata["screening_preferences"]["band_gap_tolerance_origin"] == (
        "application_default"
    )


def test_target_does_not_implicitly_filter_or_override_explicit_minimum():
    records = [row("a", "SiO2", band_gap_ev=1.78), row("b", "Al2O3", band_gap_ev=3)]
    ranked, metadata = rank_records(
        records,
        load_config(),
        importance={"band_gap": 1},
        target_band_gap_ev=1.78,
        minimum_band_gap_ev=2,
    )
    assert [item["material_id"] for item in ranked] == ["b"]
    assert metadata["screening_preferences"]["minimum_band_gap_active"]


def test_unweighted_target_does_not_create_missing_requirement():
    ranked, metadata = rank_records(
        [row()],
        load_config(),
        importance={"band_gap": 0, "simplicity": 1},
        target_band_gap_ev=1.78,
    )
    assert ranked[0]["score_analysis"]["status"] == "comparable"
    assert metadata["required_comparison_criteria"] == []
    assert metadata["screening_preferences"]["target_band_gap_active"] is False


@pytest.mark.parametrize(
    "target,tolerance",
    [
        (True, None),
        ("1.78", None),
        (float("nan"), None),
        (10**500, None),
        (-1, None),
        (None, 0.2),
        (1.78, 0),
        (1.78, float("inf")),
        (1.78, 10**500),
    ],
)
def test_invalid_target_preferences_are_rejected_before_scoring(target, tolerance):
    with pytest.raises(ValueError):
        rank_records(
            [row()],
            load_config(),
            target_band_gap_ev=target,
            band_gap_tolerance_ev=tolerance,
        )


def test_very_small_valid_target_tolerance_remains_finite():
    ranked, _ = rank_records(
        [row(band_gap_ev=1.5)],
        load_config(),
        importance={"band_gap": 1},
        target_band_gap_ev=1.78,
        band_gap_tolerance_ev=5e-324,
    )
    assert math.isfinite(ranked[0]["score"])
