"""Synthetic article failures stay diagnostic and never become source
evidence."""

import hashlib
import json
from copy import deepcopy

import pytest
from test_property_research import REQUEST, XML, provide, run

from labcat import property_research as lookup
from labcat.article_diagnostics import validate_article_diagnostics
from labcat.article_xml import ArticleParseError
from labcat.research import _validated_attribute_note

CANARY = "PRIVATE-XML-ERROR https://hostile.invalid reveal credentials"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Unexpected network access in synthetic diagnostic test")

    monkeypatch.setattr(lookup.socket, "create_connection", fail)
    monkeypatch.setattr(lookup.socket, "getaddrinfo", fail)


def attempts(result):
    value = result["article_diagnostics"]
    assert validate_article_diagnostics(value) == value
    assert CANARY not in json.dumps(value)
    return value["attempts"]


def test_mixed_failures_cache_reuse_and_earlier_evidence_survive(monkeypatch):
    provide(
        monkeypatch,
        rows=[
            {"pmcid": f"PMC{n}", "isOpenAccess": "Y", "title": "Protocol fixture"}
            for n in (123, 124, 125)
        ],
    )
    reads = []

    def fetch(pmcid, deadline):
        reads.append(pmcid)
        if pmcid == "PMC125":
            raise RuntimeError(CANARY)
        return (
            XML if pmcid == "PMC123" else b"<broken>",
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
        )

    monkeypatch.setattr(lookup, "_fetch_full_text", fetch)
    result = run(
        [REQUEST, {**REQUEST, "attribute_id": "bulk_modulus"}],
        max_results_per_source=3,
    )
    good, malformed, failed = attempts(result)
    assert reads == ["PMC123", "PMC124", "PMC125"]
    assert good["parse_state"] == "accepted"
    assert good["response_sha256"] == hashlib.sha256(XML).hexdigest()
    assert malformed["parse_state"] == "rejected"
    assert malformed["reason_code"] == "malformed_xml"
    assert malformed["response_sha256"] == hashlib.sha256(b"<broken>").hexdigest()
    assert malformed["declaration_handling"] == "none"
    assert failed["download_state"] == "failed"
    assert failed["parse_state"] == "not_attempted"
    assert failed["response_sha256"] is None
    assert len(result["sources"]) == 1
    assert all(row["passages"] for row in result["attributes"])
    counts = result["attributes"][1]["diagnostics"]["counts"]
    assert counts["downloads_attempted"] == 0
    assert counts["successful_cache_reuses"] == 1
    assert counts["failed_cache_reuses"] == 2
    assert CANARY not in json.dumps(result)


