"""Unscored, synthetic adapter observations retain citations in saved
exports."""

import io
import json
from copy import deepcopy
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from pypdf import PdfReader
from test_evidence_comparison_workflow import adapter_record

from labcat import science
from labcat.config import load_config
from labcat.report_exports import (
    ExportError,
    _links,
    prepare_presentation,
    render_download,
)
from labcat.research_intent import resolve_intent
from labcat.science.ranking import rank_records
from labcat.science.reporting import render_reports
from labcat.workspace import WorkspaceStore

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


@pytest.fixture
def saved_review_report(tmp_path):
    prompt = "Find semiconductors and minimize band gap."
    scope = resolve_intent(
        prompt,
        {
            "decision": "materials_research",
            "intent": {
                "material_class": "semiconductors",
                "identity_scope": "bulk",
                "application": "unknown",
                "target_spans": ["semiconductors"],
                "application_spans": [],
                "environment_spans": [],
                "processing_spans": [],
                "goals": [
                    {
                        "attribute_id": "band_gap",
                        "request_span": "minimize band gap",
                        "priority": "primary",
                        "relation": "minimize",
                    }
                ],
            },
        },
        None,
        None,
    )["scope"]
    record = adapter_record(991, 1.4, True)
    candidates, ranking = rank_records(
        [deepcopy(record)],
        load_config(),
        importance={"band_gap": 1},
        goal_review={"scope": scope, "prompt": prompt, "authority": "inferred"},
    )
    assert candidates == []
    assert ranking["excluded_records"][0]["unscored_goal_reasons"]
    records = [deepcopy(record)]
    sources = science._sources([], records)
    result = {
        "stage": "partial",
        "summary": "Synthetic export fixture; no scientific recommendation.",
        "candidates": [],
        "ranking": ranking,
        "review_records": records,
    }
    summary, technical = render_reports(result, load_config(), sources)
    outcome = {
        "stage": "partial",
        "answer": "Synthetic export fixture.",
        "pi_summary": summary,
        "technical_audit": technical,
        "result": result,
        "sources": sources,
    }
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY unscored export")
    chat = store.create_global_chat("TEST ONLY unscored export", project["id"])
    store.append_research(chat["id"], project["id"], prompt, outcome)
    detail = WorkspaceStore(store.path).get_global_chat(chat["id"])
    return {**detail["reports"][0], "sources": detail["sources"]}


@pytest.mark.parametrize("settings", ["saved", "current"])
def test_saved_review_sources_rebind_without_creating_scores(
    saved_review_report, settings
):
    original = deepcopy(saved_review_report)
    prepared = prepare_presentation(saved_review_report, settings, load_config())
    record = prepared["result"]["review_records"][0]
    source_id = "material:" + record["material_id"]
    assert record["source_ids"] == [source_id]
    assert prepared["sources"][0]["source_id"] == source_id
    assert prepared["sources"][0]["provenance"] == record["provenance"]
    assert prepared["references"][0]["url"] == record["provenance"]["source_url"]
    assert prepared["result"]["candidates"] == []
    assert not {"rank", "score", "utility", "overall_utility"} & set(record)
    assert saved_review_report == original
    for view in ("pi_summary", "technical_audit"):
        assert "[R1]" in prepared[view]
        assert "1.4" in prepared[view]


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_review_downloads_keep_citations_and_formula_typography(
    saved_review_report, format
):
    prepared = prepare_presentation(saved_review_report, config=load_config())
    body, _, _ = render_download(prepared, format, "both")
    url = prepared["result"]["review_records"][0]["provenance"]["source_url"]
    if format == "json":
        payload = json.loads(body)
        assert (
            payload["result"]["review_records"]
            == saved_review_report["result"]["review_records"]
        )
        assert payload["result"]["candidates"] == []
        assert any(ref["url"] == url for ref in payload["references"])
        text = " ".join(payload["views"].values())
    elif format == "pdf":
        pages = PdfReader(io.BytesIO(body)).pages
        text = " ".join(page.extract_text() for page in pages)
        links = [
            annotation.get_object().get("/A", {}).get("/URI")
            for page in pages
            for annotation in page.get("/Annots", [])
        ]
        assert url in links
    elif format == "docx":
        with ZipFile(io.BytesIO(body)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
            relationships = ElementTree.fromstring(
                archive.read("word/_rels/document.xml.rels")
            )
        text = " ".join(node.text or "" for node in root.iter(W + "t"))
        assert any(
            node.get(W + "val") == "subscript" for node in root.iter(W + "vertAlign")
        )
        assert any(
            node.get("Target") == url
            for node in relationships.iter(REL + "Relationship")
        )
    else:
        text = body.decode()
        assert url in text
    assert "[R1]" in text
    assert "1.4" in text


@pytest.mark.parametrize("reviews", [None, {}, "invalid", [{}] * 13])
def test_invalid_or_oversize_review_lists_cannot_be_reformatted(
    saved_review_report, reviews
):
    saved_review_report["result"]["review_records"] = reviews
    with pytest.raises(ExportError, match="review evidence"):
        prepare_presentation(saved_review_report)


def test_review_record_missing_verified_source_cannot_be_reformatted(
    saved_review_report,
):
    saved_review_report["sources"] = []
    with pytest.raises(ExportError, match="cannot be formatted safely"):
        prepare_presentation(saved_review_report)


def test_cli_provenance_links_include_unscored_review_records(saved_review_report):
    record = saved_review_report["result"]["review_records"][0]
    report = {"result": {"candidates": [], "review_records": [record]}}
    assert record["provenance"]["source_url"] in _links(report, {})
    report["result"]["review_records"] = "invalid"
    assert _links(report, {}) == set()
