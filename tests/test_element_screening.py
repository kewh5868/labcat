"""Synthetic records exercise screening policy, never scientific
conclusions."""

from copy import deepcopy

import pytest

from labcat.config import load_config
from labcat.science.ranking import ELEMENT_PRESET_VERSION, rank_records
from labcat.science.sources import load_snapshot


@pytest.mark.parametrize("element", ["Pm", "Ac", "Pu", "Ra", "Tc", "Np"])
def test_expanded_screen_excludes_matches_only_when_selected(element):
    records, _ = load_snapshot()
    synthetic = deepcopy(records[0])
    synthetic.update(material_id="synthetic-screen-test", elements=[element, "O"])
    original = deepcopy(synthetic)
    rows, audit = rank_records(
        [synthetic], load_config(), importance={"element_screen": 0.5}
    )
    assert rows == []
    assert audit["excluded_element_preset_version"] == ELEMENT_PRESET_VERSION
    assert element in audit["excluded_element_preset"]
    assert element in audit["excluded_records"][0]["reasons"][0]
    assert synthetic == original

    rows, _ = rank_records(
        [synthetic], load_config(), importance={"simplicity": 0.5, "element_screen": 0}
    )
    assert len(rows) == 1
    assert rows[0]["element_screen"]["preset_matches"] == [element]
    assert rows[0]["element_screen"]["hazard_assessment"] == "unassessed"
