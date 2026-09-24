"""Bounded, keyless property literature searches and open-access passage
skimming.

Europe PMC supplies PMCID-only fullTextXML for its OA subset. Selected
OpenAlex can supply public abstracts through its existing fixed metadata
adapter. Search hints select documents; they never establish material
identity or values. Literal passages are unscored review leads, never
scientific evidence records.
"""

import hashlib
import http.client
import re
import socket
import ssl
import time
from xml.etree import ElementTree

from labcat import public_sources as public
from labcat.article_diagnostics import (
    mark_download_complete,
    mark_parse_accepted,
    mark_parse_rejected,
    new_article_attempt,
    validate_article_diagnostics,
)
from labcat.untrusted_text import source_instruction_reason

MAX_ATTRIBUTES = 3
MAX_ARTICLES = 6
MAX_PASSAGES_PER_ATTRIBUTE = 3
MAX_SECONDS = 15
MAX_BYTES = 2_000_000
MAX_REQUESTS = 100
MAX_EXCERPT = 1000
MAX_COMPLETE_PARAGRAPH = 4000
HOST = "www.ebi.ac.uk"
PATH = "/europepmc/webservices/rest/"

DIAGNOSTICS_VERSION = "property-filter-v1"
MAX_DIAGNOSTIC_COUNT = 180_000
_DIAGNOSTIC_COUNTS = frozenset(
    {
        "searches_attempted",
        "searches_failed",
        "search_records_validated",
        "lookup_budget_skips",
        "invalid_article_identifiers",
        "article_budget_skips",
        "downloads_attempted",
        "downloads_completed",
        "download_failures",
        "articles_parsed",
        "parse_failures",
        "article_metadata_failures",
        "successful_cache_reuses",
        "failed_cache_reuses",
        "paragraphs_available",
        "paragraphs_screened_out",
        "paragraphs_examined",
        "paragraphs_unexamined",
        "paragraphs_without_criterion",
        "criterion_matching_paragraphs",
        "criterion_without_candidate",
        "candidate_and_criterion_paragraphs",
        "candidate_filter_not_required",
        "complete_passages_selected",
        "cropped_passages_selected",
        "crop_context_rejections",
        "passage_selection_failures",
        "duplicate_passages_skipped",
        "passages_retained",
    }
)


def _new_diagnostics():
    return {
        "version": DIAGNOSTICS_VERSION,
        "count_limit": MAX_DIAGNOSTIC_COUNT,
        "counts_saturated": False,
        "counts": dict.fromkeys(sorted(_DIAGNOSTIC_COUNTS), 0),
    }


def _count(diagnostics, name, amount=1):
    if diagnostics is None:
        return
    total = diagnostics["counts"][name] + amount
    diagnostics["counts"][name] = min(total, MAX_DIAGNOSTIC_COUNT)
    if total > MAX_DIAGNOSTIC_COUNT:
        diagnostics["counts_saturated"] = True


def validate_property_diagnostics(value):
    """Copy only a closed set of bounded counters, never source or error
    text.

    Counts describe one attribute lookup. Available/screened paragraph
    counts include cached articles reused for this attribute; examined
    counts stop at the existing passage cap. They do not establish
    scientific evidence.
    """
    if (
        type(value) is not dict
        or any(type(key) is not str for key in value)
        or set(value) != {"version", "count_limit", "counts_saturated", "counts"}
        or type(value["version"]) is not str
        or value["version"] != DIAGNOSTICS_VERSION
        or type(value["count_limit"]) is not int
        or value["count_limit"] != MAX_DIAGNOSTIC_COUNT
        or type(value["counts_saturated"]) is not bool
        or type(value["counts"]) is not dict
        or any(type(key) is not str for key in value["counts"])
        or set(value["counts"]) != _DIAGNOSTIC_COUNTS
        or any(
            type(count) is not int or not 0 <= count <= MAX_DIAGNOSTIC_COUNT
            for count in value["counts"].values()
        )
    ):
        raise ValueError("Invalid property lookup diagnostics.")
    return {
        "version": DIAGNOSTICS_VERSION,
        "count_limit": MAX_DIAGNOSTIC_COUNT,
        "counts_saturated": value["counts_saturated"],
        "counts": dict(value["counts"]),
    }


