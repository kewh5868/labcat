"""Offline failure injection; no production evidence or live provider
calls."""

import http.client
import json
from copy import deepcopy
from urllib.error import HTTPError

import pytest

from labcat import property_research, public_sources, science
from labcat.config import load_config
from labcat.research import _missing_attribute_requests
from labcat.science.retrieval_budget import bounded_deadline, repository_budget

SECRET_MARKER = "synthetic-request-secret-must-not-appear"
ERRORS = [
    lambda: HTTPError("https://example.invalid", 429, SECRET_MARKER, None, None),
    lambda: HTTPError("https://example.invalid", 503, SECRET_MARKER, None, None),
    lambda: TimeoutError(SECRET_MARKER),
    lambda: http.client.RemoteDisconnected(SECRET_MARKER),
    lambda: json.JSONDecodeError(SECRET_MARKER, "{", 1),
    lambda: TypeError(SECRET_MARKER),
    lambda: KeyError(SECRET_MARKER),
    lambda: IndexError(SECRET_MARKER),
    lambda: RuntimeError(SECRET_MARKER),
]


def failure(factory):
    def fail(*args, **kwargs):
        raise factory()

    return fail


def reference(identifier="PMC123"):
    return public_sources._reference(
        "europe_pmc",
        identifier,
        "Explicit offline materials protocol fixture",
        f"https://europepmc.org/articles/{identifier}",
        {"record_type": "open_access_publication", "full_text_read": False},
        b"offline protocol fixture only",
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
    )


@pytest.fixture
def material_records():
    # Existing checked-in historical evidence is substituted explicitly in tests;
    # the runtime never reads this fixture on network failure.
    return science.load_snapshot()[0]


@pytest.mark.parametrize("error", ERRORS)
def test_property_source_failure_preserves_other_source_ranked_evidence(
    monkeypatch, material_records, error
):
    monkeypatch.setattr(science, "retrieve_live", failure(error))
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda _: (deepcopy(material_records), {})
    )
    outcome = science.run_research(
        "Find oxide materials for a dielectric screening comparison",
        load_config(),
        mp_api_key="offline-test-only",
        importance={"band_gap": 1},
    )
    assert outcome["stage"] == "partial"
    assert outcome["result"]["candidates"]
    attempts = outcome["result"]["retrieval"]["repository_attempts"]
    assert [(row["repository"], row["status"]) for row in attempts] == [
        ("materials_project", "unavailable"),
        ("nomad", "ok"),
    ]
    assert SECRET_MARKER not in json.dumps(outcome)


@pytest.mark.parametrize(
    "malformation",
    [
        "duplicate",
        "missing_formula",
        "missing_method",
        "bad_gap",
        "bad_url",
        "bad_shape",
    ],
)
def test_malformed_repository_batch_is_rejected_before_combining_with_valid_records(
    monkeypatch, material_records, malformation
):
    bad = deepcopy(material_records[:1])
    if malformation == "duplicate":
        bad.append(deepcopy(bad[0]))
    elif malformation == "missing_formula":
        bad[0].pop("formula")
    elif malformation == "missing_method":
        bad[0].pop("method")
    elif malformation == "bad_gap":
        bad[0]["band_gap_ev"] = SECRET_MARKER
    elif malformation == "bad_url":
        bad[0]["provenance"]["source_url"] = "http://localhost/private"
    else:
        bad = None
    monkeypatch.setattr(science, "retrieve_live", lambda *_: (bad, {}))
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda _: (deepcopy(material_records), {})
    )
    outcome = science.run_research(
        "Find oxide dielectric materials",
        load_config(),
        mp_api_key="offline-only",
        importance={"band_gap": 1},
    )
    assert outcome["result"]["candidates"]
    assert (
        outcome["result"]["retrieval"]["repository_attempts"][0]["status"]
        == "unavailable"
    )
    assert SECRET_MARKER not in json.dumps(outcome)


