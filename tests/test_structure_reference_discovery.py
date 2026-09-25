"""Synthetic navigation responses: no live scientific results or
credentials."""

import json
from copy import deepcopy
from urllib.parse import quote, urlencode

import pytest
from test_literature_structures import (
    literature_report,
    publication_reference,
    report_bytes,
)
from test_structures import structure_store

from labcat import structures
from labcat.science.retrieval_budget import bounded_deadline


@pytest.fixture(autouse=True)
def offline_name_resolution(monkeypatch):
    monkeypatch.setattr(
        structures.structure_identity, "lookup_name", lambda *args: None
    )


def name_receipt(name="test oxide", formula="ZnMoO4"):
    """Invented test-only identity receipt; never a scientific
    result."""
    return {
        "source_id": "pubchem",
        "record_id": "9999999991",
        "url": "https://pubchem.ncbi.nlm.nih.gov/compound/9999999991",
        "query_name": name,
        "matched_name": name,
        "formula": formula,
        "retrieved_at": "2026-09-23T00:00:00+00:00",
        "property_url": "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
        + quote(name, safe="")
        + "/property/MolecularFormula/JSON?name_type=complete",
        "synonyms_url": (
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/9999999991/"
            "synonyms/JSON"
        ),
        "property_sha256": "b" * 64,
        "synonyms_sha256": "c" * 64,
        "scope": "composition_reference_only",
        "phase_match": "unverified",
    }


def name_transport(monkeypatch, receipt):
    calls = []

    def lookup(name, deadline):
        assert name == "test oxide"
        assert 0 < deadline - structures.time.monotonic() <= 18
        calls.append(name)
        return deepcopy(receipt)

    monkeypatch.setattr(structures.structure_identity, "lookup_name", lookup)
    return calls


def mp_url(formula="ZnMoO4"):
    return "https://api.materialsproject.org/materials/summary/?" + urlencode(
        {
            "formula": formula,
            "deprecated": "false",
            "id_format": "legacy",
            "_fields": ",".join(structures.MP_FIELDS),
            "_limit": structures.MAX_RECORDS,
            "_skip": 0,
            "_sort_fields": "material_id",
        }
    )


def mp_row(identity="mp-9999999991", formula="ZnMoO4"):
    return {
        "material_id": identity,
        "formula_pretty": formula,
        "deprecated": False,
        "elements": [element for element, _ in structures._composition(formula)],
    }


def mp_transport(store, monkeypatch, rows=None, *, selectable=True):
    store.connections.source_connections = lambda: {
        "materials_project": {"selectable": selectable}
    }
    # Deliberately invalid as a real key; only the patched adapter sees it.
    store.connections.materials_project_key = lambda mode: "TEST ONLY"
    calls = []

    def request(key, filters):
        assert key == "TEST ONLY"
        assert filters == {"formula": "ZnMoO4"}
        assert 0 < bounded_deadline(60) - structures.time.monotonic() <= 18
        calls.append(filters)
        return (
            {"data": deepcopy(rows if rows is not None else [mp_row()])},
            "a" * 64,
            mp_url(),
        )

    monkeypatch.setattr(structures, "_request_mp_data", request)
    return calls


def formula_report(store, *, numeric=None, name="ZnMoO4"):
    return literature_report(
        store, names=(name,), refs=[publication_reference(name)], numeric=numeric
    )