# Search vocabulary, not material facts, numerical defaults or score functions.
ATTRIBUTE_TERMS = {
    "stability": ("thermodynamic stability", "energy above hull", "phase stability"),
    "ambient_phase_stability": (
        "room temperature",
        "ambient stability",
        "phase stability",
        "phase transition",
        "decomposition",
        "moisture stability",
    ),
    "operational_stability": (
        "operational stability",
        "degradation",
        "photostability",
        "thermal stability",
        "humidity",
        "lifetime",
        "stability test",
        "fatigue",
        "cyclic loading",
        "cycling stability",
        "durability",
        "wear resistance",
        "corrosion resistance",
        "creep",
        "photobleaching",
        "aging",
        "ageing",
        "signal drift",
    ),
    "formation_energy": ("formation energy", "formation enthalpy"),
    "element_screen": ("toxicity", "toxicology", "biocompatibility"),
    "simplicity": ("chemical composition", "stoichiometry"),
    "nsites": ("unit cell", "atomic sites"),
    "density": ("density",),
    "volume": ("cell volume", "unit cell volume"),
    "band_gap": ("band gap", "bandgap", "energy gap"),
    "direct_gap": ("direct band gap", "indirect band gap", "direct gap"),
    "metallicity": ("metallic", "metallicity", "electronic structure"),
    "conduction_band_edge": ("conduction band", "conduction-band"),
    "valence_band_edge": ("valence band", "valence-band"),
    "fermi_energy": ("Fermi energy", "Fermi level"),
    "refractive_index": ("refractive index",),
    "dielectric_total": ("dielectric constant", "permittivity"),
    "dielectric_electronic": ("electronic dielectric", "optical permittivity"),
    "dielectric_ionic": ("ionic dielectric", "ionic permittivity"),
    "piezoelectric_response": ("piezoelectric",),
    "bulk_modulus": ("bulk modulus",),
    "shear_modulus": ("shear modulus",),
    "elastic_anisotropy": ("elastic anisotropy",),
    "poisson_ratio": ("Poisson ratio", "Poisson's ratio"),
    "magnetization": ("magnetization", "magnetic moment"),
    "magnetic_ordering": ("magnetic ordering", "ferromagnetic", "antiferromagnetic"),
    "magnetic_site_count": ("magnetic sites", "magnetic atoms"),
    "surface_energy": ("surface energy",),
    "work_function": ("work function",),
    "solution_processability": (
        "solution processing",
        "solution processable",
        "solution deposition",
    ),
}
_CAVEAT = (
    "Literal public-text mention for review only. Material phase, sample, method, "
    "units and applicability have not been verified; no value enters the ranking."
)


def _fetch_full_text(pmcid: str, deadline: float) -> tuple[bytes, str]:
    """Fixed XML path, pinned global address, verified TLS, no
    redirects/proxies."""
    if not re.fullmatch(r"PMC[0-9]{1,12}", pmcid):
        raise public.PublicSourceError("Invalid public article identifier.")
    path = PATH + pmcid + "/fullTextXML"
    connection = http.client.HTTPSConnection(HOST, timeout=public._remaining(deadline))
    try:
        address = public._addresses(HOST, deadline)[0]
        raw_socket = socket.create_connection(
            (address, 443), timeout=public._remaining(deadline)
        )
        try:
            secured = ssl.create_default_context().wrap_socket(
                raw_socket, server_hostname=HOST
            )
            connection.sock = secured
        except Exception:
            raw_socket.close()
            raise
        secured.settimeout(public._remaining(deadline))
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "application/xml, text/xml",
                "Accept-Encoding": "identity",
                "User-Agent": "Labcat/0.1 public-property-review",
            },
        )
        secured.settimeout(public._remaining(deadline))
        response = connection.getresponse()
        if response.status != 200:
            raise public.PublicSourceError("Open-access article was unavailable.")
        if response.getheader("Content-Type", "").split(";", 1)[0].strip() not in {
            "application/xml",
            "text/xml",
        }:
            raise public.PublicSourceError("Open-access article was not XML.")
        if response.getheader("Content-Encoding", "identity") != "identity":
            raise public.PublicSourceError("Compressed article was rejected.")
        length = response.getheader("Content-Length")
        if length and (not length.isdigit() or int(length) > MAX_BYTES):
            raise public.PublicSourceError("Article exceeded the size budget.")
        chunks, size = [], 0
        while True:
            secured.settimeout(public._remaining(deadline))
            chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise public.PublicSourceError("Article exceeded the size budget.")
        return b"".join(chunks), "https://" + HOST + path
    except public.PublicSourceError:
        raise
    except (OSError, ValueError, http.client.HTTPException):
        raise public.PublicSourceError("Article connection failed safely.") from None
    finally:
        connection.close()