@pytest.mark.parametrize(
    "malformation", [None, "raw_digest", "band_gap", "formula", "property_kind"]
)
def test_comparison_source_binding_is_checked_before_healthy_sources_merge(
    monkeypatch, material_records, malformation
):
    from test_evidence_comparison_workflow import adapter_record

    rows = [adapter_record(1, 2.0, True), adapter_record(2, 1.5, False)]
    # Keep historical fixtures composition-disjoint from the synthetic pair;
    # this test covers source isolation, not cross-source scientific equivalence.
    healthy = [row for row in material_records if row["formula"] != "SiO2"]
    if malformation == "raw_digest":
        rows[0]["provenance"]["raw_fields_sha256"] = "0" * 64
    elif malformation == "band_gap":
        rows[0]["band_gap_ev"] = 2.5
    elif malformation == "formula":
        # The elements remain unchanged, so shape validation alone is insufficient.
        rows[0]["formula"] = "SiO"
    elif malformation == "property_kind":
        rows[0]["band_gap_kind"] = "band gap (optical, transmission)"
    before = deepcopy(rows)
    monkeypatch.setattr(
        science, "retrieve_hybrid3", lambda *a, **kw: (deepcopy(rows), {})
    )
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda *a, **kw: (deepcopy(healthy), {})
    )
    outcome = science.run_research(
        "Compare semiconductor materials.",
        load_config(),
        importance={"band_gap": 1},
        allow_hybrid3=True,
        allow_nomad=True,
        materials_project_mode="off",
    )
    assert outcome["stage"] == "partial"
    assert outcome["result"]["candidates"]
    assert rows == before, "source records are never repaired to pass validation"
    attempts = outcome["result"]["retrieval"]["repository_attempts"]
    assert [(row["repository"], row["status"]) for row in attempts] == [
        ("hybrid3", "unavailable" if malformation else "ok"),
        ("nomad", "ok"),
    ]
    if malformation:
        healthy_ids = {row["material_id"] for row in healthy}
        assert all(
            row["material_id"] in healthy_ids for row in outcome["result"]["candidates"]
        )
        for field in ("pi_summary", "technical_audit"):
            assert "Source availability:" in outcome[field]
            assert "HybriD³ (property search)" in outcome[field]
            assert "[R1]" in outcome[field]
    else:
        for field in ("pi_summary", "technical_audit"):
            assert "experimental 2 eV" in outcome[field]
            assert "computed 1.5 eV" in outcome[field]


def test_all_repositories_unavailable_returns_explanation_without_fabricated_candidates(
    monkeypatch,
):
    monkeypatch.setattr(science, "retrieve_live", failure(ERRORS[0]))
    monkeypatch.setattr(science, "retrieve_nomad", failure(ERRORS[3]))
    monkeypatch.setattr(
        science, "load_snapshot", lambda: pytest.fail("No fallback cohort")
    )
    outcome = science.run_research(
        "Find oxide dielectric materials", load_config(), mp_api_key="offline-only"
    )
    assert outcome["stage"] == "partial"
    assert outcome["result"]["candidates"] == []
    assert outcome["sources"] == []
    assert outcome["result"]["retrieval"]["status"] == "unavailable"
    assert "unavailable" in outcome["answer"]
    assert all(
        row["status"] == "unavailable"
        for row in outcome["result"]["retrieval"]["repository_attempts"]
    )


def test_selected_api_outage_still_uses_independently_enabled_public_repository(
    monkeypatch, material_records
):
    monkeypatch.setattr(science, "retrieve_live", failure(ERRORS[1]))
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda _: (deepcopy(material_records), {})
    )
    result = science.run_research(
        "Find oxide dielectric materials",
        load_config(),
        mp_api_key="offline-test-only",
        materials_project_mode="api",
        allow_nomad=True,
        importance={"band_gap": 1},
    )["result"]
    assert result["candidates"]
    assert [
        (row["repository"], row["status"])
        for row in result["retrieval"]["repository_attempts"]
    ] == [("materials_project", "unavailable"), ("nomad", "ok")]


@pytest.mark.parametrize("api_key", [None, ""])
def test_missing_selected_api_key_keeps_enabled_repository_results(
    monkeypatch, material_records, api_key
):
    monkeypatch.setattr(
        science, "retrieve_live", lambda *a: pytest.fail("No unusable API key sent")
    )
    monkeypatch.setattr(
        science, "load_snapshot", lambda: pytest.fail("No snapshot fallback")
    )
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda _: (deepcopy(material_records), {})
    )
    outcome = science.run_research(
        "Find oxide dielectric materials",
        load_config(),
        mp_api_key=api_key,
        materials_project_mode="api",
        allow_nomad=True,
        importance={"band_gap": 1},
    )
    assert outcome["stage"] == "partial" and outcome["result"]["candidates"]
    attempts = outcome["result"]["retrieval"]["repository_attempts"]
    assert [(row["repository"], row["status"]) for row in attempts] == [
        ("materials_project", "unavailable"),
        ("nomad", "ok"),
    ]
    assert attempts[0]["records_retrieved"] == 0
    for style in ("pi_summary", "technical_audit"):
        assert "Source availability:" in outcome[style]
        assert "Materials Project (property search)" in outcome[style]


