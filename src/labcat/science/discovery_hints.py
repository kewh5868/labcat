"""Cited public-reference formula leads, never property or material
evidence.

Call only with records already accepted by the public-discovery
boundary. Formulas are literal navigation hints; a quantitative adapter
must independently retrieve and validate every candidate. This module
has no prompt/model input.
"""

import re
from urllib.parse import urlsplit

from labcat.untrusted_text import source_instruction_reason

from .preferences import composition_key, validate_formula

MAX_FORMULA_LEADS = 6
MAX_REFERENCES = 80
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_REFERENCE_PATHS = {
    "public_dielectric": ("doi.org", r"/10\.6084/m9\.figshare\.7108790\.v2"),
    "hybrid3": ("materials.hybrid3.duke.edu", r"/materials/systems/[0-9]+/"),
    "nomad": ("nomad-lab.eu", r"/prod/v1/gui/search/entries/entry/id/[A-Za-z0-9_-]+"),
    "europe_pmc": ("europepmc.org", r"/articles/PMC[0-9]+"),
    "arxiv": (
        "arxiv.org",
        r"/abs/(?:[0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?|[a-z.-]+/[0-9]{7}(?:v[0-9]+)?)",
    ),
    "wikipedia": ("en.wikipedia.org", r"/wiki/[^/:]+"),
    "openalex": ("openalex.org", r"/W[0-9]{1,15}"),
    "chemrxiv": ("openalex.org", r"/W[0-9]{1,15}"),
}


def _reference_fields(reference):
    if not isinstance(reference, dict):
        return None
    provider = reference.get("source_id")
    if (
        not isinstance(provider, str)
        or provider not in _REFERENCE_PATHS
        or reference.get("kind") != "discovery_reference"
        or reference.get("access_scope") != "public"
        or reference.get("is_material_evidence") is not False
        or reference.get("provenance_status") != "verified"
        or not isinstance(reference.get("record_id"), str)
        or not 1 <= len(reference["record_id"]) <= 160
    ):
        return None
    title, url, metadata = (
        reference.get("title"),
        reference.get("url"),
        reference.get("metadata"),
    )
    provenance = reference.get("provenance")
    if (
        not isinstance(title, str)
        or not 1 <= len(title) <= 1200
        or not isinstance(url, str)
        or not 1 <= len(url) <= 2048
        or not isinstance(metadata, dict)
        or not isinstance(provenance, dict)
        or not isinstance(provenance.get("response_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", provenance["response_sha256"])
    ):
        return None
    host, path = _REFERENCE_PATHS[provider]
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != host
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or re.fullmatch(path, parsed.path) is None
            or any(ord(character) < 32 for character in url)
        ):
            return None
    except ValueError:
        return None
    fields = {"title": title}
    formula = metadata.get("formula")
    if isinstance(formula, str) and 1 <= len(formula) <= 120:
        fields["metadata.formula"] = formula
    excerpt = metadata.get("excerpt")
    if (
        provider == "wikipedia"
        and metadata.get("excerpt_read") is True
        and isinstance(excerpt, str)
        and 1 <= len(excerpt) <= 2000
    ):
        fields["metadata.excerpt"] = excerpt
    if any(source_instruction_reason(value) for value in fields.values()):
        return None
    return fields


def _formulas(value, *, explicit):
    # Whole tokens only: never strip a doping suffix, charge, fraction or bond
    # from an unsupported expression to manufacture a different composition.
    tokens = [value.strip()] if explicit else value.split()[:400]
    for token in tokens:
        token = token.strip(",;:!?[]{}\"'").rstrip(".").translate(_SUBSCRIPTS)
        if not token or len(token) > 120:
            continue
        try:
            elements = validate_formula(token)
            identity = composition_key(token)
        except (ValueError, OverflowError):
            continue
        # Single-element prose tokens (In, As, At, ...) are often ordinary words.
        # They are accepted only in an explicit source formula field.
        if not explicit and len(elements) < 2:
            continue
        yield token, identity


def formula_leads(references):
    """Return at most six distinct literal formulas with their public
    citations."""
    if not isinstance(references, (list, tuple)):
        return []
    accepted = [
        (reference, fields)
        for reference in references[:MAX_REFERENCES]
        if (fields := _reference_fields(reference)) is not None
    ]
    leads = {}
    for field in ("metadata.formula", "title", "metadata.excerpt"):
        for reference, fields in accepted:
            if field not in fields:
                continue
            for formula, identity in _formulas(
                fields[field], explicit=field == "metadata.formula"
            ):
                if identity not in leads and len(leads) >= MAX_FORMULA_LEADS:
                    continue
                lead = leads.setdefault(
                    identity,
                    {
                        "formula": formula,
                        "is_material_evidence": False,
                        "citations": [],
                    },
                )
                citation = {
                    "source_id": reference["source_id"],
                    "record_id": reference["record_id"],
                    "url": reference["url"],
                    "title": reference["title"],
                    "field": field,
                }
                if citation not in lead["citations"] and len(lead["citations"]) < 4:
                    lead["citations"].append(citation)
    return list(leads.values())
