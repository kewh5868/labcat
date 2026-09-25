"""Saved preferences cannot supply scientific facts or loosen fixed
policy."""

import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from labcat.config import load_config
from labcat.ranking_profiles import (
    DEFAULT_PROFILE_ID,
    PRESETS,
    SUPPORTED_ATTRIBUTES,
    RankingProfileNotFound,
    RankingProfileStore,
    catalog,
    create_ranking_profiles_router,
    normalize_importance,
)
from labcat.workspace import WorkspaceStore


@pytest.fixture
def store(tmp_path):
    profiles = RankingProfileStore(WorkspaceStore(tmp_path / "workspace.sqlite3"))
    profiles.initialize()
    return profiles


def custom(**kwargs):
    return {
        "name": "My priorities",
        "material_class": "oxide_dielectrics",
        "application": "thin_film_insulation",
        "importance": {"band_gap": 1, "dielectric_total": 1, "stability": 0.2},
        **kwargs,
    }


def test_catalog_discloses_available_scoring_and_exploratory_scopes():
    from labcat.science.ranking import SUPPORTED_CRITERIA

    data = catalog()
    assert SUPPORTED_ATTRIBUTES == SUPPORTED_CRITERIA
    assert {
        item["id"] for item in data["attributes"] if item["supported"]
    } == SUPPORTED_ATTRIBUTES
    fields = {item["id"]: item["source_field"] for item in data["attributes"]}
    assert fields["dielectric_total"] == "e_total"
    assert fields["dielectric_electronic"] == "e_electronic"
    assert fields["bulk_modulus"] == "bulk_modulus"
    assert fields["direct_gap"] == "is_gap_direct"
    assert fields["nsites"] == "nsites"
    mechanical = [
        item for item in data["attributes"] if item["category"] == "Mechanical"
    ]
    assert {item["id"] for item in mechanical if item["supported"]} == {
        "bulk_modulus",
        "shear_modulus",
    }
    assert all("cited passages" in item["availability_note"] for item in mechanical)
    assert all(
        "No numeric scoring rule" in item["availability_note"]
        for item in mechanical
        if not item["supported"]
    )
    assert "Public discovery" in data["material_classes"][1]["scope"]
    assert all("oxide-only" not in item["scope"] for item in data["material_classes"])
    data["attributes"][0]["label"] = "mutated"
    assert catalog()["attributes"][0]["label"] != "mutated"


def test_new_workspace_defaults_to_existing_high_k_preset(store):
    data = store.list()
    assert len(data["profiles"]) == len(PRESETS)
    assert data["active_profile_id"] == DEFAULT_PROFILE_ID == "preset-oxide-high-k"
    active = store.active()
    expected = dict(PRESETS)["preset-oxide-high-k"]
    assert active["name"] == "Oxide dielectrics · High-k screening"
    assert active["material_class"] == "oxide_dielectrics"
    assert active["application"] == "high_k_screening"
    assert active["minimum_band_gap_ev"] == 2.0
    assert active["importance"] == expected["importance"]
    assert active["normalized_weights"] == normalize_importance(expected["importance"])
    assert all(profile["preset"] for profile in data["profiles"])


def earlier_high_k_default():
    """Exact old shipped preference state; never a scientific
    benchmark."""
    return {
        "name": "Oxide dielectrics · High-k screening",
        "material_class": "oxide_dielectrics",
        "application": "high_k_screening",
        "importance": {
            "stability": 0.5,
            "band_gap": 0.5,
            "dielectric_total": 1.0,
            "dielectric_electronic": 0.4,
            "element_screen": 0.3,
            "simplicity": 0.2,
            "evidence_quality": 0.5,
        },
    }


def test_old_high_k_migrates_once_preserving_selection_and_creation_date(store):
    selected = "preset-oxide-thin-film"
    store.activate(selected)
    with store.workspace._connection(write=True) as connection:
        connection.execute(
            "UPDATE ranking_profiles SET value=?,updated_at=? WHERE id=?",
            (
                json.dumps(earlier_high_k_default()),
                "old-version-timestamp",
                DEFAULT_PROFILE_ID,
            ),
        )
    before = next(
        profile
        for profile in store.list()["profiles"]
        if profile["id"] == DEFAULT_PROFILE_ID
    )
    store.initialize()
    after = next(
        profile
        for profile in store.list()["profiles"]
        if profile["id"] == DEFAULT_PROFILE_ID
    )
    assert after["importance"] == {
        "stability": 0.5,
        "band_gap": 0.6,
        "dielectric_total": 1.0,
        "dielectric_electronic": 0.0,
        "element_screen": 0.3,
        "simplicity": 0.2,
        "evidence_quality": 0.0,
        "ambient_phase_stability": 0.3,
        "operational_stability": 0.3,
    }
    assert after["minimum_band_gap_ev"] == 2.0
    assert after["created_at"] == before["created_at"]
    assert after["updated_at"] != before["updated_at"]
    assert store.active()["id"] == selected
    store.initialize()
    assert (
        next(
            profile
            for profile in store.list()["profiles"]
            if profile["id"] == DEFAULT_PROFILE_ID
        )
        == after
    )


