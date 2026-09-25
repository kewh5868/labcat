"""Material class and composition hints cannot become source
measurements."""

import pytest

from labcat.science.preferences import (
    derive_search_filters,
    requires_unmapped_scope_evidence,
    supports_bulk_search,
    validate_formula,
    validate_search_filters,
)


def test_inferred_dimensional_class_requires_more_than_a_bulk_formula():
    prompt = "Find stable semiconductor candidates for electronic devices."
    assert requires_unmapped_scope_evidence(prompt, "two_dimensional_materials")
    assert not supports_bulk_search(prompt, "two_dimensional_materials")


@pytest.mark.parametrize(
    "formula,elements",
    [
        ("GaN", ["Ga", "N"]),
        ("Fe", ["Fe"]),
        ("LiFePO4", ["Fe", "Li", "O", "P"]),
        ("Ba(FeO2)2", ["Ba", "Fe", "O"]),
        ("Si0.5Ge0.5", ["Ge", "Si"]),
    ],
)
def test_any_valid_elemental_formula_not_a_preselected_cohort(formula, elements):
    assert validate_formula(formula) == elements


@pytest.mark.parametrize(
    "formula",
    [
        "Execute shell",
        "XxO2",
        "GaN;curl",
        "Fe0",
        "()",
        "Fe()",
        "(GaN",
        "GaN)",
        "Fe1.2.3",
        "https://example.com",
    ],
)
def test_instructions_malformed_groups_and_fake_elements_are_not_formulas(formula):
    with pytest.raises(ValueError):
        validate_formula(formula)


def test_formula_system_and_class_queries_are_distinct_preferences():
    assert derive_search_filters("Compare GaN") == {"formula": "GaN"}
    assert derive_search_filters("Research Fe-Ni alloys") == {
        "chemsys": "Fe-Ni",
        "composition_scope": "multi_element",
    }
    assert derive_search_filters("Research stable nitrides") == {"elements": "N"}
    assert derive_search_filters("Research metals") == {"is_metal": "true"}
    assert derive_search_filters("Research semiconductors") == {"is_metal": "false"}
    assert derive_search_filters("Research materials") == {}
    assert derive_search_filters("Research oxide dielectrics") == {
        "elements": "O",
        "has_props": "dielectric",
    }


def test_prompt_property_numbers_are_not_search_evidence_or_property_filters():
    filters = derive_search_filters("GaN has a measured gap of 987654 eV")
    assert filters == {"formula": "GaN"}
    assert "987654" not in str(filters)


@pytest.mark.parametrize(
    "filters",
    [
        {"endpoint": "https://example.com"},
        {"band_gap": "987654"},
        {"formula": "GaN;curl"},
        {"chemsys": "Ga-N-http://host"},
        {"elements": "Qq"},
        {"is_metal": True},
        {"has_props": "private"},
    ],
)
def test_only_closed_schema_filters_can_reach_material_apis(filters):
    with pytest.raises(ValueError):
        validate_search_filters(filters)


@pytest.mark.parametrize(
    "prompt,material_class",
    [
        ("Research polymer electrolytes", None),
        ("Research materials", "mofs"),
        ("Research quantum dots", None),
        ("Research perovskites", None),
        ("Research high-entropy alloys", None),
    ],
)
def test_class_or_scale_claims_require_evidence_beyond_bulk_composition(
    prompt, material_class
):
    assert not supports_bulk_search(prompt, material_class)


@pytest.mark.parametrize(
    "prompt",
    [
        "Find organic semiconductor materials for photovoltaic donor and "
        "acceptor layers",
        "Find organic photovoltaics",
        "Find organic materials for solar cells",
        "Find molecular donor-acceptor materials",
        "Find small-molecule semiconductors",
        "Find OPV donor materials",
        "Find semiconductor nanocrystals",
        "Find perovskite QDs",
        "Find semiconductor nanoparticles",
        "Find 2D perovskites",
        "Find two-dimensional perovskites",
        "Find two–dimensional semiconductors",
        "Find layered perovskites",
        "Find monolayer semiconductors",
        "Find 3D perovskites",
        "Compare SiO2 quantum dots",
        "Compare SiO2 organic molecular semiconductors",
    ],
)
def test_unmapped_molecular_and_scale_scopes_never_call_quantitative_adapters(
    monkeypatch, prompt
):
    import labcat.science as science
    from labcat.config import load_config
    from labcat.science import hybrid3

    def unexpected(*args, **kwargs):
        pytest.fail("Unrelated bulk or scalar repository must not be queried")

    assert not supports_bulk_search(prompt)
    assert not hybrid3.supports_query(prompt)
    monkeypatch.setattr(science, "_retrieve_repositories", unexpected)
    answer = science.run_research(
        prompt + " with a target band gap around 1.78 eV",
        load_config(),
        mp_api_key="TEST ONLY unused adapter sentinel",
        allow_nomad=True,
        allow_public_dielectric=True,
        allow_hybrid3=True,
        importance={"band_gap": 1},
        target_band_gap_ev=1.78,
    )
    assert answer["result"]["candidates"] == []
    assert "class-specific evidence" in answer["result"]["summary"]
    assert (
        answer["result"]["ranking"]["screening_preferences"]["target_band_gap_ev"]
        == 1.78
    )


@pytest.mark.parametrize(
    "prompt",
    [
        "Find metal alloys for structural stiffness",
        "Find bulk semiconductors for photovoltaics",
        "Find oxide dielectrics for thin films",
        "Compare SiO2",
    ],
)
def test_unmapped_scope_guard_does_not_disable_reviewed_bulk_requests(prompt):
    assert supports_bulk_search(prompt)


