"""Keyless public discovery adapters; returned metadata never
establishes properties.

Only fixed public services are contacted. Queries are untrusted search
hints and never copied into evidence fields. Remote instructions, links,
user/account fields, abstracts and measurements are not passed to a
model or the scientific ranker. Bounded title/abstract text may
establish lexical relevance for a review lead; it never establishes
material properties, phase identity or application suitability.
"""

import hashlib
import html
import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from contextvars import ContextVar
from copy import deepcopy
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlencode
from xml.etree import ElementTree

from labcat.extended_discovery import (
    search_chemrxiv,
    search_openalex,
    search_wikipedia,
)

MAX_BYTES = 1_000_000
MAX_SECONDS = 12
MAX_RESULTS = 10
ROUTES = {
    "hybrid3": ("materials.hybrid3.duke.edu", "/materials/systems/"),
    "hybrid3_datasets": ("materials.hybrid3.duke.edu", "/materials/datasets/"),
    "hybrid3_dataset": ("materials.hybrid3.duke.edu", "/materials/datasets/"),
    "hybrid3_dataset_files": ("materials.hybrid3.duke.edu", "/materials/datasets/"),
    "hybrid3_coordinates": (
        "materials.hybrid3.duke.edu",
        "/materials/get-atomic-coordinates/",
    ),
    "nomad": ("nomad-lab.eu", "/prod/v1/api/v1/entries/query"),
    "europe_pmc": ("www.ebi.ac.uk", "/europepmc/webservices/rest/search"),
    "arxiv": ("export.arxiv.org", "/api/query"),
    "wikipedia": ("en.wikipedia.org", "/w/api.php"),
    "openalex": ("api.openalex.org", "/works"),
    "chemrxiv": ("api.openalex.org", "/works"),
    # Identity-only structure helper; not a research/ranking source or model tool.
    "pubchem_identity": ("pubchem.ncbi.nlm.nih.gov", "/rest/pug/compound/name/"),
    "pubchem_synonyms": ("pubchem.ncbi.nlm.nih.gov", "/rest/pug/compound/cid/"),
    "pubchem_formula": ("pubchem.ncbi.nlm.nih.gov", "/rest/pug/compound/fastformula/"),
    "pubchem_names": ("pubchem.ncbi.nlm.nih.gov", "/rest/pug/compound/cid/"),
}
_CATALOG = (
    {
        "id": "public_dielectric",
        "name": "Public dielectric dataset",
        "description": "Anonymous access to a versioned corpus of calculated "
        "dielectric properties and crystal structures.",
        "homepage": "https://doi.org/10.6084/m9.figshare.7108790.v2",
        "documentation_url": "https://www.nature.com/articles/sdata2016134",
        "kind": "materials_database",
        "scope": "Fresh reads of a historical public release. Matching rows can "
        "supply calculated dielectric and band-gap evidence; stability, safety "
        "and thin-film performance remain unassessed.",
    },
    {
        "id": "hybrid3",
        "name": "HybriD³",
        "description": "Public compound identities and attributed band-gap datasets.",
        "homepage": "https://materials.hybrid3.duke.edu/",
        "documentation_url": (
            "https://hybrid3-database.readthedocs.io/en/latest/website.html"
        ),
        "kind": "materials_database",
        "scope": "Bounded public identity discovery and fresh band-gap dataset reads "
        "with source method, phase and uncertainty. Database membership does not "
        "establish a material class, stability or processing suitability.",
    },
    {
        "id": "nomad",
        "name": "NOMAD",
        "description": "Published, non-embargoed material identity records.",
        "homepage": "https://nomad-lab.eu/",
        "documentation_url": (
            "https://docs.nomad-lab.eu/develop/howto/manage/program/api.html"
        ),
        "kind": "materials_database",
        "scope": "Composition hints required; no property claims extracted.",
    },
    {
        "id": "europe_pmc",
        "name": "Europe PMC",
        "description": "Open-access publication references with a public article link.",
        "homepage": "https://europepmc.org/",
        "documentation_url": "https://europepmc.org/RestfulWebService",
        "kind": "open_publications",
        "scope": "Open-access records; targeted missing-attribute follow-up can "
        "skim a bounded set of approved open article XML passages for review.",
    },
    {
        "id": "arxiv",
        "name": "arXiv",
        "description": "Public preprint references for physics and materials research.",
        "homepage": "https://arxiv.org/",
        "documentation_url": "https://info.arxiv.org/help/api/user-manual.html",
        "kind": "open_publications",
        "scope": "Preprint metadata; peer review and property claims are not verified.",
    },
    {
        "id": "wikipedia",
        "name": "Wikipedia",
        "description": "Public encyclopedia introductions for background context.",
        "homepage": "https://en.wikipedia.org/",
        "documentation_url": "https://www.mediawiki.org/wiki/API:Search",
        "kind": "background_reference",
        "scope": "Article introductions only; not peer-reviewed material-property "
        "evidence and never used to calculate ranking scores.",
    },
    {
        "id": "openalex",
        "name": "OpenAlex",
        "description": "Scholarly references with provider-reported open locations.",
        "homepage": "https://openalex.org/",
        "documentation_url": "https://help.openalex.org/api/",
        "kind": "open_publications",
        "scope": "Bounded anonymous metadata search. Open-access status, versions "
        "and licenses are provider-reported; publisher full text is not fetched.",
    },
    {
        "id": "chemrxiv",
        "name": "ChemRxiv via OpenAlex",
        "description": "Public chemistry preprint references indexed by OpenAlex.",
        "homepage": "https://chemrxiv.org/",
        "documentation_url": "https://help.openalex.org/api/",
        "kind": "open_publications",
        "scope": "References must have an open location in the indexed ChemRxiv "
        "repository. No direct scraping, full-text or peer-review verification.",
    },
)
_STOP = set(
    "a an the i we you me us my our your please find search look for to of and or "
    "in on with from that this these those is are be can could would should want "
    "need show return give help promising candidates candidate materials material "
    "prefer preference preferred experiments experiment evidence public sources "
    "source request question about using use based summary audit rank ranked "
    "shortlist caveats include have has which when what than then ignore previous "
    "instructions system assistant user prompt compare comparison compared screen "
    "screening report reports reporting reported record records methods method "
    "missing uncertain property properties details information results output "
    "generate generation write written list lists available access open online "
    "retrieve retrieved research study studies assess assessment evaluate "
    "evaluation criteria criterion ranking like used it its they them their "
    "also able around approximately roughly about suitable particular specific "
    "ideally desired ev solution processed processable processing "
    "identify suggest recommend explore select prepare build starting "
    "prioritize prioritizing prefer favor worth investigate review keep "
    "distinguish explain establish compare comparison".split()
)
_ELEMENTS = set(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu "
    "Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs "
    "Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl "
    "Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg "
    "Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split()
)
_ARXIV_LOCK = threading.Lock()
_ARXIV_LAST = 0.0