@pytest.mark.parametrize(
    "change", ["name", "application", "class", "weight", "order", "custom"]
)
def test_high_k_upgrade_preserves_edits_and_custom_copies(store, change):
    previous = earlier_high_k_default()
    if change == "name":
        previous["name"] = "My adjusted high-k screen"
    elif change == "application":
        previous["application"] = "Custom screening"
    elif change == "class":
        previous["material_class"] = "My oxide scope"
    elif change == "weight":
        previous["importance"]["band_gap"] = 0.55
    elif change == "order":
        previous["importance"] = dict(reversed(list(previous["importance"].items())))
    if change == "custom":
        created = store.create(previous)
        identifier = created["id"]
    else:
        identifier = DEFAULT_PROFILE_ID
        with store.workspace._connection(write=True) as connection:
            connection.execute(
                "UPDATE ranking_profiles SET value=? WHERE id=?",
                (json.dumps(previous), identifier),
            )
    store.activate(identifier)
    before = store.active()
    store.initialize()
    assert store.active() == before


@pytest.mark.parametrize("minimum", [None, 0, 0.1, 2.0, 100])
def test_optional_gap_preference_roundtrips_without_becoming_source_evidence(
    store, minimum
):
    made = store.create(custom(minimum_band_gap_ev=minimum))
    store.activate(made["id"])
    store.initialize()
    assert store.active()["minimum_band_gap_ev"] == minimum
    assert store.active()["importance"] == made["importance"]


@pytest.mark.parametrize(
    "minimum", [True, False, "2", -0.1, 100.1, float("nan"), float("inf"), {}, 10**500]
)
def test_invalid_gap_preference_rejected_without_writing_profile(store, minimum):
    before = store.list()
    with pytest.raises(ValueError, match="Minimum band gap"):
        store.create(custom(minimum_band_gap_ev=minimum))
    assert store.list() == before


def test_old_custom_profile_keeps_gap_preference_absent(store):
    made = store.create(custom())
    store.activate(made["id"])
    store.initialize()
    assert "minimum_band_gap_ev" not in store.active()
    assert "minimum_band_gap_ev" not in dict(PRESETS)["preset-oxide-thin-film"]
    assert "minimum_band_gap_ev" not in dict(PRESETS)["preset-ceramic-stiffness"]


@pytest.mark.parametrize(
    "variant", ["intermediate", "disabled", "edited_minimum", "invalid_boolean"]
)
def test_gap_upgrade_handles_intermediate_preset_and_preserves_explicit_changes(
    store, variant
):
    value = dict(PRESETS)[DEFAULT_PROFILE_ID].copy()
    value["importance"] = value["importance"].copy()
    value.pop("minimum_band_gap_ev")
    if variant == "disabled":
        value["minimum_band_gap_ev"] = None
    elif variant == "edited_minimum":
        value["minimum_band_gap_ev"] = 1.5
    elif variant == "invalid_boolean":
        value["importance"]["dielectric_electronic"] = False
    with store.workspace._connection(write=True) as connection:
        connection.execute(
            "UPDATE ranking_profiles SET value=? WHERE id=?",
            (json.dumps(value), DEFAULT_PROFILE_ID),
        )
    store.initialize()
    if variant == "invalid_boolean":
        with pytest.raises(sqlite3.DatabaseError):
            store.active()
        with store.workspace._connection() as connection:
            saved = connection.execute(
                "SELECT value FROM ranking_profiles WHERE id=?", (DEFAULT_PROFILE_ID,)
            ).fetchone()[0]
        assert json.loads(saved) == value
    elif variant == "intermediate":
        assert store.active()["minimum_band_gap_ev"] == 2.0
    else:
        assert store.active()["minimum_band_gap_ev"] == value["minimum_band_gap_ev"]