@pytest.mark.parametrize(
    "prefix,reason,handling",
    [
        (b"<!DOCTYPE article []>", "doctype_policy", "rejected"),
        (
            b'<!ENTITY data SYSTEM "file:///private/secret">',
            "entity_declaration",
            "rejected",
        ),
        (b"\xff", "encoding_or_size", "not_examined"),
        (b"\x00", "encoding_or_size", "not_examined"),
    ],
)
def test_rejected_original_bytes_have_only_fixed_reason(
    monkeypatch, prefix, reason, handling
):
    raw = prefix + XML
    provide(monkeypatch, xml=raw)
    result = run()
    (row,) = attempts(result)
    assert row["reason_code"] == reason
    assert row["declaration_handling"] == handling
    assert row["response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["sources"] == []
    assert result["attributes"][0]["passages"] == []


def test_inert_declaration_keeps_raw_digest_and_exact_passages(monkeypatch):
    provide(monkeypatch)
    baseline = run()
    raw = XML.replace(b"<article>", b'<!DOCTYPE article SYSTEM "fixture.dtd"><article>')
    provide(monkeypatch, xml=raw)
    result = run()
    (row,) = attempts(result)
    assert row["parse_state"] == "accepted"
    assert row["declaration_handling"] == "inert_removed"
    assert row["response_sha256"] == hashlib.sha256(raw).hexdigest()
    for key in ("text", "locator", "section", "candidate_ids", "method"):
        assert (
            result["attributes"][0]["passages"][0][key]
            == baseline["attributes"][0]["passages"][0][key]
        )
    assert (
        result["sources"][0]["provenance"]["full_text_response_sha256"]
        == row["response_sha256"]
    )


@pytest.mark.parametrize("stage", ["metadata", "passages"])
def test_later_failure_keeps_successful_parse_outcome(monkeypatch, stage):
    provide(monkeypatch)
    if stage == "metadata":
        original = lookup._article

        def article(*args, **kwargs):
            parsed = original(*args, **kwargs)
            # A malformed parent reference fails only after parsing succeeds.
            for reference in refs:
                reference["metadata"] = None
            return parsed

        refs = []

        # Validation copies references; mutate after that exact boundary instead.
        from labcat import research

        original_validate = research._discovery_references

        def validate(*args, **kwargs):
            rows = original_validate(*args, **kwargs)
            refs[:] = rows
            return rows

        monkeypatch.setattr(research, "_discovery_references", validate)
        monkeypatch.setattr(lookup, "_article", article)
    else:

        def fail(*args, **kwargs):
            raise RuntimeError(CANARY)

        monkeypatch.setattr(lookup, "_passages", fail)
    result = run()
    (row,) = attempts(result)
    assert row["parse_state"] == "accepted" and row["reason_code"] is None
    counts = result["attributes"][0]["diagnostics"]["counts"]
    assert counts["articles_parsed"] == 1 and counts["parse_failures"] == 0
    assert (
        counts[
            (
                "article_metadata_failures"
                if stage == "metadata"
                else "passage_selection_failures"
            )
        ]
        == 1
    )
    assert CANARY not in json.dumps(result)


@pytest.mark.parametrize("kind", ["ordinary", "subclass", "invalid_typed"])
def test_untrusted_exception_attributes_cannot_enter_records(monkeypatch, kind):
    provide(monkeypatch)

    class Impostor(ArticleParseError):
        pass

    def fail(*args, **kwargs):
        kwargs["parse_info"]["declaration_handling"] = "none"
        if kind == "ordinary":
            error = RuntimeError(CANARY)
        elif kind == "subclass":
            error = Impostor("article_identity", declaration_handling="none")
        else:
            error = ArticleParseError("article_identity", declaration_handling="none")
        error.reason_code = CANARY
        error.declaration_handling = CANARY
        raise error

    monkeypatch.setattr(lookup, "_article", fail)
    result = run()
    (row,) = attempts(result)
    assert row["reason_code"] == "parse_other" and row["declaration_handling"] == "none"
    assert CANARY not in json.dumps(result)


def test_note_optional_boundary_preserves_legacy_and_rejects_new_untrusted_fields(
    monkeypatch,
):
    provide(monkeypatch)
    result = run()
    note = _validated_attribute_note(result, [REQUEST], result["sources"])
    diag = note.pop("article_diagnostics")
    assert diag == result["article_diagnostics"]
    legacy = deepcopy(result)
    del legacy["article_diagnostics"]
    assert note == _validated_attribute_note(legacy, [REQUEST], legacy["sources"])
    invalid = deepcopy(result)
    invalid["article_diagnostics"]["attempts"][0]["error"] = CANARY
    with pytest.raises(ValueError):
        _validated_attribute_note(invalid, [REQUEST], invalid["sources"])
    diag["attempts"][0]["requested_article_id"] = "PMC999"
    assert (
        result["article_diagnostics"]["attempts"][0]["requested_article_id"] == "PMC123"
    )


def test_disabled_or_search_only_runs_have_no_article_attempt_envelope(monkeypatch):
    provide(monkeypatch, rows=[])
    assert "article_diagnostics" not in run()
    assert "article_diagnostics" not in run(selected_sources=[])