class PublicSourceError(ValueError):
    """A bounded public discovery request could not be completed
    safely."""


def catalog() -> list[dict]:
    return [{**entry, "requires_credentials": False} for entry in _CATALOG]


def _query_text(query: str) -> str:
    query = re.sub(r"https?://\S+|www\.\S+|\S+@\S+", " ", query, flags=re.I)
    # Pasted search operators are not material hints and cannot override our
    # service-owned query fields (for example OPEN_ACCESS:N).
    return re.sub(r"\b[A-Z][A-Z_]+:[A-Za-z0-9_-]+", " ", query)


_SEARCH_SCOPE = ContextVar("public_source_semantic_scope", default=None)
_SEARCH_CONTEXT = ContextVar("public_source_identity_context", default=None)


def _identity_context(query):
    if context := _SEARCH_CONTEXT.get():
        return context
    scope = _SEARCH_SCOPE.get()
    if scope is None:
        return query, None, None
    return (
        scope["target_text"],
        (
            None
            if scope["material_class"] in {"unknown", "custom"}
            else scope["material_class"]
        ),
        scope["identity_scope"],
    )


def _terms(query: str) -> list[str]:
    # Focused literature topics already express the requested application.
    # Catalog class labels must not become extra mandatory publication words.
    words = re.findall(r"[A-Za-z][A-Za-z0-9]{0,39}", _query_text(query))
    return list(
        dict.fromkeys(word.lower() for word in words if word.lower() not in _STOP)
    )[:8]


def _hints(query, *, include_context=False):
    from labcat.science.preferences import derive_search_filters

    target, material_class, _ = _identity_context(query)
    filters = derive_search_filters(_query_text(target), material_class)
    formulas = filters.get("formula", "").split(",") if filters.get("formula") else []
    symbols = {formula.lower() for formula in formulas}
    topics = [
        term
        for term in _terms(query if include_context else target)
        if term not in symbols and len(term) > 2
    ]
    return filters, formulas, topics


def _word_set(text):
    # Whole words prevent Si from matching silver/cesium/bismuth. A conservative
    # plural normalization helps class names without stemming unrelated words.
    return {
        (
            word[:-1]
            if len(word) > 4 and word.endswith("s") and not word.endswith("ss")
            else word
        )
        for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", text.lower())
    }


def _matches_composition(formula, filters):
    from labcat.science.preferences import (
        composition_key,
        matches_composition_scope,
        validate_formula,
    )

    try:
        elements = set(validate_formula(formula))
        if not matches_composition_scope(formula, filters.get("composition_scope")):
            return False
        if filters.get("formula"):
            return composition_key(formula) in {
                composition_key(value) for value in filters["formula"].split(",")
            }
        if filters.get("chemsys"):
            return elements in [
                set(value.split("-")) for value in filters["chemsys"].split(",")
            ]
        return set(filters.get("elements", "").split(",")) - {""} <= elements
    except ValueError:
        return False


def _publication_terms(query):
    from labcat.perovskite_discovery import tandem_terms

    return list(tandem_terms(query, _SEARCH_SCOPE.get())) or _terms(query)