def test_profile_migration_preserves_saved_report_and_frozen_pin_preferences(store):
    previous = earlier_high_k_default()
    with store.workspace._connection(write=True) as connection:
        connection.execute(
            "UPDATE ranking_profiles SET value=? WHERE id=?",
            (json.dumps(previous), DEFAULT_PROFILE_ID),
        )
    project = store.workspace.create_project("Migration fixture project")
    chat = store.workspace.project_draft(project["id"])
    detail = store.workspace.append_research(
        chat["id"],
        project["id"],
        "Fixture request; no material evidence",
        {
            "stage": "partial",
            "answer": "Fixture response without scientific claims",
            "pi_summary": "Fixture summary",
            "technical_audit": "Fixture technical document",
            "sources": [],
            "result": {
                "stage": "partial",
                "execution": {
                    "ranking_profile": {"id": DEFAULT_PROFILE_ID, **previous}
                },
                "ranking": {"algorithm": "public-materials-utility-v4"},
            },
        },
    )
    store.workspace.set_pin(project["id"], "report", detail["reports"][-1]["id"])
    before = store.workspace.contents(project["id"])
    store.initialize()
    assert store.active()["minimum_band_gap_ev"] == 2.0
    assert store.workspace.contents(project["id"]) == before
    assert (
        "minimum_band_gap_ev"
        not in before["reports"][0]["result"]["execution"]["ranking_profile"]
    )


def test_unchanged_legacy_config_uses_new_first_run_default(tmp_path):
    profiles = RankingProfileStore(WorkspaceStore(tmp_path / "first-run.sqlite3"))
    profiles.initialize(legacy_importance=load_config().to_dict()["ranking"])
    assert profiles.active()["id"] == "preset-oxide-high-k"
    assert "migrated-ranking-preferences" not in {
        item["id"] for item in profiles.list()["profiles"]
    }


@pytest.mark.parametrize(
    "selected", ["preset-oxide-thin-film", "preset-liquid-crystals-exploration"]
)
def test_existing_preset_choice_survives_new_default_on_restart(store, selected):
    store.activate(selected)
    before = store.active()
    restarted = RankingProfileStore(store.workspace)
    restarted.initialize(legacy_importance=load_config().to_dict()["ranking"])
    assert restarted.active() == before


def test_independent_importance_normalizes_without_dropping_unsupported_weights():
    result = normalize_importance({"band_gap": 1, "bulk_modulus": 1, "stability": 0})
    assert result == {"band_gap": 0.5, "bulk_modulus": 0.5, "stability": 0}
    assert sum(result.values()) == pytest.approx(1)


def test_create_save_activate_edit_and_restart_preserve_profile(store):
    made = store.create(custom())
    assert made["preset"] is False
    assert store.active()["id"] == DEFAULT_PROFILE_ID
    store.activate(made["id"])
    changed = custom(
        name="Updated priorities",
        importance={"bulk_modulus": 0.8, "shear_modulus": 0.9},
    )
    updated = store.update(made["id"], changed)
    assert updated["id"] == made["id"]
    assert updated["created_at"] == made["created_at"]
    assert store.active()["importance"] == changed["importance"]
    restarted = RankingProfileStore(store.workspace)
    restarted.initialize()
    assert restarted.active()["id"] == made["id"]
    assert restarted.active()["importance"] == changed["importance"]


def test_presets_are_copied_into_custom_profiles_not_modified_in_place(store):
    with pytest.raises(ValueError, match="custom copy"):
        store.update(DEFAULT_PROFILE_ID, custom())
    before = store.active()
    made = store.create(
        {
            key: before[key]
            for key in ("name", "material_class", "application", "importance")
        }
    )
    assert made["id"] != before["id"]
    assert made["preset"] is False
    assert store.active() == before


@pytest.mark.parametrize(
    "importance",
    [
        {},
        {"band_gap": 0},
        {"band_gap": -0.1},
        {"band_gap": 1.1},
        {"band_gap": True},
        {"band_gap": "0.5"},
        {"band_gap": float("nan")},
        {"band_gap": float("inf")},
        {"band_gap": 10**500},
        {"band_gap": 0.5, "enable_private_data": 0.5},
        {"band_gap": {"value": 7.0, "source": "user"}},
    ],
)
def test_invalid_importance_never_changes_the_active_profile(store, importance):
    before = store.active()
    with pytest.raises(ValueError):
        store.create(custom(importance=importance))
    assert store.active() == before
    assert len(store.list()["profiles"]) == len(PRESETS)


