"""Source-bound model interpretations for a separate provisional
literature rank.

This module never creates a material measurement. Exact public passages
support an auditable interpretation, not a verified property or
applicability claim. Numerical fit is preference arithmetic over
qualitative judgments only.
"""

import hashlib
import json
import math
import re
import unicodedata
from copy import deepcopy

from labcat.config import DEFAULT_TARGET_BAND_GAP_TOLERANCE_EV
from labcat.property_research import ATTRIBUTE_TERMS
from labcat.ranking_profiles import ATTRIBUTE_IDS, catalog
from labcat.research_intent import INTENT_VERSION, RELATIONS, _valid_intent

from .candidate_leads import (
    MAX_DOCUMENTS,
    MAX_LEADS,
    _body_documents,
    _cited_mention,
    _safe_text,
    discovery_documents,
    validate_candidate_leads,
)

LEGACY_VERSION = "literature-fit-v1"
VERSION = "literature-fit-v2"
GENERAL_CRITERIA = ("application_fit", "demonstrated_use")
_CRITERION_IDS = ATTRIBUTE_IDS | set(GENERAL_CRITERIA)
_GENERAL_LABELS = {
    "application_fit": "Application relevance",
    "demonstrated_use": "Demonstrated use",
}
MAX_EVALUATIONS = 96
MAX_EVALUATION_ARGUMENT_BYTES = 24_000
MAX_BATCHES = 2
JUDGMENTS = ("supports", "mixed", "concern", "unknown")
STABILITY = ("stability", "ambient_phase_stability", "operational_stability")
_FIELDS = {
    "lead_id",
    "criterion_id",
    "document_id",
    "quote",
    "judgment",
    "interpretation",
}
_VALUES = {"supports": 1.0, "mixed": 0.5, "concern": 0.0, "unknown": None}
_UNKNOWN_REVIEW_UTILITY = 0.25
_DIRECTIONS = {
    "stability": "maximize",
    "ambient_phase_stability": "maximize",
    "operational_stability": "maximize",
    "band_gap": "maximize",
    "element_screen": "maximize",
    "simplicity": "maximize",
    "evidence_quality": "maximize",
    "dielectric_total": "maximize",
    "dielectric_electronic": "maximize",
    "nsites": "minimize",
    "density": "minimize",
    "bulk_modulus": "maximize",
    "shear_modulus": "maximize",
    "metallicity": "maximize",
    "direct_gap": "maximize",
}
_URL = re.compile(r"https?://|www\.|\bdoi:|[a-z][a-z0-9+.-]*://", re.I)
_CAUTIONS = [
    "Provisional literature fit is a model interpretation of cited passages, "
    "not a verified measurement, material identity or experimental recommendation.",
    "Rank uses supported weighted fit with unknown criteria left unresolved. "
    "The lower and upper bounds show possible fit if unknown criteria range "
    "from concern to support; they are not confidence intervals or probabilities.",
    "Unknown stability is not established stability. Source phase, sample, "
    "conditions and applicability still require review.",
    "Conflicting passages remain visible. Mixed assessments do not establish "
    "that the same phase or operating conditions were compared.",
]
_PRELIMINARY_CAUTIONS = [
    "Candidate priority is a model interpretation of cited public passages, "
    "not a verified measurement, material identity, performance score or "
    "experimental recommendation.",
    "Preliminary priority uses application relevance (70%), demonstrated use "
    "(20%) and distinct cited works (10%, capped at three). Unknown general "
    "judgments use a fixed 0.25 review prior, not evidence of suitability.",
    "Selected attribute coverage sets the refinement weight: priority is "
    "(1 - coverage) times preliminary priority plus coverage times observed "
    "attribute fit. Unknown attributes do not erase a candidate's preliminary "
    "priority or imply that it meets the criterion.",
    "Application or stability concerns place a candidate after candidates "
    "without those concerns, regardless of score; mixed passages form an "
    "intermediate tier. Equal tier and priority share a rank. Unknown stability "
    "is not established stability.",
    "Cited works are grouped by matching DOI or normalized title, including "
    "cross-index copies missing a DOI; URL is used when both are unavailable. "
    "Wikipedia background does not count as corroboration. Distinct works are "
    "not necessarily independent experiments or verified peer review.",
    "Conflicting passages remain visible. Experimental and computed accounts "
    "are not averaged into measurements; phase, sample and operating conditions "
    "must be compatible before preferring an experimental interpretation.",
    "Attribute bounds concern unresolved qualitative attribute fit only, not "
    "the final priority, confidence or probability. A tied unknown-only "
    "shortlist is a starting point for review, not an ordered recommendation.",
]


