"""Public material evidence screening with constrained requests and
cited reports."""

import json
import math
import re
import time
from copy import deepcopy

from labcat.config import AppConfig
from labcat.research_progress import report_progress

from .preferences import (
    composition_key,
    derive_search_filters,
    matches_composition_scope,
    scalar_scope_resolved,
    source_search_context,
    supports_bulk_search,
    validate_formula,
)
from .ranking import EXCLUDED_ELEMENTS, SHORTLIST_SIZE, rank_records
from .reporting import render_reports
from .sources import MP_DOCS_URL, PAPER_URL, SourceError, retrieve_live
from .sources import load_snapshot as load_snapshot

PLAN_CHOICES = {
    "task": ("materials_triage", "oxide_dielectric_triage", "unsupported"),
    "stability": ("prefer_stable", "any"),
    "band_gap": ("prefer_wide", "any"),
    "element_screen": ("prefer_lower_concern", "any"),
    "simplicity": ("prefer_simple", "any"),
    "evidence": ("public_only",),
}


def retrieve_nomad(filters=None):
    """Load the keyless adapter lazily, keeping its source boundary
    independent."""
    from .nomad import retrieve_live

    return retrieve_live(filters)


def retrieve_public_dielectric(filters=None):
    """Read the full approved public release without a bundled candidate
    list."""
    from .dielectric import retrieve_live

    return retrieve_live(filters)


def retrieve_hybrid3(filters=None, *, query="", system_ids=()):
    """Read public hybrid-material datasets through their own validation
    boundary."""
    from .hybrid3 import retrieve_live

    return retrieve_live(filters, query=query, system_ids=system_ids)


