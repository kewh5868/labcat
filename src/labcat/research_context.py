"""Reuse chat preferences and source identities without trusting saved
prose."""

import re
from copy import deepcopy

from labcat.intake import assess, resets_scope


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
    """Keep manual choices fixed; infer from bounded user context each
    run."""
    if requested != "infer":
        # An omitted selection retains the API's active-profile contract. A
        # concrete ID always wins, regardless of current or previous prompts.
        return store.select(requested, prompt)
    _, effective_prompt = assess(prompt, context=context if enabled else None)
    # Saved reports are historical outcomes, not a new manual selection. In
    # particular, a past fallback must never freeze future automatic inference.
    return store.select("infer", effective_prompt)


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
