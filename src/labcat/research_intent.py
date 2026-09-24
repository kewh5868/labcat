"""Bounded model interpretation of request roles, never scientific
evidence.

The same structural validator is shared by both Goose gateways. Exact
span binding and preference resolution happen in the parent against its
own request. Nothing here changes source selection, credentials, safety
policy or tool access.
"""

import json
import math
import re
import unicodedata
from copy import deepcopy

from labcat.config import DEFAULT_TARGET_BAND_GAP_TOLERANCE_EV
from labcat.ranking_profiles import (
    ATTRIBUTE_IDS,
    PRESETS,
    SUPPORTED_ATTRIBUTES,
    _negated_preference,
    apply_semantic_goals,
    catalog,
    compose_catalog_profile,
    prompt_preferences,
)
from labcat.untrusted_text import source_instruction_reason

INTENT_VERSION = "semantic-intake-v1"
DECISIONS = ("materials_research", "needs_clarification", "out_of_scope", "unsafe")
IDENTITY_SCOPES = ("bulk", "molecular", "nanoscale", "unspecified")
PRIORITIES = ("primary", "normal", "secondary")
RELATIONS = ("consider", "maximize", "minimize", "target")
MAX_ARGUMENT_BYTES = 12_000
_ROLE_FIELDS = (
    "target_spans",
    "application_spans",
    "environment_spans",
    "processing_spans",
)
_INTENT_FIELDS = frozenset(
    {"material_class", "application", "identity_scope", "goals", *_ROLE_FIELDS}
)
_SCOPE_FIELDS = _INTENT_FIELDS | {"version", "target_text", "is_evidence"}
_URL = re.compile(r"https?://|www\.|\bdoi:|[a-z][a-z0-9+.-]*://", re.I)
_CLAIM = re.compile(
    r"\b(?:according to|i (?:claim|read)|(?:source|paper|article|literature|study) "
    r"(?:says|states|reports|claims)|measured band[ -]?gap)\b",
    re.I,
)
_NEGATED_DIRECTIVE = re.compile(
    r"\b(?:do not|don't|not)\s+(?:need|require|prefer|prioritize|target|use|"
    r"consider|include|select|seek|want|find|choose|compare|look for|search for)|"
    r"\bno need (?:for|to)\b|"
    r"\bnot\s+(?:needed|required|necessary|desired|a priority)\b",
    re.I,
)


def _choices():
    definitions = catalog()
    return (
        {item["id"] for item in definitions["material_classes"]} | {"unknown"},
        {item["id"] for item in definitions["applications"]} | {"unknown"},
    )


def assessment_schema() -> dict:
    """Return the full first-tool schema, retaining decision-only
    compatibility."""
    classes, applications = _choices()
    attribute_meanings = "\n".join(
        f"{item['id']} — {item['label']}: {item['description']}"
        for item in catalog()["attributes"]
    )
    span = {"type": "string", "minLength": 1, "maxLength": 240}
    intent_properties = {
        "material_class": {"type": "string", "enum": sorted(classes)},
        "application": {"type": "string", "enum": sorted(applications)},
        "identity_scope": {"type": "string", "enum": list(IDENTITY_SCOPES)},
        **{
            name: {
                "type": "array",
                "minItems": 1 if name == "target_spans" else 0,
                "maxItems": 3,
                "uniqueItems": True,
                "items": deepcopy(span),
            }
            for name in _ROLE_FIELDS
        },
        "goals": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "attribute_id": {
                        "type": "string",
                        "enum": sorted(ATTRIBUTE_IDS),
                        "description": (
                            "Choose the criterion by its catalog meaning, not only "
                            "its identifier. These definitions describe preferences, "
                            "never facts about a candidate.\n" + attribute_meanings
                        ),
                    },
                    "request_span": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 300,
                    },
                    "priority": {"type": "string", "enum": list(PRIORITIES)},
                    "relation": {
                        "type": "string",
                        "enum": list(RELATIONS),
                        "description": "Desired direction of the catalog criterion "
                        "itself, not a raw proxy: maximize stability means more "
                        "stable, not greater hull energy. Use target for an "
                        "explicit requested value; never supply that value here.",
                    },
                },
                "required": ["attribute_id", "request_span", "priority", "relation"],
                "additionalProperties": False,
            },
        },
    }
    intent_properties["material_class"]["description"] = (
        "Class of the material sought, not its substrate, environment or device. "
        "Use unknown for unresolved or mixed classes."
    )
    intent_properties["application"][
        "description"
    ] = "Requested use; use unknown when no application is stated."
    intent_properties["identity_scope"]["description"] = (
        "Identity or scale requested for the target material; never a fact about "
        "a candidate. Use unspecified when unclear."
    )
    for name in _ROLE_FIELDS:
        intent_properties[name]["description"] = (
            "Exact substrings of the original request for this role. Keep target "
            "and contextual snippets separate. Use an empty list if unstated."
            if name != "target_spans"
            else "One to three exact substrings naming the sought material family "
            "or user-specified comparison. Exclude applications, environments, "
            "processing, negated subjects and source claims."
        )
    intent_properties["goals"]["description"] = (
        "Positive user preferences only, with one entry per catalog attribute. "
        "Each snippet must be literal request text, not a source claim. "
        "No candidate values, invented targets or arbitrary weights. "
        "Before submitting, review the requested functional use and every retained "
        "processing or environment span for preferences that need a goal. "
        "Include all corresponding catalog preferences, not just the first. "
        "A role span can be context only: do not turn context into a requested "
        "goal automatically. When no criterion fits, preserve the role span "
        "without inventing a proxy criterion."
    )
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": list(DECISIONS)},
            "intent": {
                "type": "object",
                "properties": intent_properties,
                "required": list(intent_properties),
                "additionalProperties": False,
            },
        },
        "required": ["decision"],
        "additionalProperties": False,
    }


