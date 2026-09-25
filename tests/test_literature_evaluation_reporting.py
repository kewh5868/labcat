"""Synthetic source-passage protocol fixtures, not material
recommendations."""

import io
from copy import deepcopy
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from pypdf import PdfReader
from test_candidate_lead_reporting import lead_report
from test_semantic_goal_scoring import review

from labcat.config import load_config
from labcat.report_exports import (
    ExportError,
    _blocks,
    _score_fills,
    prepare_presentation,
    render_download,
)
from labcat.science.candidate_leads import (
    discovery_documents,
    validate_candidate_leads,
)
from labcat.science.literature_evaluation import (
    evaluate_candidates,
    evaluation_goals,
)
from labcat.science.reporting import render_reports
from labcat.workspace import WorkspaceStore


def evaluated_report(*, version="literature-fit-v1"):
    report = lead_report()
    report["stage"] = "partial"
    profile = {"importance": {"band_gap": 1, "ambient_phase_stability": 1}}
    mentions = []
    for source, lead in zip(
        report["sources"], report["result"]["candidate_leads"], strict=True
    ):
        quote = (
            f"TEST ONLY: {lead['name']} band gap and room-temperature phase stability "
            "are compared in this synthetic protocol; this is not a material "
            "measurement."
        )
        source["metadata"]["abstract"] = quote
        mentions.append(
            {
                "document_id": lead["citations"][0]["document_id"],
                "name": lead["name"],
                "quote": quote,
            }
        )
    report["result"]["candidate_leads"] = validate_candidate_leads(
        mentions,
        discovery_documents(report["sources"]),
        report["sources"],
        profile["importance"],
    )
    proposals = []
    for index, lead in enumerate(report["result"]["candidate_leads"]):
        citation = lead["citations"][0]
        proposals.append(
            {
                "lead_id": lead["id"],
                "criterion_id": "band_gap",
                "document_id": citation["document_id"],
                "quote": citation["quote"],
                "judgment": "mixed" if index == 0 else "supports",
                "interpretation": "TEST ONLY protocol interpretation of the cited "
                "comparison; not a material measurement.",
            }
        )
        if index == 0:
            proposals.append(
                {
                    "lead_id": lead["id"],
                    "criterion_id": "ambient_phase_stability",
                    "document_id": citation["document_id"],
                    "quote": citation["quote"],
                    "judgment": "concern",
                    "interpretation": "TEST ONLY stability concern interpretation; "
                    "no actual stability claim.",
                }
            )
    result = report["result"]
    result["execution"]["ranking_profile"] = profile
    result["ranking"]["raw_importance"] = profile["importance"]
    evaluated = evaluate_candidates(
        {"evaluations": proposals},
        result["candidate_leads"],
        report["sources"],
        profile,
        version=version,
    )
    result["literature_evaluation"] = evaluated["evaluation"]
    assert len(result["literature_evaluation"]["ranked_candidates"]) == 12
    report["pi_summary"], report["technical_audit"] = render_reports(
        result, load_config(), report["sources"]
    )
    return report


def test_all_evaluated_candidates_are_ranked_separately_from_measured_properties():
    report = evaluated_report()
    evaluation = report["result"]["literature_evaluation"]
    for view in ("pi_summary", "technical_audit"):
        text = report[view]
        assert "Provisional literature shortlist:" in text
        assert "| Provisional rank | Material | Literature fit |" in text
        assert "supported fit" in text and "assessed; 1 unknown criterion" in text
        assert "not a confidence interval" in text
        assert "not measured material performance or citation counts" in text
        assert "Stability & uncertainty" in text and "Concern:" in text
        assert "not enough validated" not in text
        assert "No scored shortlist was produced" not in text
        assert "Review order is not a performance ranking" not in text
        assert "TEST ONLY quantitative adapter unavailable" in text
        for candidate in evaluation["ranked_candidates"]:
            assert candidate["name"] in text
        tables = [content for kind, content, _ in _blocks(text) if kind == "table"]
        primary = next(table for table in tables if table[0][0] == "Provisional rank")
        assert len(primary) == 13
        assert _score_fills(primary, report, "pi") == {}
    assert report["result"]["report_tables"]["technical"]["rows"] == []
    assert "Literature criterion assessments:" in report["technical_audit"]
    assert "Supporting passage [S" in report["technical_audit"]
    assert "Fit among assessed criteria" in report["technical_audit"]