def test_literal_formula_hint_is_linked_only_after_source_validation(
    tmp_path, monkeypatch
):
    store = structure_store(tmp_path)
    chat, report, leads, _ = formula_report(store)
    original = report_bytes(store)
    calls = mp_transport(store, monkeypatch)
    before = store.list(chat, report)
    assert before["structures"] == []
    assert before["literature_candidates"][0]["status"] == "reference_lookup_available"
    result = store.discover_references(chat, report, enabled_sources=[])
    assert len(calls) == 1
    assert result["literature_candidates"][0]["status"] == "references_found"
    row = result["structures"][0]
    assert row["material_id"] == "mp-9999999991" and row["status"] == "not_loaded"
    assert row["literature_association"] == {
        "relation": "composition_reference",
        "phase_match": "unverified",
        "lead_ids": [leads[0]["id"]],
        "lead_names": ["ZnMoO4"],
    }
    assert store.discover_references(chat, report, enabled_sources=[]) == result
    assert len(calls) == 1 and report_bytes(store) == original
    with store.workspace._connection() as connection:
        cache = json.loads(
            connection.execute(
                "SELECT lookup_json FROM report_structure_references"
            ).fetchone()[0]
        )
    assert cache["version"] == 3
    assert cache["references"][0]["response_sha256"] == "a" * 64
    assert cache["references"][0]["request_url"] == mp_url()
    assert "TEST ONLY" not in json.dumps(cache)


@pytest.mark.parametrize(
    "mode,selectable", [("off", True), ("snapshot", True), ("auto", False)]
)
def test_mp_discovery_respects_selection_and_verified_connection(
    tmp_path, monkeypatch, mode, selectable
):
    store = structure_store(tmp_path)
    chat, report, _, _ = formula_report(store)
    calls = mp_transport(store, monkeypatch, selectable=selectable)
    result = store.discover_references(
        chat, report, enabled_sources=[], materials_project_mode=mode
    )
    assert not calls and result["structures"] == []


def test_explicit_discovery_prepares_saved_connection_within_shared_budget(
    tmp_path, monkeypatch
):
    store = structure_store(tmp_path)
    chat, report, _, _ = formula_report(store)
    calls = mp_transport(store, monkeypatch, selectable=False)
    preparations = []

    def prepare(mode):
        preparations.append(mode)
        assert 0 < bounded_deadline(60) - structures.time.monotonic() <= 18
        store.connections.source_connections = lambda: {
            "materials_project": {"selectable": True}
        }

    store.connections.prepare_materials_project = prepare
    assert store.list(chat, report)["structures"] == [] and not preparations
    result = store.discover_references(
        chat, report, enabled_sources=[], materials_project_mode="auto"
    )
    assert preparations == ["auto"] and len(calls) == 1
    assert result["structures"][0]["status"] == "not_loaded"


@pytest.mark.parametrize(
    "mutation",
    [
        "formula",
        "identity",
        "deprecated",
        "elements",
        "duplicate",
        "oversized",
        "digest",
        "request_host",
        "request_formula",
        "request_credential",
    ],
)
def test_mp_reference_response_rejects_unbound_or_unsafe_identities(
    tmp_path, monkeypatch, mutation
):
    store = structure_store(tmp_path)
    chat, report, _, _ = formula_report(store)
    rows = [mp_row()]
    if mutation == "formula":
        rows[0]["formula_pretty"] = "SiO2"
    elif mutation == "identity":
        rows[0]["material_id"] = "mp-1/instructions"
    elif mutation == "deprecated":
        rows[0]["deprecated"] = True
    elif mutation == "elements":
        rows[0]["elements"] = ["Si", "O"]
    elif mutation == "duplicate":
        rows *= 2
    elif mutation == "oversized":
        rows *= structures.MAX_RECORDS + 1
    calls = mp_transport(store, monkeypatch, rows)
    original_request = structures._request_mp_data
    if mutation in {"digest", "request_host", "request_formula", "request_credential"}:

        def request(*args):
            payload, digest, url = original_request(*args)
            if mutation == "digest":
                digest = "invalid"
            elif mutation == "request_host":
                url = url.replace("api.materialsproject.org", "example.org")
            elif mutation == "request_formula":
                url = mp_url("SiO2")
            else:
                url += "&api_key=TESTONLY"
            return payload, digest, url

        monkeypatch.setattr(structures, "_request_mp_data", request)
    result = store.discover_references(chat, report, enabled_sources=[])
    assert len(calls) == 1 and not result["structures"]
    assert result["literature_candidates"][0]["status"] == "reference_lookup_failed"
    assert store.discover_references(chat, report, enabled_sources=[]) == result
    assert len(calls) == 1


