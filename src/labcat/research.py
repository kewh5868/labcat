"""Shared orchestration: bounded intent, public evidence, deterministic
reports."""

import json
import re
from collections import Counter
from copy import deepcopy
from urllib.parse import urlsplit

from labcat.config import AppConfig
from labcat.extended_discovery import valid_wikipedia_url
from labcat.onboarding import SetupRequired
from labcat.research_progress import report_progress

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


_DISCOVERY_CAVEATS = [
    "General discovery reads bibliographic and material-identity metadata and "
    "selected encyclopedia introductions; these are not scored property evidence. "
    "Any subsequent full-text "
    "skimming is identified separately in attribute follow-up and source annotations.",
    "Only the selected public adapters were searched; coverage is incomplete. "
    "Some database adapters need composition hints. Retrieved instructions and "
    "arbitrary links are never followed.",
]


_SOURCE_STATUSES = {"ok", "no_results", "unavailable", "blocked", "skipped"}


def _public_api_key(connections, mode):
    """An unavailable optional API cannot stop the other selected
    sources."""
    from labcat.credentials import ConnectionError

    try:
        connections.prepare_materials_project(mode)
        return connections.materials_project_key("auto" if mode == "api" else mode)
    except ConnectionError:
        # The verified-key accessor remains authoritative. No unverified key is
        # used, and storage errors never become user-visible credential details.
        return None


def _material_class_hint(profile: dict | None, selection: dict | None) -> str | None:
    """A fallback weighting profile must not silently narrow retrieval
    scope."""
    if not profile or (selection and selection.get("mode") == "fallback"):
        return None
    return profile.get("material_class")


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


def _attach_public_discovery(
    outcome: dict, references: list[dict], discovery_note: dict
) -> dict:
    """Assemble one class-neutral report from captured public adapter
    results."""
    outcome["sources"].extend(deepcopy(references))
    outcome["result"]["public_discovery"] = deepcopy(discovery_note)
    if outcome["stage"] == "blocked":
        # A failed quantitative request remains visible. Discovery never grants
        # permission or disguises an adapter/planning failure as a successful run.
        return outcome
    if not outcome["result"].get("candidates"):
        result = outcome["result"]
        reason = (
            result.get("reason")
            or result.get("summary")
            or ("Verified quantitative material properties were not retrieved.")
        )
        search_summary = (
            f"Returned {len(references)} public references for relevance review."
            if references
            else "No public references were returned by the selected adapters. "
            "Check source availability and refine the research topic or filters."
        )
        summary = "No scored material shortlist was generated. " + search_summary
        outcome.update(stage="partial", answer=summary)
        result.update(stage="partial", summary=summary, candidates=[])
        result.setdefault("ranking", {"status": "not_run", "reason": reason})
        result.setdefault(
            "retrieval", {"mode": "no_material_evidence", "reason": reason}
        )
        limitations = result.setdefault("limitations", [])
        for caveat in [
            reason,
            "No material properties, stability assessments or ranking scores "
            "were established for this question. Reference order is not a "
            "ranking of material performance.",
            *_DISCOVERY_CAVEATS,
        ]:
            if caveat not in limitations:
                limitations.append(caveat)
    elif references:
        outcome["answer"] += (
            f"\n\nFound {len(references)} additional public references for review. "
            "They were not used for material-property claims or ranking."
        )
    return outcome


