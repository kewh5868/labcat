"""Structure adapter, provenance, isolation and injection regression
checks.

NOMAD fixture: one anonymous public archive response retrieved
2026-09-10; never bundled in the application's public results. MP data
here is test-only.
"""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from labcat import structures
from labcat.config import load_config
from labcat.science import sources
from labcat.web import create_app
from labcat.workspace import WorkspaceNotFound, WorkspaceStore

NOMAD_FIXTURE = Path(__file__).parent / "fixtures" / "nomad-structure.json"
NOMAD_ID = "nomad:-1MyUqWhJXYiWx2cQvqa00NTb_JT"


@pytest.fixture
def candidate():
    return {"material_id": NOMAD_ID, "formula": "Si", "source_mode": "live_nomad"}


@pytest.fixture
def payload():
    return json.loads(NOMAD_FIXTURE.read_bytes())


def transport(monkeypatch, payload):
    calls = []

    def fetch(source, params, deadline, body, **kwargs):
        assert source == "nomad" and params == {}
        assert kwargs == {"structure_archive": True}
        assert body["owner"] == "public"
        assert body["query"] == {"entry_id": NOMAD_ID[6:]}
        assert body["pagination"] == {"page_size": 1}
        calls.append(body)
        return (
            json.dumps(payload).encode(),
            "https://nomad-lab.eu/prod/v1/api/v1/entries/archive/query",
        )

    monkeypatch.setattr(structures, "_fetch", fetch)
    return calls


def report_fixture(workspace, candidate):
    chat = workspace.create_global_chat("Structure QA")
    with workspace._connection() as connection:
        scope = workspace._scope_for_chat(connection, chat["id"])
    detail = workspace.append_research(
        chat["id"],
        scope,
        "Test-only query",
        {
            "stage": "partial",
            "answer": "Test-only adapter exercise",
            "pi_summary": "Test-only summary",
            "technical_audit": "Test-only overview",
            "sources": [],
            "result": {"candidates": [candidate]},
        },
    )
    return chat["id"], detail["reports"][0]["id"]


def structure_store(tmp_path, enabled=True):
    workspace = WorkspaceStore(tmp_path / "workspace.sqlite3")
    connections = SimpleNamespace(
        source_connections=lambda: {"materials_project": {"selectable": False}},
        materials_project_key=lambda mode: None,
    )
    store = structures.StructureStore(
        workspace, connections, lambda: {"viewer_enabled": enabled}
    )
    store.initialize()
    return store


def test_real_nomad_archive_units_exact_identity_and_safe_derived_cif(
    monkeypatch, payload, candidate, tmp_path
):
    calls = transport(monkeypatch, payload)
    store = structure_store(tmp_path)
    chat, report = report_fixture(store.workspace, candidate)
    assert store.list(chat, report)["structures"][0]["status"] == "not_loaded"
    assert not calls
    metadata = store.retrieve(chat, report, NOMAD_ID)
    assert len(calls) == 1 and metadata["status"] == "ready"
    assert metadata["n_sites"] == 8
    assert metadata["representation"] == "nomad_terminal_system"
    assert "last system" in metadata["caveats"][-1]
    body, repeated = store.content(chat, report, NOMAD_ID)
    assert body.startswith(b"# Labcat derived")
    assert b"_cell_length_a 3.852381" in body  # actual public metre input, converted
    assert b"Si8 Si 0.500000000000 0.666856000000 0.562956000000 1" in body
    assert hashlib.sha256(body).hexdigest() == repeated["sha256"] == metadata["sha256"]
    assert store.retrieve(chat, report, NOMAD_ID) == metadata
    assert len(calls) == 1
    reopened = structures.StructureStore(
        WorkspaceStore(store.workspace.path),
        store.connections,
        lambda: {"viewer_enabled": False},
    )
    assert reopened.list(chat, report)["viewer_enabled"] is False
    assert reopened.content(chat, report, NOMAD_ID)[0] == body


