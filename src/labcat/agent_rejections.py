"""Fixed parent-owned repair guidance; exception contents never cross
the boundary."""

from types import MappingProxyType


class WorkerRejectionError(ValueError):
    """Shared marker for worker validation across imported and module
    entrypoints."""


class AgentToolError(ValueError):
    """An expected rejected action, optionally classified by a server-
    owned code."""

    def __init__(self, *args, reason_code: str | None = None):
        super().__init__(*args)
        self.reason_code = reason_code


_CORRECTIONS = MappingProxyType(
    {
        "tool_call_limit": "The tool-call budget is exhausted. Stop requesting tools; "
        "the parent will retain available results without inventing evidence.",
        "unsupported_tool": "Use only the tools in the supplied tool catalog. "
        "No other action or destination is available.",
        "intake_catalog_or_shape": "Use the supplied intake schema and catalog IDs. "
        "Supply only supported fields and bounded values; no interpretation "
        "was accepted by this call.",
        "intake_binding_failed": "Recheck the intake catalog, exact original request "
        "spans, separate target/context roles and goal preferences. The parent "
        "could not validate this interpretation; no interpretation was accepted.",
        "intake_frozen": "The accepted intake interpretation is already fixed. "
        "Continue with that interpretation instead of changing it.",
        "tool_order": "Follow the tool dependencies: accepted intake, public "
        "discovery, candidate selection, assessment, then report. Selection and "
        "assessment cannot change after their permitted stage.",
        "candidate_selection_arguments": "Use the candidate-selection schema: "
        "bounded literal names and exact quotes from the supplied public documents. "
        "Source numbers may remain in exact quotes; do not add factual fields, "
        "instructions, URLs or remembered candidates.",
        "candidate_selection_batch_limit": "The candidate-selection batch budget "
        "is exhausted. Continue with admitted candidates within the remaining "
        "tool budget; do not submit another selection batch.",
        "evaluation_arguments": "Use the assessment schema and existing byte and "
        "row limits. Submit only bounded candidate, criterion and source selectors "
        "with qualitative judgments; do not add fields or invented evidence.",
        "evaluation_batch_limit": "The assessment batch budget is exhausted. "
        "Generate the report within the remaining tool budget; missing assessments "
        "must stay unknown.",
        "evaluation_binding_failed": "Recheck admitted candidate IDs, selected "
        "criteria and exact excerpts from delivered source documents. The parent "
        "could not safely validate this batch; no new assessments were retained.",
        "invalid_arguments": "Use only the selected tool's supplied argument "
        "schema. Report generation accepts an empty object; discovery accepts "
        "an empty object or a bounded plain-language topic.",
        "discovery_refinement_unavailable": "Discovery refinement is unavailable "
        "after assessment or report generation, or when its pass budget is "
        "exhausted. Continue with retained discovery within the remaining budget.",
        "retrieval_not_authorized": "Retrieval requires accepted research intake. "
        "A refusal or clarification does not authorize source access.",
        "tool_reply_limit": "The parent could not fit this reply within its byte "
        "limit. Do not repeat the same call or invent missing context; use only "
        "already delivered evidence within the remaining tool budget.",
    }
)

PARENT_REJECTION_REASONS = frozenset(_CORRECTIONS) | {"unclassified"}


def parent_rejection_reply(error: Exception) -> dict:
    """Never serialize exception text, arguments, subclasses or unknown
    codes."""
    if type(error) is not AgentToolError:
        return {"status": "rejected"}
    code = getattr(error, "reason_code", None)
    if type(code) is not str or code not in _CORRECTIONS:
        return {"status": "rejected"}
    return {
        "status": "rejected",
        "reason_code": code,
        "correction": _CORRECTIONS[code],
    }
