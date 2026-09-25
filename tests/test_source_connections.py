"""Only the current, explicitly verified credential can select an
optional API."""

import json
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from labcat import science
from labcat.agent_tools import ResearchToolSession
from labcat.config import load_config
from labcat.connections import ConnectionManager
from labcat.public_sources_api import create_public_sources_router
from labcat.research import research
from labcat.science.sources import SourceError
from labcat.source_preferences import (
    SourceConnectionRequired,
    SourcePreferencesStore,
    create_source_settings_router,
    default_source_preferences,
)
from labcat.workspace import WorkspaceStore

KEY = "fixture-only-materials-api-credential"
SECOND_KEY = "fixture-only-replacement-api-credential"
PHRASE = "fixture source vault passphrase"


def configure(manager, key=KEY, *, storage="session", forget=False):
    return manager.configure(
        {
            "profile": manager.status()["profile"],
            "secret_storage": storage,
            **(
                {"forget_secrets": ["materials_project"]}
                if forget
                else {"secrets": {"materials_project": key}}
            ),
        }
    )


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "labcat.science.sources.probe_connection",
        lambda key: {"records_checked": 1, "id_format": "legacy"},
    )
    return ConnectionManager(tmp_path / "workspace.sqlite3")


def readiness(manager):
    return manager.status()["source_connections"]["materials_project"]


def test_verification_is_bound_to_current_key_and_never_exposed_or_persisted(manager):
    assert readiness(manager)["status"] == "not_configured"
    configure(manager)
    assert readiness(manager)["status"] == "verification_required"
    assert manager.materials_project_key("auto") is None
    with pytest.raises(SourceConnectionRequired):
        manager.materials_project_key("api")
    assert manager.test("materials_project")["status"] == "ok"
    assert readiness(manager)["status"] == "ready"
    assert readiness(manager)["verified_at"]
    assert manager.materials_project_key("api") == KEY
    assert "fingerprint" not in json.dumps(manager.status())
    assert KEY not in json.dumps(manager.status())
    assert KEY not in manager.profile_path.read_text()
    configure(manager, SECOND_KEY)
    assert readiness(manager)["status"] == "verification_required"
    assert manager.materials_project_key("auto") is None
    manager.test("materials_project")
    assert manager.materials_project_key("api") == SECOND_KEY
    configure(manager, forget=True)
    assert readiness(manager)["status"] == "not_configured"


def test_direct_vault_key_change_cannot_reuse_verification(manager):
    configure(manager)
    manager.test("materials_project")
    manager.vault.update({"materials_project": SECOND_KEY}, [], "session")
    assert readiness(manager)["status"] == "verification_required"
    assert manager.materials_project_key("auto") is None


def test_research_prepares_saved_connection_once_without_weakening_accessor(
    manager, monkeypatch
):
    configure(manager)
    calls = []
    monkeypatch.setattr(
        "labcat.science.sources.probe_connection", lambda key: calls.append(key)
    )
    assert manager.materials_project_key("auto") is None
    manager.prepare_materials_project("off")
    manager.prepare_materials_project("snapshot")
    assert calls == []
    manager.prepare_materials_project("auto")
    manager.prepare_materials_project("api")
    assert calls == [KEY]
    assert manager.materials_project_key("auto") == KEY
    configure(manager, SECOND_KEY)
    manager.prepare_materials_project("auto")
    assert calls == [KEY, SECOND_KEY]


def test_failed_automatic_probe_is_not_repeated_for_every_candidate(
    manager, monkeypatch
):
    configure(manager)
    calls = []

    def fail(key):
        calls.append(key)
        raise SourceError("Unavailable")

    monkeypatch.setattr("labcat.science.sources.probe_connection", fail)
    manager.prepare_materials_project("auto")
    manager.prepare_materials_project("auto")
    assert calls == [KEY]
    assert readiness(manager)["status"] == "error"
    assert manager.materials_project_key("auto") is None


def test_parallel_preparation_uses_one_probe(manager, monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor

    configure(manager)
    calls = []

    def probe(key):
        calls.append(key)
        time.sleep(0.03)

    monkeypatch.setattr("labcat.science.sources.probe_connection", probe)
    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(manager.prepare_materials_project, ["auto"] * 3))
    assert calls == [KEY]


