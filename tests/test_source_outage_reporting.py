"""Transport-status fixtures preserve completed evidence without
inventing rows."""

import io
import json
from copy import deepcopy
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from pypdf import PdfReader

from labcat import science
from labcat.config import load_config
from labcat.report_exports import prepare_presentation, render_download
from labcat.science.candidate_leads import (
    discovery_documents,
    validate_candidate_leads,
)
from labcat.science.reporting import render_reports


@pytest.fixture
def partial_report(historical_property_fixture):
    outcome = science.run_research(
        "Find oxide dielectric materials for thin-film screening", load_config()
    )
    report = {
        "id": "source-outage-fixture",
        "title": "TEST ONLY partial report",
        **outcome,
    }
    report["stage"] = "partial"
    result = report["result"]
    result["retrieval"]["repository_attempts"] = [
        {"repository": "nomad", "status": "ok"},
        {
            "repository": "materials_project",
            "status": "unavailable",
            "reason": "SECRET",
        },
    ]
    result["retrieval"]["discovery_leads"] = {
        "attempts": [
            {"repository": "nomad", "status": "unavailable", "error": "SECRET"},
            {"repository": "nomad", "status": "unavailable"},
            {"repository": "hybrid3", "status": "budget_exhausted"},
        ]
    }
    result["retrieval"]["chat_source_refresh"] = {
        "attempts": [{"repository": "public_dielectric", "status": "unavailable"}]
    }
    result["public_discovery"] = {
        "source_statuses": [
            {"source_id": "arxiv", "status": "unavailable", "message": "SECRET"},
            {"source_id": "openalex", "status": "no_results"},
            {"source_id": "europe_pmc", "status": "ok"},
        ]
    }
    return report


def render(report):
    report["pi_summary"], report["technical_audit"] = render_reports(
        report["result"], load_config(), report["sources"]
    )
    return report["pi_summary"], report["technical_audit"]


def test_source_outages_leave_completed_candidates_scores_and_citations_intact(
    partial_report,
):
    result = partial_report["result"]
    candidates = deepcopy(result["candidates"])
    sources = deepcopy(partial_report["sources"])
    for text in render(partial_report):
        assert "Source availability:" in text
        assert "Materials Project (property search)" in text
        assert "arXiv (reference search)" in text
        assert text.count("NOMAD (candidate lookup)") == 1
        assert "NOMAD (property search)" not in text
        assert "Public dielectric dataset (saved-source refresh)" in text
        assert "Retrieval time limit reached: HybriD³ (candidate lookup)" in text
        assert "Completed results are retained" in text
        assert "failed lookup does not establish that evidence is absent" in text
        assert "not treated as measured zeros" in text
        assert "SECRET" not in text
        assert "OpenAlex (reference search)" not in text
        assert "[R1]" in text
    assert result["candidates"] == candidates
    assert partial_report["sources"] == sources
    assert result["report_tables"]["technical"]["rows"]


def test_all_sources_down_still_produce_views_with_actionable_coverage_gaps(
    partial_report,
):
    result = partial_report["result"]
    result.update(
        candidates=[],
        comparison_records=[],
        summary="The selected sources were unavailable for this run.",
    )
    result["retrieval"]["records_retrieved"] = 0
    result["ranking"]["evidence_comparisons"] = []
    partial_report["sources"] = []
    summary, technical = render(partial_report)
    for text in (summary, technical):
        assert "Materials Project (property search)" in text
        assert "arXiv (reference search)" in text
        assert "Coverage is incomplete" in text
        assert "Completed results are retained" not in text
        assert "SECRET" not in text
    assert "There is not enough validated, relevant property evidence" in summary
    assert "No scored shortlist was produced" in technical
    assert result["report_tables"]["technical"]["rows"] == []


def test_no_records_is_distinct_from_unavailable_and_disabled_sources(partial_report):
    result = partial_report["result"]
    result["retrieval"] = {
        "repository_attempts": [{"repository": "nomad", "status": "no_records"}]
    }
    result["public_discovery"] = {
        "source_statuses": [
            {"source_id": "arxiv", "status": "skipped"},
            {"source_id": "openalex", "status": "no_results"},
        ]
    }
    for text in render(partial_report):
        assert "Source availability:" not in text


def test_completed_cited_lead_survives_other_sources_failing(partial_report):
    quote = "TEST ONLY: FixtureLead appears in this synthetic source passage."
    source = {
        "source_id": "arxiv",
        "record_id": "2601.00001",
        "title": "TEST ONLY source fixture",
        "source_name": "arXiv",
        "url": "https://arxiv.org/abs/2601.00001",
        "kind": "discovery_reference",
        "access_scope": "public",
        "is_material_evidence": False,
        "provenance_status": "verified",
        "provenance": {"response_sha256": "a" * 64},
        "metadata": {"abstract_read": True, "abstract": quote},
    }
    documents = discovery_documents([source])
    leads = validate_candidate_leads(
        [
            {
                "document_id": documents[0]["document_id"],
                "name": "FixtureLead",
                "quote": quote,
            }
        ],
        documents,
        [source],
        {"band_gap": 1},
    )
    assert len(leads) == 1
    result = partial_report["result"]
    result.update(candidates=[], comparison_records=[], candidate_leads=leads)
    result["ranking"]["evidence_comparisons"] = []
    result["public_discovery"]["source_statuses"] = [
        {"source_id": "arxiv", "status": "ok"},
        {"source_id": "openalex", "status": "unavailable"},
    ]
    partial_report["sources"] = [source]
    for text in render(partial_report):
        assert "FixtureLead" in text and "[S1]" in text
        assert "OpenAlex (reference search)" in text
        assert "Completed results are retained" in text
        assert "Review order is not a performance ranking" in text
        assert "unknown does not mean stable" in text
    assert result["candidate_leads"] == leads
    assert result["report_tables"]["technical"]["rows"] == []


def test_malformed_status_metadata_cannot_break_valid_reports_or_leak_raw_text(
    partial_report,
):
    statuses = partial_report["result"]["public_discovery"]["source_statuses"]
    statuses.extend(
        [
            None,
            "SECRET",
            {"source_id": {"secret": "SECRET"}, "status": "unavailable"},
            {"source_id": "arxiv", "status": ["SECRET"]},
            {"source_id": "SECRET", "status": "unavailable"},
        ]
    )
    for text in render(partial_report):
        assert "arXiv (reference search)" in text
        assert "SECRET" not in text


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_reformatted_exports_keep_source_outages_and_valid_results(
    partial_report, format
):
    render(partial_report)
    prepared = prepare_presentation(partial_report, "current", load_config())
    body, _, _ = render_download(prepared, format, "both")
    if format == "json":
        decoded = json.loads(body)
        text = " ".join(decoded["views"].values())
        assert decoded["result"]["candidates"] == prepared["result"]["candidates"]
    elif format == "pdf":
        text = " ".join(
            page.extract_text() for page in PdfReader(io.BytesIO(body)).pages
        )
    elif format == "docx":
        with ZipFile(io.BytesIO(body)) as archive:
            xml = ElementTree.fromstring(archive.read("word/document.xml"))
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        text = " ".join(
            "".join(node.text or "" for node in paragraph.iter(namespace + "t"))
            for paragraph in xml.iter(namespace + "p")
        )
    else:
        text = body.decode()
    text = " ".join(text.split())
    assert "Materials Project (property search)" in text
    assert "arXiv (reference search)" in text
    assert "Completed results are retained" in text
    assert "[R1]" in text
    assert "SECRET" not in text
