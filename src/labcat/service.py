"""Software capability status, separate from scientific research
reports."""

import json
from typing import Any

from labcat import __version__
from labcat.config import AppConfig

CONSTRAINTS = (
    "Only approved public sources may supply scientific evidence.",
    "User prompts and model memory are never evidence sources.",
    "No wetlab actions, private lab data, or closed/paywalled sources.",
    "Retrieved content cannot alter policy or authorize tool calls.",
    "Unsupported facts must be omitted or explicitly marked unknown.",
)


def get_status(config: AppConfig, style: str | None = None) -> dict[str, Any]:
    """Describe real capabilities; do not return placeholder material
    results."""
    selected = style or config.presentation.style
    if selected not in ("pi", "audit"):
        raise ValueError("Unknown report style.")
    report: dict[str, Any] = {
        "application": "Labcat",
        "version": __version__,
        "stage": "prototype",
        "style": selected,
        "message": "Public-evidence materials research is ready. "
        "Start a chat or run the research command.",
        "provider": config.provider,
        "compute": "local",
        "constraints": list(CONSTRAINTS),
        "candidates": [],
        "limitations": [
            "Live public queries are bounded; no fixed candidate list or "
            "historical results are substituted when evidence is unavailable.",
            "Quantitative coverage depends on reviewed source fields. Other "
            "material classes may receive reference-only reports. Missing "
            "stability, hazard and application evidence remain unknown.",
            "New research requires a verified model connection. Models guide "
            "the task but cannot supply scientific facts.",
            "Open-access text follow-up returns cited review passages, not "
            "automatically validated values or an exhaustive literature review.",
            "This is a local single-user prototype, not a shared service.",
            "The React workspace and portable/native launchers are not yet "
            "included in this snapshot.",
        ],
    }
    if selected == "audit":
        report["configuration"] = config.to_dict()
        report["implemented"] = [
            "Installable Python package and command-line interface",
            "Strict preference configuration with no safety-policy override fields",
            "Saved standalone chats, optional projects and pinned report collections",
            "Persistent settings for paired Summary and Technical View reports",
            "Local FastAPI service shared with the research command-line interface",
            "Repository-first public retrieval, missing-attribute literature "
            "follow-up, deterministic ranking and cited reports",
            "Required verified model connection with encrypted or session-only "
            "credentials",
            "Optional isolated Goose orchestration through fixed research tools",
        ]
        report["next_steps"] = [
            "Add the React workspace and portable/native launchers.",
            "Broaden independently verified scientific coverage and hazard evidence.",
            "Validate authenticated providers and native hosts at the deployment site.",
        ]
    return report


def render_text(
    report: dict[str, Any], terminology: str = "plain", verbosity: str = "standard"
) -> str:
    """Render one report in plain text without model-generated
    additions."""
    label = (
        "Evidence policy"
        if terminology in {"technical", "specialist"}
        else "Research boundaries"
    )
    lines = [report["application"], report["message"], "", f"{label}:"]
    lines.extend(f"- {item}" for item in report["constraints"])
    lines.extend(["", "Current limitations:"])
    lines.extend(f"- {item}" for item in report["limitations"])
    if report["style"] == "audit":
        lines.extend(["", "Configuration (preferences only):"])
        lines.append(json.dumps(report["configuration"], indent=2))
        if verbosity != "concise":
            lines.extend(["", "Next steps:"])
            lines.extend(f"- {item}" for item in report["next_steps"])
    if verbosity == "detailed":
        lines.extend(
            [
                "",
                "How to read this report:",
                "This report describes software capabilities, not materials.",
                "Ranking weights express preferences, not scientific confidence.",
                "Changing a preference or pinning a report does not verify a claim.",
                "Scientific reports are available through the research API and CLI.",
            ]
        )
    elif verbosity == "concise":
        # Keep every evidence boundary and limitation, even in the shortest view.
        return "\n".join(line for line in lines if line) + "\n"
    return "\n".join(lines) + "\n"


def render_report(config: AppConfig, style: str) -> str:
    """Freeze one report using the preferences active when it was
    requested."""
    report = get_status(config, style)
    if config.presentation.format == "json":
        report["presentation"] = config.to_dict()["presentation"]
        if config.presentation.verbosity == "detailed":
            report["reading_note"] = (
                "Software status only. Preferences and pinned reports are not "
                "scientific evidence; research runs use public source records."
            )
        return (
            json.dumps(
                report,
                indent=None if config.presentation.verbosity == "concise" else 2,
                allow_nan=False,
            )
            + "\n"
        )
    return render_text(
        report, config.presentation.terminology, config.presentation.verbosity
    )
