"""Saved report downloads preserve selected views and cannot execute
report markup."""

import io
import json
import subprocess
import sys
import zipfile
from dataclasses import replace
from xml.etree import ElementTree

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from labcat.config import load_config
from labcat.report_exports import (
    ExportError,
    _blocks,
    create_exports_router,
    render_download,
)
from labcat.science import run_research
from labcat.workspace import WorkspaceStore

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture
def report(historical_property_fixture):
    outcome = run_research(
        "Find oxide dielectric candidates for thin films", load_config()
    )
    return {
        "id": "report_123",
        "title": "Oxide dielectric triage",
        "stage": outcome["stage"],
        "created_at": "2026-09-09T12:00:00Z",
        **outcome,
    }


def _pdf_text(body):
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(body)).pages)


def _docx_text(body):
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
        return "\n".join(
            "".join(node.text or "" for node in paragraph.iter(W + "t"))
            for paragraph in root.iter(W + "p")
        )


def _decode(body, format):
    if format == "pdf":
        return _pdf_text(body)
    if format == "docx":
        return _docx_text(body)
    return body.decode()


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
@pytest.mark.parametrize("views", ["pi", "audit", "both"])
def test_view_selection_metadata_and_safe_filename(report, format, views):
    report["pi_summary"] = "PI_ONLY_MARKER\nCaveat: unassessed."
    report["technical_audit"] = (
        "AUDIT_ONLY_MARKER\nSource: https://www.nature.com/articles/sdata2016134"
    )
    report["private_path"] = "/Users/private/secret-vault.json"
    report["api_key"] = "never-exported-key"
    body, media, filename = render_download(report, format, views)
    text = _decode(body, format)
    assert ("PI_ONLY_MARKER" in text) == (views in {"pi", "both"})
    assert ("AUDIT_ONLY_MARKER" in text) == (views in {"audit", "both"})
    assert "never-exported-key" not in text
    assert "/Users/private" not in text
    assert (
        filename == f"labcat-report_123-{views}.{'txt' if format == 'text' else format}"
    )
    assert "report_123" in text
    assert media.startswith(
        {
            "text": "text/plain",
            "json": "application/json",
            "pdf": "application/pdf",
            "docx": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        }[format]
    )


def test_json_saved_views_are_objects_not_escaped_strings(report):
    report["pi_summary"] = json.dumps({"summary": "Saved PI", "caveats": ["Unknown"]})
    report["technical_audit"] = json.dumps(
        {"ranking": {"band_gap": 0.5}, "sources": []}
    )
    body, _, _ = render_download(report, "json", "both")
    payload = json.loads(body)
    assert payload["views"]["pi"]["summary"] == "Saved PI"
    assert payload["views"]["audit"]["ranking"] == {"band_gap": 0.5}
    for format in ("text", "pdf", "docx"):
        text = _decode(render_download(report, format, "both")[0], format)
        assert "Saved PI" in text
        assert "Unknown" in text
        assert '\\"ranking\\"' not in text


def test_json_technical_exports_retain_structured_research_without_widening_pi(report):
    report["pi_summary"] = "Saved written summary."
    report["technical_audit"] = "Saved written technical overview."
    for views in ("pi", "audit", "both"):
        body, _, _ = render_download(report, "json", views)
        exported = json.loads(body)
        assert ("result" in exported) == (views != "pi")
        if views != "pi":
            assert exported["result"] == report["result"]
        assert isinstance(exported["views"].get("pi", ""), str)
    report.pop("result")
    assert set(json.loads(render_download(report, "json")[0])) == {"report", "views"}


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_exports_preserve_distinct_coverage_measures(report, format):
    body, _, _ = render_download(report, format, "both")
    text = " ".join(_decode(body, format).split())
    assert "Supported-field completeness" in text
    assert "evidence_quality criterion" in text
    assert "not scientific confidence" in " ".join(text.split())
    for candidate in report["result"]["candidates"]:
        expected = f"Usable evidence covers {candidate['selected_weight_coverage']:.1%}"
        assert expected in text
    if format == "json":
        payload = json.loads(body)
        assert payload["result"] == report["result"]
        assert payload["views"]["audit"] == report["technical_audit"]


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_export_does_not_rewrite_coverage_in_saved_historical_reports(report, format):
    report["pi_summary"] = "Summary:\nSaved wording: Supported property coverage."
    report["technical_audit"] = "Technical View:\nSaved public evidence coverage."
    expected = (report["pi_summary"], report["technical_audit"])
    text = " ".join(_decode(render_download(report, format, "both")[0], format).split())
    assert "Saved wording: Supported property coverage." in text
    assert "Saved public evidence coverage." in text
    assert "Selected importance coverage:" not in text.split('"result"')[0]
    assert (report["pi_summary"], report["technical_audit"]) == expected


@pytest.mark.parametrize("bad_result", [{"value": float("nan")}, {"value": object()}])
def test_json_rejects_invalid_structured_result_without_echo(report, bad_result):
    report["result"] = bad_result
    with pytest.raises(ExportError, match="unsupported data"):
        render_download(report, "json", "audit")


def test_json_structured_result_obeys_export_size_limit(report):
    report["result"] = {"value": "x" * 2_000_001}
    with pytest.raises(ExportError, match="size limit"):
        render_download(report, "json", "both")


