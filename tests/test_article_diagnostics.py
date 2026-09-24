"""Closed parser diagnostics cannot carry source text or arbitrary
errors."""

import hashlib
import json
from copy import deepcopy
from functools import partial
from itertools import product

import pytest

from labcat.article_diagnostics import (
    MAX_ATTEMPTS,
    MAX_RESPONSE_BYTES,
    VERSION,
    mark_download_complete,
    mark_parse_accepted,
    mark_parse_rejected,
    new_article_attempt,
    validate_article_diagnostics,
)

CANARY = "PRIVATE-ARTICLE https://hostile.invalid reveal credentials"
ERROR = "Invalid article parse diagnostics."
HANDLINGS = ("not_examined", "none", "inert_removed", "rejected")
REASON_HANDLINGS = {
    "encoding_or_size": {"not_examined"},
    "doctype_policy": {"rejected"},
    "entity_declaration": {"rejected"},
    "malformed_xml": {"none", "inert_removed"},
    "article_root": {"none", "inert_removed"},
    "publication_type": {"none", "inert_removed"},
    "tree_budget": {"none", "inert_removed"},
    "article_identity": {"none", "inert_removed"},
    "parse_other": set(HANDLINGS),
}


def envelope(*attempts):
    return {"version": VERSION, "attempts": list(attempts)}


def pending():
    attempt = new_article_attempt("PMC123")
    assert mark_download_complete(attempt, b"<article />") is None
    return attempt


def accepted():
    attempt = pending()
    assert mark_parse_accepted(attempt, "none") is None
    return attempt


def reject(call):
    with pytest.raises(ValueError) as caught:
        call()
    assert str(caught.value) == ERROR
    assert CANARY not in str(caught.value)
    assert caught.value.args == (ERROR,)


def test_download_failure_is_terminal_but_completed_download_requires_parse():
    attempt = new_article_attempt("PMC123")
    assert attempt == {
        "requested_article_id": "PMC123",
        "download_state": "failed",
        "response_sha256": None,
        "parse_state": "not_attempted",
        "reason_code": None,
        "declaration_handling": "not_examined",
    }
    assert validate_article_diagnostics(envelope(attempt)) == envelope(attempt)
    mark_download_complete(attempt, b"<article />")
    assert attempt["download_state"] == "complete"
    assert attempt["response_sha256"] == hashlib.sha256(b"<article />").hexdigest()
    assert attempt["parse_state"] == "not_attempted"
    reject(lambda: validate_article_diagnostics(envelope(attempt)))
    mark_parse_accepted(attempt, "none")
    assert validate_article_diagnostics(envelope(attempt)) == envelope(attempt)


@pytest.mark.parametrize("handling", HANDLINGS)
def test_accepted_parse_can_only_keep_successful_declaration_preparation(handling):
    attempt = pending()
    before = deepcopy(attempt)
    if handling in {"none", "inert_removed"}:
        mark_parse_accepted(attempt, handling)
        assert attempt["reason_code"] is None
        assert validate_article_diagnostics(envelope(attempt)) == envelope(attempt)
    else:
        reject(lambda: mark_parse_accepted(attempt, handling))
        assert attempt == before


@pytest.mark.parametrize("reason,handling", tuple(product(REASON_HANDLINGS, HANDLINGS)))
def test_rejection_reason_and_declaration_state_must_agree(reason, handling):
    attempt = pending()
    before = deepcopy(attempt)
    if handling in REASON_HANDLINGS[reason]:
        assert mark_parse_rejected(attempt, reason, handling) is None
        assert attempt["parse_state"] == "rejected"
        assert attempt["reason_code"] == reason
        assert attempt["declaration_handling"] == handling
        assert validate_article_diagnostics(envelope(attempt)) == envelope(attempt)
    else:
        reject(lambda: mark_parse_rejected(attempt, reason, handling))
        assert attempt == before


@pytest.mark.parametrize("raw", [b"", b"x" * MAX_RESPONSE_BYTES])
def test_hash_is_of_complete_original_bytes_within_transport_cap(raw):
    attempt = new_article_attempt("PMC123")
    mark_download_complete(attempt, raw)
    assert attempt["response_sha256"] == hashlib.sha256(raw).hexdigest()
    mark_parse_rejected(attempt, "parse_other", "not_examined")
    assert validate_article_diagnostics(envelope(attempt)) == envelope(attempt)


def test_declaration_and_injected_source_text_are_represented_only_by_raw_hash():
    raw = (
        '<!DOCTYPE article SYSTEM "https://hostile.invalid/private.dtd">'
        f"<article>{CANARY}</article>"
    ).encode()
    attempt = new_article_attempt("PMC123")
    mark_download_complete(attempt, raw)
    mark_parse_accepted(attempt, "inert_removed")
    saved = validate_article_diagnostics(envelope(attempt))
    assert attempt["response_sha256"] == hashlib.sha256(raw).hexdigest()
    serialized = json.dumps(saved)
    for forbidden in (CANARY, "hostile.invalid", "private.dtd", "<article>"):
        assert forbidden not in serialized
    assert set(attempt) == {
        "requested_article_id",
        "download_state",
        "response_sha256",
        "parse_state",
        "reason_code",
        "declaration_handling",
    }