def _attach_preliminary_screening(
    outcome, profile, *, goals=None, evaluation=None, references=None, documents=None
):
    """Rank source-bound leads in new reports without requiring property
    coverage.

    Historical reports retain their original method. Source bindings are
    checked even with no model judgments; invalid judgments cannot erase
    valid leads.
    """
    from labcat.science.literature_evaluation import (
        evaluate_candidate_batches,
        validate_evaluation,
    )

    if outcome["stage"] == "blocked":
        return outcome
    result = outcome["result"]
    leads = result.get("candidate_leads", [])
    if not leads:
        return outcome
    if references is None:
        references = result.get("public_discovery", {}).get("references", [])
    assessed = None
    if evaluation is not None:
        try:
            assessed = validate_evaluation(
                evaluation, leads, references, profile, goals=goals
            )
        except (TypeError, ValueError, KeyError):
            result.setdefault("limitations", []).append(
                "The submitted literature judgments failed revalidation and were "
                "omitted. Valid cited candidates retain preliminary screening "
                "priority with those judgments marked unknown."
            )
    if assessed is None:
        assessed = evaluate_candidate_batches(
            [], leads, references, profile, goals=goals, documents=documents
        )["evaluation"]
    result["literature_evaluation"] = assessed
    # Keep the exact discovery snapshot apart from later follow-up/deduplication.
    result.setdefault("public_discovery", {})["references"] = deepcopy(references)
    ranked = assessed["ranked_candidates"]
    if ranked:
        obsolete = (
            "No material properties, stability assessments or ranking scores "
            "were established for this question. Reference order is not a "
            "ranking of material performance."
        )
        result["limitations"] = [
            (
                "No quantitative material properties were established by public "
                "reference discovery. The preliminary shortlist uses attributed "
                "qualitative judgments and explicit unknown priors; it is not a "
                "ranking of measured performance."
                if item == obsolete
                else item
            )
            for item in result.get("limitations", [])
        ]
        summary = (
            f"Prepared a candidate shortlist of {len(ranked)} cited materials. "
            "Screening priority starts with public application discussion and "
            "is refined by available attribute assessments. Unknowns and ties "
            "remain explicit; this is review priority, not measured performance."
        )
        if result.get("candidates"):
            summary += (
                " A separate property comparison ranks retrieved material records "
                "using their validated measurements and calculations."
            )
        else:
            outcome["stage"] = result["stage"] = "partial"
        outcome["answer"] = result["summary"] = summary
    return outcome


def _add_public_discovery(
    outcome: dict,
    prompt: str,
    preferences: dict,
    *,
    allow_preprints=True,
    focused_topic=False,
    deadline=None,
    semantic_scope=None,
    scope_prompt=None,
    discovery_article_budget=None,
) -> dict:
    from labcat.public_sources import search_public_sources

    report_progress("discovery")
    failed = False
    try:
        options = {}
        if discovery_article_budget is not None:
            options["discovery_article_budget"] = discovery_article_budget
        if focused_topic:
            options["focused_topic"] = True
        if deadline is not None:
            options["deadline"] = deadline
        if semantic_scope is not None:
            options["semantic_scope"] = semantic_scope
            options["scope_prompt"] = scope_prompt
        discovery = search_public_sources(
            prompt,
            preferences["enabled_sources"],
            preferences["max_results_per_source"],
            allow_preprints=allow_preprints,
            **options,
        )
        references = _discovery_references(
            discovery,
            preferences["enabled_sources"],
            preferences["max_results_per_source"],
        )
    except (OSError, TypeError, ValueError):
        failed = True
        discovery = {
            "references": [],
            "source_statuses": [],
            "caveats": [
                "Public reference discovery was unavailable or failed validation; "
                "no additional references were saved."
            ],
        }
        references = []
    discovery_note = {
        "selected_sources": preferences["enabled_sources"],
        "reference_count": len(references),
        "source_statuses": _safe_discovery_statuses(
            discovery, references, preferences["enabled_sources"]
        ),
        "caveats": [
            *_DISCOVERY_CAVEATS,
            *(
                [
                    "Public reference discovery was unavailable or failed validation; "
                    "no additional references were saved."
                ]
                if failed
                else []
            ),
        ],
        "is_material_evidence": False,
        "used_for_ranking": False,
        "full_text_read": False,
    }
    # Display statuses also label missing observations unavailable. Scheduling
    # uses only explicit current-run outages from the approved adapters.
    raw_statuses = discovery.get("source_statuses", [])
    confirmed_unavailable = [
        source
        for source in ("europe_pmc", "openalex")
        if source in preferences["enabled_sources"]
        and not any(row["source_id"] == source for row in references)
        and isinstance(raw_statuses, list)
        and {
            row.get("status")
            for row in raw_statuses
            if isinstance(row, dict)
            and row.get("source_id") == source
            and isinstance(row.get("status"), str)
        }
        == {"unavailable"}
    ]
    if confirmed_unavailable:
        discovery_note["confirmed_unavailable_sources"] = confirmed_unavailable
    return _attach_public_discovery(outcome, references, discovery_note)


