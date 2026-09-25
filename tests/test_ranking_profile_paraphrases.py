"""Independent preference-only paraphrases, not evidence or held-out
examples."""

import json
from copy import deepcopy

import pytest

from labcat.ranking_profiles import (
    PRESETS,
    RankingProfileStore,
    normalize_importance,
)
from labcat.workspace import WorkspaceStore


@pytest.fixture
def profiles(tmp_path):
    store = RankingProfileStore(WorkspaceStore(tmp_path / "preferences.sqlite3"))
    store.initialize()
    return store


@pytest.mark.parametrize(
    "subject,material_class,application,criterion",
    [
        (
            "oxide perovskites with high permittivity for capacitor coatings",
            "perovskites",
            "high_k_screening",
            "dielectric_total",
        ),
        (
            "halide perovskites as solar absorbers",
            "perovskites",
            "optoelectronics",
            "direct_gap",
        ),
        (
            "metallic candidates with high bulk modulus",
            "metals_metal_alloys",
            "stiffness",
            "bulk_modulus",
        ),
        (
            "multi-principal-element alloys with high shear modulus",
            "high_entropy_alloys",
            "stiffness",
            "shear_modulus",
        ),
        (
            "organic solar cells made with solution-processable materials",
            "organic_electronic_materials",
            "optoelectronics",
            "solution_processability",
        ),
        (
            "quantum-dot emitters for light-emitting devices",
            "semiconductor_nanocrystals",
            "optoelectronics",
            "direct_gap",
        ),
        (
            "polymers as thin films with low density",
            "polymers",
            "property_exploration",
            "density",
        ),
        (
            "ceramics with high elastic modulus",
            "structural_ceramics",
            "stiffness",
            "bulk_modulus",
        ),
        (
            "monolayer semiconductors for photodetection",
            "two_dimensional_materials",
            "optoelectronics",
            "direct_gap",
        ),
        (
            "metal–organic frameworks with simple compositions",
            "mofs",
            "property_exploration",
            "simplicity",
        ),
    ],
)
@pytest.mark.parametrize(
    "opening", ["Identify candidates among", "Shortlist", "Assess"]
)
def test_cross_class_requests_select_relevant_priorities_without_saved_changes(
    profiles, opening, subject, material_class, application, criterion
):
    before = profiles.list()
    selected, decision = profiles.select("infer", f"{opening} {subject}.")
    assert decision["mode"] == "inferred"
    assert selected["material_class"] == material_class
    assert selected["application"] == application
    assert selected["importance"][criterion] > 0
    for scope in ("stability", "ambient_phase_stability", "operational_stability"):
        assert selected["importance"][scope] >= 0.3
    if application != "high_k_screening":
        expected_gap = (
            0.9
            if material_class == "perovskites" and application == "optoelectronics"
            else 0
        )
        assert selected["importance"].get("band_gap", 0) == expected_gap
        assert selected["importance"].get("dielectric_total", 0) == 0
        assert selected.get("minimum_band_gap_ev") is None
    assert selected["normalized_weights"] == normalize_importance(
        selected["importance"]
    )
    assert profiles.list() == before
    assert not {"sources", "candidates", "band_gap_ev"} & selected.keys()


@pytest.mark.parametrize("subject", ["perovskites", "polymers", "MOFs", "quantum dots"])
def test_film_geometry_does_not_impose_an_insulating_band_gap(profiles, subject):
    selected, decision = profiles.select("infer", f"Explore {subject} in thin films.")
    assert decision["mode"] == "inferred"
    assert selected["application"] == "property_exploration"
    assert selected["importance"].get("band_gap", 0) == 0
    explicit, _ = profiles.select(
        "infer", f"Explore {subject} for thin-film insulation."
    )
    assert explicit["application"] == "thin_film_insulation"
    assert explicit["importance"]["band_gap"] > 0


@pytest.mark.parametrize(
    "criterion,attribute",
    [
        ("room-temperature phase stability", "ambient_phase_stability"),
        ("stable under illumination", "operational_stability"),
        ("wide band gaps", "band_gap"),
        ("large dielectric response", "dielectric_total"),
        ("fewer distinct elements", "simplicity"),
        ("non-toxic elements", "element_screen"),
        ("direct band gap", "direct_gap"),
    ],
)
def test_explicit_criterion_goals_remain_preferences_with_no_material_facts(
    profiles, criterion, attribute
):
    selected, decision = profiles.select(
        "infer", f"Find perovskites. Prefer {criterion}."
    )
    assert selected["importance"][attribute] >= 0.5
    assert attribute in {
        item["attribute"] for item in decision["preference_adjustments"]
    }
    assert selected.get("target_band_gap_ev") is None
    assert not {"sources", "candidates", "band_gap_ev"} & selected.keys()


@pytest.mark.parametrize(
    "suffix",
    [
        "Do not prioritize wide band gaps.",
        "Wide band gaps are not required.",
        "A paper reports wide band gaps and high permittivity in oxide dielectrics.",
        "According to literature, semiconductor photodetectors need wide band gaps.",
        "https://example.invalid/oxide-dielectrics/high-permittivity",
    ],
)
def test_negation_and_source_claims_do_not_change_class_or_criteria(profiles, suffix):
    baseline, _ = profiles.select("infer", "Find polymers.")
    selected, decision = profiles.select("infer", f"Find polymers. {suffix}")
    assert selected == baseline
    assert "preference_adjustments" not in decision