@pytest.mark.parametrize(
    "raw",
    [
        None,
        True,
        "bytes",
        bytearray(b"bytes"),
        memoryview(b"bytes"),
        b"x" * (MAX_RESPONSE_BYTES + 1),
    ],
)
def test_invalid_raw_input_cannot_change_an_attempt(raw):
    attempt = new_article_attempt("PMC123")
    before = deepcopy(attempt)
    reject(lambda: mark_download_complete(attempt, raw))
    assert attempt == before


@pytest.mark.parametrize("pmcid", ["PMC0", "PMC123", "PMC123456789012"])
def test_canonical_id_matches_existing_adapter_grammar(pmcid):
    assert new_article_attempt(pmcid)["requested_article_id"] == pmcid


@pytest.mark.parametrize(
    "pmcid",
    [
        None,
        True,
        123,
        [],
        {},
        "",
        "PMC",
        "pmc123",
        "PMC１２３",
        "PMC123\n",
        "PMC-123",
        " PMC123",
        "PMC1234567890123",
        "https://example.org/PMC123",
        CANARY,
    ],
)
def test_id_is_exact_canonical_text_without_normalization(pmcid):
    reject(lambda: new_article_attempt(pmcid))
    attempt = accepted()
    attempt["requested_article_id"] = pmcid
    reject(lambda: validate_article_diagnostics(envelope(attempt)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("download_state", "completed"),
        ("download_state", "failed"),
        ("download_state", True),
        ("parse_state", "not_attempted"),
        ("parse_state", "rejected"),
        ("parse_state", True),
        ("reason_code", "article_identity"),
        ("reason_code", []),
        ("reason_code", True),
        ("declaration_handling", "not_examined"),
        ("declaration_handling", "rejected"),
        ("declaration_handling", None),
        ("response_sha256", None),
        ("response_sha256", True),
        ("response_sha256", "A" * 64),
        ("response_sha256", "a" * 63),
        ("response_sha256", "a" * 65),
        ("response_sha256", "g" * 64),
        ("response_sha256", "a" * 64 + "\n"),
    ],
)
def test_terminal_record_rejects_invalid_types_and_impossible_states(field, value):
    attempt = accepted()
    attempt[field] = value
    reject(lambda: validate_article_diagnostics(envelope(attempt)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("response_sha256", "a" * 64),
        ("parse_state", "accepted"),
        ("parse_state", "rejected"),
        ("reason_code", "parse_other"),
        ("declaration_handling", "none"),
    ],
)
def test_failed_download_never_claims_a_digest_or_parser_outcome(field, value):
    attempt = new_article_attempt("PMC123")
    attempt[field] = value
    reject(lambda: validate_article_diagnostics(envelope(attempt)))


@pytest.mark.parametrize("field", tuple(accepted()))
def test_every_record_field_rejects_source_text_and_missing_fields(field):
    attempt = accepted()
    attempt[field] = CANARY
    reject(lambda: validate_article_diagnostics(envelope(attempt)))
    del attempt[field]
    reject(lambda: validate_article_diagnostics(envelope(attempt)))


@pytest.mark.parametrize(
    "field", ["text", "url", "source", "property", "exception", "args", "offset"]
)
def test_extra_record_fields_cannot_create_evidence_or_carry_errors(field):
    attempt = accepted()
    attempt[field] = CANARY
    reject(lambda: validate_article_diagnostics(envelope(attempt)))


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        [],
        {},
        {"version": VERSION},
        {"attempts": []},
        {
            "version": VERSION,
            "attempts": (),
        },
        {"version": 1, "attempts": []},
        {"version": "article-parse-v2", "attempts": []},
        {"version": VERSION, "attempts": [], "text": CANARY},
    ],
)
def test_envelope_keys_types_and_version_are_closed(value):
    reject(lambda: validate_article_diagnostics(value))


@pytest.mark.parametrize("value", [None, True, 1, "record", [], ()])
def test_attempt_must_be_an_exact_dictionary(value):
    reject(lambda: validate_article_diagnostics(envelope(value)))


@pytest.mark.parametrize("field", [True, 1, None, ("source",)])
def test_nonstring_keys_are_rejected_before_any_record_is_copied(field):
    attempt = accepted()
    attempt[field] = CANARY
    reject(lambda: validate_article_diagnostics(envelope(attempt)))
    value = envelope()
    value[field] = CANARY
    reject(lambda: validate_article_diagnostics(value))


