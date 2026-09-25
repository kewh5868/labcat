"""Synthetic comparison fixtures verify reporting, never scientific
results."""

import hashlib
import json
from copy import deepcopy

import pytest

from labcat.config import load_config
from labcat.science import hybrid3
from labcat.science.evidence_comparison import compare_observations
from labcat.science.ranking import rank_records
from labcat.science.reporting import citation_references, render_reports


def adapter_record(
    identifier,
    gap,
    experimental,
    *,
    formula="SiO2",
    phase="TEST ONLY matched phase",
    dataset_id=None,
):
    """Pass deliberately synthetic transport data through the approved
    parser."""
    row = {
        "pk": dataset_id or identifier,
        "visible": True,
        "system": {"id": 1, "formula": formula, "compound_name": "TEST ONLY"},
        "reference": {"id": identifier, "title": "TEST ONLY fixture"},
        "primary_property": {"id": 1, "name": "band gap (fundamental)"},
        "primary_unit": {"label": "eV"},
        "secondary_property": None,
        "secondary_unit": None,
        "is_experimental": experimental,
        "sample_type": "single crystal",
        "space_group": "P1",
        "computational": [] if experimental else [{"code": "TEST ONLY"}],
        "experimental": [{"method": "TEST ONLY"}] if experimental else [],
        "subsets": [
            {
                "pk": identifier,
                "label": phase,
                "crystal_system": "triclinic",
                "fixed_values": [
                    {
                        "physical_property": {"name": "temperature"},
                        "unit": {"label": "K"},
                        "formatted": "300",
                        "upper_bound": None,
                    }
                ],
                "datapoints": [
                    {"values": [{"qualifier": "primary", "formatted": str(gap)}]}
                ],
            }
        ],
    }
    records, _ = hybrid3._records(
        row,
        {},
        set(),
        hashlib.sha256(json.dumps(row).encode()).hexdigest(),
        hybrid3.API_URL,
        "2026-09-10T00:00:00Z",
    )
    assert len(records) == 1
    records[0]["source_ids"] = ["material:" + records[0]["material_id"]]
    return records[0]


def source_for(record):
    return {
        "source_id": record["source_ids"][0],
        "record_id": record["material_id"],
        "url": record["provenance"]["source_url"],
        "provenance": deepcopy(record["provenance"]),
        "access_scope": "public",
        "provenance_status": "verified",
        "source_name": "Synthetic reporting fixture only",
    }


@pytest.fixture
def comparison_report():
    evidence = [adapter_record(1, 2.0, True), adapter_record(2, 1.5, False)]
    ranked, ranking = rank_records(evidence, load_config(), importance={"band_gap": 1})
    result = {
        "stage": "complete",
        "summary": "Synthetic arithmetic fixture; not a scientific recommendation.",
        "candidates": ranked,
        "ranking": ranking,
        "comparison_records": evidence,
    }
    return {
        "id": "comparison-test-only",
        "title": "Synthetic evidence comparison rendering",
        "result": result,
        "sources": [source_for(row) for row in evidence],
    }


def _render(report):
    report["pi_summary"], report["technical_audit"] = render_reports(
        report["result"], load_config(), report["sources"]
    )
    report["references"] = citation_references(report["result"], report["sources"])
    return report["pi_summary"], report["technical_audit"]


def test_both_views_show_original_values_signed_difference_and_experimental_basis(
    comparison_report,
):
    original = deepcopy(comparison_report["result"]["comparison_records"])
    summary, technical = _render(comparison_report)
    for text in (summary, technical):
        assert "experimental 2 eV [R1]; computed 1.5 eV [R2]" in text
        assert "Computed − experimental: -0.5 eV" in text
        assert "Experimental evidence used for screening and recommendations" in text
        assert "[R1] SiO2 — public material record" in text
        assert "[R2] SiO2 — public material record" in text
        assert "test-only-computation" not in text
    assert comparison_report["result"]["comparison_records"] == original
    # Experimental and computed observations each retain their own citation.
    assert [ref["id"] for ref in comparison_report["references"]] == ["R1", "R2"]


def test_unmatched_conditions_never_show_a_delta_or_substitution(comparison_report):
    result = comparison_report["result"]
    result["comparison_records"][1] = adapter_record(2, 1.5, False, phase="other phase")
    comparison_report["sources"][1] = source_for(result["comparison_records"][1])
    result["candidates"], result["ranking"] = rank_records(
        result["comparison_records"], load_config(), importance={"band_gap": 1}
    )
    for text in _render(comparison_report):
        assert "experimental 2 eV [R1]; computed 1.5 eV [R2]" in text
        assert "Source phase label differs." in text
        assert "No direct numerical comparison" in text
        assert "values are not substituted" in text
        assert "Computed − experimental" not in text
        assert "Experimental evidence used" not in text


