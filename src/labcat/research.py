"""Shared orchestration: bounded intent, public evidence, deterministic
reports."""

import json
import re
from collections import Counter
from copy import deepcopy
from urllib.parse import urlsplit

from labcat.config import AppConfig
from labcat.connections import ConnectionManager
from labcat.developer_settings import defaults as default_controls
from labcat.developer_settings import effective_sources, validate_controls
from labcat.extended_discovery import valid_wikipedia_url
from labcat.models import ModelBusy, ModelError
from labcat.onboarding import SetupRequired
from labcat.research_progress import ResearchProgress, report_progress
from labcat.source_preferences import (
    default_source_preferences,
    validate_source_preferences,
)

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


def research(
    prompt: str,
    config: AppConfig,
    *,
    connections: ConnectionManager | None = None,
    context: dict | None = None,
    ranking_profile: dict | None = None,
    ranking_selection: dict | None = None,
    source_preferences: dict | None = None,
    research_controls: dict | None = None,
) -> dict:
    """Run without accepting caller-supplied scientific records or
    arbitrary tools."""
    from labcat.intake import assess, decision
    from labcat.intake import outcome as intake_outcome
    from labcat.science import render_research, run_research

    report_progress("intake")
    # Refuse prohibited intent before transmitting it to a provider or source API.
    controls = validate_controls(
        default_controls() if research_controls is None else research_controls
    )
    execution_preferences = {
        "presentation": config.to_dict()["presentation"],
        "ranking_profile": deepcopy(ranking_profile),
        "ranking_selection": deepcopy(ranking_selection),
        "profile_labels_are_user_preferences": True,
        "research_controls": controls,
    }
    if not controls["include_history"]:
        context = None
    intake, effective_prompt = assess(prompt, context=context)
    _require_research_setup(connections, controls, intake)
    if intake["status"] == "refused":
        outcome = intake_outcome(intake)
        outcome["result"]["execution"] = {
            "provider": "none",
            "mode": "not_run",
            "warning": None,
            "context_is_evidence": False,
            **execution_preferences,
        }
        return render_research(outcome, config)
    semantic_assessment = connections.agent.uses_goose and intake["reason_code"] in {
        "materials_scope_needed",
        "research_details_needed",
    }
    if intake["status"] == "clarification_required" and not semantic_assessment:
        outcome = intake_outcome(intake)
        outcome["result"]["execution"] = {
            "provider": connections.status()["profile"]["provider"],
            "requested_model": connections.status()["profile"]["model"],
            "mode": "not_run",
            "context_is_evidence": False,
            **execution_preferences,
        }
        return outcome
    from labcat.research_context import material_hints

    prior_material_ids = material_hints(context, prompt)
    prompt = effective_prompt
    source_config = validate_source_preferences(
        default_source_preferences()
        if source_preferences is None
        else source_preferences
    )
    source_config = effective_sources(source_config, controls)
    # Optional source credentials are checked at retrieval, independently of
    # model readiness. One unavailable API must not stop other public sources.
    if connections is not None and connections.agent.uses_goose:
        from labcat.agent_tools import ResearchToolSession
        from labcat.credentials import ConnectionBusy, ConnectionError

        session = ResearchToolSession(
            prompt,
            config,
            ranking_profile=ranking_profile,
            ranking_selection=ranking_selection,
            source_preferences=source_config,
            research_controls=controls,
            key_supplier=lambda: _public_api_key(
                connections, source_config["materials_project_mode"]
            ),
            source_observer=connections.observe_source_result,
            prior_material_ids=prior_material_ids,
        )
        requested_profile = connections.status()["profile"]
        provider = requested_profile["provider"]
        agent_run = None
        interrupted = False
        attempt = None
        failure_code = None
        worker_rejections = None
        try:
            report_progress("model")
            agent_run = connections.agent.run(prompt, context, session)
            if (
                agent_run.get("status") == "stopped_after_report"
                and not session.report_retained
            ):
                raise ModelError(
                    "The model worker reported an unconfirmed report stop."
                )
        except (ModelBusy, ConnectionBusy):
            # No provider request ran. A metadata refresh is not a failed login.
            raise
        except (ModelError, ConnectionError) as error:
            from labcat.goose_runtime import (
                FAILURE_CODES,
                safe_worker_rejection_diagnostics,
            )

            candidate_attempt = getattr(error, "research_attempt", None)
            if isinstance(candidate_attempt, dict) and candidate_attempt == {
                "provider": provider,
                "model": requested_profile["model"],
            }:
                attempt = dict(candidate_attempt)
            code = getattr(error, "failure_code", None)
            if isinstance(code, str) and code in FAILURE_CODES:
                failure_code = code
            diagnostics = getattr(error, "worker_rejection_diagnostics", None)
            if diagnostics is not None:
                try:
                    worker_rejections = safe_worker_rejection_diagnostics(diagnostics)
                except ValueError:
                    pass  # Untrusted diagnostic content cannot enter the report.
            connections.setup.invalidate(
                "The model request failed. Check the connection and available quota."
            )
            if not session.can_complete_without_model:
                raise ModelError(
                    "The language-model request failed. No report was saved and no "
                    "automatic retry was made. Check the connection and quota."
                ) from None
            # The request already passed both intake checks. Complete only the
            # fixed, selected public-source stages; no model retry or generated
            # facts are needed to retain approved evidence and render the report.
            interrupted = True
        outcome = session.finalize()
        if interrupted:
            if outcome["stage"] == "complete":
                outcome["stage"] = outcome["result"]["stage"] = "partial"
            outcome["result"]["execution"].update(
                provider=provider,
                mode="goose",
                model_interrupted=True,
                completion_version="bounded-recovery-v2",
                requested_model=requested_profile["model"],
                attempted_model=attempt["model"] if attempt else None,
                failure_code=failure_code,
                warning=(
                    "Model-led research stopped before completion. The server "
                    "completed the configured public-source stages without "
                    "another model call. Search coverage may be incomplete."
                ),
            )
            if worker_rejections is not None:
                outcome["result"]["execution"][
                    "worker_rejection_diagnostics"
                ] = worker_rejections
        else:
            outcome["result"]["execution"].update(
                provider=agent_run["provider"],
                mode="goose",
                warning=None,
                agent=agent_run,
                requested_model=requested_profile["model"],
            )
            if agent_run.get("status") == "stopped_after_report":
                outcome["result"]["execution"].update(
                    model_stopped_after_report=True,
                    stop_reason="server_report_retained",
                )
        return render_research(outcome, config)
    requested_profile = connections.status()["profile"]
    provider = requested_profile["provider"]
    try:
        report_progress("model")
        plan = connections.plan(prompt, context=context).to_dict()
    except ModelError:
        connections.setup.invalidate(
            "The model request failed. Check the connection and available quota."
        )
        raise ModelError(
            "The language-model request failed. No report was saved and no "
            "automatic retry was made. Check the connection and quota."
        ) from None
    if plan["task"] == "unsupported":
        outcome = intake_outcome(
            decision("clarification_required", "model_scope_uncertain")
        )
        outcome["result"]["execution"] = {
            "provider": provider,
            "mode": "model",
            "requested_model": requested_profile["model"],
            "context_is_evidence": False,
            **execution_preferences,
        }
        return outcome
    key = _public_api_key(connections, source_config["materials_project_mode"])
    from labcat.perovskite_discovery import (
        discovery_article_budget,
        remaining_literature_controls,
    )

    discovery = None
    reserved_articles = 0
    if source_config["search_public_references"]:
        reserved_articles = discovery_article_budget(
            prompt, source_config["enabled_sources"], controls
        )
        discovery = _add_public_discovery(
            {"stage": "partial", "answer": "", "sources": [], "result": {}},
            prompt,
            source_config,
            allow_preprints=controls["allow_preprints"],
            discovery_article_budget=reserved_articles,
        )
    try:
        outcome = run_research(
            prompt,
            config,
            mp_api_key=key,
            materials_project_mode=source_config["materials_project_mode"],
            plan=plan,
            importance=ranking_profile["importance"] if ranking_profile else None,
            material_class=_material_class_hint(ranking_profile, ranking_selection),
            application=ranking_profile.get("application") if ranking_profile else None,
            minimum_band_gap_ev=(
                ranking_profile.get("minimum_band_gap_ev") if ranking_profile else None
            ),
            target_band_gap_ev=(
                ranking_profile.get("target_band_gap_ev") if ranking_profile else None
            ),
            band_gap_tolerance_ev=(
                ranking_profile.get("band_gap_tolerance_ev")
                if ranking_profile
                else None
            ),
            allow_hybrid3="hybrid3" in source_config["enabled_sources"],
            discovery_references=discovery["sources"] if discovery else [],
            allow_nomad="nomad" in source_config["enabled_sources"],
            allow_public_dielectric="public_dielectric"
            in source_config["enabled_sources"],
            prior_material_ids=prior_material_ids,
        )
    except Exception:
        from labcat.science import _blocked

        outcome = _blocked("The material-property retrieval stage was unavailable.")
        outcome["result"]["failure_stage"] = "material_retrieval"
    if (
        discovery is not None
        and discovery.get("sources")
        and outcome.get("result", {}).get("failure_stage") == "material_retrieval"
    ):
        from labcat.science import _reference_only

        outcome = _reference_only(
            "The material-property retrieval stage was unavailable. Healthy "
            "public-source results are retained for screening.",
            config,
            plan,
            ranking_profile["importance"] if ranking_profile else None,
        )
    try:
        connections.observe_source_result(outcome, key)
    except Exception:
        outcome["result"].setdefault("limitations", []).append(
            "Source connection status could not be refreshed. Retrieved "
            "evidence remains available in this report."
        )
    outcome["result"]["execution"] = {
        "provider": provider,
        "mode": "model",
        "warning": None,
        "context_is_evidence": False,
        **execution_preferences,
        "source_preferences": source_config,
    }
    if discovery is not None:
        outcome = _attach_public_discovery(
            outcome, discovery["sources"], discovery["result"]["public_discovery"]
        )
    if outcome["stage"] != "blocked" and discovery is not None:
        from labcat.science.candidate_leads import (
            discovery_documents,
            literal_formula_proposals,
            validate_candidate_leads,
        )

        references = discovery["sources"]
        documents = discovery_documents(references)
        outcome["result"]["candidate_leads"] = validate_candidate_leads(
            literal_formula_proposals(documents),
            documents,
            references,
            importance=ranking_profile["importance"] if ranking_profile else None,
        )
    followup = deepcopy(outcome)
    try:
        _add_attribute_research(
            followup,
            prompt,
            config,
            source_config,
            remaining_literature_controls(controls, reserved_articles),
        )
        outcome = followup
    except Exception:
        outcome["result"].setdefault("limitations", []).append(
            "Optional attribute follow-up was unavailable. Earlier retrieved "
            "evidence and candidate screening are retained."
        )
    if outcome["stage"] != "blocked" and discovery is not None:
        _attach_preliminary_screening(
            outcome,
            ranking_profile or {"importance": config.to_dict()["ranking"]},
            references=references,
            documents=documents,
        )
    return render_research(outcome, config)