def _missing_attribute_requests(
    outcome: dict, config: AppConfig, *, priority_criteria=()
) -> list[dict]:
    """Search targets are selected preferences plus adapter-owned
    identities."""
    result = outcome["result"]
    weights = result.get("ranking", {}).get("weights", config.to_dict()["ranking"])
    candidates = result.get("candidates", [])
    # These leads are produced by the parent-owned candidate validator, not by
    # prompt text. Literal names may guide follow-up without asserting a phase.
    leads = result.get("candidate_leads", []) if not candidates else []
    requests = []
    for attribute, weight in sorted(
        weights.items(),
        key=lambda item: (item[0] not in priority_criteria, -item[1], item[0]),
    ):
        if weight <= 0:
            continue
        missing = [
            candidate
            for candidate in candidates
            if attribute in candidate.get("missing_selected_criteria", [])
        ]
        if candidates and not missing:
            continue
        requests.append(
            {
                "attribute_id": attribute,
                "candidate_ids": [candidate["material_id"] for candidate in missing]
                or [lead["id"] for lead in leads],
                "candidate_identities": [
                    {
                        "candidate_id": candidate["material_id"],
                        "names": [candidate["formula"]],
                    }
                    for candidate in missing
                ]
                or [
                    {"candidate_id": lead["id"], "names": [lead["name"]]}
                    for lead in leads
                ],
                "formulas": list(
                    dict.fromkeys(candidate["formula"] for candidate in missing)
                ),
            }
        )
    # Reserve one of the bounded follow-up queries for a selected, missing
    # stability scope. Other properties retain their weight order; unsupported
    # high-weight attributes must not crowd stability out of every request.
    stability_order = ("ambient_phase_stability", "operational_stability", "stability")
    stability_requests = [
        request for request in requests if request["attribute_id"] in stability_order
    ]
    if stability_requests:
        priority = min(
            stability_requests,
            key=lambda request: (
                request["attribute_id"] not in priority_criteria,
                -weights[request["attribute_id"]],
                stability_order.index(request["attribute_id"]),
            ),
        )
        requests.remove(priority)
        requests.insert(0, priority)
    return requests


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


