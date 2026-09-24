"""Research request and plan boundaries; retrieval is not yet
implemented."""

import re

PLAN_CHOICES = {
    "task": ("materials_triage", "oxide_dielectric_triage", "unsupported"),
    "stability": ("prefer_stable", "any"),
    "band_gap": ("prefer_wide", "any"),
    "element_screen": ("prefer_lower_concern", "any"),
    "simplicity": ("prefer_simple", "any"),
    "evidence": ("public_only",),
}


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