def test_free_class_application_labels_are_context_only_not_schema_or_facts(store):
    made = store.create(
        custom(
            material_class="My unverified material class",
            application="My experimental goal",
        )
    )
    assert made["material_class"] == "My unverified material class"
    with pytest.raises(ValueError):
        store.create({**custom(), "material_properties": {"band_gap": 99}})
    with pytest.raises(ValueError):
        store.create({**custom(), "allow_private_sources": True})


def test_legacy_weights_migrate_once_and_do_not_override_later_edits(tmp_path):
    workspace = WorkspaceStore(tmp_path / "legacy.sqlite3")
    profiles = RankingProfileStore(workspace)
    old = {
        "stability": 0.1,
        "band_gap": 0.5,
        "element_screen": 0.1,
        "simplicity": 0.1,
        "evidence_quality": 0.2,
    }
    profiles.initialize(legacy_importance=old)
    assert profiles.active()["id"] == "migrated-ranking-preferences"
    assert profiles.active()["importance"] == old
    profiles.activate(PRESETS[1][0])
    profiles.initialize(legacy_importance=old)
    assert profiles.active()["id"] == PRESETS[1][0]
    assert len(profiles.list()["profiles"]) == len(PRESETS) + 1


def test_each_added_class_loads_editable_preferences_without_claiming_coverage(store):
    expected_labels = {
        "Polymers",
        "Perovskites",
        "Perovskitoids",
        "Ceramic Oxides",
        "Metals & Metal Alloys",
        "MOFs",
        "High-Entropy Alloys",
        "Semiconductor Nanocrystals (Quantum Dots)",
        "Organic Electronic Materials",
        "Two-Dimensional Materials",
        "Polymer Matrix Composites",
        "Ceramic Matrix Composites",
        "Biomaterials",
        "Elastomers",
        "Liquid Crystals",
        "Thermosets",
        "Thermoplastics",
    }
    data = store.list()
    classes = {
        item["id"]: item
        for item in data["catalog"]["material_classes"]
        if item["label"] in expected_labels
    }
    assert {item["label"] for item in classes.values()} == expected_labels
    templates = {
        profile["material_class"]: profile
        for profile in data["profiles"]
        if profile["application"] == "property_exploration"
    }
    assert set(templates) == set(classes)
    for identifier, template in templates.items():
        assert "Public discovery" in classes[identifier]["scope"]
        assert "missing properties remain unknown" in classes[identifier]["scope"]
        assert template["importance"]["evidence_quality"] == 0.5
        assert template["importance"]["element_screen"] == 0.5
        assert template["importance"]["stability"] == 0.3
        assert template["importance"]["ambient_phase_stability"] == 0.3
        assert template["importance"]["operational_stability"] == 0.3
        assert all(
            value == 0
            for name, value in template["importance"].items()
            if name
            not in {
                "evidence_quality",
                "element_screen",
                "stability",
                "ambient_phase_stability",
                "operational_stability",
            }
        )
    polymer = templates["polymers"]
    semiconductor = templates["semiconductor_nanocrystals"]
    assert "shear_modulus" in polymer["importance"]
    assert "direct_gap" in semiconductor["importance"]
    assert polymer["importance"] != semiconductor["importance"]
    edited = store.create(
        {
            key: polymer[key]
            for key in ("name", "material_class", "application", "importance")
        }
    )
    changed = custom(
        name="My polymer question",
        material_class="polymers",
        application="property_exploration",
        importance={"shear_modulus": 0.8, "evidence_quality": 0.8},
    )
    store.update(edited["id"], changed)
    store.activate(edited["id"])
    store.initialize()
    assert store.active()["importance"] == changed["importance"]
    assert store.active()["normalized_weights"] == {
        "shear_modulus": 0.5,
        "evidence_quality": 0.5,
    }


def test_existing_workspace_gains_new_templates_without_resetting_active_profile(store):
    made = store.create(custom())
    store.activate(made["id"])
    original_ids = {identifier for identifier, _ in PRESETS[:4]}
    with store.workspace._connection(write=True) as connection:
        connection.executemany(
            "DELETE FROM ranking_profiles WHERE id=?",
            [
                (identifier,)
                for identifier, _ in PRESETS
                if identifier not in original_ids
            ],
        )
    assert len(store.list()["profiles"]) == len(original_ids) + 1
    store.initialize()
    upgraded = store.list()
    assert upgraded["active_profile_id"] == made["id"]
    assert store.active() == made
    assert len(upgraded["profiles"]) == len(PRESETS) + 1
    assert original_ids.issubset({profile["id"] for profile in upgraded["profiles"]})