def request_violation(prompt: str) -> str | None:
    """Basic intent checks complement absent unsafe tools; this is not a
    sanitizer."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20_000:
        return (
            "Provide a nonempty materials research request within the supported length."
        )
    from labcat.intake import harmful_manufacture, negated_action, normalized

    if harmful_manufacture(prompt):
        return (
            "Requests to select, manufacture or improve materials for weapons "
            "or for harming people are not supported."
        )
    # Line wrapping cannot separate a prohibited verb from its object.
    text = " ".join(normalized(prompt).split())
    # New privacy checks bind an access action to a resource, rather than
    # treating "restricted" or "unpublished" as scientific taboo words.
    # Do not cross a public-source object, a negation or another action to
    # borrow a later private noun ("use public papers, not private notes").
    resource = (
        r"(?:files?|notes?|notebooks?|records?|repositories|repository|"
        r"databases?|datasets?|data|measurements?|results?|reports?|documents?)"
    )
    access_context = (
        r"(?:\s+(?:to|for|in|through|inside|within|from|the|a|an|any|all|these|"
        r"those|my|your|our|their|other|saved|stored|current|local|workspace|"
        r"[\w-]+(?:['’]s|s['’]))){0,8}\s+"
    )
    resource_modifiers = (
        r"(?:\s+(?:lab(?:oratory)?|research|scientific|materials?|project|"
        r"workspace|company|team|personal|experimental|source|raw)){0,4}\s+"
    )
    private_resource = (
        rf"(?:private|restricted|confidential|non[ -]public){resource_modifiers}"
        rf"{resource}|unpublished\s+(?:lab(?:oratory)?|internal|personal)"
        rf"{resource_modifiers}{resource}|unpublished\s+(?:notes?|notebooks?)|"
        rf"internal\s+(?:company|team|workspace|lab(?:oratory)?)"
        rf"{resource_modifiers}{resource}"
    )
    access_action = (
        r"(?:access(?:ing)?|read(?:ing)?|use|using|open(?:ing)?|fetch(?:ing)?|"
        r"retrieve|retrieving|scrape|scraping|search(?:ing)?|inspect(?:ing)?|"
        r"consult(?:ing)?|query(?:ing)?|scan(?:ning)?|connect(?:ing)?)"
    )
    disclosure_action = (
        r"(?:attach(?:ing)?|append(?:ing)?|includ(?:e|ing)|transmit(?:ting)?|"
        r"export(?:ing)?|past(?:e|ing)|leak(?:ing)?|emit(?:ting)?)"
    )
    policy_action = (
        r"(?:replac(?:e|ing)|suspend(?:ing)?|relax(?:ing)?|waiv(?:e|ing)|"
        r"lift(?:ing)?|remov(?:e|ing)|drop(?:ping)?)"
    )
    patterns = (
        r"\b(?:ignore|disregard|override|disable|bypass)\b.{0,60}\b"
        r"(?:instructions?|rules?|polic(?:y|ies)|constraints?|safeguards?|"
        r"guardrails?|paywalls?|authentication)\b",
        r"\b(?:access|read|use|open|fetch|retrieve|scrape)\b.{0,40}\b"
        r"(?:private|paywalled|secret|credentials?|subscription[ -]only|"
        r"behind (?:a |the )?(?:paywall|subscription wall)|"
        r"closed[ -](?:sources?|data(?:bases?)?|records?|repositories))\b",
        r"\b(?:reveal|send|upload|print|exfiltrate|forward|read|show|copy|"
        r"access|retrieve)\b.{0,90}\b"
        r"(?:passwords?|secrets?|credentials?|api[ _-]?keys?|"
        r"access[ _-]?tokens?|refresh[ _-]?tokens?|"
        r"environment[ _-]?variables?|private[ _-]?files?)\b",
        r"\b(?:invent|fabricate|falsify)\b.{0,40}\b"
        r"(?:evidence|citations?|data|values?|properties|results?)\b",
        r"\b(?:trigger|perform|start|execute|schedule)\b.{0,40}\b"
        r"(?:wet[ -]?lab|synthesis|experiments?|instruments?)\b",
        r"\b"
        + access_action
        + r"\b"
        + access_context
        + r"(?:"
        + private_resource
        + r")\b",
        # Explicitly transmitting credential values differs from discussing
        # public documentation about credential storage or secure telemetry.
        r"\b"
        + disclosure_action
        + r"\b"
        + r"(?:\s+(?:the|my|your|our|their|saved|stored|workspace|current|provider|"
        r"account|login|raw|local|personal)){0,5}\s+"
        r"(?:passwords?|secrets?|credentials?|api[ _-]?keys?|access[ _-]?tokens?|"
        r"refresh[ _-]?tokens?|environment[ _-]?variables?|private[ _-]?files?)\b",
        # Authority claims do not permit changing fixed access safeguards.
        # Ordinary materials replacement or preference changes remain valid.
        r"\b"
        + policy_action
        + r"\b"
        + r"(?:\s+(?:the|your|our|these|all|current|existing|mandatory)){0,3}\s+"
        r"(?:fixed|system|safety|security|access|public[ -]only|research)"
        r"(?:\s+(?:access|data|source|research|safety|security|system|only|fixed))"
        r"{0,3}\s+(?:rules?|polic(?:y|ies)|restrictions?|constraints?|boundaries|"
        r"safeguards?|guardrails?)\b",
    )
    verbs = (
        r"\b(?:ignore|disregard|override|disable|bypass|access|read|use|open|fetch|"
        r"retrieve|scrape|invent|fabricate|falsify|trigger|perform|start|"
        r"execute|schedule|reveal|send|upload|print|exfiltrate|forward|show|copy|"
        r"search|inspect|consult|query|scan|connect|attach|append|include|transmit|"
        r"export|paste|leak|emit|replace|suspend|relax|waive|lift|remove|drop|"
        + access_action
        + r"|"
        + disclosure_action
        + r"|"
        + policy_action
        + r")\b"
    )
    # A verb in a benign sentence must not borrow an object from a separate
    # prohibition ("Use public data. Do not reveal credentials."). Line wrapping
    # was collapsed above; each later sentence still receives its own check.
    statements = re.split(r"[.!?;](?:\s+|$)", text)
    if any(
        not negated_action(statement[: match.start()])
        and any(re.match(pattern, statement[match.start() :]) for pattern in patterns)
        for statement in statements
        for match in re.finditer(verbs, statement)
    ):
        return (
            "This request asks to cross a fixed research boundary. Only cited "
            "public-data screening is available; no private, paywalled, wetlab, "
            "or fabricated-evidence actions are provided."
        )
    return None


def _validate_plan(plan: dict | None) -> dict:
    if plan is None:
        return {key: choices[0] for key, choices in PLAN_CHOICES.items()}
    if not isinstance(plan, dict) or set(plan) != set(PLAN_CHOICES):
        raise ValueError(
            "Unsupported planner fields; no facts, URLs or tools accepted."
        )
    if any(
        not isinstance(plan[key], str) or plan[key] not in choices
        for key, choices in PLAN_CHOICES.items()
    ):
        raise ValueError("Unsupported planner preference value.")
    return plan.copy()


def _blocked(reason: str) -> dict:
    return {
        "stage": "blocked",
        "answer": reason,
        "pi_summary": reason,
        "technical_audit": reason + "\nNo scientific records were reported.\n",
        "sources": [],
        "result": {"stage": "blocked", "candidates": [], "reason": reason},
    }


def _sources(candidates: list[dict], comparison_records=None) -> list[dict]:
    from .formula_display import display_formula

    sources = []
    retained = {}
    for candidate in [*candidates, *(comparison_records or [])]:
        source_id = "material:" + candidate["material_id"]
        candidate["source_ids"] = [source_id]
        if candidate["material_id"] in retained:
            if (
                retained[candidate["material_id"]]["provenance"]
                != candidate["provenance"]
            ):
                raise ValueError("Conflicting retained evidence identity.")
            continue
        retained[candidate["material_id"]] = candidate
        sources.append(
            {
                "source_id": source_id,
                "record_id": candidate["material_id"],
                "title": display_formula(candidate["formula"])
                + " ("
                + candidate["material_id"]
                + ") — public material record",
                "url": candidate["provenance"]["source_url"],
                "source_name": (
                    "Materials Project / public dielectric snapshot"
                    if candidate["source_mode"] == "public_snapshot"
                    else (
                        "NOMAD public archive"
                        if candidate["source_mode"] == "live_nomad"
                        else (
                            "Public dielectric dataset (historical calculations)"
                            if candidate["source_mode"] == "live_public_dielectric"
                            else (
                                "HybriD³ public datasets"
                                if candidate["source_mode"] == "live_hybrid3"
                                else "Materials Project API"
                            )
                        )
                    )
                ),
                "access_scope": "public",
                "provenance_status": "verified",
                "provenance": candidate["provenance"],
            }
        )
    if any(
        candidate["source_mode"] in {"public_snapshot", "live_public_dielectric"}
        for candidate in retained.values()
    ):
        sources.append(
            {
                "source_id": "methodology",
                "title": (
                    "Petousis et al. (2017): dielectric data and calculation caveats"
                ),
                "url": PAPER_URL,
                "source_name": "Scientific Data (open access)",
                "access_scope": "public",
                "provenance_status": "verified",
            }
        )
    if any(
        candidate["source_mode"] == "live_materials_project"
        for candidate in retained.values()
    ):
        sources.append(
            {
                "source_id": "mp-api-method",
                "title": "Materials Project: query fields and calculation origins",
                "url": MP_DOCS_URL,
                "source_name": "Materials Project documentation",
                "access_scope": "public",
                "provenance_status": "verified",
            }
        )
    return sources


def render_research(response: dict, config: AppConfig) -> dict:
    """Compile written views; full structured evidence remains in
    ``result``."""
    from labcat.intake import decision

    intake = response["result"].setdefault("intake", decision("accepted", "accepted"))
    if intake["status"] != "accepted":
        return response
    report_progress("formatting")
    summary, overview = render_reports(response["result"], config, response["sources"])
    return {**response, "pi_summary": summary, "technical_audit": overview}


def _reference_only(
    reason,
    config,
    selected_plan,
    importance,
    retrieval=None,
    ranking_details=None,
    comparison_records=None,
    review_records=None,
):
    if ranking_details is None:
        _, ranking = rank_records([], config, importance=importance)
    else:
        ranking = dict(ranking_details)
    ranking.update(status="not_run", reason=reason)
    result = {
        "stage": "partial",
        "summary": reason,
        "reason": reason,
        "candidates": [],
        "ranking": ranking,
        "retrieval": retrieval
        or {
            "mode": "no_material_evidence",
            "records_retrieved": 0,
            "coverage": reason,
        },
        "limitations": [
            "No material properties were filled from prompts, model memory, "
            "or a saved candidate list.",
            "Public references may guide follow-up; they are not "
            "automatically material-property evidence.",
        ],
        "plan": selected_plan,
    }
    if comparison_records:
        result["comparison_records"] = comparison_records
    if review_records:
        result["review_records"] = review_records
    return render_research(
        {
            "stage": "partial",
            "answer": reason,
            "sources": _sources(review_records or [], comparison_records),
            "result": result,
        },
        config,
    )


def _repository_response(
    retrieve, filters, deadline, *, preserve_composition_scope=False
):
    """Isolate one approved adapter before its batch enters shared
    ranking.

    Adapters remain responsible for scientific validation. These structural
    checks prevent a broken response from invalidating other source batches.
    Exception text is deliberately discarded: it can contain request secrets or
    remote content. Configuration and request-policy checks happen upstream.
    """
    from .reporting import _comparison_record, approved_citation_url
    from .retrieval_budget import repository_budget

    try:
        query = {
            key: value
            for key, value in filters.items()
            if key != "composition_scope" or preserve_composition_scope
        }
        with repository_budget(seconds=max(0, deadline - time.monotonic())):
            response = retrieve(query)
        if not isinstance(response, (tuple, list)) or len(response) != 2:
            raise ValueError("Invalid adapter response.")
        rows, metadata = response
        if (
            not isinstance(rows, list)
            or len(rows) > 1056
            or not isinstance(metadata, dict)
        ):
            raise ValueError("Invalid adapter response shape.")
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid adapter record.")
            identity = row.get("material_id")
            if (
                not isinstance(identity, str)
                or re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", identity) is None
                or identity in seen
                or not isinstance(row.get("elements"), list)
                or row["elements"] != validate_formula(row.get("formula"))
                or row.get("source_mode")
                not in {
                    "live_materials_project",
                    "live_nomad",
                    "live_public_dielectric",
                    "live_hybrid3",
                    "public_snapshot",
                }
                or not isinstance(row.get("method"), str)
                or not 1 <= len(row["method"]) <= 2000
                or not isinstance(row.get("issues"), list)
                or any(not isinstance(issue, str) for issue in row["issues"])
                or not isinstance(row.get("provenance"), dict)
            ):
                raise ValueError("Invalid adapter record identity or shape.")
            provenance = row["provenance"]
            response_digest = (
                "upstream_sha256"
                if row["source_mode"] == "public_snapshot"
                else "response_sha256"
            )
            if (
                not isinstance(provenance.get("raw_fields"), dict)
                or not approved_citation_url(provenance.get("source_url"))
                or any(
                    not isinstance(provenance.get(field), str)
                    or re.fullmatch(r"[0-9a-f]{64}", provenance[field]) is None
                    for field in (response_digest, "raw_fields_sha256")
                )
            ):
                raise ValueError("Invalid adapter provenance.")
            # Use the same raw-field binding required by the final report before
            # merging sources. A corrupt comparison record must fail here without
            # discarding independently valid batches during report rendering.
            _comparison_record(row)
            seen.add(identity)
            for field in (
                "band_gap_ev",
                "dielectric_total",
                "dielectric_electronic",
                "energy_above_hull_ev_atom",
                "density_g_cm3",
                "bulk_modulus_gpa",
                "shear_modulus_gpa",
                "nsites",
            ):
                value = row.get(field)
                if value is not None and (
                    type(value) not in (int, float)
                    or not math.isfinite(value)
                    or value < 0
                    or (field == "nsites" and value <= 0)
                ):
                    raise ValueError("Invalid adapter numeric property.")
            for field in ("is_metal", "is_gap_direct", "potential_ferroelectric"):
                if row.get(field) is not None and type(row[field]) is not bool:
                    raise ValueError("Invalid adapter boolean property.")
        # This checks serializability, not evidence quality; scientific checks
        # still belong to the approved adapter that created these records.
        if len(json.dumps(response, allow_nan=False)) > 16_000_000:
            raise ValueError("Adapter response exceeds the retained batch bound.")
        if scope := filters.get("composition_scope"):
            kept = [
                row for row in rows if matches_composition_scope(row["formula"], scope)
            ]
            metadata = {
                **metadata,
                "composition_scope_screen": {
                    "scope": scope,
                    "records_removed": len(rows) - len(kept),
                    "interpretation": "Distinct element count from source formula; "
                    "necessary composition scope only, not proof of alloy phase "
                    "or processing state.",
                },
            }
            rows = kept
        return rows, metadata
    except Exception:
        # A single source outage, parser failure or adapter error must not erase
        # already verified evidence from another independently configured source.
        raise SourceError(
            "Public repository unavailable or failed validation."
        ) from None


def _unavailable_api_retrieval():
    """Describe a selected but unusable API without exposing credential
    details."""
    return {
        "mode": "public_repositories",
        "status": "unavailable",
        "records_retrieved": 0,
        "repository_attempts": [
            {
                "repository": "materials_project",
                "status": "unavailable",
                "records_retrieved": 0,
                "reason": "The selected Materials Project API key is missing, "
                "locked or unverified. Other independently selected public "
                "sources remain available.",
            }
        ],
    }


def _retrieve_repositories(
    filters,
    *,
    mp_api_key,
    mode,
    allow_nomad,
    allow_public_dielectric=False,
    required_fields=(),
    minimum_band_gap_ev=None,
    prior_material_ids=None,
    screen_elements=False,
    prefer_simple=False,
    allow_hybrid3=False,
    query="",
    discovery_references=(),
):
    """Try configured quantitative repositories after public lead
    discovery.

    Continue when a source cannot supply a full shortlist with required
    evidence. Each record remains independent; never join properties
    across source phases.
    """
    from .discovery_hints import formula_leads
    from .retrieval_budget import bounded_deadline, repository_budget

    leads = formula_leads(discovery_references)
    lead_attempts = []
    lead_records_retained = False
    adapters = []
    if allow_hybrid3:
        # Hints originate only from already-validated discovery adapter records.
        # They can prioritize an identity lookup, never establish its properties.
        systems = tuple(
            dict.fromkeys(
                int(ref["record_id"])
                for ref in discovery_references
                if ref.get("source_id") == "hybrid3"
                and isinstance(ref.get("record_id"), str)
                and re.fullmatch(r"[1-9][0-9]{0,8}", ref["record_id"])
            )
        )[:20]
        adapters.append(
            (
                "hybrid3",
                lambda filters: retrieve_hybrid3(
                    filters, query=query, system_ids=systems
                ),
            )
        )
    if mp_api_key is not None:
        adapters.append(
            ("materials_project", lambda query: retrieve_live(mp_api_key, query))
        )
    if allow_public_dielectric:
        adapters.append(("public_dielectric", retrieve_public_dielectric))
    if allow_nomad:
        # A selected API provider may fail after its key was verified. Keep
        # independently enabled public repositories available for that request.
        adapters.append(
            (
                "nomad",
                lambda query: retrieve_nomad(
                    {
                        **query,
                        **(
                            {"exclude_elements": ",".join(EXCLUDED_ELEMENTS)}
                            if screen_elements
                            else {}
                        ),
                        **({"prefer_simple": "true"} if prefer_simple else {}),
                    }
                ),
            )
        )
    attempts = (
        _unavailable_api_retrieval()["repository_attempts"]
        if mode == "api" and not mp_api_key
        else []
    )
    report_progress("repositories")
    records = []
    selected = []
    refresh = []
    for index, (name, adapter) in enumerate(adapters):
        now = time.monotonic()
        try:
            remaining = bounded_deadline(30) - now
        except ValueError:
            remaining = 0
        # Share the remaining existing budget fairly; a slow first provider must
        # leave later configured providers an opportunity to return evidence.
        deadline = now + max(0, remaining) / (len(adapters) - index)

        def retrieve(
            query,
            *,
            _adapter=adapter,
            _deadline=deadline,
            _preserve_scope=name == "materials_project",
        ):
            return _repository_response(
                _adapter, query, _deadline, preserve_composition_scope=_preserve_scope
            )

        prior = [
            value
            for value in (prior_material_ids or [])
            if (name == "nomad" and value.startswith("nomad:"))
            or (name == "public_dielectric" and value.startswith("dielectric:"))
            or (name == "materials_project" and value.startswith("mp-"))
        ]
        refreshed = []
        if prior:
            identity_key = "entry_ids" if name == "nomad" else "material_ids"
            query = {
                **filters,
                identity_key: ",".join(
                    dict.fromkeys(
                        value.removeprefix("nomad:")
                        .removeprefix("dielectric:")
                        .split(":row", 1)[0]
                        for value in prior
                    )
                ),
            }
            try:
                refreshed, metadata = retrieve(query)
                if name == "public_dielectric":
                    refreshed = [
                        row for row in refreshed if row["material_id"] in prior
                    ]
                refresh.append(
                    {
                        "repository": name,
                        "status": "ok" if refreshed else "no_records",
                        "requested_identities": prior,
                        "records_retrieved": len(refreshed),
                        "provenance": metadata,
                    }
                )
            except (SourceError, OSError):
                refresh.append(
                    {
                        "repository": name,
                        "status": "unavailable",
                        "requested_identities": prior,
                        "records_retrieved": 0,
                    }
                )
        lead_records = []
        if (
            name in {"nomad", "materials_project"}
            and leads
            and not set(filters) & {"formula", "chemsys", "material_ids", "entry_ids"}
        ):
            # Supplemental identity lookups get at most four seconds and a
            # quarter of the remaining shared budget. Always run the original
            # broad query afterward, even if leads already fill the shortlist.
            try:
                remaining = bounded_deadline(30) - time.monotonic()
                with repository_budget(seconds=min(4, remaining / 4)):
                    for offset in range(0, len(leads), 5):
                        formulas = [
                            lead["formula"] for lead in leads[offset : offset + 5]
                        ]
                        try:
                            hinted, metadata = retrieve(
                                {**filters, "formula": ",".join(formulas)}
                            )
                            if len({row["material_id"] for row in hinted}) != len(
                                hinted
                            ):
                                raise SourceError("Duplicate source identities.")
                        except (SourceError, OSError):
                            lead_attempts.append(
                                {
                                    "repository": name,
                                    "requested_formulas": formulas,
                                    "status": "unavailable",
                                    "records_retrieved": 0,
                                }
                            )
                        else:
                            lead_records = list(
                                {
                                    row["material_id"]: row
                                    for row in [*lead_records, *hinted]
                                }.values()
                            )
                            lead_attempts.append(
                                {
                                    "repository": name,
                                    "requested_formulas": formulas,
                                    "status": "ok" if hinted else "no_records",
                                    "records_retrieved": len(hinted),
                                    "provenance": metadata,
                                }
                            )
            except ValueError:
                lead_attempts.append(
                    {
                        "repository": name,
                        "status": "budget_exhausted",
                        "records_retrieved": 0,
                    }
                )
        try:
            rows, metadata = retrieve(filters)
        except (SourceError, OSError):
            attempts.append(
                {
                    "repository": name,
                    "status": "unavailable",
                    "records_retrieved": 0,
                    "reason": "The public repository was unavailable or failed "
                    "validation.",
                }
            )
            rows = []
            metadata = {}
            if not refreshed and not lead_records:
                continue
        else:
            attempts.append(
                {
                    "repository": name,
                    "status": "ok" if rows else "no_records",
                    "records_retrieved": len(rows),
                    "provenance": metadata,
                }
            )
        if rows or refreshed or lead_records:
            # Both sets are freshly adapter-validated. The later search response
            # replaces an earlier refreshed row with the same exact identity.
            records = list(
                {
                    row["material_id"]: row
                    for row in [*records, *refreshed, *lead_records, *rows]
                }.values()
            )
            lead_records_retained |= bool(lead_records)
            selected.append(name)
            comparable = {
                composition_key(row["formula"])
                for row in records
                if all(row.get(field) is not None for field in required_fields)
                and (
                    minimum_band_gap_ev is None
                    or row.get("band_gap_ev") is not None
                    and row["band_gap_ev"] >= minimum_band_gap_ev
                )
                and not (
                    screen_elements and set(row["elements"]) & set(EXCLUDED_ELEMENTS)
                )
            }
            if len(comparable) >= SHORTLIST_SIZE:
                break
    return records, {
        "mode": "public_repositories",
        "status": (
            "ok"
            if records
            else (
                "unavailable"
                if attempts
                and all(attempt["status"] == "unavailable" for attempt in attempts)
                else "no_records"
            )
        ),
        "records_retrieved": len(records),
        "selected_repository": (
            selected[0]
            if len(selected) == 1
            else "multiple_public_repositories" if selected else None
        ),
        "selected_repositories": selected,
        "shortlist_target": SHORTLIST_SIZE,
        "required_property_fields": list(required_fields),
        "repository_attempts": attempts,
        "discovery_leads": {
            "formulas": leads,
            "attempts": lead_attempts,
            "adapter_records_returned": lead_records_retained,
            "policy": "Literal formulas from validated public references are "
            "supplemental search hints only. Quantitative adapters independently "
            "retrieve and validate every record within the original scope. "
            "The broad query still runs; no properties or phases are merged.",
        },
        "chat_source_refresh": {
            "requested": bool(prior_material_ids),
            "attempts": refresh,
            "policy": (
                "Prior source identities are hints. Public adapters re-fetch and "
                "validate them against current filters; old measurements are never "
                "substituted. New search rows replace refreshed rows with the "
                "same identity."
            ),
        },
        "coverage": "Selected repositories are queried until enough distinct "
        "compositions have the application-required evidence, or available "
        "sources/time are exhausted. No values are merged across records or phases.",
    }


def run_research(
    prompt: str,
    config: AppConfig,
    *,
    mp_api_key: str | None = None,
    materials_project_mode: str = "auto",
    plan: dict | None = None,
    importance: dict[str, float] | None = None,
    material_class: str | None = None,
    application: str | None = None,
    minimum_band_gap_ev: float | None = None,
    target_band_gap_ev: float | None = None,
    band_gap_tolerance_ev: float | None = None,
    allow_nomad: bool = True,
    allow_public_dielectric: bool = False,
    allow_hybrid3: bool = False,
    discovery_references: list[dict] | None = None,
    prior_material_ids: list[str] | None = None,
    semantic_scope: dict | None = None,
    semantic_goal_authority: str = "inferred",
) -> dict:
    """Query current public sources; prompts supply preferences, never
    facts."""
    from labcat.intake import assess, outcome

    intake, prompt = assess(prompt)
    promotable_intake = intake["status"] == "clarification_required" and (
        intake.get("reason_code")
        in {"materials_scope_needed", "research_details_needed"}
    )
    if intake["status"] != "accepted" and (
        not promotable_intake or semantic_scope is None
    ):
        return outcome(intake)
    if materials_project_mode not in ("auto", "api", "snapshot", "off"):
        return render_research(
            _blocked("Unsupported Materials Project source mode."), config
        )
    if materials_project_mode == "off":
        mp_api_key = None
    try:
        search_prompt, search_class, identity_scope = source_search_context(
            prompt, material_class, semantic_scope=semantic_scope
        )
        if intake["status"] != "accepted" and search_class is None:
            return outcome(intake)
        if not isinstance(
            semantic_goal_authority, str
        ) or semantic_goal_authority not in {"inferred", "profile"}:
            raise ValueError("Unsupported semantic goal authority.")
        goal_review = (
            {
                "scope": semantic_scope,
                "prompt": prompt,
                "authority": semantic_goal_authority,
            }
            if semantic_scope is not None
            else None
        )
        selected_plan = _validate_plan(plan)
        _, empty_ranking = rank_records(
            [],
            config,
            importance=importance,
            application=application,
            minimum_band_gap_ev=minimum_band_gap_ev,
            target_band_gap_ev=target_band_gap_ev,
            band_gap_tolerance_ev=band_gap_tolerance_ev,
            goal_review=goal_review,
        )
        if any(
            type(flag) is not bool
            for flag in (allow_nomad, allow_public_dielectric, allow_hybrid3)
        ):
            raise ValueError("Unsupported public source selection.")
        if prior_material_ids is not None and (
            not isinstance(prior_material_ids, list)
            or len(prior_material_ids) > 6
            or any(
                not isinstance(value, str)
                or not re.fullmatch(
                    r"(?:nomad:[A-Za-z0-9_-]{1,80}|mp-[0-9]{1,10}|"
                    r"dielectric:mp-[0-9]{1,10}(?::row[0-9]{1,4})?)",
                    value,
                )
                for value in prior_material_ids
            )
        ):
            raise ValueError("Invalid prior source identity hints.")
    except ValueError as error:
        return render_research(_blocked(str(error)), config)
    if materials_project_mode == "snapshot":
        return _reference_only(
            "Historical fixed candidate snapshots are test fixtures only. "
            "Select live public sources to research this question.",
            config,
            selected_plan,
            importance,
            ranking_details=empty_ranking,
        )
    missing_api = (
        _unavailable_api_retrieval()
        if materials_project_mode == "api" and not mp_api_key
        else None
    )
    if missing_api:
        mp_api_key = None
    if mp_api_key is None and not any(
        (allow_nomad, allow_public_dielectric, allow_hybrid3)
    ):
        return _reference_only(
            (
                "The selected Materials Project API source needs an available API key, "
                "and no other quantitative public source is selected. "
                "No unselected source or saved candidate list was substituted."
                if missing_api
                else "No quantitative public source is selected or connected. "
                "No unselected quantitative source was queried."
            ),
            config,
            selected_plan,
            importance,
            retrieval=missing_api,
            ranking_details=empty_ranking,
        )
    scope_resolved = scalar_scope_resolved(search_prompt, search_class, identity_scope)
    bulk_supported = scope_resolved and (
        supports_bulk_search(search_prompt, search_class)
    )
    class_query = search_prompt
    if semantic_scope is not None and search_class is not None:
        # Closed class vocabulary is a source metadata hint, not evidence that a
        # returned material belongs to that class. The adapter verifies matches.
        class_query += " " + search_class.replace("_", " ")
    if allow_hybrid3:
        from .hybrid3 import supports_query

        allow_hybrid3 = scope_resolved and supports_query(class_query, search_class)
    if selected_plan["task"] == "unsupported" or (
        not bulk_supported and not allow_hybrid3
    ):
        return _reference_only(
            "This material class requires class-specific evidence beyond "
            "the current bulk-property adapters. Search public references "
            "for this question; no unrelated bulk candidates were "
            "substituted.",
            config,
            selected_plan,
            importance,
            retrieval=missing_api,
            ranking_details=empty_ranking,
        )
    try:
        filters = derive_search_filters(search_prompt, search_class)
        selected_weights = (
            importance if importance is not None else config.to_dict()["ranking"]
        )
        unscored_goals = set(
            empty_ranking.get("goal_review", {}).get("unscored_attributes", [])
        )
        dielectric_context = filters.get("has_props") == "dielectric" or any(
            selected_weights.get(key, 0) > 0
            for key in ("dielectric_total", "dielectric_electronic")
        )
        required_fields = tuple(
            field
            for key, field in (
                ("dielectric_total", "dielectric_total"),
                ("band_gap", "band_gap_ev"),
            )
            if application == "high_k_screening"
            and selected_weights.get(key, 0) > 0
            and key not in unscored_goals
        )
        if (
            target_band_gap_ev is not None
            and selected_weights.get("band_gap", 0) > 0
            and "band_gap" not in unscored_goals
            and "band_gap_ev" not in required_fields
        ):
            required_fields = (*required_fields, "band_gap_ev")
        from .retrieval_budget import repository_budget

        with repository_budget():
            records, retrieval = _retrieve_repositories(
                filters,
                mp_api_key=mp_api_key if bulk_supported else None,
                mode=materials_project_mode,
                allow_nomad=allow_nomad and bulk_supported,
                allow_public_dielectric=allow_public_dielectric
                and dielectric_context
                and bulk_supported,
                allow_hybrid3=allow_hybrid3,
                query=class_query,
                discovery_references=discovery_references or [],
                required_fields=required_fields,
                minimum_band_gap_ev=(
                    minimum_band_gap_ev
                    if selected_weights.get("band_gap", 0) > 0
                    and "band_gap" not in unscored_goals
                    else None
                ),
                prior_material_ids=prior_material_ids,
                screen_elements=(
                    importance
                    if importance is not None
                    else config.to_dict()["ranking"]
                ).get("element_screen", 0)
                > 0
                and "element_screen" not in unscored_goals,
                prefer_simple=(
                    importance
                    if importance is not None
                    else config.to_dict()["ranking"]
                ).get("simplicity", 0)
                > 0
                and "simplicity" not in unscored_goals,
            )
        report_progress("ranking")
        candidates, ranking = rank_records(
            records,
            config,
            importance=importance,
            application=application,
            minimum_band_gap_ev=minimum_band_gap_ev,
            target_band_gap_ev=target_band_gap_ev,
            band_gap_tolerance_ev=band_gap_tolerance_ev,
            goal_review=goal_review,
        )
    except (SourceError, OSError, ValueError) as error:
        reason = (
            str(error)
            if isinstance(error, SourceError)
            else (
                "Public evidence validation failed; no scientific facts were reported."
            )
        )
        failed = _blocked(reason)
        # Distinguish quarantined source/data failures from invalid preferences
        # or intake refusals, so healthy discovery can still support screening.
        failed["result"]["failure_stage"] = "material_retrieval"
        return render_research(failed, config)
    comparison_ids = set(ranking.get("comparison_record_ids", []))
    comparison_records = [
        deepcopy(record)
        for record in records
        if record["material_id"] in comparison_ids
    ]
    if not candidates:
        review_ids = {
            row["material_id"]
            for row in ranking.get("excluded_records", [])
            if row.get("unscored_goal_reasons")
        }
        review_records = [
            deepcopy(row) for row in records if row["material_id"] in review_ids
        ][:SHORTLIST_SIZE]
        return _reference_only(
            (
                "Retrieved records did not yield an eligible scored candidate. "
                "Selected criteria lack usable evidence or records were excluded; "
                "the ranking details retain the individual exclusion reasons."
                if records
                else (
                    "The selected public repositories were unavailable or failed "
                    "validation. No quantitative material properties were reported."
                    if retrieval["status"] == "unavailable"
                    else "The public repository queries returned no eligible "
                    "quantitative "
                    "material records. No values or candidates were substituted "
                    "from prompts, model memory, or a saved list."
                )
            ),
            config,
            selected_plan,
            importance,
            retrieval,
            ranking_details=ranking,
            comparison_records=comparison_records,
            review_records=review_records,
        )
    if not any(candidate["selected_weight_coverage"] > 0 for candidate in candidates):
        return _reference_only(
            "No selected ranking criterion has usable evidence in the "
            "current source records; no arbitrary identifier order is "
            "presented as a scientific ranking.",
            config,
            selected_plan,
            importance,
            retrieval,
            ranking_details=ranking,
            comparison_records=comparison_records,
        )
    sources = _sources(candidates, comparison_records)
    summary = (
        f"Ranked {len(candidates)} distinct compositions from {len(records)} "
        "retrieved public material records matching the search preferences. "
        "This bounded evidence screen is provisional; it does not establish "
        "application suitability."
    )
    limitations = [
        "Composition matches do not verify a material class, oxidation state, "
        "structure family, or application suitability.",
        "Prompts and model memory provide search preferences, never "
        "material properties or scientific citations.",
        "Numerical thresholds stated in a prompt are search preferences, not "
        "measured values or automatically enforced acceptance limits. The saved "
        "ranking profile controls the recorded weights and scoring rules.",
        "The current query is bounded, not exhaustive. No fixed candidate "
        "list or cross-version property substitution is used.",
        "Scores, utility anchors, weights, and counts are application "
        "preferences or derived values, not measurements or probabilities.",
        "Missing selected properties contribute zero without redistributing "
        "their weight. Check criterion coverage before comparing scores.",
        "The conservative element screen is incomplete and does not "
        "establish compound safety or toxicity.",
        "Reported calculations depend on their source methodology and "
        "phase; bulk records do not establish processing, device, film, or "
        "nanoscale performance.",
        "Hashes support reproducibility, not semantic truth. Independent "
        "evidence checks and scientific judgment remain necessary.",
        "Only approved public-source adapters can create property evidence; "
        "no wetlab, private-data or paywall access is provided.",
    ]
    result = {
        "stage": "partial",
        "summary": summary,
        "candidates": candidates,
        "ranking": ranking,
        "retrieval": retrieval,
        "limitations": limitations,
        "plan": selected_plan,
        "plan_effect": (
            "Task preferences only; selected ranking weights remain authoritative."
        ),
    }
    if comparison_records:
        result["comparison_records"] = comparison_records
    return render_research(
        {
            "stage": "partial",
            "answer": summary,
            "sources": sources,
            "result": result,
        },
        config,
    )


__all__ = ["load_snapshot", "render_research", "request_violation", "run_research"]