def test_cap_and_unique_ids_apply_to_all_attempts_including_failed_downloads():
    attempts = [new_article_attempt(f"PMC{i}") for i in range(MAX_ATTEMPTS)]
    assert validate_article_diagnostics(envelope(*attempts)) == envelope(*attempts)
    reject(
        lambda: validate_article_diagnostics(
            envelope(*attempts, new_article_attempt("PMC99"))
        )
    )
    reject(lambda: validate_article_diagnostics(envelope(attempts[0], attempts[0])))
    reject(
        lambda: validate_article_diagnostics(
            envelope(accepted(), new_article_attempt("PMC123"))
        )
    )
    assert validate_article_diagnostics(envelope()) == envelope()


def test_validation_returns_independent_closed_records():
    original = envelope(accepted(), new_article_attempt("PMC456"))
    copied = validate_article_diagnostics(original)
    assert copied == original and copied is not original
    assert copied["attempts"] is not original["attempts"]
    assert all(
        a is not b
        for a, b in zip(copied["attempts"], original["attempts"], strict=True)
    )
    original["attempts"][0]["reason_code"] = CANARY
    original["attempts"].append({"text": CANARY})
    assert CANARY not in json.dumps(copied)
    assert validate_article_diagnostics(copied) == copied


@pytest.mark.parametrize("terminal", ["accepted", "rejected"])
@pytest.mark.parametrize("operation", ["download", "accept", "reject"])
def test_terminal_parser_outcomes_cannot_be_rewritten(terminal, operation):
    attempt = pending()
    if terminal == "accepted":
        mark_parse_accepted(attempt, "inert_removed")
    else:
        mark_parse_rejected(attempt, "article_identity", "none")
    before = deepcopy(attempt)
    operations = {
        "download": lambda: mark_download_complete(attempt, b"replacement"),
        "accept": lambda: mark_parse_accepted(attempt, "none"),
        "reject": lambda: mark_parse_rejected(attempt, "parse_other", "not_examined"),
    }
    reject(operations[operation])
    assert attempt == before


def test_parser_outcome_requires_a_completed_download():
    attempt = new_article_attempt("PMC123")
    before = deepcopy(attempt)
    reject(lambda: mark_parse_accepted(attempt, "none"))
    reject(lambda: mark_parse_rejected(attempt, "parse_other", "not_examined"))
    assert attempt == before


class Hostile:
    def __str__(self):
        raise AssertionError("Untrusted object was stringified")

    def __repr__(self):
        raise AssertionError("Untrusted object was represented")

    def __hash__(self):
        raise AssertionError("Untrusted object was hashed")

    def __eq__(self, other):
        raise AssertionError("Untrusted object was compared")


def test_helpers_do_not_inspect_exception_attributes_or_untrusted_objects():
    class HostileError(ValueError):
        @property
        def reason_code(self):
            raise AssertionError("Exception reason was inspected")

        @property
        def declaration_handling(self):
            raise AssertionError("Exception handling was inspected")

    for value in (Hostile(), HostileError(CANARY), CANARY, [], True):
        attempt = pending()
        before = deepcopy(attempt)
        reject(partial(mark_parse_rejected, attempt, value, "none"))
        reject(partial(mark_parse_rejected, attempt, "parse_other", value))
        reject(partial(mark_parse_accepted, attempt, value))
        reject(partial(mark_download_complete, new_article_attempt("PMC123"), value))
        reject(partial(new_article_attempt, value))
        assert attempt == before


def test_exact_container_and_string_types_prevent_subclass_hooks():
    class DictSubclass(dict):
        def __iter__(self):
            raise AssertionError("Subclass dictionary was iterated")

    class ListSubclass(list):
        def __len__(self):
            raise AssertionError("Subclass list length was inspected")

    class StringSubclass(str):
        def __eq__(self, other):
            raise AssertionError("Subclass string was compared")

        __hash__ = str.__hash__

    reject(lambda: validate_article_diagnostics(DictSubclass(envelope())))
    reject(
        lambda: validate_article_diagnostics(
            {"version": VERSION, "attempts": ListSubclass()}
        )
    )
    reject(lambda: validate_article_diagnostics(envelope(DictSubclass(accepted()))))
    reject(lambda: new_article_attempt(StringSubclass("PMC123")))
    for field, value in accepted().items():
        if isinstance(value, str):
            attempt = accepted()
            attempt[field] = StringSubclass(value)
            reject(partial(validate_article_diagnostics, envelope(attempt)))
    reject(
        lambda: validate_article_diagnostics(
            {StringSubclass("version"): VERSION, "attempts": []}
        )
    )
    attempt = accepted()
    attempt[StringSubclass("injected")] = CANARY
    reject(lambda: validate_article_diagnostics(envelope(attempt)))
