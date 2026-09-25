"""Bounded Goose runtime with one server-owned public-research
capability.

Goose/model prose is discarded. Only the parent ResearchToolSession can
produce evidence or reports. Goose receives no workspace, URL fetcher,
shell, file, extension-management, scheduling, or private-data tool.

Pinned upstream behavior reviewed at aaif-goose/goose v1.50.0:
crates/goose-cli/src/session/builder.rs (--no-profile and hidden
sessions)   crates/goose-cli/src/session/mod.rs (JSON usage metadata)
crates/goose/src/config/paths.rs (isolated GOOSE_PATH_ROOT)
"""

GOOSE_VERSION = "1.50.0"
MAX_RUNTIME_SECONDS = 180


MAX_TOOL_CALLS = 8


RESEARCH_TOOLS = frozenset(
    {
        "assess_research_intent",
        "search_public_references",
        "propose_candidate_leads",
        "evaluate_candidate_fit",
        "generate_ranked_report",
    }
)


WORKER_REJECTION_REASONS = frozenset(
    {
        "invalid_arguments",
        "evaluation_envelope",
        "evaluation_payload_size",
        "evaluation_quote_length",
        "evaluation_interpretation_format",
    }
)


def safe_worker_rejection_diagnostics(value):
    """Only bounded worker-reported counters survive, never submitted
    content."""
    if (
        not isinstance(value, dict)
        or set(value) != {"scope", "rejections"}
        or value["scope"] != "worker_reported"
        or not isinstance(value["rejections"], list)
        or len(value["rejections"]) > MAX_TOOL_CALLS
    ):
        raise ValueError("Invalid worker rejection diagnostics.")
    rows, seen, total = [], set(), 0
    for row in value["rejections"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"tool", "reason", "count"}
            or not isinstance(row["tool"], str)
            or row["tool"] not in RESEARCH_TOOLS
            or not isinstance(row["reason"], str)
            or row["reason"] not in WORKER_REJECTION_REASONS
            or (
                row["reason"] != "invalid_arguments"
                and row["tool"] != "evaluate_candidate_fit"
            )
            or type(row["count"]) is not int
            or not 1 <= row["count"] <= MAX_TOOL_CALLS
            or (row["tool"], row["reason"]) in seen
        ):
            raise ValueError("Invalid worker rejection diagnostics.")
        total += row["count"]
        seen.add((row["tool"], row["reason"]))
        rows.append(dict(row))
    if total > MAX_TOOL_CALLS:
        raise ValueError("Invalid worker rejection diagnostics.")
    return {"scope": "worker_reported", "rejections": rows}
