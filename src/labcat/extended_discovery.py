"""Anonymous encyclopedia and open scholarly metadata, never scored
evidence."""

import re
import unicodedata
from urllib.parse import quote, unquote, urlsplit

CHEMRXIV_SOURCE = "https://openalex.org/S4393918830"


def wikipedia_title_url(title):
    """One namespace-zero title; reject encoded namespaces and path
    ambiguity."""
    if (
        not isinstance(title, str)
        or not 1 <= len(title) <= 300
        or title != title.strip()
        or any(character in title for character in ":/\\%?#")
        or ".." in title
        or any(unicodedata.category(character).startswith("C") for character in title)
    ):
        return None
    return "https://en.wikipedia.org/wiki/" + quote(
        title.replace(" ", "_"), safe="()_,.-"
    )


def valid_wikipedia_url(value):
    try:
        url = urlsplit(value)
        title = unquote(url.path.removeprefix("/wiki/"), errors="strict")
        return (
            url.scheme == "https"
            and url.netloc == "en.wikipedia.org"
            and not url.query
            and not url.fragment
            and url.path.startswith("/wiki/")
            and wikipedia_title_url(title) == value
        )
    except (TypeError, ValueError, UnicodeError):
        return False


def search_wikipedia(query, limit, deadline, *, focused_topic=False):
    from labcat import public_sources as public

    terms = " ".join(public._terms(query)[: 8 if focused_topic else 3])
    if not terms:
        return [], "No usable topic hints for encyclopedia discovery."
    raw, request_url = public._fetch(
        "wikipedia",
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": terms,
            "gsrnamespace": 0,
            "gsrlimit": limit,
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
            "exchars": 1200,
            "format": "json",
            "formatversion": 2,
        },
        deadline,
    )
    data = public._json(raw)
    if "error" in data:
        raise ValueError("Encyclopedia search unavailable")
    rows = data.get("query", {}).get("pages", [])
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError("Unsupported encyclopedia results")
    references = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or type(row.get("ns")) is not int
            or row["ns"] != 0
        ):
            continue
        title = public._text(row.get("title"), 300)
        excerpt = public._text(row.get("extract"), 2000)
        identity = row.get("pageid")
        url = wikipedia_title_url(title)
        if (
            not title
            or not url
            or not excerpt
            or type(identity) is not int
            or not 0 < identity < 10**12
            or row.get("missing") is True
            or not public._publication_matches(query, title, excerpt)
        ):
            continue
        reference = public._reference(
            "wikipedia",
            str(identity),
            title,
            url,
            {
                "record_type": "encyclopedia_background",
                "excerpt": excerpt,
                "excerpt_read": True,
                "full_text_read": False,
                "peer_review_verified": False,
                "used_for_ranking": False,
            },
            raw,
            request_url,
        )
        reference["provenance"]["verification_scope"] = (
            "Public encyclopedia title and introduction; background context only, "
            "not material-property evidence or a peer-reviewed source."
        )
        references.append(reference)
    return references, (
        "Public namespace-zero encyclopedia introductions; background context only. "
        "No numerical property claims are extracted or used in ranking."
    )


def _open_locations(row, *, chemrxiv, allow_preprints):
    locations = row.get("locations")
    if not isinstance(locations, list) or len(locations) > 200:
        return []
    result = []
    for location in locations:
        if not isinstance(location, dict) or location.get("is_oa") is not True:
            continue
        source = location.get("source")
        if not isinstance(source, dict):
            continue
        if chemrxiv and (
            source.get("id") != CHEMRXIV_SOURCE or source.get("type") != "repository"
        ):
            continue
        version = location.get("version")
        if not allow_preprints and version not in {
            "publishedVersion",
            "acceptedVersion",
        }:
            continue
        if version not in {"publishedVersion", "acceptedVersion", "submittedVersion"}:
            continue
        result.append(location)
    return result


