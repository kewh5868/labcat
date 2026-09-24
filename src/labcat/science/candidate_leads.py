"""Literal public-source mentions, separate from material evidence and
ranking.

Model output selects an existing document, name and quote. It cannot
introduce a source, a property value or a suitability judgment. Call
with references already accepted by public discovery; this module
performs no retrieval.
"""

import hashlib
import json
import math
import re
import unicodedata
from collections import deque
from urllib.parse import urlsplit

from labcat.extended_discovery import valid_wikipedia_url
from labcat.untrusted_text import source_instruction_reason

from .discovery_hints import MAX_REFERENCES, _reference_fields
from .preferences import validate_formula

MAX_DOCUMENTS = 24
MAX_DOCUMENT_TEXT = 2400
MAX_PROPOSALS = 48
MAX_FORMULA_PROPOSALS = 36  # Leaves room for twelve model selectors.
MAX_LEADS = 12
MAX_NAME = 120
MAX_QUOTE = 480
_ABSTRACT_PROVIDERS = {"europe_pmc", "arxiv", "openalex", "chemrxiv"}
_DOCUMENT_FIELDS = {"document_id", "source_id", "record_id", "title", "text", "url"}
_STABILITY_CRITERIA = ("stability", "ambient_phase_stability", "operational_stability")
_GENERIC_WORDS = frozenset(
    "a an the and or of for in with material materials compound compounds "
    "candidate candidates system systems donor donors acceptor acceptors "
    "layer layers organic inorganic hybrid hybrids molecular molecule molecules "
    "small polymer polymers semiconductor semiconductors perovskite perovskites "
    "perovskitoid perovskitoids oxide oxides metal metals alloy alloys ceramic "
    "ceramics quantum dot dots qd qds nanoparticle nanoparticles nanocrystal "
    "nanocrystals photovoltaic photovoltaics device devices crystal crystals "
    "thin film films blend blends composite composites unspecified unknown "
    "study studies paper papers results sample samples control reference "
    "property properties phase phases structure structures".split()
)
_PROPERTY_NAME = re.compile(
    r"\b(?:band[ -]?gap|stability|stable|unstable|efficiency|density|modulus|"
    r"permittivity|dielectric constant|non[ -]?toxic|toxic|safe|optimal|best|"
    r"promising|solution[ -]processable|measured|calculated|reported)\b|"
    r"\d(?:\.\d+)?\s*(?:ev|mev|kev|gpa|mpa|nm|kelvin|celsius|%)\b",
    re.I,
)
_URL = re.compile(r"(?:https?://|www\.|\bdoi:|[a-z][a-z0-9+.-]*://)", re.I)
_CAUTIONS = (
    "This is a literal cited mention, not verified material identity, phase, "
    "property evidence or suitability for the requested application.",
    "The source may discuss a comparison, limitation or rejected material; "
    "mention alone does not establish a recommendation.",
    "Thermodynamic, room-temperature phase and operational stability remain "
    "unverified; unknown is not stable.",
)


def _normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _safe_text(value, maximum):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or source_instruction_reason(value)
        or any(
            unicodedata.category(c).startswith("C") and c not in "\n\r\t" for c in value
        )
    ):
        return None
    value = _normalized(value)
    return value if value and len(value) <= maximum else None


