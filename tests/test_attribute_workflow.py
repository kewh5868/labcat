"""Repository-first retrieval and literal literature leads share one
evidence path."""

from copy import deepcopy

import pytest

from labcat import property_research, public_sources, science
from labcat.agent_tools import ResearchToolSession
from labcat.config import load_config
from labcat.research import _add_attribute_research, research
from labcat.science.sources import SourceError, load_snapshot
from labcat.source_preferences import default_source_preferences

PROMPT = "Compare public evidence for oxide dielectric materials."
IMPORTANCE = {"band_gap": 0.5, "bulk_modulus": 0.5}
PROFILE = {"id": "fixture", "name": "TEST profile", "importance": IMPORTANCE}


def _source():
    return {
        "source_id": "europe_pmc",
        "record_id": "PMC123456",
        "title": "TEST FIXTURE: public article for context review",
        "url": "https://europepmc.org/articles/PMC123456",
        "source_name": "Europe PMC",
        "access_scope": "public",
        "provenance_status": "verified",
        "kind": "discovery_reference",
        "is_material_evidence": False,
        "metadata": {"full_text_read": True, "full_text_scope": "body paragraphs only"},
        "provenance": {"full_text_response_sha256": "a" * 64},
    }


def _followup(requests):
    item = requests[0]
    return {
        "status": "complete",
        "sources": [_source()],
        "caveats": [],
        "attributes": [
            {
                "attribute_id": item["attribute_id"],
                "status": "review_leads",
                "queries": ["TEST bounded material property query"],
                "articles_read": 1,
                "caveats": [],
                "passages": [
                    {
                        "source_url": _source()["url"],
                        "text": "TEST FIXTURE: an unrelated sample was reported "
                        "at 42 GPa.",
                        "locator": "body/sec[1]/p[1]",
                        "section": "Test methods",
                        "article_id": "PMC123456",
                        "response_sha256": "a" * 64,
                        "candidate_ids": item["candidate_ids"],
                        "formulas": item["formulas"],
                        "method": None,
                        "caveat": "Sample phase and applicability unverified.",
                    }
                ],
            }
        ],
    }


@pytest.fixture
def repository(monkeypatch):
    records, metadata = load_snapshot()  # Explicit test data, never runtime fallback.
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda filters: deepcopy((records, metadata))
    )
    return records, metadata


@pytest.mark.parametrize("first_status", ["empty", "unavailable"])
def test_auto_repository_fallback_preserves_source_identity(
    monkeypatch, repository, first_status
):
    records, metadata = repository
    calls = []

    def first(key, filters):
        calls.append("materials_project")
        if first_status == "unavailable":
            raise SourceError("Unavailable")
        return [], {"mode": "test_empty"}

    def second(filters):
        calls.append("nomad")
        return deepcopy((records, metadata))

    monkeypatch.setattr(science, "retrieve_live", first)
    monkeypatch.setattr(science, "retrieve_nomad", second)
    outcome = science.run_research(PROMPT, load_config(), mp_api_key="test-only")
    assert calls == ["materials_project", "nomad"]
    assert outcome["result"]["retrieval"]["selected_repository"] == "nomad"
    assert outcome["result"]["candidates"]
    for candidate in outcome["result"]["candidates"]:
        assert candidate["bulk_modulus_gpa"] is None
        assert candidate["provenance"]["source_url"] == metadata["source_url"]


def test_successful_repository_records_are_not_cross_source_property_joins(
    monkeypatch, repository
):
    records, metadata = repository
    monkeypatch.setattr(
        science, "retrieve_live", lambda key, filters: deepcopy((records, metadata))
    )
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda filters: pytest.fail("Unexpected phase join")
    )
    outcome = science.run_research(
        PROMPT, load_config(), mp_api_key="test-only", importance=IMPORTANCE
    )
    assert outcome["result"]["retrieval"]["selected_repository"] == "materials_project"
    assert all(
        row["bulk_modulus_gpa"] is None for row in outcome["result"]["candidates"]
    )


