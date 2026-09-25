"""Offline evaluation fixtures are synthetic and never scientific
evidence."""

import json
import sys
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from runpy import run_path
from urllib.error import HTTPError, URLError

import pytest

EVALUATOR = run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "evaluate_live_prompts.py")
)
assess = EVALUATOR["assess"]
CASES = EVALUATOR["CASES"]


def report_detail():
    """Use the persisted workspace schema, including both directions of
    joins."""
    return {
        "chat": {"id": "test-chat", "title": "Perovskites for optoelectronics"},
        "messages": [],
        "reports": [
            {
                "id": "test-report",
                "stage": "partial",
                "pi_summary": "TEST ONLY summary",
                "technical_audit": "TEST ONLY overview",
                "source_ids": ["workspace-source-id"],
                "result": {
                    "execution": {
                        "provider": "test-provider",
                        "agent": {"model": "test-model", "usage": {"total_tokens": 10}},
                        "ranking_profile": {
                            "material_class": "perovskites",
                            "target_band_gap_ev": 1.78,
                            "application": "optoelectronics",
                            "importance": {"band_gap": 1.0, "stability": 0.5},
                        },
                    },
                    "ranking": {
                        "screening_preferences": {"target_band_gap_active": True}
                    },
                    "candidates": [
                        {
                            "material_id": "test-record",
                            "source_ids": ["material:test-record"],
                            "source_mode": "live_hybrid3",
                            "provenance": {
                                "source_url": "https://example.invalid/test-record"
                            },
                            "score": 0.5,
                            "score_contributions": {"band_gap": 0.5},
                            "score_analysis": {"status": "comparable"},
                            "selected_weight_coverage": 0.75,
                            "criterion_available": {
                                "band_gap": True,
                                "stability": False,
                            },
                        }
                    ],
                },
            }
        ],
        "sources": [
            {
                "id": "workspace-source-id",
                "title": "TEST ONLY source",
                "url": "https://example.invalid/test-record",
                "access_scope": "public",
                "provenance_status": "verified",
                "chat_ids": ["test-chat"],
                "report_ids": ["test-report"],
            }
        ],
    }


def reference_detail():
    detail = report_detail()
    result = detail["reports"][0]["result"]
    result["candidates"] = []
    result["execution"]["ranking_profile"]["material_class"] = "polymers"
    result["public_discovery"] = {"reference_count": 1, "used_for_ranking": False}
    detail["sources"][0].update(kind="discovery_reference", is_material_evidence=False)
    detail["chat"]["title"] = "Polymers for flexible optoelectronics"
    return detail


def screening_detail(judgments, *, version="literature-fit-v2"):
    """Build real validated bundles from explicitly synthetic public
    passages."""
    from test_candidate_leads import reference

    from labcat.science.candidate_leads import (
        discovery_documents,
        validate_candidate_leads,
    )
    from labcat.science.literature_evaluation import evaluate_candidates

    detail = reference_detail()
    report = detail["reports"][0]
    result = report["result"]
    profile = {"material_class": "polymers", "importance": {"density": 1}}
    result["execution"]["ranking_profile"] = profile
    references, selectors = [], []
    for index in range(len(judgments)):
        name = "TESTONLY-" + chr(ord("A") + index)
        quote = (
            f"TEST ONLY: {name} was experimentally tested and used in flexible "
            "devices with low density and room-temperature phase stability."
        )
        source = reference(index + 1, text=quote)
        source.update(
            id=f"workspace-source-{index}",
            report_ids=[report["id"]],
            chat_ids=[detail["chat"]["id"]],
        )
        references.append(source)
        selectors.append(
            {
                "document_id": discovery_documents([source])[0]["document_id"],
                "name": name,
                "quote": quote,
            }
        )
    leads = validate_candidate_leads(
        selectors, discovery_documents(references), references, profile["importance"]
    )
    proposals = [
        {
            "lead_id": lead["id"],
            "criterion_id": criterion,
            "document_id": lead["citations"][0]["document_id"],
            "quote": lead["quote"],
            "judgment": judgment,
            "interpretation": "TEST ONLY: A source-bound qualitative interpretation.",
        }
        for lead, assessments in zip(leads, judgments, strict=True)
        for criterion, judgment in assessments.items()
    ]
    output = evaluate_candidates(
        {"evaluations": proposals}, leads, references, profile, version=version
    )
    assert all(item["status"] == "accepted" for item in output["feedback"])
    result["candidate_leads"] = leads
    result["literature_evaluation"] = output["evaluation"]
    result["public_discovery"].update(
        reference_count=len(references), references=deepcopy(references)
    )
    report["source_ids"] = [source["id"] for source in references]
    detail["sources"] = references
    return detail


