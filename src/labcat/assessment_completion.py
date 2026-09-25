"""Aggregate diagnostics for parent-offered assessment tasks, never
evidence.

Only fixed states and bounded counts survive aggregation. The
synchronous parent captures actually delivered selectors before
admission; neither those selectors nor submitted text is retained in
this diagnostic or sent to the model.

Counts describe one attempted batch, not the whole research request.
Offered tasks are the parent's delivered attribute worklist; general
assessments may be unmatched rows. Accepted unknowns do not supply
evidence coverage. Non-unknown includes support, mixed and concern,
without certifying scientific correctness. Task sets may overlap when
multiple submitted rows address the same selector.
"""

import json
import re
from copy import deepcopy
from dataclasses import dataclass

from labcat.science.literature_evaluation import (
    _CRITERION_IDS,
    JUDGMENTS,
)
from labcat.science.literature_evaluation import (
    MAX_EVALUATIONS as MAX_ROWS,
)

VERSION = "assessment-task-completion-v1"
RECORD_LIMIT = 8
TASK_LIMIT = 192  # At most twelve existing tool replies with sixteen tasks each.
MAX_BYTES = 16_384
CATEGORIES = ("format", "selector", "quote_binding", "criterion", "method", "goal")
REASONS = {
    "invalid_row_format": "format",
    "invalid_identity_format": "format",
    "evaluation_quote_length": "format",
    "evaluation_interpretation_format": "format",
    "unknown_lead": "selector",
    "unselected_criterion": "selector",
    "unavailable_document": "selector",
    "quote_or_candidate_not_bound": "quote_binding",
    "criterion_context_missing": "criterion",
    "demonstration_not_established": "method",
    "attribute_requires_source_context": "method",
    "model_input_not_observation": "method",
    "goal_target_unresolved": "goal",
}
ACCEPT_REASONS = {"source_bound_interpretation", "already_retained"}
STATUSES = {"processed", "binding_failed", "transport_rejected", "batch_limit"}


def _selector(row):
    if type(row) is not dict:
        return None
    fields = tuple(row.get(key) for key in ("lead_id", "criterion_id", "document_id"))
    if (
        any(type(value) is not str for value in fields)
        or re.fullmatch(r"lead-[a-f0-9]{24}", fields[0]) is None
        or fields[1] not in _CRITERION_IDS
        or re.fullmatch(r"doc-[a-f0-9]{24}", fields[2]) is None
    ):
        return None
    return fields


@dataclass(frozen=True)
class Submission:
    """Temporary row ordinals and fixed judgment flags; no source/model
    text."""

    offered_tasks: int
    row_ordinals: tuple
    judgments: tuple


def capture(arguments, offered_keys, delivered_documents):
    """Called only after the unchanged bounded transport gate, under
    parent lock.

    offered_keys is an immutable parent snapshot from the successful
    reply gate. Unknown selectors are discarded immediately; only
    matching ordinals survive.
    """
    if (
        type(offered_keys) is not frozenset
        or len(offered_keys) > TASK_LIMIT
        or type(delivered_documents) is not frozenset
        or type(arguments) is not dict
        or set(arguments) != {"evaluations"}
        or type(arguments["evaluations"]) is not list
        or len(arguments["evaluations"]) > MAX_ROWS
    ):
        return None
    for key in offered_keys:
        if type(key) is not tuple or len(key) != 3:
            return None
        if (
            _selector(
                dict(zip(("lead_id", "criterion_id", "document_id"), key, strict=True))
            )
            != key
        ):
            return None
        if key[2] not in delivered_documents:
            return None
    known = {key: ordinal for ordinal, key in enumerate(sorted(offered_keys))}
    ordinals, judgments = [], []
    for row in arguments["evaluations"]:
        ordinals.append(known.get(_selector(row)))
        judgment = row.get("judgment") if type(row) is dict else None
        judgments.append(
            judgment if type(judgment) is str and judgment in JUDGMENTS else None
        )
    return Submission(len(known), tuple(ordinals), tuple(judgments))


def _empty_outcomes():
    return {
        "accepted_unknown": 0,
        "accepted_nonunknown": 0,
        "already_retained": 0,
        "rejected": 0,
        "rejections": dict.fromkeys(CATEGORIES, 0),
    }


def _empty_record(status, context):
    return {"status": status, "context": context, "submission": None, "outcomes": None}


