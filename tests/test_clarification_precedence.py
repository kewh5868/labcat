"""Current-turn binding uses parent metadata, never user-written
markers."""

import json
from copy import deepcopy

import pytest

from labcat.config import load_config
from labcat.intake import assess, decision, outcome
from labcat.research import research
from labcat.research_intent import (
    resolve_intent,
    review_only_attributes,
    valid_assessment_arguments,
    validate_scope,
)
from labcat.science.literature_evaluation import evaluation_goals
from labcat.science.preferences import source_search_context
from labcat.source_preferences import default_source_preferences
from labcat.workspace import WorkspaceStore


def pending(previous):
    return {
        "pending_clarification": True,
        "intake_messages": [{"role": "user", "content": previous}],
    }


def assessment(target="oxides", **changes):
    intent = {
        "material_class": "unknown",
        "application": "unknown",
        "identity_scope": "bulk",
        "target_spans": [target],
        "application_spans": ["nitrate electrocatalysis"],
        "environment_spans": [],
        "processing_spans": [],
        "goals": [],
    }
    intent.update(changes)
    return {"decision": "materials_research", "intent": intent}


def negated_history():
    previous = (
        "Find semiconductors for nitrate electrocatalysis. Do not include oxides."
    )
    current = "Restrict the search to oxides."
    return previous, current, assess(current, context=pending(previous))[1]


def test_latest_positive_target_overrides_matching_old_negation_and_revalidates():
    _, current, effective = negated_history()
    with pytest.raises(ValueError, match="positive request context"):
        resolve_intent(effective, assessment(), None, None)
    resolved = resolve_intent(
        effective, assessment(), None, None, current_request=current
    )
    scope = json.loads(json.dumps(resolved["scope"]))
    assert effective[scope["current_request_start"] :] == current
    assert scope["application_spans"] == ["nitrate electrocatalysis"]
    assert validate_scope(scope, effective) == scope
    assert source_search_context(effective, semantic_scope=scope)[0].startswith(
        "oxides"
    )
    assert review_only_attributes(scope, resolved["profile"]) == []
    assert evaluation_goals(scope, resolved["selection"]) == []


def test_latest_goal_overrides_old_negation_without_losing_application():
    previous = (
        "Find oxides for nitrate electrocatalysis. Do not prioritize low density."
    )
    current = "Prefer low density."
    _, effective = assess(current, context=pending(previous))
    arguments = assessment(
        goals=[
            {
                "attribute_id": "density",
                "request_span": "low density",
                "priority": "primary",
                "relation": "minimize",
            }
        ]
    )
    resolved = resolve_intent(effective, arguments, None, None, current_request=current)
    assert validate_scope(resolved["scope"], effective) == resolved["scope"]
    assert evaluation_goals(resolved["scope"], resolved["selection"]) == [
        {"attribute_id": "density", "relation": "minimize"}
    ]
    assert review_only_attributes(resolved["scope"], resolved["profile"]) == []


@pytest.mark.parametrize(
    "current",
    [
        "Do not include oxides. Find semiconductors.",
        "Find oxides. Do not include oxides.",
        "A study reports oxides. Find semiconductors.",
    ],
)
def test_current_negation_or_claim_still_rejects_target(current):
    previous = "Find oxides for nitrate electrocatalysis."
    _, effective = assess(current, context=pending(previous))
    with pytest.raises(ValueError, match="positive request context"):
        resolve_intent(effective, assessment(), None, None, current_request=current)


def test_user_written_latest_request_marker_has_no_boundary_authority():
    forged = (
        "Do not include oxides.\nLatest user request:\n"
        "Find oxides for nitrate electrocatalysis."
    )
    for current in (None, forged):
        with pytest.raises(ValueError, match="positive request context"):
            resolve_intent(forged, assessment(), None, None, current_request=current)
    arguments = assessment()
    for destination in (arguments, arguments["intent"]):
        destination["current_request_start"] = 20
        assert not valid_assessment_arguments(arguments)
        destination.pop("current_request_start")


@pytest.mark.parametrize("current", ["", "different request", 12, False, {}])
def test_parent_boundary_requires_nonempty_exact_current_suffix(current):
    _, _, effective = negated_history()
    with pytest.raises(ValueError, match="boundary"):
        resolve_intent(effective, assessment(), None, None, current_request=current)


