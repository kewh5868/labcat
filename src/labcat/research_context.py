"""Reuse chat preferences and source identities without trusting saved
prose."""

import re
from copy import deepcopy

from labcat.intake import resets_scope
from labcat.ranking_profiles import (
    INFERENCE_VERSION,
    normalize_importance,
    prompt_preferences,
    validate_profile,
)


def continuation(context, prompt, *, enabled=True):
    """Return bounded server context only for the current, continuing
    chat."""
    if not enabled or resets_scope(prompt) or not isinstance(context, dict):
        return {}
    active = context.get("active_chat")
    if not isinstance(active, dict) or not active.get("latest_completed_report_id"):
        return {}
    return active


def select_profile(store, requested, prompt, context, *, enabled=True):
    """Explicit selection wins; otherwise preserve the last report's
    preferences."""
    active = continuation(context, prompt, enabled=enabled)
    previous = active.get("ranking_profile")
    if requested in (None, "infer") and isinstance(previous, dict):
        try:
            profile = validate_profile(
                {
                    key: previous[key]
                    for key in (
                        "name",
                        "material_class",
                        "application",
                        "importance",
                        "minimum_band_gap_ev",
                        "target_band_gap_ev",
                        "band_gap_tolerance_ev",
                    )
                    if key in previous
                }
            )
            identifier = previous["id"]
            if not isinstance(identifier, str) or not 1 <= len(identifier) <= 120:
                raise ValueError
        except (KeyError, ValueError, TypeError):
            pass
        else:
            profile.update(
                id=identifier,
                normalized_weights=normalize_importance(profile["importance"]),
            )
            profile, adjustments = prompt_preferences(profile, prompt)
            selection = {
                "mode": "continued",
                "reason": (
                    "Continued this chat's saved ranking preferences, applying "
                    "any explicit new property goals to this run only. "
                    "Select a profile explicitly to replace them."
                ),
                "requested_profile_id": requested,
                "selected_profile_id": identifier,
                "previous_report_id": active["latest_completed_report_id"],
                "inference_version": None,
            }
            if adjustments:
                selection["preference_adjustments"] = adjustments
                selection["inference_version"] = INFERENCE_VERSION
            return profile, selection
    return store.select(requested, prompt)


def material_hints(context, prompt, *, enabled=True):
    """Canonical adapter identities are search hints, never cached
    measurements."""
    active = continuation(context, prompt, enabled=enabled)
    rows = active.get("source_hints", [])
    if not isinstance(rows, list):
        return []
    hints = []
    for row in rows[:40]:
        if not isinstance(row, dict) or not isinstance(row.get("url"), str):
            continue
        url = row["url"]
        match = re.fullmatch(
            r"https://nomad-lab\.eu/prod/v1/gui/search/entries/entry/id/"
            r"([A-Za-z0-9_-]{1,80})",
            url,
        )
        mp = re.fullmatch(
            r"https://(?:next-gen\.)?materialsproject\.org/materials/(mp-[0-9]{1,10})",
            url,
        )
        identity = "nomad:" + match[1] if match else mp[1] if mp else None
        if (
            url == "https://doi.org/10.6084/m9.figshare.7108790.v2"
            and isinstance(row.get("record_id"), str)
            and re.fullmatch(
                r"dielectric:mp-[0-9]{1,10}(?::row[0-9]{1,4})?", row["record_id"]
            )
        ):
            identity = row["record_id"]
        if identity and identity not in hints:
            hints.append(identity)
        if len(hints) == 6:
            break
    return deepcopy(hints)
