"""Complete saved chat PDFs preserve historical content and scoped
citations."""

import io
import sqlite3
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader
from test_report_source_versions import force_legacy_collision, outcome

from labcat import chat_exports, workspace
from labcat.chat_exports import render_chat_history
from labcat.config import load_config
from labcat.report_exports import ExportError, create_exports_router
from labcat.workspace import WorkspaceStore


def text_of(body):
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(body)).pages)


def links_of(body):
    return [
        item.get_object().get("/A", {}).get("/URI")
        for page in PdfReader(io.BytesIO(body)).pages
        for item in page.get("/Annots", [])
    ]


def client_for(store, **kwargs):
    app = FastAPI()
    app.include_router(create_exports_router(store, **kwargs))
    return TestClient(app)


@pytest.fixture
def saved_chat(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Synthetic export history")
    detail = store.append_global_message(
        chat["id"], "TEST ONLY question", load_config()
    )
    return store, chat, detail


def test_complete_history_exceeds_model_context_limits_without_rerunning(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(workspace, "_now", lambda: "2026-09-27T12:34:56+00:00")
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("TEST ONLY <unsafe> / filename")
    for number in range(22):
        store.append_global_message(chat["id"], f"QUERY-{number:02d}", load_config())
    detail = store.get_global_chat(chat["id"])
    with store._connection(write=True) as connection:
        for number, message in enumerate(detail["messages"][1::2]):
            connection.execute(
                "UPDATE messages SET content=? WHERE id=?",
                (f"ANSWER-{number:02d}", message["id"]),
            )
            connection.execute(
                "UPDATE reports SET pi_summary=?, technical_audit=? WHERE message_id=?",
                (f"SUMMARY-{number:02d}", f"TECHNICAL-{number:02d}", message["id"]),
            )
    detail = store.get_global_chat(chat["id"])
    reads = []
    original = store.get_global_chat
    open_connection = store._connection

    def snapshot(identifier):
        reads.append(identifier)
        return original(identifier)

    def read_only(*args, **kwargs):
        assert not kwargs.get("write"), "Export attempted a database write"
        return open_connection(*args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail(
            "History export attempted research, credentials, or external access"
        )

    monkeypatch.setattr(store, "get_global_chat", snapshot)
    monkeypatch.setattr(store, "_connection", read_only)
    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("labcat.science.run_research", forbidden)
    monkeypatch.setattr("labcat.models.plan_with_model", forbidden)
    monkeypatch.setattr("labcat.credentials.CredentialVault.get", forbidden)
    monkeypatch.setattr("labcat.chemical_names.ChemicalNameResolver.names", forbidden)
    with client_for(
        store, config_reader=forbidden, name_source_reader=forbidden
    ) as client:
        response = client.get(f"/api/chats/{chat['id']}/history.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="labcat-{chat["id"]}-history.pdf"'
    )
    assert reads == [chat["id"]]
    text = text_of(response.content)
    markers = [
        marker
        for number in range(22)
        for marker in (
            f"QUERY-{number:02d}",
            f"ANSWER-{number:02d}",
            f"SUMMARY-{number:02d}",
            f"TECHNICAL-{number:02d}",
        )
    ]
    positions = [text.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert "44 saved messages | 22 saved reports" in text
    assert "Saved report revision 22" in text
    for message in detail["messages"]:
        assert message["created_at"] in text
    assert original(chat["id"]) == detail


@pytest.mark.parametrize("legacy_collision", [False, True])
def test_each_report_keeps_its_saved_shortlist_and_source_snapshot(
    tmp_path, legacy_collision
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY")
    chat = store.create_global_chat("TEST ONLY", project["id"])
    for version in range(3):
        store.append_research(
            chat["id"],
            project["id"],
            f"TEST ONLY query version {version}",
            outcome(version),
        )
    detail = store.get_global_chat(chat["id"])
    if legacy_collision:
        force_legacy_collision(store, project["id"], *detail["reports"][:2])
        detail = store.get_global_chat(chat["id"])
    before = deepcopy(detail)
    body, _, _ = render_chat_history(detail)
    text = text_of(body)
    assert "TESTONLY-Alpha" in text
    assert "TEST ONLY body version 1" in text
    assert "TEST ONLY body version 2" in text
    for report in detail["reports"]:
        assert report["id"] in text
        assert report["created_at"] in text
    expected = {source["url"] for source in detail["sources"]}
    assert expected == set(links_of(body))
    assert detail == before == store.get_global_chat(chat["id"])
    # Moving a chat changes ownership, never its saved report/source contents.
    for destination in (None, project["id"]):
        store.move_chat(chat["id"], destination)
        moved = store.get_global_chat(chat["id"])
        moved_text = text_of(render_chat_history(moved)[0])
        assert "TEST ONLY body version 1" in moved_text
        assert "TEST ONLY body version 2" in moved_text


def test_empty_and_nonreport_messages_export_with_literal_untrusted_text(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("TEST ONLY")
    empty = text_of(render_chat_history(store.get_global_chat(chat["id"]))[0])
    assert "No messages have been saved" in empty
    assert "0 saved messages | 0 saved reports" in empty
    detail = store.get_global_chat(chat["id"])
    literal = (
        '<img src="http://127.0.0.1/private"/> <b>Keep literal</b>\n'
        '<link href="file:///etc/passwd">not a link</link>\n'
        "**Markdown stays literal** &lt; https://www.nature.com/articles/sdata2016134"
    )
    detail["messages"] = [
        {
            "id": "plain_message",
            "chat_id": chat["id"],
            "role": "assistant",
            "created_at": "2026-09-27T11:12:13Z",
            "content": literal,
            "report_id": None,
        }
    ]
    body, _, _ = render_chat_history(detail)
    text = text_of(body)
    for part in literal.split("\n"):
        assert part in " ".join(text.split())
    assert not links_of(body)
    assert "2026-09-27T11:12:13Z" in text


@pytest.mark.parametrize("removed", ["chat", "project", "missing"])
def test_removed_chat_and_parent_are_not_exportable(tmp_path, removed):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("TEST ONLY")
    chat = store.create_global_chat("TEST ONLY", project["id"])
    identifier = chat["id"]
    if removed == "chat":
        store.archive_chat(identifier)
    elif removed == "project":
        store.archive_project(project["id"])
    else:
        identifier = "missing"
    with client_for(store) as client:
        response = client.get(f"/api/chats/{identifier}/history.pdf")
    assert response.status_code == 404
    assert response.json() == {"detail": "Chat not found."}


@pytest.mark.parametrize(
    "corruption",
    ["foreign_report", "missing_report", "foreign_source", "missing_source"],
)
def test_history_rejects_cross_chat_or_incomplete_memberships(tmp_path, corruption):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chats = [store.create_global_chat(name) for name in ("Own", "Other")]
    details = []
    for chat in chats:
        scope, _ = store.research_inputs(chat["id"])
        details.append(
            store.append_research(chat["id"], scope, "TEST ONLY", outcome(1))
        )
    detail = deepcopy(details[0])
    if corruption == "foreign_report":
        detail["reports"].append(details[1]["reports"][0])
    elif corruption == "missing_report":
        detail["reports"] = []
    elif corruption == "foreign_source":
        detail["sources"].append(details[1]["sources"][0])
    else:
        detail["sources"] = []
    with pytest.raises(ExportError):
        render_chat_history(detail)
    own_text = text_of(render_chat_history(details[0])[0])
    assert details[1]["reports"][0]["id"] not in own_text


@pytest.mark.parametrize(
    "limit",
    [
        "MAX_CHAT_MESSAGES",
        "MAX_CHAT_REPORTS",
        "MAX_CHAT_CHARACTERS",
        "MAX_CHAT_PAGES",
        "MAX_CHAT_PDF_BYTES",
    ],
)
def test_size_limits_return_errors_instead_of_partial_history(
    saved_chat, monkeypatch, limit
):
    store, chat, _ = saved_chat
    monkeypatch.setattr(chat_exports, limit, 1 if limit != "MAX_CHAT_REPORTS" else 0)
    with client_for(store) as client:
        response = client.get(f"/api/chats/{chat['id']}/history.pdf")
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json"
    assert "limit" in response.json()["detail"]
    assert not response.content.startswith(b"%PDF")


def test_invalid_report_and_database_errors_are_safe_http_errors(
    saved_chat, monkeypatch
):
    store, chat, detail = saved_chat
    detail["reports"][0]["technical_audit"] = ""
    monkeypatch.setattr(store, "get_global_chat", lambda *_: detail)
    with client_for(store) as client:
        response = client.get(f"/api/chats/{chat['id']}/history.pdf")
        assert response.status_code == 422

        def unavailable(*args):
            raise sqlite3.DatabaseError("private path must not escape")

        monkeypatch.setattr(store, "get_global_chat", unavailable)
        response = client.get(f"/api/chats/{chat['id']}/history.pdf")
        assert response.status_code == 503
        assert "private path" not in response.text


def test_message_indentation_long_lines_and_extra_sources_are_retained(saved_chat):
    _, _, detail = saved_chat
    literal = (
        "  Indented    text  \n" + "literal-segment " * 400 + "END-OF-LONG-MESSAGE"
    )
    detail["messages"][0]["content"] = literal
    detail["sources"] = [
        {
            "id": "extra_source",
            "project_id": detail["chat"]["project_id"],
            "chat_ids": [detail["chat"]["id"]],
            "report_ids": [],
            "title": "TEST ONLY additional saved source",
            "source_name": "Public fixture",
            "access_scope": "public",
            "provenance_status": "verified",
            "url": "https://www.nature.com/articles/sdata2016134",
        }
    ]
    body, _, _ = render_chat_history(detail)
    text = text_of(body)
    assert "  Indented    text  " in text
    assert text.count("literal-segment") == 400
    assert "END-OF-LONG-MESSAGE" in text
    assert "Additional saved chat sources" in text
    assert "TEST ONLY additional saved source" in text
    assert detail["sources"][0]["url"] in links_of(body)


@pytest.mark.parametrize(
    "status, reason",
    [("clarification_required", "assessment_missing"), ("refused", "model_declined")],
)
def test_nonreport_intake_messages_and_blocked_reports_are_retained(
    tmp_path, status, reason
):
    from labcat.intake import decision
    from labcat.intake import outcome as intake_outcome

    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("TEST ONLY")
    scope, _ = store.research_inputs(chat["id"])
    intake = intake_outcome(decision(status, reason))
    store.append_research(chat["id"], scope, "TEST ONLY initial intake", intake)
    blocked = outcome(0)
    blocked["stage"] = "blocked"
    detail = store.append_research(chat["id"], scope, "TEST ONLY follow-up", blocked)
    text = text_of(render_chat_history(detail)[0])
    assert "TEST ONLY initial intake" in text
    assert " ".join(intake["answer"].split()) in " ".join(text.split())
    assert "TEST ONLY follow-up" in text
    assert "Stage: blocked" in text
    assert "4 saved messages | 1 saved reports" in text


@pytest.mark.parametrize("page_size", ["letter", "a4"])
@pytest.mark.parametrize("font_family", ["sans", "serif"])
def test_six_column_shortlist_rank_heading_fits_largest_supported_font(
    tmp_path, page_size, font_family
):
    from labcat.config import ReportLayout
    from labcat.report_exports import render_download

    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("TEST ONLY")
    scope, _ = store.research_inputs(chat["id"])
    detail = store.append_research(chat["id"], scope, "TEST ONLY", outcome(1))
    report = {**detail["reports"][0], "sources": detail["sources"]}
    body, _, _ = render_download(
        report,
        "pdf",
        "pi",
        fallback_layout=ReportLayout(
            page_size=page_size,
            font_family=font_family,
            font_size=12,
        ),
    )
    text = text_of(body)
    assert "Rank\nMaterial" in text
    assert "Ra\nnk" not in text