def test_preparation_lock_respects_structure_deadline(manager, monkeypatch):
    import time

    from labcat.credentials import ConnectionError
    from labcat.science.retrieval_budget import repository_budget

    configure(manager)
    monkeypatch.setattr(
        "labcat.science.sources.probe_connection",
        lambda key: pytest.fail("Unexpected probe"),
    )
    manager._mp_probe_lock.acquire()
    started = time.monotonic()
    try:
        with repository_budget(seconds=0.03), pytest.raises(ConnectionError):
            manager.prepare_materials_project("auto")
    finally:
        manager._mp_probe_lock.release()
    assert time.monotonic() - started < 0.5


def test_stale_probe_cannot_verify_a_replaced_key_even_if_changed_back(
    manager, monkeypatch
):
    configure(manager)

    def delayed_probe(key):
        configure(manager, SECOND_KEY)
        configure(manager, KEY)
        return {"records_checked": 1, "id_format": "legacy"}

    monkeypatch.setattr("labcat.science.sources.probe_connection", delayed_probe)
    result = manager.test("materials_project")
    assert result["status"] == "error"
    assert readiness(manager)["status"] == "verification_required"
    assert manager.materials_project_key("auto") is None


def test_failed_probe_and_actual_retrieval_invalidate_previous_success(
    manager, monkeypatch
):
    configure(manager)
    manager.test("materials_project")
    failed = {
        "result": {
            "retrieval": {
                "repository_attempts": [
                    {"repository": "materials_project", "status": "unavailable"}
                ]
            }
        }
    }
    manager.observe_source_result(failed, SECOND_KEY)
    assert readiness(manager)["selectable"] is True  # Another credential's failure.
    manager.observe_source_result(failed, KEY)
    assert readiness(manager)["status"] == "error"
    assert manager.materials_project_key("auto") is None
    manager.test("materials_project")

    def rejected(key):
        raise SourceError(
            "Materials Project returned HTTP 401; no response text retained."
        )

    monkeypatch.setattr("labcat.science.sources.probe_connection", rejected)
    assert manager.test("materials_project")["status"] == "error"
    assert readiness(manager)["status"] == "error"


def test_lock_unlock_and_restart_require_a_new_probe(manager):
    manager.vault_action({"action": "create", "passphrase": PHRASE})
    configure(manager, storage="encrypted")
    manager.test("materials_project")
    manager.vault_action({"action": "lock"})
    assert readiness(manager)["status"] == "locked"
    manager.vault_action({"action": "unlock", "passphrase": PHRASE})
    assert readiness(manager)["status"] == "verification_required"
    manager.test("materials_project")
    restarted = ConnectionManager(
        manager.profile_path.with_suffix("").with_suffix(".sqlite3")
    )
    assert readiness(restarted)["status"] == "locked"
    restarted.vault_action({"action": "unlock", "passphrase": PHRASE})
    assert readiness(restarted)["status"] == "verification_required"
    for path in manager.profile_path.parent.iterdir():
        if path.is_file():
            assert KEY.encode() not in path.read_bytes()


def test_source_selection_requires_verification_but_old_preferences_remain_readable(
    manager,
):
    store = SourcePreferencesStore(
        WorkspaceStore(manager.profile_path.parent / "sources.sqlite3")
    )
    store.initialize()
    selected = {**default_source_preferences(), "materials_project_mode": "api"}
    app = FastAPI()
    app.include_router(create_source_settings_router(store, manager))
    app.include_router(create_public_sources_router(manager))
    with TestClient(app) as client:
        configure(manager)
        assert client.put("/api/source-settings", json=selected).status_code == 409
        manager.test("materials_project")
        assert client.put("/api/source-settings", json=selected).json() == selected
        catalog = client.get("/api/public-sources").json()
        assert all(
            source["availability"]["selectable"] and not source["requires_credentials"]
            for source in catalog["sources"]
        )
        assert catalog["connected_sources"][0]["availability"]["selectable"]
        configure(manager, SECOND_KEY)
        assert client.get("/api/source-settings").json() == selected
        assert client.put("/api/source-settings", json=selected).status_code == 409
        assert not client.get("/api/public-sources").json()["connected_sources"][0][
            "availability"
        ]["selectable"]
        assert KEY not in client.get("/api/public-sources").text
        off = {**selected, "materials_project_mode": "off"}
        assert client.put("/api/source-settings", json=off).json() == off


