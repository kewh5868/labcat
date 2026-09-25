"""Repository selection and broad discovery use fresh adapter evidence
only."""

from copy import deepcopy

import pytest

from labcat import public_sources, science
from labcat.config import load_config
from labcat.research_context import material_hints
from labcat.science.sources import SourceError


@pytest.fixture
def rows():
    # Published historical rows are explicitly substituted only in offline tests.
    records, _ = science.load_snapshot()
    for record in records:
        record["material_id"] = "dielectric:" + record["material_id"]
        record["source_mode"] = "live_public_dielectric"
        record["provenance"][
            "source_url"
        ] = "https://doi.org/10.6084/m9.figshare.7108790.v2"
        record["provenance"]["response_sha256"] = "a" * 64
    return records


def test_selected_full_corpus_supplies_more_than_old_six_candidate_limit(
    monkeypatch, rows
):
    calls = []

    def retrieve(filters):
        calls.append(filters)
        return deepcopy(rows), {
            "records_examined": len(rows),
            "records_retrieved": len(rows),
        }

    monkeypatch.setattr(science, "retrieve_public_dielectric", retrieve)
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda _: pytest.fail("unselected source")
    )
    result = science.run_research(
        "Find oxide dielectric candidates",
        load_config(),
        application="high_k_screening",
        importance={"dielectric_total": 1, "band_gap": 1},
        allow_nomad=False,
        allow_public_dielectric=True,
    )["result"]
    assert calls == [{"elements": "O", "has_props": "dielectric"}]
    assert len(result["candidates"]) == 12
    assert result["retrieval"]["records_retrieved"] == len(rows)
    assert all(
        row["source_mode"] == "live_public_dielectric" for row in result["candidates"]
    )


@pytest.mark.parametrize(
    "selected,prompt",
    [(False, "Find oxide dielectrics"), (True, "Find nitride mechanical materials")],
)
def test_unselected_or_irrelevant_specialized_corpus_is_not_queried(
    monkeypatch, selected, prompt
):
    monkeypatch.setattr(
        science,
        "retrieve_public_dielectric",
        lambda _: pytest.fail("unselected or irrelevant source"),
    )
    result = science.run_research(
        prompt,
        load_config(),
        importance={"bulk_modulus": 1},
        allow_public_dielectric=selected,
    )
    assert result["result"]["candidates"] == []


def test_sparse_first_repository_does_not_end_discovery_or_merge_properties(
    monkeypatch, rows
):
    first = deepcopy(rows[0])
    first["material_id"] = first["material_id"].removeprefix("dielectric:")
    first["source_mode"] = "live_materials_project"
    first["dielectric_total"] = None
    calls = []
    monkeypatch.setattr(science, "retrieve_live", lambda *_: ([first], {}))
    monkeypatch.setattr(
        science,
        "retrieve_public_dielectric",
        lambda filters: (calls.append(filters) or deepcopy(rows), {}),
    )
    records, metadata = science._retrieve_repositories(
        {"elements": "O", "has_props": "dielectric"},
        mp_api_key="offline-test-key",
        mode="auto",
        allow_nomad=False,
        allow_public_dielectric=True,
        required_fields=("dielectric_total", "band_gap_ev"),
    )
    assert calls and len(records) == len(rows) + 1
    assert records[0]["dielectric_total"] is None
    assert metadata["selected_repositories"] == [
        "materials_project",
        "public_dielectric",
    ]


def test_target_gap_keeps_searching_after_twelve_records_without_gap(monkeypatch, rows):
    first = deepcopy(rows[:12])
    for record in first:
        record["material_id"] = record["material_id"].removeprefix("dielectric:")
        record["source_mode"] = "live_materials_project"
        record["band_gap_ev"] = None
    later = deepcopy(rows[12:13])
    calls = []
    monkeypatch.setattr(science, "retrieve_live", lambda *_: (first, {}))
    monkeypatch.setattr(
        science,
        "retrieve_nomad",
        lambda filters: (calls.append(filters) or later, {}),
    )
    result = science.run_research(
        "Find semiconductor materials with a band gap around 1.78 eV.",
        load_config(),
        mp_api_key="offline-test-key",
        importance={"band_gap": 0.5, "simplicity": 0.5},
        application="optoelectronics",
        target_band_gap_ev=1.78,
        band_gap_tolerance_ev=0.2,
        allow_nomad=True,
    )["result"]
    assert calls
    assert result["retrieval"]["required_property_fields"] == ["band_gap_ev"]
    assert result["retrieval"]["selected_repositories"] == [
        "materials_project",
        "nomad",
    ]
    assert result["candidates"][0]["material_id"] == later[0]["material_id"]
    assert result["candidates"][0]["band_gap_ev"] == later[0]["band_gap_ev"]
    assert all(record["band_gap_ev"] is None for record in first)