def test_existing_numeric_formula_reference_retains_properties_without_network(
    tmp_path, monkeypatch
):
    store = structure_store(tmp_path)
    numeric = {
        "material_id": "mp-9999999991",
        "formula": "MoO4Zn",
        "source_mode": "live_materials_project",
        "sentinel": "preserve property record",
    }
    chat, report, leads, _ = formula_report(store, numeric=[numeric])
    original = report_bytes(store)
    monkeypatch.setattr(
        structures, "_request_mp_data", lambda *a, **k: pytest.fail("network")
    )
    result = store.discover_references(chat, report)
    assert result["literature_candidates"][0]["status"] == "references_found"
    association = result["structures"][0]["literature_association"]
    assert association["lead_ids"] == [leads[0]["id"]]
    assert association["phase_match"] == "unverified"
    with store.workspace._connection() as connection:
        candidate = store._candidates(connection, chat, report)[0]
    assert {key: candidate[key] for key in numeric} == numeric
    assert report_bytes(store) == original


def test_formula_hint_does_not_reduce_molecular_counts_into_numeric_record(tmp_path):
    store = structure_store(tmp_path)
    numeric = {
        "material_id": "mp-9999999991",
        "formula": "CH",
        "source_mode": "live_materials_project",
    }
    chat, report, _, _ = formula_report(store, numeric=[numeric], name="C6H6")
    result = store.list(chat, report)
    assert "literature_association" not in result["structures"][0]


def test_mp_discovery_caps_returned_reference_choices(tmp_path, monkeypatch):
    store = structure_store(tmp_path)
    chat, report, _, _ = formula_report(store)
    calls = mp_transport(
        store, monkeypatch, [mp_row(f"mp-{900000 + i}") for i in range(8)]
    )
    result = store.discover_references(chat, report, enabled_sources=[])
    assert (
        len(calls) == 1
        and len(result["structures"]) == structures.MAX_REFERENCE_RECORDS
    )


def test_literal_hint_does_not_revive_an_old_untyped_cache(tmp_path, monkeypatch):
    store = structure_store(tmp_path)
    chat, report, _, _ = formula_report(store)
    mp_transport(store, monkeypatch)
    store.discover_references(chat, report, enabled_sources=[])
    with store.workspace._connection(write=True) as connection:
        cache = json.loads(
            connection.execute(
                "SELECT lookup_json FROM report_structure_references"
            ).fetchone()[0]
        )
        cache["version"] = 2
        encoded = structures.canonical(cache)
        connection.execute(
            "UPDATE report_structure_references SET lookup_json=?,sha256=?",
            (encoded.decode(), structures.hashlib.sha256(encoded).hexdigest()),
        )
    assert store.list(chat, report)["structures"] == []


def test_structure_retrieval_preparation_shares_budget_and_concurrency_guard(
    tmp_path, monkeypatch
):
    store = structure_store(tmp_path)
    identity = "mp-9999999991"
    numeric = {
        "material_id": identity,
        "formula": "ZnMoO4",
        "source_mode": "live_materials_project",
    }
    chat, report, _, _ = formula_report(store, numeric=[numeric])
    preparations = []
    store.connections.materials_project_key = lambda mode: "TEST ONLY"

    def prepare(mode):
        preparations.append(mode)
        assert 0 < bounded_deadline(60) - structures.time.monotonic() <= 18

    def retrieve(candidate, key):
        assert key == "TEST ONLY" and candidate["material_id"] == identity
        assert 0 < bounded_deadline(60) - structures.time.monotonic() <= 18
        return (
            [[5, 0, 0], [0, 5, 0], [0, 0, 5]],
            [[element, [0, 0, 0]] for element in ["Zn", "Mo", "O", "O", "O", "O"]],
            "a" * 64,
            mp_url(),
            "mp_summary_structure",
        )

    store.connections.prepare_materials_project = prepare
    monkeypatch.setattr(structures, "_mp", retrieve)
    assert structures._NETWORK_SLOTS.acquire(blocking=False)
    assert structures._NETWORK_SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(structures.StructureUnavailable) as error:
            store.retrieve(chat, report, identity)
        assert error.value.code == "structure_busy" and not preparations
    finally:
        structures._NETWORK_SLOTS.release()
        structures._NETWORK_SLOTS.release()
    assert store.retrieve(chat, report, identity)["status"] == "ready"
    assert preparations == ["api"]
    store.retrieve(chat, report, identity)
    assert preparations == ["api"]


