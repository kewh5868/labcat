"""Synthetic adapter fixtures test precedence, persistence and export
together."""

import hashlib
import json
from copy import deepcopy

import pytest

from labcat import science
from labcat.config import load_config
from labcat.report_exports import ExportError, prepare_presentation
from labcat.science import hybrid3
from labcat.workspace import WorkspaceStore


def adapter_record(identifier, gap, experimental):
    """Pass deliberately synthetic transport data through the approved
    parser."""
    row = {
        "pk": identifier,
        "visible": True,
        "system": {"id": 1, "formula": "SiO2", "compound_name": "TEST ONLY"},
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
                "label": "TEST ONLY matched phase",
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
    return records[0]


@pytest.mark.parametrize("minimum,expected_count", [(None, 1), (2.0, 0)])
def test_experiment_precedence_and_both_sources_survive_save_and_reformat(
    monkeypatch, tmp_path, minimum, expected_count
):
    records = [adapter_record(1, 1.4, True), adapter_record(2, 3.2, False)]
    before = deepcopy(records)
    monkeypatch.setattr(
        science,
        "_retrieve_repositories",
        lambda *a, **k: (
            deepcopy(records),
            {"status": "ok", "records_retrieved": 2},
        ),
    )
    outcome = science.run_research(
        "Find semiconductor candidates.",
        load_config(),
        importance={"band_gap": 1},
        minimum_band_gap_ev=minimum,
        materials_project_mode="off",
    )
    assert len(outcome["result"]["candidates"]) == expected_count
    if expected_count:
        assert outcome["result"]["candidates"][0]["band_gap_ev"] == 1.4
    retained = outcome["result"]["comparison_records"]
    assert {r["material_id"] for r in retained} == {r["material_id"] for r in records}
    assert len(outcome["sources"]) == 2
    assert records == before
    for view in ("pi_summary", "technical_audit"):
        assert "1.4 eV" in outcome[view] and "3.2 eV" in outcome[view]
        assert "[R1]" in outcome[view] and "[R2]" in outcome[view]

    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY experimental comparison")
    chat = store.create_global_chat("TEST ONLY", project["id"])
    store.append_research(chat["id"], project["id"], "Compare evidence.", outcome)
    detail = WorkspaceStore(store.path).get_global_chat(chat["id"])
    saved = {**detail["reports"][0], "sources": detail["sources"]}
    original_saved = deepcopy(saved)
    for mode in ("saved", "current"):
        prepared = prepare_presentation(saved, mode, load_config())
        assert len(prepared["references"]) == 2
        for view in ("pi_summary", "technical_audit"):
            assert "1.4 eV" in prepared[view] and "3.2 eV" in prepared[view]
            assert "[R1]" in prepared[view] and "[R2]" in prepared[view]
    assert saved == original_saved
    saved["sources"] = saved["sources"][:1]
    with pytest.raises(ExportError):
        prepare_presentation(saved)


@pytest.mark.parametrize("count,allowed", [(144, True), (145, False)])
def test_comparison_citations_fit_bounded_workspace_source_storage(
    tmp_path, count, allowed
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY citation limit")
    chat = store.create_global_chat("TEST ONLY", project["id"])
    outcome = {
        "stage": "partial",
        "answer": "Synthetic source-count fixture.",
        "pi_summary": "Synthetic fixture.",
        "technical_audit": "Synthetic fixture.",
        "result": {"candidates": []},
        "sources": [
            {
                "title": f"TEST ONLY source {i}",
                "source_name": "TEST ONLY",
                "url": f"https://materials.hybrid3.duke.edu/materials/dataset/{i + 1}",
                "access_scope": "public",
                "provenance_status": "verified",
            }
            for i in range(count)
        ],
    }
    if allowed:
        detail = store.append_research(chat["id"], project["id"], "Fixture", outcome)
        assert len(detail["sources"]) == count
    else:
        with pytest.raises(ValueError, match="source set"):
            store.append_research(chat["id"], project["id"], "Fixture", outcome)
        assert not store.get_global_chat(chat["id"])["reports"]
