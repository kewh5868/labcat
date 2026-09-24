"""Closed, bounded article-attempt diagnostics; never scientific
evidence."""

import hashlib
import re

VERSION = "article-parse-v1"
MAX_ATTEMPTS = 6
MAX_RESPONSE_BYTES = 2_000_000
_FIELDS = frozenset(
    {
        "requested_article_id",
        "download_state",
        "response_sha256",
        "parse_state",
        "reason_code",
        "declaration_handling",
    }
)
_HANDLING = frozenset({"not_examined", "none", "inert_removed", "rejected"})
_PREPARED = frozenset({"none", "inert_removed"})
_REASON_HANDLING = {
    "encoding_or_size": frozenset({"not_examined"}),
    "doctype_policy": frozenset({"rejected"}),
    "entity_declaration": frozenset({"rejected"}),
    "malformed_xml": _PREPARED,
    "article_root": _PREPARED,
    "publication_type": _PREPARED,
    "tree_budget": _PREPARED,
    "article_identity": _PREPARED,
    "parse_other": _HANDLING,
}


def _invalid():
    raise ValueError("Invalid article parse diagnostics.")


def _article_id(value):
    if type(value) is not str or re.fullmatch(r"PMC[0-9]{1,12}", value) is None:
        _invalid()
    return value


def _validated_attempt(value, *, allow_intermediate=False):
    if (
        type(value) is not dict
        or any(type(key) is not str for key in value)
        or set(value) != _FIELDS
    ):
        _invalid()
    _article_id(value["requested_article_id"])
    for field in ("download_state", "parse_state", "declaration_handling"):
        if type(value[field]) is not str:
            _invalid()
    reason = value["reason_code"]
    digest = value["response_sha256"]
    if reason is not None and type(reason) is not str:
        _invalid()
    if digest is not None and (
        type(digest) is not str or re.fullmatch(r"[a-f0-9]{64}", digest) is None
    ):
        _invalid()
    download = value["download_state"]
    parsed = value["parse_state"]
    handling = value["declaration_handling"]
    if download == "failed":
        valid = (
            digest is None
            and parsed == "not_attempted"
            and reason is None
            and handling == "not_examined"
        )
    elif download == "complete" and digest is not None:
        if parsed == "accepted":
            valid = reason is None and handling in _PREPARED
        elif parsed == "rejected":
            valid = reason in _REASON_HANDLING and handling in _REASON_HANDLING[reason]
        else:
            valid = (
                allow_intermediate
                and parsed == "not_attempted"
                and reason is None
                and handling == "not_examined"
            )
    else:
        valid = False
    if not valid:
        _invalid()
    return dict(value)


def validate_article_diagnostics(value):
    """Copy only terminal fixed records; reject incomplete or untrusted
    fields."""
    if (
        type(value) is not dict
        or any(type(key) is not str for key in value)
        or set(value) != {"version", "attempts"}
        or type(value["version"]) is not str
        or value["version"] != VERSION
        or type(value["attempts"]) is not list
        or len(value["attempts"]) > MAX_ATTEMPTS
    ):
        _invalid()
    attempts = [_validated_attempt(attempt) for attempt in value["attempts"]]
    identifiers = {attempt["requested_article_id"] for attempt in attempts}
    if len(identifiers) != len(attempts):
        _invalid()
    return {"version": VERSION, "attempts": attempts}


def new_article_attempt(pmcid):
    """Create an attempted download; a failure retains this terminal
    state."""
    return {
        "requested_article_id": _article_id(pmcid),
        "download_state": "failed",
        "response_sha256": None,
        "parse_state": "not_attempted",
        "reason_code": None,
        "declaration_handling": "not_examined",
    }


def mark_download_complete(attempt, raw):
    """Hash only a complete capped byte response, before any parser
    transformation.

    This temporary state is deliberately rejected by the final envelope
    validator until mark_parse_accepted or mark_parse_rejected records
    its parser outcome.
    """
    clean = _validated_attempt(attempt)
    if (
        clean["download_state"] != "failed"
        or type(raw) is not bytes
        or len(raw) > MAX_RESPONSE_BYTES
    ):
        _invalid()
    clean.update(
        download_state="complete", response_sha256=hashlib.sha256(raw).hexdigest()
    )
    attempt.update(clean)


def _pending_parse(attempt):
    clean = _validated_attempt(attempt, allow_intermediate=True)
    if clean["download_state"] != "complete" or clean["parse_state"] != "not_attempted":
        _invalid()
    return clean


def mark_parse_accepted(attempt, handling):
    """Record success without permitting a later metadata failure to
    replace it."""
    clean = _pending_parse(attempt)
    clean.update(parse_state="accepted", declaration_handling=handling)
    attempt.update(_validated_attempt(clean))


def mark_parse_rejected(attempt, reason, handling):
    """Record a caller-selected fixed reason; never inspect exception
    strings."""
    clean = _pending_parse(attempt)
    clean.update(
        parse_state="rejected", reason_code=reason, declaration_handling=handling
    )
    attempt.update(_validated_attempt(clean))
