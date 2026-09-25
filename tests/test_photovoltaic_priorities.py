"""Photovoltaic preference inference; no scientific measurements are
supplied."""

from copy import deepcopy

import pytest
from test_research_intent import assessment, fallback

from labcat.ranking_profiles import (
    RankingProfileStore,
    application_preferences,
    compose_catalog_profile,
)
from labcat.research_intent import resolve_intent
from labcat.science.literature_evaluation import evaluation_context, evaluation_goals
from labcat.workspace import WorkspaceStore

PROMPT = (
    "Can you find some stable metal halide perovskite compositions "
    "that could be used as a top cell for a bottom cell Si-perovskite "
    "tandem solar cell?"
)


@pytest.mark.parametrize(
    "prompt",
    [
        PROMPT,
        "Shortlist perovskites for a solar absorber above silicon.",
        "Find halide perovskites for photovoltaic devices, with long operating life.",
    ],
)
def test_application_preferences_include_gap_without_inventing_optimum(
    tmp_path, prompt
):
    store = RankingProfileStore(WorkspaceStore(tmp_path / "workspace.sqlite3"))
    store.initialize()
    before = store.list()
    profile, decision = store.select("infer", prompt)
    assert profile["material_class"] == "perovskites"
    assert profile["importance"]["band_gap"] >= 0.9
    assert profile["importance"]["operational_stability"] >= 0.9
    assert profile["importance"]["refractive_index"] == 0
    assert profile.get("target_band_gap_ev") is None
    assert profile.get("minimum_band_gap_ev") is None
    criteria = evaluation_context(profile, goals=evaluation_goals(None, decision))
    assert next(c for c in criteria if c["criterion_id"] == "band_gap")["goal"] == {
        "relation": "consider"
    }
    assert store.list() == before


@pytest.mark.parametrize(
    "prompt",
    [
        "Find perovskites for LEDs.",
        "Find oxide perovskites for capacitors.",
        "Find perovskites, not solar cells.",
        "Find perovskites. A paper says solar cells use them.",
    ],
)
def test_other_or_negated_applications_do_not_inherit_photovoltaic_defaults(prompt):
    profile = compose_catalog_profile("perovskites", "optoelectronics")
    before = deepcopy(profile)
    result, adjustments = application_preferences(profile, prompt)
    assert result == before and adjustments == []


def test_explicit_saved_profile_weights_remain_authoritative(tmp_path):
    store = RankingProfileStore(WorkspaceStore(tmp_path / "workspace.sqlite3"))
    store.initialize()
    custom = store.create(
        {
            "name": "My optics",
            "material_class": "perovskites",
            "application": "optoelectronics",
            "importance": {"refractive_index": 1, "band_gap": 0},
        }
    )
    profile, decision = store.select(custom["id"], PROMPT)
    assert profile["importance"] == custom["importance"]
    assert evaluation_goals(None, decision) == []


def test_semantic_inference_keeps_application_defaults_and_explicit_target():
    prompt = "Find perovskites for tandem solar cells; target a 1.72 eV band gap."
    args = assessment(
        "perovskites",
        material_class="perovskites",
        application="optoelectronics",
        application_spans=["tandem solar cells"],
        goals=[
            {
                "attribute_id": "band_gap",
                "request_span": "target a 1.72 eV band gap",
                "priority": "primary",
                "relation": "target",
            }
        ],
    )
    result = resolve_intent(prompt, args, *fallback())
    profile = result["profile"]
    assert profile["target_band_gap_ev"] == 1.72
    assert profile["importance"]["operational_stability"] == 0.9
    goals = evaluation_goals(result["scope"], result["selection"])
    assert goals[0]["attribute_id"] == "band_gap"
    criteria = evaluation_context(profile, goals=goals)
    gap = next(c for c in criteria if c["criterion_id"] == "band_gap")
    assert gap["goal"]["relation"] == "target"
    assert gap["goal"]["target_band_gap_ev"] == 1.72