def _publication_query(query, *, focused_topic=False):
    from labcat.perovskite_discovery import tandem_terms

    if terms := tandem_terms(query, _SEARCH_SCOPE.get()):
        return "(" + " AND ".join(f'"{term}"' for term in terms) + ")"
    _, formulas, topics = _hints(query, include_context=True)
    clauses = []
    if formulas:
        clauses.append("(" + " OR ".join(f'"{formula}"' for formula in formulas) + ")")
    if topics:
        # Alternative requested compositions must not all occur in one article.
        # For explicit identities, a topic match narrows the material literature.
        # Discovery is deliberately broad. Fine-grained property requirements
        # are searched separately after candidate identities have been found.
        # Requiring every adjective from a conversational prompt destroys recall.
        # Compact coordinator topics deliberately include the application after
        # the class words. Do not silently discard those disambiguating words.
        # Long conversational requests retain the broad legacy behavior.
        topics = topics if formulas or focused_topic else topics[:2]
        operator = " OR " if formulas else " AND "
        clauses.append("(" + operator.join(f'"{term}"' for term in topics) + ")")
    return " AND ".join(clauses)


def _publication_matches(query, title, abstract=None):
    """Conservative metadata relevance only; missing synonyms may reduce
    recall."""
    _, formulas, topics = _hints(query, include_context=True)
    title = _text(title, 1000)
    if title is None:
        return False
    if abstract is not None and abstract != "":
        abstract = _text(abstract, 20_000)
        if abstract is None:
            return False
    # Comparison only: publisher HfO<sub>2</sub> and its escaped spelling must
    # match the formula hint HfO2. Preserve original text/provenance in references;
    # never render markup or interpret links, attributes, or nonnumeric contents.
    text = html.unescape(title + " " + (abstract or ""))
    text = re.sub(
        r"<sub>\s*([0-9]{1,6}(?:\.[0-9]{1,6})?)\s*</sub>",
        r"\1",
        text,
        flags=re.I,
    )
    # Apply the same instruction/control screen after normalization as before it.
    text = _text(text, 21_001)
    if text is None:
        return False
    if formulas and not any(
        re.search(r"(?<![A-Za-z0-9])" + re.escape(formula) + r"(?![A-Za-z0-9])", text)
        for formula in formulas
    ):
        return False
    if not topics:
        return bool(formulas)
    from labcat.perovskite_discovery import tandem_terms

    if terms := tandem_terms(query, _SEARCH_SCOPE.get()):
        words = _word_set(text)
        # Role relevance only, never a demonstration or property judgment.
        return (
            "perovskite" in words
            and "tandem" in words
            and ("silicon" not in terms or bool(words & {"silicon", "si"}))
        )
    matched = len(_word_set(text) & _word_set(" ".join(topics)))
    return matched >= (1 if formulas else min(2, len(_word_set(" ".join(topics)))))


def _elements(query: str) -> list[str]:
    query = re.sub(r"https?://\S+|www\.\S+|\S+@\S+", " ", query, flags=re.I)
    found = set()
    for token in re.findall(r"\b[A-Z][A-Za-z0-9]{1,39}\b", query):
        parts = re.findall(r"([A-Z][a-z]?)[0-9]*", token)
        if (
            parts
            and re.fullmatch(r"(?:[A-Z][a-z]?[0-9]*)+", token)
            and set(parts) <= _ELEMENTS
            and token not in {"He", "In", "As", "At", "Am", "Be", "No"}
        ):
            found.update(parts)
    for word, element in (("oxide", "O"), ("nitride", "N"), ("sulfide", "S")):
        if re.search(r"\b" + word + r"s?\b", query, re.I):
            found.add(element)
    return sorted(found)[:8]


