"""Bounded inert JATS prolog handling without DTD or external entity
resolution.

Declarations identify syntax only; they cannot establish article
identity, publication status, default attributes, schema validation or
scientific evidence.
"""

import re

ARTICLE_PARSE_REASONS = frozenset(
    {
        "encoding_or_size",
        "doctype_policy",
        "entity_declaration",
        "malformed_xml",
        "article_root",
        "publication_type",
        "tree_budget",
        "article_identity",
        "parse_other",
    }
)
DECLARATION_STATES = frozenset({"not_examined", "none", "inert_removed", "rejected"})

MAX_DECLARATION = 2048
MAX_LITERAL = 1024
SPACE = " \t\r\n"
NAME = re.compile(r"[A-Za-z_:][A-Za-z0-9_.:-]*")
XML_DECLARATION = re.compile(
    r"<\?xml[ \t\r\n]+version[ \t\r\n]*=[ \t\r\n]*(?:\"1\.[01]\"|'1\.[01]')"
    r"(?:[ \t\r\n]+encoding[ \t\r\n]*=[ \t\r\n]*"
    r"(?:\"[A-Za-z][A-Za-z0-9._-]*\"|'[A-Za-z][A-Za-z0-9._-]*'))?"
    r"(?:[ \t\r\n]+standalone[ \t\r\n]*=[ \t\r\n]*(?:\"(?:yes|no)\"|'(?:yes|no)'))?"
    r"[ \t\r\n]*\?>"
)
PUBLIC_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "
    "\r\n-'()+,./:=?;!*#@$_"
)


class ArticleParseError(ValueError):
    """A fixed parser failure and last known declaration state, never
    XML text."""

    def __init__(self, reason_code, *, declaration_handling="rejected"):
        if (
            not isinstance(reason_code, str)
            or reason_code not in ARTICLE_PARSE_REASONS
            or not isinstance(declaration_handling, str)
            or declaration_handling not in DECLARATION_STATES
        ):
            raise ValueError("Invalid article parser failure state.")
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.declaration_handling = declaration_handling


def _system_literal(value):
    if not 1 <= len(value) <= MAX_LITERAL or not value.isascii():
        return False
    if "://" in value:
        scheme, _, rest = value.partition("://")
        host, separator, value = rest.partition("/")
        if scheme not in {"http", "https"} or not separator:
            return False
        labels = host.split(".")
        if (
            not 1 <= len(host) <= 253
            or len(labels) < 2
            or all(label.isdigit() for label in labels)
            or any(
                not re.fullmatch(
                    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label
                )
                for label in labels
            )
        ):
            return False
    parts = value.split("/")
    return bool(
        parts
        and parts[-1].endswith(".dtd")
        and all(
            part not in {".", ".."} and re.fullmatch(r"[A-Za-z0-9_.-]+", part)
            for part in parts
        )
    )


def _declaration_end(text, start):
    quote = None
    for index in range(start, min(len(text), start + MAX_DECLARATION)):
        char = text[index]
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == ">":
            return index + 1
    raise ArticleParseError("doctype_policy")


