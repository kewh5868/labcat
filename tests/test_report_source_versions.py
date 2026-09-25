"""Synthetic source-version storage/replay; no live material
evidence."""

import hashlib
import json
from copy import deepcopy

import pytest
from test_candidate_leads import reference

from labcat.config import load_config
from labcat.science.candidate_leads import (
    discovery_documents,
    validate_candidate_leads,
)
from labcat.science.literature_evaluation import evaluate_candidates
from labcat.science.report_sources import (
    discovery_version,
    report_scoped_sources,
)
from labcat.science.reporting import (
    render_reports,
    validated_literature_evaluation,
)
from labcat.workspace import WorkspaceStore


def outcome(version):
    """Same paper/abstract, with different exact retrieved body
    context."""
    source = {
        **reference(
            provider="europe_pmc", text="TESTONLY-Alpha is a synthetic test mention."
        ),
        "source_name": "Europe PMC",
    }
    profile = {"importance": {"band_gap": 1}}
    docs = discovery_documents([source])
    leads = validate_candidate_leads(
        [
            {
                "name": "TESTONLY-Alpha",
                "quote": docs[0]["text"],
                "document_id": docs[0]["document_id"],
            }
        ],
        docs,
        [source],
        profile["importance"],
    )
    proposals = []
    if version:
        digest = ("b" if version == 1 else "c") * 64
        text = (
            f"TEST ONLY body version {version}: TESTONLY-Alpha band gap is discussed. "
            "This is synthetic protocol context, not a measurement."
        )
        source["metadata"].update(
            full_text_read=True,
            full_text_scope="body paragraphs only",
            full_text_provenance={
                "full_text_request_url": (
                    "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML"
                ),
                "full_text_response_sha256": digest,
            },
            assessment_passages=[
                {
                    "text": text,
                    "locator": "body/sec[1]/p[1]",
                    "section": "Test results",
                    "article_id": "PMC1",
                    "response_sha256": digest,
                    "candidate_ids": [leads[0]["id"]],
                    "paragraph_complete": True,
                }
            ],
        )
        body = next(doc for doc in discovery_documents([source]) if doc["text"] == text)
        proposals.append(
            {
                "lead_id": leads[0]["id"],
                "criterion_id": "band_gap",
                "document_id": body["document_id"],
                "quote": text,
                "judgment": "mixed" if version == 1 else "supports",
                "interpretation": "TEST ONLY interpretation; no material measurement.",
            }
        )
    result = {
        "stage": "public_discovery",
        "candidates": [],
        "candidate_leads": leads,
        "summary": "Synthetic source version test.",
        "reason": "No material measurements.",
        "public_discovery": {
            "references": deepcopy([source]),
            "source_statuses": [],
            "caveats": [],
        },
        "execution": {"ranking_profile": profile},
        "ranking": {"raw_importance": profile["importance"]},
        "literature_evaluation": evaluate_candidates(
            {"evaluations": proposals}, leads, [source], profile
        )["evaluation"],
    }
    assert len(result["literature_evaluation"]["proposals"]) == len(proposals)
    summary, technical = render_reports(result, load_config(), [source])
    return {
        "stage": "partial",
        "answer": "TEST ONLY",
        "result": result,
        "sources": [source],
        "pi_summary": summary,
        "technical_audit": technical,
    }


def append(store, project, chat, version):
    return store.append_research(chat, project, "TEST ONLY", outcome(version))[
        "reports"
    ][-1]


def report_with_sources(store, chat, report_id):
    detail = store.get_global_chat(chat)
    report = next(report for report in detail["reports"] if report["id"] == report_id)
    return {
        **report,
        "sources": [
            source
            for source in detail["sources"]
            if source["id"] in report["source_ids"]
        ],
    }


def immutable_bytes(store):
    with store._connection() as conn:
        return [
            tuple(row)
            for row in conn.execute(
                "SELECT r.id,r.pi_summary,r.technical_audit,rr.outcome_json "
                "FROM reports r "
                "JOIN research_runs rr ON rr.report_id=r.id ORDER BY r.id"
            )
        ]


def assert_replays(report):
    before = deepcopy(report)
    assert (
        validated_literature_evaluation(report["result"], report["sources"])
        == report["result"]["literature_evaluation"]
    )
    assert report == before


@pytest.mark.parametrize("versions", [(0, 1), (1, 0), (1, 2), (2, 1)])
@pytest.mark.parametrize("same_chat", [False, True])
def test_distinct_response_versions_replay_independently(tmp_path, versions, same_chat):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY")["id"]
    chat1 = store.create_global_chat("TEST ONLY", project)["id"]
    first = append(store, project, chat1, versions[0])
    store.set_pin(project, "report", first["id"])
    tracking = store.set_report_tracking(project, chat1)
    chat2 = chat1 if same_chat else store.create_global_chat("TEST ONLY", project)["id"]
    second = append(store, project, chat2, versions[1])
    assert first["source_ids"] != second["source_ids"]
    before = immutable_bytes(store)
    for chat, report in ((chat1, first), (chat2, second)):
        saved = report_with_sources(store, chat, report["id"])
        assert saved["sources"][0]["evidence_version"] == discovery_version(
            saved["sources"][0]
        )
        assert_replays(saved)
    pins = store.contents(project)["reports"]
    assert (
        next(pin for pin in pins if pin["pin"]["mode"] == "snapshot")["id"]
        == first["id"]
    )
    assert (
        next(pin for pin in pins if pin["pin"]["id"] == tracking["id"])["id"]
        == (second if same_chat else first)["id"]
    )
    assert immutable_bytes(store) == before