@pytest.mark.parametrize(
    "prompt, allow_nomad",
    [("Find oxide dielectric materials", False), ("Research polymers", True)],
)
def test_missing_api_key_does_not_enable_unselected_or_unsuitable_repositories(
    monkeypatch, prompt, allow_nomad
):
    for adapter in (
        "retrieve_live",
        "retrieve_nomad",
        "retrieve_hybrid3",
        "retrieve_public_dielectric",
        "load_snapshot",
    ):
        monkeypatch.setattr(
            science, adapter, lambda *a, **kw: pytest.fail("Unexpected retrieval")
        )
    outcome = science.run_research(
        prompt,
        load_config(),
        materials_project_mode="api",
        allow_nomad=allow_nomad,
    )
    assert outcome["stage"] == "partial"
    assert outcome["result"]["candidates"] == []
    attempts = outcome["result"]["retrieval"]["repository_attempts"]
    assert [(row["repository"], row["status"]) for row in attempts] == [
        ("materials_project", "unavailable")
    ]


def test_missing_api_and_failed_public_repository_return_honest_partial(monkeypatch):
    monkeypatch.setattr(science, "retrieve_nomad", failure(ERRORS[0]))
    monkeypatch.setattr(
        science, "load_snapshot", lambda: pytest.fail("No snapshot fallback")
    )
    outcome = science.run_research(
        "Find oxide dielectric materials",
        load_config(),
        materials_project_mode="api",
        allow_nomad=True,
    )
    assert outcome["stage"] == "partial"
    assert outcome["result"]["candidates"] == []
    retrieval = outcome["result"]["retrieval"]
    assert retrieval["status"] == "unavailable"
    assert [
        (row["repository"], row["status"]) for row in retrieval["repository_attempts"]
    ] == [("materials_project", "unavailable"), ("nomad", "unavailable")]


def test_refresh_failure_does_not_prevent_broad_query(monkeypatch, material_records):
    calls = []

    def retrieve(filters):
        calls.append(filters)
        if "entry_ids" in filters:
            raise RuntimeError(SECRET_MARKER)
        return deepcopy(material_records), {}

    monkeypatch.setattr(science, "retrieve_nomad", retrieve)
    records, metadata = science._retrieve_repositories(
        {},
        mp_api_key=None,
        mode="auto",
        allow_nomad=True,
        prior_material_ids=["nomad:offline-test-entry"],
    )
    assert records and len(calls) == 2
    assert metadata["chat_source_refresh"]["attempts"][0]["status"] == "unavailable"
    assert metadata["repository_attempts"][0]["status"] == "ok"


def test_early_source_timeout_keeps_budget_for_later_sources(
    monkeypatch, material_records
):
    clock, calls = [100.0], []
    monkeypatch.setattr(science.time, "monotonic", lambda: clock[0])

    def timed(name, fails=False):
        def retrieve(*args, **kwargs):
            allowed = bounded_deadline(99) - clock[0]
            calls.append((name, allowed))
            if fails:
                clock[0] += allowed + 0.01
                raise TimeoutError(SECRET_MARKER)
            clock[0] += 0.01
            return deepcopy(material_records[:1]), {}

        return retrieve

    monkeypatch.setattr(science, "retrieve_hybrid3", timed("hybrid3", True))
    monkeypatch.setattr(science, "retrieve_live", timed("materials_project"))
    monkeypatch.setattr(
        science, "retrieve_public_dielectric", timed("public_dielectric")
    )
    monkeypatch.setattr(science, "retrieve_nomad", timed("nomad"))
    with repository_budget(seconds=30):
        records, metadata = science._retrieve_repositories(
            {},
            mp_api_key="offline-only",
            mode="auto",
            allow_nomad=True,
            allow_public_dielectric=True,
            allow_hybrid3=True,
        )
    assert records and len(calls) == 4
    assert calls[0][1] == pytest.approx(7.5)
    assert all(0 < allowed <= 30 for _, allowed in calls)
    assert metadata["repository_attempts"][0]["status"] == "unavailable"
    assert all(row["status"] == "ok" for row in metadata["repository_attempts"][1:])


