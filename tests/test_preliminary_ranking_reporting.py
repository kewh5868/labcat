"""Synthetic passage fixtures, never material recommendations or live
claims."""

import io
import json
from copy import deepcopy
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from pypdf import PdfReader
from test_candidate_lead_reporting import lead_report
from test_literature_evaluation_reporting import evaluated_report
from test_semantic_goal_scoring import review

from labcat.config import load_config
from labcat.report_exports import (
    ExportError,
    _blocks,
    _formula_pattern,
    _formula_runs,
    _score_fills,
    prepare_presentation,
    render_download,
)
from labcat.science.candidate_leads import (
    discovery_documents,
    validate_candidate_leads,
)
from labcat.science.literature_evaluation import evaluate_candidates
from labcat.science.ranking import reviewed_goal_preferences
from labcat.science.reporting import (
    render_reports,
    screening_priority_presentation,
)


def preliminary_report(*, assessed=False, formula=False):
    report = lead_report()
    result = report["result"]
    profile = {"importance": {"density": 1, "solution_processability": 1}}
    result["execution"]["ranking_profile"] = profile
    result["ranking"]["raw_importance"] = profile["importance"]
    result["ranking"]["weights"] = {"density": 0.5, "solution_processability": 0.5}
    if formula:
        # Synthetic occurrence verifies typography only, with no material data.
        source = report["sources"][0]
        source["metadata"]["abstract"] = source["metadata"]["abstract"].replace(
            "Fixture-A", "O2Si"
        )
        mentions = [
            {
                "document_id": discovery_documents([source])[0]["document_id"],
                "name": (
                    "O2Si" if index == 0 else result["candidate_leads"][index]["name"]
                ),
                "quote": source["metadata"]["abstract"],
            }
            for index, source in enumerate(report["sources"])
        ]
        result["candidate_leads"] = validate_candidate_leads(
            mentions,
            discovery_documents(report["sources"]),
            report["sources"],
            profile["importance"],
        )
    proposals = []
    if assessed:
        for index, lead in enumerate(result["candidate_leads"]):
            citation = lead["citations"][0]
            proposals.append(
                {
                    "lead_id": lead["id"],
                    "criterion_id": "application_fit",
                    "document_id": citation["document_id"],
                    "quote": citation["quote"],
                    "judgment": "concern" if index == 0 else "supports",
                    "interpretation": "TEST ONLY interpretation of source discussion, "
                    "not a material recommendation.",
                }
            )
    result["literature_evaluation"] = evaluate_candidates(
        {"evaluations": proposals},
        result["candidate_leads"],
        report["sources"],
        profile,
    )["evaluation"]
    # A former property-stage outcome must not override the new real shortlist.
    result["summary"] = (
        "No scored material shortlist was generated. TEST ONLY missing attributes."
    )
    result["limitations"] = [
        "No material properties, stability assessments or ranking scores "
        "were established for this question. Reference order is not a "
        "ranking of material performance."
    ]
    report["pi_summary"], report["technical_audit"] = render_reports(
        result, load_config(), report["sources"]
    )
    return report