@pytest.mark.parametrize("mode", ["auto", "off"])
def test_application_uses_keyless_sources_without_forwarding_an_unverified_key(
    manager, monkeypatch, tmp_path, authenticated_model_factory, mode
):
    manager = authenticated_model_factory(tmp_path / "model.sqlite3")
    configure(manager)

    def unavailable(key):
        raise SourceError("Public connection unavailable.")

    monkeypatch.setattr("labcat.science.sources.probe_connection", unavailable)
    calls = []
    monkeypatch.setattr(
        science,
        "retrieve_live",
        lambda *args: pytest.fail("Unverified key reached source"),
    )
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda filters: (calls.append("nomad") or [], {})
    )
    preferences = {
        **default_source_preferences(),
        "materials_project_mode": mode,
        "search_public_references": False,
    }
    outcome = research(
        "Compare TiO2",
        load_config(),
        connections=manager,
        source_preferences=preferences,
    )
    assert calls == ["nomad"]
    assert outcome["result"]["candidates"] == []


@pytest.mark.parametrize("goose", [False, True])
@pytest.mark.parametrize("storage_failure", [False, True])
def test_unavailable_optional_api_preserves_healthy_source_results(
    manager,
    monkeypatch,
    tmp_path,
    authenticated_model_factory,
    historical_property_fixture,
    goose,
    storage_failure,
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose" if goose else "none")
    manager = authenticated_model_factory(tmp_path / "model.sqlite3")
    configure(manager)

    def unavailable_probe(key):
        raise SourceError("Public connection unavailable.")

    monkeypatch.setattr("labcat.science.sources.probe_connection", unavailable_probe)
    if storage_failure:
        from labcat.credentials import ConnectionError

        def unavailable(mode):
            raise ConnectionError("TEST ONLY private storage error")

        monkeypatch.setattr(manager, "materials_project_key", unavailable)
    monkeypatch.setattr(
        science, "retrieve_live", lambda *args: pytest.fail("Used an unverified key")
    )
    if goose:

        def run(prompt, context, session):
            session.call("assess_research_intent", {"decision": "materials_research"})
            session.call("generate_ranked_report", {})
            return {"provider": "openai", "runtime": "goose", "status": "completed"}

        monkeypatch.setattr(manager.agent, "run", run)
    outcome = research(
        "Compare TiO2",
        load_config(),
        connections=manager,
        source_preferences={
            **default_source_preferences(),
            "materials_project_mode": "api",
            "enabled_sources": ["nomad"],
            "search_public_references": False,
        },
    )
    assert outcome["stage"] == "partial"
    assert outcome["result"]["candidates"]
    attempts = outcome["result"]["retrieval"]["repository_attempts"]
    assert attempts[0]["repository"] == "materials_project"
    assert attempts[0]["status"] == "unavailable"
    assert any(
        row["repository"] == "nomad" and row["status"] == "ok" for row in attempts
    )
    for field in ("pi_summary", "technical_audit"):
        assert "Materials Project" in outcome[field]
        assert "Source availability" in outcome[field]
    assert KEY not in json.dumps(outcome)
    assert "TEST ONLY private storage error" not in json.dumps(outcome)


def test_verified_source_failure_blocks_reuse_and_off_is_respected(
    manager, monkeypatch, tmp_path, authenticated_model_factory
):
    manager = authenticated_model_factory(tmp_path / "model.sqlite3")
    configure(manager)
    manager.test("materials_project")
    calls = []

    def unavailable(key, filters):
        calls.append(key)
        raise SourceError("Public source unavailable")

    monkeypatch.setattr(science, "retrieve_live", unavailable)
    preferences = {**default_source_preferences(), "search_public_references": False}
    research(
        "Compare TiO2",
        load_config(),
        connections=manager,
        source_preferences=preferences,
    )
    assert readiness(manager)["status"] == "error"
    research(
        "Compare TiO2",
        load_config(),
        connections=manager,
        source_preferences=preferences,
    )
    assert calls == [KEY]
    manager.test("materials_project")
    research(
        "Compare TiO2",
        load_config(),
        connections=manager,
        source_preferences={**preferences, "materials_project_mode": "off"},
    )
    assert calls == [KEY]


def test_standalone_reference_api_obeys_deployment_controls(
    manager, monkeypatch, tmp_path, authenticated_model_factory
):
    from labcat.developer_settings import defaults

    manager = authenticated_model_factory(tmp_path / "model.sqlite3")
    policy = defaults()
    calls = []
    monkeypatch.setattr(
        "labcat.public_sources_api.search_public_sources",
        lambda *args, allow_preprints=True: (
            calls.append((args, allow_preprints)) or {"references": []}
        ),
    )
    app = FastAPI()
    app.include_router(create_public_sources_router(manager, lambda: deepcopy(policy)))
    with TestClient(app) as client:
        request = {"query": "TiO2", "sources": ["europe_pmc"], "limit": 10}
        policy["reference_search"] = False
        assert (
            client.post("/api/public-sources/search", json=request).status_code == 409
        )
        policy["reference_search"] = True
        policy["allow_preprints"] = False
        assert (
            client.post(
                "/api/public-sources/search", json={**request, "sources": ["arxiv"]}
            ).status_code
            == 422
        )
        assert not calls
        assert (
            client.post(
                "/api/public-sources/search", json={**request, "sources": ["chemrxiv"]}
            ).status_code
            == 422
        )
        policy["max_reference_results"] = 2
        assert (
            client.post("/api/public-sources/search", json=request).status_code == 200
        )
        assert calls[0][0][2] == 2
        assert calls[0][1] is False


@pytest.mark.parametrize("mode", ["auto", "api"])
def test_goose_does_not_use_a_key_revoked_while_the_model_is_planning(
    manager, monkeypatch, mode
):
    configure(manager)
    manager.test("materials_project")
    calls = []
    monkeypatch.setattr(
        science,
        "retrieve_live",
        lambda *args: pytest.fail("A revoked source key reached an API"),
    )
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda filters: (calls.append("nomad") or [], {})
    )
    preferences = {
        **default_source_preferences(),
        "materials_project_mode": mode,
        "search_public_references": False,
    }
    session = ResearchToolSession(
        "Compare TiO2",
        load_config(),
        source_preferences=preferences,
        key_supplier=lambda: manager.materials_project_key(mode),
    )
    configure(manager, forget=True)
    session.call("assess_research_intent", {"decision": "materials_research"})
    outcome = session.finalize()
    if mode == "api":
        assert outcome["stage"] == "blocked"
        assert not calls
    else:
        assert outcome["stage"] == "partial"
        assert calls == ["nomad"]
    assert outcome["result"]["candidates"] == []
    assert readiness(manager)["status"] == "not_configured"