def _project(submission, feedback, status):
    if (
        type(submission) is not Submission
        or type(submission.offered_tasks) is not int
        or not 0 <= submission.offered_tasks <= TASK_LIMIT
        or type(submission.row_ordinals) is not tuple
        or type(submission.judgments) is not tuple
        or len(submission.row_ordinals) > MAX_ROWS
        or len(submission.row_ordinals) != len(submission.judgments)
        or any(
            value is not None
            and (type(value) is not int or not 0 <= value < submission.offered_tasks)
            for value in submission.row_ordinals
        )
        or any(
            value is not None and (type(value) is not str or value not in JUDGMENTS)
            for value in submission.judgments
        )
    ):
        return _empty_record(status, "invalid")
    matches = {
        index: value
        for index, value in enumerate(submission.row_ordinals)
        if value is not None
    }
    matched = set(matches.values())
    record = _empty_record(status, "captured")
    record["submission"] = {
        "offered_tasks": submission.offered_tasks,
        "rows": len(submission.row_ordinals),
        "matched_rows": len(matches),
        "matched_tasks": len(matched),
        "unmatched_rows": len(submission.row_ordinals) - len(matches),
        "unsubmitted_tasks": submission.offered_tasks - len(matched),
    }
    if status == "binding_failed":
        return record
    if type(feedback) is not list or len(feedback) != len(submission.row_ordinals):
        raise ValueError("Invalid assessment completion feedback.")
    indices = set()
    all_rows, matched_rows = _empty_outcomes(), _empty_outcomes()
    unknown, nonunknown, rejected = set(), set(), set()
    for item in feedback:
        if (
            type(item) is not dict
            or set(item) != {"index", "status", "reason"}
            or type(item["index"]) is not int
            or not 0 <= item["index"] < len(submission.row_ordinals)
            or item["index"] in indices
            or type(item["status"]) is not str
            or type(item["reason"]) is not str
        ):
            raise ValueError("Invalid assessment completion feedback.")
        index = item["index"]
        indices.add(index)
        ordinal = matches.get(index)
        targets = [all_rows, matched_rows] if ordinal is not None else [all_rows]
        if item["status"] == "accepted" and item["reason"] in ACCEPT_REASONS:
            judgment = submission.judgments[index]
            if judgment is None:
                raise ValueError("Invalid assessment completion feedback.")
            field = (
                "accepted_unknown" if judgment == "unknown" else "accepted_nonunknown"
            )
            for target in targets:
                target[field] += 1
                target["already_retained"] += item["reason"] == "already_retained"
            if ordinal is not None:
                (unknown if judgment == "unknown" else nonunknown).add(ordinal)
        elif item["status"] == "rejected" and item["reason"] in REASONS:
            for target in targets:
                target["rejected"] += 1
                target["rejections"][REASONS[item["reason"]]] += 1
            if ordinal is not None:
                rejected.add(ordinal)
        else:
            raise ValueError("Invalid assessment completion feedback.")
    record["outcomes"] = {
        "all_rows": all_rows,
        "matched_rows": matched_rows,
        "tasks": {
            "accepted_unknown": len(unknown),
            "accepted_nonunknown": len(nonunknown),
            "accepted": len(unknown | nonunknown),
            "rejected": len(rejected),
            "submitted_without_acceptance": len(matched - (unknown | nonunknown)),
        },
    }
    return record