def test_restricted_table_parser_keeps_invalid_or_oversized_tables_literal():
    valid = "| Rank | Material |\n| --- | --- |\n| 1 | Literal <b>text</b> |"
    assert list(_blocks(valid)) == [
        ("table", [["Rank", "Material"], ["1", "Literal <b>text</b>"]], 0)
    ]
    cases = (
        valid.replace("| 1 | Literal <b>text</b> |", "| 1 | Extra | cell |"),
        valid.replace("---", "--", 1),
        valid.replace("Material", "x" * 121),
        valid.replace("Literal <b>text</b>", "x" * 4097),
        "| Rank | Material |\n| --- | --- |\n" + "| 1 | literal |\n" * 1001,
    )
    for content in cases:
        blocks = list(_blocks(content))
        assert not any(block[0] == "table" for block in blocks)
        assert "\n".join(block[1] for block in blocks) == content.rstrip()


def test_tables_escape_markup_and_only_link_verified_public_sources(report):
    reference = "https://www.nature.com/articles/sdata2016134"
    injected = "https://www.nature.com/fake-user-supplied-citation"
    literal = '<img src="http://127.0.0.1/private"/> <script>literal</script>'
    report["pi_summary"] = (
        "Shortlist:\n\n| Material | Source |\n| --- | --- |\n"
        f"| {literal} | {reference} |\n| Literal | {injected} |"
    )
    for format in ("pdf", "docx"):
        body, _, _ = render_download(report, format, "pi")
        text = _decode(body, format)
        assert "<script>literal</script>" in text
        assert "---" not in text
        if format == "pdf":
            reader = PdfReader(io.BytesIO(body))
            targets = [
                annotation.get_object().get("/A", {}).get("/URI")
                for page in reader.pages
                for annotation in page.get("/Annots", [])
            ]
        else:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                xml = ElementTree.fromstring(archive.read("word/document.xml"))
                tables = list(xml.iter(W + "tbl"))
                assert len(tables) == 2  # metadata and actual shortlist
                assert tables[1].find(f"{W}tr/{W}trPr/{W}tblHeader") is not None
                targets = [
                    relation.attrib["Target"]
                    for relation in ElementTree.fromstring(
                        archive.read("word/_rels/document.xml.rels")
                    )
                    if relation.attrib.get("TargetMode") == "External"
                ]
                assert not any(
                    name.startswith("word/media/") for name in archive.namelist()
                )
        assert reference in targets
        assert injected not in targets
        assert all(
            not url or ("127.0.0.1" not in url and not url.startswith("file:"))
            for url in targets
        )


def test_pdf_large_table_wraps_and_repeats_headers_without_losing_rows(report):
    # Repetition tests layout only; it does not introduce scientific candidates.
    candidate = report["result"]["candidates"][0]
    row = (
        f"| 1 | {candidate['formula']} ({candidate['material_id']}) | "
        "0 | Layout fixture: this explanatory cell must wrap without clipping. |"
    )
    report["technical_audit"] = (
        "Expanded shortlist:\n\n"
        "| Rank | Material (record) | Score | Selected evidence |\n"
        "| --- | --- | --- | --- |\n" + "\n".join([row] * 45)
    )
    body, _, _ = render_download(report, "pdf", "audit")
    pages = PdfReader(io.BytesIO(body)).pages
    assert len(pages) >= 3
    assert all("Selected evidence" in page.extract_text() for page in pages)
    assert _pdf_text(body).count(candidate["material_id"]) == 45
    assert _pdf_text(body).count("without clipping.") == 45


def test_pdf_oversized_table_row_splits_across_pages(report):
    repeated = "Long layout-only text with retained words. " * 85
    report["technical_audit"] = (
        "| Rank | Material | Score | Coverage | Selected evidence | Missing |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"| 1 | Layout fixture | 0 | 0 | {repeated} | Unknown |"
    )
    body, _, _ = render_download(report, "pdf", "audit")
    pages = PdfReader(io.BytesIO(body)).pages
    assert len(pages) > 1
    # Repeated page headers may interrupt a phrase in extracted text. All
    # distinctive tokens must survive each split, including its final word.
    text = _pdf_text(body)
    assert text.count("Long") == text.count("layout-only") == text.count("words.") == 85


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_real_report_citations_values_and_caveats_survive(report, format):
    text = _decode(render_download(report, format, "both")[0], format)
    assert "HfO2" in text
    assert "4.02" in text
    assert (
        next(row for row in report["result"]["candidates"] if row["formula"] == "HfO2")[
            "dielectric_total"
        ]
        == 18.75
    )
    assert "[R1]" in text
    assert "Materials Project" in text
    assert "compound safety remains unassessed" in " ".join(text.split())
    assert "not scientific confidence" in " ".join(text.split())
    assert "Ranking method" in text


@pytest.mark.parametrize(
    "reference",
    [
        "https://www.nature.com/articles/sdata2016134",
        "https://materials.hybrid3.duke.edu/materials/systems/1/",
        "https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/example",
        "https://europepmc.org/articles/PMC1234567",
        "https://arxiv.org/abs/2401.00001",
    ],
)
def test_pdf_and_word_links_only_for_stored_public_citations(report, reference):
    report.setdefault("sources", []).append(
        {
            "url": reference,
            "access_scope": "public",
            "provenance_status": "verified",
            "kind": "discovery_reference",
            "is_material_evidence": False,
        }
    )
    injected = "https://www.nature.com/fake-user-supplied-citation"
    report["pi_summary"] = (
        f"Source: {reference}\nUser preference label: {injected}\n"
        '<img src="http://127.0.0.1/private"/>\n'
        '<link href="file:///etc/passwd">untrusted literal markup</link>'
    )
    body, _, _ = render_download(report, "pdf", "pi")
    reader = PdfReader(io.BytesIO(body))
    links = []
    for page in reader.pages:
        for annotation in page.get("/Annots", []):
            action = annotation.get_object().get("/A", {})
            if action.get("/URI"):
                links.append(action["/URI"])
    assert reference in links
    assert injected not in links
    assert not any(link.startswith("file:") or "127.0.0.1" in link for link in links)
    text = _pdf_text(body)
    assert "untrusted literal markup" in text
    assert '<img src="http://127.0.0.1/private"/>' in text

    body, _, _ = render_download(report, "docx", "pi")
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        relationships = ElementTree.fromstring(
            archive.read("word/_rels/document.xml.rels")
        )
        external = [
            r.attrib["Target"]
            for r in relationships
            if r.attrib.get("TargetMode") == "External"
        ]
        assert reference in external
        assert injected not in external
        assert not any(link.startswith("file:") for link in external)
        assert not any(name.startswith("word/media/") for name in archive.namelist())


