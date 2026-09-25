"""Reference discovery is optional and cannot discard a completed
report."""

from types import SimpleNamespace

import pytest

from labcat.config import load_config
from labcat.research import ResearchWorkflow


@pytest.fixture(autouse=True)
def simulated_model_admission(monkeypatch):
    """These post-save tests replace model execution and its readiness
    gate."""
    monkeypatch.setattr("labcat.research._require_research_setup", lambda *_: None)


@pytest.mark.parametrize("enabled", [True, False])
def test_discovery_follows_save_and_respects_per_request_choice(monkeypatch, enabled):
    calls = []
    detail = {"messages": [{"role": "assistant", "report_id": "saved-report"}]}
    outcome = {"stage": "partial", "result": {}}

    def save(*args, **kwargs):
        calls.append(("saved", args[-1]["result"]["execution"]))
        return detail

    workspace = SimpleNamespace(
        research_inputs=lambda *_: ("scope", {}),
        name_submitted_chat=lambda *_: None,
        append_research=save,
    )
    sources = {
        "search_public_references": True,
        "enabled_sources": ["hybrid3"],
        "materials_project_mode": "off",
        "max_results_per_source": 5,
    }
    monkeypatch.setattr("labcat.research.research", lambda *_, **kw: outcome)
    structures = SimpleNamespace(
        discover_references=lambda *a, **kw: calls.append(("structures", a, kw))
    )
    workflow = ResearchWorkflow(
        workspace,
        None,
        source_preferences=SimpleNamespace(load=lambda: sources),
        structures=structures,
    )
    result = workflow.respond(
        "chat",
        "ordinary materials question",
        load_config(),
        search_reference_structures=enabled,
    )
    assert result is detail
    assert calls[0] == ("saved", {"search_reference_structures": enabled})
    assert len(calls) == (2 if enabled else 1)
    if enabled:
        assert calls[1] == (
            "structures",
            ("chat", "saved-report"),
            {"enabled_sources": ["hybrid3"], "materials_project_mode": "off"},
        )
    assert workflow.progress.snapshot("chat")["status"] == "completed"


def test_structure_outage_keeps_saved_response_and_default_is_on(monkeypatch):
    calls = []
    detail = {"messages": [{"role": "assistant", "report_id": "saved-report"}]}
    workspace = SimpleNamespace(
        research_inputs=lambda *_: ("scope", {}),
        name_submitted_chat=lambda *_: None,
        append_research=lambda *_, **kw: detail,
    )
    monkeypatch.setattr(
        "labcat.research.research", lambda *_, **kw: {"stage": "partial", "result": {}}
    )

    def unavailable(*a, **kw):
        calls.append(a)
        raise TimeoutError("private network diagnostics")

    workflow = ResearchWorkflow(
        workspace, None, structures=SimpleNamespace(discover_references=unavailable)
    )
    assert workflow.respond("chat", "materials question", load_config()) is detail
    assert calls == [("chat", "saved-report")]
    assert workflow.progress.snapshot("chat")["status"] == "completed"


def test_refusals_do_not_search_for_structures(monkeypatch):
    workspace = SimpleNamespace(
        research_inputs=lambda *_: ("scope", {}),
        name_submitted_chat=lambda *_: None,
        append_research=lambda *_, **kw: {"messages": [{"role": "assistant"}]},
    )
    monkeypatch.setattr(
        "labcat.research.research", lambda *_, **kw: {"stage": "blocked", "result": {}}
    )
    workflow = ResearchWorkflow(
        workspace,
        None,
        structures=SimpleNamespace(
            discover_references=lambda *_a, **_kw: pytest.fail(
                "Refusal must not start discovery"
            )
        ),
    )
    workflow.respond("chat", "blocked request", load_config())


@pytest.mark.parametrize("value", ["false", 1, 0, [], {}])
def test_structure_choice_is_strict_boolean(value):
    from pydantic import ValidationError

    from labcat.workspace_api import MessageCreate

    with pytest.raises(ValidationError):
        MessageCreate(content="question", search_reference_structures=value)