@pytest.mark.parametrize(
    "mutation",
    [
        "private",
        "embargo",
        "identity",
        "scope",
        "formula",
        "duplicate",
        "nan",
        "script",
        "occupancy",
        "not_periodic",
        "left_handed",
        "singular",
        "huge",
    ],
)
def test_malformed_or_untrusted_archive_is_not_cached(
    monkeypatch, payload, candidate, tmp_path, mutation
):
    row = payload["data"][0]
    archive = row["archive"]
    atoms = archive["run"][0]["system"][0]["atoms"]
    if mutation == "private":
        archive["metadata"]["published"] = False
    elif mutation == "embargo":
        archive["metadata"]["with_embargo"] = True
    elif mutation == "identity":
        row["entry_id"] = "different"
    elif mutation == "scope":
        payload["owner"] = "visible"
    elif mutation == "formula":
        archive["results"]["material"]["chemical_formula_reduced"] = "Ge"
    elif mutation == "duplicate":
        payload["data"].append(deepcopy(row))
    elif mutation == "nan":
        atoms["positions"][0][0] = float("nan")
    elif mutation == "script":
        atoms["labels"][0] = "Si;script https://attacker.invalid"
    elif mutation == "occupancy":
        atoms["concentrations"] = [0.5] * 8
    elif mutation == "not_periodic":
        atoms["periodic"] = [True, True, False]
    elif mutation == "left_handed":
        atoms["lattice_vectors"][0][0] *= -1
    elif mutation == "singular":
        atoms["lattice_vectors"][0] = atoms["lattice_vectors"][1]
    elif mutation == "huge":
        atoms["labels"] = ["Si"] * (structures.MAX_SITES + 1)
    transport(monkeypatch, payload)
    store = structure_store(tmp_path)
    chat, report = report_fixture(store.workspace, candidate)
    with pytest.raises(structures.StructureUnavailable):
        store.retrieve(chat, report, NOMAD_ID)
    with store.workspace._connection() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM report_structures").fetchone()[0]
            == 0
        )


def test_remote_instructions_and_raw_file_links_are_discarded(
    monkeypatch, payload, candidate, tmp_path
):
    payload["data"][0]["archive"]["instructions"] = "javascript:send private files"
    atoms = payload["data"][0]["archive"]["run"][0]["system"][0]["atoms"]
    atoms["raw_file"] = "http://127.0.0.1/private.cif"
    atoms["jsmol_script"] = "script evil; quit"
    transport(monkeypatch, payload)
    store = structure_store(tmp_path)
    chat, report = report_fixture(store.workspace, candidate)
    store.retrieve(chat, report, NOMAD_ID)
    body, metadata = store.content(chat, report, NOMAD_ID)
    assert all(text not in body for text in (b"javascript", b"private", b"evil"))
    with store.workspace._connection() as connection:
        encoded = connection.execute(
            "SELECT structure_json FROM report_structures"
        ).fetchone()[0]
    assert "instructions" not in encoded and "raw_file" not in encoded


def test_normalized_nomad_structure_preferred_and_disorder_rejected(
    monkeypatch, payload, candidate
):
    archive = payload["data"][0]["archive"]
    atoms = archive["run"][0]["system"][0]["atoms"]
    structure = {
        "dimension_types": [1, 1, 1],
        "n_sites": 8,
        "lattice_vectors": atoms["lattice_vectors"],
        "cartesian_site_positions": atoms["positions"],
        "species_at_sites": atoms["labels"],
        "species": [{"name": "Si", "chemical_symbols": ["Si"], "concentration": [1]}],
    }
    archive["results"]["properties"]["structures"] = {"structure_original": structure}
    transport(monkeypatch, payload)
    assert structures._nomad(candidate)[-1] == "nomad_structure_original"
    structure["species"][0]["concentration"] = [0.5]
    with pytest.raises(structures.StructureUnavailable):
        structures._nomad(candidate)