@pytest.mark.parametrize("assessed", [False, True])
def test_no_attribute_evidence_still_produces_complete_prioritized_table(assessed):
    report = preliminary_report(assessed=assessed)
    evaluation = report["result"]["literature_evaluation"]
    for field in ("pi_summary", "technical_audit"):
        text = report[field]
        assert "12 candidates ranked for review" in text
        assert "Candidate shortlist:" in text
        assert "No scored material shortlist" not in text
        assert "No scored shortlist was produced" not in text
        assert (
            "No material properties, stability assessments or ranking scores"
            not in text
        )
        assert "not enough validated" not in text
        if field == "pi_summary":
            assert "0% assessed · Baseline only; 2 unknown criteria" in text
        else:
            assert "Relevant properties" in text
            assert "Density — Not reported" in text
            assert "Solution processability — Not reported" in text
        assert "Missing attributes retain the preliminary score" in text
        assert "not measured performance, a probability or confidence" in text
        assert "Unknown stability is not established stability" in text
        tables = [data for kind, data, _ in _blocks(text) if kind == "table"]
        table = next(
            data
            for data in tables
            if data[0][:3] == ["Rank", "Material", "Screening priority"]
        )
        assert len(table) == 13
        fills = _score_fills(table, report, "pi")
        assert len(fills) == 12
        assert set(fills.values()) == (
            {"#DEEED7", "#F8D7DA"} if assessed else {"#EDF0F2"}
        )
        assert all(row["name"] in text for row in evaluation["ranked_candidates"])
        if assessed:
            assert "Concern reported" in text
            assert "Application relevance — Concern:" in text
        else:
            assert {row[0] for row in table[1:]} == {"1"}
            assert {row[2] for row in table[1:]} == {"22% · Unassessed review prior"}
            assert "It is not 22% suitability" in text
            assert "No adverse assessment" not in text
            assert (
                "Named in retrieved discussion; application relevance and use "
                "unassessed" in text
            )
    audit = report["technical_audit"]
    assert "Algorithm: literature-fit-v2" in audit
    assert "P = (1 − c) × B + c × A" in audit
    assert "0.25 as an explicit review prior" in audit
    assert "Attribute fit A" in audit
    assert "attribute fit A = unknown" in audit
    assert "Distinct corroborating works" in audit
    assert "Supporting passage [S" in audit
    assert report["result"]["report_tables"]["technical"]["rows"] == []


def test_priority_palette_keeps_unknown_priors_neutral_and_adverse_tiers_visible():
    # Synthetic presentation values test the color contract, not material merit.
    row = {
        "priority_score": 0.225,
        "priority_tier": 0,
        "coverage": 0,
        "general_evidence": {
            "application_fit": "unknown",
            "demonstrated_use": "unknown",
        },
    }
    assert screening_priority_presentation(row) == {
        "text": "22% · Unassessed review prior",
        "state": "unassessed",
        "fill": "#EDF0F2",
    }
    for tier, state, color in [(1, "mixed", "#FFE0B2"), (2, "concern", "#F8D7DA")]:
        adverse = {**row, "priority_score": 0.99, "priority_tier": tier}
        style = screening_priority_presentation(adverse)
        assert style["state"] == state
        assert style["fill"] == color
        assert style["text"].startswith("99%")
    for value, color in [(0, "#FFF0C2"), (1, "#D5EDDD")]:
        assessed = {**row, "priority_score": value, "coverage": 1}
        style = screening_priority_presentation(assessed)
        assert style["state"] == "assessed"
        assert style["fill"] == color


def test_preliminary_export_colors_require_the_exact_evidence_bound_table():
    report = preliminary_report(assessed=True)
    table = next(
        data
        for kind, data, _ in _blocks(report["pi_summary"])
        if kind == "table" and data[0][:3] == ["Rank", "Material", "Screening priority"]
    )
    original = deepcopy(report)
    for index in range(len(table[1])):
        changed = deepcopy(table)
        changed[1][index] = "Changed table cell"
        assert _score_fills(changed, report, "pi") == {}
    assert report == original


def test_preliminary_word_export_shades_prior_badges_without_mutating_scores():
    report = preliminary_report()
    original = deepcopy(report)
    body = render_download(prepare_presentation(report), "docx")[0]
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with ZipFile(io.BytesIO(body)) as document:
        xml = ElementTree.fromstring(document.read("word/document.xml"))
    tables = xml.findall(".//w:tbl", namespace)
    shortlist = next(
        table
        for table in tables
        if "Screening priority"
        in ["".join(cell.itertext()) for cell in table.find("w:tr", namespace)]
    )
    for row in shortlist.findall("w:tr", namespace)[1:]:
        cells = row.findall("w:tc", namespace)
        for index in (0, 2):
            fill = cells[index].find("w:tcPr/w:shd", namespace)
            assert fill.attrib[f"{{{namespace['w']}}}fill"] == "EDF0F2"
    assert report == original


def test_selected_attribute_refinement_and_adverse_tier_are_reported():
    report = evaluated_report(version="literature-fit-v2")
    evaluation = report["result"]["literature_evaluation"]
    assert evaluation["version"] == "literature-fit-v2"
    assert any(
        row["ranking_basis"] == "blended" for row in evaluation["ranked_candidates"]
    )
    assert any(row["priority_tier"] == 2 for row in evaluation["ranked_candidates"])
    for field in ("pi_summary", "technical_audit"):
        assert "Attribute-refined" in report[field]
        assert "Concern reported" in report[field]
        assert "Criterion" in report[field] or "criterion" in report[field]
    assert "Band gap (maximize)" in report["technical_audit"]
    assert "Room-temperature phase stability (maximize)" in report["technical_audit"]
    assert "No separate measured-property ranking" in report["technical_audit"]


