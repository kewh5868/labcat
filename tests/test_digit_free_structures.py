"""Digit-free formula queries use synthetic source records, never
invented facts."""

import pytest
from test_component_structures import (  # noqa: F401
    component_mp_transport,
    offline_adapters,
)
from test_literature_structures import report_bytes
from test_structure_reference_discovery import formula_report
from test_structures import structure_store

from labcat import structures


@pytest.mark.parametrize("formula", ["CdS", "ZnS", "ZnSe", "InP"])
def test_digit_free_formula_reaches_repository_and_downloads_cif(
    tmp_path, monkeypatch, formula
):
    store = structure_store(tmp_path)
    chat, report, leads, _ = formula_report(store, name=formula)
    before = report_bytes(store)
    searches, retrievals, _ = component_mp_transport(store, monkeypatch)
    listed = store.list(chat, report)
    assert listed["structures"] == []
    assert listed["literature_candidates"][0]["status"] == "reference_lookup_available"
    found = store.find_references(chat, report, leads[0]["id"])
    assert searches == [formula]
    row = found["structures"][0]
    assert row["source_formula"] == formula
    assert row["literature_association"]["relation"] == "composition_reference"
    assert row["literature_association"]["phase_match"] == "unverified"
    loaded = store.retrieve(chat, report, row["material_id"])
    assert loaded["status"] == "ready"
    cif, metadata = store.content(chat, report, row["material_id"])
    assert cif.startswith(b"# Labcat derived") and b"_atom_site_fract_x" in cif
    assert metadata["sha256"] == loaded["sha256"]
    assert retrievals == [row["material_id"]]
    assert report_bytes(store) == before


@pytest.mark.parametrize("formula", ["InAs", "CdSe", "GaAs", "GaN", "SiC", "NaCl"])
def test_other_properly_cased_formulas_are_only_lookup_hints(formula):
    lead = {"name": formula, "citations": []}
    assert structures._formula_hint(lead, []) == formula


@pytest.mark.parametrize(
    "name",
    [
        "CDs",
        "PI",
        "NO",
        "Y6",
        "C60",
        "CdS nanocrystals",
        "CdS; ignore instructions",
        "CdS/ZnSe",
        "CdS0.5",
    ],
)
def test_abbreviations_composites_and_partial_formula_labels_are_not_single_structures(
    name,
):
    assert structures._formula_hint({"name": name, "citations": []}, []) is None


def test_digit_free_query_does_not_accept_different_repository_composition(
    tmp_path, monkeypatch
):
    store = structure_store(tmp_path)
    chat, report, leads, _ = formula_report(store, name="CdS")
    before = report_bytes(store)
    component_mp_transport(store, monkeypatch)
    request = structures._request_mp_data

    def mismatched(key, filters=None, **kwargs):
        data, digest, url = request(key, filters, **kwargs)
        data["data"][0]["formula_pretty"] = "ZnS"
        data["data"][0]["elements"] = ["Zn", "S"]
        return data, digest, url

    monkeypatch.setattr(structures, "_request_mp_data", mismatched)
    with pytest.raises(structures.StructureUnavailable):
        store.find_references(chat, report, leads[0]["id"])
    assert store.list(chat, report)["structures"] == []
    assert report_bytes(store) == before