@pytest.mark.parametrize("numeric_available", [True, False])
def test_source_resolved_name_links_numeric_or_mp_records_and_caches_receipt(
    tmp_path, monkeypatch, numeric_available
):
    store = structure_store(tmp_path)
    numeric = (
        [
            {
                "material_id": "mp-9999999991",
                "formula": "ZnMoO4",
                "source_mode": "live_materials_project",
            }
        ]
        if numeric_available
        else None
    )
    chat, report, leads, _ = formula_report(store, numeric=numeric, name="test oxide")
    original = report_bytes(store)
    names = name_transport(monkeypatch, name_receipt())
    mp_calls = mp_transport(store, monkeypatch)
    before = store.list(chat, report)
    assert not names and not mp_calls
    assert before["literature_candidates"][0]["status"] == "reference_lookup_available"
    result = store.discover_references(chat, report, enabled_sources=[])
    assert names == ["test oxide"] and len(mp_calls) == (0 if numeric_available else 1)
    assert result["literature_candidates"][0]["status"] == "references_found"
    assert result["structures"][0]["literature_association"] == {
        "relation": "composition_reference",
        "phase_match": "unverified",
        "lead_ids": [leads[0]["id"]],
        "lead_names": ["test oxide"],
    }
    assert store.discover_references(chat, report, enabled_sources=[]) == result
    assert names == ["test oxide"] and report_bytes(store) == original
    with store.workspace._connection() as connection:
        cache = json.loads(
            connection.execute(
                "SELECT lookup_json FROM report_structure_references"
            ).fetchone()[0]
        )
    assert cache["version"] == 4 and cache["identity_status"] == "resolved"
    assert cache["identity_resolution"] == name_receipt()


def test_unresolved_name_is_cached_without_passive_queries_and_allows_explicit_retry(
    tmp_path, monkeypatch
):
    store = structure_store(tmp_path)
    chat, report, leads, _ = formula_report(store, name="test oxide")
    names = name_transport(monkeypatch, None)
    mp_calls = mp_transport(store, monkeypatch)
    result = store.discover_references(chat, report, enabled_sources=[])
    assert names == ["test oxide"] and not mp_calls and not result["structures"]
    assert result["literature_candidates"][0]["status"] == "no_reference_matches"
    assert "did not establish" in result["literature_candidates"][0]["reason"]
    assert "Retry" in result["literature_candidates"][0]["reason"]
    assert store.list(chat, report) == result
    assert store.discover_references(chat, report, enabled_sources=[]) == result
    assert names == ["test oxide"]
    retries = name_transport(monkeypatch, name_receipt())
    retried = store.find_references(chat, report, leads[0]["id"], enabled_sources=[])
    assert retries == ["test oxide"] and len(mp_calls) == 1
    assert retried["literature_candidates"][0]["status"] == "references_found"
    assert len(retried["structures"]) == 1


@pytest.mark.parametrize("mode", ["off", "snapshot"])
def test_disabled_repositories_do_not_resolve_names(tmp_path, monkeypatch, mode):
    store = structure_store(tmp_path)
    chat, report, _, _ = formula_report(store, name="test oxide")
    names = name_transport(monkeypatch, name_receipt())
    mp_calls = mp_transport(store, monkeypatch)
    result = store.discover_references(
        chat, report, enabled_sources=[], materials_project_mode=mode
    )
    assert not names and not mp_calls and not result["structures"]