def _check_version(version):
    if version not in (LEGACY_VERSION, VERSION):
        raise ValueError("Unsupported provisional evaluation version.")


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def evaluation_schema():
    """Shared bounded proposal envelope; no scientific values or new
    identities."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "evaluations": {
                "type": "array",
                "maxItems": MAX_EVALUATIONS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "lead_id": {"type": "string", "pattern": "^lead-[a-f0-9]{24}$"},
                        "criterion_id": {
                            "type": "string",
                            "enum": sorted(_CRITERION_IDS),
                        },
                        "document_id": {
                            "type": "string",
                            "pattern": "^doc-[a-f0-9]{24}$",
                        },
                        "quote": {
                            "type": "string",
                            "minLength": 12,
                            "maxLength": 480,
                            "description": "Copy a contiguous source quotation, "
                            "including the candidate name and the criterion or "
                            "demonstration context. Preserve qualifiers; do not "
                            "paraphrase or insert ellipses. Source numbers belong "
                            "here, not in the interpretation.",
                        },
                        "judgment": {
                            "type": "string",
                            "enum": list(JUDGMENTS),
                            "description": "Judge the selected goal under its "
                            "requested conditions and material/device scope. "
                            "Use unknown when that scope is not established. "
                            "Mixed requires actual applicable favorable and "
                            "adverse or conflicting evidence, not a missing test.",
                        },
                        "interpretation": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                            "description": "Concise qualitative interpretation of this "
                            "passage for this candidate and criterion goal. Refer "
                            "to 'this candidate'; do not repeat its name, even "
                            "when the name contains numbers. Do not add numbers, "
                            "measurements, identities, URLs or instructions. "
                            "State scope limitations consistently with the judgment.",
                        },
                    },
                    "required": sorted(_FIELDS),
                },
            }
        },
        "required": ["evaluations"],
    }


def _valid_row(row):
    return (
        isinstance(row, dict)
        and set(row) == _FIELDS
        and isinstance(row["lead_id"], str)
        and re.fullmatch(r"lead-[a-f0-9]{24}", row["lead_id"]) is not None
        and isinstance(row["document_id"], str)
        and re.fullmatch(r"doc-[a-f0-9]{24}", row["document_id"]) is not None
        and isinstance(row["criterion_id"], str)
        and row["criterion_id"] in _CRITERION_IDS
        and isinstance(row["judgment"], str)
        and row["judgment"] in JUDGMENTS
        and isinstance(row["quote"], str)
        and 12 <= len(row["quote"]) <= 480
        and _safe_text(row["quote"], 480) == row["quote"]
        and not _URL.search(row["quote"])
        and isinstance(row["interpretation"], str)
        and _safe_text(row["interpretation"], 200) == row["interpretation"]
        and not _URL.search(row["interpretation"])
        and not any(c.isnumeric() for c in row["interpretation"])
        and not any(c in row["interpretation"] for c in "<>{}`$")
    )


def valid_evaluation_arguments(arguments):
    """Validate one transport batch without reading or trusting source
    text."""
    try:
        return (
            isinstance(arguments, dict)
            and set(arguments) == {"evaluations"}
            and isinstance(arguments["evaluations"], list)
            and len(arguments["evaluations"]) <= MAX_EVALUATIONS
            and len(json.dumps(arguments, allow_nan=False).encode())
            <= MAX_EVALUATION_ARGUMENT_BYTES
            and all(_valid_row(row) for row in arguments["evaluations"])
        )
    except (TypeError, ValueError, RecursionError):
        return False


def valid_evaluation_transport_arguments(arguments):
    """Bound a submission, leaving each scientific row to parent
    admission.

    This grants no row scientific validity. The strict validator above
    remains authoritative for canonical evaluators and historical saved
    bundles.
    """
    try:
        return (
            isinstance(arguments, dict)
            and set(arguments) == {"evaluations"}
            and isinstance(arguments["evaluations"], list)
            and len(arguments["evaluations"]) <= MAX_EVALUATIONS
            and len(json.dumps(arguments, allow_nan=False).encode())
            <= MAX_EVALUATION_ARGUMENT_BYTES
        )
    except (TypeError, ValueError, RecursionError):
        return False


def _row_format_reason(row):
    """Return fixed feedback only; rejected content never leaves
    admission."""
    if not isinstance(row, dict) or set(row) != _FIELDS:
        return "invalid_row_format"
    if any(
        not isinstance(row[key], str) or re.fullmatch(pattern, row[key]) is None
        for key, pattern in (
            ("lead_id", r"lead-[a-f0-9]{24}"),
            ("document_id", r"doc-[a-f0-9]{24}"),
        )
    ):
        return "invalid_identity_format"
    if not isinstance(row["quote"], str) or not 12 <= len(row["quote"]) <= 480:
        return "evaluation_quote_length"
    interpretation = row["interpretation"]
    if (
        not isinstance(interpretation, str)
        or not 1 <= len(interpretation) <= 200
        or _safe_text(interpretation, 200) != interpretation
        or _URL.search(interpretation)
        or any(c.isnumeric() or c in "<>{}`$" for c in interpretation)
    ):
        return "evaluation_interpretation_format"
    return "invalid_row_format"


def partition_evaluation_arguments(arguments):
    """Separate strict rows from fixed indexed errors, without repairing
    data."""
    if not valid_evaluation_transport_arguments(arguments):
        raise ValueError("Invalid provisional evaluation envelope.")
    rows, indices, feedback = [], [], []
    for index, row in enumerate(arguments["evaluations"]):
        if _valid_row(row):
            rows.append(deepcopy(row))
            indices.append(index)
        else:
            feedback.append(
                {
                    "index": index,
                    "status": "rejected",
                    "reason": _row_format_reason(row),
                }
            )
    return {"evaluations": rows}, indices, feedback


def evaluation_goals(scope, selection):
    """Extract preference directions from an already request-validated
    scope."""
    if not isinstance(selection, dict):
        return []
    explicit_adjustments = {
        item.get("attribute")
        for item in selection.get("preference_adjustments", [])
        if isinstance(item, dict) and item.get("status") == "applied_preference"
    }
    application_goals = (
        [
            {"attribute_id": item["attribute"], "relation": item["relation"]}
            for item in selection.get("preference_adjustments", [])
            if isinstance(item, dict)
            and item.get("status") == "applied_application_preference"
            and item.get("attribute") not in explicit_adjustments
            and item.get("attribute") in ATTRIBUTE_IDS
            and item.get("relation") in RELATIONS
        ]
        if selection.get("mode") in {"inferred", "semantic_inferred"}
        else []
    )
    if selection.get("mode") != "semantic_inferred":
        return application_goals
    if (
        not isinstance(scope, dict)
        or scope.get("version") != INTENT_VERSION
        or scope.get("is_evidence") is not False
        or not _valid_intent(
            {
                key: value
                for key, value in scope.items()
                if key not in {"version", "target_text", "is_evidence"}
            }
        )
    ):
        raise ValueError("Invalid provisional criterion goal context.")
    explicit_goals = [
        {
            "attribute_id": item["attribute_id"],
            "relation": item.get("relation", "consider"),
        }
        for item in scope["goals"]
    ]

    explicit_ids = {item["attribute_id"] for item in explicit_goals}
    return explicit_goals + [
        item for item in application_goals if item["attribute_id"] not in explicit_ids
    ]


def evaluation_context(profile, *, goals=None, version=VERSION):
    """Return actual preference weights and goal directions, never
    evidence."""
    _check_version(version)
    if not isinstance(profile, dict) or not isinstance(profile.get("importance"), dict):
        raise ValueError("A provisional evaluation requires a selected profile.")
    importance = profile["importance"]
    if (
        not importance
        or len(importance) > len(ATTRIBUTE_IDS)
        or any(
            key not in ATTRIBUTE_IDS
            or type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for key, value in importance.items()
        )
        or sum(importance.values()) <= 0
    ):
        raise ValueError("Invalid provisional criterion weights.")
    goals = [] if goals is None else goals
    if not isinstance(goals, list) or len(goals) > len(ATTRIBUTE_IDS):
        raise ValueError("Invalid provisional criterion goals.")
    relations = {}
    for goal in goals:
        if (
            not isinstance(goal, dict)
            or set(goal) != {"attribute_id", "relation"}
            or not isinstance(goal["attribute_id"], str)
            or goal["attribute_id"] not in ATTRIBUTE_IDS
            or not isinstance(goal["relation"], str)
            or goal["relation"] not in RELATIONS
            or goal["attribute_id"] in relations
        ):
            raise ValueError("Invalid provisional criterion goals.")
        relations[goal["attribute_id"]] = goal["relation"]
    definitions = {item["id"]: item for item in catalog()["attributes"]}
    total = sum(importance.values())
    criteria = []
    for key in sorted(
        {key for key, value in importance.items() if value > 0} | set(STABILITY)
    ):
        relation = relations.get(key, _DIRECTIONS.get(key, "consider"))
        goal = {"relation": relation}
        if key == "band_gap":
            supplied_tolerance = profile.get("band_gap_tolerance_ev")
            if supplied_tolerance is not None and (
                type(supplied_tolerance) not in (int, float)
                or not math.isfinite(supplied_tolerance)
                or not 0 < supplied_tolerance <= 100
                or profile.get("target_band_gap_ev") is None
            ):
                raise ValueError("Invalid provisional band-gap tolerance.")
            for field in (
                "minimum_band_gap_ev",
                "target_band_gap_ev",
                "band_gap_tolerance_ev",
            ):
                value = profile.get(field)
                if value is not None:
                    if (
                        type(value) not in (int, float)
                        or not math.isfinite(value)
                        or not 0 <= value <= 100
                    ):
                        raise ValueError("Invalid provisional band-gap preference.")
                    goal[field] = value
            if profile.get("target_band_gap_ev") is not None and key not in relations:
                goal["relation"] = "target"
            if goal["relation"] == "target" and "target_band_gap_ev" in goal:
                goal.setdefault(
                    "band_gap_tolerance_ev", DEFAULT_TARGET_BAND_GAP_TOLERANCE_EV
                )
        criteria.append(
            {
                "criterion_id": key,
                "label": definitions[key]["label"],
                "importance": importance.get(key, 0),
                "weight": round(importance.get(key, 0) / total, 12),
                "goal": goal,
            }
        )
    if version == VERSION:
        criteria += [
            {
                "criterion_id": key,
                "label": _GENERAL_LABELS[key],
                "importance": 0,
                "weight": 0,
                "goal": {
                    "relation": "consider" if key == "application_fit" else "maximize"
                },
            }
            for key in GENERAL_CRITERIA
        ]
    return criteria


def _spellings(text, name):
    folded, offsets = "", {0: 0}
    for index, char in enumerate(text):
        folded += char.casefold()
        offsets[len(folded)] = index + 1
    return list(
        dict.fromkeys(
            text[offsets[match.start()] : offsets[match.end()]]
            for match in re.finditer(re.escape(name.casefold()), folded)
            if match.start() in offsets and match.end() in offsets
        )
    )


def _bindings(leads, references, proposals, documents):
    if not isinstance(leads, list) or len(leads) > MAX_LEADS:
        raise ValueError("Invalid provisional candidate list.")
    preferred = []
    for lead in leads:
        if not isinstance(lead, dict) or not isinstance(lead.get("citations"), list):
            raise ValueError("Invalid provisional candidate identity.")
        preferred += [
            citation.get("document_id")
            for citation in lead["citations"]
            if isinstance(citation, dict)
        ]
    preferred += [row["document_id"] for row in proposals]
    preferred = list(
        dict.fromkeys(value for value in preferred if isinstance(value, str))
    )
    if documents is not None:
        if (
            not isinstance(documents, list)
            or len(documents) > MAX_DOCUMENTS
            or any(
                not isinstance(doc, dict)
                or not isinstance(doc.get("document_id"), str)
                or re.fullmatch(r"doc-[a-f0-9]{24}", doc["document_id"]) is None
                for doc in documents
            )
        ):
            raise ValueError("Invalid provisional source documents.")
        supplied = [doc["document_id"] for doc in documents]
        if len(set(supplied)) != len(supplied):
            raise ValueError("Invalid provisional source documents.")
        # Authenticate the parent's bounded selection, including uncited
        # follow-up excerpts, rather than comparing it with a different default
        # selection. The union cannot expand the shared document budget.
        preferred = list(dict.fromkeys([*supplied, *preferred]))
    if len(preferred) > MAX_DOCUMENTS:
        raise ValueError("Provisional evidence exceeds the document limit.")
    originals = discovery_documents(references, preferred_document_ids=preferred)
    if documents is not None:
        lookup = {doc["document_id"]: doc for doc in originals}
        if any(
            not isinstance(doc, dict) or lookup.get(doc.get("document_id")) != doc
            for doc in documents
        ):
            raise ValueError("Provisional documents do not match approved references.")
        originals = documents
    docs = {doc["document_id"]: doc for doc in originals}
    bound_leads = {}
    for lead in leads:
        name, missing = lead.get("name"), lead.get("missing_criteria")
        if (
            not isinstance(name, str)
            or not isinstance(missing, list)
            or not set(STABILITY) <= set(missing)
        ):
            raise ValueError("Invalid provisional candidate identity.")
        recovered_proposals = []
        for citation in lead["citations"]:
            if not isinstance(citation, dict) or not isinstance(
                citation.get("quote"), str
            ):
                raise ValueError("Invalid provisional candidate citation.")
            spellings = _spellings(citation["quote"], name)
            if name in spellings:
                spellings = [name, *(value for value in spellings if value != name)]
            recovered_proposals += [
                {
                    "document_id": citation.get("document_id"),
                    "name": spelling,
                    "quote": citation["quote"],
                }
                for spelling in spellings
            ]
        recovered = validate_candidate_leads(recovered_proposals, originals, references)
        if (
            len(recovered) != 1
            or {**recovered[0], "missing_criteria": missing} != lead
            or lead["id"] in bound_leads
        ):
            raise ValueError(
                "Provisional candidate does not match approved source mentions."
            )
        bound_leads[lead["id"]] = lead
    refs = {}
    for reference in references:
        if isinstance(reference, dict):
            key = (reference.get("source_id"), reference.get("record_id"))
            if key in refs and refs[key] != reference:
                # Conflicting documents are excluded by discovery_documents.
                continue
            refs[key] = reference
    return bound_leads, docs, refs


def _term_present(text, term):
    pattern = re.escape(term).replace(r"\ ", r"[\s-]+")
    return bool(re.search(r"(?<!\w)" + pattern + r"(?!\w)", text, re.I))


def _operating_exposure_context(sentence, name):
    """Recognize bounded condition wording, without inferring a
    judgment.

    Bare stability, humid processing or oxidative activity is
    insufficient. Keep the literal candidate and both
    condition/stability parts local; this remains a lexical review gate,
    not a scientific scope or truth classifier.
    """
    environment = r"(?:humid|moist|oxidative|oxidizing|oxidising)"
    exposure = (
        rf"\b{environment}(?:\s+(?:and|or)\s+{environment})?\s+"
        r"(?:(?:operating|service)\s+)?"
        r"(?:air|conditions?|environments?|atmospheres?)\b|"
        r"\b(?:adsorption[ -]+desorption|charge[ -]+discharge|thermal|mechanical)"
        r"\s+cycles?\b"
    )
    for clause in re.split(
        r";|\b(?:whereas|while|but)\b|\band\s+(?=(?:another|other|different)\b)|"
        r"\band\s+(?=(?:[^\s,;]+[ \t]+){1,8}"
        r"(?:is|are|was|were|has|have|shows?|remains?|became)\b)",
        sentence,
        flags=re.I,
    ):
        if not any(
            _cited_mention(clause, clause, spelling)
            for spelling in _spellings(clause, name)
        ):
            continue
        # Do not broaden this new path into preparation or equilibrium claims.
        # Existing operational vocabulary remains unchanged for saved bundles.
        if re.search(
            r"\b(?:thermodynamic(?:ally)?|convex[ -]+hull|equilibrium|"
            r"synthesis|synthesi[sz]ed|"
            r"precursors?|intermediates?)\b",
            clause,
            re.I,
        ):
            continue
        if re.search(r"\b(?:(?:in)?stabil(?:ity|ities)|(?:un)?stable)\b", clause, re.I):
            if re.search(exposure, clause, re.I):
                return True
    return False


def _criterion_relevant(quote, name, criterion, judgment=None):
    """Require a local candidate mention and criterion vocabulary, not
    just a hit.

    This lexical relevance check does not prove the model's
    interpretation. Unsupported criterion vocabulary remains unknown
    instead of being guessed.
    """
    terms = ATTRIBUTE_TERMS.get(criterion, ())
    if criterion == "stability":
        terms = (
            "thermodynamic stability",
            "energy above hull",
            "convex hull",
            "phase equilibrium",
        )
    elif criterion == "solution_processability":
        terms = (
            *terms,
            "solution processed",
            "solution-coated",
            "solution coating",
            "solubility",
        )
    elif criterion == "operational_stability":
        terms = (*terms, "photobleaching", "aging", "cycling stability", "signal drift")
    for sentence in re.split(r"(?<=[.!?;])\s+", quote):
        if not any(
            _cited_mention(sentence, sentence, spelling)
            for spelling in _spellings(sentence, name)
        ):
            continue
        if criterion == "application_fit":
            # Application relevance is semantic and class-independent. The
            # model interprets only a passage containing this literal candidate;
            # it still cannot establish relevance as a scientific fact.
            return True
        if criterion == "demonstrated_use":
            if judgment != "supports":
                return True
            # A favorable use interpretation needs local demonstration language.
            # This is a relevance gate, not proof of a completed experiment.
            # Review/simulation discussion belongs in mixed or unknown instead.
            experimental = re.search(
                r"\b(?:experiment(?:s|al(?:ly)?)?|fabricat(?:ed|ion)|"
                r"measur(?:ed|ements?)|test(?:ed|ing)|deploy(?:ed|ment)|"
                r"commercial(?:ized|ly)|implemented|prototypes?)\b",
                sentence,
                re.I,
            )
            applied = re.search(
                r"\b(?:demonstrat(?:e[ds]?|ing|ion)|used|applied|utilized|"
                r"operated|manufactured)\b",
                sentence,
                re.I,
            )
            computed = re.search(
                r"\b(?:simulat\w*|comput\w*|theoretic\w*|predict\w*|"
                r"review|propos\w*|prospective|could|might)\b",
                sentence,
                re.I,
            )
            if experimental or (applied and not computed):
                return True
            continue
        if criterion == "ambient_phase_stability":
            if re.search(r"room[ -]temperature|ambient", sentence, re.I) and re.search(
                r"phase|stabil|decompos|transition", sentence, re.I
            ):
                return True
        elif any(_term_present(sentence, term) for term in terms):
            return True
        elif criterion == "operational_stability" and _operating_exposure_context(
            sentence, name
        ):
            return True
    return False


def _aggregate(assessments):
    values = {item["judgment"] for item in assessments} - {"unknown"}
    if not values:
        return "unknown"
    return next(iter(values)) if len(values) == 1 else "mixed"


def _quotation_contexts(quote, doc):
    """Return every containing sentence, retaining semicolon qualifiers.

    An identical short quote may occur in conflicting contexts. Inspect
    all of them rather than attributing it to whichever occurrence
    happens to be first. A longer quotation can disambiguate a later
    corrected submission. Newlines separate the title from the retained
    body; decimal points do not split it.
    """
    text = doc["text"].casefold()
    boundaries = [
        0,
        *[m.end() for m in re.finditer(r"[.!?]\s+|\n+", text)],
        len(text),
    ]
    contexts = []
    for match in re.finditer(re.escape(quote.casefold()), text):
        left = max(value for value in boundaries if value <= match.start())
        right = min(value for value in boundaries if value >= match.end())
        contexts.append(text[left:right])
    return list(dict.fromkeys(contexts))


def _candidate_clauses(context, name):
    """Keep local candidate clauses, not unrelated comparison
    subjects."""
    parts = re.split(r"(;|\b(?:whereas|while)\b)", context)
    clauses = []
    for index in range(0, len(parts), 2):
        clause = parts[index]
        if not any(
            _cited_mention(clause, clause, spelling)
            for spelling in _spellings(clause, name)
        ):
            continue
        if (
            index + 2 < len(parts)
            and parts[index + 1] == ";"
            and re.match(
                r"\s*(?:this|that|which|the "
                r"(?:device|use|demonstration|test|experiment))\b",
                parts[index + 2],
                re.I,
            )
        ):
            clause += ";" + parts[index + 2]
        clauses.append(clause)
    return clauses


def _demonstration_missing(context, name):
    # These patterns address explicit counterexamples, not arbitrary scientific
    # prose. Experimental and simulated observations can legitimately coexist.
    action = (
        r"(?:fabricated|tested|measured|deployed|used|operated|"
        r"demonstrated|implemented|manufactured|performed)"
    )
    adverb = r"(?:(?:successfully|experimentally|directly|previously|already)\s+)*"
    actual = (
        rf"\b(?:(?:was|were|has been|have been|had been)\s+{adverb}"
        r"(?:fabricated|tested|measured|deployed|demonstrated|"
        r"implemented|manufactured)|"
        rf"(?:we|authors|researchers)\s+(?:have\s+)?{adverb}"
        r"(?:fabricated|tested|measured|deployed|demonstrat(?:e|ed))|"
        r"measurements?\s+(?:show|showed|demonstrate|demonstrated))\b"
    )
    for clause in _candidate_clauses(context, name):
        if re.search(
            rf"\b{action}\s+(?:only|solely|exclusively)\s+"
            r"(?:in|using|through)\s+(?:(?:a|the|numerical|computer|device)\s+)*"
            r"simulat\w*\b",
            clause,
            re.I,
        ):
            return True
        completed = bool(re.search(actual, clause, re.I))
        negated = re.search(
            rf"\b(?:(?:not(?!\s+only\b)|never|neither)\s+(?:\w+\s+){{0,3}}{action}|"
            rf"(?:yet|remains?)\s+to\s+(?:be\s+)?{action}|"
            rf"(?:will|would|could|might|may)\s+(?:be\s+)?{action})\b",
            clause,
            re.I,
        )
        prospective = re.search(
            r"\b(?:propos\w*|planned|prospective|simulat\w*|could|might|would)\b",
            clause,
            re.I,
        )
        if (negated or prospective) and not completed:
            return True
    return False


def _physical_demonstration(context):
    """Explicit experimental action, rather than an unqualified
    'demonstrate'."""
    if re.search(
        r"\b(?:numerically|computationally|virtually)\s+"
        r"(?:tested|measured|fabricated|demonstrated)|"
        r"\b(?:tested|measured|demonstrated)\s+"
        r"(?:numerically|computationally|virtually)\b|"
        r"\b(?:tested|measured|demonstrated|used|operated)\s+"
        r"(?:(?:only|solely)\s+)?"
        r"(?:in|using|through|with|by)\s+"
        r"(?:(?:a|the|numerical|computer|device)\s+)*"
        r"(?:simulat\w*|models?)\b",
        context,
        re.I,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:(?:in|during)\s+(?:the|an|our)\s+experiment\b.{0,150}"
            r"\b(?:used|operated|demonstrat\w*)|"
            r"experimentally\s+(?:demonstrat\w*|test\w*|measur\w*)|"
            r"(?:demonstrat\w*|test\w*|measur\w*)\s+experimentally|"
            r"(?:we|authors|researchers)\s+(?:have\s+)?"
            r"(?:fabricated|measured|tested|deployed)|"
            r"(?:was|were|has been|have been)\s+(?:experimentally\s+)?"
            r"(?:fabricated|measured|tested|deployed)|"
            r"measurements?\s+(?:show|showed|demonstrat\w*))\b",
            context,
            re.I,
        )
    )


def _candidate_physical_demonstration(context, name):
    """Another named subject after 'and' cannot supply physical-use
    credit."""
    for clause in _candidate_clauses(context, name):
        parts = re.split(r"\b(?:and|but)\b", clause)
        for index, part in enumerate(parts):
            if not _candidate_clauses(part, name):
                continue
            if _physical_demonstration(part):
                return True
            if index and re.fullmatch(
                r"\s*(?:we|authors|researchers)\s+(?:have\s+)?"
                r"(?:experimentally\s+)?(?:fabricated|tested|measured|deployed)\s*",
                parts[index - 1],
                re.I,
            ):
                # A bare verb has no other object: 'we fabricated and tested
                # this candidate' is a shared-subject experimental statement.
                return _physical_demonstration(parts[index - 1] + " and " + part)
    return False


def _adjacent_demonstration_missing(quote, doc, name):
    """Keep directly adjacent method qualifiers on generic use claims.

    A simulation may say 'we demonstrate' in its results sentence.
    Inspect the immediate neighboring sentences for a scoped method or
    future-experiment qualifier, without treating every computed
    comparison in a mixed-method article as a veto. This is bounded
    admission, not semantic method extraction.
    """
    # Discovery documents prepend a title without a sentence separator. The
    # title is not an adjacent method sentence and must not hide a body's 'Here'.
    text = doc["text"].casefold().removeprefix(doc["title"].casefold()).lstrip()
    boundaries = [
        0,
        *[m.end() for m in re.finditer(r"[.!?]\s+|\n+", text)],
        len(text),
    ]
    for match in re.finditer(re.escape(quote.casefold()), text):
        left = max(i for i, value in enumerate(boundaries) if value <= match.start())
        right = min(i for i, value in enumerate(boundaries) if value >= match.end())
        context = text[boundaries[left] : boundaries[right]]
        # Explicit actual use of this candidate survives nearby simulation work.
        if _candidate_physical_demonstration(context, name):
            continue
        neighbors = []
        if left > 0:
            neighbors.append((True, text[boundaries[left - 1] : boundaries[left]]))
        if right + 1 < len(boundaries):
            neighbors.append((False, text[boundaries[right] : boundaries[right + 1]]))
        if any(
            _candidate_physical_demonstration(clause, name)
            and re.search(
                r"\b(?:devices?|cells?|prototypes?|contacts?|components?)\b", clause
            )
            for _, neighbor in neighbors
            for clause in _candidate_clauses(neighbor, name)
        ):
            continue
        for preceding, neighbor in neighbors:
            neighbor = neighbor.strip()
            named = bool(_candidate_clauses(neighbor, name))
            # Do not borrow another sample's or a comparison's method. Without
            # the same named sample, only a following result/work qualifier can
            # link back. An unnamed previous study may concern another sample.
            linked = named or (
                not preceding
                and not re.search(
                    r"\b(?:another|other|different|unrelated|comparison|whereas)\b",
                    neighbor,
                )
                and re.match(
                    r"(?:our (?:study|work|analysis)\b|"
                    r"this (?:study|work|analysis|result|device|cell|system)\b|"
                    r"these (?:results|devices|cells|systems)\b|"
                    r"experimental (?:realization|validation|demonstration)\b)",
                    neighbor,
                )
            )
            physical = (
                _candidate_physical_demonstration(neighbor, name)
                if named
                else _physical_demonstration(
                    re.split(r";|\b(?:whereas|while|and|but)\b", neighbor)[0]
                )
            )
            if not linked or physical:
                continue
            future_experiment = re.search(
                r"\b(?:motivat\w*|await\w*|require\w*|future|further)\b.{0,100}"
                r"\bexperimental (?:realization|validation|demonstration)\b|"
                r"\bexperimental (?:realization|validation|demonstration)\b"
                r".{0,100}\b(?:future|planned|pending|remain\w*|yet)\b",
                neighbor,
            )
            computational = re.search(
                r"\b(?:simulat\w*|computational(?:ly)?|theoretical(?:ly)?|numerically|"
                r"numerical (?:model\w*|stud\w*|analys\w*))\b",
                neighbor,
            )
            if future_experiment or computational:
                return True
    return False


def _explicit_property_input(context, name, criterion):
    """Reject explicit input relations, not every assumption in a study.

    A measured/calculated property can later be used as a model input.
    That reuse does not erase the observation. Different subjects or
    assumptions about other properties likewise do not establish that
    this value is an input.
    """
    terms = ATTRIBUTE_TERMS.get(criterion, ())
    if not terms:
        return False
    property_term = "(?:" + "|".join(re.escape(term) for term in terms) + ")"
    # Stop before a different argument or property introduced by a conjunction.
    link = r"(?:(?!\b(?:with|and|but|whereas|while|another|other)\b).){0,100}?"
    input_term = r"(?:model[ -]inputs?|input[ -]parameters?|simulation[ -]parameters?)"
    parts = re.split(r"(;|\b(?:whereas|while)\b)", context)
    for index in range(0, len(parts), 2):
        clause = parts[index]
        if not _candidate_clauses(clause, name) or not re.search(
            property_term, clause, re.I
        ):
            continue
        # A semicolon can introduce a qualifier of the preceding value. Do not
        # adopt an unrelated sample's following clause as this material's method.
        if (
            index + 2 < len(parts)
            and parts[index + 1] == ";"
            and re.match(
                r"\s*(?:this|that|which|the (?:value|gap|parameter)|an? assumed)\b",
                parts[index + 2],
                re.I,
            )
        ):
            clause += ";" + parts[index + 2]
        observed = re.search(
            rf"\b(?:measured|observed|calculated)\s+(?:\w+\s+){{0,3}}{property_term}\b|"
            rf"\b{property_term}\b{link}\b(?:was|is|has been)\s+"
            r"(?:experimentally\s+)?(?:measured|observed|calculated)\b",
            clause,
            re.I,
        )
        if observed and not re.search(
            r"\b(?:not|never)\s+(?:experimentally\s+)?"
            r"(?:measured|observed|calculated)\b",
            clause,
        ):
            continue
        if re.search(
            rf"\b(?:not|never)\s+(?:an?\s+)?(?:assumed|{input_term})\b", clause
        ):
            continue
        direct = re.search(
            rf"\b(?:assumed|{input_term})\s+(?:\w+\s+){{0,3}}{property_term}\b|"
            rf"\b{property_term}\s+assumed\s+to\s+be\b|"
            rf"\b{property_term}\b{link}\b(?:was|is|were|has been)\s+"
            rf"(?:an?\s+)?(?:assumed|{input_term})\b|"
            rf"\b{property_term}\b{link}\b(?:was|is|has been)\s+not\s+"
            r"(?:measured|observed|calculated)\s+but\s+assumed\b|"
            rf"\b{property_term}\b{link}\b(?:used|fixed|chosen|set|selected)\b"
            rf"{link}\b(?:simulation|model)\b|"
            rf"\b{input_term}\b{link}\b{property_term}\b",
            clause,
            re.I,
        )
        qualified = ";" in clause and re.search(
            rf";\s*(?:this|that|which|the (?:value|gap|parameter))\b.*?"
            rf"\b(?:assumed|{input_term})\b",
            clause,
            re.I,
        )
        if direct or qualified:
            return True
    return False


def _body_input_heading(reference, doc, name, criterion, quote):
    """Reject explicit input headings, preserving locally observed
    properties.

    Simulation results are not assumptions. A measured/calculated value
    reused as input remains an observation under its stated method and
    conditions.
    """
    terms = ATTRIBUTE_TERMS.get(criterion, ())
    if not terms:
        return False
    property_term = "(?:" + "|".join(re.escape(term) for term in terms) + ")"
    link = r"(?:(?!\b(?:with|and|but|whereas|while|another|other)\b).){0,60}?"
    for body, _ in _body_documents(reference, include_context=True):
        if body["document_id"] != doc["document_id"]:
            continue
        if not re.search(
            r"\b(?:input[ -]parameters?|(?:model|simulation)[ -]inputs?|"
            r"(?:assumed|chosen)\s+(?:(?:model|simulation|input)\s+)*parameters?)\b",
            body["section"],
            re.I,
        ):
            return False
        local = []
        for context in _quotation_contexts(quote, doc):
            for sentence in re.split(r"[.!?]\s+|\n+", context):
                # An observation attributed to a conjunction's other subject
                # cannot establish that this input parameter was observed.
                for scoped in re.split(r"\b(?:and|but)\b", sentence, flags=re.I):
                    for clause in _candidate_clauses(scoped, name):
                        if re.search(property_term, clause, re.I):
                            local.append(clause)
        # Every occurrence must establish the observed value in its own local
        # candidate/property context. Another sentence or different-condition
        # measurement cannot exempt an indistinguishable assumed quotation.
        return not local or any(
            not re.search(
                rf"\b(?:measured|observed|calculated)\s+(?:\w+\s+){{0,3}}"
                rf"{property_term}\b|"
                rf"\b{property_term}\b{link}\b(?:was|is|has been)\s+"
                r"(?:experimentally\s+)?(?:measured|observed|calculated)\b",
                clause,
                re.I,
            )
            or re.search(
                r"\b(?:not|never)\s+(?:experimentally\s+)?"
                r"(?:measured|observed|calculated)\b",
                clause,
                re.I,
            )
            for clause in local
        )
    return False


def _admission_reason(row, lead, doc, reference=None):
    """Conservative checks for newly submitted judgments, not scientific
    proof.

    Saved bundles keep their original interpretation and arithmetic.
    Admission rejects a new claim instead of silently changing it into
    another judgment. Full source text remains available for a
    corrected, scoped quotation.
    """
    if row["judgment"] == "unknown":
        return None
    criterion = row["criterion_id"]
    if criterion == "demonstrated_use":
        if row["judgment"] in {"supports", "mixed"}:
            if not _criterion_relevant(
                row["quote"], lead["name"], criterion, "supports"
            ):
                return "demonstration_not_established"
            if any(
                _demonstration_missing(context, lead["name"])
                for context in _quotation_contexts(row["quote"], doc)
            ):
                return "demonstration_not_established"
            if _adjacent_demonstration_missing(row["quote"], doc, lead["name"]):
                return "demonstration_not_established"
        return None
    if criterion in GENERAL_CRITERIA:
        return None
    quote = row["quote"].casefold().strip(" .:;!?")
    title = doc["title"].casefold().strip(" .:;!?")
    if quote and quote in title:
        return "attribute_requires_source_context"
    if _body_input_heading(reference, doc, lead["name"], criterion, row["quote"]):
        return "model_input_not_observation"
    if any(
        _explicit_property_input(context, lead["name"], criterion)
        for context in _quotation_contexts(row["quote"], doc)
    ):
        return "model_input_not_observation"
    return None


def _work_aliases(reference):
    """Retain DOI/title aliases so a missing index field cannot multiply
    a work."""
    aliases = set()
    doi = reference["metadata"].get("doi")
    if isinstance(doi, str):
        doi = re.sub(
            r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi.strip(), flags=re.I
        )
        if re.fullmatch(r"10\.\d{4,9}/\S+", doi):
            aliases.add(("doi", doi.casefold()))
    title = unicodedata.normalize("NFKC", reference["title"]).casefold()
    title = " ".join(re.findall(r"\w+", title))
    if title:
        aliases.add(("title", title))
    return aliases or {("url", reference["url"])}


def _work_count(references):
    """Count connected work aliases conservatively, independent of
    source order.

    Titles are not proof of scientific identity: merging an ambiguous shared
    title limits the bonus rather than granting more corroboration. Different
    DOI records without a matching title stay separate.
    """
    groups = []
    for reference in references:
        aliases = _work_aliases(reference)
        overlapping = [group for group in groups if group & aliases]
        groups = [group for group in groups if not group & aliases]
        groups.append(aliases.union(*overlapping))
    return len(groups)


def _prioritize(row, refs):
    """Apply the fixed review baseline, then refine by observed
    attribute weight."""
    by_id = {criterion["criterion_id"]: criterion for criterion in row["criteria"]}
    app, use = (by_id[key] for key in GENERAL_CRITERIA)
    work_count = _work_count(
        refs[(item["source_id"], item["record_id"])]
        for item in app["assessments"]
        if item["source_id"] != "wikipedia"
        and item["judgment"] in {"supports", "mixed"}
    )
    corroboration = min(work_count, 3) / 3
    app_utility, use_utility = (
        item["utility"] if item["utility"] is not None else _UNKNOWN_REVIEW_UTILITY
        for item in (app, use)
    )
    baseline = round(0.7 * app_utility + 0.2 * use_utility + 0.1 * corroboration, 12)
    coverage = row["coverage"]
    # Every adverse assessment affects the tier, even when a conflicting
    # favorable passage causes the aggregate judgment to become mixed.
    tier = max(
        (
            {"concern": 2, "mixed": 1}.get(assessment["judgment"], 0)
            for key in ("application_fit", *STABILITY)
            for assessment in by_id[key]["assessments"]
        ),
        default=0,
    )
    row.update(
        preliminary_score=baseline,
        priority_score=round(
            (1 - coverage) * baseline + coverage * (row["observed_fit"] or 0), 12
        ),
        priority_tier=tier,
        ranking_basis=(
            "preliminary"
            if coverage == 0
            else "attribute" if coverage == 1 else "blended"
        ),
        general_evidence={
            "application_fit": app["judgment"],
            "demonstrated_use": use["judgment"],
            "corroborating_work_count": work_count,
            "corroboration": round(corroboration, 12),
            "unknown_utility": _UNKNOWN_REVIEW_UTILITY,
        },
    )


def _evaluate(
    proposals,
    leads,
    references,
    profile,
    *,
    documents=None,
    goals=None,
    version=VERSION,
    admission_checks=False,
):
    context = evaluation_context(profile, goals=goals, version=version)
    criteria = {item["criterion_id"]: item for item in context}
    bound, docs, refs = _bindings(leads, references, proposals, documents)
    accepted, feedback, seen, observations = [], [], set(), {}
    for index, row in enumerate(proposals):
        lead, doc = bound.get(row["lead_id"]), docs.get(row["document_id"])
        reason = None
        if lead is None:
            reason = "unknown_lead"
        elif row["criterion_id"] not in criteria:
            reason = "unselected_criterion"
        elif doc is None:
            reason = "unavailable_document"
        elif not any(
            _cited_mention(doc["text"], row["quote"], spelling)
            for spelling in _spellings(row["quote"], lead["name"])
        ):
            reason = "quote_or_candidate_not_bound"
        elif not _criterion_relevant(
            row["quote"], lead["name"], row["criterion_id"], row["judgment"]
        ):
            reason = "criterion_context_missing"
        elif (
            row["judgment"] != "unknown"
            and criteria[row["criterion_id"]]["goal"]["relation"] == "target"
            and not (
                row["criterion_id"] == "band_gap"
                and "target_band_gap_ev" in criteria[row["criterion_id"]]["goal"]
            )
        ):
            reason = "goal_target_unresolved"
        if reason is None and admission_checks and version == VERSION:
            reason = _admission_reason(
                row, lead, doc, refs.get((doc["source_id"], doc["record_id"]))
            )
        key = (row["lead_id"], row["criterion_id"], row["document_id"], row["quote"])
        exact_key = (*key, row["judgment"], row["interpretation"])
        if reason is None and exact_key in seen:
            feedback.append(
                {"index": index, "status": "accepted", "reason": "already_retained"}
            )
            continue
        if reason is not None:
            feedback.append({"index": index, "status": "rejected", "reason": reason})
            continue
        # Opposite interpretations remain visible and aggregate to mixed,
        # independent of arrival order; neither favorable nor negative wins.
        seen.add(exact_key)
        accepted.append(deepcopy(row))
        source = refs[(doc["source_id"], doc["record_id"])]
        assessment = {
            key: doc[key]
            for key in ("document_id", "source_id", "record_id", "url", "title")
        }
        assessment.update(
            {key: row[key] for key in ("quote", "judgment", "interpretation")}
        )
        assessment.update(
            document_sha256=_digest(doc),
            response_sha256=source["provenance"]["response_sha256"],
        )
        observations.setdefault((row["lead_id"], row["criterion_id"]), []).append(
            assessment
        )
        feedback.append(
            {
                "index": index,
                "status": "accepted",
                "reason": "source_bound_interpretation",
            }
        )
    rows = []
    for lead_id, lead in bound.items():
        items, known_weight, known_fit = [], 0.0, 0.0
        for criterion in context:
            key = criterion["criterion_id"]
            assessments = observations.get((lead_id, key), [])
            assessments = sorted(
                assessments,
                key=lambda item: (
                    item["document_id"],
                    item["quote"],
                    item["judgment"],
                    item["interpretation"],
                ),
            )
            judgment = _aggregate(assessments)
            utility = _VALUES[judgment]
            if utility is not None:
                known_weight += criterion["weight"]
                known_fit += criterion["weight"] * utility
            items.append(
                {
                    "criterion_id": key,
                    "judgment": judgment,
                    "utility": utility,
                    "assessments": assessments,
                }
            )
        coverage = min(1.0, round(known_weight, 12))
        lower = min(1.0, round(known_fit, 12))
        statuses = {item["criterion_id"]: item["judgment"] for item in items}
        rows.append(
            {
                "lead_id": lead_id,
                "name": lead["name"],
                "rank": None,
                "observed_fit": (
                    round(known_fit / known_weight, 12) if known_weight > 0 else None
                ),
                "coverage": coverage,
                "fit_lower_bound": lower,
                "fit_upper_bound": min(1.0, round(lower + 1 - coverage, 12)),
                "unknown_criteria": [
                    key for key, value in statuses.items() if value == "unknown"
                ],
                "stability_unknown": [
                    key for key in STABILITY if statuses[key] == "unknown"
                ],
                "stability_concerns": [
                    key for key in STABILITY if statuses[key] in {"mixed", "concern"}
                ],
                "criteria": items,
            }
        )
    if version == VERSION:
        for row in rows:
            _prioritize(row, refs)
        ranked = sorted(
            rows,
            key=lambda row: (
                row["priority_tier"],
                -row["priority_score"],
                row["name"].casefold(),
                row["lead_id"],
            ),
        )
    else:
        ranked = sorted(
            (row for row in rows if row["observed_fit"] is not None),
            key=lambda row: (
                -row["fit_lower_bound"],
                -row["coverage"],
                row["name"].casefold(),
                row["lead_id"],
            ),
        )
    previous, rank = None, 0
    for index, row in enumerate(ranked, start=1):
        tie = (
            (row["priority_tier"], row["priority_score"])
            if version == VERSION
            else row["fit_lower_bound"]
        )
        if previous != tie:
            rank = index
        row["rank"], previous = rank, tie
    unranked = (
        []
        if version == VERSION
        else sorted(
            (row for row in rows if row["observed_fit"] is None),
            key=lambda row: (row["name"].casefold(), row["lead_id"]),
        )
    )
    accepted.sort(
        key=lambda item: (
            item["lead_id"],
            item["criterion_id"],
            item["document_id"],
            item["quote"],
            item["judgment"],
            item["interpretation"],
        )
    )
    bundle = {
        "version": version,
        "is_material_evidence": False,
        "properties_verified": False,
        "criteria": context,
        "proposals": accepted,
        "ranked_candidates": ranked,
        "unranked_candidates": unranked,
        "cautions": list(_PRELIMINARY_CAUTIONS if version == VERSION else _CAUTIONS),
    }
    return {"evaluation": bundle, "accepted_proposals": accepted, "feedback": feedback}


def evaluate_candidates(
    arguments,
    leads,
    references,
    profile,
    *,
    documents=None,
    goals=None,
    version=VERSION,
    admission_checks=False,
):
    """Bind one proposal batch; invalid source selectors receive fixed
    feedback."""
    if not valid_evaluation_arguments(arguments):
        raise ValueError("Invalid provisional evaluation arguments.")
    return _evaluate(
        arguments["evaluations"],
        leads,
        references,
        profile,
        documents=documents,
        goals=goals,
        version=version,
        admission_checks=admission_checks,
    )


def evaluate_candidate_batches(
    batches,
    leads,
    references,
    profile,
    *,
    documents=None,
    goals=None,
    version=VERSION,
    admission_checks=False,
):
    """Merge two bounded attempts without overwriting retained
    interpretations."""
    if (
        not isinstance(batches, list)
        or len(batches) > MAX_BATCHES
        or not all(valid_evaluation_arguments(batch) for batch in batches)
    ):
        raise ValueError("Invalid provisional evaluation batches.")
    return _evaluate(
        [row for batch in batches for row in batch["evaluations"]],
        leads,
        references,
        profile,
        documents=documents,
        goals=goals,
        version=version,
        admission_checks=admission_checks,
    )


def validate_evaluation(bundle, leads, references, profile, *, goals=None):
    """Recompute every source binding, interpretation aggregate, score
    and rank."""
    if not isinstance(bundle, dict) or not isinstance(bundle.get("proposals"), list):
        raise ValueError("Invalid saved provisional evaluation.")
    proposals = bundle["proposals"]
    version = bundle.get("version")
    _check_version(version)
    if (
        len(proposals) > MAX_BATCHES * MAX_EVALUATIONS
        or len(json.dumps({"evaluations": proposals}, allow_nan=False).encode())
        > MAX_BATCHES * MAX_EVALUATION_ARGUMENT_BYTES
        or not all(_valid_row(row) for row in proposals)
    ):
        raise ValueError("Invalid saved provisional evaluation proposals.")
    canonical = _evaluate(
        proposals, leads, references, profile, goals=goals, version=version
    )
    if canonical["evaluation"] != bundle or any(
        item["status"] != "accepted" for item in canonical["feedback"]
    ):
        raise ValueError(
            "Saved provisional evaluation does not match its sources and preferences."
        )
    return canonical["evaluation"]