def test_invalid_saved_profile_is_reported_and_not_silently_reset(store):
    with store.workspace._connection(write=True) as connection:
        connection.execute(
            "UPDATE ranking_profiles SET value=? WHERE id=?",
            ("{broken", DEFAULT_PROFILE_ID),
        )
    with pytest.raises(sqlite3.DatabaseError):
        store.active()
    store.initialize()
    with pytest.raises(sqlite3.DatabaseError):
        store.active()


def test_profile_routes_create_update_activate_and_reject_policy_fields(store):
    app = FastAPI()
    app.include_router(create_ranking_profiles_router(store))
    client = TestClient(app)
    assert (
        client.get("/api/ranking-profiles").json()["active_profile_id"]
        == DEFAULT_PROFILE_ID
    )
    created = client.post("/api/ranking-profiles", json=custom())
    assert created.status_code == 201
    identifier = created.json()["id"]
    assert (
        client.post(f"/api/ranking-profiles/{identifier}/activate", json={}).json()[
            "active_profile_id"
        ]
        == identifier
    )
    updated = client.put(
        f"/api/ranking-profiles/{identifier}", json=custom(name="Changed")
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Changed"
    assert (
        client.post("/api/ranking-profiles/missing/activate", json={}).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/ranking-profiles/{identifier}/activate", json={"private": True}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/ranking-profiles", json={**custom(), "evidence": "fake"}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        (
            "Find oxide dielectric candidates for thin-film experiments.",
            "preset-oxide-thin-film",
        ),
        ("Compare high-k oxide dielectrics.", "preset-oxide-high-k"),
        ("Compare structural ceramics for stiffness.", "preset-ceramic-stiffness"),
        (
            "Find semiconductors for optoelectronics.",
            "preset-semiconductor-optoelectronics",
        ),
        ("Explore polymers.", "preset-polymers-exploration"),
        ("Compare MOFs.", "preset-mofs-exploration"),
        (
            "Explore polymer matrix composites.",
            "preset-polymer-matrix-composites-exploration",
        ),
        (
            "Compare semiconductor nanocrystals.",
            "preset-semiconductor-nanocrystals-exploration",
        ),
        (
            "Explore high-entropy alloys.",
            "preset-high-entropy-alloys-exploration",
        ),
    ],
)
def test_prompt_hints_select_saved_profile_without_changing_active(
    store, prompt, expected
):
    before = store.active()
    selected, decision = store.select("infer", prompt)
    assert selected["id"] == expected
    assert decision["mode"] == "inferred"
    assert decision["selected_profile_id"] == expected
    assert decision["inference_version"] == "catalog-goals-v3"
    assert store.active() == before
    # No numbers or weights are interpreted from the prompt.
    assert store.select(
        "infer", prompt + " I claim a gap of 987654 eV; weight=0.99."
    ) == (
        selected,
        decision,
    )


@pytest.mark.parametrize(
    "prompt",
    [
        "Find promising materials.",
        "Find oxide dielectrics.",
        "Find a new material class called quasiplasmonic gel.",
        "Compare polymers and oxide dielectrics for thin films.",
        "Compare oxide dielectrics for thin films and stiffness.",
        "Please use https://example.invalid/weight?value=0.99.",
        "Read https://example.invalid/polymers/property-exploration.",
    ],
)
def test_ambiguous_or_unknown_hints_report_active_fallback(store, prompt):
    active = store.active()
    selected, decision = store.select("infer", prompt)
    assert selected == active
    assert decision["mode"] == "fallback"
    assert "active ranking profile" in decision["reason"]
    assert "weights only" in decision["reason"]
    assert store.active() == active


def test_saved_custom_context_can_be_inferred_but_duplicate_context_is_ambiguous(store):
    active = store.active()
    profile = store.create(
        custom(material_class="My custom class", application="My goal")
    )
    selected, decision = store.select("infer", "Explore My custom class for My goal.")
    assert selected == profile
    assert decision["mode"] == "inferred"
    store.create(custom(material_class="My custom class", application="My goal"))
    selected, decision = store.select("infer", "Explore My custom class for My goal.")
    assert selected == active
    assert decision["mode"] == "fallback"
    # An active custom profile is retained when its saved context matches.
    store.activate(profile["id"])
    assert store.select("infer", "Explore My custom class for My goal.")[0] == profile


