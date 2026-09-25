"""Synthetic protocol fixtures only; no material properties or live
sources."""

import io
import json
import zipfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree

import pytest
from pypdf import PdfReader

from labcat.config import load_config
from labcat.report_exports import (
    ExportError,
    prepare_presentation,
    render_download,
)
from labcat.science.candidate_leads import (
    discovery_documents,
    validate_candidate_leads,
)
from labcat.science.reporting import citation_references, render_reports


def lead_report():
    sources, proposals = [], []
    for index in range(12):
        name = "Fixture-" + chr(ord("A") + index)
        quote = (
            f"TEST ONLY: {name} appears as a comparison in this synthetic passage. "
            "This fixture establishes no material performance or suitability."
        )
        source = {
            "source_id": "openalex",
            "record_id": f"W{index + 1}",
            "source_name": "Synthetic OpenAlex protocol fixture",
            "url": f"https://openalex.org/W{index + 1}",
            "title": f"TEST ONLY literature record {index + 1}",
            "kind": "discovery_reference",
            "access_scope": "public",
            "is_material_evidence": False,
            "provenance_status": "verified",
            "provenance": {"response_sha256": "a" * 64},
            "metadata": {"abstract_read": True, "abstract": quote},
        }
        sources.append(source)
        proposals.append(
            {
                "document_id": discovery_documents([source])[0]["document_id"],
                "name": name,
                "quote": quote,
            }
        )
    leads = validate_candidate_leads(
        proposals,
        discovery_documents(sources),
        sources,
        {"stability": 1, "band_gap": 1, "custom_transport": 1},
    )
    assert len(leads) == 12
    config = load_config()
    result = {
        "stage": "public_discovery",
        "candidates": [],
        "candidate_leads": leads,
        "summary": "The synthetic retrieval has no quantitative property evidence.",
        "reason": "TEST ONLY quantitative adapter unavailable.",
        "ranking": {"weights": {"stability": 0.5, "band_gap": 0.5}},
        "execution": {"presentation": config.to_dict()["presentation"]},
        "public_discovery": {"source_statuses": [], "caveats": []},
    }
    summary, technical = render_reports(result, config, sources)
    return {
        "id": "test_lead_report",
        "title": "Synthetic candidate-lead report",
        "stage": "test",
        "created_at": "2026-09-10T00:00:00Z",
        "pi_summary": summary,
        "technical_audit": technical,
        "sources": sources,
        "result": result,
    }


def test_summary_and_technical_preserve_distinct_unscored_leads():
    report = lead_report()
    before = deepcopy(report)
    summary, technical = report["pi_summary"], report["technical_audit"]
    assert "Public sources name 12 candidate leads" in summary
    assert "Fixture-E" in summary and "Fixture-F" not in summary
    assert "This compact table shows 5 of 12 leads" in summary
    for lead in report["result"]["candidate_leads"]:
        assert lead["name"] in technical and lead["quote"] in technical
        for caution in lead["cautions"]:
            assert caution in technical
    for text in (summary, technical):
        assert "Review order is not a performance ranking" in text
        assert "Missing measurements" in text
        assert "Room-temperature phase stability" in text
        assert "Custom transport" in text
        assert "unknown does not mean stable" in text
        assert "No application suitability" in text
        assert "TEST ONLY quantitative adapter unavailable" in text
        assert "| Rank |" not in text
    for table in ("summary", "technical"):
        assert report["result"]["report_tables"][table]["rows"] == []
    current = replace(
        load_config(),
        presentation=replace(
            load_config().presentation, terminology="specialist", verbosity="detailed"
        ),
    )
    presented = prepare_presentation(report, "current", current)
    assert presented["result"]["candidate_leads"] == before["result"]["candidate_leads"]
    assert presented["presentation"]["verbosity"] == "detailed"
    assert report == before


@pytest.mark.parametrize(
    "change", ["quote", "url", "flag", "score", "missing", "source", "duplicate"]
)
def test_corrupt_saved_lead_cannot_be_formatted_as_source_grounded(change):
    report = lead_report()
    lead = report["result"]["candidate_leads"][0]
    if change == "quote":
        lead["quote"] = lead["citations"][0]["quote"] = "Invented unsupported passage."
    elif change == "url":
        lead["url"] = lead["citations"][0]["url"] = "https://example.com/invented"
    elif change == "flag":
        lead["properties_verified"] = True
    elif change == "score":
        lead["score"] = 1
    elif change == "missing":
        lead["missing_criteria"].remove("operational_stability")
    elif change == "source":
        report["sources"][0]["metadata"]["abstract_read"] = False
    else:
        report["result"]["candidate_leads"] = [lead, deepcopy(lead)]
    original = report["pi_summary"]
    with pytest.raises(ExportError, match="cannot be formatted safely"):
        prepare_presentation(report)
    assert report["pi_summary"] == original


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_every_export_keeps_lead_names_quotes_gaps_and_approved_links(format):
    report = prepare_presentation(lead_report())
    body = render_download(report, format, "both")[0]
    if format == "pdf":
        reader = PdfReader(io.BytesIO(body))
        text = " ".join(page.extract_text() for page in reader.pages)
        urls = {
            str(annotation.get_object().get("/A", {}).get("/URI", ""))
            for page in reader.pages
            for annotation in page.get("/Annots", [])
        }
        assert "https://openalex.org/W12" in urls
    elif format == "docx":
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
            text = " ".join(root.itertext())
            assert b"https://openalex.org/W12" in archive.read(
                "word/_rels/document.xml.rels"
            )
    else:
        text = body.decode()
    text = " ".join(text.split())
    for lead in report["result"]["candidate_leads"]:
        assert lead["name"] in text
    assert "Missing measurements" in text
    assert "Review order" in text
    assert "no material performance or suitability" in text
    assert "unknown does not mean stable" in text


def test_frontend_fixture_is_the_actual_python_report_contract():
    report = lead_report()
    path = (
        Path(__file__).parents[1] / "frontend/tests/fixtures/candidate-lead-report.json"
    )
    assert json.loads(path.read_text()) == {
        "summary": report["pi_summary"],
        "technical": report["technical_audit"],
        "leads": report["result"]["candidate_leads"],
        "references": citation_references(report["result"], report["sources"]),
    }


def test_casefold_merged_citations_revalidate_without_changing_selected_name():
    report = lead_report()
    first, second = report["sources"][:2]
    first["metadata"][
        "abstract"
    ] = "TEST ONLY: fixture-ß and Fixture-ß are synthetic names."
    second["metadata"][
        "abstract"
    ] = "TEST ONLY: FIXTURE-SS is another synthetic mention."
    documents = discovery_documents([first, second])
    leads = validate_candidate_leads(
        [
            {
                "document_id": documents[0]["document_id"],
                "name": "Fixture-ß",
                "quote": first["metadata"]["abstract"],
            },
            {
                "document_id": documents[1]["document_id"],
                "name": "FIXTURE-SS",
                "quote": second["metadata"]["abstract"],
            },
        ],
        documents,
        [first, second],
    )
    assert len(leads) == 1 and len(leads[0]["citations"]) == 2
    report["sources"] = [first, second]
    report["result"]["candidate_leads"] = deepcopy(leads)
    prepared = prepare_presentation(report)
    assert prepared["result"]["candidate_leads"] == leads
    assert "FIXTURE-SS" in prepared["technical_audit"]
    assert "Fixture-ß" in prepared["pi_summary"]
