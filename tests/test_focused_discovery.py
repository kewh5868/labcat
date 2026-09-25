"""Compact search hints retain application terms without changing source
policy."""

import json
import time

import pytest

from labcat import public_sources as public

TOPIC = "organic semiconductor photovoltaic donor acceptor"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Focused discovery test attempted a network connection")

    monkeypatch.setattr(public.socket, "create_connection", fail)
    monkeypatch.setattr(public.socket, "getaddrinfo", fail)
    monkeypatch.setattr(public, "_ARXIV_LAST", 0)


def capture_empty_results(monkeypatch):
    calls = []

    def fetch(source, params, deadline):
        calls.append((source, params))
        bodies = {
            "wikipedia": {"query": {"pages": []}},
            "openalex": {"results": []},
            "chemrxiv": {"results": []},
            "europe_pmc": {"resultList": {"result": []}},
        }
        raw = (
            b'<feed xmlns="http://www.w3.org/2005/Atom"/>'
            if source == "arxiv"
            else json.dumps(bodies[source]).encode()
        )
        host, path = public.ROUTES[source]
        return raw, "https://" + host + path

    monkeypatch.setattr(public, "_fetch", fetch)
    return calls


@pytest.mark.parametrize(
    "provider,field",
    [
        ("europe_pmc", "query"),
        ("arxiv", "search_query"),
        ("wikipedia", "gsrsearch"),
        ("openalex", "search"),
        ("chemrxiv", "search"),
    ],
)
def test_focused_topic_retains_material_and_application_terms(
    monkeypatch, provider, field
):
    calls = capture_empty_results(monkeypatch)
    result = public.search_public_sources(TOPIC, [provider], focused_topic=True)
    assert len(calls) == 1
    sent = calls[0][1][field]
    assert all(term in sent for term in TOPIC.split())
    assert result["references"] == []
    assert result["source_statuses"][0]["status"] == "no_results"
    if provider == "europe_pmc":
        assert sent.endswith(" AND OPEN_ACCESS:Y")
    if provider in {"openalex", "chemrxiv"}:
        assert "open_access.is_oa:true,is_retracted:false" in calls[0][1]["filter"]
    if provider == "wikipedia":
        assert calls[0][1]["gsrnamespace"] == 0


def test_long_conversational_query_keeps_existing_broad_behavior():
    question = (
        "Find organic semiconductor materials for photovoltaic donor and acceptor "
        "layers with public properties and reported device stability."
    )
    assert public._publication_query(question) == '("organic" AND "semiconductor")'
    focused = public._publication_query(TOPIC, focused_topic=True)
    assert focused == (
        '("organic" AND "semiconductor" AND "photovoltaic" AND "donor" AND "acceptor")'
    )


@pytest.mark.parametrize(
    "provider,field",
    [
        ("europe_pmc", "query"),
        ("arxiv", "search_query"),
        ("wikipedia", "gsrsearch"),
        ("openalex", "search"),
        ("chemrxiv", "search"),
    ],
)
def test_focused_index_query_is_bounded_and_strips_user_search_operators(
    monkeypatch, provider, field
):
    calls = capture_empty_results(monkeypatch)
    topic = (
        "nitride semiconductor optoelectronic emission donor acceptor absorption "
        "transport extraword OPEN_ACCESS:N https://private.example/path"
    )
    public.search_public_sources(topic, [provider], focused_topic=True)
    params = calls[0][1]
    expected = [
        "nitride",
        "semiconductor",
        "optoelectronic",
        "emission",
        "donor",
        "acceptor",
        "absorption",
        "transport",
    ]
    assert all(term in params[field] for term in expected)
    assert "extraword" not in params[field]
    assert "OPEN_ACCESS:N" not in params[field]
    assert "private" not in params[field]
    if provider in {"openalex", "chemrxiv"}:
        assert params["search"].split() == expected
        assert "open_access.is_oa:true,is_retracted:false" in params["filter"]


@pytest.mark.parametrize(
    "provider,field",
    [("wikipedia", "gsrsearch"), ("openalex", "search"), ("chemrxiv", "search")],
)
def test_default_index_query_preserves_legacy_three_term_limit(
    monkeypatch, provider, field
):
    calls = capture_empty_results(monkeypatch)
    public.search_public_sources(TOPIC, [provider])
    assert calls[0][1][field] == "organic semiconductor photovoltaic"


@pytest.mark.parametrize("focused_topic", [1, "yes", None])
def test_invalid_focus_setting_is_rejected_before_network(focused_topic):
    with pytest.raises(ValueError, match="Focused discovery"):
        public.search_public_sources(TOPIC, ["openalex"], focused_topic=focused_topic)