@pytest.mark.parametrize(
    "identifier", ["../secret", "bad\r\nHeader:value", "/Users/private/a", "x" * 65]
)
def test_untrusted_filename_identity_rejected_without_echo(report, identifier):
    report["id"] = identifier
    with pytest.raises(ExportError) as error:
        render_download(report, "text", "pi")
    assert identifier not in str(error.value)


def test_invalid_views_format_missing_text_and_size_rejected(report):
    for format, views in (("html", "pi"), ("text", "none")):
        with pytest.raises(ExportError):
            render_download(report, format, views)
    report["pi_summary"] = ""
    with pytest.raises(ExportError, match="unavailable"):
        render_download(report, "pdf", "pi")
    report["pi_summary"] = "x" * 2_000_001
    with pytest.raises(ExportError, match="size limit"):
        render_download(report, "text", "pi")


def test_download_route_cannot_cross_chat_scope_or_rerun_research(
    tmp_path, monkeypatch
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chats = [store.create_global_chat(title) for title in ("Own", "Other")]
    scope, _ = store.research_inputs(chats[0]["id"])
    outcome = run_research("Find oxide dielectric candidates", load_config())
    detail = store.append_research(chats[0]["id"], scope, "Find oxides", outcome)
    report_id = detail["reports"][0]["id"]

    def forbidden(*args, **kwargs):
        pytest.fail("Export attempted research or network access")

    monkeypatch.setattr("labcat.science.run_research", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    app = FastAPI()
    app.include_router(create_exports_router(store))
    route = f"/api/chats/{chats[0]['id']}/reports/{report_id}/export"
    with TestClient(app) as c:
        for format in ("text", "json", "pdf", "docx"):
            result = c.get(route, params={"format": format, "views": "pi"})
            assert result.status_code == 200, (
                result.text[:200] if format == "text" else result.status_code
            )
            assert result.headers["content-disposition"].startswith(
                'attachment; filename="labcat-'
            )
        assert c.get(route.replace(chats[0]["id"], chats[1]["id"])).status_code == 404
        assert c.get(route.replace(report_id, "missing")).status_code == 404
        assert c.get(route, params={"format": "html"}).status_code == 422
        assert c.get(route, params={"views": "none"}).status_code == 422
    assert len(store.get_global_chat(chats[0]["id"])["reports"]) == 1


def test_json_setting_keeps_written_summary_in_pdf_and_word(
    historical_property_fixture,
):
    config = load_config()
    config = replace(config, presentation=replace(config.presentation, format="json"))
    outcome = run_research("Find oxide dielectric candidates", config)
    report = {"id": "cli", "title": "Oxide screening", "stage": "partial", **outcome}
    for format in ("pdf", "docx"):
        text = _decode(render_download(report, format, "pi")[0], format)
        assert outcome["result"]["candidates"][0]["formula"] in text
        assert "Shortlist" in text
        assert "unassessed" in text
        assert "Research limitations" in text


def test_common_scientific_unicode_is_preserved_with_embedded_pdf_fonts(report):
    report["pi_summary"] = "Scientific notation: β Δ ε Ω Al₂O₃ µm ² → ± ≤ ≥"
    body, _, _ = render_download(report, "pdf", "pi")
    text = _pdf_text(body)
    for character in "βΔεΩ₂₃µ²→±≤≥":
        assert character in text
    reader = PdfReader(io.BytesIO(body))
    fonts = reader.pages[0]["/Resources"]["/Font"]
    assert any("DejaVuSans" in str(font.get_object()) for font in fonts.values())


def test_pdf_headings_stay_with_content_and_table_starts_on_overview_page(report):
    body, _, _ = render_download(report, "pdf", "both")
    detail_count = 0
    for page in PdfReader(io.BytesIO(body)).pages:
        lines = page.extract_text().splitlines()
        for index, line in enumerate(lines):
            if line.endswith("]:") and "[R" in line:
                detail_count += 1
                assert "Supported score" in lines[index + 1]
            if line in {"Research limitations:", "Public references:"}:
                assert index < len(lines) - 1
        if "Technical View" in lines:
            assert "Expanded shortlist:" in lines
            assert "Rank" in lines and "Supported score" in " ".join(lines)
    assert detail_count == len(report["result"]["candidates"])


def test_word_title_has_no_border_and_open_audit_data_stays_with_content(report):
    # Legacy saved JSON remains readable, though new reports always store prose.
    report["technical_audit"] = json.dumps(report["result"], indent=2)
    body, _, _ = render_download(report, "docx", "both")
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        styles = ElementTree.fromstring(archive.read("word/styles.xml"))
        for style in styles.findall(W + "style"):
            if style.get(W + "styleId") in {"Title", "Subtitle"}:
                assert style.find(f"{W}pPr/{W}pBdr") is None
        root = ElementTree.fromstring(archive.read("word/document.xml"))
        openings = [
            paragraph
            for paragraph in root.iter(W + "p")
            if "".join(node.text or "" for node in paragraph.iter(W + "t"))
            .strip()
            .endswith(("{", "["))
        ]
        assert openings
        assert all(
            paragraph.find(f"{W}pPr/{W}keepNext") is not None for paragraph in openings
        )


@pytest.mark.parametrize("long_passage", [False, True])
def test_word_keeps_only_bounded_passage_provenance_together(report, long_passage):
    excerpt = "Test-only passage for layout review. " * (100 if long_passage else 1)
    lines = [
        "Unrelated preceding paragraph.",
        "- Source: TEST fixture article https://europepmc.org/articles/PMC123456",
        f"- Attributed excerpt (body/sec[1]/p[1]): {excerpt}",
        "- Method context: Unresolved in this layout fixture.",
        "- Caveat: Test-only content has no scientific applicability.",
        "- Retrieved-content SHA-256: " + "a" * 64,
        "Unrelated following paragraph.",
    ]
    report["technical_audit"] = "\n".join(lines)
    body, _, _ = render_download(report, "docx", "audit")
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
        saved = {
            "".join(node.text or "" for node in paragraph.iter(W + "t")): paragraph
            for paragraph in root.iter(W + "p")
        }
    for line in lines:
        keep = saved[line.rstrip()].find(f"{W}pPr/{W}keepNext")
        assert (keep is not None) == (not long_passage and line in lines[1:5])


def test_text_and_json_exports_import_without_web_or_document_extras():
    script = """
import builtins
original_import = builtins.__import__
def isolated_import(name, *args, **kwargs):
    if name.split('.')[0] in {'fastapi', 'starlette', 'docx', 'reportlab'}:
        raise ImportError('Optional package deliberately unavailable')
    return original_import(name, *args, **kwargs)
builtins.__import__ = isolated_import
from labcat.report_exports import render_download
report = {'id':'cli', 'pi_summary':'Saved PI', 'technical_audit':'Saved audit'}
for format in ('text', 'json'):
    body, media, filename = render_download(report, format)
    assert b'Saved PI' in body
"""
    outcome = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert outcome.returncode == 0, outcome.stderr


def test_presentation_reformats_saved_records_without_mutating_or_reranking(
    report, monkeypatch
):
    from copy import deepcopy

    from labcat.config import validate_layout
    from labcat.report_exports import prepare_presentation

    original = deepcopy(report)
    saved = load_config().to_dict()["presentation"]
    report["result"]["execution"] = {"presentation": saved}
    original = deepcopy(report)
    current = replace(
        load_config(),
        presentation=replace(
            load_config().presentation,
            verbosity="detailed",
            terminology="specialist",
            layout=validate_layout(
                {"accent": "teal", "font_family": "serif", "font_size": 12}
            ),
        ),
    )
    monkeypatch.setattr(
        "labcat.science.ranking.rank_records",
        lambda *a, **k: pytest.fail("reranked"),
    )
    old = prepare_presentation(report, "saved", current)
    new = prepare_presentation(report, "current", current)
    assert report == original
    assert old["presentation"] == saved
    assert new["presentation"] == current.to_dict()["presentation"]
    assert old["settings_source"] == "saved-report"
    assert new["settings_source"] == "current-settings"
    assert old["technical_audit"] != new["technical_audit"]
    assert old["result"]["candidates"] == new["result"]["candidates"]
    assert old["result"]["ranking"] == original["result"]["ranking"]
    assert "https://" not in old["technical_audit"]
    assert "raw_fields_sha256" not in old["technical_audit"]
    for candidate in original["result"]["candidates"]:
        assert candidate["material_id"] not in old["technical_audit"]
        assert candidate["formula"] in old["technical_audit"]
        assert all(note in old["technical_audit"] for note in candidate["caveats"])
    payload = json.loads(render_download(new, "json")[0])
    assert payload["result"] == original["result"]
    assert payload["archive"] == {
        key: original[key] for key in ("pi_summary", "technical_audit")
    }
    assert payload["presentation"]["settings"] == new["presentation"]
    assert payload["views"]["audit"] == new["technical_audit"]


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_presented_download_keeps_short_citations_and_full_archive(report, format):
    from labcat.report_exports import prepare_presentation

    prepared = prepare_presentation(report)
    body = render_download(prepared, format)[0]
    text = _decode(body, format)
    assert "[R1]" in text
    assert "Supported score" in text
    if format != "json":
        assert report["id"] not in text
        assert "raw_fields_sha256" not in text
    if format in {"pdf", "docx"}:
        assert "https://" not in text
        url = prepared["references"][0]["url"]
        if format == "pdf":
            annotations = [
                annotation.get_object()
                for page in PdfReader(io.BytesIO(body)).pages
                for annotation in page.get("/Annots", [])
            ]
            assert any(item.get("/A", {}).get("/URI") == url for item in annotations)
        else:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                assert url in archive.read("word/_rels/document.xml.rels").decode()
    if format == "text":
        assert "Source links" in text
        assert prepared["references"][0]["url"] in text


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_formula_order_is_presentational_and_original_report_stays_archived(
    report, monkeypatch, format
):
    from copy import deepcopy

    from labcat.report_exports import prepare_presentation

    # Equivalent ordering of the reviewed silica fixture exercises a legacy
    # repository label. The source measurements and provenance remain untouched.
    candidate = deepcopy(
        next(row for row in report["result"]["candidates"] if row["formula"] == "SiO2")
    )
    candidate["formula"] = "O2Si"
    report["result"]["candidates"] = [candidate]
    report["pi_summary"] = "Archived O2Si summary."
    report["technical_audit"] = "Archived O2Si technical text."
    original = deepcopy(report)
    monkeypatch.setattr(
        "labcat.science.ranking.rank_records",
        lambda *args, **kwargs: pytest.fail("Presentation must never rerank."),
    )

    presented = prepare_presentation(report)
    for key in ("pi_summary", "technical_audit"):
        assert "SiO2" in presented[key]
        assert "O2Si" not in presented[key]
        assert presented["archive"][key] == original[key]
    for view in ("summary", "technical"):
        row = presented["result"]["report_tables"][view]["rows"][0]
        assert row["formula"] == "SiO2"
        assert row["source_formula"] == "O2Si"
        assert row["material"].startswith("SiO2 [R")
        assert row["material_id"] == candidate["material_id"]
        assert row["score"] == candidate["score"]
    assert presented["references"][0]["title"] == "SiO2 — public material record"
    assert presented["result"]["candidates"][0]["formula"] == "O2Si"
    assert presented["result"]["candidates"][0]["provenance"] == candidate["provenance"]
    assert report == original

    body = render_download(presented, format)[0]
    text = _decode(body, format)
    if format == "json":
        payload = json.loads(body)
        assert payload["result"] == original["result"]
        assert payload["archive"]["pi_summary"] == original["pi_summary"]
        assert "SiO2" in payload["views"]["pi"]
        assert "O2Si" not in payload["views"]["audit"]
    else:
        assert "SiO2" in text
        assert "O2Si" not in text


def test_formula_subscripts_only_apply_to_recognized_material_tokens():
    from labcat.report_exports import (
        _formula_context,
        _formula_pattern,
        _formula_runs,
    )

    pattern = _formula_pattern(
        {"result": {"candidates": [{"formula": "O2Si"}, {"formula": "Al2O3"}]}}
    )
    text = (
        "SiO2, Al2O3 and SiO2. Score 0.7143, 3.2 eV, m3. "
        "HfO2 (unlisted), nomad:SiO2, prefix_SiO2, SiO2.id, "
        "https://example.invalid/?formula=SiO2, doi:10.123/SiO2. "
        "<script>2</script> SiO2+ 3H2O"
    )
    runs = list(_formula_runs(text, pattern))
    assert "".join(value for value, _ in runs) == text
    assert [value for value, subscript in runs if subscript] == ["2", "2", "3", "2"]
    publication = "- [S1] SiO2 research paper · Public source"
    assert list(_formula_runs(publication, _formula_context(publication, pattern))) == [
        (publication, False)
    ]
    assert list(_formula_runs("SiO2", _formula_pattern({}))) == [("SiO2", False)]


@pytest.mark.parametrize("format", ["pdf", "docx"])
def test_document_formula_counts_have_native_subscript_formatting(report, format):
    from labcat.report_exports import prepare_presentation

    presented = prepare_presentation(report)
    body = render_download(presented, format)[0]
    if format == "docx":
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        subscript_runs = [
            run
            for run in root.iter(W + "r")
            if run.find(W + "rPr/" + W + "vertAlign") is not None
            and run.find(W + "rPr/" + W + "vertAlign").get(W + "val") == "subscript"
        ]
        assert subscript_runs
        assert all(
            "".join(node.text or "" for node in run.iter(W + "t")).isdigit()
            for run in subscript_runs
        )
    else:
        operations = [
            (operands, operator)
            for page in PdfReader(io.BytesIO(body)).pages
            for operands, operator in page.get_contents().operations
        ]
        assert any(
            operator == b"Ts" and operands[0] < 0 for operands, operator in operations
        ), "The PDF must lower formula counts using native text-rise operations."


def test_old_score_diagnostics_use_saved_profile_without_reranking():
    from copy import deepcopy

    from labcat.science.reporting import _score_analysis

    candidate = {
        "score": 0.25,
        "selected_weight_coverage": 0.5,
        "criterion_available": {"band_gap": True, "dielectric_total": False},
    }
    result = {
        "execution": {"ranking_profile": {"application": "high_k_screening"}},
        "ranking": {"weights": {"dielectric_total": 0.5, "band_gap": 0.5}},
    }
    original = deepcopy((candidate, result))
    assert _score_analysis(candidate, result) == {
        "observed_fit": 0.5,
        "coverage": 0.5,
        "possible_upper_score": 0.75,
        "required_criteria": ["dielectric_total", "band_gap"],
        "missing_required_criteria": ["dielectric_total"],
        "status": "needs_evidence",
    }
    assert (candidate, result) == original
    assert _score_analysis(candidate, {})["required_criteria"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"coverage": True},
        {"coverage": 0.7},
        {"observed_fit": 0.9},
        {"possible_upper_score": 0.9},
        {"missing_required_criteria": ["band_gap"]},
        {"status": "excellent"},
        {"required_criteria": ["<script>"]},
        {"unexpected": "No extra report claims"},
    ],
)
def test_saved_score_analysis_cannot_override_evidence_or_add_claims(change):
    from labcat.science.reporting import _score_analysis

    candidate = {
        "score": 0.25,
        "selected_weight_coverage": 0.5,
        "criterion_available": {"band_gap": True},
        "score_analysis": {
            "observed_fit": 0.5,
            "coverage": 0.5,
            "possible_upper_score": 0.75,
            "required_criteria": ["band_gap"],
            "missing_required_criteria": [],
            "status": "comparable",
            **change,
        },
    }
    with pytest.raises(ValueError):
        _score_analysis(candidate, {})