@pytest.mark.parametrize(
    "error", ERRORS + [lambda: public_sources.PublicSourceError(SECRET_MARKER)]
)
def test_discovery_source_error_does_not_discard_other_public_hits(monkeypatch, error):
    monkeypatch.setitem(public_sources._ADAPTERS, "wikipedia", failure(error))
    monkeypatch.setitem(
        public_sources._ADAPTERS,
        "europe_pmc",
        lambda *a, **kw: ([reference()], "Offline fixture"),
    )
    result = public_sources.search_public_sources(
        "oxide materials", ["wikipedia", "europe_pmc"]
    )
    assert [row["record_id"] for row in result["references"]] == ["PMC123"]
    assert [row["status"] for row in result["source_statuses"]] == ["unavailable", "ok"]
    assert SECRET_MARKER not in json.dumps(result)


def test_invalid_discovery_reference_is_rejected_before_sources_merge(monkeypatch):
    bad = {**reference(), "url": "https://unapproved.invalid/private"}
    monkeypatch.setitem(
        public_sources._ADAPTERS, "arxiv", lambda *a, **kw: ([bad], "Invalid fixture")
    )
    monkeypatch.setitem(
        public_sources._ADAPTERS,
        "europe_pmc",
        lambda *a, **kw: ([reference()], "Offline fixture"),
    )
    result = public_sources.search_public_sources(
        "oxide materials", ["arxiv", "europe_pmc"]
    )
    assert len(result["references"]) == 1
    assert [row["status"] for row in result["source_statuses"]] == ["unavailable", "ok"]


def test_all_discovery_sources_unavailable_have_separate_statuses(monkeypatch):
    for source in ("wikipedia", "europe_pmc"):
        monkeypatch.setitem(public_sources._ADAPTERS, source, failure(ERRORS[3]))
    result = public_sources.search_public_sources(
        "oxide materials", ["wikipedia", "europe_pmc"]
    )
    assert result["references"] == []
    assert len(result["source_statuses"]) == 2
    assert all(row["status"] == "unavailable" for row in result["source_statuses"])


REQUEST = {"attribute_id": "band_gap", "candidate_ids": [], "formulas": ["TiO2"]}
ARTICLE = b"""<article><front><article-meta>
<article-id pub-id-type="pmcid">456</article-id>
</article-meta></front><body><sec><title>Offline fixture</title><p>
Synthetic protocol text only: TiO2 band gap discussion, without a measured value.
</p></sec></body></article>"""


@pytest.mark.parametrize("error", ERRORS)
def test_unavailable_article_does_not_erase_other_literal_passages(monkeypatch, error):
    monkeypatch.setattr(
        property_research,
        "_search",
        lambda *a, **kw: [reference(), reference("PMC456")],
    )

    def article(identity, deadline):
        if identity == "PMC123":
            raise error()
        return (
            ARTICLE,
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC456/fullTextXML",
        )

    monkeypatch.setattr(property_research, "_fetch_full_text", article)
    result = property_research.find_attribute_evidence(
        "Find materials", [REQUEST], selected_sources=["europe_pmc"]
    )
    assert result["status"] == "partial"
    assert result["attributes"][0]["status"] == "review_leads"
    assert result["attributes"][0]["passages"][0]["article_id"] == "PMC456"
    assert result["attributes"][0]["passages"][0]["method"] is None
    assert SECRET_MARKER not in json.dumps(result)


def test_failed_attribute_query_preserves_previous_passages_and_tries_later_attributes(
    monkeypatch,
):
    calls = []

    def search(query, *args, **kwargs):
        calls.append(query)
        if len(calls) == 2:
            raise RuntimeError(SECRET_MARKER)
        return [reference("PMC456")]

    monkeypatch.setattr(property_research, "_search", search)
    monkeypatch.setattr(
        property_research,
        "_fetch_full_text",
        lambda *a: (
            ARTICLE,
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC456/fullTextXML",
        ),
    )
    result = property_research.find_attribute_evidence(
        "Find materials",
        [
            REQUEST,
            {**REQUEST, "attribute_id": "bulk_modulus"},
            {**REQUEST, "attribute_id": "density"},
        ],
        selected_sources=["europe_pmc"],
    )
    assert len(calls) == 3
    assert result["attributes"][0]["passages"]
    assert result["attributes"][1]["status"] == "unavailable"
    assert result["sources"]