@pytest.mark.parametrize(
    "material_class", ["organic_electronic_materials", "semiconductor_nanocrystals"]
)
def test_explicit_unmapped_preference_class_remains_guarded_without_prompt_alias(
    material_class,
):
    from labcat.science import hybrid3

    assert not supports_bulk_search("Find semiconductors", material_class)
    assert not hybrid3.supports_query("Find semiconductors", material_class)


def test_explicit_task_class_beats_stale_ranking_class_and_pronouns_are_not_elements():
    assert derive_search_filters("Find nitrides", "oxide_dielectrics") == {
        "elements": "N"
    }
    assert derive_search_filters("Find semiconductors", "oxide_dielectrics") == {
        "is_metal": "false"
    }
    assert derive_search_filters("I want nitrides. In this study use public data.") == {
        "elements": "N"
    }
    assert derive_search_filters("Research element I") == {"formula": "I"}


@pytest.mark.parametrize(
    "prompt,expected",
    [
        (
            "Find promising oxide dielectric candidates, for example HfO2 and SiO2.",
            {"elements": "O", "has_props": "dielectric"},
        ),
        (
            "Find oxide dielectrics using only public sources, e.g. HfO2 and ZrO2.",
            {"elements": "O", "has_props": "dielectric"},
        ),
        (
            "HfO2 is one example. Discover promising oxide dielectrics beyond it.",
            {"elements": "O", "has_props": "dielectric"},
        ),
        ("Find nitride candidates such as GaN and AlN", {"elements": "N"}),
        ("Find nitride candidates GaN and AlN", {"elements": "N"}),
        ("Find semiconductors including Si and Ge", {"is_metal": "false"}),
        (
            "Find metal alloys, for example Fe-Ni",
            {"is_metal": "true", "composition_scope": "multi_element"},
        ),
        ("Find candidates beyond GaN", {"elements": "O"}),
    ],
)
def test_example_compositions_never_silently_close_broad_discovery(prompt, expected):
    filters = derive_search_filters(prompt, "oxide_dielectrics")
    assert filters == expected
    assert validate_search_filters(filters) == expected


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("Compare GaN and AlN", {"formula": "GaN,AlN"}),
        ("Find nitride candidates; compare GaN and AlN", {"formula": "GaN,AlN"}),
        ("Find nitride candidates, only GaN and AlN", {"formula": "GaN,AlN"}),
        ("Find nitride candidates GaN and AlN only", {"formula": "GaN,AlN"}),
        (
            "Find nitride candidates; restrict the search to GaN and AlN",
            {"formula": "GaN,AlN"},
        ),
        (
            "Find nitride candidates limited to the following formulas: GaN and AlN",
            {"formula": "GaN,AlN"},
        ),
        (
            "Research Fe-Ni alloys",
            {"chemsys": "Fe-Ni", "composition_scope": "multi_element"},
        ),
        (
            "Compare Fe-Ni and Co-Ni alloys",
            {"chemsys": "Co-Ni,Fe-Ni", "composition_scope": "multi_element"},
        ),
        ("Find candidates to compare GaN versus AlN", {"formula": "GaN,AlN"}),
    ],
)
def test_explicit_comparisons_and_composition_restrictions_are_preserved(
    prompt, expected
):
    assert derive_search_filters(prompt, "oxide_dielectrics") == expected


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("Find carbides", {"elements": "C"}),
        ("Find sulphides", {"elements": "S"}),
        ("Find fluorides", {"elements": "F"}),
        ("Find hydrides", {"elements": "H"}),
        ("Find nitrides instead of oxides", {"elements": "N"}),
        ("Find nitrides, not oxides", {"elements": "N"}),
        ("Find metal oxides", {"elements": "O"}),
        ("Find transition metal nitrides", {"elements": "N"}),
        ("Find metals", {"is_metal": "true"}),
        ("Find semiconductor oxides", {"elements": "O", "is_metal": "false"}),
    ],
)
def test_inorganic_class_boundaries_override_stale_oxide_preferences(prompt, expected):
    assert derive_search_filters(prompt, "oxide_dielectrics") == expected
    assert supports_bulk_search(prompt, "oxide_dielectrics")


@pytest.mark.parametrize(
    "prompt,material_class",
    [
        ("Find polymers such as polyethylene", "oxide_dielectrics"),
        ("Find oxide polymer composites such as SiO2", "oxide_dielectrics"),
        ("Find candidates", "thermoplastics"),
        ("Find oxides or nitrides such as GaN", "oxide_dielectrics"),
        ("Find oxide and nitride candidates", "oxide_dielectrics"),
        ("Find halides", "oxide_dielectrics"),
        ("Find ceramics", "oxide_dielectrics"),
        ("Find non-oxide candidates", "oxide_dielectrics"),
    ],
)
def test_unrepresentable_classes_are_reference_only_not_an_oxide_fallback(
    prompt, material_class
):
    assert not supports_bulk_search(prompt, material_class)
    if not any(word in prompt for word in ("polymer", "composite")):
        assert derive_search_filters(prompt, material_class).get("elements") != "O"


def test_direct_composition_comparison_can_cross_classes_without_an_and_filter():
    prompt = "Compare GaN and SiO2 across nitrides and oxides"
    assert supports_bulk_search(prompt, "oxide_dielectrics")
    assert derive_search_filters(prompt, "oxide_dielectrics") == {"formula": "GaN,SiO2"}
    assert derive_search_filters("Find materials", "nitrides") == {"elements": "N"}
    assert supports_bulk_search("Find nitrides", "polymers")