def test_explicit_selection_validates_saved_profile_without_activating_it(store):
    active = store.active()
    profile = store.create(custom())
    selected, decision = store.select(profile["id"], "Any request")
    assert selected == profile
    assert decision["mode"] == "explicit"
    assert store.active() == active
    with pytest.raises(RankingProfileNotFound):
        store.select("missing", "Any request")
    with store.workspace._connection(write=True) as connection:
        connection.execute(
            "UPDATE ranking_profiles SET value=? WHERE id=?", ("{broken", profile["id"])
        )
    with pytest.raises(sqlite3.DatabaseError):
        store.select(profile["id"], "Any request")


def test_punctuation_and_numeric_custom_labels_cannot_match_every_prompt(store):
    for label in ("...", "123"):
        store.create(custom(material_class=label, application=label))
    selected, decision = store.select("infer", "123 ... Find promising materials.")
    assert selected == store.active()
    assert decision["mode"] == "fallback"
    selected, decision = store.select("infer", "polymers " * 2000)
    assert selected["id"] == "preset-polymers-exploration"
    assert decision["mode"] == "inferred"


def test_perovskite_optoelectronic_request_composes_class_application_and_goals(store):
    before = store.list()
    selected, decision = store.select(
        "infer",
        "I would like to find a perovskite material that can be used in an "
        "optoelectronic device and has a bandgap around 1.78 eV. It should be "
        "solution processable, and I would like to find a stable material",
    )
    assert decision["mode"] == "inferred"
    assert selected["material_class"] == "perovskites"
    assert selected["application"] == "optoelectronics"
    assert selected["name"] == "Perovskites · Optoelectronics"
    assert selected["target_band_gap_ev"] == 1.78
    assert selected["band_gap_tolerance_ev"] == 0.2
    assert selected["minimum_band_gap_ev"] is None
    assert selected["importance"]["band_gap"] > 0
    assert selected["importance"]["stability"] >= 0.5
    assert selected["importance"]["solution_processability"] == 0.5
    assert selected["importance"].get("dielectric_total", 0) == 0
    assert selected["importance"].get("element_screen", 0) == 0
    assert selected["normalized_weights"] == normalize_importance(
        selected["importance"]
    )
    assert decision["preference_adjustments"][0]["tolerance_origin"] == (
        "application_default"
    )
    assert (
        "not a measured uncertainty" in decision["preference_adjustments"][0]["reason"]
    )
    assert store.list() == before
    assert not {"sources", "candidates", "band_gap_ev"} & selected.keys()


@pytest.mark.parametrize(
    "subject",
    [
        "metal alloys for structural stiffness",
        "polymers for flexible optoelectronic devices",
        "halide perovskites for photovoltaic absorbers",
        "quantum dots for photodetectors",
    ],
)
@pytest.mark.parametrize(
    "processing",
    [
        "solution processable",
        "solution processability",
        "solution-processed",
        "solution processing",
        "solution‑processed",
    ],
)
def test_explicit_density_and_processing_goals_augment_any_inferred_class(
    store, subject, processing
):
    saved = store.list()
    baseline, _ = store.select("infer", f"Find {subject}.")
    profile, selection = store.select(
        "infer", f"Find {subject}. Prefer low density and {processing} materials."
    )
    assert selection["mode"] == "inferred"
    assert profile["material_class"] == baseline["material_class"]
    assert profile["application"] == baseline["application"]
    assert profile["importance"]["density"] >= 0.5
    assert profile["importance"]["solution_processability"] >= 0.5
    assert {
        adjustment["attribute"]
        for adjustment in selection["preference_adjustments"]
        if adjustment["status"] == "applied_preference"
    } == {"density", "solution_processability"}
    for attribute, importance in baseline["importance"].items():
        if attribute not in {"density", "solution_processability"}:
            assert profile["importance"][attribute] == importance
    assert profile["normalized_weights"] == normalize_importance(profile["importance"])
    assert store.list() == saved
    assert not {"sources", "candidates", "density_g_cm3"} & profile.keys()