def test_later_passage_failure_keeps_citation_for_earlier_attribute(monkeypatch):
    monkeypatch.setattr(
        property_research, "_search", lambda *a, **kw: [reference("PMC456")]
    )
    fetched = []

    def full_text(*args):
        fetched.append(args)
        return (
            ARTICLE,
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC456/fullTextXML",
        )

    monkeypatch.setattr(property_research, "_fetch_full_text", full_text)
    passages = property_research._passages
    calls = []

    def partially_available(paragraphs, terms, formulas, **kwargs):
        calls.append(terms)
        if len(calls) == 2:
            raise RuntimeError(SECRET_MARKER)
        return passages(paragraphs, terms, formulas, **kwargs)

    monkeypatch.setattr(property_research, "_passages", partially_available)
    result = property_research.find_attribute_evidence(
        "Find materials",
        [REQUEST, {**REQUEST, "attribute_id": "density"}],
        selected_sources=["europe_pmc"],
    )
    assert len(fetched) == 1 and len(calls) == 2
    assert result["status"] == "partial"
    first, later = result["attributes"]
    assert first["status"] == "review_leads"
    assert later["status"] == "unavailable"
    assert len(result["sources"]) == 1
    source = result["sources"][0]
    passage = first["passages"][0]
    assert passage["article_id"] == source["record_id"]
    assert passage["source_url"] == source["url"]
    assert (
        passage["response_sha256"] == source["provenance"]["full_text_response_sha256"]
    )
    assert SECRET_MARKER not in json.dumps(result)


@pytest.mark.parametrize(
    "scope", ["stability", "ambient_phase_stability", "operational_stability"]
)
def test_selected_missing_stability_gets_a_query_slot_without_increasing_budget(scope):
    weights = {
        "direct_gap": 1,
        "refractive_index": 0.9,
        "solution_processability": 0.8,
        scope: 0.1,
    }
    outcome = {"result": {"ranking": {"weights": weights}, "candidates": []}}
    requests = _missing_attribute_requests(outcome, load_config())
    assert requests[0]["attribute_id"] == scope
    assert [row["attribute_id"] for row in requests[1:]] == [
        "direct_gap",
        "refractive_index",
        "solution_processability",
    ]
    assert scope in property_research.ATTRIBUTE_TERMS
    assert property_research.MAX_ATTRIBUTES == 3


def test_unselected_stability_is_not_silently_added_to_followup_preferences():
    outcome = {
        "result": {
            "ranking": {"weights": {"stability": 0, "band_gap": 1}},
            "candidates": [],
        }
    }
    assert [
        row["attribute_id"]
        for row in _missing_attribute_requests(outcome, load_config())
    ] == ["band_gap"]


@pytest.mark.parametrize(
    "scope, text",
    [
        (
            "ambient_phase_stability",
            "TiO2 room temperature phase stability was discussed.",
        ),
        (
            "operational_stability",
            "TiO2 operational stability and degradation were discussed.",
        ),
    ],
)
def test_stability_scopes_search_and_retain_literal_review_passages(
    monkeypatch, scope, text
):
    queries = []

    def search(query, *args, **kwargs):
        queries.append(query)
        return [reference("PMC456")]

    body = ARTICLE.replace(
        b"Synthetic protocol text only: TiO2 band gap discussion, "
        b"without a measured value.",
        text.encode(),
    )
    monkeypatch.setattr(property_research, "_search", search)
    monkeypatch.setattr(
        property_research,
        "_fetch_full_text",
        lambda *a: (
            body,
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC456/fullTextXML",
        ),
    )
    result = property_research.find_attribute_evidence(
        "Screen candidate materials for stability",
        [{**REQUEST, "attribute_id": scope}],
        selected_sources=["europe_pmc"],
    )
    assert queries and any(
        term in queries[0] for term in property_research.ATTRIBUTE_TERMS[scope]
    )
    item = result["attributes"][0]
    assert item["status"] == "review_leads"
    assert item["passages"][0]["text"] == text
    assert item["passages"][0]["method"] is None
    assert "score" not in item["passages"][0]
