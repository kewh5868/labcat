"""Screen source text as data, never as agent instructions or evidence
authority.

This is a conservative additional filter, not a complete injection
detector. The enforcement boundary is the fixed tool/source allowlist,
typed source-only evidence and deterministic reports. No returned text
can add tools or grant access.
"""

import html
import re
import unicodedata

_PATTERNS = (
    (
        "role_spoofing",
        r"(?:<\|(?:im_start|start_header_id|system|assistant)|"
        r"</?(?:system|developer|assistant)(?:\s[^>]{0,100})?>|"
        r"\[\s*(?:system|developer|assistant)\s*\]|"
        r"(?:^|\s)(?:system|developer)\s*(?:message|prompt|instruction|:))",
    ),
    (
        "policy_override",
        r"\b(?:ignore|disregard|forget|override|bypass|disable)\b.{0,90}"
        r"\b(?:previous|prior|above|instructions?|rules?|policy|policies|guardrails?|"
        r"safeguards?|constraints?|safety|paywalls?|authentication)\b",
    ),
    (
        "credential_request",
        r"\b(?:reveal|send|upload|print|exfiltrate|forward|read|show|copy)\b"
        r".{0,90}\b(?:passwords?|secrets?|credentials?|api[ _-]?keys?|"
        r"(?:access|refresh)[ _-]?tokens?|"
        r"environment[ _-]?variables?|private[ _-]?files?)\b",
    ),
    (
        "tool_instruction",
        r"\b(?:run|execute|invoke|call|launch)\b.{0,60}"
        r"\b(?:shell|commands?|sudo|bash|powershell|terminal|tools?|"
        r"generate_ranked_report|search_public_references|propose_candidate_leads)\b",
    ),
    (
        "evidence_override",
        r"\b(?:treat|accept|use|mark|promote)\b.{0,60}"
        r"\b(?:this|these|following|above|my)\b.{0,60}"
        r"\b(?:verified evidence|verified fact|authoritative instruction|"
        r"system instruction|trusted evidence)\b|"
        r"\b(?:fabricate|invent|falsify)\b.{0,60}"
        r"\b(?:citations?|evidence|measurements?|results?|scores?)\b",
    ),
)
_RULES = tuple((code, re.compile(pattern, re.I)) for code, pattern in _PATTERNS)


def source_instruction_reason(value: str) -> str | None:
    """Return a fixed rejection reason; never echo suspicious source
    content.

    Normalize only for screening. Accepted excerpts keep their original
    literal text. Entity escapes, compatibility characters and invisible
    formatting must not make an instruction invisible to the screen or
    misleading to readers.
    """
    if not isinstance(value, str):
        return "invalid_text"
    decoded = value
    for _ in range(2):
        decoded = html.unescape(decoded)
    normalized = unicodedata.normalize("NFKC", decoded)
    if any(
        unicodedata.category(character) == "Cf"
        or (unicodedata.category(character) == "Cc" and character not in "\n\r\t")
        for character in normalized
    ):
        return "hidden_control_text"
    normalized = " ".join(normalized.split())
    for code, pattern in _RULES:
        if pattern.search(normalized):
            return code
    return None