def _addresses(host: str, deadline: float) -> list[str]:
    result, errors = [], []
    complete = threading.Event()

    def resolve():
        try:
            result.extend(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError:
            errors.append(True)
        finally:
            complete.set()

    threading.Thread(target=resolve, daemon=True, name="public-source-dns").start()
    if not complete.wait(max(0, min(3, deadline - time.monotonic()))) or errors:
        raise PublicSourceError("Public source DNS lookup was unavailable.")
    addresses = sorted({item[4][0] for item in result})
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise PublicSourceError("Public source resolved to a prohibited address.")
    # Prefer IPv4 for hosts with both families: common container networks have
    # no IPv6 route. Validate every DNS answer first, including unused addresses.
    return sorted(addresses, key=lambda ip: ipaddress.ip_address(ip).version)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PublicSourceError("Public source exceeded the request time budget.")
    return remaining


def _fetch(
    source_id: str, params: dict, deadline: float, body=None, *, structure_archive=False
) -> tuple[bytes, str]:
    """Pinned public address plus verified TLS; no proxy, redirects,
    auth or cookies."""
    if source_id not in ROUTES:
        raise PublicSourceError("Public source is not approved.")
    host, path = ROUTES[source_id]
    if source_id in {"pubchem_identity", "pubchem_synonyms"}:
        from urllib.parse import quote

        if body is not None or structure_archive or not isinstance(params, dict):
            raise PublicSourceError("Unsupported public identity route.")
        if source_id == "pubchem_identity":
            name = params.get("name")
            if (
                set(params) != {"name"}
                or not isinstance(name, str)
                or not (
                    3 <= len(name) <= 120
                    and re.fullmatch(r"[A-Za-z][A-Za-z0-9 (),.'-]*", name)
                )
            ):
                raise PublicSourceError("Unsupported compound name lookup.")
            path += quote(name, safe="") + "/property/MolecularFormula/JSON"
            params = {"name_type": "complete"}
        else:
            cid = params.get("cid")
            if set(params) != {"cid"} or type(cid) is not int or not 0 < cid < 10**10:
                raise PublicSourceError("Unsupported compound identity.")
            path += str(cid) + "/synonyms/JSON"
            params = {}
    if source_id in {"pubchem_formula", "pubchem_names"}:
        if body is not None or structure_archive or not isinstance(params, dict):
            raise PublicSourceError("Unsupported public chemical-name route.")
        if source_id == "pubchem_formula":
            from labcat.chemical_names import lookup_eligible

            formula = params.get("formula")
            if set(params) != {"formula"} or not lookup_eligible(formula):
                raise PublicSourceError("Unsupported formula identity lookup.")
            path += formula + "/cids/JSON"
            params = {"MaxRecords": 3}
        else:
            cid = params.get("cid")
            if set(params) != {"cid"} or type(cid) is not int or not 0 < cid < 10**10:
                raise PublicSourceError("Unsupported compound identity.")
            path += str(cid) + "/property/MolecularFormula,IUPACName,Title/JSON"
            params = {}
    if source_id in {"hybrid3_dataset", "hybrid3_coordinates", "hybrid3_dataset_files"}:
        if (
            not isinstance(params, dict)
            or set(params) != {"record_id"}
            or type(params["record_id"]) is not int
            or not 0 < params["record_id"] < 1_000_000_000
            or body is not None
            or structure_archive
        ):
            raise PublicSourceError("Unsupported public HybriD³ record route.")
        path += str(params["record_id"])
        if source_id == "hybrid3_dataset":
            path += "/"
        elif source_id == "hybrid3_dataset_files":
            path += "/files/"
        params = {}
    if type(structure_archive) is not bool or (
        structure_archive and (source_id != "nomad" or params or body is None)
    ):
        raise PublicSourceError("Unsupported public structure transport.")
    if structure_archive:
        # An internal adapter-only operation: never accept a URL or raw-file path.
        path = "/prod/v1/api/v1/entries/archive/query"
    if params:
        path += "?" + urlencode(params)
    connection = http.client.HTTPSConnection(host, timeout=_remaining(deadline))
    try:
        addresses = _addresses(host, deadline)
        raw_socket = socket.create_connection(
            (addresses[0], 443), timeout=_remaining(deadline)
        )
        try:
            secured = ssl.create_default_context().wrap_socket(
                raw_socket, server_hostname=host
            )
            connection.sock = secured
        except Exception:
            raw_socket.close()
            raise
        secured.settimeout(_remaining(deadline))
        connection.request(
            "GET" if body is None else "POST",
            path,
            body=None if body is None else json.dumps(body).encode(),
            headers={
                "Accept": (
                    "application/atom+xml"
                    if source_id == "arxiv"
                    else (
                        "*/*"
                        if source_id == "hybrid3_dataset_files"
                        else "application/json"
                    )
                ),
                "Accept-Encoding": "identity",
                "Content-Type": "application/json",
                "User-Agent": "Labcat/0.1 public-reference-discovery",
            },
        )
        secured.settimeout(_remaining(deadline))
        response = connection.getresponse()
        if response.status != 200:
            raise PublicSourceError("Public source was unavailable or rate limited.")
        accepted = (
            {"application/atom+xml", "application/xml", "text/xml"}
            if source_id == "arxiv"
            else (
                {"application/zip", "application/x-zip-compressed"}
                if source_id == "hybrid3_dataset_files"
                else {"application/json"}
            )
        )
        if (
            response.getheader("Content-Type", "").split(";", 1)[0].strip()
            not in accepted
        ):
            raise PublicSourceError("Public source returned an unsupported format.")
        if response.getheader("Content-Encoding", "identity") != "identity":
            raise PublicSourceError("Compressed source responses are not accepted.")
        limit = (
            65536 if source_id in {"pubchem_formula", "pubchem_names"} else MAX_BYTES
        )
        length = response.getheader("Content-Length")
        if length and (not length.isdigit() or int(length) > limit):
            raise PublicSourceError("Public source exceeded the response size budget.")
        chunks, size = [], 0
        while True:
            secured.settimeout(_remaining(deadline))
            chunk = response.read1(min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                raise PublicSourceError(
                    "Public source exceeded the response size budget."
                )
        return b"".join(chunks), "https://" + host + path
    except PublicSourceError:
        raise
    except (OSError, ValueError, http.client.HTTPException):
        raise PublicSourceError("Public source connection failed safely.") from None
    finally:
        connection.close()


def _text(value, maximum=300) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        return None
    from labcat.untrusted_text import source_instruction_reason

    if source_instruction_reason(value):
        return None
    # Accepted metadata is still literal text, never interpreted as instructions.
    return " ".join(value.split())


class _AbstractPlainText(HTMLParser):
    """Read only inert source formatting; reject hidden or active
    markup."""

    _INLINE = frozenset({"b", "strong", "i", "em", "u", "small", "sub", "sup"})
    _BLOCK = frozenset({"p", "div", "h1", "h2", "h3", "h4", "h5", "h6"})
    _VOID = frozenset({"br", "hr"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []
        self.valid = True

    def handle_starttag(self, tag, attrs):
        # No attributes are needed to read scientific prose. Reject even an
        # otherwise inert tag with style/event attributes instead of hiding it.
        if attrs or tag not in self._INLINE | self._BLOCK | self._VOID:
            self.valid = False
            return
        if tag in self._BLOCK | self._VOID:
            self.parts.append(" ")
        if tag not in self._VOID:
            if len(self.stack) >= 32:
                self.valid = False
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.valid = False
            return
        self.stack.pop()
        if tag in self._BLOCK:
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        self.parts.append(data)

    def handle_comment(self, data):
        self.valid = False

    def handle_decl(self, decl):
        self.valid = False

    def unknown_decl(self, data):
        self.valid = False

    def handle_pi(self, data):
        self.valid = False


def _abstract_text(value):
    """Retain a bounded source-plain-text-v1 excerpt, never property
    evidence.

    Quotes bind to this normalized source text: decode at most two entity
    layers, remove only allowed inert formatting, preserve inline/sub/sup
    adjacency, separate blocks, and collapse whitespace. Source-response hashes
    continue to bind to the unchanged fetched bytes, not this presentation.
    """
    # Inspect the complete bounded source before any markup can disappear.
    text = _text(value, 12_000)
    if text is None:
        return None
    for _ in range(2):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    parser = _AbstractPlainText()
    try:
        parser.feed(text)
        parser.close()
    except (ValueError, AssertionError):
        return None
    if not parser.valid or parser.stack:
        return None
    visible = "".join(parser.parts)
    # Malformed or more deeply escaped tags must not survive as a concealed
    # second layer of markup after the parser has finished.
    if re.search(r"<(?:/?[A-Za-z]|[!?])", visible):
        return None
    # Formatting can split an instruction into fragments. Screen the complete
    # visible result again before taking a prefix, including text beyond it.
    text = _text(visible, 12_000)
    if text is None:
        return None
    while len(json.dumps(text, ensure_ascii=True)) > 6000:
        text = text[: max(1, len(text) * 3 // 4)].rpartition(" ")[0]
        if not text:
            return None  # Never manufacture a name by cutting through a token.
    return text


def _json(raw: bytes) -> dict:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    result = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError("invalid object")
    return result


def _reference(source_id, record_id, title, url, metadata, raw, request_url):
    return {
        "source_id": source_id,
        "record_id": record_id,
        "source_name": next(
            item["name"] for item in _CATALOG if item["id"] == source_id
        ),
        "title": title,
        "url": url,
        "access_scope": "public",
        "provenance_status": "verified",
        "kind": "discovery_reference",
        "is_material_evidence": False,
        "metadata": metadata,
        "provenance": {
            "retrieved_at": datetime.now(UTC).isoformat(),
            "request_url": request_url,
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "verification_scope": (
                "Public bibliographic/material identity metadata; "
                "not material-property evidence."
            ),
        },
    }


def _search_hybrid3(query: str, limit: int, deadline: float):
    raw, url = _fetch("hybrid3", {"page": 1, "page_size": 1000}, deadline)
    data = _json(raw)
    rows = data.get("results")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("invalid catalog")
    filters, _, topics = _hints(query)
    composition_hint = any(
        filters.get(key) for key in ("formula", "chemsys", "elements")
    )
    matches = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get("pk")) is not int:
            continue
        identity = row["pk"]
        title, formula = _text(row.get("compound_name")), _text(row.get("formula"), 160)
        if not 0 < identity < 1_000_000_000 or not title or not formula:
            continue
        if not _matches_composition(formula, filters):
            continue
        text = " ".join((title, formula, _text(row.get("group"), 1000) or ""))
        score = len(_word_set(text) & _word_set(" ".join(topics)))
        if score or composition_hint:
            matches.append((score, identity, title, formula))
    references = [
        _reference(
            "hybrid3",
            str(identity),
            f"{formula} — {title}",
            f"https://materials.hybrid3.duke.edu/materials/systems/{identity}/",
            {"formula": formula, "record_type": "compound_identity"},
            raw,
            url,
        )
        for _, identity, title, formula in sorted(matches, key=lambda r: (-r[0], r[1]))[
            :limit
        ]
    ]
    note = (
        "Matched requested compositions or whole-word topic hints in a bounded "
        "public identity catalog; numerical properties were not retrieved. "
        "Unrecognized formula notation and unmatched synonyms can reduce coverage."
    )
    if data.get("next"):
        note += " Catalog was truncated; returned pagination links were not followed."
    return references, note


def _search_nomad(query: str, limit: int, deadline: float):
    from labcat.science.preferences import validate_formula

    filters, formulas, _ = _hints(query)
    if formulas:
        groups = [validate_formula(formula) for formula in formulas]
    else:
        groups = [
            value.split("-") for value in filters.get("chemsys", "").split(",") if value
        ]
    elements = filters.get("elements", "").split(",") if filters.get("elements") else []
    if not groups and not elements:
        return (
            [],
            "Add a composition hint such as TiO2; "
            "this adapter searches element identities.",
        )
    body = {
        "owner": "public",
        "query": (
            {
                "or": [
                    {
                        "results.material.elements": {"all": sorted(set(group))},
                        "results.material.n_elements": len(set(group)),
                    }
                    for group in groups
                ]
            }
            if groups
            else {"results.material.elements": {"all": elements}}
        ),
        "pagination": {"page_size": limit},
        "required": {
            "include": [
                "entry_id",
                "upload_id",
                "published",
                "with_embargo",
                "results.material.chemical_formula_hill",
            ]
        },
    }
    raw, url = _fetch("nomad", {}, deadline, body)
    data = _json(raw)
    if data.get("owner") != "public" or not isinstance(data.get("data"), list):
        raise ValueError("unverified public scope")
    if len(data["data"]) > MAX_RESULTS:
        raise ValueError("too many results")
    references = []
    for row in data["data"]:
        if (
            not isinstance(row, dict)
            or row.get("published") is not True
            or row.get("with_embargo") is not False
        ):
            continue
        identity, upload = row.get("entry_id"), row.get("upload_id")
        if any(
            not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item)
            for item in (identity, upload)
        ):
            continue
        material = (row.get("results") or {}).get("material") or {}
        formula = _text(material.get("chemical_formula_hill"), 160)
        if not formula or not _matches_composition(formula, filters):
            continue
        references.append(
            _reference(
                "nomad",
                identity,
                f"{formula} — NOMAD public entry",
                f"https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/{identity}",
                {"formula": formula, "record_type": "compound_identity"},
                raw,
                url,
            )
        )
    return (
        references[:limit],
        "Public, non-embargoed identities matched to requested compositions; "
        "composition search is bounded and is not a property ranking.",
    )


def europe_pmc_publication_allowed(row: dict, allow_preprints: bool) -> bool:
    """Do not let a preprint-disabled policy rely on a search filter
    alone."""
    if allow_preprints:
        return True
    kinds = row.get("pubTypeList", {})
    kinds = kinds.get("pubType") if isinstance(kinds, dict) else None
    return (
        row.get("source") in {"MED", "PMC"}
        and isinstance(kinds, list)
        and bool(kinds)
        and all(isinstance(kind, str) for kind in kinds)
        and not any("preprint" in kind.lower() for kind in kinds)
        and any(
            kind.lower()
            in {"journal article", "review", "research-article", "review-article"}
            for kind in kinds
        )
    )


def _search_europe_pmc(
    query: str,
    limit: int,
    deadline: float,
    *,
    allow_preprints=True,
    focused_topic=False,
    discovery_article_budget=2,
):
    hints = _publication_query(query, focused_topic=focused_topic)
    if not hints:
        return [], "No usable material or topic hints for publication discovery."
    search = hints + " AND OPEN_ACCESS:Y"
    if not allow_preprints:
        search += ' AND NOT SRC:PPR AND NOT PUB_TYPE:"preprint"'
    raw, url = _fetch(
        "europe_pmc",
        {"query": search, "format": "json", "pageSize": limit, "resultType": "core"},
        deadline,
    )
    rows = _json(raw).get("resultList", {}).get("result")
    if not isinstance(rows, list) or len(rows) > MAX_RESULTS:
        raise ValueError("invalid publication list")
    references = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("isOpenAccess") != "Y"
            or not europe_pmc_publication_allowed(row, allow_preprints)
        ):
            continue
        identity, title = row.get("pmcid"), _text(row.get("title"), 1000)
        if (
            not title
            or not isinstance(identity, str)
            or not re.fullmatch(r"PMC[0-9]{1,12}", identity)
            or not _publication_matches(query, title, row.get("abstractText"))
        ):
            continue
        metadata = {
            "record_type": "open_access_publication",
            "full_text_read": False,
            "relevance_scope": (
                "Title/abstract search hints only; material applicability unverified."
            ),
        }
        abstract = _abstract_text(row.get("abstractText"))
        if abstract:
            metadata.update(abstract=abstract, abstract_read=True)
        year = row.get("pubYear")
        if isinstance(year, str) and re.fullmatch(r"[12][0-9]{3}", year):
            metadata["year"] = year
        references.append(
            _reference(
                "europe_pmc",
                identity,
                title,
                f"https://europepmc.org/articles/{identity}",
                metadata,
                raw,
                url,
            )
        )
    from labcat.perovskite_discovery import retain_device_passages, tandem_terms

    if tandem_terms(query, _SEARCH_SCOPE.get()):
        retain_device_passages(
            references,
            deadline,
            allow_preprints=allow_preprints,
            article_budget=discovery_article_budget,
        )
    return (
        references[:limit],
        "Open-access references screened for title/abstract relevance. "
        "Unmatched or missing metadata is omitted; synonyms may be missed. "
        "Full text and material-property claims were not verified.",
    )


def _search_arxiv(query: str, limit: int, deadline: float, *, focused_topic=False):
    global _ARXIV_LAST
    hints = _publication_query(query, focused_topic=focused_topic)
    if not hints:
        return [], "No usable material or topic hints for publication discovery."
    if not _ARXIV_LOCK.acquire(blocking=False):
        raise PublicSourceError("arXiv request is already active; try again shortly.")
    try:
        if time.monotonic() - _ARXIV_LAST < 3:
            raise PublicSourceError(
                "arXiv requires spacing requests; try again shortly."
            )
        _ARXIV_LAST = time.monotonic()
        params = {
            "search_query": re.sub(r'"([^\"]+)"', r'all:"\1"', hints),
            "start": 0,
            "max_results": limit,
        }
        raw, url = _fetch("arxiv", params, deadline)
    finally:
        _ARXIV_LOCK.release()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("unsupported XML declarations")
    tree = ElementTree.fromstring(raw)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    if tree.tag != "{" + ns["a"] + "}feed":
        raise ValueError("invalid feed")
    rows = tree.findall("a:entry", ns)
    if len(rows) > MAX_RESULTS:
        raise ValueError("too many entries")
    references = []
    for row in rows:
        identity = row.findtext("a:id", "", ns)
        match = re.fullmatch(
            r"https?://arxiv\.org/abs/([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?|"
            r"[a-z.-]+/[0-9]{7}(?:v[0-9]+)?)",
            identity,
        )
        title = _text(row.findtext("a:title", "", ns), 1000)
        if (
            not match
            or not title
            or not _publication_matches(query, title, row.findtext("a:summary", "", ns))
        ):
            continue
        record_id = match.group(1)
        references.append(
            _reference(
                "arxiv",
                record_id,
                title,
                "https://arxiv.org/abs/" + record_id,
                {
                    "record_type": "preprint",
                    "full_text_read": False,
                    "peer_review_verified": False,
                    "abstract": _abstract_text(row.findtext("a:summary", "", ns)),
                    "abstract_read": True,
                    "relevance_scope": (
                        "Title/abstract search hints only; "
                        "material applicability unverified."
                    ),
                },
                raw,
                url,
            )
        )
    return (
        references[:limit],
        "Preprint references screened for title/abstract hints; missing synonyms "
        "or metadata reduce coverage. Full text, material applicability and "
        "peer-review status were not verified.",
    )


def _search_public_dielectric(query, limit, deadline):
    from labcat.science.dielectric import retrieve_live
    from labcat.science.formula_display import display_formula
    from labcat.science.preferences import (
        derive_search_filters,
        scalar_scope_resolved,
        supports_bulk_search,
    )
    from labcat.science.retrieval_budget import repository_budget

    target, material_class, identity_scope = _identity_context(query)
    filters = derive_search_filters(target, material_class)
    if (
        not scalar_scope_resolved(target, material_class, identity_scope)
        or not supports_bulk_search(target, material_class)
        or filters.get("has_props") != "dielectric"
    ):
        return (
            [],
            "This specialized corpus is searched for inorganic dielectric queries.",
        )
    with repository_budget(_remaining(deadline)):
        records, _ = retrieve_live(filters)
    references = []
    for record in records[:limit]:
        provenance = record["provenance"]
        references.append(
            {
                "source_id": "public_dielectric",
                "record_id": record["material_id"],
                "source_name": "Public dielectric dataset",
                "title": display_formula(record["formula"])
                + " — public dielectric record",
                "url": provenance["source_url"],
                "access_scope": "public",
                "provenance_status": "verified",
                "kind": "discovery_reference",
                "is_material_evidence": False,
                "metadata": {
                    "formula": record["formula"],
                    "dataset_version": provenance["dataset_version"],
                },
                "provenance": {
                    **provenance,
                    "verification_scope": "Material identity from a freshly validated "
                    "public dataset. This reference is not ranking-property evidence.",
                },
            }
        )
    return (
        references,
        "Matching identities from the public dielectric corpus; "
        "quantitative ranking uses the separate validated property adapter.",
    )


_ADAPTERS = {
    "public_dielectric": _search_public_dielectric,
    "hybrid3": _search_hybrid3,
    "nomad": _search_nomad,
    "europe_pmc": _search_europe_pmc,
    "arxiv": _search_arxiv,
    "wikipedia": search_wikipedia,
    "openalex": search_openalex,
    "chemrxiv": search_chemrxiv,
}


def _scoped_adapter(
    adapter, query, limit, deadline, *, semantic_scope, search_context=None, **options
):
    """Explicitly carry validated preference scope across a worker
    boundary."""
    token = _SEARCH_SCOPE.set(deepcopy(semantic_scope))
    context_token = _SEARCH_CONTEXT.set(search_context)
    try:
        return adapter(query, limit, deadline, **options)
    finally:
        _SEARCH_SCOPE.reset(token)
        _SEARCH_CONTEXT.reset(context_token)


def search_public_sources(
    query: str,
    source_ids,
    limit: int = 5,
    *,
    allow_preprints=True,
    focused_topic: bool = False,
    deadline: float | None = None,
    semantic_scope: dict | None = None,
    scope_prompt: str | None = None,
    discovery_article_budget: int = 2,
) -> dict:
    """Search metadata within the per-call cap and optional monotonic
    deadline.

    Focused topics retain up to eight sanitized terms supplied by the
    coordinator. Conversational queries keep their existing broader
    discovery behavior.
    """
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 20000:
        raise ValueError("Provide a search question of at most 20,000 characters.")
    if semantic_scope is not None:
        from labcat.research_intent import validate_scope
        from labcat.science.preferences import source_search_context

        scope_prompt = query if scope_prompt is None else scope_prompt
        semantic_scope = validate_scope(semantic_scope, scope_prompt)
        search_context = source_search_context(
            scope_prompt, semantic_scope=semantic_scope
        )
    else:
        search_context = None
    if not isinstance(source_ids, (list, tuple)) or len(source_ids) > len(_ADAPTERS):
        raise ValueError("Select only the bounded list of approved public sources.")
    if (
        type(discovery_article_budget) is not int
        or not 0 <= discovery_article_budget <= 2
    ):
        raise ValueError("Discovery body budget must be between zero and two.")
    if type(allow_preprints) is not bool:
        raise ValueError("The preprint policy must be enabled or disabled.")
    if type(focused_topic) is not bool:
        raise ValueError("Focused discovery must be enabled or disabled.")
    if focused_topic and (len(query) > 160 or len(query.split()) > 16):
        raise ValueError("Focused discovery needs a short topic phrase.")
    if deadline is not None:
        try:
            valid_deadline = type(deadline) in {int, float} and math.isfinite(deadline)
        except OverflowError:
            valid_deadline = False
        if not valid_deadline:
            raise ValueError("The discovery deadline must be a finite monotonic time.")
    if any(
        not isinstance(source, str) or source not in _ADAPTERS for source in source_ids
    ):
        raise ValueError("Select only approved public sources.")
    if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
        raise ValueError("Reference count must be between 1 and 10 per source.")
    selected = list(dict.fromkeys(source_ids))
    result = {
        "references": [],
        "source_statuses": [],
        "caveats": [
            "Discovery metadata is not evidence for material properties "
            "and does not change candidate scores.",
            "Only selected public services are queried; "
            "this is not an exhaustive search of the internet.",
            "User text supplies search hints only; "
            "remote instructions and arbitrary links are never followed.",
            "Source metadata is screened for instruction-like content. Public access "
            "does not establish scientific reliability; preprints and unverified "
            "property claims remain review leads.",
        ],
    }
    if not allow_preprints:
        result["source_statuses"] = [
            {
                "source_id": source,
                "status": "skipped",
                "reference_count": 0,
                "message": "Preprints are disabled by deployment settings.",
            }
            for source in selected
            if source in {"arxiv", "chemrxiv"}
        ]
        selected = [
            source for source in selected if source not in {"arxiv", "chemrxiv"}
        ]
    if not selected:
        return result
    from labcat.science import request_violation

    violation = request_violation(query)
    if semantic_scope is not None:
        violation = violation or request_violation(scope_prompt)
    if violation:
        result["source_statuses"] = [
            {
                "source_id": source,
                "status": "blocked",
                "message": violation,
                "reference_count": 0,
            }
            for source in selected
        ]
        return result
    if not _terms(query):
        result["source_statuses"] = [
            {
                "source_id": source,
                "status": "skipped",
                "message": "Add a material or research topic.",
                "reference_count": 0,
            }
            for source in selected
        ]
        return result
    now = time.monotonic()
    deadline = (
        min(deadline, now + MAX_SECONDS)
        if deadline is not None
        else (now + MAX_SECONDS)
    )
    unavailable_message = (
        "Source unavailable within the request budget; no result was invented."
    )
    if deadline <= now:
        result["source_statuses"].extend(
            {
                "source_id": source,
                "status": "unavailable",
                "message": unavailable_message,
                "reference_count": 0,
            }
            for source in selected
        )
        return result
    executor = ThreadPoolExecutor(
        max_workers=len(selected), thread_name_prefix="public-discovery"
    )
    futures = {
        source: executor.submit(
            _scoped_adapter,
            _ADAPTERS[source],
            query,
            limit,
            deadline,
            semantic_scope=semantic_scope,
            search_context=search_context,
            **(
                {"discovery_article_budget": discovery_article_budget}
                if source == "europe_pmc" and discovery_article_budget != 2
                else {}
            ),
            **(
                {"allow_preprints": allow_preprints}
                if source in {"europe_pmc", "openalex", "chemrxiv"}
                else {}
            ),
            **(
                {"focused_topic": True}
                if focused_topic
                and source
                in {"europe_pmc", "arxiv", "wikipedia", "openalex", "chemrxiv"}
                else {}
            ),
        )
        for source in selected
    }
    done, _ = wait(futures.values(), timeout=max(0, deadline - time.monotonic()))
    executor.shutdown(wait=False, cancel_futures=True)
    for source, future in futures.items():
        status = {
            "source_id": source,
            "status": "unavailable",
            "message": unavailable_message,
            "reference_count": 0,
        }
        if future in done:
            try:
                references, message = future.result()
                # Validate each source before merging: one malformed adapter
                # batch must not invalidate other independently valid sources.
                from labcat.research import _discovery_references

                references = _discovery_references(
                    {"references": references}, [source], limit
                )
                if not isinstance(message, str) or len(message) > 2000:
                    raise ValueError("Invalid source status message.")
                result["references"].extend(references)
                status.update(
                    status="ok" if references else "no_results",
                    message=message,
                    reference_count=len(references),
                )
            except PublicSourceError as error:
                # Only these application-owned scheduling messages are shown
                # verbatim. Arbitrary exception text may contain remote content
                # or request details and is never included in a research report.
                message = str(error)
                status["message"] = (
                    message
                    if message
                    in {
                        "arXiv request is already active; try again shortly.",
                        "arXiv requires spacing requests; try again shortly.",
                    }
                    else "Source unavailable or failed validation; "
                    "other selected sources continue."
                )
            except Exception:
                # The isolated adapter future is the boundary, not the whole
                # discovery request. SystemExit/interrupts still propagate.
                status["message"] = (
                    "Source unavailable or returned unsupported metadata; "
                    "other selected sources continue."
                )
        result["source_statuses"].append(status)
    return result
