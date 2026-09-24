"""Non-secret source selections; public-only boundaries are not
configurable."""

SOURCE_IDS = (
    "hybrid3",
    "nomad",
    "europe_pmc",
    "arxiv",
    "wikipedia",
    "openalex",
    "chemrxiv",
)


def default_source_preferences() -> dict:
    return {
        "search_public_references": True,
        "enabled_sources": list(SOURCE_IDS),
        "materials_project_mode": "auto",
        "max_results_per_source": 5,
    }


def validate_source_preferences(value: dict) -> dict:
    """Accept bounded selections, never URLs, credentials, policies or
    evidence."""
    if (
        not isinstance(value, dict)
        or value.keys() != default_source_preferences().keys()
    ):
        raise ValueError("Provide the supported public source preferences only.")
    if type(value["search_public_references"]) is not bool:
        raise ValueError("Public reference search must be enabled or disabled.")
    enabled = value["enabled_sources"]
    if (
        not isinstance(enabled, list)
        or len(enabled) > len(SOURCE_IDS)
        or any(not isinstance(item, str) or item not in SOURCE_IDS for item in enabled)
        or len(set(enabled)) != len(enabled)
    ):
        raise ValueError("Select each supported public source at most once.")
    if value["materials_project_mode"] not in ("auto", "snapshot", "api", "off"):
        raise ValueError("Choose auto, api or off for Materials Project.")
    limit = value["max_results_per_source"]
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("Choose between 1 and 10 references per source.")
    return {**value, "enabled_sources": enabled.copy()}
