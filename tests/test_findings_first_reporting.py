"""Results precede diagnostics without changing the saved scientific
record."""

import io
import json
from copy import deepcopy
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from pypdf import PdfReader
from test_literature_evaluation_reporting import evaluated_report
from test_preliminary_ranking_reporting import preliminary_report

from labcat.config import load_config
from labcat.report_exports import _blocks, prepare_presentation, render_download
from labcat.science import run_research


@pytest.mark.parametrize("assessed", [False, True])
def test_saved_reports_lead_with_findings_and_shortlist_without_research(
    assessed, monkeypatch
):
    report = preliminary_report(assessed=assessed)
    report["pi_summary"] = "Summary:\n\nOriginal saved summary.\n"
    report["technical_audit"] = "Technical View:\n\nOriginal saved technical text.\n"
    result = report["result"]
    result["public_discovery"]["source_statuses"] = [
        {"source_id": "openalex", "status": "unavailable"}
    ]
    result["execution"].update(
        model_stopped_after_report=True,
        stop_reason="server_report_retained",
        agent={"status": "stopped_after_report"},
    )
    before = deepcopy(report)

    def forbidden(*args, **kwargs):
        raise AssertionError("Reformatting must not start new research.")

    monkeypatch.setattr("labcat.science.run_research", forbidden)
    prepared = prepare_presentation(report)
    for field in ("pi_summary", "technical_audit"):
        text = prepared[field]
        opening, appendix = text.split("Search and analysis details:", 1)
        assert (
            opening.index("Findings and recommendations:")
            < opening.index("Candidate shortlist:")
            < opening.index("Interpretation and tradeoffs:")
        )
        assert "Source availability:" not in opening
        assert "Research completion:" not in opening
        assert "Candidate assessment:" not in opening
        assert "Source availability:" in appendix
        assert "Research completion:" in appendix
        assert "Candidate assessment:" in appendix
        header = "| Rank | Material | Screening priority |"
        assert opening.count(header) == 1
        assert header not in appendix
        table = next(data for kind, data, _ in _blocks(text) if kind == "table")
        assert (
            len(table) == len(result["literature_evaluation"]["ranked_candidates"]) + 1
        )
        assert "[S" in opening
        assert prepared["archive"][field] == before[field]
    assert report == before
    assert prepared["original_result"] == before["result"]
    assert (
        prepared["result"]["literature_evaluation"] == result["literature_evaluation"]
    )


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_downloads_keep_findings_first_and_include_complete_analysis(format):
    report = prepare_presentation(preliminary_report(assessed=True))
    body, _, _ = render_download(report, format, "both")
    if format == "json":
        payload = json.loads(body)
        texts = [payload["views"]["pi"], payload["views"]["audit"]]
    elif format == "pdf":
        texts = [
            "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(body)).pages)
        ]
    elif format == "docx":
        with ZipFile(io.BytesIO(body)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
        texts = ["\n".join(node.text or "" for node in root.iter(tag))]
    else:
        texts = [body.decode()]
    for text in texts:
        assert (
            text.index("Findings and recommendations")
            < text.index("Candidate shortlist")
            < text.index("Search and analysis details")
        )
        assert "Candidate assessment" in text
    assert "Algorithm: literature-fit-v2" in texts[-1]


def test_property_and_legacy_literature_shortlists_remain_above_details(
    historical_property_fixture,
):
    measured = run_research("Find oxide dielectric candidates", load_config())
    for field in ("pi_summary", "technical_audit"):
        text = measured[field]
        opening, appendix = text.split("Search and analysis details:", 1)
        assert "Findings and recommendations:" in opening
        assert any(kind == "table" for kind, _, _ in _blocks(opening))
        assert "Ranking method:" not in opening
        if field == "technical_audit":
            assert "Ranking method:" in appendix
    legacy = prepare_presentation(evaluated_report())
    for field in ("pi_summary", "technical_audit"):
        text = legacy[field]
        assert text.index("Provisional literature shortlist:") < text.index(
            "Search and analysis details:"
        )
        assert text.count("| Provisional rank |") == 1


def test_literature_recommendations_and_property_records_have_one_primary_shortlist(
    historical_property_fixture,
):
    from labcat.science.reporting import render_reports

    report = preliminary_report(assessed=True)
    measured = run_research("Find oxide dielectric candidates", load_config())
    report["result"]["candidates"] = measured["result"]["candidates"]
    report["result"]["retrieval"] = measured["result"]["retrieval"]
    report["sources"] += measured["sources"]
    before = deepcopy(report)
    summary, technical = render_reports(
        deepcopy(report["result"]), load_config(), report["sources"]
    )
    for text in (summary, technical):
        main, appendix = text.split("Search and analysis details:", 1)
        assert main.count("Candidate shortlist:") == 1
        assert sum(kind == "table" for kind, _, _ in _blocks(main)) == 1
        assert "Measured-property shortlist:" not in main
        assert "Supporting property records:" in appendix
        assert "property score is separate" in appendix
        assert "Property record 1" not in main
        assert any(kind == "table" for kind, _, _ in _blocks(appendix))
    assert "Candidate 1 —" in technical
    assert "Comparison of the leading candidates:" in technical
    assert "Candidate score 1 —" in technical.split("Search and analysis details:")[1]
    assert report == before