class ResearchWorkflow:
    """Avoid holding a database write lock across retrieval or model
    requests."""

    def __init__(
        self,
        store,
        connections: ConnectionManager,
        ranking_profiles=None,
        source_preferences=None,
        developer_settings=None,
        structures=None,
    ):
        self.store = store
        self.connections = connections
        self.ranking_profiles = ranking_profiles
        self.source_preferences = source_preferences
        self.developer_settings = developer_settings
        self.structures = structures
        self.progress = ResearchProgress()

    def respond(
        self,
        chat_id: str,
        content: str,
        config: AppConfig,
        project_id: str | None = None,
        ranking_profile_id: str | None = None,
        run_id: str | None = None,
        search_reference_structures: bool = True,
    ):
        prepared = {}

        def prepare_submission():
            # Validate and snapshot after reserving this chat, after any prior run
            # completes and before naming the chat or publishing a running task.
            if type(search_reference_structures) is not bool:
                raise ValueError(
                    "Reference structure search must be enabled or disabled."
                )
            scope, context = self.store.research_inputs(chat_id, project_id)
            from labcat.research_context import select_profile

            controls = (
                self.developer_settings.load() if self.developer_settings else None
            )
            profile, selection = (
                select_profile(
                    self.ranking_profiles,
                    ranking_profile_id,
                    content,
                    context,
                    enabled=controls is None or controls["include_history"],
                )
                if self.ranking_profiles
                else (None, None)
            )
            if ranking_profile_id is not None and self.ranking_profiles is None:
                from labcat.ranking_profiles import RankingProfileNotFound

                raise RankingProfileNotFound("Ranking profiles are unavailable.")
            source_config = (
                self.source_preferences.load()
                if self.source_preferences
                else default_source_preferences()
            )
            prepared.update(
                scope=scope,
                context=context,
                profile=profile,
                selection=selection,
                source_config=source_config,
                controls=controls,
                search_reference_structures=search_reference_structures,
            )
            # A setup rejection is not an accepted submission: check the same
            # refusal-aware gate before persisting a title or publishing a run.
            from labcat.intake import assess

            admission_controls = validate_controls(
                default_controls() if controls is None else controls
            )
            intake, _ = assess(
                content,
                context=context if admission_controls["include_history"] else None,
            )
            _require_research_setup(self.connections, admission_controls, intake)
            self.store.name_submitted_chat(chat_id, content, project_id)

        with self.progress.track(chat_id, run_id, before_start=prepare_submission):
            report_progress("profile")
            return self._respond(chat_id, content, config, **prepared)

    def _respond(
        self,
        chat_id,
        content,
        config,
        *,
        scope,
        context,
        profile,
        selection,
        source_config,
        controls,
        search_reference_structures,
    ):
        outcome = research(
            content,
            config,
            connections=self.connections,
            context=context,
            ranking_profile=profile,
            ranking_selection=selection,
            source_preferences=source_config,
            research_controls=controls,
        )
        outcome.setdefault("result", {}).setdefault("execution", {})[
            "search_reference_structures"
        ] = search_reference_structures
        report_progress("saving")
        detail = self.store.append_research(
            chat_id,
            scope,
            content,
            outcome,
            submitted_at=self.progress.snapshot(chat_id)["started_at"],
        )
        if (
            search_reference_structures
            and self.structures is not None
            and outcome.get("stage") in {"complete", "partial"}
        ):
            response = next(
                (
                    message
                    for message in reversed(detail["messages"])
                    if message["role"] == "assistant"
                ),
                {},
            )
            report_id = response.get("report_id")
            if report_id:
                report_progress("structures")
                try:
                    self.structures.discover_references(
                        chat_id,
                        report_id,
                        enabled_sources=source_config["enabled_sources"],
                        materials_project_mode=source_config["materials_project_mode"],
                    )
                except Exception:
                    # Structure discovery is optional. The report is already saved;
                    # an unavailable adapter must not turn it into a failed request.
                    import logging

                    logging.getLogger(__name__).warning(
                        "Optional reference structure discovery could not complete."
                    )
        return detail
