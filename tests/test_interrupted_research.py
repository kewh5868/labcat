"""Provider failures retain bounded evidence only after successful
assessment."""

import json
from copy import deepcopy

import pytest

from labcat import science
from labcat.config import load_config
from labcat.credentials import ConnectionError
from labcat.models import ModelError
from labcat.research import research
from labcat.source_preferences import default_source_preferences
from labcat.workspace import WorkspaceStore


@pytest.mark.parametrize("failure", [ModelError, ConnectionError])
@pytest.mark.parametrize("last_stage", ["assessment", "discovery", "report"])
@pytest.mark.parametrize("diagnostic_kind", ["absent", "bounded", "invalid"])
def test_model_interruption_completes_selected_public_stages_without_retry(
    tmp_path,
    monkeypatch,
    authenticated_model_factory,
    failure,
    last_stage,
    diagnostic_kind,
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    manager = authenticated_model_factory(tmp_path / "w.sqlite3")
    historical = science.load_snapshot()
    model_calls, retrieval_calls = [], []
    diagnostics = {
        "scope": "worker_reported",
        "rejections": [
            {
                "tool": "evaluate_candidate_fit",
                "reason": "evaluation_interpretation_format",
                "count": 1,
            }
        ],
    }
    if diagnostic_kind == "invalid":
        diagnostics["submitted_content"] = "PRIVATE-DIAGNOSTIC-CANARY"

    def retrieve(filters=None):
        retrieval_calls.append(deepcopy(filters))
        return deepcopy(historical)

    def interrupted(prompt, context, session):
        model_calls.append(prompt)
        session.call("assess_research_intent", {"decision": "materials_research"})
        if last_stage in {"discovery", "report"}:
            session.call("search_public_references", {})
        if last_stage == "report":
            session.call("generate_ranked_report", {})
        error = failure("UNTRUSTED-PROVIDER-ERROR fixture-secret not for reports")
        if diagnostic_kind != "absent":
            error.worker_rejection_diagnostics = deepcopy(diagnostics)
        raise error

    monkeypatch.setattr(science, "retrieve_nomad", retrieve)
    monkeypatch.setattr(manager.agent, "run", interrupted)
    monkeypatch.setattr("labcat.research._add_attribute_research", lambda *a, **k: None)
    outcome = research(
        "Find oxide dielectric candidates for thin-film experiments.",
        load_config(),
        connections=manager,
        ranking_profile={
            "id": "test-explicit",
            "name": "Test profile only",
            "importance": {"dielectric_total": 1},
        },
        ranking_selection={"mode": "explicit"},
        source_preferences={
            **default_source_preferences(),
            "materials_project_mode": "off",
            "enabled_sources": ["nomad"],
            "search_public_references": False,
        },
    )
    assert len(model_calls) == len(retrieval_calls) == 1
    assert outcome["stage"] == "partial"
    records = outcome["result"]["candidates"]
    assert records
    expected = {row["material_id"]: row for row in historical[0]}
    for row in records:
        assert (
            row["dielectric_total"] == expected[row["material_id"]]["dielectric_total"]
        )
    execution = outcome["result"]["execution"]
    assert execution["model_interrupted"] is True
    assert execution["completion_version"] == "bounded-recovery-v2"
    assert execution["requested_model"] == manager.status()["profile"]["model"]
    assert execution["attempted_model"] is None
    assert execution["failure_code"] is None
    assert "agent" not in execution  # No fabricated completion trace or usage.
    if diagnostic_kind == "bounded":
        assert execution["worker_rejection_diagnostics"] == diagnostics
    else:
        assert "worker_rejection_diagnostics" not in execution
    assert not manager.setup.status()["can_research"]
    encoded = json.dumps(outcome)
    assert "UNTRUSTED-PROVIDER-ERROR" not in encoded
    assert "fixture-secret" not in encoded
    assert "PRIVATE-DIAGNOSTIC-CANARY" not in encoded
    for view in ("pi_summary", "technical_audit"):
        assert "Model-led research stopped before completion" in outcome[view]
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY interrupted research")
    chat = store.create_global_chat("TEST ONLY interrupted research", project["id"])
    store.append_research(chat["id"], project["id"], model_calls[0], outcome)
    reopened = WorkspaceStore(store.path).get_global_chat(chat["id"])
    saved = reopened["reports"][0]
    assert saved["stage"] == "partial"
    assert saved["result"]["candidates"] == records
    assert saved["result"]["execution"]["model_interrupted"] is True
    assert "fixture-secret" not in json.dumps(reopened)


@pytest.mark.parametrize("decision", [None, "needs_clarification", "unsafe"])
def test_interruption_without_accepted_assessment_never_starts_sources(
    tmp_path, monkeypatch, authenticated_model_factory, decision
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    manager = authenticated_model_factory(tmp_path / "w.sqlite3")

    def interrupted(prompt, context, session):
        if decision:
            session.call("assess_research_intent", {"decision": decision})
        assert not session.can_complete_without_model
        raise ModelError("Test interruption")

    monkeypatch.setattr(manager.agent, "run", interrupted)
    monkeypatch.setattr(
        science, "run_research", lambda *a, **k: pytest.fail("Unauthorized source call")
    )
    with pytest.raises(ModelError, match="No report was saved"):
        research("Find oxide materials", load_config(), connections=manager)