def test_tiny_coverage_tolerates_saved_score_rounding():
    from labcat.science.reporting import _score_analysis

    candidate = {
        "score": 0.0,  # A tiny positive contribution rounded to eight places.
        "selected_weight_coverage": 1e-10,
        "criterion_available": {},
        "score_analysis": {
            "observed_fit": 0.5,
            "coverage": 1e-10,
            "possible_upper_score": 1 - 5e-11,
            "required_criteria": [],
            "missing_required_criteria": [],
            "status": "comparable",
        },
    }
    assert _score_analysis(candidate, {}) == candidate["score_analysis"]


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_supported_score_exports_explain_partial_evidence_without_low_quality_claim(
    report, format
):
    from labcat.report_exports import _score_fills, prepare_presentation
    from labcat.science.reporting import _structured_table

    original = json.loads(json.dumps(report))
    presented = prepare_presentation(report)
    for table_name, view in (("summary", "pi"), ("technical", "audit")):
        table = presented["result"]["report_tables"][table_name]
        rows = [
            [cell.strip() for cell in line.split("|")[1:-1]]
            for line in _structured_table(table)
            if "---" not in line
        ]
        assert _score_fills(rows, presented, view) == {
            index: "#E8ECEE" for index in range(1, len(rows))
        }
        for row in table["rows"]:
            assert 0 < row["score_analysis"]["coverage"] < 1
            assert "coverage" in row["caveat"]
    body = render_download(presented, format)[0]
    text = " ".join(_decode(body, format).split())
    assert "Supported score" in text
    assert "Fit on known criteria" in text
    assert "Missing evidence is not evidence of poor material performance" in text
    assert "not a prediction or confidence interval" in text
    assert report == original
    if format == "json":
        assert json.loads(body)["result"] == original["result"]