@pytest.mark.parametrize(
    "prompt,expected_class",
    [
        ("Find polymers, not oxide ceramics.", "polymers"),
        ("Find quantum dots rather than semiconductors.", "semiconductor_nanocrystals"),
        ("Find alloys, excluding metal-organic frameworks.", "metals_metal_alloys"),
        ("Find 2D semiconductors, not metal alloys.", "two_dimensional_materials"),
        ("Find perovskite oxide ceramics with high permittivity.", "perovskites"),
        ("Find oxide dielectric perovskites for thin films.", "perovskites"),
    ],
)
def test_excluded_class_hints_do_not_override_requested_scope(
    profiles, prompt, expected_class
):
    selected, decision = profiles.select("infer", prompt)
    assert decision["mode"] == "inferred"
    assert selected["material_class"] == expected_class


@pytest.mark.parametrize(
    "prompt",
    [
        "Compare semiconductors and perovskites for solar absorption.",
        "Compare perovskites versus semiconductors for photodetection.",
        "Compare two-dimensional materials and metal alloys.",
        "Compare oxide ceramics and perovskites with high permittivity.",
    ],
)
def test_cross_family_comparisons_keep_the_explicit_ambiguity(profiles, prompt):
    selected, decision = profiles.select("infer", prompt)
    assert selected == profiles.active()
    assert decision["mode"] == "fallback"


def test_optical_defaults_need_a_gap_goal_but_explicit_preferences_survive(profiles):
    prompt = "Find organic solar cell materials."
    selected, _ = profiles.select("infer", prompt)
    assert selected["importance"]["band_gap"] == 0
    assert selected["importance"]["direct_gap"] == 0
    for goal in ("Prefer a wide band gap.", "Target a 1.6 eV band gap."):
        targeted, _ = profiles.select("infer", f"{prompt} {goal}")
        assert targeted["importance"]["band_gap"] > 0
    custom = profiles.create(
        {
            "name": "Explicit optical priorities",
            "material_class": "organic_electronic_materials",
            "application": "optoelectronics",
            "importance": {"band_gap": 0.9, "direct_gap": 0.7, "stability": 0.4},
        }
    )
    assert profiles.select("infer", prompt)[0] == custom
    profiles.activate(custom["id"])
    assert (
        profiles.select(None, "Find polymers with a band gap around 2 eV.")[0] == custom
    )
    assert profiles.select(custom["id"], "Find metallic candidates.")[0] == custom


@pytest.mark.parametrize("change", [None, "name", "weight", "order", "custom"])
def test_optical_default_upgrade_preserves_explicit_edits_and_repeated_initialization(
    profiles, change
):
    identifier = "preset-semiconductor-optoelectronics"
    previous = deepcopy(dict(PRESETS)[identifier])
    previous["importance"]["band_gap"] = 0.5
    if change == "name":
        previous["name"] = "Saved optical screen"
    elif change == "weight":
        previous["importance"]["direct_gap"] = 0.2
    elif change == "order":
        previous["importance"] = dict(reversed(list(previous["importance"].items())))
    if change == "custom":
        identifier = profiles.create(previous)["id"]
    else:
        with profiles.workspace._connection(write=True) as connection:
            connection.execute(
                "UPDATE ranking_profiles SET value=? WHERE id=?",
                (json.dumps(previous), identifier),
            )
    profiles.activate(identifier)
    before = profiles.active()
    profiles.initialize()
    after = profiles.active()
    if change is None:
        assert after["importance"]["band_gap"] == 0
        assert after["created_at"] == before["created_at"]
        assert after["id"] == before["id"]
    else:
        assert after == before
    profiles.initialize()
    assert profiles.active() == after


@pytest.mark.parametrize(
    "suffix",
    [
        "Do not prioritize high permittivity.",
        "High permittivity is not required.",
        "A paper reports insulation applications.",
        "Do not use any oxide dielectrics.",
        "Exclude all structural ceramics.",
    ],
)
def test_negated_and_claimed_applications_do_not_impose_insulation(profiles, suffix):
    baseline, _ = profiles.select("infer", "Find polymers in thin films.")
    selected, decision = profiles.select(
        "infer", f"Find polymers in thin films. {suffix}"
    )
    assert selected == baseline
    assert decision["mode"] == "inferred"
    assert "preference_adjustments" not in decision


@pytest.mark.parametrize(
    "goal",
    [
        "Do not target a 1.6 eV band gap.",
        "Do not require a band gap at least 3 eV.",
        "A band gap around 1.6 eV is not required.",
        "Do not prioritize a wide band gap.",
    ],
)
def test_negated_gap_targets_do_not_change_optical_defaults(profiles, goal):
    baseline, _ = profiles.select("infer", "Find perovskites for photodetection.")
    selected, decision = profiles.select(
        "infer", f"Find perovskites for photodetection. {goal}"
    )
    assert selected == baseline
    assert "preference_adjustments" not in decision