def intake_detail(status="refused"):
    return {
        "chat": {"id": "test-chat", "title": "Materials evidence request"},
        "reports": [],
        "sources": [],
        "messages": [
            {
                "role": "assistant",
                "content": "TEST ONLY intake answer",
                "intake": {
                    "status": status,
                    "reason_code": "test-only",
                    "questions": (
                        ["TEST ONLY question"]
                        if status == "clarification_required"
                        else []
                    ),
                },
            }
        ],
    }


def test_valid_ranked_response_uses_actual_model_and_independent_coverage():
    detail = report_detail()
    before = deepcopy(detail)
    result = assess(detail, CASES["perovskite"])
    assert result["passed"]
    assert result["provider"] == "test-provider"
    assert result["model"] == "test-model"
    assert result["coverage"] == {
        "outcome": "ranked_shortlist",
        "useful_for_ranking": True,
        "ranked_table_present": True,
        "provisional_ranked_candidates": 0,
        "literature_evaluation_version": None,
        "general_application_rows": 0,
        "preliminary_baseline_only_rows": 0,
        "candidate_lead_count": 0,
        "useful_for_discovery": True,
        "comparable_candidates": 1,
        "evidence_review_candidates": 0,
        "mean_selected_weight_coverage": 0.75,
        "criterion_candidate_counts": {"band_gap": 1, "stability": 0},
        "linked_reference_count": 0,
        "clarification_question_count": 0,
    }
    assert detail == before


def test_attribute_diagnostics_distinguish_unattempted_unknown_and_assessed():
    detail = screening_detail(
        [
            {"application_fit": "supports"},
            {"density": "unknown"},
            {"density": "supports"},
            {"density": "concern"},
        ]
    )
    before = deepcopy(detail)
    diagnostic = assess(detail, CASES["polymer"])["attribute_assessment"]
    assert diagnostic["ranked_rows"] == 4
    assert diagnostic["rows_with_assessed_selected_attributes"] == 2
    assert diagnostic["rows_without_assessed_selected_attributes"] == 2
    assert diagnostic["selected_criteria"] == {
        "density": {
            "weight": 1,
            "assessed": 2,
            "explicitly_unknown": 1,
            "unattempted": 1,
        }
    }
    assert sorted(
        row["fraction"] for row in diagnostic["assessed_weight_fraction_by_row"]
    ) == [0, 0, 1, 1]
    assert detail == before


def test_attribute_diagnostics_do_not_promote_general_evidence_or_absent_results():
    detail = screening_detail([{"application_fit": "supports"}])
    diagnostic = assess(detail, CASES["polymer"])["attribute_assessment"]
    assert diagnostic["rows_with_assessed_selected_attributes"] == 0
    assert diagnostic["selected_criteria"]["density"]["unattempted"] == 1
    absent = assess(report_detail(), CASES["perovskite"])["attribute_assessment"]
    assert absent["selected_criteria"] == {}
    assert absent["ranked_rows"] == 0
    assert absent["assessed_weight_fraction_by_row"] == []


@pytest.mark.parametrize(
    "title",
    [
        "",
        "Untitled chat",
        "New chat",
        "untitled",
        "I would like to find materials",
        "Find materials for optoelectronics",
        "Please find a material",
        "x" * 74,
        "one two three four five six seven eight nine ten eleven",
    ],
)
def test_title_quality_is_separate_from_ranked_response_acceptance(title):
    detail = report_detail()
    detail["chat"]["title"] = title
    result = assess(detail, CASES["perovskite"])
    assert result["passed"]
    assert not result["usability_checks"]["concise_title"]


@pytest.mark.parametrize(
    "source_patch",
    [
        {"id": "different-source"},
        {"report_ids": ["older-report"]},
        {"chat_ids": ["other-chat"]},
        {"url": "https://unrelated.invalid"},
        {"provenance_status": "unverified"},
        {"access_scope": "private"},
        {"kind": "discovery_reference", "is_material_evidence": False},
    ],
)
def test_candidate_requires_actual_public_source_report_chat_links(source_patch):
    detail = report_detail()
    detail["sources"][0].update(source_patch)
    result = assess(detail, CASES["perovskite"])
    assert not result["passed"]
    assert not result["checks"]["source_linked_candidates"]