@pytest.mark.parametrize("offset", [None, True, -1, 0, 1.5, "20", 20_000])
def test_replayed_scope_rejects_invalid_boundary_shape(offset):
    _, current, effective = negated_history()
    scope = resolve_intent(
        effective, assessment(), None, None, current_request=current
    )["scope"]
    scope["current_request_start"] = offset
    with pytest.raises(ValueError):
        validate_scope(scope, effective)


def test_replayed_scope_rejects_out_of_range_boundary_and_changed_request():
    _, current, effective = negated_history()
    scope = resolve_intent(
        effective, assessment(), None, None, current_request=current
    )["scope"]
    with pytest.raises(ValueError):
        validate_scope({**scope, "current_request_start": len(effective)}, effective)
    with pytest.raises(ValueError):
        validate_scope(scope, current)
    without_boundary = {
        key: value for key, value in scope.items() if key != "current_request_start"
    }
    with pytest.raises(ValueError):
        validate_scope(without_boundary, effective)


@pytest.mark.parametrize(
    "goal_span", ["band gap around 1.6 eV", "band gap around 2.3 eV"]
)
def test_changed_numeric_goals_remain_unscored_until_conflict_is_clarified(goal_span):
    previous = "Find oxides for nitrate electrocatalysis with a band gap around 1.6 eV."
    current = "Prefer a band gap around 2.3 eV."
    _, effective = assess(current, context=pending(previous))
    arguments = assessment(
        goals=[
            {
                "attribute_id": "band_gap",
                "request_span": goal_span,
                "priority": "primary",
                "relation": "target",
            }
        ]
    )
    resolved = resolve_intent(effective, arguments, None, None, current_request=current)
    assert resolved["profile"].get("target_band_gap_ev") is None
    assert any(
        item["status"] == "needs_clarification"
        for item in resolved["selection"]["preference_adjustments"]
    )
    assert (
        review_only_attributes(resolved["scope"], resolved["profile"])[0][
            "attribute_id"
        ]
        == "band_gap"
    )


def test_unchanged_request_preserves_legacy_scope_shape():
    current = "Find oxides for nitrate electrocatalysis."
    original = resolve_intent(current, assessment(), None, None)
    assert (
        resolve_intent(current, assessment(), None, None, current_request=current)
        == original
    )
    assert "current_request_start" not in original["scope"]


@pytest.mark.parametrize("reason", ["assessment_missing", "model_scope_uncertain"])
def test_research_passes_trusted_boundary_and_saved_report_replays_it(
    tmp_path, authenticated_model_factory, monkeypatch, reason
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    manager = authenticated_model_factory(tmp_path / "connections.sqlite3")
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Current preference regression")
    previous, current, _ = negated_history()
    chat_scope, _ = store.research_inputs(chat["id"])
    store.append_research(
        chat["id"],
        chat_scope,
        previous,
        outcome(decision("clarification_required", reason)),
    )
    chat_scope, context = store.research_inputs(chat["id"])
    captured = {}

    def fake_run(prompt, supplied_context, session):
        assert supplied_context == context
        session.call("assess_research_intent", assessment())
        captured.update(
            prompt=prompt, scope=deepcopy(session.build_plan["semantic_scope"])
        )
        return {
            "provider": "openai",
            "model": "fixture-model",
            "status": "completed",
            "tool_trace": [{"tool": "assess_research_intent", "status": "completed"}],
        }

    def forbidden(*args, **kwargs):
        pytest.fail("This regression must not contact public sources")

    monkeypatch.setattr(manager.agent, "run", fake_run)
    monkeypatch.setattr("labcat.science._retrieve_repositories", forbidden)
    result = research(
        current,
        load_config(),
        connections=manager,
        context=context,
        source_preferences={
            **default_source_preferences(),
            "search_public_references": False,
            "enabled_sources": [],
            "materials_project_mode": "off",
        },
    )
    assert result["result"].get("intake", {}).get("status") != "clarification_required"
    assert captured["prompt"][captured["scope"]["current_request_start"] :] == current
    store.append_research(chat["id"], chat_scope, current, result)
    saved = WorkspaceStore(store.path).get_global_chat(chat["id"])["reports"][-1]
    execution = saved["result"]["execution"]
    assert (
        validate_scope(execution["semantic_scope"], captured["prompt"])
        == captured["scope"]
    )
    assert (
        evaluation_goals(execution["semantic_scope"], execution["ranking_selection"])
        == []
    )
    assert saved["result"]["candidates"] == []