@pytest.mark.parametrize(
    "mutation", ["baseline", "priority", "tier", "rank", "count", "quote", "profile"]
)
def test_preliminary_scores_and_evidence_cannot_be_changed_in_saved_reports(mutation):
    report = preliminary_report(assessed=True)
    evaluation = report["result"]["literature_evaluation"]
    row = evaluation["ranked_candidates"][0]
    if mutation == "baseline":
        row["preliminary_score"] = 0.999
    elif mutation == "priority":
        row["priority_score"] = 0.999
    elif mutation == "tier":
        row["priority_tier"] = 2
    elif mutation == "rank":
        row["rank"] = 99
    elif mutation == "count":
        row["general_evidence"]["corroborating_work_count"] = 99
    elif mutation == "quote":
        evaluation["proposals"][0][
            "quote"
        ] = "TEST ONLY invented source quote not present in the retrieved document."
    else:
        report["result"]["execution"]["ranking_profile"]["importance"]["density"] = 0.1
    with pytest.raises(ExportError):
        prepare_presentation(report)
    with pytest.raises(ExportError):
        render_download(report, "text")


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_preliminary_shortlist_export_preserves_citations_and_unknowns(format):
    report = preliminary_report()
    original = deepcopy(report)
    prepared = prepare_presentation(report)
    body = render_download(prepared, format)[0]
    assert report == original
    if format == "pdf":
        pdf = PdfReader(io.BytesIO(body))
        text = " ".join(page.extract_text() for page in pdf.pages)
        urls = {
            str(annotation.get_object().get("/A", {}).get("/URI", ""))
            for page in pdf.pages
            for annotation in page.get("/Annots", [])
        }
        assert "https://openalex.org/W12" in urls
    elif format == "docx":
        with ZipFile(io.BytesIO(body)) as document:
            text = " ".join(
                ElementTree.fromstring(document.read("word/document.xml")).itertext()
            )
            assert b"https://openalex.org/W12" in document.read(
                "word/_rels/document.xml.rels"
            )
    elif format == "json":
        # Raw stage diagnostics remain in the archive; visible report text uses
        # the regenerated shortlist outcome without rewriting the saved result.
        data = json.loads(body)
        text = " ".join(data["views"].values())
    else:
        text = body.decode()
    text = " ".join(text.split())
    assert "Candidate shortlist" in text
    assert "Fixture-L" in text and "Supporting passage" in text
    assert "Baseline only" in text and "unknown criteria" in text
    assert "No scored material shortlist" not in text


def test_preliminary_formula_typography_does_not_rewrite_source_names_or_urls():
    report = preliminary_report(formula=True)
    evaluation = report["result"]["literature_evaluation"]
    assert any(row["name"] == "O2Si" for row in evaluation["ranked_candidates"])
    assert "SiO2 [S" in report["pi_summary"]
    assert "TEST ONLY: O2Si appears" in report["technical_audit"]
    pattern = _formula_pattern(report)
    assert [(text, sub) for text, sub in _formula_runs("SiO2", pattern) if text] == [
        ("Si", False),
        ("O", False),
        ("2", True),
    ]
    url = "https://openalex.org/SiO2"
    assert [(text, sub) for text, sub in _formula_runs(url, pattern) if text] == [
        (url, False)
    ]
    body = render_download(prepare_presentation(report), "docx")[0]
    with ZipFile(io.BytesIO(body)) as document:
        xml = document.read("word/document.xml")
        assert b'w:val="subscript"' in xml