@pytest.mark.parametrize("topic", ["x" * 161, "word " * 17])
def test_focused_topic_must_be_short(topic):
    with pytest.raises(ValueError, match="short topic"):
        public.search_public_sources(topic, ["openalex"], focused_topic=True)


def test_focused_discovery_cannot_enable_disabled_preprints(monkeypatch):
    calls = capture_empty_results(monkeypatch)
    result = public.search_public_sources(
        TOPIC, ["chemrxiv", "arxiv"], focused_topic=True, allow_preprints=False
    )
    assert calls == []
    assert result["references"] == []
    assert {row["status"] for row in result["source_statuses"]} == {"skipped"}


def test_focus_option_does_not_rewrite_material_repository_queries(monkeypatch):
    calls = []

    def repository(query, limit, deadline):
        calls.append((query, limit))
        return [], "Synthetic empty repository response."

    monkeypatch.setitem(public._ADAPTERS, "nomad", repository)
    result = public.search_public_sources(TOPIC, ["nomad"], focused_topic=True)
    assert calls == [(TOPIC, 5)]
    assert result["source_statuses"][0]["status"] == "no_results"


@pytest.mark.parametrize(
    "deadline", [True, "123", [], float("nan"), float("inf"), -float("inf"), 10**1000]
)
def test_invalid_shared_deadline_is_rejected_before_network(deadline):
    with pytest.raises(ValueError, match="finite monotonic"):
        public.search_public_sources(TOPIC, ["openalex"], deadline=deadline)


@pytest.mark.parametrize("offset", [0, -1])
def test_expired_deadline_returns_fixed_unavailable_without_starting_workers(
    monkeypatch, offset
):
    def fail(*args, **kwargs):
        pytest.fail("Expired discovery started worker threads")

    monkeypatch.setattr(public, "ThreadPoolExecutor", fail)
    result = public.search_public_sources(
        TOPIC,
        ["arxiv", "openalex", "wikipedia", "openalex"],
        focused_topic=True,
        allow_preprints=False,
        deadline=time.monotonic() + offset,
    )
    assert result["references"] == []
    assert result["source_statuses"][0]["status"] == "skipped"
    assert result["source_statuses"][1:] == [
        {
            "source_id": source,
            "status": "unavailable",
            "message": (
                "Source unavailable within the request budget; no result was invented."
            ),
            "reference_count": 0,
        }
        for source in ("openalex", "wikipedia")
    ]


@pytest.mark.parametrize("caller_seconds", [None, 2, 120])
def test_all_adapters_share_earlier_caller_or_per_call_deadline(
    monkeypatch, caller_seconds
):
    deadlines = []

    def repository(query, limit, deadline):
        deadlines.append(deadline)
        return [], "Synthetic empty repository response."

    monkeypatch.setitem(public._ADAPTERS, "nomad", repository)
    monkeypatch.setitem(public._ADAPTERS, "hybrid3", repository)
    started = time.monotonic()
    caller_deadline = None if caller_seconds is None else started + caller_seconds
    result = public.search_public_sources(
        TOPIC, ["nomad", "hybrid3"], deadline=caller_deadline
    )
    finished = time.monotonic()
    assert len(deadlines) == 2
    assert deadlines[0] == deadlines[1]
    if caller_seconds == 2:
        assert deadlines[0] == caller_deadline
    else:
        assert started + public.MAX_SECONDS <= deadlines[0]
        assert deadlines[0] <= finished + public.MAX_SECONDS
    assert {row["status"] for row in result["source_statuses"]} == {"no_results"}


def test_caller_deadline_keeps_partial_results_and_excludes_late_records(monkeypatch):
    quick_reference = public._reference(
        "hybrid3",
        "100001",
        "Synthetic quick reference fixture",
        "https://materials.hybrid3.duke.edu/materials/systems/100001/",
        {"record_type": "material_identity"},
        b"synthetic quick identity response; no material facts",
        "https://materials.hybrid3.duke.edu/api/materials/systems/",
    )
    late_reference = public._reference(
        "nomad",
        "synthetic-late",
        "Synthetic late reference fixture",
        "https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/synthetic-late",
        {"record_type": "material_identity"},
        b"synthetic late identity response; no material facts",
        "https://nomad-lab.eu/prod/v1/api/v1/entries/query",
    )

    def quick(*args):
        return [quick_reference], "Synthetic quick result."

    def slow(*args):
        time.sleep(0.08)
        return [late_reference], "Synthetic late result."

    monkeypatch.setitem(public._ADAPTERS, "hybrid3", quick)
    monkeypatch.setitem(public._ADAPTERS, "nomad", slow)
    result = public.search_public_sources(
        TOPIC, ["hybrid3", "nomad"], deadline=time.monotonic() + 0.02
    )
    assert result["references"] == [quick_reference]
    assert [row["status"] for row in result["source_statuses"]] == [
        "ok",
        "unavailable",
    ]