def test_presentation_endpoint_scopes_sources_and_returns_frozen_preferences(report):
    from copy import deepcopy

    report = deepcopy(report)
    report["source_ids"] = [str(index) for index, _ in enumerate(report["sources"])]
    sources = [
        {**source, "id": str(index)} for index, source in enumerate(report["sources"])
    ]
    # Match persisted workspace records: identity/provenance only lives in the
    # immutable result, while public source rows retain URL and verification.
    for source in sources:
        source.pop("source_id", None)
        source.pop("record_id", None)
        source.pop("provenance", None)

    class Store:
        def get_global_chat(self, chat_id):
            return {"reports": [report] if chat_id == "own" else [], "sources": sources}

    app = FastAPI()
    app.include_router(create_exports_router(Store(), load_config))
    with TestClient(app) as client:
        path = "/api/chats/own/reports/report_123/presentation"
        response = client.get(path)
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["version"] == "report-presentation-v2"
        assert value["legacy"] is False
        assert (
            value["report_tables"]["technical"]["rows"][0]["material_id"]
            == report["result"]["candidates"][0]["material_id"]
        )
        assert value["references"][0]["id"] == "R1"
        assert "layout" in value["presentation"]
        assert "result" not in value and "archive" not in value
        assert client.get(path.replace("/own/", "/other/")).status_code == 404
        assert client.get(path + "?format_source=arbitrary").status_code == 422
        sources.clear()
        assert client.get(path).status_code == 422