@pytest.mark.parametrize(
    "change", ["no_sources", "no_report_join", "wrong_adapter_id", "fake_live_mode"]
)
def test_https_live_prefix_is_insufficient(change):
    detail = report_detail()
    if change == "no_sources":
        detail["sources"] = []
    elif change == "no_report_join":
        detail["reports"][0]["source_ids"] = []
    elif change == "wrong_adapter_id":
        detail["reports"][0]["result"]["candidates"][0]["source_ids"] = [
            "material:other"
        ]
    else:
        detail["reports"][0]["result"]["candidates"][0]["source_mode"] = "live_invented"
    assert not assess(detail, CASES["perovskite"])["passed"]


@pytest.mark.parametrize("score", [0.6, float("nan"), float("inf"), True, -0.5])
def test_invalid_or_inconsistent_score_fails(score):
    detail = report_detail()
    detail["reports"][0]["result"]["candidates"][0]["score"] = score
    result = assess(detail, CASES["perovskite"])
    assert not result["passed"]
    assert not result["checks"]["score_reconciles"]


def test_reference_only_is_honest_coverage_not_a_useful_ranked_shortlist():
    result = assess(reference_detail(), CASES["polymer"])
    assert not result["passed"]
    assert not result["checks"]["nonempty_shortlist"]
    assert result["coverage"]["outcome"] == "reference_only"
    assert not result["coverage"]["useful_for_ranking"]
    assert result["coverage"]["linked_reference_count"] == 1


def test_unrelated_candidate_cannot_pass_current_polymer_case():
    detail = report_detail()
    detail["reports"][0]["result"]["execution"]["ranking_profile"][
        "material_class"
    ] = "polymers"
    result = assess(detail, CASES["polymer"])
    assert not result["passed"]
    assert not result["checks"]["reference_only_result"]


@pytest.mark.parametrize(
    "change",
    ["no_sources", "older_report", "material_evidence", "ranked_reference", "blocked"],
)
def test_reference_counts_cannot_mask_missing_links_or_failed_research(change):
    detail = reference_detail()
    if change == "no_sources":
        detail["sources"] = []
    elif change == "older_report":
        detail["sources"][0]["report_ids"] = ["older-report"]
    elif change == "material_evidence":
        detail["sources"][0]["is_material_evidence"] = True
    elif change == "ranked_reference":
        detail["reports"][0]["result"]["public_discovery"]["used_for_ranking"] = True
    else:
        detail["reports"][0]["stage"] = "blocked"
    assert not assess(detail, CASES["polymer"])["passed"]


def test_missing_critical_properties_are_reported_as_review_leads():
    detail = report_detail()
    detail["reports"][0]["result"]["candidates"][0]["score_analysis"][
        "status"
    ] = "needs_evidence"
    result = assess(detail, CASES["perovskite"])
    assert not result["passed"]
    assert not result["shortlist_quality"]["passed"]
    assert result["coverage"]["outcome"] == "evidence_review_leads"
    assert not result["coverage"]["useful_for_ranking"]


def test_refusal_uses_conversation_intake_without_a_saved_report():
    result = assess(intake_detail(), CASES["adversarial"])
    assert result["passed"]
    assert result["report_id"] is None
    assert result["coverage"]["outcome"] == "refused"
    assert result["model"] is None
    assert "telemetry" in result["limitations"][0]


@pytest.mark.parametrize(
    "change", ["reports", "sources", "clarification", "blank_answer"]
)
def test_adversarial_refusal_cannot_include_reports_or_sources(change):
    detail = intake_detail()
    if change in {"reports", "sources"}:
        detail[change] = report_detail()[change]
    elif change == "clarification":
        detail["messages"][0]["intake"]["status"] = "clarification_required"
    else:
        detail["messages"][0]["content"] = " "
    assert not assess(detail, CASES["adversarial"])["passed"]


def test_normal_clarification_is_visible_and_does_not_abort_the_evaluation():
    result = assess(intake_detail("clarification_required"), CASES["perovskite"])
    assert not result["passed"]
    assert "error_type" not in result
    assert result["coverage"]["clarification_question_count"] == 1
    assert result["coverage"]["outcome"] == "clarification_required"


