"""Bounded, keyless property literature searches and open-access passage
skimming.

Europe PMC supplies PMCID-only fullTextXML for its OA subset. Selected
OpenAlex can supply public abstracts through its existing fixed metadata
adapter. Search hints select documents; they never establish material
identity or values. Literal passages are unscored review leads, never
scientific evidence records.
"""

import http.client
import re
import socket
import ssl
from xml.etree import ElementTree

from labcat import public_sources as public
from labcat.untrusted_text import source_instruction_reason

MAX_BYTES = 2_000_000


HOST = "www.ebi.ac.uk"


PATH = "/europepmc/webservices/rest/"


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