def _span_shape(value, maximum):
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value == value.strip()
        and not _URL.search(value)
        and source_instruction_reason(value) is None
        and not any(unicodedata.category(char).startswith("C") for char in value)
    )


def _valid_intent(value):
    if not isinstance(value, dict) or set(value) != _INTENT_FIELDS:
        return False
    classes, applications = _choices()
    for name, choices in (
        ("material_class", classes),
        ("application", applications),
        ("identity_scope", IDENTITY_SCOPES),
    ):
        if not isinstance(value[name], str) or value[name] not in choices:
            return False
    for field in _ROLE_FIELDS:
        spans = value[field]
        if (
            not isinstance(spans, list)
            or not (1 if field == "target_spans" else 0) <= len(spans) <= 3
            or any(not _span_shape(span, 240) for span in spans)
            or len(set(spans)) != len(spans)
        ):
            return False
    goals = value["goals"]
    if not isinstance(goals, list) or len(goals) > 8:
        return False
    seen = set()
    for goal in goals:
        if (
            not isinstance(goal, dict)
            or not {"attribute_id", "request_span", "priority"}
            <= set(goal)
            <= {"attribute_id", "request_span", "priority", "relation"}
            or not isinstance(goal["attribute_id"], str)
            or goal["attribute_id"] not in ATTRIBUTE_IDS
            or goal["attribute_id"] in seen
            or not _span_shape(goal["request_span"], 300)
            or not isinstance(goal["priority"], str)
            or goal["priority"] not in PRIORITIES
            or not isinstance(goal.get("relation", "consider"), str)
            or goal.get("relation", "consider") not in RELATIONS
        ):
            return False
        seen.add(goal["attribute_id"])
    return True


def valid_assessment_arguments(arguments) -> bool:
    """Validate bounded transport shape; original-text binding is
    parent-owned."""
    if (
        not isinstance(arguments, dict)
        or not {"decision"} <= set(arguments) <= {"decision", "intent"}
        or not isinstance(arguments["decision"], str)
        or arguments["decision"] not in DECISIONS
    ):
        return False
    try:
        if len(json.dumps(arguments, allow_nan=False).encode()) > MAX_ARGUMENT_BYTES:
            return False
        return "intent" not in arguments or _valid_intent(arguments["intent"])
    except (ValueError, TypeError, RecursionError):
        return False


