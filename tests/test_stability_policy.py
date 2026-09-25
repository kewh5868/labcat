"""Synthetic arithmetic and preference fixtures, never scientific
evidence."""

import copy
import json

import pytest

from labcat.config import load_config
from labcat.ranking_profiles import PRESETS, RankingProfileStore, catalog
from labcat.science.ranking import rank_records
from labcat.workspace import WorkspaceStore


def record(**fields):
    return {
        "material_id": "TEST-ONLY-stability-arithmetic",
        "formula": "SiO2",
        "elements": ["O", "Si"],
        "band_gap_ev": 8,
        "source_mode": "synthetic_arithmetic_test_only",
        "issues": [],
        **fields,
    }


def rank(source, importance=None):
    return rank_records(
        [source],
        load_config(),
        importance=importance or {"stability": 1, "band_gap": 1},
    )[0][0]


def test_source_hull_energy_reduces_utility_without_claiming_ambient_instability():
    on_hull = rank(record(energy_above_hull_ev_atom=0))
    above = rank(record(energy_above_hull_ev_atom=0.05))
    far_above = rank(record(energy_above_hull_ev_atom=0.2))
    assert on_hull["score"] == 1
    assert above["score"] == 0.75
    assert far_above["score"] == 0.5
    assert above["score_components"]["stability"] == 0.5
    assert far_above["criterion_available"]["stability"] is True
    for result in (on_hull, above, far_above):
        assessment = result["stability_assessment"]
        assert assessment["schema"] == "stability-assessment-v1"
        assert assessment["thermodynamic"]["status"] == "available"
        assert assessment["ambient_phase"]["status"] == "unknown"
        assert assessment["operational"]["status"] == "unknown"
    assert "does not establish room-temperature" in (
        on_hull["stability_assessment"]["thermodynamic"]["interpretation"]
    )
    assert "does not establish a degradation rate" in (
        above["stability_assessment"]["thermodynamic"]["interpretation"]
    )


@pytest.mark.parametrize(
    "hull", [None, True, False, -0.1, "0", float("nan"), float("inf"), 10**500]
)
def test_unknown_or_invalid_hull_cannot_become_stable_or_receive_utility(hull):
    source = record(energy_above_hull_ev_atom=hull)
    result = rank(source)
    assert result["score"] == 0.5
    assert result["energy_above_hull_ev_atom"] is None
    assert result["criterion_available"]["stability"] is False
    assert result["stability_assessment"]["thermodynamic"]["status"] == "unknown"
    assert result["stability_assessment"]["ambient_phase"]["status"] == "unknown"
    assert result["score_components"]["stability"] == 0
    assert result["score_analysis"]["possible_upper_score"] == 1


def test_ambient_study_claims_and_status_fields_cannot_supply_stability_evidence():
    source = record(
        ambient_phase_stability=True,
        operational_stability=True,
        room_temperature_stable=True,
        stability_assessment={"ambient_phase": {"status": "stable"}},
        issues=["TEST ONLY paper/user/model claims room-temperature instability"],
    )
    original = copy.deepcopy(source)
    weights = {
        "band_gap": 1,
        "stability": 1,
        "ambient_phase_stability": 1,
        "operational_stability": 1,
    }
    result = rank(source, weights)
    assert source == original
    assert result["score"] == 0.25
    assert result["selected_weight_coverage"] == 0.25
    assert result["criterion_available"] == {
        "band_gap": True,
        "stability": False,
        "ambient_phase_stability": False,
        "operational_stability": False,
    }
    assert result["stability_assessment"]["ambient_phase"]["status"] == "unknown"
    assert result["stability_assessment"]["operational"]["status"] == "unknown"


def test_explicit_custom_weights_are_preserved_but_stability_scope_stays_visible():
    weights = {"band_gap": 1, "stability": 0}
    result = rank(record(energy_above_hull_ev_atom=0), weights)
    assert result["score"] == 1
    assert result["score_contributions"] == {"band_gap": 1, "stability": 0}
    assert any(
        "Room-temperature phase stability is unknown" in c for c in result["caveats"]
    )
    assert any("Operational stability is unknown" in c for c in result["caveats"])
    assert {"ambient_phase_stability", "operational_stability"} <= set(
        result["missing_data"]
    )


def test_all_shipped_class_application_profiles_consider_each_stability_scope():
    for _, profile in PRESETS:
        for criterion in (
            "stability",
            "ambient_phase_stability",
            "operational_stability",
        ):
            assert profile["importance"][criterion] >= 0.3
    definitions = {item["id"]: item for item in catalog()["attributes"]}
    assert definitions["stability"]["supported"] is True
    for criterion in ("ambient_phase_stability", "operational_stability"):
        assert definitions[criterion]["supported"] is False
        assert "unknown is not stable" in definitions[criterion]["description"]


def earlier_perovskite_preferences():
    return {
        "name": "Perovskites · Property exploration",
        "material_class": "perovskites",
        "application": "property_exploration",
        "importance": {
            "evidence_quality": 0.5,
            "element_screen": 0.5,
            "stability": 0.0,
            "band_gap": 0.0,
            "dielectric_total": 0.0,
            "piezoelectric_response": 0.0,
        },
    }


@pytest.mark.parametrize("change", [None, "weight", "name", "order", "custom"])
def test_stability_defaults_upgrade_only_exact_untouched_presets(tmp_path, change):
    profiles = RankingProfileStore(WorkspaceStore(tmp_path / "test.sqlite3"))
    profiles.initialize()
    previous = earlier_perovskite_preferences()
    identifier = "preset-perovskites-exploration"
    if change == "weight":
        previous["importance"]["stability"] = 0.1
    elif change == "name":
        previous["name"] = "TEST ONLY explicit preferences"
    elif change == "order":
        previous["importance"] = dict(reversed(list(previous["importance"].items())))
    if change == "custom":
        identifier = profiles.create(previous)["id"]
    else:
        with profiles.workspace._connection(write=True) as connection:
            connection.execute(
                "UPDATE ranking_profiles SET value=?,updated_at=? WHERE id=?",
                (json.dumps(previous), "TEST-ONLY-old-timestamp", identifier),
            )
    profiles.activate(identifier)
    before = profiles.active()
    profiles.initialize()
    after = profiles.active()
    assert after["id"] == before["id"]
    assert after["created_at"] == before["created_at"]
    if change is None:
        assert after["importance"]["stability"] == 0.3
        assert after["importance"]["ambient_phase_stability"] == 0.3
        assert after["importance"]["operational_stability"] == 0.3
        assert after["updated_at"] != before["updated_at"]
    else:
        assert after == before
    profiles.initialize()
    assert profiles.active() == after