def force_legacy_collision(store, project, first, second):
    """Recreate old URL-only storage, not merely two new versioned
    writes."""
    first_id, second_id = first["source_ids"][0], second["source_ids"][0]
    with store._connection(write=True) as conn:
        source = dict(
            conn.execute("SELECT * FROM sources WHERE id=?", (first_id,)).fetchone()
        )
        legacy_key = hashlib.sha256(
            json.dumps(
                {key: source[key] for key in ("url", "source_name", "title")},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        conn.execute(
            "UPDATE source_records SET record_key=? WHERE source_id=?",
            (legacy_key, first_id),
        )
        conn.execute("DELETE FROM report_sources WHERE report_id=?", (second["id"],))
        conn.execute(
            "INSERT INTO report_sources VALUES (?,?,?)",
            (project, second["id"], first_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO chat_sources VALUES (?,?,?)",
            (project, second["chat_id"], first_id),
        )
        conn.execute("DELETE FROM sources WHERE id=?", (second_id,))


@pytest.mark.parametrize("versions", [(0, 1), (1, 0), (1, 2)])
def test_legacy_collision_recovers_each_immutable_report_without_rewriting_rows(
    tmp_path, versions
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY")["id"]
    chat = store.create_global_chat("TEST ONLY", project)["id"]
    first, second = [append(store, project, chat, version) for version in versions]
    force_legacy_collision(store, project, first, second)
    before = immutable_bytes(store)
    with store._connection() as conn:
        annotations_before = list(
            map(tuple, conn.execute("SELECT * FROM source_annotations"))
        )
    for report in (first, second):
        saved = report_with_sources(store, chat, report["id"])
        assert "evidence_version" not in saved["sources"][0]
        assert_replays(saved)
        resolved = report_scoped_sources(saved["result"], saved["sources"])
        assert report_scoped_sources(saved["result"], resolved) == resolved
    assert immutable_bytes(store) == before
    with store._connection() as conn:
        assert annotations_before == list(
            map(tuple, conn.execute("SELECT * FROM source_annotations"))
        )
        assert list(conn.execute("PRAGMA foreign_key_check")) == []


def test_identical_annotations_deduplicate_but_moves_never_merge_different_versions(
    tmp_path,
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    first_project, second_project = [
        store.create_project(name)["id"] for name in ("A", "B")
    ]
    chat = store.create_global_chat("First", first_project)["id"]
    first, duplicate = [append(store, first_project, chat, 1) for _ in range(2)]
    assert first["source_ids"] == duplicate["source_ids"]
    store.set_pin(first_project, "source", first["source_ids"][0])
    other = store.create_global_chat("Second", second_project)["id"]
    second = append(store, second_project, other, 2)
    before = immutable_bytes(store)
    store.move_chat(chat, second_project)
    moved = report_with_sources(store, chat, first["id"])
    assert moved["source_ids"] != second["source_ids"]
    assert_replays(moved)
    assert_replays(report_with_sources(store, other, second["id"]))
    assert store.contents(first_project)["sources"][0]["id"] == first["source_ids"][0]
    for destination in (None, first_project):
        store.move_chat(chat, destination)
        assert_replays(report_with_sources(store, chat, first["id"]))
    assert immutable_bytes(store) == before
    with store._connection() as conn:
        assert list(conn.execute("PRAGMA foreign_key_check")) == []


@pytest.mark.parametrize(
    "mutation",
    [
        "snapshot_quote",
        "snapshot_hash",
        "source_quote",
        "score",
        "missing_member",
        "source_name",
        "adapter",
        "record",
        "url",
        "title",
        "private",
        "evidence",
        "duplicate",
    ],
)
def test_inconsistent_source_bound_tampering_fails_closed(tmp_path, mutation):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY")["id"]
    chat = store.create_global_chat("TEST ONLY", project)["id"]
    report = append(store, project, chat, 1)
    saved = report_with_sources(store, chat, report["id"])
    ref = saved["result"]["public_discovery"]["references"][0]
    if mutation == "snapshot_quote":
        ref["metadata"]["assessment_passages"][0]["text"] = "Invented statement"
    elif mutation == "snapshot_hash":
        ref["metadata"]["full_text_provenance"]["full_text_response_sha256"] = "f" * 64
    elif mutation == "source_quote":
        saved["sources"][0]["metadata"]["assessment_passages"][0][
            "text"
        ] = "Invented statement"
    elif mutation == "score":
        saved["result"]["literature_evaluation"]["ranked_candidates"][0]["rank"] = 99
    elif mutation == "missing_member":
        saved["sources"] = []
    elif mutation == "duplicate":
        saved["result"]["public_discovery"]["references"].append(deepcopy(ref))
    else:
        key, value = {
            "source_name": ("source_name", "Foreign adapter"),
            "adapter": ("source_id", "user"),
            "record": ("record_id", "PMC2"),
            "url": ("url", "https://europepmc.org/articles/PMC2"),
            "title": ("title", "Foreign title"),
            "private": ("access_scope", "private"),
            "evidence": ("is_material_evidence", True),
        }[mutation]
        ref[key] = value
    with pytest.raises((ValueError, TypeError)):
        validated_literature_evaluation(saved["result"], saved["sources"])


def test_legacy_overlay_cannot_replace_membership_and_pin_fields(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY")["id"]
    chat = store.create_global_chat("TEST ONLY", project)["id"]
    first, second = [append(store, project, chat, version) for version in (0, 1)]
    force_legacy_collision(store, project, first, second)
    saved = report_with_sources(store, chat, second["id"])
    ref = saved["result"]["public_discovery"]["references"][0]
    ref.update(
        id="fake",
        project_id="fake",
        chat_ids=["fake"],
        report_ids=["fake"],
        pinned=True,
        evidence_version="fake",
    )
    resolved = report_scoped_sources(saved["result"], saved["sources"])[0]
    for key in ("id", "project_id", "chat_ids", "report_ids", "pinned"):
        assert resolved[key] == saved["sources"][0][key]
    assert "evidence_version" not in resolved


@pytest.mark.parametrize("mutation", ["quote", "digest", "candidate_binding"])
def test_legacy_snapshot_recovery_keeps_canonical_passage_gates(tmp_path, mutation):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY")["id"]
    chat = store.create_global_chat("TEST ONLY", project)["id"]
    first, second = [append(store, project, chat, version) for version in (0, 1)]
    force_legacy_collision(store, project, first, second)
    saved = report_with_sources(store, chat, second["id"])
    ref = saved["result"]["public_discovery"]["references"][0]
    passage = ref["metadata"]["assessment_passages"][0]
    if mutation == "quote":
        passage["text"] = "Invented unsupported assessment"
    elif mutation == "digest":
        passage["response_sha256"] = "f" * 64
    else:
        passage["text"] = passage["text"].replace("TESTONLY-Alpha", "TESTONLY-Other")
    with pytest.raises(ValueError):
        validated_literature_evaluation(saved["result"], saved["sources"])


def test_purge_one_chat_does_not_remove_other_versions_or_pinned_source(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY")["id"]
    first_chat, second_chat = [
        store.create_global_chat(label, project)["id"] for label in ("First", "Second")
    ]
    first = append(store, project, first_chat, 1)
    second = append(store, project, second_chat, 2)
    store.set_pin(project, "source", first["source_ids"][0])
    store.archive_chat(first_chat)
    store.purge_chat(first_chat, confirm=True)
    assert_replays(report_with_sources(store, second_chat, second["id"]))
    assert store.contents(project)["sources"][0]["id"] == first["source_ids"][0]
    with store._connection() as conn:
        assert list(conn.execute("PRAGMA foreign_key_check")) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", []),
        ("id", None),
        ("report_ids", None),
        ("report_ids", {}),
        ("chat_ids", None),
        ("chat_ids", {}),
    ],
)
def test_malformed_export_membership_has_safe_validation_error(tmp_path, field, value):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY")["id"]
    chat = store.create_global_chat("TEST ONLY", project)["id"]
    report = append(store, project, chat, 1)
    saved = report_with_sources(store, chat, report["id"])
    saved["sources"][0][field] = value


@pytest.mark.parametrize("linked", [False, True])
def test_mixed_snapshot_never_imports_or_changes_quantitative_records(linked):
    report = outcome(1)
    numeric = {
        "source_id": "material:TESTONLY-record",
        "record_id": "TESTONLY-record",
        "title": "TEST ONLY quantitative protocol source",
        "url": "https://doi.org/10.0000/test-only",
        "source_name": "Synthetic adapter fixture",
        "access_scope": "public",
        "provenance_status": "verified",
        "provenance": {"response_sha256": "d" * 64},
    }
    report["result"]["public_discovery"]["references"].append(deepcopy(numeric))
    if linked:
        report["sources"].append(deepcopy(numeric))
    before = deepcopy(report)
    resolved = report_scoped_sources(report["result"], report["sources"])
    numeric_rows = [row for row in resolved if row.get("kind") != "discovery_reference"]
    assert numeric_rows == ([numeric] if linked else [])
    assert (
        validated_literature_evaluation(report["result"], resolved)
        == report["result"]["literature_evaluation"]
    )
    assert report == before
