"""Ranking tables retain selected evidence, missing penalties and
absolute colors."""

import io
import json
import zipfile
from copy import deepcopy
from xml.etree import ElementTree

import pytest
from pypdf import PdfReader

from labcat import science
from labcat.config import load_config
from labcat.report_exports import (
    _blocks,
    _export_blocks,
    _score_fills,
    render_download,
)
from labcat.science.ranking import (
    SCORE_SCALE,
    rank_records,
    score_band,
    score_color,
)


@pytest.fixture
def report(monkeypatch):
    records, provenance = science.load_snapshot()
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda filters: (records, provenance)
    )
    importance = {
        "band_gap": 0.5,
        "bulk_modulus": 0.25,
        "piezoelectric": 0.5,
        "dielectric_total": 0.5,
        "stability": 0.25,
        "simplicity": 0.25,
        "element_screen": 0.25,
        "density": 0,
    }
    outcome = science.run_research(
        "Find oxide dielectric materials for thin-film screening",
        load_config(),
        importance=importance,
    )
    return {
        "id": "fixture-report",
        "title": "Explicit historical fixture for export tests",
        **outcome,
    }


def test_all_positive_properties_have_ordered_columns_and_attributed_values(report):
    result = report["result"]
    contract = result["report_tables"]
    table = contract["technical"]
    assert contract["schema"] == "ranking-tables-v1"
    assert contract["score_scale"] == SCORE_SCALE
    assert [column["id"] for column in table["columns"]] == [
        "rank",
        "material",
        "score",
        *[key for key, value in result["ranking"]["weights"].items() if value > 0],
    ]
    plain = next(
        text for kind, text, _ in _blocks(report["technical_audit"]) if kind == "table"
    )
    assert plain[0] == [column["label"] for column in table["columns"]]
    for raw, row, cells in zip(
        result["candidates"], table["rows"], plain[1:], strict=True
    ):
        assert cells[:3] == [str(row["rank"]), row["material"], f"{row['score']:.4f}"]
        gap = row["properties"]["band_gap"]
        assert gap["value"] == raw["band_gap_ev"]
        assert gap["unit"] == "eV" and gap["citation_ids"]
        assert all(
            f"[{citation}]" in gap["display"] for citation in gap["citation_ids"]
        )
        assert row["properties"]["bulk_modulus"]["status"] == "unknown"
        assert row["properties"]["piezoelectric"]["status"] == "unavailable"
        assert row["properties"]["piezoelectric"]["value"] is None
        assert row["properties"]["piezoelectric"]["contribution"] == 0
        assert row["properties"]["piezoelectric"]["weight"] > 0
        assert row["score"] == pytest.approx(
            sum(p["contribution"] for p in row["properties"].values())
        )
    assert len(contract["summary"]["rows"]) == 3


def test_zero_selected_evidence_is_omitted_but_supported_zero_utility_is_scored():
    original, _ = science.load_snapshot()
    missing, known_zero = deepcopy(original[0]), deepcopy(original[1])
    missing["band_gap_ev"] = None
    known_zero["band_gap_ev"] = 0.0  # Explicit numerical edge-case fixture.
    ranked, audit = rank_records(
        [missing, known_zero], load_config(), importance={"band_gap": 1}
    )
    assert [row["material_id"] for row in ranked] == [known_zero["material_id"]]
    assert ranked[0]["score"] == 0 and ranked[0]["selected_weight_coverage"] == 1
    assert (
        "no overall utility is assigned" in audit["excluded_records"][0]["reasons"][0]
    )
    for field in (
        "band_gap_ev",
        "dielectric_total",
        "dielectric_electronic",
        "energy_above_hull_ev_atom",
        "density_g_cm3",
        "bulk_modulus_gpa",
        "shear_modulus_gpa",
    ):
        missing[field] = None
    assert (
        rank_records([missing], load_config(), importance={"evidence_quality": 1})[0]
        == []
    )
    assert rank_records([missing], load_config(), importance={"simplicity": 1})[0]


def test_absolute_utility_colors_never_rescale_to_the_best_observed_record():
    assert score_color(0) == "#F8D7DA"
    assert score_color(0.5) == "#FFF0C2"
    assert score_color(1) == "#D5EDDD"
    assert score_band(0.2) == score_band(0.1) == "low"
    assert score_color(0.2) != score_color(1)
    assert score_band(1 / 3) == "medium" and score_band(2 / 3) == "high"
    for invalid in (None, True, -0.1, 1.1, float("nan"), float("inf"), "0.5"):
        assert score_color(invalid) is None and score_band(invalid) == "unscored"


def test_fractional_weights_keep_complete_coverage_within_table_contract(monkeypatch):
    records, provenance = science.load_snapshot()
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda filters: (records, provenance)
    )
    outcome = science.run_research(
        "Find oxide dielectric materials for thin-film screening",
        load_config(),
        importance={"band_gap": 0.47, "simplicity": 0.66},
    )
    # These normalized weights sum to 1.0000000000000002 in binary floats.
    # Complete evidence must remain a valid fraction for the strict UI contract.
    assert outcome["result"]["candidates"]
    for candidate in outcome["result"]["candidates"]:
        assert candidate["selected_weight_coverage"] == 1.0
    for table in outcome["result"]["report_tables"].values():
        if isinstance(table, dict) and "rows" in table:
            assert table["rows"]
            assert all(row["selected_weight_coverage"] == 1.0 for row in table["rows"])


