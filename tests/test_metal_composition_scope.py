"""Generic alloy versus elemental scope; synthetic transport records
only."""

from copy import deepcopy

import pytest

from labcat import public_sources, science
from labcat.science.preferences import (
    derive_search_filters,
    matches_composition_scope,
    validate_search_filters,
)


@pytest.mark.parametrize(
    "prompt, scope",
    [
        ("Find low-density structural alloys", "multi_element"),
        ("Find stable metal alloys for engineering", "multi_element"),
        ("Research Fe-Ni alloys", "multi_element"),
        ("Find pure metals for contacts", "single_element"),
        ("Find elemental metals for heat conduction", "single_element"),
        ("Find single-element metals", "single_element"),
        ("Find unalloyed metals", "single_element"),
        ("Find metals that are pure", "single_element"),
        ("Find pure metals, not alloys", "single_element"),
        ("Find alloys rather than pure metals", "multi_element"),
        ("Find metals, not alloys", None),
        ("Find metals with no alloys", None),
        ("Find metals; avoid alloys", None),
        ("Find metals; do not include alloys", None),
        ("Find alloy-free metals", None),
        ("Compare pure metals and alloys", None),
        ("Find metals", None),
        ("Find metallic candidates", None),
    ],
)
def test_explicit_metal_scope_is_separate_from_general_metallicity(prompt, scope):
    filters = derive_search_filters(prompt)
    assert filters.get("composition_scope") == scope
    assert validate_search_filters(filters) == filters


def test_combined_metal_profile_does_not_assume_alloys_or_pure_elements():
    assert derive_search_filters(
        "Find structural candidates", "metals_metal_alloys"
    ) == {"is_metal": "true"}


def test_explicit_formula_and_system_hints_are_preserved():
    assert derive_search_filters("Compare Fe-Ni and Co-Ni alloys") == {
        "chemsys": "Co-Ni,Fe-Ni",
        "composition_scope": "multi_element",
    }
    assert derive_search_filters("Compare Fe and Cu pure metals") == {
        "formula": "Fe,Cu",
        "composition_scope": "single_element",
    }


@pytest.mark.parametrize(
    "scope, accepted, rejected",
    [
        ("multi_element", ["FeNi", "Cu0.5Zn0.5", "AlCoCrFeNi"], ["Fe", "Cu4"]),
        ("single_element", ["Fe", "Cu4"], ["FeNi", "Cu0.5Zn0.5"]),
    ],
)
def test_scope_checks_distinct_elements_without_hardcoded_candidate_names(
    scope, accepted, rejected
):
    assert all(matches_composition_scope(formula, scope) for formula in accepted)
    assert not any(matches_composition_scope(formula, scope) for formula in rejected)
    assert all(
        public_sources._matches_composition(formula, {"composition_scope": scope})
        for formula in accepted
    )
    assert not any(
        public_sources._matches_composition(formula, {"composition_scope": scope})
        for formula in rejected
    )


def test_unsupported_scope_cannot_reach_adapters():
    with pytest.raises(ValueError, match="composition scope"):
        validate_search_filters({"composition_scope": "predetermined_materials"})


@pytest.mark.parametrize(
    "scope, formulas",
    [
        ("multi_element", ["FeNi"]),
        ("single_element", ["Fe"]),
        (None, ["Fe", "FeNi"]),
    ],
)
def test_non_mp_adapter_strips_internal_scope_and_postfilters_validated_rows(
    monkeypatch, scope, formulas
):
    records, _ = science.load_snapshot()
    raw = deepcopy(records[:2])
    for record, formula, elements in zip(
        raw, ["Fe", "FeNi"], [["Fe"], ["Fe", "Ni"]], strict=True
    ):
        record.update(formula=formula, elements=elements)
    calls = []
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda filters: (calls.append(filters) or raw, {})
    )
    filters = {"composition_scope": scope} if scope else {}
    result, metadata = science._retrieve_repositories(
        filters,
        mp_api_key=None,
        mode="auto",
        allow_nomad=True,
    )
    assert calls == [{}]
    assert [record["formula"] for record in result] == formulas
    if scope:
        screen = metadata["repository_attempts"][0]["provenance"][
            "composition_scope_screen"
        ]
        assert screen["scope"] == scope and screen["records_removed"] == 1