def _abstract(index):
    """Reconstruct only a bounded, contiguous public abstract index."""
    if not isinstance(index, dict) or not 1 <= len(index) <= 2000:
        return None
    words = {}
    for word, positions in index.items():
        if (
            not isinstance(word, str)
            or not 1 <= len(word) <= 300
            or not isinstance(positions, list)
            or not 1 <= len(positions) <= 2000
        ):
            return None
        for position in positions:
            if (
                type(position) is not int
                or not 0 <= position < 3000
                or position in words
            ):
                return None
            words[position] = word
    if not words or set(words) != set(range(len(words))):
        return None
    from labcat import public_sources as public

    return public._abstract_text(" ".join(words[i] for i in range(len(words))))


def search_openalex(
    query, limit, deadline, *, allow_preprints=True, chemrxiv=False, focused_topic=False
):
    from labcat import public_sources as public

    source_id = "chemrxiv" if chemrxiv else "openalex"
    if chemrxiv and not allow_preprints:
        return [], "Preprints are disabled by deployment settings."
    terms = " ".join(public._publication_terms(query)[: 8 if focused_topic else 3])
    if not terms:
        return [], "No usable topic hints for scholarly discovery."
    filters = "open_access.is_oa:true,is_retracted:false"
    if chemrxiv:
        filters += ",locations.source.id:S4393918830"
    if not allow_preprints:
        filters += ",type:!preprint"
    raw, request_url = public._fetch(
        source_id,
        {
            "search": terms,
            "filter": filters,
            "per_page": limit,
            "select": "id,title,publication_year,type,open_access,locations,"
            "is_retracted,abstract_inverted_index",
        },
        deadline,
    )
    rows = public._json(raw).get("results")
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError("Unsupported scholarly results")
    references = []
    for row in rows:
        if not isinstance(row, dict) or row.get("is_retracted") is not False:
            continue
        access = row.get("open_access")
        identity, title = row.get("id"), public._text(row.get("title"), 1000)
        abstract = _abstract(row.get("abstract_inverted_index"))
        if (
            not isinstance(access, dict)
            or access.get("is_oa") is not True
            or not isinstance(identity, str)
            or not re.fullmatch(r"https://openalex\.org/W[0-9]{1,15}", identity)
            or not title
            or not public._publication_matches(query, title, abstract)
            or (not allow_preprints and row.get("type") not in {"article", "review"})
        ):
            continue
        locations = _open_locations(
            row, chemrxiv=chemrxiv, allow_preprints=allow_preprints
        )
        if not locations:
            continue
        location = locations[0]
        preprint = (
            chemrxiv
            or row.get("type") == "preprint"
            or location["version"] == "submittedVersion"
        )
        metadata = {
            "record_type": "preprint" if preprint else "open_access_publication",
            "full_text_read": False,
            "oa_status": "provider_reported",
            "open_access_reported": True,
            "peer_review_verified": False,
            "version": location["version"],
            "used_for_ranking": False,
            "relevance_scope": "Title search hints only; applicability unverified.",
        }
        if abstract:
            metadata.update(abstract=abstract, abstract_read=True)
        year = row.get("publication_year")
        if type(year) is int and 1000 <= year <= 2100:
            metadata["year"] = str(year)
        license_id = location.get("license")
        metadata["license"] = (
            license_id
            if isinstance(license_id, str)
            and re.fullmatch(r"[a-z][a-z0-9.-]{0,50}", license_id)
            else "not_reported"
        )
        if chemrxiv:
            metadata["repository_id"] = CHEMRXIV_SOURCE
        reference = public._reference(
            source_id,
            identity.rsplit("/", 1)[1],
            title,
            identity,
            metadata,
            raw,
            request_url,
        )
        reference["provenance"]["verification_scope"] = (
            "Public scholarly index metadata. Open access, version and license "
            "are provider-reported; publication full text was not retrieved "
            "or verified."
        )
        references.append(reference)
    return references, (
        "Public scholarly index references with provider-reported open locations. "
        "Publisher links are not followed; full text, licenses and peer review "
        "are not independently verified. References do not change ranking."
    )


def search_chemrxiv(
    query, limit, deadline, *, allow_preprints=True, focused_topic=False
):
    return search_openalex(
        query,
        limit,
        deadline,
        allow_preprints=allow_preprints,
        chemrxiv=True,
        focused_topic=focused_topic,
    )