def _article(
    raw: bytes,
    pmcid: str,
    *,
    screening: dict | None = None,
    allow_preprints=True,
    parse_info: dict | None = None,
) -> list[dict]:
    """Accept bounded JATS text without resolving declarations or
    entities."""
    from labcat.article_xml import ArticleParseError, prepare_article_xml

    if parse_info is not None:
        parse_info["declaration_handling"] = "not_examined"
    try:
        text, declaration_handling = prepare_article_xml(raw, max_bytes=MAX_BYTES)
    except ArticleParseError as error:
        if parse_info is not None:
            parse_info["declaration_handling"] = error.declaration_handling
        raise
    if parse_info is not None:
        parse_info["declaration_handling"] = declaration_handling
    try:
        tree = ElementTree.fromstring(text)
    except (ElementTree.ParseError, ValueError):
        raise ArticleParseError(
            "malformed_xml", declaration_handling=declaration_handling
        ) from None
    if tree.tag != "article":
        raise ArticleParseError(
            "article_root", declaration_handling=declaration_handling
        )
    if not allow_preprints and tree.get("article-type") not in {
        "research-article",
        "review-article",
        "brief-report",
        "case-report",
    }:
        raise ArticleParseError(
            "publication_type", declaration_handling=declaration_handling
        )
    stack, count = [(tree, 0)], 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if depth > 40 or count > 30_000:
            raise ArticleParseError(
                "tree_budget", declaration_handling=declaration_handling
            )
        stack.extend((child, depth + 1) for child in node)
    identifiers = {
        "PMC" + (item.text or "").strip().removeprefix("PMC")
        for item in tree.findall("./front/article-meta/article-id")
        if item.get("pub-id-type") in {"pmcid", "pmc"}
    }
    if identifiers != {pmcid}:
        raise ArticleParseError(
            "article_identity", declaration_handling=declaration_handling
        )
    paragraphs = []
    rejected = 0

    def visit(node, locator, section):
        nonlocal rejected
        if node.tag == "sec":
            title = node.find("title")
            if title is not None:
                section = " ".join("".join(title.itertext()).split())[:160] or section
        counts = {}
        for child in node:
            counts[child.tag] = counts.get(child.tag, 0) + 1
            child_path = f"{locator}/{child.tag}[{counts[child.tag]}]"
            if child.tag == "p":
                # Inline elements keep chemistry subscripts attached to the formula.
                passage = " ".join("".join(child.itertext()).split())
                active_markup = any(
                    element.tag in {"script", "style", "iframe", "object", "form"}
                    for element in child.iter()
                )
                if active_markup or source_instruction_reason(passage + " " + section):
                    rejected += 1
                elif passage:
                    paragraphs.append(
                        {"text": passage, "locator": child_path, "section": section}
                    )
            elif child.tag == "sec":
                visit(child, child_path, section)

    body = tree.find("body")
    if body is not None:
        visit(body, "body", "Article body")
    if screening is not None:
        screening.update(policy="source-text-v1", rejected_paragraphs=rejected)
    return paragraphs