@pytest.mark.parametrize("role,index", [("experimental", 0), ("computed", 1)])
def test_unknown_source_method_cannot_be_reclassified_by_saved_pair(
    comparison_report, role, index
):
    result = comparison_report["result"]
    result["comparison_records"][index]["source_mode"] = "live_nomad"
    pair = result["candidates"][0]["evidence_comparison"]["comparisons"][0]
    pair[role]["source_mode"] = "live_nomad"
    with pytest.raises(ValueError, match="comparison"):
        _render(comparison_report)


def test_mismatched_source_scope_cannot_be_promoted_with_a_saved_delta(
    comparison_report,
):
    result = comparison_report["result"]
    computation = adapter_record(2, 1.5, False, phase="different source phase")
    result["comparison_records"][1] = computation
    comparison_report["sources"][1] = source_for(computation)
    result["candidates"], result["ranking"] = rank_records(
        result["comparison_records"], load_config(), importance={"band_gap": 1}
    )
    pair = result["candidates"][0]["evidence_comparison"]["comparisons"][0]
    assert pair["status"] == "not_comparable"
    pair.update(
        status="comparable",
        delta_computed_minus_experimental=-0.5,
        reasons=["Fabricated matching context"],
    )
    with pytest.raises(ValueError, match="verified source context"):
        _render(comparison_report)


def test_raw_method_or_context_edit_cannot_keep_original_source_digest(
    comparison_report,
):
    record = comparison_report["result"]["comparison_records"][1]
    record["provenance"]["raw_fields"]["is_experimental"] = True
    with pytest.raises(ValueError, match="raw fields failed validation"):
        _render(comparison_report)


@pytest.mark.parametrize(
    "experimental,phase",
    [(False, "TEST ONLY matched phase"), (True, "other phase"), (True, None)],
)
def test_experimental_range_revalidates_method_and_complete_scope(
    comparison_report, experimental, phase
):
    result = comparison_report["result"]
    extra = adapter_record(3, 3.0, experimental, phase=phase)
    result["comparison_records"].append(extra)
    comparison_report["sources"].append(source_for(extra))
    result["candidates"][0]["evidence_comparison"]["experimental_range"] = {
        "minimum": 2.0,
        "maximum": 3.0,
        "unit": "eV",
        "count": 2,
        "record_ids": [result["candidates"][0]["material_id"], extra["material_id"]],
    }
    with pytest.raises(ValueError, match="experimental scopes"):
        _render(comparison_report)


def test_verified_experimental_record_cannot_be_labelled_as_a_calculation(
    comparison_report,
):
    result = comparison_report["result"]
    replacement = adapter_record(2, 1.5, True)
    result["comparison_records"][1] = replacement
    comparison_report["sources"][1] = source_for(replacement)
    endpoint = result["candidates"][0]["evidence_comparison"]["comparisons"][0][
        "computed"
    ]
    for key in ("raw_fields_sha256", "response_sha256"):
        endpoint[key] = replacement["provenance"][key]
    with pytest.raises(ValueError, match="comparison"):
        _render(comparison_report)


def test_comparison_cannot_be_relabelled_as_another_material(comparison_report):
    comparison_report["result"]["candidates"][0]["formula"] = "TiO2"
    with pytest.raises(ValueError, match="material context"):
        _render(comparison_report)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda pair: pair["computed"].update(raw_fields_sha256="0" * 64),
        lambda pair: pair["experimental"].update(response_sha256="0" * 64),
        lambda pair: pair["computed"].update(material_id="unrelated-record"),
        lambda pair: pair["computed"].update(source_url="https://example.com/record"),
        lambda pair: pair["computed"].update(formula="TiO2"),
        lambda pair: pair["computed"].update(source_mode="live_nomad"),
        lambda pair: pair["computed"].update(value=True),
        lambda pair: pair["computed"].update(value=float("nan")),
        lambda pair: (
            pair["computed"].update(value=1.9),
            pair.update(delta_computed_minus_experimental=-0.1),
        ),
        lambda pair: pair.update(delta_computed_minus_experimental=0.5),
        lambda pair: pair.update(unit="meV"),
        lambda pair: pair.update(status="not_comparable"),
    ],
)
def test_bad_comparison_metadata_cannot_be_presented_as_evidence(
    comparison_report, mutation
):
    pair = comparison_report["result"]["candidates"][0]["evidence_comparison"][
        "comparisons"
    ][0]
    mutation(pair)
    with pytest.raises(ValueError, match="comparison"):
        _render(comparison_report)


