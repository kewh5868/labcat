"""Optional run counters never block history or disclose unvalidated
metadata."""

import json
import sqlite3
from copy import deepcopy

import pytest

from labcat.assessment_completion import CompletionObserver
from labcat.config import load_config
from labcat.workspace import WorkspaceStore, _sanitize_assessment_completion


def outcome_fixture(completion):
    return {
        "untouched": {"original": [1, 2, 3]},
        "build_plan": {
            "candidate_evaluation": {
                "task_completion": deepcopy(completion),
                "batches": 1,
            }
        },
        "execution": {
            "build_plan": {
                "candidate_evaluation": {"task_completion": deepcopy(completion)}
            }
        },
    }


@pytest.mark.parametrize("value", [None, [], "old value", {}, {"execution": []}])
def test_absent_completion_leaves_historical_shapes_unchanged(value):
    original = deepcopy(value)
    _sanitize_assessment_completion(value)
    assert value == original


def test_valid_completion_is_retained_as_a_copy_in_both_locations():
    envelope = CompletionObserver().export()
    value = outcome_fixture(envelope)
    original = deepcopy(value)
    top = value["build_plan"]["candidate_evaluation"]["task_completion"]
    nested = value["execution"]["build_plan"]["candidate_evaluation"]["task_completion"]
    _sanitize_assessment_completion(value)
    assert value == original
    assert value["build_plan"]["candidate_evaluation"]["task_completion"] is not top
    assert (
        value["execution"]["build_plan"]["candidate_evaluation"]["task_completion"]
        is not nested
    )


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "TEST_ONLY_REJECTED_MODEL_TEXT",
        ["TEST_ONLY_REJECTED_MODEL_TEXT"],
        {"version": "unknown", "raw": "TEST_ONLY_REJECTED_MODEL_TEXT"},
    ],
)
def test_invalid_optional_metadata_is_omitted_without_hiding_report(invalid):
    value = outcome_fixture(invalid)
    _sanitize_assessment_completion(value)
    assert value == {
        "untouched": {"original": [1, 2, 3]},
        "build_plan": {"candidate_evaluation": {"batches": 1}},
        "execution": {"build_plan": {"candidate_evaluation": {}}},
    }


def test_one_invalid_mirror_does_not_delete_valid_other_location():
    value = outcome_fixture(CompletionObserver().export())
    value["execution"]["build_plan"]["candidate_evaluation"]["task_completion"][
        "raw"
    ] = "TEST_ONLY_REJECTED_MODEL_TEXT"
    _sanitize_assessment_completion(value)
    assert value["build_plan"]["candidate_evaluation"]["task_completion"]
    assert value["execution"]["build_plan"]["candidate_evaluation"] == {}


def test_workspace_read_redacts_invalid_metadata_without_rewriting_saved_bytes(
    tmp_path,
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("Synthetic history boundary")
    chat = store.create_chat(project["id"], "Synthetic history boundary")
    detail = store.append_message(
        project["id"], chat["id"], "Compare useful materials", load_config()
    )
    report_id = detail["reports"][0]["id"]
    value = outcome_fixture(CompletionObserver().export())
    value["build_plan"]["candidate_evaluation"]["task_completion"][
        "extra"
    ] = "TEST_ONLY_REJECTED_MODEL_TEXT"
    serialized = json.dumps(value, sort_keys=True)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO research_runs VALUES (?,?,?)",
            (report_id, project["id"], serialized),
        )
    returned = store.get_chat(project["id"], chat["id"])["reports"][0]
    assert returned["id"] == report_id
    assert "TEST_ONLY_REJECTED_MODEL_TEXT" not in json.dumps(returned["result"])
    assert returned["result"]["untouched"] == value["untouched"]
    assert returned["result"]["execution"] == value["execution"]
    with sqlite3.connect(store.path) as connection:
        saved = connection.execute(
            "SELECT outcome_json FROM research_runs WHERE report_id=?", (report_id,)
        ).fetchone()[0]
    assert saved == serialized
