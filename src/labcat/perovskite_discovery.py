"""Bounded device-literature discovery hints, never candidate/property
facts."""

import hashlib
import re
import time

MAX_DISCOVERY_ARTICLES = 2
MAX_DISCOVERY_PASSAGES = 3
MAX_DISCOVERY_PARAGRAPH = 2400


def tandem_terms(query, semantic_scope=None):
    """Keep the requested absorber role in searches, without naming
    candidates.

    Material spans are authoritative: a perovskite device used as the environment
    for another sought material does not trigger this route.
    """
    target = query
    context = query
    if semantic_scope:
        target = semantic_scope["target_text"]
        context = " ".join([target, *semantic_scope["application_spans"]])
        if semantic_scope["material_class"] not in {"perovskites", "unknown"}:
            return ()
    from labcat.ranking_profiles import _negated_preference

    def requested(pattern, text):
        text = text.casefold()
        return any(
            not _negated_preference(text, match.start(), match.end())
            for match in re.finditer(pattern, text)
        )

    if not requested(r"\bperovskites?\b", target):
        return ()
    if not requested(r"\b(?:(?:silicon|si)[ -])?tandem\b", context):
        return ()
    all_perovskite = requested(r"\ball[ -]perovskites?\b", context)
    if not all_perovskite and requested(r"\b(?:silicon|si)\b", context):
        return ("perovskite", "silicon", "tandem")
    return ("perovskite", "tandem", "solar")


def discovery_article_budget(
    query, selected_sources, controls=None, *, semantic_scope=None, reserved=0
):
    """Allocate from the shared whole-run article cap, including failed
    attempts."""
    from labcat.developer_settings import defaults

    controls = controls or defaults()
    if (
        not controls["literature_followup"]
        or "europe_pmc" not in selected_sources
        or not tandem_terms(query, semantic_scope)
    ):
        return 0
    return max(
        0, min(MAX_DISCOVERY_ARTICLES, controls["max_article_downloads"] - reserved)
    )


def remaining_literature_controls(controls, reserved):
    """Reserve before network dispatch so timed-out requests cannot
    reset a cap."""
    from labcat.developer_settings import defaults

    if not reserved:
        return controls
    result = dict(controls or defaults())
    remaining = max(0, result["max_article_downloads"] - reserved)
    if remaining:
        result["max_article_downloads"] = remaining
    else:
        result["literature_followup"] = False
    return result


def retain_device_passages(
    references, deadline, *, allow_preprints=True, article_budget=MAX_DISCOVERY_ARTICLES
):
    """Read selected Europe PMC OA bodies through the existing fixed
    adapter.

    Complete paragraphs expose compositions often absent from abstracts.
    Lexical selection is a navigation preference, never a judgment of
    demonstration or suitability. Original metadata provenance and
    abstracts remain unchanged.
    """
    from labcat.property_research import _article, _fetch_full_text

    if (
        type(article_budget) is not int
        or not 0 <= article_budget <= MAX_DISCOVERY_ARTICLES
    ):
        raise ValueError("Discovery body budget must be between zero and two.")
    # Leave time to return accepted metadata if an optional body times out.
    deadline -= 0.25
    attempted = 0
    for reference in references:
        if attempted >= article_budget or time.monotonic() >= deadline:
            break
        if reference.get("source_id") != "europe_pmc":
            continue
        attempted += 1
        identity = reference["record_id"]
        try:
            raw, url = _fetch_full_text(identity, deadline)
            screening = {}
            paragraphs = _article(
                raw, identity, screening=screening, allow_preprints=allow_preprints
            )
            selected = []
            for index, paragraph in enumerate(paragraphs):
                text = paragraph["text"]
                if (
                    not 12
                    <= len(text) + len(paragraph["section"]) + 1
                    <= MAX_DISCOVERY_PARAGRAPH
                ):
                    continue
                composition = bool(
                    re.search(
                        r"\b(?:composition|stoichiometr|precursor|mixed[ -]cation|"
                        r"mixed[ -]halide)|(?:FA|MA|Cs|Rb|Pb|Sn)[0-9.(]",
                        text,
                        re.I,
                    )
                )
                role = bool(
                    re.search(
                        r"\b(?:perovskite|absorber|tandem|top[ -]cell|wide[ -]bandgap)",
                        text,
                        re.I,
                    )
                )
                if not composition or not role:
                    continue
                device = bool(
                    re.search(
                        r"\b(?:fabricat|deposit|device|solar cell|efficien|stabili|"
                        r"operat|measur|prepar)",
                        text,
                        re.I,
                    )
                )
                exact_mixture = bool(
                    re.search(r"(?:FA|MA|Cs|Rb)[0-9]+(?:\.[0-9]+)?", text)
                )
                heading = paragraph["section"]
                tandem_fabrication = bool(
                    re.search(
                        r"\btandem\b.*\b(?:device|fabricat)|"
                        r"\b(?:device|fabricat).*\btandem\b",
                        heading,
                        re.I,
                    )
                )
                simulation_heading = bool(
                    re.search(r"\b(?:simulat|model|computational)", heading, re.I)
                )
                # Section context only changes reading order, never a scientific
                # judgment. Preserve simulation headings when retained.
                selected.append(
                    (
                        not exact_mixture,
                        not tandem_fabrication,
                        simulation_heading,
                        not device,
                        index,
                        paragraph,
                    )
                )
            selected.sort(key=lambda row: row[:5])
            digest = hashlib.sha256(raw).hexdigest()
            passages = [
                {
                    **paragraph,
                    "article_id": identity,
                    "response_sha256": digest,
                    "paragraph_complete": True,
                    "include_section_in_document": True,
                }
                for *_, paragraph in selected[:MAX_DISCOVERY_PASSAGES]
            ]
            if not passages:
                continue
            reference["metadata"].update(
                full_text_read=True,
                full_text_scope="body paragraphs only",
                discovery_full_text_provenance={
                    "full_text_request_url": url,
                    "full_text_response_sha256": digest,
                },
                discovery_passages=passages,
                discovery_content_screen=screening,
            )
        except (OSError, ValueError, KeyError, TypeError):
            # Optional body failure must retain the accepted abstract.
            continue
