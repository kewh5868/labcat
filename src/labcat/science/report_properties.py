"""Compact property selection from saved preferences, never scientific
values."""

import math

MAX_DISPLAY_PROPERTIES = 3
_NON_PROPERTIES = frozenset(
    {
        "application_fit",
        "demonstrated_use",
        "evidence_quality",
        "simplicity",
        "element_screen",
    }
)


def grouped_explicit_property_ids(criteria, goals):
    """One display priority per literal request span, not per model
    synonym.

    Distinct explicit spans remain distinct. Grouping affects only the
    compact three-property view; all criteria and their original weights
    remain intact.
    """
    weights = {
        item["criterion_id"]: item["weight"]
        for item in criteria
        if isinstance(item, dict)
        and isinstance(item.get("criterion_id"), str)
        and item["criterion_id"] not in _NON_PROPERTIES
        and type(item.get("weight")) in (int, float)
        and math.isfinite(item["weight"])
        and item["weight"] > 0
    }
    groups = {}
    priorities = {"primary": 2, "normal": 1, "secondary": 0}
    for goal in goals:
        key = goal.get("attribute_id") if isinstance(goal, dict) else None
        if not isinstance(key, str) or key not in weights:
            continue
        span = goal.get("request_span")
        # Older lexical adjustments lack spans; keep their explicit IDs.
        group = (
            ("span", " ".join(span.split()).casefold())
            if isinstance(span, str) and span.strip()
            else ("id", key)
        )
        priority = (priorities.get(goal.get("priority"), 1), weights[key])
        previous = groups.get(group)
        if previous is None or priority > previous[1]:
            groups[group] = (key, priority)
    return list(dict.fromkeys(key for key, _ in groups.values()))


def selected_property_ids(criteria, *, explicit_ids=(), application_ids=()):
    """Prefer explicit positive-weight goals, then saved
    application/profile weights.

    This never mines request text for numbers or turns a target into a
    value. Missing properties remain selected so comparisons stay
    consistent per row.
    """
    available = {
        item["criterion_id"]: item["weight"]
        for item in criteria
        if isinstance(item, dict)
        and isinstance(item.get("criterion_id"), str)
        and item["criterion_id"] not in _NON_PROPERTIES
        and type(item.get("weight")) in (int, float)
        and math.isfinite(item["weight"])
        and item["weight"] > 0
    }
    # Goals here have already been rebound to the saved profile by the report
    # validator. Use only their criterion ID for display, never the target as a
    # reported value. An enabled target/minimum remains visible even if other
    # properties have higher weights in a manually selected profile.
    targets = [
        item["criterion_id"]
        for item in criteria
        if isinstance(item, dict)
        and item.get("criterion_id") == "band_gap"
        and isinstance(item.get("goal"), dict)
        and any(
            type(item["goal"].get(field)) in (int, float)
            and math.isfinite(item["goal"][field])
            and 0 <= item["goal"][field] <= 100
            for field in ("minimum_band_gap_ev", "target_band_gap_ev")
        )
    ]
    ordered = list(
        dict.fromkeys(
            key
            for key in (*explicit_ids, *targets, *application_ids)
            if key in available
        )
    )
    ordered += sorted(
        (key for key in available if key not in ordered),
        key=lambda key: (-available[key], key),
    )
    return ordered[:MAX_DISPLAY_PROPERTIES]
