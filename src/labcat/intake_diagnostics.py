"""Closed, non-evidentiary execution metadata for responses without
reports.

Model identifiers describe the parent's selected/attempted
configuration. An attempt can fail before dispatch; neither field proves
a provider request ran or attests to a resolved model. Never retain
model prose, account IDs, source text, credentials, or arbitrary
execution dictionaries here.
"""

import re
from copy import deepcopy

from labcat.agent_rejections import PARENT_REJECTION_REASONS
from labcat.goose_runtime import (
    MAX_TOOL_CALLS,
    RESEARCH_TOOLS,
    safe_worker_rejection_diagnostics,
)
from labcat.provider_catalog import API_KEY_PROVIDERS

_PROVIDERS = {"none", "chatgpt", "ollama", "bedrock", *API_KEY_PROVIDERS}
_MODES = {"not_run", "goose", "model"}
_STATUSES = {"not_run", "completed", "stopped_after_report", "interrupted", "unknown"}
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}\Z")
_FIELDS = {
    "version",
    "is_evidence",
    "identity_scope",
    "provider",
    "mode",
    "requested_model",
    "attempted_model",
    "provider_resolved_model",
    "execution_status",
    "tool_trace",
    "parent",
    "worker_rejections",
}


def _selector(value):
    return value if type(value) is str and _MODEL.fullmatch(value) else None


def validate_intake_diagnostics(value):
    """Reject unknown fields and malformed metadata, including bool
    counters."""

    def reject():
        raise ValueError("Invalid intake execution diagnostics.")

    if type(value) is not dict or set(value) != _FIELDS:
        reject()
    if (
        value["version"] != "intake-execution-v1"
        or value["is_evidence"] is not False
        or value["identity_scope"] != "parent_requested_configuration"
        or type(value["provider"]) is not str
        or value["provider"] not in _PROVIDERS
        or type(value["mode"]) is not str
        or value["mode"] not in _MODES
        or type(value["execution_status"]) is not str
        or value["execution_status"] not in _STATUSES
        or value["provider_resolved_model"] is not None
    ):
        reject()
    for key in ("requested_model", "attempted_model"):
        if value[key] is not None and _selector(value[key]) is None:
            reject()
    if value["mode"] == "not_run" and (
        value["execution_status"] != "not_run"
        or value["attempted_model"] is not None
        or value["tool_trace"] != []
        or value["worker_rejections"] is not None
        or value["parent"] is not None
    ):
        reject()
    trace = value["tool_trace"]
    if type(trace) is not list or len(trace) > MAX_TOOL_CALLS:
        reject()
    for row in trace:
        if (
            type(row) is not dict
            or set(row) != {"tool", "status"}
            or type(row["tool"]) is not str
            or row["tool"] not in RESEARCH_TOOLS
            or type(row["status"]) is not str
            or row["status"] not in {"started", "completed", "rejected"}
        ):
            reject()
    parent = value["parent"]
    if parent is not None:
        if type(parent) is not dict or set(parent) != {
            "tool_calls_received",
            "tool_call_limit",
            "intent_assessed",
            "accepted_intake_decision",
            "rejections",
        }:
            reject()
        limit = parent["tool_call_limit"]
        if (
            type(limit) is not int
            or not 1 <= limit <= MAX_TOOL_CALLS
            or type(parent["tool_calls_received"]) is not int
            or not 0 <= parent["tool_calls_received"] <= limit
            or type(parent["intent_assessed"]) is not bool
        ):
            reject()
        decision = parent["accepted_intake_decision"]
        if (
            decision is not None
            and (
                type(decision) is not str
                or decision
                not in {
                    "materials_research",
                    "needs_clarification",
                    "out_of_scope",
                    "unsafe",
                }
            )
        ) or parent["intent_assessed"] != (decision is not None):
            reject()
        rejected = parent["rejections"]
        if (
            type(rejected) is not dict
            or set(rejected) != {"counts", "per_code_limit", "counts_saturated"}
            or type(rejected["per_code_limit"]) is not int
            or rejected["per_code_limit"] != limit
            or type(rejected["counts_saturated"]) is not bool
            or type(rejected["counts"]) is not dict
            or set(rejected["counts"]) - PARENT_REJECTION_REASONS
            or any(
                type(n) is not int or not 1 <= n <= limit
                for n in rejected["counts"].values()
            )
        ):
            reject()
    if value["worker_rejections"] is not None:
        safe_worker_rejection_diagnostics(value["worker_rejections"])
    return deepcopy(value)


def intake_diagnostics(execution):
    """Project only known metadata; invalid diagnostics never prevent a
    refusal."""
    if type(execution) is not dict:
        return None
    mode = execution.get("mode")
    if type(mode) is not str or mode not in _MODES:
        return None
    agent = execution.get("agent")
    agent = agent if type(agent) is dict else {}
    status = (
        "not_run"
        if mode == "not_run"
        else (
            "interrupted"
            if execution.get("model_interrupted") is True
            else agent.get("status", "unknown")
        )
    )
    plan = execution.get("build_plan")
    parent = None
    if mode == "goose" and type(plan) is dict:
        parent = {
            key: plan.get(key)
            for key in (
                "tool_calls_received",
                "tool_call_limit",
                "intent_assessed",
                "accepted_intake_decision",
            )
        }
        parent["rejections"] = plan.get("parent_rejections")
    attempted = None
    if mode != "not_run":
        attempted = _selector(agent.get("model") or execution.get("attempted_model"))
    value = {
        "version": "intake-execution-v1",
        "is_evidence": False,
        "identity_scope": "parent_requested_configuration",
        "provider": execution.get("provider"),
        "mode": mode,
        "requested_model": _selector(execution.get("requested_model")),
        "attempted_model": attempted,
        "provider_resolved_model": None,
        "execution_status": status,
        "tool_trace": agent.get("tool_trace", []) if mode == "goose" else [],
        "parent": parent,
        "worker_rejections": (
            agent.get(
                "worker_rejection_diagnostics",
                execution.get("worker_rejection_diagnostics"),
            )
            if mode == "goose"
            else None
        ),
    }
    try:
        return validate_intake_diagnostics(value)
    except (ValueError, TypeError, RecursionError):
        return None