@pytest.mark.parametrize("initially_connected", [False, True])
def test_goose_failure_invalidates_the_key_acquired_after_model_planning(
    tmp_path, monkeypatch, authenticated_model_factory, initially_connected
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    manager = authenticated_model_factory(tmp_path / "model.sqlite3")
    monkeypatch.setattr(
        "labcat.science.sources.probe_connection",
        lambda key: {"records_checked": 1, "id_format": "legacy"},
    )
    if initially_connected:
        configure(manager)
        manager.test("materials_project")
    keys_used = []

    def failed_repository(key, filters):
        keys_used.append(key)
        raise SourceError("Public source unavailable")

    def model_run(prompt, context, session):
        configure(manager, SECOND_KEY)
        manager.test("materials_project")
        session.call("assess_research_intent", {"decision": "materials_research"})
        session.call("generate_ranked_report", {})
        assert session._key is None
        return {"provider": "openai", "status": "completed"}

    monkeypatch.setattr(science, "retrieve_live", failed_repository)
    monkeypatch.setattr(manager.agent, "run", model_run)
    outcome = research(
        "Compare TiO2",
        load_config(),
        connections=manager,
        source_preferences={
            **default_source_preferences(),
            "search_public_references": False,
            "enabled_sources": [],
        },
    )
    assert keys_used == [SECOND_KEY]
    assert readiness(manager)["status"] == "error"
    assert manager.materials_project_key("auto") is None
    assert SECOND_KEY not in json.dumps(outcome)
    assert KEY not in json.dumps(outcome)