def test_missing_attributes_trigger_attributed_review_without_changing_scores(
    monkeypatch, repository
):
    outcome = science.run_research(PROMPT, load_config(), importance=IMPORTANCE)
    original = deepcopy(outcome["result"]["candidates"])
    captured = []

    def lookup(prompt, requests, **kwargs):
        captured.extend(deepcopy(requests))
        return _followup(requests)

    monkeypatch.setattr(property_research, "find_attribute_evidence", lookup)
    _add_attribute_research(
        outcome, PROMPT, load_config(), default_source_preferences()
    )
    assert [request["attribute_id"] for request in captured] == ["bulk_modulus"]
    assert captured[0]["formulas"] == [row["formula"] for row in original]
    assert captured[0]["candidate_identities"] == [
        {"candidate_id": row["material_id"], "names": [row["formula"]]}
        for row in original
    ]
    assert outcome["result"]["candidates"] == original
    assert outcome["result"]["attribute_research"]["used_for_ranking"] is False
    report = science.render_research(outcome, load_config())
    assert "42 GPa" in report["technical_audit"]
    assert "42 GPa" not in report["pi_summary"]
    assert "do not fill missing properties" in report["pi_summary"]
    assert "phase and applicability unverified" in report["technical_audit"]
    assert "[S1]" in report["technical_audit"]
    assert _source()["url"] not in report["technical_audit"]
    assert _source()["url"] in {source["url"] for source in report["sources"]}
    assert (
        report["result"]["attribute_research"]["attributes"][0]["passages"][0][
            "source_url"
        ]
        == _source()["url"]
    )
    passage = report["result"]["attribute_research"]["attributes"][0]["passages"][0]
    # The synthetic passage gives no material identity. Adapter-supplied IDs
    # cannot imply applicability to every record awaiting this property.
    assert passage["candidate_ids"] == []
    assert passage["context_scope"] == "general_context"


def test_skimmed_source_preserves_original_and_full_text_provenance(
    monkeypatch, repository
):
    outcome = science.run_research(PROMPT, load_config(), importance=IMPORTANCE)
    original = _source()
    original["metadata"]["full_text_read"] = False
    original["provenance"] = {"discovery_response_sha256": "b" * 64}
    outcome["sources"].append(original)
    monkeypatch.setattr(
        property_research,
        "find_attribute_evidence",
        lambda prompt, requests, **kwargs: _followup(requests),
    )
    _add_attribute_research(
        outcome, PROMPT, load_config(), default_source_preferences()
    )
    saved = next(
        source for source in outcome["sources"] if source["url"] == _source()["url"]
    )
    assert saved["provenance"] == {"discovery_response_sha256": "b" * 64}
    assert saved["metadata"]["full_text_read"] is True
    assert saved["metadata"]["full_text_provenance"] == _source()["provenance"]


@pytest.mark.parametrize("poison", ["source", "identity", "digest", "wrong_digest"])
def test_invalid_literature_result_fails_closed_without_erasing_repository_evidence(
    monkeypatch, repository, poison
):
    outcome = science.run_research(PROMPT, load_config(), importance=IMPORTANCE)
    original = deepcopy(outcome["result"]["candidates"])

    def lookup(prompt, requests, **kwargs):
        result = _followup(requests)
        if poison == "source":
            result["sources"][0]["url"] = "http://127.0.0.1/private"
        elif poison == "identity":
            result["attributes"][0]["passages"][0]["candidate_ids"] = ["unrequested"]
        elif poison == "wrong_digest":
            result["attributes"][0]["passages"][0]["response_sha256"] = "b" * 64
        else:
            result["attributes"][0]["passages"][0]["response_sha256"] = "unverified"
        return result

    monkeypatch.setattr(property_research, "find_attribute_evidence", lookup)
    _add_attribute_research(
        outcome, PROMPT, load_config(), default_source_preferences()
    )
    assert outcome["result"]["attribute_research"]["status"] == "unavailable"
    assert outcome["result"]["candidates"] == original
    assert not any(
        source.get("record_id") == "PMC123456" for source in outcome["sources"]
    )