def _id(prefix, value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    return prefix + hashlib.sha256(raw).hexdigest()[:24]


def _bound_identity(reference):
    """Bind provider record IDs to their fixed public paths where
    possible."""
    source, identity, url = (
        reference["source_id"],
        reference["record_id"],
        reference["url"],
    )
    if _safe_text(identity, 160) != identity or any(c.isspace() for c in identity):
        return False
    path = urlsplit(url).path
    if source == "wikipedia":
        return bool(
            re.fullmatch(r"[1-9][0-9]{0,11}", identity)
        ) and valid_wikipedia_url(url)
    if source == "public_dielectric":
        return True  # Release DOI is shared by independently identified rows.
    return path.rstrip("/").endswith("/" + identity)


def _document(reference):
    if _reference_fields(reference) is None or not _bound_identity(reference):
        return None
    title = _safe_text(reference["title"], 1200)
    if title is None:
        return None
    metadata, provider = reference["metadata"], reference["source_id"]
    parts = [title]
    fields = ("excerpt", 2000) if provider == "wikipedia" else ("abstract", 12_000)
    field, maximum = fields
    if provider == "wikipedia" or provider in _ABSTRACT_PROVIDERS:
        if metadata.get(field + "_read") is True:
            text = _safe_text(metadata.get(field), maximum)
            # An explicitly read but malformed/instruction-bearing field rejects
            # the document, including an attack outside the retained prefix.
            if text is None:
                return None
            parts.append(text)
    text = " ".join(parts)[:MAX_DOCUMENT_TEXT]
    # Do not retain a truncated word that could look like another identity.
    if len(" ".join(parts)) > MAX_DOCUMENT_TEXT:
        text = text.rsplit(" ", 1)[0]
    return {
        "document_id": _id("doc-", [provider, reference["record_id"]]),
        "source_id": provider,
        "record_id": reference["record_id"],
        "title": title,
        "text": text,
        "url": reference["url"],
    }, len(parts) > 1


def discovery_documents(references, *, preferred_document_ids=None):
    """Preserve valid selected documents, then round-robin rich public
    excerpts.

    Preference only affects bounded selection; it cannot recover an
    invalid or ambiguous source record or add documents outside the
    retained references.
    """
    if not isinstance(references, (list, tuple)):
        return []
    if preferred_document_ids is None:
        preferred_document_ids = []
    if (
        not isinstance(preferred_document_ids, (list, tuple))
        or len(preferred_document_ids) > MAX_DOCUMENTS
        or any(
            not isinstance(identity, str)
            or re.fullmatch(r"doc-[a-f0-9]{24}", identity) is None
            for identity in preferred_document_ids
        )
    ):
        raise ValueError("Preferred discovery documents must be a bounded ID list.")
    retained, ambiguous = {}, set()
    discovery_pairs = []
    for reference in references[:MAX_REFERENCES]:
        parsed = _document(reference)
        if parsed is None:
            continue
        bodies = _passage_documents(
            reference,
            "discovery_passages",
            "discovery_full_text_provenance",
            include_context=False,
            discovery=True,
        )
        if bodies:
            # One informative body and its abstract from each article reach the
            # model before long provider queues hit the compact transport cap.
            discovery_pairs.append(
                (bodies[0][0]["document_id"], parsed[0]["document_id"])
            )
        for document, rich in (parsed, *_body_documents(reference)):
            identity = document["document_id"]
            fingerprint = (document, reference["provenance"]["response_sha256"])
            if identity in retained and retained[identity][2] != fingerprint:
                ambiguous.add(identity)
            retained.setdefault(identity, (document, rich, fingerprint))
    preferred = list(dict.fromkeys(preferred_document_ids))
    output = [
        retained[identity][0]
        for identity in preferred
        if identity in retained and identity not in ambiguous
    ]
    selected = {document["document_id"] for document in output}
    for pair in discovery_pairs:
        for identity in pair:
            if (
                identity in retained
                and identity not in ambiguous
                and identity not in selected
                and len(output) < MAX_DOCUMENTS
            ):
                output.append(retained[identity][0])
                selected.add(identity)
    for rich in (True, False):
        groups = {}
        for identity, (document, has_excerpt, _) in retained.items():
            if (
                identity not in ambiguous
                and identity not in selected
                and has_excerpt == rich
            ):
                groups.setdefault(document["source_id"], deque()).append(document)
        while any(groups.values()) and len(output) < MAX_DOCUMENTS:
            for group in groups.values():
                if group and len(output) < MAX_DOCUMENTS:
                    output.append(group.popleft())
    return output


def _body_documents(reference, *, include_context=False):
    """Reconstruct bounded body excerpts without changing historical
    abstracts.

    Approved full-text paths attach source/hash-bound discovery or
    assessment paragraphs. New discovery text includes its literal
    section heading so a recipe or simulation retains its source
    context. These remain untrusted quoted text, not measured properties
    or matching phase/conditions.
    """
    return _passage_documents(
        reference,
        "discovery_passages",
        "discovery_full_text_provenance",
        include_context=include_context,
        discovery=True,
    ) + _passage_documents(
        reference,
        "assessment_passages",
        "full_text_provenance",
        include_context=include_context,
        discovery=False,
    )


def _passage_documents(
    reference, passage_key, provenance_key, *, include_context, discovery
):
    if _document(reference) is None:
        return []
    metadata = reference["metadata"]
    provenance = metadata.get(provenance_key, {})
    passages = metadata.get(passage_key, [])
    identity = reference["record_id"]
    if (
        reference["source_id"] != "europe_pmc"
        or re.fullmatch(r"PMC[0-9]{1,12}", identity) is None
        or metadata.get("full_text_read") is not True
        or metadata.get("full_text_scope") != "body paragraphs only"
        or not isinstance(provenance, dict)
        or provenance.get("full_text_request_url")
        != f"https://www.ebi.ac.uk/europepmc/webservices/rest/{identity}/fullTextXML"
        or not isinstance(passages, list)
        or len(passages) > (3 if discovery else 9)
    ):
        return []
    digest = provenance.get("full_text_response_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
        return []
    output = []
    for passage in passages:
        fields = {
            "text",
            "locator",
            "section",
            "article_id",
            "response_sha256",
            "paragraph_complete",
        }
        if not isinstance(passage, dict):
            continue
        if not discovery:
            fields.add("candidate_ids")
        elif "include_section_in_document" in passage:
            fields.add("include_section_in_document")
            if passage["include_section_in_document"] is not True:
                continue
        if set(passage) != fields:
            continue
        # The approved follow-up adapter preserves complete paragraphs within
        # the report boundary's 4,000-character cap. Longer cropped snippets
        # remain review-only, regardless of whether they mention a candidate.
        text = _safe_text(passage["text"], 2400 if discovery else 4000)
        section = _safe_text(passage["section"], 300)
        locator = passage["locator"]
        candidates = passage.get("candidate_ids", [])
        if (
            text is None
            or section is None
            or not isinstance(locator, str)
            or len(locator) > 500
            or re.fullmatch(r"body(?:/sec\[[1-9][0-9]*\])*/p\[[1-9][0-9]*\]", locator)
            is None
            or passage["article_id"] != identity
            or passage["response_sha256"] != digest
            or passage["paragraph_complete"] is not True
            or not isinstance(candidates, list)
            or not (0 if discovery else 1) <= len(candidates) <= 20
            or any(
                not isinstance(candidate, str)
                or re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", candidate) is None
                for candidate in candidates
            )
        ):
            continue
        if discovery and passage.get("include_section_in_document") is True:
            text = section + " " + text
            if len(text) > MAX_DOCUMENT_TEXT:
                continue
        output.append(
            (
                {
                    "document_id": _id(
                        "doc-",
                        [
                            "europe_pmc",
                            identity,
                            "body",
                            digest,
                            locator,
                            section,
                            text,
                        ],
                    ),
                    "source_id": "europe_pmc",
                    "record_id": identity,
                    "title": reference["title"],
                    "text": text,
                    "url": reference["url"],
                    **(
                        {"section": section, "locator": locator}
                        if include_context
                        else {}
                    ),
                },
                True,
            )
        )
    return output


def _name(value):
    value = _safe_text(value, MAX_NAME)
    if (
        value is None
        or len(value) < 2
        or _URL.search(value)
        or any(c in value for c in "<>{}=;\\\n`$")
        or _PROPERTY_NAME.search(value)
    ):
        return None
    words = set(re.findall(r"[^\W_]+", value.casefold()))
    if not any(c.isalpha() for c in value) or words <= _GENERIC_WORDS:
        return None
    return value


def _parenthesized_mention(text, start, end):
    """Recognize one complete enclosing pair, preserving any internal
    groups."""
    if text[max(0, start - 1) : start] != "(" or text[end : end + 1] != ")":
        return False
    depth = 0
    for character in text[start:end]:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _whole_mention(text, start, end):
    # Prose commonly introduces a name or acronym in parentheses. Only treat
    # an exact enclosing pair as prose delimiters: applying the same boundary
    # checks outside it still rejects poly(NAME), (NAME)2 and (NAME)(GROUP).
    if _parenthesized_mention(text, start, end):
        start -= 1
        end += 1
    for index in (start - 1, end):
        if 0 <= index < len(text):
            character = text[index]
            if (
                character.isalnum()
                or character in "_/+−()[]{}^=#≡·⋅∙"
                or unicodedata.category(character) == "Pd"
            ):
                return False
    return not (text[end : end + 1] == "." and text[end + 1 : end + 2].isdigit())


def _cited_mention(text, quote, name):
    for passage in re.finditer(re.escape(quote), text):
        for mention in re.finditer(re.escape(name), quote):
            if _whole_mention(
                text, passage.start() + mention.start(), passage.start() + mention.end()
            ):
                return True
    return False


def _missing(importance):
    if importance is None:
        importance = {}
    if not isinstance(importance, dict) or len(importance) > 100:
        raise ValueError(
            "Candidate-lead criteria must be a bounded preference mapping."
        )
    for key, value in importance.items():
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
            or type(value) not in (int, float)
            or not 0 <= value <= 1
            or not math.isfinite(value)
        ):
            raise ValueError("Invalid candidate-lead criterion preference.")
    return list(
        dict.fromkeys(
            [key for key, value in importance.items() if value > 0]
            + list(_STABILITY_CRITERIA)
        )
    )


def validate_candidate_leads(proposals, documents, references, importance=None):
    """Selectors prove literal mention only; rebind every document to
    its source."""
    missing = _missing(importance)
    if (
        not isinstance(proposals, (list, tuple))
        or len(proposals) > MAX_PROPOSALS
        or not isinstance(documents, (list, tuple))
        or len(documents) > MAX_DOCUMENTS
    ):
        return []
    preferred = [
        doc["document_id"]
        for doc in documents
        if isinstance(doc, dict)
        and isinstance(doc.get("document_id"), str)
        and re.fullmatch(r"doc-[a-f0-9]{24}", doc["document_id"])
    ]
    originals = {
        doc["document_id"]: doc
        for doc in discovery_documents(references, preferred_document_ids=preferred)
    }
    accepted = {
        doc["document_id"]: doc
        for doc in documents
        if isinstance(doc, dict)
        and set(doc) == _DOCUMENT_FIELDS
        and isinstance(doc.get("document_id"), str)
        and originals.get(doc["document_id"]) == doc
    }
    leads = {}
    for proposal in proposals:
        if not isinstance(proposal, dict) or set(proposal) != {
            "document_id",
            "name",
            "quote",
        }:
            continue
        identity = proposal["document_id"]
        if not isinstance(identity, str) or identity not in accepted:
            continue
        name, quote = _name(proposal["name"]), _safe_text(proposal["quote"], MAX_QUOTE)
        document = accepted[identity]
        if (
            name is None
            or quote is None
            or len(quote) < 12
            or _URL.search(quote)
            or not _cited_mention(document["text"], quote, name)
        ):
            continue
        key = name.casefold()
        if key not in leads and len(leads) >= MAX_LEADS:
            continue
        citation = {
            key: document[key]
            for key in ("document_id", "source_id", "record_id", "url", "title")
        }
        citation["quote"] = quote
        lead = leads.setdefault(
            key,
            {
                "id": _id("lead-", key),
                "name": name,
                "quote": quote,
                **{
                    key: document[key]
                    for key in ("source_id", "record_id", "url", "title")
                },
                "status": "candidate_lead",
                "properties_verified": False,
                "suitability_verified": False,
                "missing_criteria": list(missing),
                "cautions": list(_CAUTIONS),
                "citations": [],
            },
        )
        if citation not in lead["citations"] and len(lead["citations"]) < 4:
            lead["citations"].append(citation)
    return list(leads.values())


def literal_formula_proposals(documents):
    """Find whole literal formulas only; callers must validate these
    selectors."""
    if not isinstance(documents, (list, tuple)) or len(documents) > MAX_DOCUMENTS:
        return []
    proposals = []
    for document in documents:
        if not isinstance(document, dict) or set(document) != _DOCUMENT_FIELDS:
            continue
        text = _safe_text(document.get("text"), MAX_DOCUMENT_TEXT)
        if text is None or not isinstance(document.get("document_id"), str):
            continue
        for token in re.finditer(r"\S+", text):
            name = token[0].strip(",;:!?[]{}\"'").rstrip(".")
            # Bare letter groups frequently denote instruments or device
            # acronyms rather than compositions. Automatic hints deliberately
            # under-recall binary formulas; a contextual model selector can
            # still cite their complete literal names through the same boundary.
            if not any(character.isdigit() for character in name):
                continue
            try:
                elements = validate_formula(name)
            except (ValueError, OverflowError):
                continue
            if len(elements) < 2 or _name(name) is None:
                continue
            start = max(0, token.start() - 160)
            if start:
                start = text.find(" ", start, token.start()) + 1
            end = min(len(text), start + MAX_QUOTE)
            if end < len(text):
                end = text.rfind(" ", token.end(), end)
            quote = text[start:end]
            if len(quote) >= 12 and _cited_mention(text, quote, name):
                proposals.append(
                    {
                        "document_id": document["document_id"],
                        "name": name,
                        "quote": quote,
                    }
                )
            if len(proposals) >= MAX_FORMULA_PROPOSALS:
                return proposals
    return proposals