@pytest.mark.parametrize(
    "options",
    [
        {"materials_project_mode": "snapshot"},
        {"materials_project_mode": "api"},
        {"allow_nomad": False},
        {"material_class": "thermoplastics"},
    ],
)
def test_reference_only_reports_keep_target_and_application_preferences(options):
    result = science.run_research(
        "Find semiconductor materials with a band gap around 1.78 eV.",
        load_config(),
        importance={"band_gap": 1},
        application="optoelectronics",
        target_band_gap_ev=1.78,
        band_gap_tolerance_ev=0.1,
        **options,
    )["result"]
    assert result["candidates"] == []
    assert result["ranking"]["status"] == "not_run"
    assert result["ranking"]["application"] == "optoelectronics"
    assert result["ranking"]["screening_preferences"]["target_band_gap_ev"] == 1.78
    assert result["ranking"]["screening_preferences"]["band_gap_tolerance_ev"] == 0.1
    assert "1.78" in result["ranking"]["normalization"]["band_gap"]


def test_corpus_outage_cannot_load_a_bundled_snapshot(monkeypatch):
    def unavailable(_):
        raise SourceError("Offline test outage")

    monkeypatch.setattr(science, "retrieve_public_dielectric", unavailable)
    monkeypatch.setattr(
        science, "load_snapshot", lambda: pytest.fail("saved evidence substituted")
    )
    result = science.run_research(
        "Find oxide dielectric candidates",
        load_config(),
        allow_nomad=False,
        allow_public_dielectric=True,
    )
    assert result["result"]["candidates"] == []
    assert result["result"]["retrieval"]["status"] == "unavailable"


def test_versioned_hint_uses_corpus_adapter_only_and_refetches(monkeypatch, rows):
    identity = rows[0]["material_id"]
    calls = []
    monkeypatch.setattr(
        science,
        "retrieve_public_dielectric",
        lambda query: (calls.append(query) or deepcopy(rows[:1]), {}),
    )
    monkeypatch.setattr(
        science, "retrieve_live", lambda *_: pytest.fail("wrong repository")
    )
    context = {
        "active_chat": {
            "latest_completed_report_id": "saved",
            "source_hints": [
                {"url": rows[0]["provenance"]["source_url"], "record_id": identity}
            ],
        }
    }
    assert material_hints(context, "Refine this report") == [identity]
    science._retrieve_repositories(
        {"elements": "O"},
        mp_api_key=None,
        mode="auto",
        allow_nomad=False,
        allow_public_dielectric=True,
        prior_material_ids=[identity],
    )
    assert calls[0]["material_ids"] == identity.removeprefix("dielectric:")
    context["active_chat"]["source_hints"][0]["url"] = "https://unreviewed.example/"
    assert material_hints(context, "Refine this report") == []


def test_corpus_discovery_references_remain_identity_only(monkeypatch, rows):
    from labcat.science import dielectric

    row = rows[0]
    row["provenance"]["dataset_version"] = "Explicit offline historical test"
    monkeypatch.setattr(dielectric, "retrieve_live", lambda _: ([row], {}))
    result = public_sources.search_public_sources(
        "Find oxide dielectric candidates", ["public_dielectric"], 1
    )
    assert len(result["references"]) == 1
    ref = result["references"][0]
    assert ref["is_material_evidence"] is False
    assert ref["record_id"] == row["material_id"]
    assert set(ref["metadata"]) == {"formula", "dataset_version"}
    assert ref["provenance"]["response_sha256"] == row["provenance"]["response_sha256"]
    from labcat.research import _discovery_references

    other = {
        **ref,
        "source_id": "openalex",
        "record_id": "W123",
        "url": "https://openalex.org/W123",
        "title": "Offline bibliographic interface fixture",
    }
    mixed = {"references": [ref, other]}
    assert _discovery_references(mixed, ["public_dielectric", "openalex"], 1) == [
        ref,
        other,
    ]
    with pytest.raises(ValueError, match="URL"):
        _discovery_references(
            {"references": [{**ref, "url": ref["url"] + "?redirect=other"}]},
            ["public_dielectric"],
            1,
        )


def test_legacy_report_without_result_remains_readable_in_chat_context(tmp_path):
    from labcat.workspace import WorkspaceStore

    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Legacy report context")
    scope, _ = store.research_inputs(chat["id"])
    store.append_research(
        chat["id"],
        scope,
        "Offline legacy report fixture",
        {
            "stage": "partial",
            "answer": "Legacy fixture",
            "pi_summary": "Legacy fixture",
            "technical_audit": "Legacy fixture",
            "sources": [],
        },
    )
    with store._connection(write=True) as connection:
        connection.execute("DELETE FROM research_runs")
    _, context = store.research_inputs(chat["id"])
    assert context["active_chat"]["latest_completed_report_id"]
    assert material_hints(context, "Refine this report") == []