def mp_payload():
    # Synthetic API protocol fixture, never public scientific evidence.
    return {
        "data": [
            {
                "material_id": "mp-149",
                "formula_pretty": "Si",
                "elements": ["Si"],
                "deprecated": False,
                "structure": {
                    "lattice": {
                        "matrix": [[3, 0, 0], [0, 3, 0], [0, 0, 3]],
                        "pbc": [True, True, True],
                    },
                    "sites": [
                        {"species": [{"element": "Si", "occu": 1}], "abc": [0, 0, 0]}
                    ],
                },
            }
        ]
    }


def test_mp_exact_structure_field_adapter(monkeypatch):
    payload = mp_payload()
    calls = []

    def request(key, *, structure_id):
        calls.append(structure_id)
        return payload, "a" * 64, "https://api.materialsproject.org/materials/summary/"

    monkeypatch.setattr(structures, "_request_mp_data", request)
    candidate = {"material_id": "mp-149", "formula": "Si"}
    assert (
        structures._mp(candidate, "test-not-a-real-key")[-1] == "mp_summary_structure"
    )
    assert calls == ["mp-149"]
    payload["data"][0]["structure"]["sites"][0]["species"][0]["occu"] = 0.5
    with pytest.raises(structures.StructureUnavailable):
        structures._mp(candidate, "test-not-a-real-key")


@pytest.mark.parametrize(
    "identity",
    [
        "https://private.invalid/file",
        "mp-1/../../vault",
        "nomad:../../file",
        "mp-1;script",
        "mp-149&query=secret",
    ],
)
def test_arbitrary_structure_identifier_never_reaches_network(monkeypatch, identity):
    monkeypatch.setattr(sources, "_public_addresses", lambda *_: pytest.fail("network"))
    with pytest.raises(sources.SourceError):
        sources._request_mp_data("x" * 32, structure_id=identity)


def test_report_scope_archive_restore_move_and_purge(
    monkeypatch, payload, candidate, tmp_path
):
    transport(monkeypatch, payload)
    store = structure_store(tmp_path)
    chat, report = report_fixture(store.workspace, candidate)
    other, other_report = report_fixture(store.workspace, candidate)
    with pytest.raises(WorkspaceNotFound):
        store.retrieve(other, report, NOMAD_ID)
    with pytest.raises(WorkspaceNotFound):
        store.retrieve(chat, report, "mp-149")
    store.retrieve(chat, report, NOMAD_ID)
    project = store.workspace.create_project("Destination")
    store.workspace.update_chat(chat, project_id=project["id"])
    assert store.content(chat, report, NOMAD_ID)[0]
    store.workspace.archive_project(project["id"])
    with pytest.raises(WorkspaceNotFound):
        store.content(chat, report, NOMAD_ID)
    store.workspace.restore_project(project["id"])
    assert store.content(chat, report, NOMAD_ID)[0]
    store.workspace.archive_chat(chat)
    with pytest.raises(WorkspaceNotFound):
        store.content(chat, report, NOMAD_ID)
    store.workspace.purge_chat(chat, confirm=True)
    with store.workspace._connection() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM report_structures").fetchone()[0]
            == 0
        )
    assert store.list(other, other_report)["structures"][0]["status"] == "not_loaded"


def test_cache_corruption_fails_closed(monkeypatch, payload, candidate, tmp_path):
    transport(monkeypatch, payload)
    store = structure_store(tmp_path)
    chat, report = report_fixture(store.workspace, candidate)
    store.retrieve(chat, report, NOMAD_ID)
    with store.workspace._connection(write=True) as connection:
        connection.execute("UPDATE report_structures SET structure_json='{}'")
    with pytest.raises(structures.StructureUnavailable):
        store.content(chat, report, NOMAD_ID)


def test_metadata_key_requirement_and_old_empty_reports(tmp_path):
    store = structure_store(tmp_path)
    chat, report = report_fixture(
        store.workspace,
        {
            "material_id": "mp-149",
            "formula": "Si",
            "source_mode": "live_materials_project",
        },
    )
    assert store.list(chat, report)["structures"][0]["status"] == "connection_required"
    with pytest.raises(structures.StructureConnectionRequired):
        store.retrieve(chat, report, "mp-149")
    chat2 = store.workspace.create_global_chat("Scaffold")
    detail = store.workspace.append_global_message(chat2["id"], "Test", load_config())
    assert store.list(chat2["id"], detail["reports"][0]["id"])["structures"] == []