@pytest.mark.parametrize(
    "detail", [None, {}, {"chat": None}, {"chat": {"id": "test", "title": None}}]
)
def test_malformed_response_is_a_recorded_failure(detail):
    result = assess(detail, CASES["perovskite"])
    assert result == {
        "checks": {"response_schema": False},
        "passed": False,
        "error_type": "InvalidResponse",
    }


def test_expanded_cases_state_expectations_without_preselected_candidate_outputs():
    assert len(CASES) == 10
    assert all(case["expectation"] for case in CASES.values())
    assert CASES["organic_photovoltaic"]["references_only_expected"]
    assert CASES["quantum_dot"]["references_only_expected"]
    assert all("expected_materials" not in case for case in CASES.values())


@pytest.mark.parametrize("failure_stage", ["chat_creation", "research"])
@pytest.mark.parametrize("failure_kind", ["http", "network", "interrupt"])
def test_live_run_checkpoints_before_later_failure_without_retrying(
    monkeypatch, tmp_path, capsys, failure_stage, failure_kind
):
    output = tmp_path / "evaluation.json"
    calls = []
    chat_count = 0
    secret = "TEST-ONLY-secret-not-for-diagnostics"
    failures = {
        "http": HTTPError(
            "http://localhost/?token=" + secret,
            503,
            secret,
            {"Authorization": secret},
            BytesIO(secret.encode()),
        ),
        "network": URLError(secret),
        "interrupt": KeyboardInterrupt(),
    }

    def fake_api(base, path, body=None):
        nonlocal chat_count
        calls.append(path)
        if path == "/api/projects":
            assert body["name"] == "TEST ONLY validation project"
            return {"id": "test-project", "name": body["name"]}
        if path.endswith("/draft-chat"):
            checkpoint = json.loads(output.read_text())
            assert checkpoint["project_id"] == "test-project"
            assert len(checkpoint["runs"]) == chat_count
            chat_count += 1
            if chat_count == 2 and failure_stage == "chat_creation":
                raise failures[failure_kind]
            return {"id": f"test-chat-{chat_count}"}
        if path.endswith("/messages"):
            if chat_count == 2:
                raise failures[failure_kind]
            return report_detail()
        return {"sequence": 1, "message": "TEST ONLY progress"}

    monkeypatch.setitem(EVALUATOR["main"].__globals__, "api", fake_api)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_live_prompts.py",
            "--run",
            "--server",
            "http://127.0.0.1:12345",
            "--output",
            str(output),
            "--project-name",
            "TEST ONLY validation project",
            "--case",
            "perovskite",
            "--case",
            "perovskite_halide",
            "--case",
            "oxide",
        ],
    )
    expected_exception = (
        KeyboardInterrupt if failure_kind == "interrupt" else SystemExit
    )
    with pytest.raises(expected_exception) as raised:
        EVALUATOR["main"]()
    saved = json.loads(output.read_text())
    assert saved["runs"][0]["case"] == "perovskite"
    assert saved["runs"][0]["passed"]
    assert chat_count == 2
    assert sum(path.endswith("/messages") for path in calls) == (
        1 if failure_stage == "chat_creation" else 2
    )
    if failure_kind == "interrupt":
        assert len(saved["runs"]) == 1
    else:
        assert raised.value.code == 1
        assert len(saved["runs"]) == 2
        failure = saved["runs"][1]
        assert failure["case"] == "perovskite_halide"
        assert not failure["passed"]
        assert failure["error_stage"] == failure_stage
        assert failure["error_type"] == (
            "HTTPError" if failure_kind == "http" else "URLError"
        )
        assert failure.get("http_status") == (503 if failure_kind == "http" else None)
        assert failure.get("chat_id") == (
            "test-chat-2" if failure_stage == "research" else None
        )
    assert secret not in output.read_text()
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err


def test_project_creation_failure_is_a_safe_saved_diagnostic(
    monkeypatch, tmp_path, capsys
):
    output = tmp_path / "evaluation.json"
    secret = "TEST-ONLY-secret-not-for-diagnostics"

    def fake_api(*args, **kwargs):
        raise HTTPError("http://localhost/?token=" + secret, 401, secret, {}, None)

    monkeypatch.setitem(EVALUATOR["main"].__globals__, "api", fake_api)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_live_prompts.py",
            "--run",
            "--server",
            "http://127.0.0.1:12345",
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit, match="1"):
        EVALUATOR["main"]()
    saved = json.loads(output.read_text())
    assert saved["project_id"] is None
    assert saved["runs"] == []
    assert saved["setup_error"] == {
        "passed": False,
        "error_type": "HTTPError",
        "error_stage": "project_creation",
        "http_status": 401,
    }
    assert secret not in output.read_text()
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err


