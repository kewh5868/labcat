"""Model search hints are explicit while historical empty calls remain
supported."""

from copy import deepcopy

import pytest

from labcat import public_sources as public
from labcat.agent_tools import ResearchToolSession, valid_search_arguments
from labcat.config import load_config
from labcat.source_preferences import default_source_preferences

PROMPT = (
    "Review nickel-based alloys for cooling fins in humid air, made by cold forming. "
    "Favor low density."
)
TOPIC = "Metal alloys Cooling fins"


def test_model_schema_requires_a_bounded_topic_but_legacy_parser_accepts_empty():
    definition = next(
        tool
        for tool in ResearchToolSession.tool_definitions()
        if tool["name"] == "search_public_references"
    )
    schema = definition["inputSchema"]
    assert schema["required"] == ["topic"]
    assert set(schema["properties"]) == {"topic"}
    assert schema["properties"]["topic"] == {
        "type": "string",
        "minLength": 3,
        "maxLength": 160,
    }
    assert schema["additionalProperties"] is False
    assert "material class and functional application" in definition["description"]
    assert valid_search_arguments({"topic": TOPIC})
    assert valid_search_arguments({})
    assert valid_search_arguments(None)
    assert not valid_search_arguments({"topic": ""})
    assert not valid_search_arguments({"topic": TOPIC, "url": "https://example.org"})


@pytest.mark.parametrize("arguments", [{"topic": TOPIC}, {}])
def test_hint_reaches_adapters_unchanged_with_full_validated_scope(
    monkeypatch, arguments
):
    def denied(*args, **kwargs):
        pytest.fail("Discovery topic regression attempted a network connection")

    monkeypatch.setattr(public.socket, "create_connection", denied)
    monkeypatch.setattr(public.socket, "getaddrinfo", denied)
    original_search = public.search_public_sources
    boundary_calls, adapter_calls = [], {}

    def search(query, *args, **options):
        boundary_calls.append((query, deepcopy(options)))
        return original_search(query, *args, **options)

    def adapter(source):
        def capture(query, limit, deadline, **options):
            adapter_calls[source] = {
                "query": query,
                "scope": deepcopy(public._SEARCH_SCOPE.get()),
                "identity": public._identity_context(query),
                "options": options,
            }
            return [], "Synthetic empty source response."

        return capture

    monkeypatch.setattr(public, "search_public_sources", search)
    for source in ("openalex", "nomad"):
        monkeypatch.setitem(public._ADAPTERS, source, adapter(source))
    session = ResearchToolSession(
        PROMPT,
        load_config(),
        source_preferences={
            **default_source_preferences(),
            "enabled_sources": ["openalex", "nomad"],
            "materials_project_mode": "off",
        },
    )
    session.call(
        "assess_research_intent",
        {
            "decision": "materials_research",
            "intent": {
                "material_class": "metals_metal_alloys",
                "application": "unknown",
                "identity_scope": "bulk",
                "target_spans": ["nickel-based alloys"],
                "application_spans": ["cooling fins"],
                "environment_spans": ["humid air"],
                "processing_spans": ["cold forming"],
                "goals": [
                    {
                        "attribute_id": "density",
                        "request_span": "Favor low density",
                        "priority": "primary",
                        "relation": "minimize",
                    }
                ],
            },
        },
    )
    original_scope = deepcopy(session.build_plan["semantic_scope"])
    response = session.call("search_public_references", arguments)
    session.call("search_public_references", arguments)
    assert len(boundary_calls) == 1
    query, options = boundary_calls[0]
    assert query == (TOPIC if arguments else PROMPT)
    assert options.get("focused_topic", False) is bool(arguments)
    assert options["scope_prompt"] == PROMPT
    assert options["semantic_scope"] == original_scope
    assert set(adapter_calls) == {"openalex", "nomad"}
    for source, captured in adapter_calls.items():
        assert captured["query"] == query
        assert captured["scope"] == original_scope
        assert captured["identity"] == (
            "nickel-based alloys",
            "metals_metal_alloys",
            "bulk",
        )
        assert captured["options"].get("focused_topic", False) is (
            bool(arguments) and source == "openalex"
        )
    assert session.build_plan["semantic_scope"] == original_scope
    assert (
        session.build_plan["stages"]["search_public_references"]["execution_count"] == 1
    )
    assert response["reference_count"] == 0
    assert response["public_documents"] == []
    assert public._SEARCH_SCOPE.get() is None
    assert public._SEARCH_CONTEXT.get() is None