def test_display_formula_does_not_change_source_identity_cache_or_cif(
    tmp_path, monkeypatch
):
    # Synthetic coordinates test presentation only; no claim about a real phase.
    candidate = {
        "material_id": "nomad:formula-order-test",
        "formula": "O2Si",
        "source_mode": "live_nomad",
    }
    cell = [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]]
    sites = [["Si", [0.0, 0.0, 0.0]], ["O", [0.25, 0.0, 0.0]], ["O", [0.5, 0, 0]]]
    calls = []

    def fetch(saved_candidate):
        calls.append(deepcopy(saved_candidate))
        assert saved_candidate == candidate
        return cell, sites, "a" * 64, "unused-test-url", "nomad_structure_original"

    monkeypatch.setattr(structures, "_nomad", fetch)
    store = structure_store(tmp_path)
    chat, report = report_fixture(store.workspace, candidate)
    original = deepcopy(store.workspace.get_global_chat(chat))
    unloaded = store.list(chat, report)["structures"][0]
    assert unloaded["formula"] == "SiO2"
    assert unloaded["source_formula"] == "O2Si"
    metadata = store.retrieve(chat, report, candidate["material_id"])
    assert metadata["formula"] == "SiO2"
    assert metadata["source_formula"] == "O2Si"
    assert metadata["material_id"] == candidate["material_id"]
    body, repeated = store.content(chat, report, candidate["material_id"])
    with store.workspace._connection() as connection:
        cache_before = connection.execute(
            "SELECT structure_json, sha256 FROM report_structures"
        ).fetchone()
    cached = json.loads(cache_before[0])
    assert body == structures._cif(cached)
    assert metadata["sha256"] == repeated["sha256"] == hashlib.sha256(body).hexdigest()

    # Disabling this display transform simulates the prior renderer: the same
    # cached atoms, validation, response digest and CIF bytes must be retained.
    monkeypatch.setattr(structures, "display_formula", lambda value: value)
    old_body, old_metadata = store.content(chat, report, candidate["material_id"])
    assert old_metadata["formula"] == "O2Si"
    assert old_body == body
    assert old_metadata["sha256"] == metadata["sha256"]
    with store.workspace._connection() as connection:
        assert (
            connection.execute(
                "SELECT structure_json, sha256 FROM report_structures"
            ).fetchone()
            == cache_before
        )
    assert store.workspace.get_global_chat(chat) == original
    assert len(calls) == 1


@pytest.mark.parametrize("formula", [None, 12, ["Si"], {"formula": "Si"}])
def test_malformed_saved_formula_fails_with_structure_validation(tmp_path, formula):
    store = structure_store(tmp_path)
    chat, report = report_fixture(
        store.workspace,
        {"material_id": NOMAD_ID, "formula": formula, "source_mode": "live_nomad"},
    )
    with pytest.raises(structures.StructureUnavailable, match="formula is invalid"):
        store.list(chat, report)


@pytest.fixture
def dielectric_geometry():
    # Synthetic geometry and identity exercise the exact-release boundary only.
    # These coordinates are never a scientific demonstration or production row.
    structure = {
        "@module": "must.never.import",
        "@class": "MustNeverInstantiate",
        "lattice": {"matrix": [[4, 0, 0], [0, 4, 0], [0, 0, 4]]},
        "sites": [
            {"species": [{"element": symbol, "occu": 1}], "abc": position}
            for symbol, position in (
                ("Si", [0, 0, 0]),
                ("O", [0.25, 0, 0]),
                ("O", [0.5, 0, 0]),
            )
        ],
    }
    record = {
        "material_id": "dielectric:mp-123",
        "source_record_id": "mp-123",
        "formula": "O2Si",
        "nsites": 3,
        "source_mode": "live_public_dielectric",
        "provenance": {
            "source_url": structures.dielectric.DATASET_URL,
            "dataset_version": structures.dielectric.DATASET_VERSION,
            "source_record_id": "mp-123",
            "upstream_row_index": 0,
            "response_sha256": structures.dielectric.UPSTREAM_SHA256,
            "upstream_row_sha256": hashlib.sha256(
                json.dumps(structure, sort_keys=True).encode()
            ).hexdigest(),
        },
    }
    return record, {**deepcopy(record), "structure": structure}


