"""Developer-only configuration of bounded research actions, never
evidence policy.

The user edition applies installed defaults but exposes no configuration
routes. No setting can add a host, tool, credential, system prompt or
scientific fact.
"""

import re
from copy import deepcopy

LIMITS = {
    "max_reference_results": (1, 10),
    "max_attribute_queries": (1, 3),
    "max_article_downloads": (1, 6),
    "literature_timeout_seconds": (3, 15),
    "max_agent_tool_calls": (2, 8),
}


IMMUTABLE = [
    "Only approved public-source adapters can establish scientific evidence.",
    "User messages, model memory and retrieved instructions never establish facts.",
    "Private data, paywalled content and wetlab actions remain unavailable.",
    "The agent cannot access host files, system settings or arbitrary tools.",
    "Citations, missing evidence and scientific caveats stay in every report.",
]


def defaults():
    return {
        "reference_search": True,
        "literature_followup": True,
        "allow_preprints": True,
        "include_history": True,
        "viewer_enabled": True,
        "max_reference_results": 10,
        "max_attribute_queries": 3,
        "max_article_downloads": 6,
        "literature_timeout_seconds": 15,
        "max_agent_tool_calls": 8,
        "default_model_account_id": None,
    }


def validate_controls(value):
    if not isinstance(value, dict) or value.keys() != defaults().keys():
        raise ValueError("Provide only the supported developer research controls.")
    for field in (
        "reference_search",
        "literature_followup",
        "allow_preprints",
        "include_history",
        "viewer_enabled",
    ):
        if type(value[field]) is not bool:
            raise ValueError("Research actions must be enabled or disabled.")
    for field, (low, high) in LIMITS.items():
        if type(value[field]) is not int or not low <= value[field] <= high:
            raise ValueError(f"{field} must be an integer between {low} and {high}.")
    account = value["default_model_account_id"]
    if account is not None and (
        not isinstance(account, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", account)
    ):
        raise ValueError("Choose a saved default model connection.")
    return deepcopy(value)


def effective_sources(preferences, controls):
    """Intersect user choices with deployment limits; never enable a
    source."""
    result = deepcopy(preferences)
    result["search_public_references"] &= controls["reference_search"]
    result["max_results_per_source"] = min(
        result["max_results_per_source"], controls["max_reference_results"]
    )
    if not controls["allow_preprints"]:
        result["enabled_sources"] = [
            s for s in result["enabled_sources"] if s not in {"arxiv", "chemrxiv"}
        ]
    return result