def validate_record(record):
    """Closed read validator with arithmetic bounds; bool is never a
    count."""
    if type(record) is not dict or set(record) != {
        "status",
        "context",
        "submission",
        "outcomes",
    }:
        return False
    if type(record["status"]) is not str or type(record["context"]) is not str:
        return False
    if record["status"] not in STATUSES or record["context"] not in {
        "captured",
        "not_inspected",
        "invalid",
    }:
        return False
    submission, outcomes = record["submission"], record["outcomes"]
    if record["context"] != "captured":
        return (
            submission is None
            and outcomes is None
            and (
                (record["status"] in {"transport_rejected", "batch_limit"})
                == (record["context"] == "not_inspected")
            )
        )
    if record["status"] not in {"processed", "binding_failed"}:
        return False
    fields = {
        "offered_tasks",
        "rows",
        "matched_rows",
        "matched_tasks",
        "unmatched_rows",
        "unsubmitted_tasks",
    }
    if type(submission) is not dict or set(submission) != fields:
        return False
    if not all(
        type(value) is int and 0 <= value <= TASK_LIMIT for value in submission.values()
    ):
        return False
    if (
        submission["rows"] > MAX_ROWS
        or submission["matched_rows"] + submission["unmatched_rows"]
        != submission["rows"]
        or submission["matched_tasks"] + submission["unsubmitted_tasks"]
        != submission["offered_tasks"]
        or submission["matched_tasks"] > submission["matched_rows"]
        or bool(submission["matched_tasks"]) != bool(submission["matched_rows"])
    ):
        return False
    if record["status"] == "binding_failed":
        return outcomes is None
    if type(outcomes) is not dict or set(outcomes) != {
        "all_rows",
        "matched_rows",
        "tasks",
    }:
        return False
    for key, maximum in (
        ("all_rows", submission["rows"]),
        ("matched_rows", submission["matched_rows"]),
    ):
        counts = outcomes[key]
        if type(counts) is not dict or set(counts) != set(_empty_outcomes()):
            return False
        if not all(
            type(counts[k]) is int and 0 <= counts[k] <= maximum
            for k in counts
            if k != "rejections"
        ):
            return False
        reasons = counts["rejections"]
        if type(reasons) is not dict or set(reasons) != set(CATEGORIES):
            return False
        if not all(
            type(value) is int and 0 <= value <= maximum for value in reasons.values()
        ):
            return False
        if (
            sum(reasons.values()) != counts["rejected"]
            or counts["accepted_unknown"]
            + counts["accepted_nonunknown"]
            + counts["rejected"]
            != maximum
            or counts["already_retained"] > maximum - counts["rejected"]
        ):
            return False
    matched_counts, all_counts = outcomes["matched_rows"], outcomes["all_rows"]
    if any(
        matched_counts[key] > all_counts[key]
        for key in matched_counts
        if key != "rejections"
    ):
        return False
    if any(
        matched_counts["rejections"][key] > all_counts["rejections"][key]
        for key in CATEGORIES
    ):
        return False
    if (
        all_counts["already_retained"] - matched_counts["already_retained"]
        > all_counts["accepted_unknown"]
        + all_counts["accepted_nonunknown"]
        - matched_counts["accepted_unknown"]
        - matched_counts["accepted_nonunknown"]
    ):
        return False
    tasks = outcomes["tasks"]
    fields = {
        "accepted_unknown",
        "accepted_nonunknown",
        "accepted",
        "rejected",
        "submitted_without_acceptance",
    }
    if (
        type(tasks) is not dict
        or set(tasks) != fields
        or not all(
            type(value) is int and 0 <= value <= submission["matched_tasks"]
            for value in tasks.values()
        )
    ):
        return False
    return (
        max(tasks["accepted_unknown"], tasks["accepted_nonunknown"])
        <= tasks["accepted"]
        <= tasks["accepted_unknown"] + tasks["accepted_nonunknown"]
        and tasks["accepted"] + tasks["submitted_without_acceptance"]
        == submission["matched_tasks"]
        and tasks["submitted_without_acceptance"] <= tasks["rejected"]
        and all(
            tasks[key] <= matched_counts[key]
            for key in ("accepted_unknown", "accepted_nonunknown", "rejected")
        )
        and all(
            bool(tasks[key]) == bool(matched_counts[key])
            for key in ("accepted_unknown", "accepted_nonunknown", "rejected")
        )
    )


def validate_assessment_completion(value):
    """Validate optional persisted metadata; absence is handled by the
    caller."""
    valid = (
        type(value) is dict
        and set(value)
        == {"version", "is_evidence", "record_limit", "records_saturated", "records"}
        and type(value["version"]) is str
        and value["version"] == VERSION
        and value["is_evidence"] is False
        and type(value["record_limit"]) is int
        and value["record_limit"] == RECORD_LIMIT
        and type(value["records_saturated"]) is bool
        and type(value["records"]) is list
        and len(value["records"]) <= RECORD_LIMIT
        and (not value["records_saturated"] or len(value["records"]) == RECORD_LIMIT)
        and all(validate_record(record) for record in value["records"])
    )
    if not valid or len(json.dumps(value, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError("Invalid assessment completion diagnostics.")
    return deepcopy(value)


class CompletionObserver:
    """Bounded count recorder, with no influence on scientific
    admission."""

    def __init__(self):
        self._records = []
        self._saturated = False

    @property
    def has_records(self):
        return bool(self._records)

    def export(self):
        return validate_assessment_completion(
            {
                "version": VERSION,
                "is_evidence": False,
                "record_limit": RECORD_LIMIT,
                "records_saturated": self._saturated,
                "records": self._records,
            }
        )

    def _append(self, record):
        if len(self._records) >= RECORD_LIMIT:
            self._saturated = True
        elif validate_record(record):
            self._records.append(deepcopy(record))

    def note_uninspected(self, status):
        if type(status) is not str or status not in {
            "transport_rejected",
            "batch_limit",
        }:
            raise ValueError("Invalid assessment completion status.")
        self._append(_empty_record(status, "not_inspected"))

    def finish(self, submission, feedback=None, *, status="processed"):
        if type(status) is not str or status not in {"processed", "binding_failed"}:
            raise ValueError("Invalid assessment completion status.")
        try:
            record = _project(submission, feedback, status)
            if not validate_record(record):
                record = _empty_record(status, "invalid")
        except (
            TypeError,
            ValueError,
            KeyError,
            IndexError,
            AttributeError,
            RecursionError,
        ):
            record = _empty_record(status, "invalid")
        self._append(record)
