"""Shared orchestration: bounded intent, public evidence, deterministic
reports."""

import json
import re
from collections import Counter
from copy import deepcopy
from urllib.parse import urlsplit

from labcat.extended_discovery import valid_wikipedia_url

_REFERENCE_PATHS = {
    "public_dielectric": ("doi.org", r"/10\.6084/m9\.figshare\.7108790\.v2"),
    "hybrid3": ("materials.hybrid3.duke.edu", r"/materials/systems/[0-9]+/"),
    "nomad": ("nomad-lab.eu", r"/prod/v1/gui/search/entries/entry/id/[A-Za-z0-9_-]+"),
    "europe_pmc": ("europepmc.org", r"/articles/PMC[0-9]+"),
    "arxiv": (
        "arxiv.org",
        r"/abs/(?:[0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?|[a-z.-]+/[0-9]{7}(?:v[0-9]+)?)",
    ),
    "wikipedia": ("en.wikipedia.org", r"/wiki/[^/]+"),
    "openalex": ("openalex.org", r"/W[0-9]{1,15}"),
    "chemrxiv": ("openalex.org", r"/W[0-9]{1,15}"),
}


_SOURCE_STATUSES = {"ok", "no_results", "unavailable", "blocked", "skipped"}


def _discovery_references(
    response: dict, selected: list[str], limit: int
) -> list[dict]:
    """Validate adapter-owned reference scope before persisting
    navigation records."""
    if not isinstance(response, dict) or not isinstance(
        response.get("references"), list
    ):
        raise ValueError("Unsupported public discovery response.")
    if len(response["references"]) > len(selected) * limit:
        raise ValueError("Public discovery exceeded its reference limit.")
    from labcat.untrusted_text import source_instruction_reason

    references, counts = [], {}
    for item in response["references"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid public reference record.")
        provider = item.get("source_id")
        if (
            not isinstance(provider, str)
            or provider not in selected
            or provider not in _REFERENCE_PATHS
        ):
            raise ValueError("Reference source was not selected.")
        if (
            item.get("kind") != "discovery_reference"
            or item.get("is_material_evidence") is not False
            or item.get("access_scope") != "public"
            or item.get("provenance_status") != "verified"
        ):
            raise ValueError("Unsupported public reference scope.")
        for field, maximum in (("title", 1200), ("url", 2048), ("source_name", 120)):
            if (
                not isinstance(item.get(field), str)
                or not 1 <= len(item[field]) <= maximum
            ):
                raise ValueError("Invalid public reference metadata.")
        if source_instruction_reason(item["title"]):
            raise ValueError("Public reference contained untrusted instructions.")
        url = urlsplit(item["url"])
        host, pattern = _REFERENCE_PATHS[provider]
        if (
            url.scheme != "https"
            or url.hostname != host
            or url.port not in (None, 443)
            or url.username
            or url.password
            or url.query
            or url.fragment
            or not re.fullmatch(pattern, url.path)
            or any(ord(character) < 32 for character in item["url"])
            or (provider == "wikipedia" and not valid_wikipedia_url(item["url"]))
            or (
                provider in {"openalex", "chemrxiv"}
                and not re.fullmatch(r"https://openalex\.org/W[0-9]{1,15}", item["url"])
            )
        ):
            raise ValueError("Unsupported public reference URL.")
        counts[provider] = counts.get(provider, 0) + 1
        if counts[provider] > limit:
            raise ValueError("Public source exceeded its reference limit.")
        references.append(item)
    return references


def _safe_discovery_statuses(
    discovery: dict, references: list[dict], selected: list[str]
) -> list[dict]:
    """Keep adapter status enums and verified counts, never remote/error
    prose."""
    statuses = {}
    rows = discovery.get("source_statuses", [])
    if isinstance(rows, list):
        for row in rows[: len(selected)]:
            if not isinstance(row, dict):
                continue
            source, status = row.get("source_id"), row.get("status")
            if (
                isinstance(source, str)
                and source in selected
                and isinstance(status, str)
                and status in _SOURCE_STATUSES
            ):
                statuses[source] = "no_results" if status == "ok" else status
    counts = Counter(reference["source_id"] for reference in references)
    return [
        {
            "source_id": source,
            "status": "ok" if counts[source] else statuses.get(source, "unavailable"),
            "reference_count": counts[source],
        }
        for source in selected
    ]


def _targeted_abstract_document(reference):
    """Validate an approved index abstract without treating it as a body
    read."""
    from labcat.science.candidate_leads import _document

    metadata = reference.get("metadata", {})
    if (
        reference.get("source_id") != "openalex"
        or not isinstance(metadata, dict)
        or metadata.get("full_text_read") is not False
        or metadata.get("abstract_read") is not True
        or metadata.get("open_access_reported") is not True
        or metadata.get("oa_status") != "provider_reported"
        or metadata.get("record_type") not in {"open_access_publication", "preprint"}
        or any(
            key in metadata
            for key in (
                "full_text_provenance",
                "assessment_passages",
                "full_text_scope",
            )
        )
    ):
        return None
    parsed = _document(reference)
    if parsed is None or not parsed[1] or parsed[0]["text"] == parsed[0]["title"]:
        return None
    return parsed[0]


def _targeted_abstract_documents(note, references):
    """Rebind follow-up URLs to the actual retained abstract
    snapshots."""
    urls = {
        url
        for attribute in note.get("attributes", [])
        for url in attribute.get("abstract_source_urls", [])
    }
    return [
        document
        for reference in references
        if reference["url"] in urls
        and (document := _targeted_abstract_document(reference)) is not None
    ]


def _validated_attribute_note(
    followup: dict, requests: list[dict], references: list[dict]
) -> dict:
    """Keep bounded, source-linked excerpts; never accept added property
    fields."""
    from labcat.article_diagnostics import validate_article_diagnostics
    from labcat.property_research import (
        candidate_mentions,
        validate_property_diagnostics,
    )
    from labcat.untrusted_text import source_instruction_reason

    if len(json.dumps(followup, allow_nan=False)) > 524288:
        raise ValueError("Attribute follow-up exceeded its evidence limit.")
    if followup.get("status") not in {"complete", "partial", "disabled"}:
        raise ValueError("Unsupported attribute follow-up status.")
    requested = {item["attribute_id"]: item for item in requests}
    sources = {source["url"]: source for source in references}
    attributes = followup.get("attributes")
    if not isinstance(attributes, list) or len(attributes) > len(requested):
        raise ValueError("Unexpected attribute follow-up rows.")
    seen, clean = set(), []
    for item in attributes:
        identifier = item["attribute_id"]
        if (
            identifier not in requested
            or identifier in seen
            or item["status"]
            not in {
                "review_leads",
                "abstract_review_leads",
                "no_passages",
                "unavailable",
                "disabled",
                "budget_exhausted",
                "unsupported",
            }
        ):
            raise ValueError("Unexpected attribute follow-up identity.")
        seen.add(identifier)
        abstract_urls = item.get("abstract_source_urls", [])
        if (
            not isinstance(abstract_urls, list)
            or len(abstract_urls) > 3
            or any(not isinstance(url, str) for url in abstract_urls)
            or len(set(abstract_urls)) != len(abstract_urls)
            or any(
                url not in sources or _targeted_abstract_document(sources[url]) is None
                for url in abstract_urls
            )
        ):
            raise ValueError("Invalid targeted abstract references.")
        if item["status"] == "abstract_review_leads" and not abstract_urls:
            raise ValueError("Abstract review status has no accepted abstract.")
        passages = item.get("passages", [])
        if not isinstance(passages, list) or len(passages) > 3:
            raise ValueError("Too many attribute passages.")
        kept = []
        for passage in passages:
            if not isinstance(passage, dict):
                raise ValueError("Invalid attributed passage.")
            if any(
                source_instruction_reason(passage.get(field, ""))
                for field in ("text", "section")
            ):
                raise ValueError("Public passage contained untrusted instructions.")
            source = sources.get(passage["source_url"])
            if (
                not source
                or source.get("metadata", {}).get("full_text_read") is not True
            ):
                raise ValueError("Passage has no accepted open full-text source.")
            for field, maximum in (
                ("text", 4000),
                ("locator", 500),
                ("section", 300),
                ("caveat", 1200),
            ):
                if (
                    not isinstance(passage.get(field), str)
                    or not 1 <= len(passage[field]) <= maximum
                ):
                    raise ValueError("Invalid attributed passage.")
            if not re.fullmatch(r"[a-f0-9]{64}", passage.get("response_sha256", "")):
                raise ValueError("Passage content digest is missing.")
            if passage["response_sha256"] != source.get("provenance", {}).get(
                "full_text_response_sha256"
            ):
                raise ValueError("Passage and full-text source digests disagree.")
            if passage.get("article_id") != source["record_id"]:
                raise ValueError("Passage and article identities disagree.")
            for field in ("candidate_ids", "formulas"):
                if not isinstance(passage.get(field), list) or any(
                    value not in requested[identifier][field]
                    for value in passage[field]
                ):
                    raise ValueError(
                        "Passage contains an unrequested material identity."
                    )
            kept.append(
                {
                    key: deepcopy(passage[key])
                    for key in (
                        "source_url",
                        "text",
                        "locator",
                        "section",
                        "article_id",
                        "response_sha256",
                        "candidate_ids",
                        "formulas",
                        "caveat",
                    )
                }
            )
            kept[-1]["method"] = None
            # Only complete retained paragraphs are offered for model assessment;
            # cropped review snippets may omit an important method or condition.
            kept[-1]["paragraph_complete"] = passage.get("paragraph_complete") is True
            kept[-1].update(candidate_mentions(passage["text"], requested[identifier]))
        articles_read = item.get("articles_read", 0)
        if type(articles_read) is not int or not 0 <= articles_read <= 6:
            raise ValueError("Invalid full-text read count.")
        clean.append(
            {
                "attribute_id": identifier,
                "status": item["status"],
                "queries": deepcopy(item.get("queries", [])),
                "articles_read": articles_read,
                "passages": kept,
                "caveats": deepcopy(item.get("caveats", [])),
            }
        )
        if "abstract_source_urls" in item:
            clean[-1]["abstract_source_urls"] = list(abstract_urls)
        if "diagnostics" in item:
            clean[-1]["diagnostics"] = validate_property_diagnostics(
                item["diagnostics"]
            )
    note = {
        "status": followup["status"],
        "attributes": clean,
        "caveats": deepcopy(followup.get("caveats", [])),
        "used_for_ranking": False,
        "source_urls": list(sources),
    }
    if "article_diagnostics" in followup:
        note["article_diagnostics"] = validate_article_diagnostics(
            followup["article_diagnostics"]
        )
    return note