def test_legacy_presentation_keeps_original_prose_and_layout(report):
    from labcat.report_exports import prepare_presentation

    report = {
        **report,
        "result": {"old_schema": True},
        "pi_summary": "Archived prose.",
        "technical_audit": "Archived technical prose.",
    }
    value = prepare_presentation(report)
    assert value["legacy"] is True
    assert value["pi_summary"] == report["pi_summary"]
    payload = json.loads(render_download(value, "json")[0])
    assert payload["result"] == report["result"]
    assert payload["archive"]["technical_audit"] == report["technical_audit"]


@pytest.mark.parametrize(
    "url,allowed",
    [
        ("https://openalex.org/W1234", True),
        ("https://en.wikipedia.org/wiki/Hafnium_dioxide", True),
        ("https://en.wikipedia.org/wiki/File%3Aexample", False),
        ("https://en.wikipedia.org/wiki/Materials%2Ftest", False),
        ("https://openalex.org/W1234?redirect=bad", False),
        ("https://openalex.org/users/1234", False),
        ("https://en.wikipedia.org/wiki/Hafnium_dioxide#fragment", False),
        ("https://europepmc.org@private.example/article", False),
    ],
)
def test_background_citation_paths_are_narrow(url, allowed):
    from labcat.science.reporting import approved_citation_url

    assert approved_citation_url(url) is allowed


def test_reference_identity_survives_shared_dataset_url_and_inert_publisher_markup(
    report,
):
    from labcat.science.reporting import citation_references

    sources = report["sources"] + [
        {
            "source_id": "europe_pmc",
            "record_id": "PMC1234567",
            "title": (
                "HfO&lt;sub&gt;2&lt;/sub&gt; and &lt;i&gt;x&lt;/i&gt; "
                "&amp; data <img src='x'>"
            ),
            "source_name": "Europe PMC",
            "url": "https://europepmc.org/articles/PMC1234567",
            "access_scope": "public",
            "provenance_status": "verified",
            "kind": "discovery_reference",
            "is_material_evidence": False,
        }
    ]
    references = citation_references(report["result"], sources)
    for candidate in report["result"]["candidates"]:
        reference = next(
            item for item in references if item["id"] == f"R{candidate['rank']}"
        )
        assert reference["title"] == candidate["formula"] + " — public material record"
        assert reference["url"] == candidate["provenance"]["source_url"]
    assert references[-1]["title"] == "HfO2 and x & data <img src='x'>"
    assert len({item["id"] for item in references}) == len(references)


