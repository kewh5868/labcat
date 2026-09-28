"""Provider limits are connection failures, never requests for more
science detail."""

import json
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from labcat import science
from labcat.config import load_config
from labcat.model_failures import (
    PROVIDER_FAILURE_MESSAGES,
    provider_failure_code,
    research_model_error,
)
from labcat.models import ModelError
from labcat.research import research
from labcat.source_preferences import default_source_preferences
from labcat.web import create_app

CANARY = "TEST_ONLY_PRIVATE_PROVIDER_BODY"


def failure(code):
    error = ModelError(CANARY)
    error.failure_code = code
    return error


@pytest.mark.parametrize("code", list(PROVIDER_FAILURE_MESSAGES))
@pytest.mark.parametrize("engine", ["direct", "goose"])
def test_known_provider_failure_never_asks_for_clarification_or_starts_retrieval(
    tmp_path, monkeypatch, authenticated_model_factory, code, engine
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", engine)
    manager = authenticated_model_factory(tmp_path / "model.sqlite3")
    assert manager.setup.verify()["can_research"]
    calls = []

    def failed(*args, **kwargs):
        calls.append(args[0])
        raise failure(code)

    monkeypatch.setattr(manager.agent, "run", failed)
    monkeypatch.setattr(manager, "plan", failed)
    monkeypatch.setattr(
        science, "run_research", lambda *a, **k: pytest.fail("Unexpected retrieval")
    )
    prompt = "Compare perovskite absorbers for a silicon tandem solar cell."
    with pytest.raises(ModelError) as caught:
        research(prompt, load_config(), connections=manager)
    assert provider_failure_code(caught.value) == code
    assert str(caught.value) == PROVIDER_FAILURE_MESSAGES[code]
    assert CANARY not in str(caught.value)
    assert calls == [prompt]
    assert manager.setup.status()["can_research"] is (code != "provider_authentication")


@pytest.mark.parametrize("code", list(PROVIDER_FAILURE_MESSAGES))
def test_api_retains_typed_failure_without_retry_or_clarification(
    tmp_path, monkeypatch, authenticated_app_models, code
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    calls = []

    def failed(*args, **kwargs):
        calls.append(args[0])
        raise failure(code)

    monkeypatch.setattr(app.state.connections.agent, "run", failed)
    with TestClient(app, base_url="http://localhost") as client:
        chat = client.post("/api/chats", json={"title": "Untitled chat"}).json()
        run_id = str(uuid4())
        prompt = "Find oxide materials for thin-film capacitors."
        path = f"/api/chats/{chat['id']}"
        response = client.post(
            path + "/messages", json={"content": prompt, "run_id": run_id}
        )
        assert response.status_code == 502
        assert response.json()["detail"] == {
            "code": "model_execution_failed",
            "failure_code": code,
            "setup_required": False,
            "message": PROVIDER_FAILURE_MESSAGES[code],
        }
        assert calls == [prompt]
        detail = client.get(path).json()
        assert detail["messages"] == detail["reports"] == []
        assert detail["chat"]["title"] != "Untitled chat"
        status = client.get(path + "/research-status?run_id=" + run_id).json()
        assert status["status"] == "failed"
        assert client.get("/api/research-runs").json() == {"runs": []}
        assert client.get("/api/connections").status_code == 200
        assert CANARY not in response.text + json.dumps(detail)


@pytest.mark.parametrize("code", [None, "raw error", CANARY, {}, [], 0, True])
def test_unrecognized_diagnostic_cannot_become_account_status(code):
    error = failure(code)
    assert provider_failure_code(error) is None
    assert provider_failure_code(research_model_error(error)) is None
    assert CANARY not in str(research_model_error(error))
    assert "No report was saved" in str(research_model_error(error))


@pytest.mark.parametrize("last_stage", ["assessment", "report"])
def test_late_credit_failure_preserves_evidence_and_explains_incomplete_report(
    tmp_path, monkeypatch, authenticated_model_factory, last_stage
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    manager = authenticated_model_factory(tmp_path / "model.sqlite3")
    historical = science.load_snapshot()
    calls = []
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda filters=None: deepcopy(historical)
    )
    monkeypatch.setattr("labcat.research._add_attribute_research", lambda *a, **k: None)

    def failed(prompt, context, session):
        calls.append(prompt)
        session.call("assess_research_intent", {"decision": "materials_research"})
        if last_stage == "report":
            session.call("generate_ranked_report", {})
        raise failure("provider_usage_limit")

    monkeypatch.setattr(manager.agent, "run", failed)
    result = research(
        "Find oxide dielectric materials",
        load_config(),
        connections=manager,
        source_preferences={
            **default_source_preferences(),
            "materials_project_mode": "off",
            "enabled_sources": ["nomad"],
            "search_public_references": False,
        },
    )
    assert len(calls) == 1
    assert result["stage"] == "partial"
    assert result["result"]["candidates"]
    assert result["result"]["execution"]["failure_code"] == "provider_usage_limit"
    for view in ("pi_summary", "technical_audit"):
        assert "exhausted its available credits or usage allowance" in result[view]
        assert "Changing your question will not resolve this" in result[view]
    assert CANARY not in json.dumps(result)
    assert manager.setup.status()["can_research"]


@pytest.mark.parametrize("transport_status", ["completed", "failed"])
def test_fresh_confirmed_limit_explains_a_missing_assessment(
    tmp_path, monkeypatch, authenticated_model_factory, transport_status
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    manager = authenticated_model_factory(tmp_path / "model.sqlite3")
    assert manager.setup.verify()["can_research"]
    captured = {
        "provider": "chatgpt",
        "model": "fixture-model",
        "account_id": "test-account",
    }
    diagnoses = []
    calls = []

    def run(prompt, context, session):
        calls.append(prompt)
        if transport_status == "failed":
            error = ModelError(CANARY)
            error.research_attempt = {
                "provider": captured["provider"],
                "model": captured["model"],
            }
            error.research_account_id = captured["account_id"]
            raise error
        return {**captured, "status": "completed"}

    def diagnose(attempt):
        diagnoses.append({key: attempt[key] for key in captured})
        return "provider_usage_limit"

    monkeypatch.setattr(manager.agent, "run", run)
    monkeypatch.setattr(manager.agent, "failure_after_missing_assessment", diagnose)
    monkeypatch.setattr(
        science, "run_research", lambda *a, **k: pytest.fail("Unexpected retrieval")
    )
    prompt = "Compare perovskite absorbers for a silicon tandem solar cell."
    with pytest.raises(ModelError) as caught:
        research(prompt, load_config(), connections=manager)
    assert provider_failure_code(caught.value) == "provider_usage_limit"
    assert str(caught.value) == PROVIDER_FAILURE_MESSAGES["provider_usage_limit"]
    assert calls == [prompt]
    assert diagnoses == [captured]
    assert manager.setup.status()["can_research"]


def test_unknown_allowance_does_not_invent_a_credit_failure_or_request_details(
    tmp_path, monkeypatch, authenticated_model_factory
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    manager = authenticated_model_factory(tmp_path / "model.sqlite3")
    calls = []

    def run(prompt, context, session):
        calls.append(prompt)
        return {"provider": "chatgpt", "model": "fixture-model", "status": "completed"}

    monkeypatch.setattr(manager.agent, "run", run)
    monkeypatch.setattr(
        manager.agent, "failure_after_missing_assessment", lambda a: None
    )
    result = research("Compare oxide dielectrics", load_config(), connections=manager)
    intake = result["result"]["intake"]
    assert intake["reason_code"] == "assessment_missing"
    assert intake["questions"] == []
    assert "exhausted" not in result["pi_summary"]
    assert len(calls) == 1


@pytest.mark.parametrize("decision", ["out_of_scope", "materials_research"])
def test_valid_intent_decision_is_not_replaced_by_post_failure_diagnostics(
    tmp_path, monkeypatch, authenticated_model_factory, decision
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    manager = authenticated_model_factory(tmp_path / "model.sqlite3")

    def run(prompt, context, session):
        session.call("assess_research_intent", {"decision": decision})
        return {"provider": "openai", "model": "fixture-model", "status": "completed"}

    monkeypatch.setattr(manager.agent, "run", run)
    monkeypatch.setattr(
        manager.agent,
        "failure_after_missing_assessment",
        lambda a: pytest.fail("An assessed request was probed for exhausted allowance"),
    )
    result = research(
        "Compare oxide dielectrics",
        load_config(),
        connections=manager,
        source_preferences={
            **default_source_preferences(),
            "materials_project_mode": "off",
            "enabled_sources": [],
            "search_public_references": False,
        },
    )
    assert result["result"]["intake"]["status"] == (
        "clarification_required" if decision == "out_of_scope" else "accepted"
    )
