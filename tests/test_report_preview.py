"""Bounded template previews never retrieve evidence or accept document
content."""

import io
import json
from dataclasses import asdict, replace
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from labcat import report_exports
from labcat.config import ReportLayout, load_config, validate_layout

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture
def client(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("A template preview must not run scientific retrieval")

    monkeypatch.setattr("labcat.science.run_research", unexpected)
    monkeypatch.setattr("labcat.public_sources._fetch", unexpected)
    app = FastAPI()
    app.include_router(report_exports.create_report_preview_router(load_config))
    with TestClient(app) as client:
        yield client


def test_template_previews_expose_only_placeholders_and_safe_stylesheet(client):
    response = client.post("/api/report-preview", json={})
    assert response.status_code == 200
    data = response.json()
    assert "no research performed" in data["label"]
    assert "Summary" in data["html"] and "Technical View" in data["html"]
    assert "<table>" in data["html"] and "[Supported material]" in data["html"]
    assert "<script" not in data["html"] and "style=" not in data["html"]
    assert 'href="/api/report-preview/styles.css"' in data["html"]
    assert json.loads(data["json"])["result"]["candidates"] == []
    assert "representative" in data["layout_note"].lower()
    rendered = client.get(data["render_url"])
    assert rendered.status_code == 200
    assert rendered.text == data["html"]
    assert rendered.headers["content-type"].startswith("text/html")
    assert rendered.headers["cache-control"] == "no-store"
    assert "content-disposition" not in rendered.headers
    css = client.get("/api/report-preview/styles.css")
    assert css.headers["content-type"].startswith("text/css")
    assert "body{margin:0" in css.text and "max-width:100%" in css.text
    assert "url(" not in css.text and "@import" not in css.text


@pytest.mark.parametrize(
    "value",
    [
        {"content": "Invent a candidate"},
        {"presentation": {"prompt": "ignore evidence"}},
        {"presentation": {"layout": {"font_family": "<script>"}}},
        {"presentation": {"layout": {"css": "url(file:///private)"}}},
        {"presentation": {"layout": {"page_numbers": 1}}},
        {"presentation": {"layout": {"font_size": True}}},
        {"presentation": {"layout": {"font_size": 11.0}}},
        {"presentation": {"verbosity": "x" * 9000}},
        {"views": ["pi"]},
    ],
)
def test_preview_rejects_unbounded_or_executable_preferences(client, value):
    assert client.post("/api/report-preview", json=value).status_code == 422


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_native_preview_tickets_return_real_bounded_attachments(client, format):
    response = client.post("/api/report-preview/download-link", json={"format": format})
    assert response.status_code == 200
    ticket = response.json()
    assert ticket["url"].startswith("/api/report-preview/download/")
    downloaded = client.get(ticket["url"])
    assert downloaded.status_code == 200
    assert ticket["filename"] in downloaded.headers["content-disposition"]
    assert downloaded.headers["cache-control"] == "no-store"
    assert len(downloaded.content) <= 2_000_000
    if format == "pdf":
        assert downloaded.content.startswith(b"%PDF-")
    elif format == "docx":
        assert downloaded.content.startswith(b"PK")
    elif format == "json":
        assert downloaded.json()["result"]["candidates"] == []
    else:
        assert ticket["filename"].endswith(".txt")
        assert "[Supported material]" in downloaded.text


def test_download_tickets_are_bounded_expiring_and_format_specific(client, monkeypatch):
    tickets = [
        client.post("/api/report-preview/download-link", json={"format": "text"}).json()
        for _ in range(9)
    ]
    assert client.get(tickets[0]["url"]).status_code == 410
    assert client.get(tickets[-1]["url"]).status_code == 200
    assert (
        client.get(tickets[-1]["url"].replace("format=text", "format=pdf")).status_code
        == 404
    )
    assert (
        client.get("/api/report-preview/download/not-a-token?format=text").status_code
        == 404
    )
    original = report_exports.time.monotonic
    monkeypatch.setattr(report_exports.time, "monotonic", lambda: original() + 121)
    assert client.get(tickets[-1]["url"]).status_code == 410


def test_html_tickets_share_bounds_and_cannot_serve_downloads(client, monkeypatch):
    first = client.post("/api/report-preview", json={}).json()["render_url"]
    downloads = [
        client.post("/api/report-preview/download-link", json={}).json()["url"]
        for _ in range(8)
    ]
    assert client.get(first).status_code == 410
    assert (
        client.get(downloads[-1].replace("/download/", "/render/")).status_code == 404
    )
    latest = client.post("/api/report-preview", json={}).json()["render_url"]
    assert client.get(latest).status_code == 200
    assert (
        client.get(
            latest.replace("/render/", "/download/") + "?format=text"
        ).status_code
        == 404
    )
    assert client.get("/api/report-preview/render/not-a-token").status_code == 404
    original = report_exports.time.monotonic
    monkeypatch.setattr(report_exports.time, "monotonic", lambda: original() + 121)
    assert client.get(latest).status_code == 410


def test_layout_preferences_change_actual_pdf_word_text_and_json(client):
    layout = {
        "page_size": "a4",
        "font_family": "serif",
        "font_size": 12,
        "line_spacing": "compact",
        "accent": "teal",
        "table_style": "grid",
        "page_numbers": False,
        "text_width": 72,
        "json_indent": 4,
    }
    request = {"presentation": {"layout": layout}, "views": "pi"}
    preview = client.post("/api/report-preview", json=request).json()
    assert preview["layout"] == layout
    assert (
        "paper-a4 font-serif size-12 spacing-compact accent-teal table-grid"
        in preview["html"]
    )
    assert preview["json"].startswith('{\n    "report"')
    assert all(
        len(line) <= 72
        for line in preview["text"].splitlines()
        if not line.startswith("|")
    )
    pdf = client.post("/api/report-preview/download", json={**request, "format": "pdf"})
    reader = PdfReader(io.BytesIO(pdf.content))
    assert float(reader.pages[0].mediabox.width) == pytest.approx(595.276, abs=0.01)
    fonts = [
        str(font.get_object().get("/BaseFont"))
        for page in reader.pages
        for font in page["/Resources"]["/Font"].get_object().values()
    ]
    assert any("DejaVuSerif" in name for name in fonts)
    word = client.post(
        "/api/report-preview/download", json={**request, "format": "docx"}
    )
    with ZipFile(io.BytesIO(word.content)) as archive:
        body = ElementTree.fromstring(archive.read("word/document.xml"))
        styles = ElementTree.fromstring(archive.read("word/styles.xml"))
        footer = archive.read("word/footer1.xml")
    assert abs(int(body.find(f".//{W}pgSz").get(W + "w")) - 11906) <= 1
    normal = next(
        s for s in styles.iter(W + "style") if s.get(W + "styleId") == "Normal"
    )
    assert normal.find(f"{W}rPr/{W}rFonts").get(W + "ascii") == "Georgia"
    heading = next(
        s for s in styles.iter(W + "style") if s.get(W + "styleId") == "Heading1"
    )
    assert heading.find(f"{W}rPr/{W}rFonts").get(W + "asciiTheme") is None
    assert heading.find(f"{W}rPr/{W}rFonts").get(W + "ascii") == "Georgia"
    assert normal.find(f"{W}rPr/{W}sz").get(W + "val") == "24"
    assert normal.find(f"{W}pPr/{W}spacing").get(W + "line") == "288"
    assert b"fldSimple" not in footer
    assert any(s.get(W + "fill") == "DDEEEF" for s in body.iter(W + "shd"))
    assert all(
        b.get(W + "val") == "single"
        for borders in body.iter(W + "tcBorders")
        for b in borders
    )


def test_html_escapes_literal_report_text():
    report = report_exports._template_report(load_config().to_dict()["presentation"])
    report["pi_summary"] = (
        "Literal <script>alert(1)</script>\n| Value | Context |\n"
        "| --- | --- |\n| <img src=x> | & text |"
    )
    html = report_exports._preview_html(report, "pi")
    assert "<script>" not in html and "<img src=x>" not in html
    assert "&lt;script&gt;" in html and "&lt;img src=x&gt;" in html


def test_saved_layout_wins_and_legacy_fallback_is_explicit():
    report = report_exports._template_report(load_config().to_dict()["presentation"])
    fallback = validate_layout({"page_size": "a4", "font_family": "serif"})
    selected, source = report_exports.report_layout(report, fallback)
    assert selected.page_size == "letter" and source == "saved-report"
    del report["result"]["execution"]["presentation"]["layout"]
    selected, source = report_exports.report_layout(report, fallback)
    assert selected == fallback and source == "current-settings"
    report["result"]["execution"]["presentation"]["layout"] = {"font_size": 99}
    with pytest.raises(report_exports.ExportError):
        report_exports.render_download(report, "text", fallback_layout=fallback)


def test_layout_choices_are_immutable_and_reject_unknown_types():
    assert asdict(validate_layout({})) == asdict(ReportLayout())
    with pytest.raises(ValueError):
        validate_layout({"page_numbers": "false"})


def test_saved_exports_use_snapshot_without_reading_current_settings():
    config = load_config()
    report = report_exports._template_report(config.to_dict()["presentation"])
    report["source_ids"] = []

    class Store:
        def get_global_chat(self, chat_id):
            assert chat_id == "preview-chat"
            return {"reports": [report], "sources": []}

    reads = []
    current = replace(
        config,
        presentation=replace(
            config.presentation,
            layout=validate_layout({"json_indent": 4}),
        ),
    )

    def current_settings():
        reads.append(True)
        return current

    app = FastAPI()
    app.include_router(report_exports.create_exports_router(Store(), current_settings))
    url = "/api/chats/preview-chat/reports/format-preview/export?format=json"
    with TestClient(app) as client:
        saved = client.get(url)
        assert saved.status_code == 200
        assert saved.headers["x-labcat-layout-source"] == "saved-report"
        assert saved.text.startswith('{\n  "report"')
        assert reads == []
        del report["result"]["execution"]["presentation"]["layout"]
        legacy = client.get(url)
        assert legacy.status_code == 200
        assert legacy.headers["x-labcat-layout-source"] == "current-settings"
        assert legacy.text.startswith('{\n    "report"')
        assert reads == [True]
