"""Shared orchestration: bounded intent, public evidence, deterministic
reports."""

import re
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