def _positive_span(prompt, span):
    if _NEGATED_DIRECTIVE.search(span):
        return False
    # Role snippets cannot promote a negated class or a quoted source assertion
    # into the user's requested subject/goal. Repeated ambiguous uses are rejected.
    occurrences = list(re.finditer(re.escape(span), prompt))
    for match in occurrences:
        prefix = prompt[: match.start()].casefold()
        if re.search(
            r"\b(?:do not|don't)\s+(?:find|choose|compare|look for|search for)\s+"
            r"(?:(?:a|an|the|any)\s+)?$",
            prefix[-100:],
        ):
            return False
        if _negated_preference(
            prefix + prompt[match.start() :].casefold(),
            len(prefix),
            len(prefix) + len(span.casefold()),
        ):
            return False
        sentence_start = max(
            (
                boundary.end()
                for boundary in re.finditer(r"[.!?]\s+|\n", prompt[: match.start()])
            ),
            default=0,
        )
        sentence_end = re.search(r"[.!?]\s+|\n", prompt[match.end() :])
        end = match.end() + sentence_end.start() if sentence_end else len(prompt)
        if _CLAIM.search(prompt[sentence_start:end]):
            return False
    return bool(occurrences)


def _bound_intent(intent, prompt):
    if not isinstance(prompt, str) or not 1 <= len(prompt) <= 20_000:
        raise ValueError("Invalid semantic research request.")
    for field in _ROLE_FIELDS:
        for span in intent[field]:
            if span not in prompt:
                raise ValueError("Semantic spans must match the original request.")
            if field in {"target_spans", "application_spans"} and not _positive_span(
                prompt, span
            ):
                raise ValueError("Semantic subjects must be positive request context.")
    targets = intent["target_spans"]
    for field in ("application_spans", "environment_spans", "processing_spans"):
        if any(
            left in right or right in left
            for left in targets
            for right in intent[field]
        ):
            raise ValueError("Target and context spans must describe separate roles.")
    if intent["application"] != "unknown" and not intent["application_spans"]:
        raise ValueError("An application preference needs literal request context.")
    for goal in intent["goals"]:
        if not _positive_span(prompt, goal["request_span"]):
            raise ValueError("A semantic goal must match a positive user request.")
    normalized = deepcopy(intent)
    for goal in normalized["goals"]:
        goal.setdefault("relation", "consider")
    return {
        **normalized,
        "version": INTENT_VERSION,
        "target_text": " ".join(targets),
        "is_evidence": False,
    }


def validate_scope(scope, prompt) -> dict:
    """Revalidate exact request binding and derived fields at each
    boundary."""
    if (
        not isinstance(scope, dict)
        or set(scope) != _SCOPE_FIELDS
        or scope.get("version") != INTENT_VERSION
        or scope.get("is_evidence") is not False
    ):
        raise ValueError("Invalid semantic research scope.")
    intent = {field: scope[field] for field in _INTENT_FIELDS}
    if not valid_assessment_arguments(
        {"decision": "materials_research", "intent": intent}
    ):
        raise ValueError("Invalid semantic research scope.")
    bound = _bound_intent(intent, prompt)
    if scope != bound:
        raise ValueError("Semantic scope does not match its original request.")
    return bound


def _preserve_profile(profile, selection):
    if profile is None and selection is None:
        return False
    if not isinstance(selection, dict) or selection.get("mode") not in {
        "inferred",
        "fallback",
        "semantic_inferred",
    }:
        return True
    if not isinstance(profile, dict):
        return False
    identifier = profile.get("id")
    return not isinstance(identifier, str) or not (
        identifier in {key for key, _ in PRESETS} or identifier.startswith("inferred-")
    )