@pytest.mark.parametrize(
    "mutation", ["rank", "fit", "quote", "reason", "source", "profile"]
)
def test_saved_evaluation_must_rebind_before_render_or_export(mutation):
    report = evaluated_report()
    evaluation = report["result"]["literature_evaluation"]
    row = evaluation["ranked_candidates"][0]
    if mutation == "rank":
        row["rank"] = 99
    elif mutation == "fit":
        row["fit_lower_bound"] = 0.99
    elif mutation == "quote":
        evaluation["proposals"][0]["quote"] = "Unretrieved measurement was invented."
    elif mutation == "reason":
        next(item for item in row["criteria"] if item["assessments"])["assessments"][0][
            "interpretation"
        ] = "Invented interpretation change"
    elif mutation == "source":
        report["sources"][0]["metadata"]["abstract_read"] = False
    else:
        report["result"]["execution"]["ranking_profile"]["importance"]["band_gap"] = 0.5
    with pytest.raises(ExportError):
        prepare_presentation(report)
    with pytest.raises(ExportError):
        render_download(report, "text")


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_saved_evaluation_citations_survive_all_export_formats(tmp_path, format):
    report = evaluated_report()
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY literature evaluation")
    chat = store.create_global_chat("TEST ONLY", project["id"])
    store.append_research(
        chat["id"],
        project["id"],
        "TEST ONLY request",
        {"answer": "TEST ONLY", **report},
    )
    saved = store.get_global_chat(chat["id"])
    snapshot = {**saved["reports"][0], "sources": saved["sources"]}
    before = deepcopy(snapshot)
    prepared = prepare_presentation(snapshot, "current", load_config())
    body = render_download(prepared, format)[0]
    assert snapshot == before
    if format == "pdf":
        document = PdfReader(io.BytesIO(body))
        text = " ".join(page.extract_text() for page in document.pages)
        urls = {
            str(item.get_object().get("/A", {}).get("/URI", ""))
            for page in document.pages
            for item in page.get("/Annots", [])
        }
        assert "https://openalex.org/W12" in urls
    elif format == "docx":
        with ZipFile(io.BytesIO(body)) as archive:
            text = " ".join(
                ElementTree.fromstring(archive.read("word/document.xml")).itertext()
            )
            assert b"https://openalex.org/W12" in archive.read(
                "word/_rels/document.xml.rels"
            )
    else:
        text = body.decode()
    text = " ".join(text.split())
    assert "Provisional literature shortlist" in text
    assert "Fixture-L" in text and "Supporting passage" in text
    assert "Unknown" in text and "Concern" in text


def test_legacy_lead_only_reports_keep_their_original_presentation():
    report = lead_report()
    before = deepcopy(report)
    prepared = prepare_presentation(report)
    assert prepared["pi_summary"] == before["pi_summary"]
    assert prepared["technical_audit"] == before["technical_audit"]
    assert report == before


def test_inferred_semantic_goal_direction_survives_saved_report_replay():
    report = evaluated_report()
    result = report["result"]
    preferences = review("band_gap", "minimize")
    result["execution"].update(
        semantic_scope=preferences["scope"],
        ranking_selection={"mode": "semantic_inferred"},
    )
    goals = evaluation_goals(
        preferences["scope"], result["execution"]["ranking_selection"]
    )
    result["literature_evaluation"] = evaluate_candidates(
        {"evaluations": result["literature_evaluation"]["proposals"]},
        result["candidate_leads"],
        report["sources"],
        result["execution"]["ranking_profile"],
        goals=goals,
        version="literature-fit-v1",
    )["evaluation"]
    prepared = prepare_presentation(report)
    for view in ("pi_summary", "technical_audit"):
        assert "Band gap (minimize)" in prepared[view]
    broken = deepcopy(report)
    broken["result"]["execution"]["ranking_selection"] = {"mode": "explicit"}
    with pytest.raises(ExportError):
        prepare_presentation(broken)


def test_conflicting_cited_assessments_remain_visible():
    report = evaluated_report()
    result = report["result"]
    lead = result["candidate_leads"][1]
    source = deepcopy(report["sources"][1])
    source.update(
        record_id="W100",
        url="https://openalex.org/W100",
        title="TEST ONLY conflicting reference",
    )
    report["sources"].append(source)
    document = discovery_documents([source])[0]
    proposals = [
        *result["literature_evaluation"]["proposals"],
        {
            "lead_id": lead["id"],
            "criterion_id": "band_gap",
            "document_id": document["document_id"],
            "quote": source["metadata"]["abstract"],
            "judgment": "concern",
            "interpretation": "TEST ONLY conflicting interpretation retained "
            "for source comparison.",
        },
    ]
    result["literature_evaluation"] = evaluate_candidates(
        {"evaluations": proposals},
        result["candidate_leads"],
        report["sources"],
        result["execution"]["ranking_profile"],
        version="literature-fit-v1",
    )["evaluation"]
    prepared = prepare_presentation(report)
    text = prepared["technical_audit"]
    assert "Mixed evidence:" in text
    assert "conflicting interpretation retained" in text
    assert "protocol interpretation of the cited comparison" in text
    assert "TEST ONLY conflicting reference" in text


def test_later_retained_source_documents_are_not_evicted_during_report_rebinding():
    report = evaluated_report()
    unrelated = []
    for index in range(30):
        source = deepcopy(report["sources"][0])
        source.update(
            record_id=f"W{200 + index}", url=f"https://openalex.org/W{200 + index}"
        )
        source["metadata"][
            "abstract"
        ] = "TEST ONLY unrelated public document for bounded selection regression."
        unrelated.append(source)
    report["sources"] = [*unrelated, *report["sources"]]
    assert not any(
        document["url"] == "https://openalex.org/W1"
        for document in discovery_documents(report["sources"])
    )
    prepared = prepare_presentation(report)
    assert "Fixture-A" in prepared["technical_audit"]
    assert "Provisional literature shortlist" in prepared["pi_summary"]