def test_scored_reports_require_public_verified_citations(report):
    report["sources"] = [
        {**source, "provenance_status": "unverified"} for source in report["sources"]
    ]
    with pytest.raises(ValueError, match="verified public citations"):
        science.render_research(report, load_config())


@pytest.mark.parametrize("field", ["record_id", "url", "raw_fields_sha256"])
def test_scored_citation_must_match_the_actual_phase_and_provenance(report, field):
    source = report["sources"][0]
    if field == "raw_fields_sha256":
        source["provenance"] = {**source["provenance"], field: "0" * 64}
    else:
        source[field] = "unrelated-public-record"
    with pytest.raises(ValueError, match="verified public citations"):
        science.render_research(report, load_config())


def test_importance_order_changes_column_order_without_changing_scores():
    records, _ = science.load_snapshot()
    importance = {"band_gap": 0.7, "simplicity": 0.1, "unsupported": 0.9}
    first, audit = rank_records(records, load_config(), importance=importance)
    second, _ = rank_records(
        records, load_config(), importance=dict(reversed(list(importance.items())))
    )
    assert [(row["material_id"], row["score"]) for row in first] == [
        (row["material_id"], row["score"]) for row in second
    ]
    assert audit["weights"]["unsupported"] == pytest.approx(0.9 / 1.7)


def test_wide_table_exports_repeat_identity_without_losing_selected_properties(report):
    full = next(
        text for kind, text, _ in _blocks(report["technical_audit"]) if kind == "table"
    )
    chunks = [
        text
        for kind, text, _ in _export_blocks(report["technical_audit"])
        if kind == "table"
    ]
    assert len(chunks) == 2
    assert [name for chunk in chunks for name in chunk[0][3:]] == full[0][3:]
    for chunk in chunks:
        assert len(chunk[0]) <= 7
        assert [row[:3] for row in chunk] == [row[:3] for row in full]
        assert _score_fills(chunk, report, "audit")
    corrupted = deepcopy(chunks[0])
    corrupted[1][2] = "1.0000"
    assert 1 not in _score_fills(corrupted, report, "audit")


def test_pdf_word_and_json_retain_dynamic_properties_and_semantic_scores(report):
    table = report["result"]["report_tables"]["technical"]
    docx = render_download(report, "docx", "both")[0]
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        xml = ElementTree.fromstring(archive.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    text = " ".join(node.text or "" for node in xml.findall(".//w:t", ns))
    fills = {item.attrib[f"{{{ns['w']}}}fill"] for item in xml.findall(".//w:shd", ns)}
    for row in table["rows"]:
        assert row["selected_weight_coverage"] < 1
        assert "E8ECEE" in fills
        # The saved absolute score-color metadata remains unchanged, while
        # partial evidence is presented neutrally rather than as poor performance.
        assert row["score_color"] == score_color(row["score"])
        assert f"{row['score']:.4f}" in text
    pdf = PdfReader(io.BytesIO(render_download(report, "pdf", "both")[0]))
    pdf_text = " ".join(page.extract_text() for page in pdf.pages)
    for column in table["columns"]:
        assert column["label"] in text
        assert " ".join(column["label"].split()) in " ".join(pdf_text.split())
    assert "Technical View" in text and "Technical View" in pdf_text
    assert "Summary" in text and "Summary" in pdf_text
    parsed = json.loads(render_download(report, "json", "audit")[0])
    assert parsed["result"]["report_tables"]["technical"] == table


def test_complete_evidence_tables_keep_absolute_score_colors(monkeypatch):
    records, provenance = science.load_snapshot()
    monkeypatch.setattr(
        science, "retrieve_nomad", lambda filters: (records, provenance)
    )
    outcome = science.run_research(
        "Compare band gaps of oxide materials",
        load_config(),
        importance={"band_gap": 1},
    )
    report = {"id": "complete-fixture", "title": "Historical fixture", **outcome}
    table = report["result"]["report_tables"]["technical"]
    text_table = next(
        text for kind, text, _ in _blocks(report["technical_audit"]) if kind == "table"
    )
    expected = {index: row["score_color"] for index, row in enumerate(table["rows"], 1)}
    assert expected and all(
        row["selected_weight_coverage"] == 1 for row in table["rows"]
    )
    assert _score_fills(text_table, report, "audit") == expected
    with zipfile.ZipFile(
        io.BytesIO(render_download(report, "docx", "audit")[0])
    ) as archive:
        xml = ElementTree.fromstring(archive.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    fills = {node.attrib[f"{{{ns['w']}}}fill"] for node in xml.findall(".//w:shd", ns)}
    assert {color.lstrip("#") for color in expected.values()} <= fills


def test_maximum_profile_keeps_all_100_positive_properties_in_text_and_export_blocks(
    report,
):
    importance = {"band_gap": 1, **{f"custom_property_{i}": 1 for i in range(99)}}
    candidates, ranking = rank_records(
        science.load_snapshot()[0], load_config(), importance=importance
    )
    by_id = {
        row["material_id"]: row["source_ids"] for row in report["result"]["candidates"]
    }
    # Reuse only source-linked records present in the explicit report fixture.
    candidates = [row for row in candidates if row["material_id"] in by_id]
    for row in candidates:
        row["source_ids"] = by_id[row["material_id"]]
    report["result"].update(candidates=candidates, ranking=ranking)
    value = science.render_research(report, load_config())
    columns = value["result"]["report_tables"]["technical"]["columns"]
    assert len(columns) == 103
    blocks = list(_export_blocks(value["technical_audit"]))
    assert sum(len(text[0]) - 3 for kind, text, _ in blocks if kind == "table") == 100