@pytest.mark.parametrize(
    "preference",
    ["low density", "low-density", "lower density", "mass density", "density"],
)
def test_density_request_uses_catalog_importance_without_importing_prompt_values(
    store, preference
):
    selected, decision = store.select(
        "infer", f"Find metal alloys for structural stiffness. Compare {preference}."
    )
    assert selected["importance"]["density"] == 0.5
    assert "no density value comes from the prompt" in (
        decision["preference_adjustments"][0]["reason"]
    )


@pytest.mark.parametrize(
    "criterion",
    [
        "low density",
        "solution-processed",
        "solution processing",
    ],
)
@pytest.mark.parametrize(
    "clause", ["Do not require {criterion}", "{criterion} is not required"]
)
def test_negated_criteria_do_not_add_inferred_preferences(store, criterion, clause):
    baseline, _ = store.select("infer", "Find metal alloys for structural stiffness.")
    selected, decision = store.select(
        "infer",
        "Find metal alloys for structural stiffness. "
        + clause.format(criterion=criterion),
    )
    assert selected == baseline
    assert "preference_adjustments" not in decision


@pytest.mark.parametrize(
    "clause",
    [
        "Compare energy density.",
        "Compare current density.",
        "Compare density of states.",
        "Prefer high-density materials.",
        "Prefer higher mass density.",
        "A paper reports low density and solution-processed materials.",
        "https://example.invalid/low-density/solution-processing",
    ],
)
def test_other_density_quantities_and_source_hints_do_not_add_mass_density(
    store, clause
):
    baseline, _ = store.select("infer", "Find metal alloys for structural stiffness.")
    selected, decision = store.select(
        "infer", "Find metal alloys for structural stiffness. " + clause
    )
    assert selected == baseline
    assert "preference_adjustments" not in decision


@pytest.mark.parametrize("selection_mode", ["explicit", "active"])
def test_requested_density_and_processing_do_not_override_chosen_profile(
    store, selection_mode
):
    before = store.active()
    selected, decision = store.select(
        before["id"] if selection_mode == "explicit" else None,
        "Find low-density solution-processed alloys for structural stiffness.",
    )
    assert selected == before
    assert decision["mode"] == selection_mode
    assert "preference_adjustments" not in decision
    assert store.active() == before


@pytest.mark.parametrize(
    "prompt,material_class,application,criterion",
    [
        (
            "Find stiff polymers for structural stiffness.",
            "polymers",
            "stiffness",
            "bulk_modulus",
        ),
        (
            "Find quantum dots for photodetectors.",
            "semiconductor_nanocrystals",
            "optoelectronics",
            "direct_gap",
        ),
        (
            "Find perovskitoids for thin-film photovoltaics.",
            "perovskitoids",
            "optoelectronics",
            "direct_gap",
        ),
        (
            "Find metal-halide perovskite semiconductors for solar cells.",
            "perovskites",
            "optoelectronics",
            "direct_gap",
        ),
        (
            "Find metal alloys for structural stiffness.",
            "metals_metal_alloys",
            "stiffness",
            "shear_modulus",
        ),
        (
            "Find alloys for structural stiffness.",
            "metals_metal_alloys",
            "stiffness",
            "shear_modulus",
        ),
        (
            "Find organic semiconductor materials for photovoltaic donor and "
            "acceptor layers.",
            "organic_electronic_materials",
            "optoelectronics",
            "stability",
        ),
        (
            "Find organic photovoltaics for solution-processable thin films.",
            "organic_electronic_materials",
            "optoelectronics",
            "solution_processability",
        ),
        (
            "Find molecular donor-acceptor semiconductors for solar cells.",
            "organic_electronic_materials",
            "optoelectronics",
            "stability",
        ),
        (
            "Find QDs for photodetectors.",
            "semiconductor_nanocrystals",
            "optoelectronics",
            "direct_gap",
        ),
    ],
)
def test_class_application_composition_is_generic_and_does_not_create_saved_results(
    store, prompt, material_class, application, criterion
):
    before = store.list()
    profile, decision = store.select("infer", prompt)
    assert decision["mode"] == "inferred"
    assert profile["material_class"] == material_class
    assert profile["application"] == application
    assert profile["importance"][criterion] > 0
    assert profile["id"].startswith("inferred-")
    assert store.list() == before


def test_exact_saved_class_application_wins_over_composed_defaults(store):
    made = store.create(
        custom(
            material_class="perovskites",
            application="optoelectronics",
            importance={"band_gap": 0.8, "direct_gap": 0.2},
        )
    )
    selected, decision = store.select("infer", "Find perovskites for optoelectronics.")
    assert selected == made
    assert decision["mode"] == "inferred"