def test_version_one_saved_presentation_is_not_upgraded_to_preliminary_method():
    historical = evaluated_report()
    before = deepcopy(historical)
    prepared = prepare_presentation(historical)
    assert historical == before
    assert prepared["result"]["literature_evaluation"]["version"] == "literature-fit-v1"
    assert prepared["pi_summary"] == before["pi_summary"]
    assert prepared["technical_audit"] == before["technical_audit"]
    assert "Provisional literature shortlist:" in prepared["pi_summary"]
    assert "Screening priority" not in prepared["pi_summary"]
    # Presentation may improve; the saved v1 scientific method must not change.
    assert (
        prepared["result"]["literature_evaluation"]
        == before["result"]["literature_evaluation"]
    )
    for field in ("pi_summary", "technical_audit"):
        text = prepared[field]
        assert "Findings and recommendations:" in text
        assert "Algorithm: literature-fit-v2" not in text
        assert text.index("Provisional literature shortlist:") < text.index(
            "Search and analysis details:"
        )
        table = next(data for kind, data, _ in _blocks(text) if kind == "table")
        assert table[0][:3] == ["Provisional rank", "Material", "Literature fit"]
        assert [int(row[0]) for row in table[1:]] == [
            row["rank"]
            for row in before["result"]["literature_evaluation"]["ranked_candidates"]
        ]


def test_zero_property_records_do_not_claim_zero_preliminary_candidates():
    report = preliminary_report()
    report["result"]["retrieval"] = {"records_retrieved": 0}
    prepared = prepare_presentation(report)
    audit = prepared["technical_audit"]
    assert "0 quantitative property records retrieved" in audit
    assert "0 entries in the separate measured-property table" in audit
    assert "The preliminary shortlist contains 12 cited candidates" in audit
    assert "0 distinct compositions shortlisted" not in audit
    assert "Measured-property ranking method:" in audit
    assert "This section describes the separate property table" in audit
    assert "In the separate property table, coverage" in audit
    assert "These are distinct from preliminary screening priority" in audit


def test_unscored_property_goal_remains_eligible_for_qualitative_assessment():
    report = preliminary_report()
    result = report["result"]
    preferences = review("solution_processability", "maximize")
    result["ranking"]["goal_review"] = reviewed_goal_preferences(
        preferences["scope"], result["execution"]["ranking_profile"], "inferred"
    )
    prepared = prepare_presentation(report)
    for field in ("pi_summary", "technical_audit"):
        text = prepared[field]
        assert "Measured-property scoring: Unsupported requested directions" in text
        assert "Unscored by measured-property utilities" in text
        assert "can still use valid qualitative assessments" in text
        assert "- Unscored requested goal" not in text


@pytest.mark.parametrize("assessment_kind", ["none", "unknown", "supports"])
def test_public_reference_note_distinguishes_review_prior_from_assessments(
    assessment_kind,
):
    report = preliminary_report(assessed=assessment_kind != "none")
    if assessment_kind == "unknown":
        result = report["result"]
        proposals = [
            {**row, "judgment": "unknown"}
            for row in result["literature_evaluation"]["proposals"]
        ]
        result["literature_evaluation"] = evaluate_candidates(
            {"evaluations": proposals},
            result["candidate_leads"],
            report["sources"],
            result["execution"]["ranking_profile"],
        )["evaluation"]
    prepared = prepare_presentation(report)
    for field in ("pi_summary", "technical_audit"):
        note = prepared[field].split("Public literature:")[-1]
        if assessment_kind == "supports":
            assert "through attributed assessments" in note
            assert "No non-unknown criterion judgments" not in note
        else:
            assert "Retrieved passages supply the candidate names" in note
            assert "priorities use the disclosed preliminary review prior" in note
            assert "through attributed assessments" not in note


@pytest.mark.parametrize(
    "legacy,completion_version",
    [
        (False, None),
        (True, None),
        (True, "bounded-recovery-v2"),
    ],
)
def test_interrupted_v2_describes_incomplete_model_work_without_guessing_failure(
    legacy,
    completion_version,
):
    report = evaluated_report() if legacy else preliminary_report()
    report["result"]["execution"].update(
        model_interrupted=True, warning="SECRET untrusted provider failure"
    )
    if completion_version:
        report["result"]["execution"]["completion_version"] = completion_version
    prepared = prepare_presentation(report)
    for field in ("pi_summary", "technical_audit"):
        text = prepared[field]
        assert "SECRET" not in text
        assert "without another model call" in text
        if legacy and not completion_version:
            assert "The model connection stopped after the request was assessed" in text
        else:
            assert "Model-led research stopped before completion" in text
            assert "model connection stopped" not in text
            assert "incomplete assessments or search coverage" in text