@pytest.mark.parametrize(
    "mutation",
    [
        "name",
        "matched_name",
        "cid",
        "url",
        "formula",
        "hash",
        "phase",
        "scope",
        "digest",
    ],
)
def test_name_cache_is_revalidated_before_numeric_or_source_links(
    tmp_path, monkeypatch, mutation
):
    store = structure_store(tmp_path)
    chat, report, leads, _ = formula_report(store, name="test oxide")
    name_transport(monkeypatch, name_receipt())
    mp_transport(store, monkeypatch)
    store.discover_references(chat, report, enabled_sources=[])
    with store.workspace._connection(write=True) as connection:
        cache = json.loads(
            connection.execute(
                "SELECT lookup_json FROM report_structure_references"
            ).fetchone()[0]
        )
        receipt = cache["identity_resolution"]
        field, value = {
            "name": ("query_name", "another oxide"),
            "matched_name": ("matched_name", "another oxide"),
            "cid": ("record_id", "9999999992"),
            "url": ("url", "https://example.org/9999999991"),
            "formula": ("formula", "SiO2"),
            "hash": ("property_sha256", "invalid"),
            "phase": ("phase_match", "verified"),
            "scope": ("scope", "property_evidence"),
            "digest": ("formula", "ZnMoO4"),
        }[mutation]
        receipt[field] = value
        encoded = structures.canonical(cache)
        digest = (
            "invalid"
            if mutation == "digest"
            else structures.hashlib.sha256(encoded).hexdigest()
        )
        connection.execute(
            "UPDATE report_structure_references SET lookup_json=?,sha256=?",
            (encoded.decode(), digest),
        )
    with pytest.raises(structures.StructureUnavailable):
        store.list(chat, report)
    with pytest.raises(structures.StructureUnavailable):
        store.find_references(chat, report, leads[0]["id"], enabled_sources=[])


def test_invalid_name_response_does_not_create_formula_or_structure(
    tmp_path, monkeypatch
):
    store = structure_store(tmp_path)
    chat, report, _, _ = formula_report(store, name="test oxide")
    receipt = name_receipt()
    receipt["matched_name"] = "another oxide"
    name_transport(monkeypatch, receipt)
    calls = mp_transport(store, monkeypatch)
    result = store.discover_references(chat, report, enabled_sources=[])
    assert not calls and not result["structures"]
    assert result["literature_candidates"][0]["status"] == "no_reference_matches"


@pytest.mark.parametrize(
    "name,formula",
    [
        ("test oxide (ZnMoO4)", "ZnMoO4"),
        ("test oxide (ZnO)", "ZnO"),
        ("test oxide (HfO₂)", "HfO2"),
    ],
)
def test_whole_parenthesized_formula_only_selects_independent_numeric_reference(
    tmp_path, monkeypatch, name, formula
):
    store = structure_store(tmp_path)
    numeric = {
        "material_id": "mp-9999999991",
        "formula": formula,
        "source_mode": "live_materials_project",
    }
    chat, report, leads, _ = formula_report(store, numeric=[numeric], name=name)
    monkeypatch.setattr(
        structures.structure_identity,
        "lookup_name",
        lambda *args: pytest.fail("No alias resolution was requested"),
    )
    result = store.discover_references(
        chat, report, enabled_sources=[], materials_project_mode="off"
    )
    assert result["literature_candidates"][0]["status"] == "references_found"
    association = result["structures"][0]["literature_association"]
    assert association["phase_match"] == "unverified"
    assert association["relation"] == "composition_reference"
    assert association["lead_ids"] == [leads[0]["id"]]
    assert association["lead_names"] == [leads[0]["name"]]