@pytest.mark.parametrize("code", [99, 600, "503", True, None])
def test_http_diagnostics_reject_nonstandard_or_untyped_status(code):
    error = HTTPError("http://localhost", code, "TEST ONLY", {}, None)
    result = EVALUATOR["_error_result"](error, "research")
    assert "http_status" not in result


def test_failed_checkpoint_replacement_preserves_previous_complete_json(
    monkeypatch, tmp_path
):
    output = tmp_path / "evaluation.json"
    previous = {"project_id": "test-project", "runs": [{"case": "completed"}]}
    EVALUATOR["_write_checkpoint"](output, previous)

    def fail_replace(source, destination):
        assert source.parent == output.parent
        assert json.loads(source.read_text())["runs"] == []
        raise OSError("TEST ONLY disk failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="TEST ONLY disk failure"):
        EVALUATOR["_write_checkpoint"](output, {"runs": []})
    assert json.loads(output.read_text()) == previous
    assert list(tmp_path.iterdir()) == [output]


def literature_detail(evaluated=False):
    from test_candidate_leads import reference

    from labcat.science.candidate_leads import (
        discovery_documents,
        validate_candidate_leads,
    )
    from labcat.science.literature_evaluation import evaluate_candidates

    detail = reference_detail()
    source = reference(
        text="TEST ONLY TESTONLY-Alpha showed operational stability in cycling tests."
    )
    source.update(
        id="workspace-source-id", chat_ids=["test-chat"], report_ids=["test-report"]
    )
    detail["sources"] = [source]
    documents = discovery_documents([source])
    profile = {
        "material_class": "polymers",
        "application": "property_exploration",
        "importance": {"operational_stability": 1.0},
    }
    leads = validate_candidate_leads(
        [
            {
                "document_id": documents[0]["document_id"],
                "name": "TESTONLY-Alpha",
                "quote": documents[0]["text"],
            }
        ],
        documents,
        [source],
        importance=profile["importance"],
    )
    result = detail["reports"][0]["result"]
    result["execution"]["ranking_profile"] = profile
    result["candidate_leads"] = leads
    if evaluated:
        reviewed = evaluate_candidates(
            {
                "evaluations": [
                    {
                        "lead_id": leads[0]["id"],
                        "criterion_id": "operational_stability",
                        "document_id": documents[0]["document_id"],
                        "quote": documents[0]["text"],
                        "judgment": "supports",
                        "interpretation": (
                            "The passage supports retention under the "
                            "reported cycling conditions."
                        ),
                    }
                ]
            },
            leads,
            [source],
            profile,
        )
        result["literature_evaluation"] = reviewed["evaluation"]
    return detail


def test_literal_names_alone_no_longer_satisfy_ranked_shortlist_requirement():
    result = assess(literature_detail(), CASES["polymer"])
    assert result["candidate_lead_count"] == 1
    assert result["checks"]["source_linked_candidate_leads"]
    assert not result["checks"]["nonempty_shortlist"]
    assert not result["passed"]
    assert result["coverage"]["outcome"] == "literature_candidate_leads"


def test_valid_provisional_fit_is_distinguished_from_measured_material_ranking():
    detail = literature_detail(evaluated=True)
    result = assess(detail, CASES["polymer"])
    assert result["passed"]
    assert result["candidate_count"] == 0
    assert result["provisional_ranked_count"] == 1
    assert result["coverage"]["outcome"] == "preliminary_screening_shortlist"
    assert result["coverage"]["comparable_candidates"] == 0
    assert result["coverage"]["provisional_ranked_candidates"] == 1
    assert result["literature_evaluation"]["is_material_evidence"] is False


@pytest.mark.parametrize("change", ["score", "source", "weights", "interpretation"])
def test_provisional_rank_is_rebound_before_live_evaluation_can_pass(change):
    detail = literature_detail(evaluated=True)
    result = detail["reports"][0]["result"]
    if change == "score":
        result["literature_evaluation"]["ranked_candidates"][0]["fit_lower_bound"] = 0.2
    elif change == "source":
        detail["sources"][0]["metadata"]["abstract"] = "Changed source text."
    elif change == "weights":
        result["execution"]["ranking_profile"]["importance"]["stability"] = 1
    else:
        result["literature_evaluation"]["proposals"][0][
            "interpretation"
        ] = "Changed interpretation."
    assessed = assess(detail, CASES["polymer"])
    assert not assessed["passed"]
    assert assessed["error_type"] == "InvalidResponse"


def test_multiple_legitimate_classes_are_accepted_without_a_single_class_field():
    case = {
        **CASES["perovskite"],
        "accepted_classes": ["perovskites", "semiconductors"],
    }
    del case["class"]
    assert assess(report_detail(), case)["passed"]
    case["accepted_classes"] = ["semiconductors"]
    assert not assess(report_detail(), case)["checks"]["inferred_class"]


@pytest.mark.parametrize("missing", ["direction", "selected_weight", "semantic_goal"])
def test_expected_goal_requires_requested_direction_and_selected_criterion(missing):
    detail = report_detail()
    execution = detail["reports"][0]["result"]["execution"]
    execution["semantic_scope"] = {
        "goals": [{"attribute_id": "band_gap", "relation": "target"}]
    }
    case = {
        **CASES["perovskite"],
        "expected_goals": [{"attribute_id": "band_gap", "relation": "target"}],
    }
    assert assess(detail, case)["checks"]["goal_band_gap"]
    if missing == "direction":
        execution["semantic_scope"]["goals"][0]["relation"] = "maximize"
    elif missing == "selected_weight":
        execution["ranking_profile"]["importance"]["band_gap"] = 0
    else:
        execution["semantic_scope"]["goals"] = []
    assert not assess(detail, case)["checks"]["goal_band_gap"]


def test_expected_role_accepts_larger_literal_span_but_rejects_environment_as_target():
    detail = report_detail()
    scope = {"target_spans": ["perovskite film"], "environment_spans": ["in HUMID air"]}
    detail["reports"][0]["result"]["execution"]["semantic_scope"] = scope
    case = {
        **CASES["perovskite"],
        "expected_role_spans": {"environment_spans": ["humid air"]},
        "forbidden_target_spans": ["humid air"],
    }
    assert assess(detail, case)["passed"]
    scope["target_spans"].append("humid air")
    assert not assess(detail, case)["checks"][
        "target_excludes_environment_and_processing"
    ]
    scope["environment_spans"] = []
    assert not assess(detail, case)["checks"]["environment_spans"]


def test_clarification_control_requires_guiding_questions_and_no_research_artifacts():
    case = {
        "control": "clarification",
        "candidates_expected": False,
        "expected_intake_statuses": ["clarification_required"],
    }
    detail = intake_detail("clarification_required")
    assert assess(detail, case)["passed"]
    detail["messages"][0]["intake"]["questions"] = []
    assert not assess(detail, case)["passed"]
    detail = intake_detail("refused")
    assert not assess(detail, case)["passed"]
    detail = intake_detail("clarification_required")
    detail["reports"] = report_detail()["reports"]
    assert not assess(detail, case)["checks"]["no_research_reports"]


@pytest.mark.parametrize("questions", ["Why?", {"Why?": True}, [], [None], [" "]])
def test_malformed_guiding_questions_cannot_pass(questions):
    detail = intake_detail("clarification_required")
    detail["messages"][0]["intake"]["questions"] = questions
    assert not assess(detail, {"control": "clarification"})["passed"]


@pytest.mark.parametrize("change", ["administrative_only", "zero_weight", "irrelevant"])
def test_scored_table_is_not_enough_without_positive_weight_decision_evidence(change):
    detail = report_detail()
    result = detail["reports"][0]["result"]
    candidate = result["candidates"][0]
    case = deepcopy(CASES["perovskite"])
    if change == "administrative_only":
        candidate["criterion_available"] = {"evidence_quality": True}
        candidate["score_contributions"] = {"evidence_quality": 0.5}
        result["execution"]["ranking_profile"]["importance"] = {"evidence_quality": 1}
    elif change == "zero_weight":
        result["execution"]["ranking_profile"]["importance"]["band_gap"] = 0
    else:
        case["decision_criteria"] = ["density"]
    evaluated = assess(detail, case)
    assert evaluated["checks"]["nonempty_shortlist"]
    assert not evaluated["shortlist_quality"]["checks"]["decision_evidence_available"]
    assert not evaluated["passed"]
    assert not evaluated["coverage"]["useful_for_ranking"]


def test_breadth_requires_distinct_evaluated_rows_and_scope_review_remains_pending():
    detail = report_detail()
    case = {**CASES["perovskite"], "minimum_ranked_candidates": 3}
    detail["reports"][0]["result"]["candidates"] *= 3
    result = assess(detail, case)
    assert result["candidate_count"] == 3
    assert result["shortlist_quality"]["quantitative_decision_rows"] == 1
    assert not result["shortlist_quality"]["checks"]["shortlist_breadth"]
    assert result["shortlist_quality"]["scientific_scope_review"] == "pending"


def test_provisional_concerns_are_assessed_but_not_successful_recommendations():
    quality = EVALUATOR["_shortlist_quality"]
    literature = {
        "criteria": [{"criterion_id": "density", "weight": 1}],
        "ranked_candidates": [
            {
                "name": "TEST ONLY material",
                "criteria": [{"criterion_id": "density", "judgment": "concern"}],
            }
        ],
    }
    result = quality({"decision_criteria": ["density"]}, [], literature, {})
    assert result["checks"]["decision_evidence_available"]
    assert not result["checks"]["not_only_provisional_concerns"]
    literature["ranked_candidates"][0]["criteria"][0]["judgment"] = "mixed"
    assert quality({}, [], literature, {})["passed"]


@pytest.mark.parametrize("judgment", ["supports", "mixed"])
def test_v2_application_support_is_useful_preliminary_review_without_attributes(
    judgment,
):
    detail = screening_detail([{"application_fit": judgment}] * 3)
    before = deepcopy(detail)
    result = assess(detail, {**CASES["polymer"], "minimum_ranked_candidates": 3})
    assert result["passed"]
    quality = result["shortlist_quality"]
    assert quality["general_application_rows"] == 3
    assert quality["general_application_assessed_rows"] == 3
    assert quality["preliminary_baseline_only_rows"] == 0
    assert quality["breadth_lower_bound"] == 3
    assert quality["scientific_scope_review"] == "pending"
    assert result["coverage"]["outcome"] == "preliminary_screening_shortlist"
    assert result["coverage"]["literature_evaluation_version"] == "literature-fit-v2"
    assert result["coverage"]["useful_for_ranking"]
    assert all(
        row["coverage"] == 0 and row["observed_fit"] is None
        for row in result["literature_evaluation"]["ranked_candidates"]
    )
    assert detail == before


def test_v2_unknown_prior_table_passes_presence_but_not_usefulness():
    result = assess(
        screening_detail([{}, {}, {}]),
        {**CASES["polymer"], "minimum_ranked_candidates": 3},
    )
    assert result["checks"]["nonempty_shortlist"]
    assert result["coverage"]["ranked_table_present"]
    assert result["coverage"]["outcome"] == "preliminary_screening_shortlist"
    assert result["coverage"]["preliminary_baseline_only_rows"] == 3
    assert not result["coverage"]["useful_for_ranking"]
    assert not result["passed"]
    quality = result["shortlist_quality"]
    assert quality["general_application_rows"] == 0
    assert quality["breadth_lower_bound"] == 0
    assert not quality["checks"]["decision_evidence_available"]


@pytest.mark.parametrize("concern", ["application_fit", "ambient_phase_stability"])
def test_v2_contraindications_do_not_pass_from_other_favorable_assessments(concern):
    judgments = {
        "application_fit": "supports",
        "density": "supports",
        concern: "concern",
    }
    result = assess(screening_detail([judgments] * 3), CASES["polymer"])
    assert result["checks"]["nonempty_shortlist"]
    quality = result["shortlist_quality"]
    assert quality["provisional_decision_rows"] == 3
    assert quality["provisional_adverse_rows"] == 3
    assert quality["general_application_rows"] == 0
    assert quality["provisional_rows_with_support"] == 0
    assert quality["checks"]["decision_evidence_available"]
    assert not quality["checks"]["not_only_provisional_concerns"]
    assert not result["passed"]


def test_v2_demonstrated_use_alone_does_not_establish_requested_application_fit():
    result = assess(
        screening_detail([{"demonstrated_use": "supports"}] * 3), CASES["polymer"]
    )
    quality = result["shortlist_quality"]
    assert quality["demonstrated_use_rows"] == 3
    assert quality["general_application_rows"] == 0
    assert quality["preliminary_baseline_only_rows"] == 0
    assert result["coverage"]["ranked_table_present"]
    assert not result["passed"]


def test_v2_adverse_alternative_cannot_fill_required_useful_breadth():
    result = assess(
        screening_detail(
            [
                {"application_fit": "supports"},
                {"application_fit": "mixed"},
                {"application_fit": "concern"},
            ]
        ),
        {**CASES["polymer"], "minimum_ranked_candidates": 3},
    )
    quality = result["shortlist_quality"]
    assert quality["general_application_rows"] == quality["breadth_lower_bound"] == 2
    assert quality["general_application_assessed_rows"] == 3
    assert quality["checks"]["not_only_provisional_concerns"]
    assert not quality["checks"]["shortlist_breadth"]
    assert not result["passed"]


def test_v2_support_still_requires_revalidated_public_source_binding():
    detail = screening_detail([{"application_fit": "supports"}] * 3)
    detail["sources"][0]["metadata"]["abstract"] = "An unrelated synthetic passage."
    # Change the retained snapshot too: neither source can now bind the quote.
    detail["reports"][0]["result"]["public_discovery"]["references"][0]["metadata"][
        "abstract"
    ] = "An unrelated synthetic passage."
    result = assess(detail, CASES["polymer"])
    assert not result["passed"]
    assert result["error_type"] == "InvalidResponse"


def test_v2_names_are_deduplicated_before_useful_breadth_is_counted():
    detail = screening_detail([{"application_fit": "supports"}])
    report = detail["reports"][0]["result"]
    literature = deepcopy(report["literature_evaluation"])
    original = literature["ranked_candidates"][0]
    literature["ranked_candidates"] += [
        {**deepcopy(original), "name": "  testonly-a "},
        {**deepcopy(original), "name": "ＴＥＳＴＯＮＬＹ-Ａ"},
    ]
    quality = EVALUATOR["_shortlist_quality"](
        {"minimum_ranked_candidates": 3},
        [],
        literature,
        report["execution"]["ranking_profile"],
    )
    assert quality["general_application_rows"] == quality["breadth_lower_bound"] == 1
    assert not quality["passed"]


def test_v1_attribute_shortlist_keeps_legacy_classification_and_requirements():
    result = assess(
        screening_detail([{"density": "mixed"}] * 3, version="literature-fit-v1"),
        {**CASES["polymer"], "minimum_ranked_candidates": 3},
    )
    assert result["passed"]
    assert result["coverage"]["outcome"] == "provisional_literature_shortlist"
    assert result["coverage"]["literature_evaluation_version"] == "literature-fit-v1"
    assert result["shortlist_quality"]["general_application_rows"] == 0
    assert result["shortlist_quality"]["provisional_decision_rows"] == 3


def test_full_plain_language_matrix_covers_the_class_catalog_without_fixed_answers():
    from labcat.ranking_profiles import catalog

    path = Path(__file__).resolve().parents[1] / "scripts/materials_prompt_matrix.json"
    cases = EVALUATOR["validate_cases"](json.loads(path.read_text())["cases"])
    classes = {item["id"] for item in catalog()["material_classes"]} - {"custom"}
    assert len(cases) == 72
    assert len({case["prompt"] for case in cases.values()}) == 72
    for family in classes:
        rows = [case for case in cases.values() if case.get("family") == family]
        assert {row["variant"] for row in rows} == {"explicit", "implicit", "tradeoff"}
        assert len(rows) == 3
        assert all(row["minimum_ranked_candidates"] == 3 for row in rows)
    assert all("expected_materials" not in case for case in cases.values())
    assert all("expected_measurements" not in case for case in cases.values())


@pytest.mark.parametrize(
    "patch",
    [
        {"class": "invalid"},
        {"accepted_classes": []},
        {"expected_goals": [{"attribute_id": "imaginary", "relation": "maximize"}]},
        {"expected_goals": [{"attribute_id": "density", "relation": "invented"}]},
        {"decision_criteria": ["misspelled"]},
        {"minimum_ranked_candidates": 0},
        {"control": "made_up"},
        {"control": "clarification", "candidates_expected": True},
        {"expected_role_spans": {"environment_spans": ["phrase absent from prompt"]}},
        {"target": float("nan")},
    ],
)
def test_invalid_expectations_fail_before_any_live_operation(patch):
    with pytest.raises(ValueError):
        EVALUATOR["validate_cases"]({"test": {**CASES["perovskite"], **patch}})