def _query(
    prompt: str,
    formulas: list[str],
    terms: tuple[str, ...],
    *,
    names=(),
    semantic_scope=None,
) -> str | None:
    # Names come from the parent's validated source/identity pairs. Encode only
    # words and ordinary name punctuation inside fixed quoted query clauses;
    # names and request spans cannot contribute query operators or destinations.
    source_names = list(
        dict.fromkeys(
            " ".join(re.findall(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*", name))
            for name in names
        )
    )[:12]
    source_names = [name for name in source_names if name]
    target = (
        public._terms(" ".join(semantic_scope["target_spans"]))[:4]
        if semantic_scope
        else public._terms(prompt)[:2]
    )
    # Retained candidates are already bounded. Do not silently make only the
    # first three candidates eligible for every selected-criterion lookup.
    # Query/article/time counts remain unchanged.
    hints = formulas[:12] or source_names or target
    if not hints:
        return None
    # All dynamic terms are bounded quoted names or alphanumeric search tokens.
    # A user URL or query operators cannot change the fixed OA constraint.
    # Formulas identify alternatives; topic words qualify the same search scope.
    # In particular, "oxide perovskites" must not admit any oxide OR any halide
    # perovskite solely because it matches one half of that material-class phrase.
    operator = " OR " if formulas or source_names else " AND "
    identity = operator.join(f'"{hint}"' for hint in hints)
    clauses = [f"({identity})"]
    if semantic_scope:
        application = public._terms(" ".join(semantic_scope["application_spans"]))
        if application:
            # Preserve the requested role without requiring every conversational
            # adjective to appear in a publication's searchable metadata.
            clauses.append("(" + " OR ".join(f'"{term}"' for term in application) + ")")
    # Require property vocabulary even when conversational context matches.
    # Environment/processing spans remain in the assessment scope; they cannot
    # substitute for the selected property or make this query more restrictive.
    properties = " OR ".join(f'"{term}"' for term in dict.fromkeys(terms))
    clauses.extend([f"({properties})", "OPEN_ACCESS:Y"])
    return " AND ".join(clauses)


def _search(
    query: str, limit: int, deadline: float, *, allow_preprints=True
) -> list[dict]:
    if not allow_preprints:
        query += ' AND NOT SRC:PPR AND NOT PUB_TYPE:"preprint"'
    raw, request_url = public._fetch(
        "europe_pmc",
        {
            "query": query,
            "format": "json",
            "pageSize": limit,
            "resultType": "core" if not allow_preprints else "lite",
        },
        deadline,
    )
    rows = public._json(raw).get("resultList", {}).get("result")
    if not isinstance(rows, list) or len(rows) > public.MAX_RESULTS:
        raise ValueError("invalid open-access search response")
    references = []
    for row in rows[:limit]:
        if (
            not isinstance(row, dict)
            or row.get("isOpenAccess") != "Y"
            or not public.europe_pmc_publication_allowed(row, allow_preprints)
        ):
            continue
        pmcid, title = row.get("pmcid"), public._text(row.get("title"), 1000)
        if (
            not isinstance(pmcid, str)
            or not re.fullmatch(r"PMC[0-9]{1,12}", pmcid)
            or not title
            or source_instruction_reason(title)
        ):
            continue
        references.append(
            public._reference(
                "europe_pmc",
                pmcid,
                title,
                f"https://europepmc.org/articles/{pmcid}",
                {"record_type": "open_access_publication", "full_text_read": False},
                raw,
                request_url,
            )
        )
    return references


def _abstract_topic(prompt, terms, semantic_scope):
    """Plain adapter hints, not Europe PMC operators or candidate
    aliases."""
    criterion = public._terms(terms[0])
    target = public._terms(
        " ".join(semantic_scope["target_spans"]) if semantic_scope else prompt
    )[:3]
    application = (
        public._terms(" ".join(semantic_scope["application_spans"]))[:2]
        if semantic_scope
        else []
    )
    if not criterion or not target:
        return None
    return " ".join(list(dict.fromkeys([*criterion, *target, *application]))[:8])


def _search_abstracts(query, limit, deadline, *, allow_preprints):
    from labcat.extended_discovery import search_openalex

    records, _ = search_openalex(
        query, limit, deadline, allow_preprints=allow_preprints, focused_topic=True
    )
    return records


def _readable_abstract(reference):
    from labcat.research import _targeted_abstract_document

    try:
        return _targeted_abstract_document(reference) is not None
    except Exception:
        # An invalid individual abstract must not discard other approved leads.
        # The shared parent gate still decides what qualifies as a document.
        return False


def _request(item: dict) -> tuple[str, list[str], list[str]]:
    if not isinstance(item, dict):
        raise ValueError("Invalid property lookup request.")
    attribute = item.get("attribute_id")
    if not isinstance(attribute, str) or not re.fullmatch(r"[a-z_]{1,64}", attribute):
        raise ValueError("Invalid property identifier.")
    formulas = item.get("formulas", [])
    candidate_ids = item.get("candidate_ids", [])
    if not isinstance(formulas, list) or not isinstance(candidate_ids, list):
        raise ValueError("Invalid material search hints.")
    formulas = list(
        dict.fromkeys(
            value
            for value in formulas[:20]
            if isinstance(value, str)
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,59}", value)
        )
    )
    candidate_ids = list(
        dict.fromkeys(
            value
            for value in candidate_ids[:20]
            if isinstance(value, str)
            and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", value)
        )
    )
    return attribute, candidate_ids, formulas


def _candidate_identities(request, candidate_ids):
    """Preserve explicit parent-owned pairs; independent lists cannot
    prove a join."""
    from labcat.science.candidate_leads import _name

    identities = request.get("candidate_identities", [])
    if not isinstance(identities, list) or len(identities) > 20:
        raise ValueError("Invalid candidate identity mappings.")
    result = []
    for identity in identities:
        if (
            not isinstance(identity, dict)
            or set(identity) != {"candidate_id", "names"}
            or identity["candidate_id"] not in candidate_ids
            or not isinstance(identity["names"], list)
            or not 1 <= len(identity["names"]) <= 6
            or any(_name(name) is None for name in identity["names"])
        ):
            raise ValueError("Invalid candidate identity mapping.")
        result.append(identity)
    return result


def _literal_matches(text, name):
    from labcat.science.candidate_leads import _whole_mention

    return [
        match
        for match in re.finditer(re.escape(name), text)
        if _whole_mention(text, match.start(), match.end())
    ]


def candidate_mentions(text: str, request: dict) -> dict:
    """Return literal associations only, never phase or property
    applicability.

    A parent must supply explicit candidate/name pairs from approved
    source rows. Legacy independent ID/formula lists remain unjoined
    general context. This helper is also used at the report boundary to
    recompute proposed associations.
    """
    if not isinstance(text, str) or len(text) > 4000:
        raise ValueError("Invalid candidate mention context.")
    _, candidate_ids, formulas = _request(request)
    identities = _candidate_identities(request, candidate_ids)
    matched_ids = list(
        dict.fromkeys(
            identity["candidate_id"]
            for identity in identities
            if any(_literal_matches(text, name) for name in identity["names"])
        )
    )
    return {
        "candidate_ids": matched_ids,
        "formulas": [
            formula for formula in formulas if _literal_matches(text, formula)
        ],
        "context_scope": (
            "candidate_literal_mention" if matched_ids else "general_context"
        ),
    }


def _passages(paragraphs, terms, formulas, *, diagnostics=None):
    found = []
    # Prefer the article's results/discussion to introductory summaries of other
    # works. This is a reading order only, not a claim of scientific reliability.
    ordered = sorted(
        paragraphs,
        key=lambda item: (
            not re.search(r"results|discussion|conclusion", item["section"], re.I)
        ),
    )
    examined = 0
    for paragraph in ordered:
        examined += 1
        _count(diagnostics, "paragraphs_examined")
        text = paragraph["text"]
        match = re.search("|".join(re.escape(term) for term in terms), text, re.I)
        if not match:
            _count(diagnostics, "paragraphs_without_criterion")
            continue
        _count(diagnostics, "criterion_matching_paragraphs")
        identity_matches = [
            identity_match
            for hint in formulas
            for identity_match in _literal_matches(text, hint)
        ]
        if formulas and not identity_matches:
            _count(diagnostics, "criterion_without_candidate")
            continue
        _count(
            diagnostics,
            (
                "candidate_and_criterion_paragraphs"
                if formulas
                else "candidate_filter_not_required"
            ),
        )
        # Preserve a complete bounded paragraph before considering a short
        # review snippet. Cropping ordinary results paragraphs can remove the
        # method, sample or adverse finding that qualifies the matching phrase.
        if len(text) <= MAX_COMPLETE_PARAGRAPH:
            found.append({**paragraph, "paragraph_complete": True})
            _count(diagnostics, "complete_passages_selected")
            if len(found) >= MAX_PASSAGES_PER_ATTRIBUTE:
                break
            continue
        start = max(0, match.start() - 250)
        if identity_matches:
            identity = min(
                identity_matches, key=lambda item: abs(item.start() - match.start())
            )
            start = max(0, min(identity.start(), match.start()) - 100)
            if max(identity.end(), match.end()) > start + MAX_EXCERPT:
                _count(diagnostics, "crop_context_rejections")
                continue
        # This is a literal slice of whitespace-normalized source text. Search
        # hints, inferred values and model prose are never inserted into excerpts.
        # Keep complete tokens at both edges so the saved slice cannot turn a
        # longer composition into an apparently standalone candidate mention.
        if len(text) <= MAX_EXCERPT:
            start = 0
        end = min(len(text), start + MAX_EXCERPT)
        if start and not text[start - 1].isspace():
            boundary = text.find(" ", start, end)
            if boundary == -1:
                _count(diagnostics, "crop_context_rejections")
                continue
            start = boundary + 1
        if end < len(text) and not text[end].isspace():
            end = text.rfind(" ", start, end)
            if end == -1:
                _count(diagnostics, "crop_context_rejections")
                continue
        excerpt = text[start:end]
        if not re.search(
            "|".join(re.escape(term) for term in terms), excerpt, re.I
        ) or (
            formulas and not any(_literal_matches(excerpt, name) for name in formulas)
        ):
            _count(diagnostics, "crop_context_rejections")
            continue
        found.append(
            {**paragraph, "text": excerpt, "paragraph_complete": excerpt == text}
        )
        _count(diagnostics, "cropped_passages_selected")
        if len(found) >= MAX_PASSAGES_PER_ATTRIBUTE:
            break
    _count(diagnostics, "paragraphs_unexamined", len(ordered) - examined)
    return found


def find_attribute_evidence(
    prompt: str,
    requests: list[dict],
    *,
    selected_sources: list[str],
    max_results_per_source: int = 2,
    query_budget: int = MAX_ATTRIBUTES,
    article_budget: int = MAX_ARTICLES,
    seconds_budget: int = MAX_SECONDS,
    allow_preprints: bool = True,
    semantic_scope: dict | None = None,
    unavailable_sources: tuple[str, ...] | list[str] = (),
) -> dict:
    """Search each missing property; return attributable leads without
    score changes.

    ``candidate_ids`` and ``formulas`` are retrieval hints only, even
    when supplied by a trusted parent. Only explicit
    ``candidate_identities`` pairs can link a literal passage mention to
    an ID; this still does not verify candidate phase. ``complete``
    means the bounded lookup finished, never complete literature
    coverage. ``unavailable_sources`` is parent-owned, current-run
    scheduling metadata; callers must not populate it from model or
    retrieved source instructions.
    """
    if not isinstance(prompt, str) or len(prompt) > 20_000:
        raise ValueError("Invalid property lookup question.")
    if semantic_scope is not None:
        from labcat.research_intent import validate_scope

        semantic_scope = validate_scope(semantic_scope, prompt)
    if type(allow_preprints) is not bool:
        raise ValueError("Invalid preprint policy.")
    if (
        type(unavailable_sources) not in (tuple, list)
        or len(unavailable_sources) > 2
        or any(
            type(source) is not str or source not in {"europe_pmc", "openalex"}
            for source in unavailable_sources
        )
        or len(set(unavailable_sources)) != len(unavailable_sources)
    ):
        raise ValueError("Invalid internal property-source availability hint.")
    if not isinstance(requests, list) or len(requests) > MAX_REQUESTS:
        raise ValueError("Too many property lookup requests.")
    if type(max_results_per_source) is not int or not 1 <= max_results_per_source <= 10:
        raise ValueError("Invalid property lookup result limit.")
    for value, maximum in (
        (query_budget, MAX_ATTRIBUTES),
        (article_budget, MAX_ARTICLES),
        (seconds_budget, MAX_SECONDS),
    ):
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(
                "Property lookup budgets must stay within fixed safety limits."
            )
    parsed = []
    for request in requests:
        attribute, candidate_ids, formulas = _request(request)
        identities = _candidate_identities(request, candidate_ids)
        names = list(
            dict.fromkeys(
                formulas + [name for item in identities for name in item["names"]]
            )
        )
        parsed.append((attribute, formulas, names, request))
    providers = [
        provider
        for provider in ("europe_pmc", "openalex")
        if isinstance(selected_sources, list) and provider in selected_sources
    ]
    enabled = bool(providers)
    result = {
        "status": "complete" if enabled else "disabled",
        "attributes": [],
        "sources": [],
        "caveats": [_CAVEAT],
    }
    deadline = time.monotonic() + seconds_budget
    cache, references, attempts, queries = {}, {}, 0, 0
    article_attempts = []
    unavailable = set(unavailable_sources) & set(providers)
    deferred = []
    limit = min(3, max_results_per_source)

    def search(provider, query, entry):
        nonlocal queries
        now = time.monotonic()
        search_deadline = min(
            deadline, now + (deadline - now) / (query_budget - queries)
        )
        entry["queries"].append(query)
        queries += 1
        diagnostics = entry["diagnostics"]
        _count(diagnostics, "searches_attempted")
        try:
            adapter = _search if provider == "europe_pmc" else _search_abstracts
            records = adapter(
                query, limit, search_deadline, allow_preprints=allow_preprints
            )
            from labcat.research import _discovery_references

            records = _discovery_references({"references": records}, [provider], limit)
            _count(diagnostics, "search_records_validated", len(records))
            return records
        except Exception:
            _count(diagnostics, "searches_failed")
            # Preserve historical single-provider recovery. When abstract
            # fallback is enabled, do not spend every criterion on a failed path.
            if "openalex" in providers:
                unavailable.add(provider)
            entry["status"] = "unavailable"
            entry["caveats"].append(
                "A public property search was unavailable or failed validation."
            )
            return None

    def retain_abstracts(records, entry):
        # Conflicting duplicates in one response cannot select a preferred text.
        grouped, ambiguous = {}, set()
        for reference in records:
            url = reference["url"]
            if url in grouped and grouped[url] != reference:
                ambiguous.add(url)
            grouped.setdefault(url, reference)
        urls = []
        for url, reference in grouped.items():
            if url in ambiguous or not _readable_abstract(reference):
                continue
            if url not in references:
                if len(references) >= MAX_ARTICLES:
                    entry["caveats"].append(
                        "Additional references exceeded the lookup budget."
                    )
                    if not urls:
                        entry["status"] = "budget_exhausted"
                    break
                references[url] = reference
            urls.append(url)
        if urls:
            entry["abstract_source_urls"] = urls
            entry["status"] = "abstract_review_leads"
            entry["caveats"] = [
                caveat
                for caveat in entry["caveats"]
                if caveat
                != (
                    "No matching body passage was retained; "
                    "the property remains missing."
                )
            ]

    for attribute, formulas, names, request in parsed:
        diagnostics = _new_diagnostics()
        entry = {
            "attribute_id": attribute,
            "status": "no_passages",
            "queries": [],
            "articles_read": 0,
            "passages": [],
            "caveats": [],
            "diagnostics": diagnostics,
        }
        result["attributes"].append(entry)
        if not enabled:
            entry.update(
                status="disabled", caveats=["No property search source is selected."]
            )
            continue
        if attribute not in ATTRIBUTE_TERMS:
            entry.update(
                status="unsupported",
                caveats=[
                    "No literature vocabulary is configured for this ranking criterion."
                ],
            )
            continue
        if queries >= query_budget or time.monotonic() >= deadline:
            _count(diagnostics, "lookup_budget_skips")
            entry.update(
                status="budget_exhausted",
                caveats=["Property lookup stopped at its query or time budget."],
            )
            continue
        terms = ATTRIBUTE_TERMS[attribute]
        provider = next((item for item in providers if item not in unavailable), None)
        if provider is None:
            entry.update(
                status="unavailable",
                caveats=[
                    "Selected property search sources are unavailable for this run."
                ],
            )
            continue
        abstract_topic = _abstract_topic(prompt, terms, semantic_scope)
        query = (
            _query(prompt, formulas, terms, names=names, semantic_scope=semantic_scope)
            if provider == "europe_pmc"
            else abstract_topic
        )
        if query is None:
            entry["caveats"].append("No usable material search hints were available.")
            continue
        records = search(provider, query, entry)
        alternate = (
            provider == "europe_pmc"
            and "openalex" in providers
            and "openalex" not in unavailable
            and abstract_topic is not None
        )
        if records is None and alternate:
            if queries < query_budget and time.monotonic() < deadline:
                provider = "openalex"
                records = search(provider, abstract_topic, entry)
        elif records == [] and alternate:
            # Empty results say nothing about provider health. Give other
            # requested criteria their first turn before retrying this one.
            deferred.append((entry, abstract_topic))
        if records is None:
            continue
        if provider == "openalex":
            retain_abstracts(records, entry)
            continue
        failed, exhausted = False, False
        for reference in records:
            pmcid = reference.get("record_id")
            if (
                not isinstance(pmcid, str)
                or re.fullmatch(r"PMC[0-9]{1,12}", pmcid) is None
            ):
                _count(diagnostics, "invalid_article_identifiers")
                failed = True
                continue
            if pmcid not in cache:
                if (
                    attempts >= article_budget
                    or len(references) >= MAX_ARTICLES
                    or time.monotonic() >= deadline
                ):
                    _count(diagnostics, "article_budget_skips")
                    exhausted = True
                    continue
                attempts += 1
                _count(diagnostics, "downloads_attempted")
                failure_stage = "download_failures"
                attempt = new_article_attempt(pmcid)
                article_attempts.append(attempt)
                parse_info = {}
                try:
                    raw, url = _fetch_full_text(pmcid, deadline)
                    _count(diagnostics, "downloads_completed")
                    mark_download_complete(attempt, raw)
                    failure_stage = "parse_failures"
                    screening = {}
                    paragraphs = _article(
                        raw,
                        pmcid,
                        screening=screening,
                        allow_preprints=allow_preprints,
                        parse_info=parse_info,
                    )
                    mark_parse_accepted(attempt, parse_info["declaration_handling"])
                    _count(diagnostics, "articles_parsed")
                    failure_stage = "article_metadata_failures"
                    reference["metadata"].update(
                        full_text_read=True,
                        full_text_scope="body paragraphs only",
                        content_screen=screening,
                    )
                    reference["provenance"].update(
                        full_text_request_url=url,
                        full_text_response_sha256=hashlib.sha256(raw).hexdigest(),
                        verification_scope="Public article identity and literal body "
                        "passages; property values and material applicability "
                        "unverified.",
                    )
                    cache[pmcid] = (paragraphs, reference)
                    references[pmcid] = reference
                except Exception as error:
                    # Unavailability, transport/parser failures and malformed
                    # records affect this article only, never earlier evidence.
                    cache[pmcid] = None
                    _count(diagnostics, failure_stage)
                    if failure_stage == "parse_failures":
                        from labcat.article_xml import ArticleParseError

                        # Diagnostics never contain exception text or arbitrary
                        # exception attributes. Even our typed codes are validated.
                        handling = parse_info.get("declaration_handling")
                        if type(handling) is not str or handling not in {
                            "not_examined",
                            "none",
                            "inert_removed",
                            "rejected",
                        }:
                            handling = "not_examined"
                        if type(error) is ArticleParseError:
                            try:
                                mark_parse_rejected(
                                    attempt,
                                    error.reason_code,
                                    error.declaration_handling,
                                )
                            except (AttributeError, ValueError):
                                mark_parse_rejected(attempt, "parse_other", handling)
                        else:
                            mark_parse_rejected(attempt, "parse_other", handling)
            else:
                _count(
                    diagnostics,
                    (
                        "successful_cache_reuses"
                        if cache[pmcid] is not None
                        else "failed_cache_reuses"
                    ),
                )
            if cache.get(pmcid) is None:
                failed = True
                continue
            paragraphs, reference = cache[pmcid]
            _count(diagnostics, "paragraphs_available", len(paragraphs))
            screening = reference["metadata"].get("content_screen", {})
            screened = (
                screening.get("rejected_paragraphs", 0)
                if isinstance(screening, dict)
                else 0
            )
            if type(screened) is int and screened >= 0:
                _count(diagnostics, "paragraphs_screened_out", screened)
            try:
                passages = _passages(paragraphs, terms, names, diagnostics=diagnostics)
            except Exception:
                _count(diagnostics, "passage_selection_failures")
                cache[pmcid] = None
                failed = True
                continue
            entry["articles_read"] += 1
            for passage in passages:
                if any(
                    item["article_id"] == pmcid
                    and item["locator"] == passage["locator"]
                    for item in entry["passages"]
                ):
                    _count(diagnostics, "duplicate_passages_skipped")
                    continue
                entry["passages"].append(
                    {
                        **passage,
                        "source_url": reference["url"],
                        "article_id": pmcid,
                        "response_sha256": reference["provenance"][
                            "full_text_response_sha256"
                        ],
                        **candidate_mentions(passage["text"], request),
                        "method": None,
                        "caveat": _CAVEAT,
                    }
                )
                _count(diagnostics, "passages_retained")
                if len(entry["passages"]) >= MAX_PASSAGES_PER_ATTRIBUTE:
                    break
            if len(entry["passages"]) >= MAX_PASSAGES_PER_ATTRIBUTE:
                break
        if entry["passages"]:
            entry["status"] = "review_leads"
        elif exhausted:
            entry["status"] = "budget_exhausted"
        elif failed:
            entry["status"] = "unavailable"
        if failed:
            entry["caveats"].append("Some articles were unavailable or rejected.")
        if exhausted:
            entry["caveats"].append("Additional articles exceeded the lookup budget.")
        if not entry["passages"]:
            entry["caveats"].append(
                "No matching body passage was retained; the property remains missing."
            )
    for entry, topic in deferred:
        if queries >= query_budget or time.monotonic() >= deadline:
            break
        if "openalex" in unavailable:
            break
        records = search("openalex", topic, entry)
        if records is not None:
            retain_abstracts(records, entry)
    result["sources"] = list(references.values())
    if article_attempts:
        result["article_diagnostics"] = validate_article_diagnostics(
            {"version": "article-parse-v1", "attempts": article_attempts}
        )
    if enabled and any(
        item["status"] in {"unavailable", "budget_exhausted", "unsupported"}
        or item["caveats"]
        for item in result["attributes"]
    ):
        result["status"] = "partial"
    return result