def test_exact_release_structure_api_keeps_source_atoms_and_report_immutable(
    tmp_path, monkeypatch, dielectric_geometry
):
    candidate, source = dielectric_geometry
    calls = []

    def retrieve(identity):
        assert identity == candidate["material_id"]
        calls.append(identity)
        return deepcopy(source)

    monkeypatch.setattr(structures.dielectric, "retrieve_structure_source", retrieve)
    monkeypatch.setattr(
        structures, "_request_mp_data", lambda *a, **k: pytest.fail("Current MP join")
    )
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    with TestClient(app, base_url="http://127.0.0.1:8123") as client:
        chat, report = report_fixture(app.state.workspace_store, candidate)
        original = deepcopy(app.state.workspace_store.get_global_chat(chat))
        path = f"/api/chats/{chat}/reports/{report}/structures"
        assert client.get(path).json()["structures"][0]["status"] == "not_loaded"
        headers = {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"]}
        response = client.post(path + "/" + candidate["material_id"], headers=headers)
        assert response.status_code == 200, response.text
        metadata = response.json()
        assert metadata["formula"] == "SiO2" and metadata["source_formula"] == "O2Si"
        assert metadata["representation"] == "public_dielectric_structure"
        assert "No current Materials Project" in metadata["caveats"][-1]
        download = client.get(metadata["download_url"])
        assert download.status_code == 200
        assert (
            b"Si1 Si 0.000000000000 0.000000000000 0.000000000000 1" in download.content
        )
        assert b"must.never.import" not in download.content
        assert b"MustNeverInstantiate" not in download.content
        assert hashlib.sha256(download.content).hexdigest() == metadata["sha256"]
        assert client.get(metadata["content_url"]).content == download.content
        assert client.post(path + "/mp-123", headers=headers).status_code == 404
        assert (
            client.post(path + "/dielectric:mp-123:row0", headers=headers).status_code
            == 404
        )
        assert app.state.workspace_store.get_global_chat(chat) == original
        assert calls == [candidate["material_id"]]


@pytest.mark.parametrize(
    "mutation",
    [
        "identity",
        "release",
        "response_digest",
        "row_digest",
        "row_index",
        "formula",
        "count",
        "nonperiodic",
        "occupancy",
        "nonfinite",
        "left_handed",
        "unknown_element",
        "missing_lattice",
        "provenance_type",
    ],
)
def test_dataset_structure_rejects_mismatched_release_or_geometry(
    monkeypatch, dielectric_geometry, mutation
):
    candidate, source = dielectric_geometry
    if mutation == "identity":
        source["material_id"] = "dielectric:mp-124"
    elif mutation == "release":
        source["provenance"]["dataset_version"] = "A different release"
    elif mutation == "response_digest":
        source["provenance"]["response_sha256"] = "b" * 64
    elif mutation == "row_digest":
        source["provenance"]["upstream_row_sha256"] = "b" * 64
    elif mutation == "row_index":
        source["provenance"]["upstream_row_index"] = 1
    elif mutation == "formula":
        source["formula"] = "Si"
    elif mutation == "count":
        source["nsites"] = 4
    elif mutation == "nonperiodic":
        source["structure"]["lattice"]["pbc"] = [True, False, True]
    elif mutation == "occupancy":
        source["structure"]["sites"][0]["species"][0]["occu"] = 0.5
    elif mutation == "nonfinite":
        source["structure"]["sites"][0]["abc"][0] = float("nan")
    elif mutation == "left_handed":
        source["structure"]["lattice"]["matrix"][0][0] = -4
    elif mutation == "unknown_element":
        source["structure"]["sites"][0]["species"][0]["element"] = "MadeUp"
    elif mutation == "missing_lattice":
        source["structure"].pop("lattice")
    elif mutation == "provenance_type":
        source["provenance"] = []
    monkeypatch.setattr(
        structures.dielectric, "retrieve_structure_source", lambda _: source
    )
    with pytest.raises(structures.StructureUnavailable):
        structures._dielectric(candidate)


def test_structure_api_csrf_content_type_and_cached_download_without_network(
    tmp_path, monkeypatch, payload, candidate
):
    calls = transport(monkeypatch, payload)
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    with TestClient(app, base_url="http://127.0.0.1:8123") as client:
        chat, report = report_fixture(app.state.workspace_store, candidate)
        path = f"/api/chats/{chat}/reports/{report}/structures"
        assert client.get(path).json()["structures"][0]["status"] == "not_loaded"
        assert not calls
        assert client.post(path + "/" + NOMAD_ID).status_code == 403
        headers = {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"]}
        assert (
            client.post(
                path + "/" + NOMAD_ID,
                headers={**headers, "Origin": "https://attacker.invalid"},
            ).status_code
            == 403
        )
        response = client.post(path + "/" + NOMAD_ID, headers=headers)
        assert response.status_code == 200
        ready = response.json()
        download = client.get(ready["download_url"])
        assert download.status_code == 200
        assert download.headers["content-type"] == "chemical/x-cif"
        assert download.headers["content-disposition"].startswith("attachment;")
        assert download.headers["x-structure-sha256"] == ready["sha256"]
        assert client.get(ready["content_url"]).content == download.content
        assert len(calls) == 1
        assert client.post(path + "/mp-1", headers=headers).status_code == 404


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (
            structures.PublicSourceError("PRIVATE_PROVIDER_DIAGNOSTIC"),
            "structure_source_unavailable",
        ),
        (
            structures.StructureUnavailable(
                "PRIVATE_PROVIDER_DIAGNOSTIC", code="structure_access_unverified"
            ),
            "structure_access_unverified",
        ),
        (
            structures.StructureUnavailable(
                "PRIVATE_PROVIDER_DIAGNOSTIC", code="unexpected_code"
            ),
            "structure_invalid",
        ),
        *[
            (
                structures.hybrid3.StructureSourceError(
                    "PRIVATE_PROVIDER_DIAGNOSTIC", code=code
                ),
                code,
            )
            for code in (
                "structure_missing",
                "structure_ambiguous",
                "structure_search_incomplete",
            )
        ],
    ],
)
def test_structure_failure_codes_are_fixed_and_do_not_cache_substitutes(
    tmp_path, monkeypatch, candidate, failure, expected_code
):
    def unavailable(_candidate):
        raise failure

    monkeypatch.setattr(structures, "_nomad", unavailable)
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    with TestClient(app, base_url="http://127.0.0.1:8123") as client:
        chat, report = report_fixture(app.state.workspace_store, candidate)
        path = f"/api/chats/{chat}/reports/{report}/structures"
        headers = {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"]}
        response = client.post(path + "/" + NOMAD_ID, headers=headers)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == expected_code
        assert "PRIVATE_PROVIDER_DIAGNOSTIC" not in response.text
        assert client.get(path).json()["structures"][0]["status"] == "not_loaded"
        assert client.get(path + "/" + NOMAD_ID + "/download").status_code == 404


def test_unverified_public_access_has_distinct_structure_failure(
    monkeypatch, payload, candidate
):
    payload["data"][0]["archive"]["metadata"]["published"] = False
    transport(monkeypatch, payload)
    with pytest.raises(structures.StructureUnavailable) as caught:
        structures._nomad(candidate)
    assert caught.value.code == "structure_access_unverified"