@pytest.mark.parametrize(
    "name",
    [
        "PI",
        "NO",
        "C60",
        "Y6",
        "test oxide HfO2",
        "test oxide (HfO2) extra",
        "test polymer (C2H4)",
        "test nanocrystals (CsPbBr3)",
        "test composite (HfO2)",
        "test oxide (HfO2/ZrO2)",
        "test oxide (HfO)",
    ],
)
def test_labels_do_not_parse_arbitrary_substrings_or_replace_incompatible_atoms(
    tmp_path, name
):
    store = structure_store(tmp_path)
    numeric = {
        "material_id": "mp-9999999991",
        "formula": "HfO2",
        "source_mode": "live_materials_project",
    }
    chat, report, _, _ = formula_report(store, numeric=[numeric], name=name)
    result = store.list(chat, report)
    assert "literature_association" not in result["structures"][0]


def test_parenthesized_formula_without_source_match_is_only_a_pending_hint(tmp_path):
    store = structure_store(tmp_path)
    chat, report, _, _ = formula_report(store, name="test oxide (ZnO)")
    result = store.list(chat, report)
    assert not result["structures"]
    assert result["literature_candidates"][0]["status"] == "reference_lookup_available"


@pytest.mark.parametrize(
    "connection_status,expected",
    [
        ("verification_required", "not_loaded"),
        ("locked", "connection_required"),
        ("not_configured", "connection_required"),
        ("error", "connection_required"),
    ],
)
def test_existing_mp_structure_can_explicitly_verify_unlocked_saved_key(
    tmp_path, monkeypatch, connection_status, expected
):
    store = structure_store(tmp_path)
    identity = "mp-9999999991"
    numeric = {
        "material_id": identity,
        "formula": "ZnMoO4",
        "source_mode": "live_materials_project",
    }
    chat, report, _, _ = formula_report(store, numeric=[numeric])
    state = {"status": connection_status, "selectable": False}
    store.connections.source_connections = lambda: {"materials_project": dict(state)}
    preparations = []

    def prepare(mode):
        assert mode == "api" and state["status"] == "verification_required"
        preparations.append(mode)
        state.update(status="ready", selectable=True)

    store.connections.prepare_materials_project = prepare
    store.connections.materials_project_key = lambda mode: (
        "TEST ONLY" if state["selectable"] else None
    )
    monkeypatch.setattr(
        structures,
        "_mp",
        lambda candidate, key: (
            [[5, 0, 0], [0, 5, 0], [0, 0, 5]],
            [[element, [0, 0, 0]] for element in ["Zn", "Mo", "O", "O", "O", "O"]],
            "a" * 64,
            mp_url(),
            "mp_summary_structure",
        ),
    )
    listed = store.list(chat, report)["structures"][0]
    assert listed["status"] == expected and not preparations
    if expected == "not_loaded":
        assert "will be verified" in listed["reason"]
        assert store.retrieve(chat, report, identity)["status"] == "ready"
        assert preparations == ["api"]
        state.update(status="locked", selectable=False)
        assert store.list(chat, report)["structures"][0]["status"] == "ready"
        assert preparations == ["api"]


@pytest.mark.parametrize("enabled_sources", [[], ["nomad"]])
def test_returned_mp_probe_error_is_a_cached_failure_not_an_empty_search(
    tmp_path, monkeypatch, enabled_sources
):
    store = structure_store(tmp_path)
    chat, report, _, _ = formula_report(store)
    state = {"status": "verification_required", "selectable": False}
    store.connections.source_connections = lambda: {"materials_project": dict(state)}
    preparations = []

    def prepare(mode):
        preparations.append(mode)
        state.update(status="error", selectable=False)
        return None

    store.connections.prepare_materials_project = prepare
    monkeypatch.setattr(structures, "_search_nomad", lambda *args: ([], "TEST ONLY"))
    monkeypatch.setattr(
        structures, "_request_mp_data", lambda *a, **k: pytest.fail("Unverified key")
    )
    result = store.discover_references(chat, report, enabled_sources=enabled_sources)
    assert result["literature_candidates"][0]["status"] == "reference_lookup_failed"
    assert not result["structures"] and preparations == ["auto"]
    with store.workspace._connection() as connection:
        cache = json.loads(
            connection.execute(
                "SELECT lookup_json FROM report_structure_references"
            ).fetchone()[0]
        )
    assert cache["failed_sources"] == ["materials_project"]
    assert (
        store.discover_references(chat, report, enabled_sources=enabled_sources)
        == result
    )
    assert preparations == ["auto"]