def _add_attribute_research(
    outcome: dict,
    prompt: str,
    config: AppConfig,
    preferences: dict,
    research_controls: dict | None = None,
    *,
    semantic_scope: dict | None = None,
    priority_criteria: tuple[str, ...] = (),
) -> dict:
    """Skim approved open literature for source-bound candidate
    identities.

    Extracted passages are attributed review leads. No value is parsed
    into a candidate, phase-joined, or promoted into a ranking property
    by this stage.
    """
    if outcome["stage"] == "blocked":
        return outcome
    requests = _missing_attribute_requests(
        outcome, config, priority_criteria=priority_criteria
    )
    if not requests:
        outcome["result"]["attribute_research"] = {
            "status": "not_needed",
            "attributes": [],
            "sources": [],
            "used_for_ranking": False,
            "caveats": [
                "All selected criteria have repository evidence in the "
                "shortlisted records."
            ],
        }
        return outcome
    if not preferences["search_public_references"] or (
        research_controls is not None and not research_controls["literature_followup"]
    ):
        outcome["result"]["attribute_research"] = {
            "status": "disabled",
            "attributes": [],
            "sources": [],
            "used_for_ranking": False,
            "caveats": [
                "Targeted public literature follow-up is disabled by the "
                "selected research settings."
            ],
        }
        return outcome
    from labcat.property_research import find_attribute_evidence

    report_progress("literature")
    try:
        unavailable = (
            outcome["result"]
            .get("public_discovery", {})
            .get("confirmed_unavailable_sources", [])
        )
        unavailable = tuple(
            source
            for source in ("europe_pmc", "openalex")
            if isinstance(unavailable, (list, tuple))
            and source in unavailable
            and source in preferences["enabled_sources"]
            and not any(row.get("source_id") == source for row in outcome["sources"])
        )
        followup = find_attribute_evidence(
            prompt,
            requests,
            selected_sources=preferences["enabled_sources"],
            max_results_per_source=preferences["max_results_per_source"],
            **({"semantic_scope": semantic_scope} if semantic_scope else {}),
            **({"unavailable_sources": unavailable} if unavailable else {}),
            **(
                {
                    "query_budget": research_controls["max_attribute_queries"],
                    "article_budget": research_controls["max_article_downloads"],
                    "seconds_budget": research_controls["literature_timeout_seconds"],
                    "allow_preprints": research_controls["allow_preprints"],
                }
                if research_controls is not None
                else {}
            ),
        )
        if (
            not isinstance(followup.get("sources"), list)
            or len(followup["sources"]) > 6
        ):
            raise ValueError("Attribute follow-up exceeded its shared source limit.")
        references = _discovery_references(
            {"references": followup["sources"]},
            [
                source
                for source in ("europe_pmc", "openalex")
                if source in preferences["enabled_sources"]
            ],
            6,
        )
        by_url = {}
        for source in references:
            if source["url"] in by_url and source != by_url[source["url"]]:
                raise ValueError("Conflicting targeted source snapshots.")
            by_url[source["url"]] = source
            if source["source_id"] == "openalex":
                if _targeted_abstract_document(source) is None:
                    raise ValueError("Targeted source has no safe approved abstract.")
                if research_controls and not research_controls["allow_preprints"]:
                    metadata = source["metadata"]
                    if metadata.get("record_type") == "preprint" or metadata.get(
                        "version"
                    ) not in {"publishedVersion", "acceptedVersion"}:
                        raise ValueError("Preprints were not selected.")
        references = list(by_url.values())
        note = _validated_attribute_note(followup, requests, references)
        # Validate the complete reply before touching retained evidence. Index
        # document IDs identify works, not text versions: an earlier abstract
        # used for admission must never be replaced by a later search snapshot.
        staged_sources = deepcopy(outcome["sources"])
        existing = {source["url"]: source for source in staged_sources}
        retained, discarded = [], set()
        for source in references:
            if source["source_id"] == "openalex" and source["url"] in existing:
                original = existing[source["url"]]
                if _targeted_abstract_document(original) is None:
                    discarded.add(source["url"])
                    continue
                source = original
            retained.append(source)
        references = retained
        note["source_urls"] = [source["url"] for source in references]
        for attribute in note["attributes"]:
            if "abstract_source_urls" in attribute:
                attribute["abstract_source_urls"] = [
                    url
                    for url in attribute["abstract_source_urls"]
                    if url not in discarded
                ]
                if (
                    attribute["status"] == "abstract_review_leads"
                    and not attribute["abstract_source_urls"]
                ):
                    attribute["status"] = "no_passages"
        for source in references:
            source = deepcopy(source)
            if source["source_id"] == "openalex":
                if source["url"] not in existing:
                    staged_sources.append(source)
                    existing[source["url"]] = source
                continue
            source.setdefault("metadata", {})["full_text_provenance"] = deepcopy(
                source.get("provenance", {})
            )
            # Body documents have independent IDs. Never replace an earlier
            # abstract/title used to admit a candidate with later search text.
            passages = []
            for attribute in note["attributes"]:
                for passage in attribute["passages"]:
                    if (
                        passage["source_url"] != source["url"]
                        or not passage["candidate_ids"]
                    ):
                        continue
                    selected = {
                        key: deepcopy(passage[key])
                        for key in (
                            "text",
                            "locator",
                            "section",
                            "article_id",
                            "response_sha256",
                            "candidate_ids",
                            "paragraph_complete",
                        )
                    }
                    if selected not in passages:
                        passages.append(selected)
            source["metadata"]["assessment_passages"] = passages[:9]
            if source["url"] in existing:
                original = existing[source["url"]].setdefault("metadata", {})
                for key in (
                    "full_text_read",
                    "full_text_scope",
                    "full_text_provenance",
                    "content_screen",
                    "assessment_passages",
                ):
                    if key in source["metadata"]:
                        original[key] = deepcopy(source["metadata"][key])
            else:
                staged_sources.append(source)
                existing[source["url"]] = source
        outcome["sources"] = staged_sources
        outcome["result"]["attribute_research"] = note
        if references and not outcome["result"].get("candidates"):
            summary = (
                "No scored material shortlist was generated. Targeted follow-up "
                f"reviewed {len(references)} public references for missing "
                "attribute evidence; retained excerpts require context review."
            )
            outcome["result"]["summary"] = summary
            outcome["answer"] = summary
    except (OSError, TypeError, ValueError, KeyError):
        outcome["result"]["attribute_research"] = {
            "status": "unavailable",
            "attributes": [],
            "used_for_ranking": False,
            "caveats": [
                "Targeted public literature follow-up was unavailable or failed "
                "validation. Missing values remain unfilled."
            ],
        }
    return outcome


def _require_research_setup(connections, controls, intake):
    """Admit safety refusals locally; otherwise require the selected
    model."""
    if intake["status"] == "refused":
        return
    if connections is None:
        raise SetupRequired(
            "Connect and verify a language-model account in setup before research. "
            "For the CLI, use --server with the running application or supply "
            "--connections WORKSPACE_PATH."
        )
    connections.apply_default_account(controls["default_model_account_id"])
    connections.setup.require_ready()