def test_experiment_excluded_by_screening_still_reports_discrepancy(comparison_report):
    result = comparison_report["result"]
    candidate = result["candidates"].pop()
    result["ranking"]["evidence_comparisons"] = [
        {
            "material_id": candidate["material_id"],
            "formula": candidate["formula"],
            **candidate["evidence_comparison"],
        }
    ]
    for text in _render(comparison_report):
        assert "experimental 2 eV [R1]; computed 1.5 eV [R2]" in text
        assert "this material was not shortlisted" in text
        assert "[R2] SiO2 — public material record" in text
        assert (
            "Experimental evidence used for screening and recommendations" not in text
        )


def test_legacy_report_without_comparison_does_not_gain_experimental_claim(
    comparison_report,
):
    result = comparison_report["result"]
    result.pop("comparison_records")
    result["candidates"][0].pop("evidence_comparison")
    result["ranking"].pop("evidence_comparisons")
    for text in _render(comparison_report):
        assert "Experimental and computed evidence:" not in text


def test_excluded_comparison_remains_visible_beside_another_shortlisted_material(
    comparison_report,
):
    result = comparison_report["result"]
    original = result["candidates"][0]
    result["ranking"]["evidence_comparisons"] = [
        {
            "material_id": original["material_id"],
            "formula": original["formula"],
            **original["evidence_comparison"],
        }
    ]
    other = adapter_record(3, 2.0, True, formula="TiO2")
    result["candidates"], _ = rank_records(
        [other], load_config(), importance={"band_gap": 1}
    )
    comparison_report["sources"].append(source_for(other))
    for text in _render(comparison_report):
        assert "TiO2" in text
        assert "SiO2 · Band gap: experimental 2 eV [R1]" in text
        assert "this material was not shortlisted" in text
        assert (
            "Experimental evidence used for screening and recommendations" not in text
        )


def test_experimental_range_shows_source_extrema_and_does_not_invent_uncertainty(
    comparison_report,
):
    result = comparison_report["result"]
    # Different experimental subsets can share the same dataset URL.
    extra = adapter_record(3, 3.0, True, dataset_id=1)
    result["comparison_records"].append(extra)
    comparison_report["sources"].append(source_for(extra))
    metadata = result["candidates"][0]["evidence_comparison"]
    metadata["experimental_range"] = {
        "minimum": 2.0,
        "maximum": 3.0,
        "unit": "eV",
        "count": 2,
        "record_ids": [result["candidates"][0]["material_id"], extra["material_id"]],
    }
    for text in _render(comparison_report):
        assert "experimental band-gap spread: 2–3 eV [R1] [R3]" in text
        assert "Reported extrema of comparable source experiments" in text
        assert "not an uncertainty interval" in text
    metadata["experimental_range"]["maximum"] = 99
    with pytest.raises(ValueError, match="experimental spread"):
        _render(comparison_report)


def test_summary_is_compact_and_technical_retains_comparison_notes(comparison_report):
    result = comparison_report["result"]
    metadata = result["candidates"][0]["evidence_comparison"]
    for index in range(3, 6):
        other = adapter_record(index, 1.5, False)
        result["comparison_records"].append(other)
        comparison_report["sources"].append(source_for(other))
        pair = compare_observations(result["comparison_records"][0], other)
        metadata["comparisons"].append(pair)
    result["ranking"]["evidence_comparison_policy"] = {"omitted_pairs": 7}
    summary, technical = _render(comparison_report)
    assert summary.count("Computed − experimental:") == 3
    assert technical.count("Computed − experimental:") == 4
    assert "Technical Overview lists all 4 retained comparison notes" in summary
    for text in (summary, technical):
        assert "7 additional experiment/calculation pairs exceeded" in text


def test_omitted_experimental_ranges_are_disclosed_without_inventing_values(
    comparison_report,
):
    result = comparison_report["result"]
    result["candidates"][0]["evidence_comparison"]["comparisons"] = []
    result["comparison_records"] = []
    result["ranking"]["evidence_comparisons"] = []
    result["ranking"]["evidence_comparison_policy"] = {"omitted_experimental_ranges": 6}
    for text in _render(comparison_report):
        assert (
            "6 experimental ranges exceeded the supporting-record display limit" in text
        )
        assert "All supplied experiments still informed screening" in text
        assert "experimental band-gap spread:" not in text
        assert "Computed − experimental:" not in text
