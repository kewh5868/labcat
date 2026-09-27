"""Account changes during inference cannot consume or invalidate a newer
login."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import pytest
from test_agent_connections import Broker, auth_fixture

from labcat.agent_connections import _pack
from labcat.chatgpt_auth import goose_token_cache
from labcat.config import load_config
from labcat.connections import DEFAULT_PROFILE, ConnectionManager
from labcat.credentials import ConnectionBusy
from labcat.models import ModelBusy, ModelError
from labcat.research import research


class UnchangedBroker(Broker):
    """Metadata does not rotate the explicitly synthetic login
    fixture."""

    def metadata(self, auth):
        public, _ = super().metadata(auth)
        return public, deepcopy(auth)


@pytest.fixture
def connected_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    monkeypatch.delenv("LABCAT_VAULT_KEY", raising=False)
    monkeypatch.delenv("LABCAT_VAULT_KEY_FILE", raising=False)
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    manager.agent._auth = UnchangedBroker()
    identifiers = []
    for label in ("First fixture account", "Second fixture account"):
        identifier = manager.save_account(
            {
                "label": label,
                "profile": {
                    **DEFAULT_PROFILE,
                    "provider": "chatgpt",
                    "model": "test-model",
                    "allow_paid_inference": True,
                },
                "secret_storage": "session",
            }
        )["active_account_id"]
        manager.vault.update(
            {"oauth_" + identifier: _pack(auth_fixture())}, [], "session"
        )
        identifiers.append(identifier)
    manager.select_account(identifiers[0])
    assert manager.setup.verify()["can_research"]
    yield manager, *identifiers
    manager.agent.close()


def complete_login(manager, identifier):
    flow = manager.agent.start_login(identifier, {"secret_storage": "session"})
    manager.agent._auth.state = "complete"
    result = manager.agent.login_action(identifier, flow["flow_id"], "poll")
    assert result["status"] == "complete"


def test_running_goose_allows_select_login_and_verification_of_another_account(
    connected_accounts, monkeypatch
):
    manager, first, second = connected_accounts
    entered, release = Event(), Event()

    def worker(profile, secret, prompt, **kwargs):
        assert secret is None
        assert profile["model"] == "test-model"
        assert kwargs["chatgpt_tokens"] == goose_token_cache(auth_fixture())
        entered.set()
        assert release.wait(10), "The test did not release its worker"
        return {"status": "completed", "usage": None}

    def switch_and_reconnect():
        manager.select_account(second)
        complete_login(manager, second)
        assert manager.agent.metadata(second)["account_ready"]
        return manager.setup.verify()

    monkeypatch.setattr("labcat.goose_worker_client.run_remote_goose", worker)
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(manager.agent.run, "Fixture research", None, None)
        try:
            assert entered.wait(5)
            # Resolving before release proves that no inference lock gates login.
            ready = pool.submit(switch_and_reconnect).result(timeout=5)
            assert ready["can_research"]
            assert ready["model"]["account_id"] == second
        finally:
            release.set()
        result = running.result(timeout=5)
    assert result["account_id"] == first
    assert result["model"] == "test-model"
    assert manager.status()["active_account_id"] == second
    assert manager.setup.status() == ready
    assert manager.agent.usage()["last_run"] is None


def test_same_account_metadata_and_competing_run_are_bounded_while_inference_runs(
    connected_accounts, monkeypatch
):
    manager, first, _ = connected_accounts
    entered, release = Event(), Event()
    calls = []

    def worker(*args, **kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(10), "The test did not release its worker"
        return {"status": "completed", "usage": None}

    def competing_operations():
        with pytest.raises(ConnectionBusy):
            manager.agent.metadata(first)
        with pytest.raises(ModelBusy):
            manager.agent.run("Do not queue this request", None, None)

    monkeypatch.setattr("labcat.goose_worker_client.run_remote_goose", worker)
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(manager.agent.run, "Fixture research", None, None)
        try:
            assert entered.wait(5)
            pool.submit(competing_operations).result(timeout=5)
        finally:
            release.set()
        assert running.result(timeout=5)["account_id"] == first
    assert calls == [True]
    assert manager.agent.metadata(first)["account_ready"]


def test_failed_old_run_cannot_invalidate_newly_verified_account(
    connected_accounts, monkeypatch
):
    manager, _, second = connected_accounts
    entered, release = Event(), Event()

    def worker(*args, **kwargs):
        entered.set()
        assert release.wait(10), "The test did not release its worker"
        raise ModelError("Synthetic provider failure from the previous account")

    def switch_and_verify():
        manager.select_account(second)
        return manager.setup.verify()

    monkeypatch.setattr("labcat.goose_worker_client.run_remote_goose", worker)
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(
            research,
            "Find oxide dielectric candidates for thin-film experiments",
            load_config(),
            connections=manager,
        )
        try:
            assert entered.wait(5)
            ready = pool.submit(switch_and_verify).result(timeout=5)
            assert ready["can_research"]
        finally:
            release.set()
        with pytest.raises(ModelError, match="No report was saved"):
            running.result(timeout=5)
    assert manager.setup.status() == ready
    assert manager.status()["active_account_id"] == second


@pytest.mark.parametrize("worker_fails", [False, True])
def test_old_worker_refresh_cannot_overwrite_identical_fresh_login(
    connected_accounts, monkeypatch, worker_fails
):
    manager, first, _ = connected_accounts
    entered, release = Event(), Event()
    original = manager.vault.get("oauth_" + first)
    refreshed = goose_token_cache(auth_fixture())
    refreshed["refresh_token"] = "fixture-stale-worker-refresh"

    def worker(*args, **kwargs):
        assert kwargs["chatgpt_tokens"] == goose_token_cache(auth_fixture())
        entered.set()
        assert release.wait(10), "The test did not release its worker"
        if worker_fails:
            error = ModelError("Synthetic old worker failure")
            error.refreshed_chatgpt_tokens = refreshed
            raise error
        return {
            "status": "completed",
            "usage": None,
            "refreshed_chatgpt_tokens": refreshed,
        }

    monkeypatch.setattr("labcat.goose_worker_client.run_remote_goose", worker)
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(manager.agent.run, "Fixture research", None, None)
        try:
            assert entered.wait(5)
            pool.submit(complete_login, manager, first).result(timeout=5)
            # Value comparison cannot identify this explicit new credential event.
            assert manager.vault.get("oauth_" + first) == original
            assert not manager.setup.status()["can_research"]
        finally:
            release.set()
        if worker_fails:
            with pytest.raises(ModelError, match="Synthetic old worker failure"):
                running.result(timeout=5)
        else:
            result = running.result(timeout=5)
            assert result["status"] == "completed"
            assert result["account_id"] == first
            assert "refreshed_chatgpt_tokens" not in result
    assert manager.vault.get("oauth_" + first) == original
    assert manager.status()["active_account_id"] == first
    assert manager.setup.verify()["can_research"]


@pytest.mark.parametrize("metadata_fails", [False, True])
def test_late_verification_cannot_authorize_or_error_another_selected_account(
    connected_accounts, monkeypatch, metadata_fails
):
    manager, _, second = connected_accounts
    entered, release = Event(), Event()
    original_metadata = manager.agent._auth.metadata

    def metadata(document):
        entered.set()
        assert release.wait(10), "The test did not release its metadata response"
        if metadata_fails:
            raise ModelError("Synthetic metadata error for the previous account")
        return original_metadata(document)

    monkeypatch.setattr(manager.agent._auth, "metadata", metadata)
    with ThreadPoolExecutor(max_workers=2) as pool:
        checking = pool.submit(manager.setup.verify)
        try:
            assert entered.wait(5)
            selected = pool.submit(manager.select_account, second).result(timeout=5)
            assert selected["active_account_id"] == second
        finally:
            release.set()
        result = checking.result(timeout=5)
    assert result["model"]["account_id"] == second
    assert result["model"]["status"] == "verification_required"
    assert not result["can_research"]
    assert "previous account" not in result["model"]["message"]
    monkeypatch.setattr(manager.agent._auth, "metadata", original_metadata)
    assert manager.setup.verify()["can_research"]


@pytest.mark.parametrize("worker_fails", [False, True])
def test_report_model_identity_comes_from_captured_run_after_last_moment_switch(
    connected_accounts, monkeypatch, historical_property_fixture, worker_fails
):
    manager, first, second = connected_accounts
    original_metadata = manager.agent._auth.metadata

    def metadata(document):
        public, updated = original_metadata(document)
        public["models"].append({"id": "other-model", "label": "Other fixture model"})
        return public, updated

    monkeypatch.setattr(manager.agent._auth, "metadata", metadata)
    account = next(
        item for item in manager.status()["accounts"] if item["id"] == second
    )
    manager.save_account(
        {
            "label": account["label"],
            "profile": {**account["profile"], "model": "other-model"},
            "secret_storage": "session",
        },
        second,
    )
    manager.select_account(first)
    assert manager.setup.verify()["can_research"]
    original_run = manager.agent.run

    def run_after_switch(prompt, context, session):
        # Force the gap between research's preliminary status and actual capture.
        manager.select_account(second)
        assert manager.setup.verify()["can_research"]
        return original_run(prompt, context, session)

    def worker(profile, secret, prompt, **kwargs):
        assert profile["model"] == "other-model"
        session = kwargs["tool_session"]
        session.call("assess_research_intent", {"decision": "materials_research"})
        if worker_fails:
            error = ModelError("Synthetic failure after accepted assessment")
            # The application replaces provider-supplied identity with its snapshot.
            error.research_attempt = {"provider": "untrusted", "model": "untrusted"}
            raise error
        session.call("generate_ranked_report", {})
        return {"status": "completed", "usage": None}

    monkeypatch.setattr(manager.agent, "run", run_after_switch)
    monkeypatch.setattr("labcat.goose_worker_client.run_remote_goose", worker)
    monkeypatch.setattr("labcat.research._add_attribute_research", lambda *a, **k: None)
    outcome = research(
        "Find oxide dielectric candidates for thin-film experiments",
        load_config(),
        connections=manager,
    )
    execution = outcome["result"]["execution"]
    assert execution["provider"] == "chatgpt"
    assert execution["requested_model"] == "other-model"
    if worker_fails:
        assert execution["model_interrupted"] is True
        assert execution["attempted_model"] == "other-model"
    else:
        assert execution["agent"]["account_id"] == second
        assert execution["agent"]["model"] == "other-model"
