"""Unfinished requests retain user preferences without acquiring
evidence or authority."""

import json
from copy import deepcopy

import pytest

from labcat.config import load_config
from labcat.developer_settings import defaults
from labcat.intake import QUESTIONS, assess, decision, outcome, validate_intake
from labcat.models import Plan, bounded_context
from labcat.research import research
from labcat.research_intent import resolve_intent
from labcat.workspace import WorkspaceStore

FIRST = (
    "I need a semi-conductor with a dominant surface facet having a high potential "
    "of zero charge, but with a very small band-gap"
)
SECOND = (
    "I would like to study anion adsorption + electrocatalytic reduction, should "
    "focus primarily on the activation of nitrate from solution. Material should "
    "be a poor HER catalyst, or inactive for HER in the potential window at which "
    "nitrate is activated"
)
THIRD = "restrict search to oxides"
FIFTH = (
    "1 - I would like to study anion adsorption for oxides. 2 - The comparison "
    "should be for the selective removal of nitrate anions over other common "
    "wastewater anions. 3 - Dominant surface facet should have a PZC below -0.5 "
    "vs SHE, and should be a poor HER catalyst"
)


def save_intake(store, chat_id, prompt, reason="model_scope_uncertain"):
    scope, _ = store.research_inputs(chat_id)
    return store.append_research(
        chat_id, scope, prompt, outcome(decision("clarification_required", reason))
    )