@pytest.mark.parametrize("connection_status", ["not_configured", "locked"])
def test_missing_or_locked_key_does_not_become_a_failed_mp_search(
    tmp_path, monkeypatch, connection_status
):
    store = structure_store(tmp_path)
    chat, report, _, _ = formula_report(store)
    store.connections.source_connections = lambda: {
        "materials_project": {"status": connection_status, "selectable": False}
    }
    store.connections.prepare_materials_project = lambda mode: None
    monkeypatch.setattr(structures, "_search_nomad", lambda *args: ([], "TEST ONLY"))
    result = store.discover_references(chat, report, enabled_sources=["nomad"])
    assert result["literature_candidates"][0]["status"] == "no_reference_matches"
    with store.workspace._connection() as connection:
        cache = json.loads(
            connection.execute(
                "SELECT lookup_json FROM report_structure_references"
            ).fetchone()[0]
        )
    assert cache["failed_sources"] == []


@pytest.mark.parametrize(
    "failure", ["returned_error", "prepare_exception", "status_exception"]
)
def test_name_lookup_preserves_mp_preparation_failure_and_explicit_retry(
    tmp_path, monkeypatch, failure
):
    store = structure_store(tmp_path)
    chat, report, leads, _ = formula_report(store, name="test oxide")
    names = name_transport(monkeypatch, name_receipt())
    state = {"status": "verification_required", "selectable": False}

    def prepare(mode):
        if failure == "prepare_exception":
            raise structures.CredentialConnectionError("PRIVATE vault details")
        state.update(status="error", selectable=False)

    def readiness():
        if failure == "status_exception":
            raise structures.CredentialConnectionError("PRIVATE vault details")
        return {"materials_project": dict(state)}

    store.connections.prepare_materials_project = prepare
    store.connections.source_connections = readiness
    result = store.discover_references(chat, report, enabled_sources=[])
    assert (
        not names
        and result["literature_candidates"][0]["status"] == "reference_lookup_failed"
    )
    assert "PRIVATE" not in json.dumps(result)
    with store.workspace._connection() as connection:
        cache = json.loads(
            connection.execute(
                "SELECT lookup_json FROM report_structure_references"
            ).fetchone()[0]
        )
    assert cache["identity_status"] == "unavailable"
    assert cache["identity_resolution"] is None and cache["formula"] is None
    assert cache["failed_sources"] == ["materials_project"]
    assert store.discover_references(chat, report, enabled_sources=[]) == result
    calls = mp_transport(store, monkeypatch)
    store.connections.prepare_materials_project = lambda mode: None
    retried = store.find_references(chat, report, leads[0]["id"], enabled_sources=[])
    assert retried["literature_candidates"][0]["status"] == "references_found"
    assert names == ["test oxide"] and len(calls) == 1


def test_credential_status_error_keeps_saved_mp_record_readable(tmp_path):
    store = structure_store(tmp_path)
    numeric = {
        "material_id": "mp-9999999991",
        "formula": "ZnMoO4",
        "source_mode": "live_materials_project",
    }
    chat, report, _, _ = formula_report(store, numeric=[numeric])

    def unavailable():
        raise structures.CredentialConnectionError("PRIVATE vault details")

    store.connections.source_connections = unavailable
    listed = store.list(chat, report)
    assert listed["structures"][0]["status"] == "connection_required"
    assert "PRIVATE" not in json.dumps(listed)