def _validate_declaration(declaration):
    # Tokenization is bounded by the declaration cap; no XML/DTD parser is used.
    if not declaration.startswith("<!DOCTYPE") or not declaration.endswith(">"):
        raise ArticleParseError("doctype_policy")
    cursor = len("<!DOCTYPE")

    def whitespace(required=False):
        nonlocal cursor
        start = cursor
        while cursor < len(declaration) and declaration[cursor] in SPACE:
            cursor += 1
        if required and cursor == start:
            raise ArticleParseError("doctype_policy")

    def literal():
        nonlocal cursor
        if cursor >= len(declaration) or declaration[cursor] not in "\"'":
            raise ArticleParseError("doctype_policy")
        quote = declaration[cursor]
        cursor += 1
        end = declaration.find(quote, cursor)
        if end < 0 or not 1 <= end - cursor <= MAX_LITERAL:
            raise ArticleParseError("doctype_policy")
        value = declaration[cursor:end]
        cursor = end + 1
        return value

    whitespace(required=True)
    if not declaration.startswith("article", cursor):
        raise ArticleParseError("doctype_policy")
    cursor += len("article")
    if declaration[cursor:] == ">":
        return
    whitespace(required=True)
    if declaration[cursor:] == ">":
        return
    if declaration.startswith("SYSTEM", cursor):
        cursor += len("SYSTEM")
        whitespace(required=True)
        system = literal()
    elif declaration.startswith("PUBLIC", cursor):
        cursor += len("PUBLIC")
        whitespace(required=True)
        public = literal()
        if any(char not in PUBLIC_CHARACTERS for char in public):
            raise ArticleParseError("doctype_policy")
        whitespace(required=True)
        system = literal()
    else:
        raise ArticleParseError("doctype_policy")
    if not _system_literal(system):
        raise ArticleParseError("doctype_policy")
    whitespace()
    if declaration[cursor:] != ">":
        raise ArticleParseError("doctype_policy")


def remove_inert_article_doctype(text):
    """Return unchanged text or one same-length, newline-preserving
    replacement."""
    upper = text.upper()
    if "<!ENTITY" in upper:
        raise ArticleParseError("entity_declaration")
    count = upper.count("<!DOCTYPE")
    if not count:
        return text, "none"
    if count != 1:
        raise ArticleParseError("doctype_policy")
    marker = upper.index("<!DOCTYPE")
    cursor = 0
    if re.match(r"<\?xml[ \t\r\n]", text):
        end = text.find("?>", cursor)
        if end < 0 or not XML_DECLARATION.fullmatch(text[: end + 2]):
            raise ArticleParseError("doctype_policy")
        cursor = end + 2
    while True:
        while cursor < len(text) and text[cursor] in SPACE:
            cursor += 1
        if cursor == marker:
            break
        if cursor > marker:
            raise ArticleParseError("doctype_policy")
        if text.startswith("<!--", cursor):
            end = text.find("-->", cursor + 4)
            if end < 0 or "--" in text[cursor + 4 : end] or end >= marker:
                raise ArticleParseError("doctype_policy")
            cursor = end + 3
        elif text.startswith("<?", cursor):
            end = text.find("?>", cursor + 2)
            target = NAME.match(text, cursor + 2)
            if (
                end < 0
                or end >= marker
                or target is None
                or target.group().casefold() == "xml"
                or target.end() != end
                and text[target.end()] not in SPACE
            ):
                raise ArticleParseError("doctype_policy")
            cursor = end + 2
        else:
            raise ArticleParseError("doctype_policy")
    end = _declaration_end(text, marker)
    _validate_declaration(text[marker:end])
    replacement = "".join(c if c in "\r\n" else " " for c in text[marker:end])
    cleaned = text[:marker] + replacement + text[end:]
    if "<!DOCTYPE" in cleaned.upper() or "<!ENTITY" in cleaned.upper():
        raise ArticleParseError("doctype_policy")
    return cleaned, "inert_removed"


def prepare_article_xml(raw: bytes, *, max_bytes: int) -> tuple[str, str]:
    """Validate original bytes, then remove at most one permitted
    declaration."""
    if (
        not isinstance(raw, (bytes, bytearray))
        or len(raw) > max_bytes
        or b"\x00" in raw
    ):
        raise ArticleParseError("encoding_or_size", declaration_handling="not_examined")
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise ArticleParseError(
            "encoding_or_size", declaration_handling="not_examined"
        ) from None
    encoding = re.search(r"<\?xml[^>]*encoding\s*=\s*['\"]([^'\"]+)", text, re.I)
    if encoding and encoding[1].lower() not in {"utf-8", "us-ascii"}:
        raise ArticleParseError("encoding_or_size", declaration_handling="not_examined")
    return remove_inert_article_doctype(text)