def test_word_keeps_normal_table_rows_together_but_allows_long_rows(report):
    report["technical_audit"] = (
        "| A | B |\n| --- | --- |\n| short | row |\n| long | " + "word " * 100 + " |\n"
    )
    body = render_download(report, "docx", "audit")[0]
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    table = document.findall(".//" + W + "tbl")[-1]
    rows = table.findall(W + "tr")
    assert rows[1].find(W + "trPr/" + W + "cantSplit") is not None
    assert rows[2].find(W + "trPr/" + W + "cantSplit") is None


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_saved_band_gap_screening_is_explained_without_reapplying_policy(
    report, format
):
    from copy import deepcopy

    from labcat.report_exports import prepare_presentation

    report["result"]["ranking"]["screening_preferences"] = {
        "minimum_band_gap_ev": 2.0,
        "minimum_band_gap_active": True,
        "unknown_band_gap": "Untrusted stored prose must not be reflected.",
    }
    original = deepcopy(report)
    presented = prepare_presentation(report)
    for view in ("pi_summary", "technical_audit"):
        assert "minimum band gap 2 eV, inclusive" in presented[view]
        assert "Unknown band gaps remain for evidence review" in presented[view]
        assert "not a scientific measurement" in presented[view]
        assert "Untrusted stored prose" not in presented[view]
    text = " ".join(_decode(render_download(presented, format)[0], format).split())
    assert "minimum band gap 2 eV, inclusive" in text
    assert report == original
    assert presented["original_result"] == original["result"]
    assert presented["result"]["candidates"] == original["result"]["candidates"]


@pytest.mark.parametrize("minimum", [True, "2", -1, 101, float("nan"), float("inf")])
def test_invalid_saved_screening_is_not_a_new_claim(report, minimum):
    from labcat.science.reporting import _screening_note

    report["result"]["ranking"]["screening_preferences"] = {
        "minimum_band_gap_ev": minimum,
        "minimum_band_gap_active": True,
    }
    assert _screening_note(report["result"]) is None


def test_old_or_inactive_screening_does_not_inherit_todays_default(report):
    from labcat.science.reporting import _screening_note

    report["result"]["ranking"].pop("screening_preferences", None)
    assert _screening_note(report["result"]) is None
    report["result"]["ranking"]["screening_preferences"] = {
        "minimum_band_gap_ev": 2.0,
        "minimum_band_gap_active": False,
    }
    assert _screening_note(report["result"]) is None


@pytest.mark.parametrize(
    "key,label",
    [
        ("public_dielectric", "Public dielectric dataset (historical calculations)"),
        ("multiple_public_repositories", "Multiple public repositories"),
    ],
)
def test_repository_labels_are_readable_in_prepared_report(report, key, label):
    from labcat.report_exports import prepare_presentation

    report["result"]["retrieval"]["selected_repository"] = key
    assert (
        "Quantitative source: " + label
        in prepare_presentation(report)["technical_audit"]
    )


@pytest.fixture
def source_report():
    """Layout-only stored source metadata; no scientific result is
    fabricated."""
    return {
        "id": "source_export",
        "chat_id": "own_chat",
        "title": "Export selection fixture",
        "stage": "recorded",
        "created_at": "2026-09-22T12:00:00Z",
        "pi_summary": "SUMMARY_SELECTION_MARKER [S1] Essential summary caveat.",
        "technical_audit": "TECHNICAL_SELECTION_MARKER Essential technical caveat.",
        "source_ids": ["own_source"],
        "sources": [
            {
                "id": "own_source",
                "report_ids": ["source_export"],
                "chat_ids": ["own_chat"],
                "title": "SOURCE_SELECTION_MARKER HfO&lt;sub&gt;2&lt;/sub&gt;",
                "source_name": "Europe PMC",
                "url": "https://europepmc.org/articles/PMC1234567",
                "kind": "discovery_reference",
                "is_material_evidence": False,
                "access_scope": "public",
                "provenance_status": "verified",
                "created_at": "2026-09-22T12:00:00Z",
                "metadata": {"private_path": "/private/secret", "api_key": "secret"},
                "api_key": "never-export-this-key",
            }
        ],
    }


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
@pytest.mark.parametrize(
    "views,selected",
    [
        ("pi", {"pi"}),
        ("audit", {"audit"}),
        ("both", {"pi", "audit"}),
        ("sources", {"sources"}),
        ("pi,sources", {"pi", "sources"}),
        ("audit,sources", {"audit", "sources"}),
        ("all", {"pi", "audit", "sources"}),
    ],
)
def test_sources_selection_all_formats(source_report, format, views, selected):
    from copy import deepcopy

    original = deepcopy(source_report)
    body = render_download(source_report, format, views)[0]
    text = " ".join(_decode(body, format).split())
    for view, marker in (
        ("pi", "SUMMARY_SELECTION_MARKER"),
        ("audit", "TECHNICAL_SELECTION_MARKER"),
        ("sources", "SOURCE_SELECTION_MARKER"),
    ):
        assert (marker in text) == (view in selected)
    assert "never-export-this-key" not in text
    assert "/private/secret" not in text
    if "sources" in selected:
        assert "Europe PMC" in text and "HfO2" in text
        assert "verified" in text and "public" in text
        if format == "json":
            exported = json.loads(body)
            assert set(exported["views"]) == selected
            source = exported["views"]["sources"][0]
            assert source["id"] == "own_source"
            assert "metadata" not in source and "report_ids" not in source
    if "pi" in selected:
        assert "[S1] Essential summary caveat." in text
    assert source_report == original


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_source_only_endpoint_without_prose_excludes_other_reports(
    source_report, format
):
    source_report.pop("pi_summary")
    source_report.pop("technical_audit")
    foreign = {
        **source_report["sources"][0],
        "id": "foreign_source",
        "report_ids": ["another_report"],
        "title": "UNRELATED_REPORT_SOURCE",
    }

    class Store:
        def get_global_chat(self, chat_id):
            return {
                "reports": [source_report],
                "sources": [*source_report["sources"], foreign],
            }

    app = FastAPI()
    app.include_router(create_exports_router(Store(), load_config))
    with TestClient(app) as client:
        response = client.get(
            "/api/chats/own_chat/reports/source_export/export",
            params={"format": format, "views": "sources"},
        )
    assert response.status_code == 200, response.text[:300]
    text = _decode(response.content, format)
    assert "SOURCE_SELECTION_MARKER" in text
    assert "UNRELATED_REPORT_SOURCE" not in text
    if format == "json":
        value = response.json()
        assert value["archive"] == {}
        assert set(value["views"]) == {"sources"}
        assert "result" not in value


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_source_only_empty_list_is_explicit(source_report, format):
    source_report.update(source_ids=[], sources=[])
    body = render_download(source_report, format, "sources")[0]
    if format == "json":
        assert json.loads(body)["views"]["sources"] == []
    else:
        assert "No sources are saved with this report." in _decode(body, format)