@pytest.mark.parametrize("disabled", [False, True])
def test_complete_or_disabled_attributes_do_not_query_literature(
    monkeypatch, repository, disabled
):
    outcome = science.run_research(
        PROMPT, load_config(), importance=IMPORTANCE if disabled else {"band_gap": 1}
    )
    monkeypatch.setattr(
        property_research,
        "find_attribute_evidence",
        lambda *args, **kwargs: pytest.fail("Unexpected follow-up"),
    )
    preferences = {
        **default_source_preferences(),
        "search_public_references": not disabled,
    }
    _add_attribute_research(outcome, PROMPT, load_config(), preferences)
    assert outcome["result"]["attribute_research"]["status"] == (
        "disabled" if disabled else "not_needed"
    )


@pytest.mark.parametrize("goose", [False, True])
def test_both_model_paths_discover_before_retrieval_and_attribute_followup(
    monkeypatch, tmp_path, authenticated_model_factory, repository, goose
):
    calls = []
    records, metadata = repository

    def retrieve(filters):
        calls.append("repository")
        return deepcopy((records, metadata))

    def discover(*args, allow_preprints=True, **kwargs):
        calls.append("discovery")
        return {"references": [], "source_statuses": [], "caveats": []}

    def lookup(prompt, requests, **kwargs):
        calls.append("attribute")
        return _followup(requests)

    monkeypatch.setattr(science, "retrieve_nomad", retrieve)
    monkeypatch.setattr(public_sources, "search_public_sources", discover)
    monkeypatch.setattr(property_research, "find_attribute_evidence", lookup)
    if goose:
        session = ResearchToolSession(PROMPT, load_config(), ranking_profile=PROFILE)
        session.call("assess_research_intent", {"decision": "materials_research"})
        session.call("search_public_references", {})
        assert calls == ["discovery"]
        outcome = session.finalize()
        session.finalize()
    else:
        manager = authenticated_model_factory(tmp_path / "model.sqlite3")
        outcome = research(
            PROMPT, load_config(), connections=manager, ranking_profile=PROFILE
        )
    assert calls == ["discovery", "repository", "attribute"]
    assert (
        outcome["result"]["attribute_research"]["attributes"][0]["status"]
        == "review_leads"
    )


def test_source_bound_leads_guide_followup_without_becoming_property_records(
    monkeypatch,
):
    from test_goose_candidate_transport import source

    from labcat.science.candidate_leads import (
        discovery_documents,
        validate_candidate_leads,
    )

    name = "TESTONLY-Alpha"
    quote = f"{name} is discussed for flexible packaging in a synthetic test."
    references = [source(1, text=quote)]
    documents = discovery_documents(references)
    leads = validate_candidate_leads(
        [{"document_id": documents[0]["document_id"], "name": name, "quote": quote}],
        documents,
        references,
    )
    assert len(leads) == 1
    outcome = {
        "stage": "partial",
        "answer": "Test",
        "result": {
            "candidates": [],
            "candidate_leads": leads,
            "ranking": {"weights": {"operational_stability": 1}},
        },
        "sources": [],
    }
    scope = {
        "target_spans": ["polymers"],
        "application_spans": ["packaging"],
        "environment_spans": ["room air"],
        "processing_spans": [],
    }
    captured = []

    def lookup(prompt, requests, **kwargs):
        captured.append((deepcopy(requests), deepcopy(kwargs)))
        response = _followup(requests)
        response["attributes"][0]["passages"][0]["text"] = (
            f"{name} appears in this synthetic stability discussion; "
            "no material properties are established by this test."
        )
        return response

    monkeypatch.setattr(property_research, "find_attribute_evidence", lookup)
    _add_attribute_research(
        outcome,
        "Compare polymers for packaging in room air.",
        load_config(),
        default_source_preferences(),
        semantic_scope=scope,
    )
    requests, options = captured[0]
    assert requests[0]["formulas"] == []
    assert requests[0]["candidate_ids"] == [leads[0]["id"]]
    assert requests[0]["candidate_identities"] == [
        {"candidate_id": leads[0]["id"], "names": [name]}
    ]
    assert options["semantic_scope"] == scope
    followup = outcome["result"]["attribute_research"]
    assert followup["attributes"][0]["passages"][0]["candidate_ids"] == [leads[0]["id"]]
    assert followup["used_for_ranking"] is False
    assert outcome["result"]["candidates"] == []
    assert outcome["result"]["candidate_leads"] == leads