@pytest.mark.parametrize("target", [None, 0, 1.78, 100])
def test_optional_target_roundtrips_as_preferences_only(store, target):
    created = store.create(custom(target_band_gap_ev=target))
    store.activate(created["id"])
    store.initialize()
    assert store.active()["target_band_gap_ev"] == target
    assert "band_gap_tolerance_ev" not in store.active()


@pytest.mark.parametrize(
    "fields",
    [
        {"target_band_gap_ev": True},
        {"target_band_gap_ev": "1.78"},
        {"target_band_gap_ev": -1},
        {"target_band_gap_ev": float("nan")},
        {"target_band_gap_ev": 10**500},
        {"band_gap_tolerance_ev": 0.2},
        {"target_band_gap_ev": 1.78, "band_gap_tolerance_ev": 0},
        {"target_band_gap_ev": 1.78, "band_gap_tolerance_ev": True},
        {"target_band_gap_ev": 1.78, "band_gap_tolerance_ev": float("inf")},
        {"target_band_gap_ev": 1.78, "band_gap_tolerance_ev": 10**500},
    ],
)
def test_invalid_targets_and_tolerances_do_not_change_saved_profiles(store, fields):
    before = store.list()
    with pytest.raises(ValueError):
        store.create(custom(**fields))
    assert store.list() == before


def test_explicit_profile_keeps_preferences_even_when_prompt_requests_different_goals(
    store,
):
    before = store.active()
    selected, selection = store.select(
        before["id"],
        "Find perovskites for optoelectronics with a band gap around 1.78 eV.",
    )
    assert selected == before
    assert selection["mode"] == "explicit"


@pytest.mark.parametrize(
    "prompt",
    [
        "A material has a band gap around 1.78 eV.",
        "Find perovskites. A public page says the measured band gap is 1.78 eV.",
        "Find perovskites. Literature says band gap around 1.78 eV.",
        "Find perovskites. https://example.invalid/band-gap-around-1.78-eV",
        'Find perovskites. {"target_band_gap_ev": 1.78, "weight": 0.99}',
    ],
)
def test_property_claims_and_raw_numbers_do_not_become_target_preferences(
    store, prompt
):
    from labcat.ranking_profiles import prompt_preferences

    before = store.active()
    selected, adjustments = prompt_preferences(before, prompt)
    assert selected == before
    assert adjustments == []


def test_explicit_tolerance_minimum_and_conflicting_targets_are_distinct(store):
    from labcat.ranking_profiles import prompt_preferences

    base = store.active()
    selected, adjustments = prompt_preferences(
        base, "Find semiconductors with a band gap around 1.78 eV, ± 0.1 eV."
    )
    assert selected["target_band_gap_ev"] == 1.78
    assert selected["band_gap_tolerance_ev"] == 0.1
    assert selected["minimum_band_gap_ev"] is None
    assert adjustments[0]["tolerance_origin"] == "prompt_preference"
    changed, _ = prompt_preferences(
        selected, "Instead require a band gap at least 3 eV."
    )
    assert changed["minimum_band_gap_ev"] == 3
    assert changed["target_band_gap_ev"] is None
    assert changed["band_gap_tolerance_ev"] is None
    conflicting, notes = prompt_preferences(
        base, "Find semiconductors with band gap around 1 eV or band gap around 2 eV."
    )
    assert conflicting == base
    assert notes[0]["status"] == "needs_clarification"


def test_inline_target_tolerance_is_a_goal_and_negated_processing_is_not(store):
    from labcat.ranking_profiles import prompt_preferences

    base = store.active()
    selected, adjustments = prompt_preferences(
        base,
        "Find semiconductors with a band gap 1.78 ± 0.15 eV. "
        "They need not be solution processable.",
    )
    assert selected["target_band_gap_ev"] == 1.78
    assert selected["band_gap_tolerance_ev"] == 0.15
    assert "solution_processability" not in selected["importance"]
    assert len(adjustments) == 1


def test_invalid_requested_tolerance_does_not_silently_use_default(store):
    from labcat.ranking_profiles import prompt_preferences

    base = store.active()
    selected, adjustments = prompt_preferences(
        base, "Find semiconductors with a band gap around 1.78 eV ± 0 eV."
    )
    assert selected == base
    assert adjustments[0]["status"] == "needs_clarification"