@pytest.mark.parametrize("reason", ["model_scope_uncertain", "assessment_missing"])
@pytest.mark.parametrize("project_chat", [False, True])
def test_reported_sequence_retains_pending_same_chat_preferences(
    tmp_path, reason, project_chat
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("Intake context") if project_chat else None
    chat = store.create_global_chat(
        "Pending request", project["id"] if project else None
    )
    prompts = [FIRST, SECOND, THIRD, "\n".join((FIRST, SECOND, THIRD)), FIFTH]
    for index, prompt in enumerate(prompts):
        _, context = store.research_inputs(chat["id"])
        assert context["pending_clarification"] is (index > 0)
        before = deepcopy(context)
        intake, effective = assess(prompt, context=context)
        assert intake["status"] == "accepted"
        assert effective.endswith(prompt)
        assert len(effective) <= 20_000
        assert context == before
        if index:
            for previous in prompts[max(0, index - 4) : index]:
                assert previous[:500] in effective
            assert "Latest user request:" in effective
        else:
            assert effective == prompt
        detail = save_intake(store, chat["id"], prompt, reason)
        assert detail["reports"] == detail["sources"] == []
    assert len(detail["messages"]) == 10
    assert "below -0.5 vs SHE" in effective.rsplit("Latest user request", 1)[-1]
    reopened = WorkspaceStore(store.path)
    assert reopened.research_inputs(chat["id"])[1]["pending_clarification"] is True


def test_class_answer_binds_prior_application_as_user_context_not_evidence(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Pending request")
    save_intake(store, chat["id"], SECOND, "assessment_missing")
    _, context = store.research_inputs(chat["id"])
    _, effective = assess(THIRD, context=context)
    arguments = {
        "decision": "materials_research",
        "intent": {
            "material_class": "unknown",
            "application": "unknown",
            "identity_scope": "unspecified",
            "target_spans": ["oxides"],
            "application_spans": ["anion adsorption + electrocatalytic reduction"],
            "environment_spans": [],
            "processing_spans": [],
            "goals": [],
        },
    }
    with pytest.raises(ValueError, match="original request"):
        resolve_intent(THIRD, arguments, None, None)
    resolved = resolve_intent(effective, arguments, None, None)
    assert resolved["scope"]["is_evidence"] is False
    assert resolved["scope"]["target_text"] == "oxides"
    assert "sources" not in resolved and "candidates" not in resolved


def test_pending_marker_is_from_own_saved_intake_and_clears_on_report(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("Shared project")
    own, other = [
        store.create_global_chat(name, project["id"])
        for name in ("Own pending question", "Other question")
    ]
    save_intake(store, other["id"], "Compare polymer coatings", "assessment_missing")
    _, context = store.research_inputs(own["id"])
    assert context["pending_clarification"] is False
    assert assess(THIRD, context=context)[1] == THIRD
    save_intake(store, own["id"], SECOND)
    _, context = store.research_inputs(own["id"])
    assert context["pending_clarification"] is True
    effective = assess(THIRD, context=context)[1]
    assert SECOND in effective and "polymer coatings" not in effective
    assert not any(question in effective for question in QUESTIONS)
    assert "pending_clarification" not in bounded_context(context)
    store.append_global_message(own["id"], "Compare oxide candidates", load_config())
    assert store.research_inputs(own["id"])[1]["pending_clarification"] is False


def test_standalone_scope_and_explicit_reset_do_not_inherit_pending_preferences():
    context = {
        "intake_messages": [{"role": "user", "content": FIRST}],
        "pending_clarification": False,
    }
    standalone = "Compare polymer membranes for selective gas transport"
    assert assess(standalone, context=context)[1] == standalone
    context["pending_clarification"] = True
    for prompt in (
        "New topic: compare polymer membranes for selective gas transport",
        "Compare biodegradable polymers for food packaging",
    ):
        assert assess(prompt, context=context)[1] == prompt


@pytest.mark.parametrize(
    "reason", ["harmful_manufacture", "research_boundary", "model_declined"]
)
def test_pending_marker_cannot_clear_an_earlier_refusal(reason):
    context = {
        "pending_clarification": True,
        "intake_messages": [
            {
                "role": "user",
                "content": "Compare alloy alternatives",
                "refused": True,
                "reason_code": reason,
            }
        ],
    }
    intake, effective = assess("restrict search to oxides", context=context)
    assert intake == decision("refused", reason)
    assert effective == "restrict search to oxides"


@pytest.mark.parametrize("size", [13_000, 19_999, 20_000])
def test_pending_history_keeps_full_current_request_and_newest_optional_text(size):
    prompt = "oxides " + "x" * (size - 18) + " TAIL_GOAL!"
    context = {
        "pending_clarification": True,
        "intake_messages": [
            {"role": "user", "content": FIRST},
            {"role": "user", "content": SECOND},
        ],
    }
    _, effective = assess(prompt, context=context)
    assert effective.endswith(prompt)
    assert len(effective) <= 20_000
    if size == 13_000:
        assert (
            effective.index(FIRST) < effective.index(SECOND) < effective.index(prompt)
        )


def test_history_disabled_never_sends_pending_context_to_model(
    tmp_path, authenticated_model_factory, monkeypatch
):
    manager = authenticated_model_factory(tmp_path / "connections.sqlite3")
    seen = {}

    def plan(prompt, **kwargs):
        seen.update(prompt=prompt, context=kwargs.get("context"))
        return Plan(task="unsupported")

    monkeypatch.setattr(manager, "plan", plan)
    controls = {**defaults(), "include_history": False}
    research(
        THIRD,
        load_config(),
        connections=manager,
        context={
            "pending_clarification": True,
            "intake_messages": [
                {"role": "user", "content": SECOND},
            ],
        },
        research_controls=controls,
    )
    assert seen == {"prompt": THIRD, "context": None}


def test_missing_assessment_has_actionable_text_and_no_questions_or_retrieval(tmp_path):
    intake = decision("clarification_required", "assessment_missing")
    assert intake["questions"] == []
    result = outcome(intake)
    assert "model could not finish the request assessment" in result["answer"]
    assert "question remains valid" in result["answer"]
    assert "Retry" in result["answer"] and "another model" in result["answer"]
    assert "provider account's access and usage limits" in result["answer"]
    assert not any(question in result["answer"] for question in QUESTIONS)
    assert result["sources"] == result["result"]["candidates"] == []
    assert result["result"]["retrieval"] == {"status": "not_run"}
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Assessment failure")
    detail = save_intake(store, chat["id"], FIRST, "assessment_missing")
    saved = detail["messages"][-1]
    assert saved["intake"] == intake and saved["content"] == result["answer"]
    assert (
        WorkspaceStore(store.path).get_global_chat(chat["id"])["messages"][-1] == saved
    )


def test_legacy_assessment_questions_remain_readable_without_rewriting_history(
    tmp_path,
):
    legacy = {
        "status": "clarification_required",
        "reason_code": "assessment_missing",
        "questions": list(QUESTIONS),
    }
    assert validate_intake(legacy) == legacy
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Historical failure")
    detail = save_intake(store, chat["id"], FIRST, "assessment_missing")
    message = detail["messages"][-1]
    old_answer = "Historical clarification\n" + "\n".join(QUESTIONS)
    with store._connection(write=True) as connection:
        connection.execute(
            "UPDATE messages SET content=? WHERE id=?", (old_answer, message["id"])
        )
        connection.execute(
            "UPDATE message_intakes SET intake_json=? WHERE message_id=?",
            (json.dumps(legacy), message["id"]),
        )
    reopened = WorkspaceStore(store.path)
    saved = reopened.get_global_chat(chat["id"])["messages"][-1]
    assert saved["intake"] == legacy and saved["content"] == old_answer
    assert reopened.research_inputs(chat["id"])[1]["pending_clarification"] is True
    with pytest.raises(ValueError):
        validate_intake({**legacy, "questions": ["arbitrary question"]})
    with pytest.raises(ValueError):
        validate_intake(
            {**legacy, "reason_code": "model_scope_uncertain", "questions": []}
        )