@pytest.mark.parametrize("field,value", [("report_ids", []), ("chat_ids", [])])
def test_source_download_rejects_unrelated_membership(source_report, field, value):
    source_report["sources"][0][field] = value
    with pytest.raises(ExportError, match="source membership cannot be verified"):
        render_download(source_report, "json", "sources")


@pytest.mark.parametrize("format", ["pdf", "docx"])
def test_source_download_links_clean_titles_only_for_verified_public_sources(
    source_report, format
):
    original = source_report["sources"][0]
    source_report["sources"] = [
        original,
        {
            **original,
            "id": "unverified",
            "title": "Unverified title with " + original["url"],
            "provenance_status": "unverified",
        },
        {**original, "id": "private", "access_scope": "private"},
        {**original, "id": "arbitrary", "url": "https://example.invalid/secret"},
        {
            **original,
            "id": "markup",
            "title": '<link href="file:///secret">Literal title</link>',
            "url": "file:///secret",
        },
    ]
    source_report["source_ids"] = [source["id"] for source in source_report["sources"]]
    body = render_download(source_report, format, "sources")[0]
    text = _decode(body, format)
    assert "Approved public link unavailable." in text
    assert "Literal title" in text
    if format == "pdf":
        destinations = [
            annotation.get_object().get("/A", {}).get("/URI")
            for page in PdfReader(io.BytesIO(body)).pages
            for annotation in page.get("/Annots", [])
        ]
    else:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            relationships = ElementTree.fromstring(
                archive.read("word/_rels/document.xml.rels")
            )
        destinations = [
            relationship.attrib["Target"]
            for relationship in relationships
            if relationship.attrib.get("TargetMode") == "External"
        ]
    assert destinations == [original["url"]]


def test_sources_same_url_remain_distinct_but_joined_workspace_row_is_once(
    source_report,
):
    original = source_report["sources"][0]
    source_report["sources"].extend(
        [{**original, "source_id": "joined-material"}, {**original, "id": "second"}]
    )
    source_report["source_ids"].append("second")
    sources = json.loads(render_download(source_report, "json", "sources")[0])["views"][
        "sources"
    ]
    assert [source["id"] for source in sources] == ["own_source", "second"]


@pytest.mark.parametrize("views", ["", "none", "sources,pi", "sources,sources"])
def test_download_rejects_empty_or_invalid_section_selection(source_report, views):
    with pytest.raises(ExportError, match="Choose at least one"):
        render_download(source_report, "json", views)


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
def test_sources_preserve_prepared_scientific_report_and_its_citations(report, format):
    from copy import deepcopy

    from labcat.report_exports import prepare_presentation

    original = deepcopy(report)
    prepared = prepare_presentation(report)
    body = render_download(prepared, format, "all")[0]
    text = " ".join(_decode(body, format).split())
    assert "Sources" in text or '"sources"' in text
    assert "[R1]" in text
    assert "Missing evidence is not evidence of poor material performance" in text
    if format == "json":
        payload = json.loads(body)
        assert set(payload["views"]) == {"pi", "audit", "sources"}
        assert len(payload["views"]["sources"]) == len(prepared["sources"])
        assert payload["result"] == original["result"]
        assert payload["archive"] == {
            key: original[key] for key in ("pi_summary", "technical_audit")
        }
        assert payload["references"] == prepared["references"]
    assert report == original


@pytest.mark.parametrize("views", ["sources", "pi,sources", "audit,sources", "all"])
def test_http_accepts_new_download_selections(source_report, views):
    class Store:
        def get_global_chat(self, chat_id):
            return {"reports": [source_report], "sources": source_report["sources"]}

    app = FastAPI()
    app.include_router(create_exports_router(Store(), load_config))
    with TestClient(app) as client:
        response = client.get(
            "/api/chats/own_chat/reports/source_export/export",
            params={"format": "json", "views": views},
        )
    assert response.status_code == 200, response.text[:300]
    expected = {"pi", "audit", "sources"} if views == "all" else set(views.split(","))
    assert set(response.json()["views"]) == expected