def review_only_attributes(scope, profile) -> list[dict]:
    """Flag selected goals the catalog utility cannot score as
    requested.

    Call after validate_scope binds the request. Only criterion
    direction and server-owned preference values are inspected; no
    material evidence enters. The caller preserves explicit-profile
    authority; inferred profiles can keep incompatible goals visible and
    unscored instead of applying an opposite utility.
    """
    if scope is None:
        return []
    if (
        not isinstance(scope, dict)
        or set(scope) != _SCOPE_FIELDS
        or scope.get("version") != INTENT_VERSION
        or scope.get("is_evidence") is not False
        or not _valid_intent({field: scope[field] for field in _INTENT_FIELDS})
        or not isinstance(profile, dict)
        or not isinstance(profile.get("importance"), dict)
    ):
        raise ValueError("Invalid directional goal preferences.")
    directions = {
        "stability": "maximize",
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
    reviews = []
    for goal in scope["goals"]:
        attribute = goal["attribute_id"]
        importance = profile["importance"].get(attribute, 0)
        if (
            type(importance) not in (int, float)
            or not math.isfinite(importance)
            or not 0 <= importance <= 1
        ):
            raise ValueError("Invalid directional goal importance.")
        if importance <= 0:
            continue
        relation = goal.get("relation", "consider")
        reason = None
        if attribute not in SUPPORTED_ATTRIBUTES:
            reason = (
                "This selected criterion has no reviewed scoring utility; "
                "the requested goal requires evidence review."
            )
        elif relation == "target":
            # Existing parsing is limited to numeric band-gap targets. Bind a
            # supported target to both its literal requested goal and the actual
            # profile; an unrelated saved target cannot satisfy a new request.
            parsed, adjustments = prompt_preferences(
                {"importance": {"band_gap": 0.5}},
                "Prefer " + goal["request_span"],
            )
            expected = parsed.get("target_band_gap_ev")
            actual = profile.get("target_band_gap_ev")
            tolerance = profile.get("band_gap_tolerance_ev")
            if tolerance is None:
                tolerance = DEFAULT_TARGET_BAND_GAP_TOLERANCE_EV
            stated_tolerance = any(
                item.get("tolerance_origin") == "prompt_preference"
                for item in adjustments
            )
            if (
                attribute != "band_gap"
                or type(expected) not in (int, float)
                or type(actual) not in (int, float)
                or not math.isfinite(actual)
                or actual != expected
                or type(tolerance) not in (int, float)
                or not math.isfinite(tolerance)
                or not 0 < tolerance <= 100
                or stated_tolerance
                and tolerance != parsed.get("band_gap_tolerance_ev")
                or any(item["status"] == "needs_clarification" for item in adjustments)
            ):
                reason = (
                    "The requested target has no supported, unambiguous "
                    "server-parsed target utility matching this profile."
                )
        elif relation != "consider":
            if (
                attribute == "band_gap"
                and profile.get("target_band_gap_ev") is not None
            ):
                reason = (
                    "This profile uses a band-gap target utility, which "
                    "does not implement the requested directional goal."
                )
            elif directions.get(attribute) != relation:
                reason = (
                    "The catalog utility does not implement the requested "
                    "direction for this criterion; the goal requires evidence review."
                )
        if reason is not None:
            reviews.append(
                {"attribute_id": attribute, "relation": relation, "reason": reason}
            )
    return reviews


def resolve_intent(prompt, arguments, profile, selection) -> dict:
    """Resolve a validated per-run preference snapshot; never mutate the
    inputs."""
    if not valid_assessment_arguments(arguments):
        raise ValueError("Invalid semantic research assessment.")
    result = {
        "profile": deepcopy(profile),
        "selection": deepcopy(selection),
        "scope": None,
    }
    if "intent" not in arguments or arguments["decision"] != "materials_research":
        return result
    scope = _bound_intent(arguments["intent"], prompt)
    result["scope"] = scope
    if _preserve_profile(profile, selection):
        return result
    unknown_class = scope["material_class"] == "unknown"
    application = scope["application"]
    if application == "unknown" or unknown_class:
        application = "property_exploration"
    selected = compose_catalog_profile(
        "custom" if unknown_class else scope["material_class"], application
    )
    if unknown_class:
        selected["name"] = "Unresolved material class · Property exploration"
    selected, adjustments = apply_semantic_goals(selected, prompt, scope["goals"])
    selection = {
        **deepcopy(selection or {}),
        "mode": "semantic_inferred",
        "selected_profile_id": selected["id"],
        "inference_version": INTENT_VERSION,
        "reason": (
            "The requested material class remains unresolved. Used neutral "
            "property-exploration preferences and retained the scope uncertainty; "
            "no saved profile changed."
            if unknown_class
            else "Interpreted the requested material separately from its "
            "application and environment. Used catalog preferences for this run; "
            "no saved profile changed and no material facts came from the model."
        ),
    }
    if adjustments:
        selection["preference_adjustments"] = adjustments
    else:
        selection.pop("preference_adjustments", None)
    result.update(profile=selected, selection=selection)
    return result
