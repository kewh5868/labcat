"""Local project history; user context never becomes scientific
evidence."""

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from labcat.config import AppConfig
from labcat.science.report_sources import (
    VERSION_PREFIX,
    discovery_annotation,
    discovery_version,
)
from labcat.service import render_report

SCHEMA_VERSION = 5
CONTEXT_LIMITS = {"chats": 100, "messages": 40, "reports": 10, "sources": 20}
UNTITLED_CHAT = "Untitled chat"
REMOVED_RETENTION_DAYS = 30
SEARCH_QUERY_LIMIT = 200
SEARCH_RESULT_LIMIT = 50
SEARCH_SNIPPET_LIMIT = 240
_UNCHANGED = object()

PIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS report_pin_identities (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, report_id TEXT NOT NULL,
    updated_at TEXT NOT NULL, UNIQUE(project_id, report_id),
    FOREIGN KEY(project_id, report_id)
        REFERENCES report_pins(project_id, report_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS tracked_report_pins (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, chat_id TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(project_id, chat_id),
    FOREIGN KEY(chat_id, project_id)
        REFERENCES chats(id, project_id) ON DELETE CASCADE
);
"""

ARCHIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_identities (
    chat_number INTEGER PRIMARY KEY AUTOINCREMENT
        CHECK(chat_number BETWEEN 1 AND 9007199254740991),
    chat_id TEXT NOT NULL UNIQUE,
    FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS workspace_preferences (
    id INTEGER PRIMARY KEY CHECK(id=1),
    confirm_removal INTEGER NOT NULL CHECK(confirm_removal IN (0, 1))
);
CREATE TABLE IF NOT EXISTS message_intakes (
    message_id TEXT PRIMARY KEY, intake_json TEXT NOT NULL,
    FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS message_intake_diagnostics (
    message_id TEXT PRIMARY KEY, diagnostics_json TEXT NOT NULL,
    FOREIGN KEY(message_id) REFERENCES message_intakes(message_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS archived_projects (
    project_id TEXT PRIMARY KEY, archived_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS archived_chats (
    chat_id TEXT PRIMARY KEY, archived_at TEXT NOT NULL,
    FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS manual_chat_titles (
    chat_id TEXT PRIMARY KEY,
    FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS source_annotations (
    source_id TEXT NOT NULL, project_id TEXT NOT NULL, annotation_json TEXT NOT NULL,
    PRIMARY KEY(source_id, project_id),
    FOREIGN KEY(source_id, project_id) REFERENCES sources(id, project_id)
        ON DELETE CASCADE
);
CREATE VIEW IF NOT EXISTS visible_chats AS
    SELECT * FROM chats c WHERE NOT EXISTS
    (SELECT 1 FROM archived_chats a WHERE a.chat_id=c.id)
    AND NOT EXISTS (SELECT 1 FROM archived_projects a WHERE a.project_id=c.project_id);
CREATE VIEW IF NOT EXISTS visible_reports AS
    SELECT * FROM reports r WHERE EXISTS
    (SELECT 1 FROM visible_chats c WHERE c.id=r.chat_id AND c.project_id=r.project_id);
CREATE VIEW IF NOT EXISTS visible_sources AS
    SELECT * FROM sources s WHERE NOT EXISTS
    (SELECT 1 FROM archived_projects a WHERE a.project_id=s.project_id) AND (
        EXISTS(SELECT 1 FROM chat_sources cs JOIN visible_chats c ON c.id=cs.chat_id
            AND c.project_id=cs.project_id
            WHERE cs.source_id=s.id AND cs.project_id=s.project_id)
        OR EXISTS(SELECT 1 FROM report_sources rs
            JOIN visible_reports r ON r.id=rs.report_id
            AND r.project_id=rs.project_id
            WHERE rs.source_id=s.id AND rs.project_id=s.project_id)
        OR (NOT EXISTS(SELECT 1 FROM chat_sources cs
            WHERE cs.source_id=s.id AND cs.project_id=s.project_id)
            AND NOT EXISTS(SELECT 1 FROM report_sources rs
            WHERE rs.source_id=s.id AND rs.project_id=s.project_id))
    );
"""

SCHEMA = """
CREATE TABLE projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    is_internal INTEGER NOT NULL DEFAULT 0 CHECK(is_internal IN (0, 1))
);
CREATE TABLE chats (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(id, project_id),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE messages (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, chat_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(id, chat_id, project_id),
    FOREIGN KEY(chat_id, project_id) REFERENCES chats(id, project_id) ON DELETE CASCADE
);
CREATE TABLE reports (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, chat_id TEXT NOT NULL,
    message_id TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('scaffold', 'complete', 'partial', 'blocked')),
    pi_summary TEXT NOT NULL, technical_audit TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(id, project_id),
    FOREIGN KEY(chat_id, project_id) REFERENCES chats(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY(message_id, chat_id, project_id)
        REFERENCES messages(id, chat_id, project_id) ON DELETE CASCADE
);
CREATE TABLE sources (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
    url TEXT NOT NULL, source_name TEXT NOT NULL, access_scope TEXT NOT NULL,
    provenance_status TEXT NOT NULL
        CHECK(provenance_status IN ('verified', 'unverified', 'rejected')),
    created_at TEXT NOT NULL, UNIQUE(id, project_id),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE chat_sources (
    project_id TEXT NOT NULL, chat_id TEXT NOT NULL, source_id TEXT NOT NULL,
    PRIMARY KEY(project_id, chat_id, source_id),
    FOREIGN KEY(chat_id, project_id) REFERENCES chats(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY(source_id, project_id)
        REFERENCES sources(id, project_id) ON DELETE CASCADE
);
CREATE TABLE report_sources (
    project_id TEXT NOT NULL, report_id TEXT NOT NULL, source_id TEXT NOT NULL,
    PRIMARY KEY(project_id, report_id, source_id),
    FOREIGN KEY(report_id, project_id)
        REFERENCES reports(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY(source_id, project_id)
        REFERENCES sources(id, project_id) ON DELETE CASCADE
);
CREATE TABLE report_pins (
    project_id TEXT NOT NULL, report_id TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, report_id),
    FOREIGN KEY(report_id, project_id)
        REFERENCES reports(id, project_id) ON DELETE CASCADE
);
CREATE TABLE source_pins (
    project_id TEXT NOT NULL, source_id TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, source_id),
    FOREIGN KEY(source_id, project_id)
        REFERENCES sources(id, project_id) ON DELETE CASCADE
);
CREATE INDEX messages_by_chat ON messages(project_id, chat_id, created_at);
CREATE INDEX chats_by_project ON chats(project_id, updated_at);
CREATE TABLE research_runs (
    report_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, outcome_json TEXT NOT NULL,
    FOREIGN KEY(report_id, project_id)
        REFERENCES reports(id, project_id) ON DELETE CASCADE
);
CREATE TABLE source_records (
    project_id TEXT NOT NULL, source_id TEXT NOT NULL, record_key TEXT NOT NULL,
    PRIMARY KEY(project_id, record_key),
    FOREIGN KEY(source_id, project_id)
        REFERENCES sources(id, project_id) ON DELETE CASCADE
);
CREATE TABLE app_settings (
    id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL
);
"""


class WorkspaceNotFound(ValueError):
    """An item does not exist inside the requested project."""


class WorkspaceConflict(ValueError):
    """A chat moved while a research request was in flight."""


class WorkspacePinConflict(ValueError):
    """A snapshot changed, or the selected revision already has a
    snapshot."""


class WorkspaceRestoreConflict(ValueError):
    """A removed chat's project must be restored first."""


class WorkspaceRemovedConflict(ValueError):
    """The removed-items list changed after permanent deletion was
    reviewed."""


class WorkspaceGeneralChatsConflict(ValueError):
    """General-chat membership changed after bulk removal was
    reviewed."""


class WorkspaceSchemaError(RuntimeError):
    """Stored data needs a supported migration; never silently reset
    it."""


def _sanitize_assessment_completion(result) -> None:
    """Validate optional diagnostic metadata on a fresh decoded report
    only.

    Older reports have no completion counters. Invalid optional counters
    must neither expose arbitrary saved strings nor prevent access to
    the report. This does not rewrite the stored outcome or its
    scientific interpretations.
    """
    if not isinstance(result, dict):
        return
    from labcat.assessment_completion import validate_assessment_completion

    containers = [result]
    if isinstance(result.get("execution"), dict):
        containers.append(result["execution"])
    for container in containers:
        plan = container.get("build_plan")
        evaluation = (
            plan.get("candidate_evaluation") if isinstance(plan, dict) else None
        )
        if not isinstance(evaluation, dict) or "task_completion" not in evaluation:
            continue
        try:
            evaluation["task_completion"] = validate_assessment_completion(
                evaluation["task_completion"]
            )
        except ValueError:
            del evaluation["task_completion"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _submitted_timestamp(value: str | None, completed_at: str) -> str:
    """Normalize trusted run metadata; historical/direct saves use save
    time."""
    if value is None:
        return completed_at
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Research submission timestamp is invalid.")
    try:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("A timezone is required.")
        return timestamp.astimezone(UTC).isoformat(timespec="microseconds")
    except (ValueError, OverflowError) as error:
        raise ValueError("Research submission timestamp is invalid.") from error


def _search_normalized(value: str) -> str:
    """Literal, Unicode-aware matching without treating punctuation as
    syntax."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _search_snippet(value: str, needle: str) -> str:
    """Return a small plain-text excerpt around the match, preserving
    its text."""
    text = " ".join(value.split())
    position = _search_normalized(text).find(needle)
    # Case folding and compatibility normalization may change string lengths
    # (for example Straße/STRASSE and chemical subscripts). Map the match back
    # to the original display text instead of slicing at a folded-string index.
    low, high = 0, len(text)
    while low < high:
        middle = (low + high) // 2
        if len(_search_normalized(text[:middle])) <= position:
            low = middle + 1
        else:
            high = middle
    start = max(0, low - 1 - 60) if position >= 0 else 0
    end = min(len(text), start + SEARCH_SNIPPET_LIMIT - 2)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def _removal_deadline(archived_at) -> datetime | None:
    """Use only unambiguous stored ages; malformed timestamps remain
    recoverable."""
    if not isinstance(archived_at, str):
        return None
    try:
        removed_at = datetime.fromisoformat(archived_at)
        if removed_at.tzinfo is None or removed_at.utcoffset() is None:
            return None
        return removed_at.astimezone(UTC) + timedelta(days=REMOVED_RETENTION_DAYS)
    except (ValueError, OverflowError):
        return None


def _title_from_prompt(content: str) -> str:
    """Extract a short navigation label, never a scientific fact or
    instruction.

    This local, deterministic transformation cannot call a model, follow
    a URL, or add evidence. Preserve formula capitalization and the
    question's own words.
    """
    text = re.sub(r"(?:https?://|www\.)\S+", " ", content, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]*>", " ", text)
    text = "".join(
        " " if character.isspace() else character
        for character in text
        if character.isspace() or not unicodedata.category(character).startswith("C")
    )
    text = " ".join(text.split()).strip("#*`_ \"'")
    text = re.sub(
        r"^(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?"
        r"(?:(?:please|help me(?: to)?)\s+)*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:(?:I|we)\s+(?:(?:would|would really)\s+like|want|need|hope)"
        r"\s+(?:to\s+)?)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:find|identify|suggest|recommend|look for|search for|prepare|build|"
        r"give me|show me)\s+"
        r"(?:(?:a|an|some|promising|suitable)\s+)*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:an?\s+|the\s+)?(?:(?:starting|initial|short|ranked|brief)\s+)*"
        r"(?:list|shortlist|comparison|overview|review)\s+of\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip(" .!?;:#*`_\"'")
    # Compress common request grammar while preserving the topic and application.
    # This remains a navigation label, never an assertion of material performance.
    text = re.sub(
        r"\s+(?:material|materials|candidate|candidates)\s+that\s+"
        r"(?:can|could|would|will|may)\s+be\s+(?:used|suitable)\s+(?:in|for)\s+"
        r"(?:an?\s+)?",
        " for ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.split(
        r"\s+(?:and\s+)?(?:has|have|with)\s+(?:an?\s+)?band\s*gap\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    if not any(character.isalnum() for character in text):
        return "Research question"
    words = text.split()
    title = " ".join(words[:10])
    truncated = len(words) > 10 or len(title) > 72
    if len(title) > 72:
        prefix = title[:71]
        title = prefix.rsplit(" ", 1)[0] if " " in prefix else prefix
    title = title[0].upper() + title[1:]
    return title.rstrip(" ,;:") + ("…" if truncated else "")


class WorkspaceStore:
    """Open one connection per operation, with atomic writes and foreign
    keys.

    This is a single-user local store, not an authenticated multi-user
    service. It has no credential fields or public method for minting
    source evidence.
    """

    def __init__(self, path: Path, *, initialize: bool = True):
        self.path = Path(path)
        if initialize:
            self.initialize()

    def initialize(self) -> None:
        """Create or validate storage at startup; safe to call more than
        once."""
        if self.path.is_symlink():
            raise WorkspaceSchemaError("Workspace database must not be a symlink.")
        parent_existed = self.path.parent.exists()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix" and not parent_existed:
            self.path.parent.chmod(0o700)
        descriptor = os.open(
            self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        try:
            if os.name == "posix":
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        connection = self._open()
        try:
            # Check compatibility before changing persistent journal settings.
            self._schema_version(connection)
            # Rebuilding the report CHECK constraint must not cascade-delete pins.
            # This connection is initialization-only; all operations enable FKs.
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("BEGIN IMMEDIATE")
            version = self._schema_version(connection)
            if version == 0:
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            elif version == 1:
                connection.execute(
                    "ALTER TABLE projects ADD COLUMN is_internal INTEGER NOT NULL "
                    "DEFAULT 0 CHECK(is_internal IN (0, 1))"
                )
                connection.execute(
                    "CREATE TABLE app_settings "
                    "(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)"
                )
            if version in (1, 2):
                definition = SCHEMA.split("CREATE TABLE reports (", 1)[1].split(";", 1)[
                    0
                ]
                connection.execute("CREATE TABLE reports_new (" + definition)
                connection.execute("INSERT INTO reports_new SELECT * FROM reports")
                connection.execute("DROP TABLE reports")
                connection.execute("ALTER TABLE reports_new RENAME TO reports")
                for table in ("research_runs", "source_records"):
                    definition = SCHEMA.split(f"CREATE TABLE {table} (", 1)[1].split(
                        ";", 1
                    )[0]
                    connection.execute(f"CREATE TABLE {table} (" + definition)
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise WorkspaceSchemaError("Workspace integrity check failed.")
            for statement in ARCHIVE_SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(statement)
            for statement in PIN_SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(statement)
            # Legacy report pins already point at immutable revisions. Assign
            # stable pin identities without changing their reports or timestamps.
            for pin in connection.execute(
                "SELECT p.project_id,p.report_id,p.created_at FROM report_pins p "
                "WHERE NOT EXISTS(SELECT 1 FROM report_pin_identities i "
                "WHERE i.project_id=p.project_id AND i.report_id=p.report_id)"
            ).fetchall():
                connection.execute(
                    "INSERT INTO report_pin_identities VALUES (?,?,?,?)",
                    (
                        uuid4().hex,
                        pin["project_id"],
                        pin["report_id"],
                        pin["created_at"],
                    ),
                )
            # Backfill deterministically without touching UUIDs, names or history.
            # AUTOINCREMENT retains its high-water mark after permanent deletion.
            connection.execute(
                "INSERT INTO chat_identities (chat_id) SELECT c.id FROM chats c "
                "WHERE NOT EXISTS(SELECT 1 FROM chat_identities i "
                "WHERE i.chat_id=c.id) "
                "ORDER BY c.created_at,c.id"
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            # Add a starter only to empty visible projects. The same startup
            # transaction serializes concurrent initialization; existing history,
            # titles and project timestamps are untouched, with no schema rewrite.
            empty_projects = connection.execute(
                "SELECT id FROM projects p WHERE is_internal=0 AND NOT EXISTS "
                "(SELECT 1 FROM archived_projects a WHERE a.project_id=p.id) AND NOT "
                "EXISTS "
                "(SELECT 1 FROM chats c WHERE c.project_id=p.id)"
            ).fetchall()
            for project in empty_projects:
                self._insert_chat(connection, project["id"], UNTITLED_CHAT, _now())
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise WorkspaceSchemaError("Workspace relationship integrity failed.")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _schema_version(connection) -> int:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2, 3, 4, SCHEMA_VERSION):
            raise WorkspaceSchemaError(
                "Unsupported workspace schema version; migration is required."
            )
        if version == 0:
            existing = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if existing:
                raise WorkspaceSchemaError(
                    "Unversioned workspace database; migration is required."
                )
        return version

    def _open(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _connection(self, *, write: bool = False):
        connection = self._open()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _project(connection, project_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT id,name,description,created_at,updated_at "
            "FROM projects p WHERE id=? AND is_internal=0 AND NOT EXISTS "
            "(SELECT 1 FROM archived_projects a WHERE a.project_id=p.id)",
            (project_id,),
        ).fetchone()
        if row is None:
            raise WorkspaceNotFound("Workspace item not found.")
        project = dict(row)
        project["pin_counts"] = WorkspaceStore._pin_counts(connection, project_id)
        project["chat_count"] = connection.execute(
            "SELECT COUNT(*) FROM visible_chats WHERE project_id=?", (project_id,)
        ).fetchone()[0]
        return project

    @staticmethod
    def _pin_counts(connection, project_id, chat_id=None):
        reports = (
            "SELECT COUNT(*) FROM report_pins p JOIN visible_reports r "
            "ON r.id=p.report_id AND r.project_id=p.project_id WHERE p.project_id=?"
        )
        sources = (
            "SELECT COUNT(*) FROM source_pins p JOIN visible_sources s "
            "ON s.id=p.source_id AND s.project_id=p.project_id WHERE p.project_id=?"
        )
        tracking = (
            "SELECT COUNT(*) FROM tracked_report_pins p JOIN visible_chats c "
            "ON c.id=p.chat_id AND c.project_id=p.project_id WHERE p.project_id=?"
        )
        args = [project_id]
        source_args = [project_id]
        if chat_id is not None:
            reports += " AND r.chat_id=?"
            tracking += " AND p.chat_id=?"
            args.append(chat_id)
            sources += (
                " AND (EXISTS(SELECT 1 FROM chat_sources c "
                "WHERE c.project_id=p.project_id AND c.source_id=p.source_id "
                "AND c.chat_id=?) OR EXISTS(SELECT 1 FROM report_sources rs "
                "JOIN visible_reports r ON r.id=rs.report_id AND "
                "r.project_id=rs.project_id "
                "WHERE rs.project_id=p.project_id AND rs.source_id=p.source_id "
                "AND r.chat_id=?))"
            )
            source_args.extend([chat_id, chat_id])
        return {
            "reports": connection.execute(reports, args).fetchone()[0]
            + connection.execute(tracking, args).fetchone()[0],
            "sources": connection.execute(sources, source_args).fetchone()[0],
        }

    @staticmethod
    def _public_project_id(connection, scope_id: str) -> str | None:
        row = connection.execute(
            "SELECT is_internal FROM projects p WHERE id=? AND NOT EXISTS "
            "(SELECT 1 FROM archived_projects a WHERE a.project_id=p.id)",
            (scope_id,),
        ).fetchone()
        if row is None:
            raise WorkspaceNotFound("Workspace item not found.")
        return None if row[0] else scope_id

    @staticmethod
    def _scope_for_chat(connection, chat_id: str) -> str:
        row = connection.execute(
            "SELECT project_id FROM visible_chats WHERE id=?", (chat_id,)
        ).fetchone()
        if row is None:
            raise WorkspaceNotFound("Workspace item not found.")
        return row[0]

    @staticmethod
    def _new_private_scope(connection) -> str:
        """An invisible storage scope, not a user project, for one
        standalone chat.

        Non-null composite foreign keys remain enforceable inside this
        scope. Its ID is never returned or accepted through project-
        facing endpoints.
        """
        scope_id, timestamp = uuid4().hex, _now()
        connection.execute(
            "INSERT INTO projects "
            "(id,name,description,created_at,updated_at,is_internal) "
            "VALUES (?,?,?,?,?,1)",
            (scope_id, "", "", timestamp, timestamp),
        )
        return scope_id

    @staticmethod
    def _chat_identity(connection, chat_id: str, title: str):
        row = connection.execute(
            "SELECT chat_number FROM chat_identities WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("Stored chat identity is missing.")
        return {"chat_number": row[0], "display_title": f"{title} · #{row[0]}"}

    @staticmethod
    def _chat(connection, project_id: str, chat_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM visible_chats WHERE id=? AND project_id=?",
            (chat_id, project_id),
        ).fetchone()
        if row is None:
            raise WorkspaceNotFound("Workspace item not found.")
        chat = dict(row)
        chat.update(WorkspaceStore._chat_identity(connection, chat_id, chat["title"]))
        chat["pin_counts"] = WorkspaceStore._pin_counts(connection, project_id, chat_id)
        chat["message_count"] = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE project_id=? AND chat_id=?",
            (project_id, chat_id),
        ).fetchone()[0]
        return chat

    @staticmethod
    def _insert_chat(connection, project_id, title, timestamp):
        chat_id = uuid4().hex
        connection.execute(
            "INSERT INTO chats VALUES (?,?,?,?,?)",
            (chat_id, project_id, title, timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO chat_identities (chat_id) VALUES (?)", (chat_id,)
        )
        return chat_id

    @staticmethod
    def _name_first_prompt(connection, project_id, chat_id, content):
        # Called on accepted submission or before inserting a saved exchange.
        # Custom titles and previously used chats are never renamed here.
        return connection.execute(
            "UPDATE chats SET title=? WHERE id=? AND project_id=? AND title=? "
            "AND NOT EXISTS(SELECT 1 FROM messages m WHERE m.chat_id=chats.id "
            "AND m.project_id=chats.project_id AND m.role='user') "
            "AND NOT EXISTS(SELECT 1 FROM manual_chat_titles t WHERE "
            "t.chat_id=chats.id)",
            (_title_from_prompt(content), chat_id, project_id, UNTITLED_CHAT),
        ).rowcount

    @staticmethod
    def _chats(connection, project_id: str) -> list[dict[str, Any]]:
        return [
            WorkspaceStore._chat(connection, project_id, row["id"])
            for row in connection.execute(
                "SELECT * FROM visible_chats WHERE project_id=? ORDER BY updated_at "
                "DESC,id",
                (project_id,),
            )
        ]

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            return [
                self._project(connection, row["id"])
                for row in connection.execute(
                    "SELECT id,name,description,created_at,updated_at FROM projects "
                    "WHERE is_internal=0 AND NOT EXISTS(SELECT 1 FROM "
                    "archived_projects a "
                    "WHERE a.project_id=projects.id) ORDER BY updated_at DESC,id"
                )
            ]

    def search(self, query: str, limit: int = 20) -> dict[str, Any]:
        """Search saved, visible navigation and conversation text
        locally.

        Results are capped per kind. Titles precede content matches,
        then newer chats/projects come first, with IDs breaking ties.
        Sources, credentials, intake metadata and research execution
        JSON are never searched. This is navigation text, not newly
        retrieved or validated scientific evidence.
        """
        if not isinstance(query, str) or len(query) > SEARCH_QUERY_LIMIT:
            raise ValueError("Search queries must be at most 200 characters.")
        if type(limit) is not int or not 1 <= limit <= SEARCH_RESULT_LIMIT:
            raise ValueError("Search limits must be between 1 and 50.")
        query = query.strip()
        result: dict[str, Any] = {
            "query": query,
            "projects": [],
            "chats": [],
            "has_more": False,
        }
        needle = _search_normalized(query)
        if not needle:
            return result
        with self._connection() as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.create_function(
                "workspace_search_fold", 1, _search_normalized, deterministic=True
            )
            parameters = {"needle": needle, "fetch_limit": limit + 1}
            projects = connection.execute(
                "SELECT p.id,p.name,p.description,"
                "CASE WHEN instr(workspace_search_fold(p.name),:needle)>0 "
                "THEN 'name' ELSE 'description' END AS match_field "
                "FROM projects p WHERE p.is_internal=0 AND NOT EXISTS "
                "(SELECT 1 FROM archived_projects a WHERE a.project_id=p.id) "
                "AND (instr(workspace_search_fold(p.name),:needle)>0 OR "
                "instr(workspace_search_fold(p.description),:needle)>0) "
                "ORDER BY CASE WHEN match_field='name' THEN 0 ELSE 1 END,"
                "p.updated_at DESC,p.id LIMIT :fetch_limit",
                parameters,
            ).fetchall()
            # Only lightweight match identities participate in de-duplication;
            # conversation bodies are not copied into an in-memory result list.
            chats = connection.execute(
                "WITH matches AS ("
                "SELECT c.id AS chat_id,c.project_id,0 AS priority,"
                "'title' AS match_field,NULL AS message_id,NULL AS report_id,"
                "c.updated_at AS matched_at,c.id AS matched_id "
                "FROM visible_chats c "
                "WHERE instr(workspace_search_fold(c.title),:needle)>0 "
                "UNION ALL "
                "SELECT m.chat_id,m.project_id,1,'message',m.id,NULL,"
                "m.created_at,m.id FROM messages m JOIN visible_chats c "
                "ON c.id=m.chat_id AND c.project_id=m.project_id "
                "WHERE instr(workspace_search_fold(m.content),:needle)>0 "
                "UNION ALL "
                "SELECT r.chat_id,r.project_id,1,'report',r.message_id,r.id,"
                "r.created_at,r.id FROM visible_reports r JOIN messages m "
                "ON m.id=r.message_id AND m.chat_id=r.chat_id "
                "AND m.project_id=r.project_id WHERE "
                "instr(workspace_search_fold(r.pi_summary),:needle)>0 OR "
                "instr(workspace_search_fold(r.technical_audit),:needle)>0"
                "), ranked AS (SELECT *,row_number() OVER ("
                "PARTITION BY chat_id,project_id ORDER BY priority,matched_at DESC,"
                "match_field,matched_id DESC) AS match_rank FROM matches) "
                "SELECT ranked.*,CASE WHEN p.is_internal=1 THEN NULL ELSE p.name "
                "END AS project_name FROM ranked JOIN visible_chats c "
                "ON c.id=ranked.chat_id AND c.project_id=ranked.project_id "
                "JOIN projects p ON p.id=c.project_id WHERE match_rank=1 "
                "ORDER BY priority,c.updated_at DESC,c.id LIMIT :fetch_limit",
                parameters,
            ).fetchall()
            result["has_more"] = len(projects) > limit or len(chats) > limit
            result["projects"] = [
                {
                    "project": self._project(connection, row["id"]),
                    "match_field": row["match_field"],
                    "snippet": _search_snippet(row[row["match_field"]], needle),
                }
                for row in projects[:limit]
            ]
            for row in chats[:limit]:
                chat = self._chat(connection, row["project_id"], row["chat_id"])
                chat["project_id"] = self._public_project_id(
                    connection, row["project_id"]
                )
                if row["match_field"] == "message":
                    text = connection.execute(
                        "SELECT content FROM messages WHERE id=? AND chat_id=? "
                        "AND project_id=?",
                        (row["message_id"], row["chat_id"], row["project_id"]),
                    ).fetchone()[0]
                elif row["match_field"] == "report":
                    report = connection.execute(
                        "SELECT pi_summary,technical_audit FROM visible_reports "
                        "WHERE id=? AND chat_id=? AND project_id=? AND message_id=?",
                        (
                            row["report_id"],
                            row["chat_id"],
                            row["project_id"],
                            row["message_id"],
                        ),
                    ).fetchone()
                    text = (
                        report["pi_summary"]
                        if needle in _search_normalized(report["pi_summary"])
                        else report["technical_audit"]
                    )
                else:
                    text = chat["title"]
                result["chats"].append(
                    {
                        "chat": chat,
                        "project_name": row["project_name"],
                        "match_field": row["match_field"],
                        "snippet": _search_snippet(text, needle),
                        "message_id": row["message_id"],
                        "report_id": row["report_id"],
                    }
                )
        return result

    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        project_id, timestamp = uuid4().hex, _now()
        with self._connection(write=True) as connection:
            connection.execute(
                "INSERT INTO projects "
                "(id,name,description,created_at,updated_at) VALUES (?,?,?,?,?)",
                (project_id, name, description, timestamp, timestamp),
            )
            self._insert_chat(connection, project_id, UNTITLED_CHAT, timestamp)
            return self._project(connection, project_id)

    def update_project(self, project_id: str, *, name=None, description=None):
        """Change navigation metadata without rewriting scientific
        history."""
        with self._connection(write=True) as connection:
            project = self._project(connection, project_id)
            connection.execute(
                "UPDATE projects SET name=?,description=?,updated_at=? WHERE id=?",
                (
                    project["name"] if name is None else name,
                    project["description"] if description is None else description,
                    _now(),
                    project_id,
                ),
            )
            return self._project(connection, project_id)

    def archive_project(self, project_id: str):
        """Hide a project and its children for the recovery period."""
        with self._connection(write=True) as connection:
            self._project(connection, project_id)
            connection.execute(
                "INSERT INTO archived_projects VALUES (?,?)", (project_id, _now())
            )

    def restore_project(self, project_id: str):
        with self._connection(write=True) as connection:
            self._purge_expired(connection, datetime.now(UTC))
            row = connection.execute(
                "SELECT p.id FROM projects p JOIN archived_projects a ON "
                "a.project_id=p.id "
                "WHERE p.id=? AND p.is_internal=0",
                (project_id,),
            ).fetchone()
            if row is not None:
                connection.execute(
                    "DELETE FROM archived_projects WHERE project_id=?", (project_id,)
                )
                restored = self._project(connection, project_id)
        # Commit expiration even when this item is no longer recoverable.
        if row is None:
            raise WorkspaceNotFound("Workspace item not found.")
        return restored

    def archive_chat(self, chat_id: str):
        with self._connection(write=True) as connection:
            self._scope_for_chat(connection, chat_id)
            connection.execute(
                "INSERT INTO archived_chats VALUES (?,?)", (chat_id, _now())
            )

    def archive_general_chats(self, *, confirm=False, snapshot=None):
        """Atomically remove only the reviewed, currently visible
        general chats."""
        if confirm is not True:
            raise ValueError("Clearing general chats requires explicit confirmation.")
        if (
            not isinstance(snapshot, list)
            or any(
                not isinstance(chat_id, str) or not 1 <= len(chat_id) <= 64
                for chat_id in snapshot
            )
            or len(snapshot) != len(set(snapshot))
        ):
            raise ValueError("Provide a unique list of reviewed general-chat IDs.")
        with self._connection(write=True) as connection:
            current = {
                row[0]
                for row in connection.execute(
                    "SELECT c.id FROM visible_chats c "
                    "JOIN projects p ON p.id=c.project_id WHERE p.is_internal=1"
                )
            }
            if current != set(snapshot):
                raise WorkspaceGeneralChatsConflict(
                    "General chats changed. Review the updated list and try again."
                )
            timestamp = _now()
            connection.executemany(
                "INSERT INTO archived_chats VALUES (?,?)",
                [(chat_id, timestamp) for chat_id in sorted(current)],
            )
            return {"removed_chats": len(current)}

    def restore_chat(self, chat_id: str):
        with self._connection(write=True) as connection:
            self._purge_expired(connection, datetime.now(UTC))
            row = connection.execute(
                "SELECT c.project_id FROM chats c JOIN archived_chats a ON "
                "a.chat_id=c.id "
                "WHERE c.id=?",
                (chat_id,),
            ).fetchone()
            parent_removed = row is not None and (
                connection.execute(
                    "SELECT 1 FROM archived_projects WHERE project_id=?", (row[0],)
                ).fetchone()
                is not None
            )
            if row is not None and not parent_removed:
                connection.execute(
                    "DELETE FROM archived_chats WHERE chat_id=?", (chat_id,)
                )
                restored = self._detail(connection, row[0], chat_id)
        # No restore can interleave with expiration; failures must not undo cleanup.
        if row is None:
            raise WorkspaceNotFound("Workspace item not found.")
        if parent_removed:
            raise WorkspaceRestoreConflict(
                "Restore the project before restoring this chat."
            )
        return restored

    def removed_items(self):
        """List recoverable navigation items; project children are not
        duplicated."""
        with self._connection(write=True) as connection:
            self._purge_expired(connection, datetime.now(UTC))
            return self._removed_items(connection)

    def _removed_items(self, connection):
        """Read a consistent removal snapshot within the caller's
        transaction."""
        projects = []
        for row in connection.execute(
            "SELECT "
            "p.id,p.name,p.description,p.created_at,p.updated_at,a.archived_at "
            "FROM projects p JOIN archived_projects a ON a.project_id=p.id "
            "WHERE p.is_internal=0 ORDER BY a.archived_at DESC,p.id"
        ):
            project = dict(row)
            deadline = _removal_deadline(row["archived_at"])
            project["expires_at"] = deadline.isoformat() if deadline else None
            project["chat_count"] = connection.execute(
                "SELECT COUNT(*) FROM chats WHERE project_id=?", (row["id"],)
            ).fetchone()[0]
            project["pin_counts"] = {
                "reports": connection.execute(
                    "SELECT (SELECT COUNT(*) FROM report_pins WHERE project_id=?)"
                    "+(SELECT COUNT(*) FROM tracked_report_pins "
                    "WHERE project_id=?)",
                    (row["id"], row["id"]),
                ).fetchone()[0],
                "sources": connection.execute(
                    "SELECT COUNT(*) FROM source_pins WHERE project_id=?",
                    (row["id"],),
                ).fetchone()[0],
            }
            projects.append(project)
        chats = []
        for row in connection.execute(
            "SELECT c.id,CASE WHEN p.is_internal=1 THEN NULL ELSE c.project_id "
            "END AS project_id,"
            "c.title,c.created_at,c.updated_at,a.archived_at,"
            "pa.archived_at AS parent_archived_at FROM chats c "
            "JOIN projects p ON p.id=c.project_id JOIN archived_chats a ON "
            "a.chat_id=c.id LEFT JOIN archived_projects pa "
            "ON pa.project_id=p.id AND p.is_internal=0 "
            "ORDER BY a.archived_at DESC,c.id"
        ):
            chat = dict(row)
            deadlines = [
                deadline
                for timestamp in (
                    chat["archived_at"],
                    chat.pop("parent_archived_at"),
                )
                if (deadline := _removal_deadline(timestamp)) is not None
            ]
            chat["expires_at"] = min(deadlines).isoformat() if deadlines else None
            chat.update(self._chat_identity(connection, row["id"], row["title"]))
            chat["message_count"] = connection.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id=?", (row["id"],)
            ).fetchone()[0]
            chat["pin_counts"] = {
                "reports": connection.execute(
                    "SELECT (SELECT COUNT(*) FROM report_pins p JOIN reports r ON "
                    "r.id=p.report_id "
                    "AND r.project_id=p.project_id WHERE r.chat_id=?)"
                    "+(SELECT COUNT(*) FROM tracked_report_pins WHERE chat_id=?)",
                    (row["id"], row["id"]),
                ).fetchone()[0],
                "sources": connection.execute(
                    "SELECT COUNT(*) FROM source_pins p WHERE EXISTS(SELECT 1 "
                    "FROM chat_sources cs "
                    "WHERE cs.source_id=p.source_id AND "
                    "cs.project_id=p.project_id AND cs.chat_id=?) "
                    "OR EXISTS(SELECT 1 FROM report_sources rs JOIN reports r ON "
                    "r.id=rs.report_id "
                    "AND r.project_id=rs.project_id WHERE rs.source_id=p.source_id "
                    "AND rs.project_id=p.project_id AND r.chat_id=?)",
                    (row["id"], row["id"]),
                ).fetchone()[0],
            }
            chats.append(chat)
        items = {
            "projects": projects,
            "chats": chats,
            "retention_days": REMOVED_RETENTION_DAYS,
        }
        items["snapshot"] = hashlib.sha256(
            json.dumps(items, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return items

    def workspace_preferences(self):
        """Navigation preferences are independent of scientific report
        settings."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT confirm_removal FROM workspace_preferences WHERE id=1"
            ).fetchone()
            if row is None:
                return {"confirm_removal": True}
            if type(row[0]) is not int or row[0] not in (0, 1):
                raise sqlite3.DatabaseError("Stored workspace preference is invalid.")
            return {"confirm_removal": bool(row[0])}

    def save_workspace_preferences(self, *, confirm_removal):
        if type(confirm_removal) is not bool:
            raise ValueError("Removal confirmation must be a boolean.")
        with self._connection(write=True) as connection:
            connection.execute(
                "INSERT INTO workspace_preferences (id,confirm_removal) VALUES (1,?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "confirm_removal=excluded.confirm_removal",
                (int(confirm_removal),),
            )
        return {"confirm_removal": confirm_removal}

    def purge_removed(self, *, confirm=False, snapshot=None):
        """Atomically delete the reviewed removed items, preserving
        active history."""
        if confirm is not True:
            raise ValueError("Permanent deletion requires explicit confirmation.")
        if not isinstance(snapshot, str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot):
            raise ValueError("Permanent deletion requires a removed-items snapshot.")
        with self._connection(write=True) as connection:
            items = self._removed_items(connection)
            if snapshot != items["snapshot"]:
                raise WorkspaceRemovedConflict(
                    "Removed items changed. Review the updated list and try again."
                )
            counts = {"projects": 0, "chats": 0}
            for project in items["projects"]:
                counts["chats"] += self._purge_project(connection, project["id"])
                counts["projects"] += 1
            # Project cascades already removed their children; select survivors.
            for row in connection.execute(
                "SELECT chat_id FROM archived_chats"
            ).fetchall():
                self._purge_chat(connection, row["chat_id"])
                counts["chats"] += 1
            return counts

    def purge_expired(self, now: datetime | None = None):
        """Permanently delete removals at least 30 days old, in one
        transaction.

        Counts include all deleted chats, including project children.
        Internal standalone scopes are cleanup details and do not count
        as public projects.
        """
        if now is None:
            now = datetime.now(UTC)
        if (
            not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise ValueError("Retention cleanup requires a timezone-aware time.")
        with self._connection(write=True) as connection:
            return self._purge_expired(connection, now.astimezone(UTC))

    def _purge_expired(self, connection, now: datetime):
        counts = {"projects": 0, "chats": 0}
        for row in connection.execute(
            "SELECT p.id,a.archived_at FROM projects p JOIN archived_projects a "
            "ON a.project_id=p.id WHERE p.is_internal=0"
        ).fetchall():
            deadline = _removal_deadline(row["archived_at"])
            if deadline is not None and deadline <= now:
                counts["chats"] += self._purge_project(connection, row["id"])
                counts["projects"] += 1
        for row in connection.execute(
            "SELECT chat_id,archived_at FROM archived_chats"
        ).fetchall():
            deadline = _removal_deadline(row["archived_at"])
            if deadline is not None and deadline <= now:
                self._purge_chat(connection, row["chat_id"])
                counts["chats"] += 1
        return counts

    def purge_project(self, project_id: str, *, confirm=False):
        """Delete only an explicitly removed public project and its
        current children."""
        if confirm is not True:
            raise ValueError("Permanent deletion requires explicit confirmation.")
        with self._connection(write=True) as connection:
            self._purge_project(connection, project_id)

    @staticmethod
    def _purge_project(connection, project_id: str):
        row = connection.execute(
            "SELECT p.id FROM projects p JOIN archived_projects a "
            "ON a.project_id=p.id WHERE p.id=? AND p.is_internal=0",
            (project_id,),
        ).fetchone()
        if row is None:
            raise WorkspaceNotFound("Removed workspace item not found.")
        chat_count = connection.execute(
            "SELECT COUNT(*) FROM chats WHERE project_id=?", (project_id,)
        ).fetchone()[0]
        # Composite foreign keys cascade only within this project scope.
        connection.execute("DELETE FROM projects WHERE id=?", (project_id,))
        return chat_count

    def purge_chat(self, chat_id: str, *, confirm=False):
        """Delete a removed chat; retain surviving links and project-
        pinned sources."""
        if confirm is not True:
            raise ValueError("Permanent deletion requires explicit confirmation.")
        with self._connection(write=True) as connection:
            self._purge_chat(connection, chat_id)

    @staticmethod
    def _purge_chat(connection, chat_id: str):
        row = connection.execute(
            "SELECT c.project_id,p.is_internal FROM chats c "
            "JOIN archived_chats a ON a.chat_id=c.id "
            "JOIN projects p ON p.id=c.project_id WHERE c.id=?",
            (chat_id,),
        ).fetchone()
        if row is None:
            raise WorkspaceNotFound("Removed workspace item not found.")
        project_id = row["project_id"]
        # Capture this chat's associations before the cascades. Never sweep
        # unrelated orphan sources, which can be project-owned saved material.
        source_ids = [
            source[0]
            for source in connection.execute(
                "SELECT source_id FROM chat_sources WHERE project_id=? "
                "AND chat_id=? UNION SELECT rs.source_id FROM report_sources rs "
                "JOIN reports r ON r.id=rs.report_id "
                "AND r.project_id=rs.project_id "
                "WHERE r.project_id=? AND r.chat_id=?",
                (project_id, chat_id, project_id, chat_id),
            )
        ]
        connection.execute("DELETE FROM chats WHERE id=?", (chat_id,))
        for source_id in source_ids:
            connection.execute(
                "DELETE FROM sources WHERE id=? AND project_id=? "
                "AND NOT EXISTS(SELECT 1 FROM chat_sources cs "
                "WHERE cs.source_id=sources.id "
                "AND cs.project_id=sources.project_id) "
                "AND NOT EXISTS(SELECT 1 FROM report_sources rs "
                "WHERE rs.source_id=sources.id "
                "AND rs.project_id=sources.project_id) "
                "AND NOT EXISTS(SELECT 1 FROM source_pins p "
                "WHERE p.source_id=sources.id AND p.project_id=sources.project_id)",
                (source_id, project_id),
            )
        if row["is_internal"]:
            connection.execute(
                "DELETE FROM projects WHERE id=? AND is_internal=1 "
                "AND NOT EXISTS(SELECT 1 FROM chats WHERE project_id=projects.id)",
                (project_id,),
            )

    def list_chats(self, project_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            self._project(connection, project_id)
            return self._chats(connection, project_id)

    def create_chat(self, project_id: str, title: str) -> dict[str, Any]:
        timestamp = _now()
        with self._connection(write=True) as connection:
            self._project(connection, project_id)
            chat_id = self._insert_chat(connection, project_id, title, timestamp)
            connection.execute(
                "UPDATE projects SET updated_at=? WHERE id=?", (timestamp, project_id)
            )
            return self._chat(connection, project_id, chat_id)

    def project_draft(self, project_id: str) -> dict[str, Any]:
        """Atomically reuse an empty default chat for the project prompt
        field."""
        with self._connection(write=True) as connection:
            self._project(connection, project_id)
            row = connection.execute(
                "SELECT id FROM visible_chats c WHERE project_id=? AND title=? "
                "AND NOT EXISTS(SELECT 1 FROM messages m WHERE m.chat_id=c.id "
                "AND m.project_id=c.project_id) ORDER BY created_at,id LIMIT 1",
                (project_id, UNTITLED_CHAT),
            ).fetchone()
            if row is not None:
                return self._chat(connection, project_id, row["id"])
            timestamp = _now()
            chat_id = self._insert_chat(
                connection, project_id, UNTITLED_CHAT, timestamp
            )
            connection.execute(
                "UPDATE projects SET updated_at=? WHERE id=?", (timestamp, project_id)
            )
            return self._chat(connection, project_id, chat_id)

    def list_all_chats(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            return [
                {
                    **dict(row),
                    **self._chat_identity(connection, row["id"], row["title"]),
                    "message_count": connection.execute(
                        "SELECT COUNT(*) FROM messages WHERE chat_id=?", (row["id"],)
                    ).fetchone()[0],
                    "pin_counts": self._pin_counts(
                        connection,
                        self._scope_for_chat(connection, row["id"]),
                        row["id"],
                    ),
                }
                for row in connection.execute(
                    "SELECT c.id,CASE WHEN p.is_internal=1 THEN NULL ELSE c.project_id "
                    "END AS project_id,c.title,c.created_at,c.updated_at FROM "
                    "visible_chats c "
                    "JOIN projects p ON p.id=c.project_id "
                    "ORDER BY c.updated_at DESC,c.id"
                )
            ]

    def create_global_chat(
        self, title: str, project_id: str | None = None
    ) -> dict[str, Any]:
        timestamp = _now()
        with self._connection(write=True) as connection:
            if project_id is None:
                scope_id = self._new_private_scope(connection)
            else:
                self._project(connection, project_id)
                scope_id = project_id
            chat_id = self._insert_chat(connection, scope_id, title, timestamp)
            connection.execute(
                "UPDATE projects SET updated_at=? WHERE id=?", (timestamp, scope_id)
            )
            chat = self._chat(connection, scope_id, chat_id)
            chat["project_id"] = project_id
            return chat

    @staticmethod
    def _latest_report(connection, project_id: str, chat_id: str):
        """A failed or clarification turn must not replace a completed
        report."""
        return connection.execute(
            "SELECT id,created_at FROM visible_reports WHERE project_id=? "
            "AND chat_id=? AND stage IN ('complete','partial') "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (project_id, chat_id),
        ).fetchone()

    @staticmethod
    def _tracking_pin(connection, project_id: str, chat_id: str):
        row = connection.execute(
            "SELECT p.* FROM tracked_report_pins p JOIN visible_chats c "
            "ON c.id=p.chat_id AND c.project_id=p.project_id "
            "WHERE p.project_id=? AND p.chat_id=?",
            (project_id, chat_id),
        ).fetchone()
        if row is None:
            return None
        pin = dict(row)
        latest = WorkspaceStore._latest_report(connection, project_id, chat_id)
        pin["mode"] = "latest"
        pin["report_id"] = latest["id"] if latest else None
        if latest:
            pin["updated_at"] = max(pin["updated_at"], latest["created_at"])
        return pin

    @staticmethod
    def _snapshot_pin(connection, project_id: str, report_id: str, chat_id: str):
        row = connection.execute(
            "SELECT i.id,p.created_at,i.updated_at FROM report_pins p "
            "JOIN report_pin_identities i ON i.project_id=p.project_id "
            "AND i.report_id=p.report_id WHERE p.project_id=? AND p.report_id=?",
            (project_id, report_id),
        ).fetchone()
        if row is None:
            return None
        return {
            **dict(row),
            "project_id": project_id,
            "mode": "snapshot",
            "chat_id": chat_id,
            "report_id": report_id,
        }

    @staticmethod
    def _reports(connection, project_id: str, chat_id=None, *, pinned=False):
        query = (
            "SELECT r.*, EXISTS(SELECT 1 FROM report_pins p "
            "WHERE p.project_id=r.project_id AND p.report_id=r.id) AS pinned "
            "FROM visible_reports r WHERE r.project_id=?"
        )
        arguments = [project_id]
        if chat_id is not None:
            query += " AND r.chat_id=?"
            arguments.append(chat_id)
        if pinned:
            query += (
                " AND (EXISTS(SELECT 1 FROM report_pins p WHERE "
                "p.project_id=r.project_id AND p.report_id=r.id) OR "
                "EXISTS(SELECT 1 FROM tracked_report_pins p WHERE "
                "p.project_id=r.project_id AND p.chat_id=r.chat_id "
                "AND r.id=(SELECT v.id FROM visible_reports v WHERE "
                "v.project_id=r.project_id AND v.chat_id=r.chat_id "
                "AND v.stage IN ('complete','partial') "
                "ORDER BY v.created_at DESC,v.id DESC LIMIT 1)))"
            )
        query += " ORDER BY r.created_at,r.id"
        reports = []
        latest_by_chat = {}
        tracking_by_chat = {}
        for row in connection.execute(query, arguments):
            report = dict(row)
            report["project_id"] = WorkspaceStore._public_project_id(
                connection, project_id
            )
            report["pinned"] = bool(report["pinned"])
            report["snapshot_pin"] = WorkspaceStore._snapshot_pin(
                connection, project_id, report["id"], report["chat_id"]
            )
            if report["chat_id"] not in latest_by_chat:
                latest_by_chat[report["chat_id"]] = WorkspaceStore._latest_report(
                    connection, project_id, report["chat_id"]
                )
                tracking_by_chat[report["chat_id"]] = WorkspaceStore._tracking_pin(
                    connection, project_id, report["chat_id"]
                )
            latest = latest_by_chat[report["chat_id"]]
            report["latest_report_id"] = latest["id"] if latest else None
            report["tracking_pin"] = (
                tracking_by_chat[report["chat_id"]]
                if latest and latest["id"] == report["id"]
                else None
            )
            report["source_ids"] = [
                item[0]
                for item in connection.execute(
                    "SELECT source_id FROM report_sources "
                    "WHERE project_id=? AND report_id=? ORDER BY source_id",
                    (project_id, report["id"]),
                )
            ]
            run = connection.execute(
                "SELECT outcome_json FROM research_runs "
                "WHERE report_id=? AND project_id=?",
                (report["id"], project_id),
            ).fetchone()
            report["result"] = json.loads(run[0]) if run else None
            _sanitize_assessment_completion(report["result"])
            reports.append(report)
        return reports

    @staticmethod
    def _sources(connection, project_id: str, chat_id=None, *, pinned=False):
        query = (
            "SELECT s.*, EXISTS(SELECT 1 FROM source_pins p "
            "WHERE p.project_id=s.project_id AND p.source_id=s.id) AS pinned "
            "FROM visible_sources s WHERE s.project_id=?"
        )
        arguments = [project_id]
        if chat_id is not None:
            query += (
                " AND (EXISTS(SELECT 1 FROM chat_sources c WHERE "
                "c.project_id=s.project_id AND c.source_id=s.id AND c.chat_id=?) "
                "OR EXISTS(SELECT 1 FROM report_sources rs JOIN visible_reports r "
                "ON r.id=rs.report_id AND r.project_id=rs.project_id "
                "WHERE rs.project_id=s.project_id AND rs.source_id=s.id "
                "AND r.chat_id=?))"
            )
            arguments.extend([chat_id, chat_id])
        if pinned:
            query += " AND EXISTS(SELECT 1 FROM source_pins p WHERE "
            query += "p.project_id=s.project_id AND p.source_id=s.id)"
        query += " ORDER BY s.created_at,s.id"
        sources = []
        for row in connection.execute(query, arguments):
            source = dict(row)
            annotation = connection.execute(
                "SELECT annotation_json FROM source_annotations "
                "WHERE source_id=? AND project_id=?",
                (source["id"], project_id),
            ).fetchone()
            if annotation is not None:
                source.update(json.loads(annotation[0]))
                version = connection.execute(
                    "SELECT record_key FROM source_records "
                    "WHERE source_id=? AND project_id=?",
                    (source["id"], project_id),
                ).fetchone()
                if version is not None and version[0].startswith(VERSION_PREFIX):
                    source["evidence_version"] = version[0]
            source["project_id"] = WorkspaceStore._public_project_id(
                connection, project_id
            )
            source["pinned"] = bool(source["pinned"])
            source["chat_ids"] = [
                item[0]
                for item in connection.execute(
                    "SELECT cs.chat_id FROM chat_sources cs JOIN visible_chats c "
                    "ON c.id=cs.chat_id AND c.project_id=cs.project_id "
                    "WHERE cs.project_id=? AND cs.source_id=? "
                    "UNION SELECT r.chat_id FROM report_sources rs JOIN "
                    "visible_reports r "
                    "ON r.id=rs.report_id AND r.project_id=rs.project_id "
                    "WHERE rs.project_id=? AND rs.source_id=? ORDER BY chat_id",
                    (project_id, source["id"], project_id, source["id"]),
                )
            ]
            source["report_ids"] = [
                item[0]
                for item in connection.execute(
                    "SELECT rs.report_id FROM report_sources rs JOIN visible_reports r "
                    "ON r.id=rs.report_id AND r.project_id=rs.project_id "
                    "WHERE rs.project_id=? AND rs.source_id=? ORDER BY rs.report_id",
                    (project_id, source["id"]),
                )
            ]
            sources.append(source)
        return sources

    def _detail(self, connection, project_id: str, chat_id: str):
        chat = self._chat(connection, project_id, chat_id)
        chat["project_id"] = self._public_project_id(connection, project_id)
        messages = [
            dict(row)
            for row in connection.execute(
                "SELECT m.id,m.chat_id,m.role,m.content,m.created_at,"
                "r.id AS report_id, "
                "i.intake_json, d.diagnostics_json "
                "FROM messages m LEFT JOIN reports r ON r.message_id=m.id "
                "AND r.project_id=m.project_id "
                "LEFT JOIN message_intakes i ON i.message_id=m.id "
                "LEFT JOIN message_intake_diagnostics d ON d.message_id=m.id "
                "WHERE m.project_id=? AND m.chat_id=? ORDER BY m.created_at,m.rowid",
                (project_id, chat_id),
            )
        ]
        from labcat.intake import validate_intake
        from labcat.intake_diagnostics import validate_intake_diagnostics

        for message in messages:
            saved_intake = message.pop("intake_json")
            diagnostics = message.pop("diagnostics_json")
            if saved_intake is not None:
                try:
                    message["intake"] = validate_intake(json.loads(saved_intake))
                    if diagnostics is not None:
                        message["execution_diagnostics"] = validate_intake_diagnostics(
                            json.loads(diagnostics)
                        )
                except (ValueError, TypeError, RecursionError) as error:
                    raise sqlite3.DatabaseError(
                        "Stored intake metadata is invalid."
                    ) from error
        return {
            "chat": chat,
            "report_tracking": self._tracking_pin(connection, project_id, chat_id),
            "messages": messages,
            "reports": self._reports(connection, project_id, chat_id),
            "sources": self._sources(connection, project_id, chat_id),
        }

    def get_chat(self, project_id: str, chat_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            self._project(connection, project_id)
            return self._detail(connection, project_id, chat_id)

    def get_global_chat(self, chat_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            scope_id = self._scope_for_chat(connection, chat_id)
            return self._detail(connection, scope_id, chat_id)

    def append_message(
        self, project_id: str, chat_id: str, content: str, config: AppConfig
    ) -> dict[str, Any]:
        with self._connection(write=True) as connection:
            self._project(connection, project_id)
            return self._append_exchange(
                connection, project_id, chat_id, content, config
            )

    def append_global_message(
        self, chat_id: str, content: str, config: AppConfig
    ) -> dict[str, Any]:
        with self._connection(write=True) as connection:
            scope_id = self._scope_for_chat(connection, chat_id)
            return self._append_exchange(connection, scope_id, chat_id, content, config)

    def _append_exchange(self, connection, project_id, chat_id, content, config):
        """Atomically save context and an honest response; never extract
        its facts."""
        timestamp = _now()
        user_id, assistant_id, report_id = (uuid4().hex for _ in range(3))
        response = (
            "Your request has been saved in this chat. Scientific search, evidence "
            "retrieval, ranking, and model connections are not implemented yet. "
            "No candidate materials or scientific claims have been generated. "
            "The report records the current application capabilities and limitations."
        )
        pi_summary = render_report(config, "pi")
        technical_audit = render_report(config, "audit")
        # The caller owns the transaction, including the scope lookup and writes.
        self._chat(connection, project_id, chat_id)
        self._name_first_prompt(connection, project_id, chat_id, content)
        connection.executemany(
            "INSERT INTO messages VALUES (?,?,?,?,?,?)",
            [
                (user_id, project_id, chat_id, "user", content, timestamp),
                (
                    assistant_id,
                    project_id,
                    chat_id,
                    "assistant",
                    response,
                    timestamp,
                ),
            ],
        )
        connection.execute(
            "INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?)",
            (
                report_id,
                project_id,
                chat_id,
                assistant_id,
                "Research request: framework status",
                "scaffold",
                pi_summary,
                technical_audit,
                timestamp,
            ),
        )
        connection.execute(
            "UPDATE chats SET updated_at=? WHERE id=? AND project_id=?",
            (timestamp, chat_id, project_id),
        )
        connection.execute(
            "UPDATE projects SET updated_at=? WHERE id=?", (timestamp, project_id)
        )
        return self._detail(connection, project_id, chat_id)

    def name_submitted_chat(self, chat_id: str, content: str, project_id=None):
        """Persist a first prompt's navigation title before external
        research."""
        if not isinstance(content, str) or not content.strip() or len(content) > 20000:
            raise ValueError("Provide a bounded, nonempty prompt.")
        with self._connection(write=True) as connection:
            scope = self._scope_for_chat(connection, chat_id)
            if project_id is not None:
                self._project(connection, project_id)
                if scope != project_id:
                    raise WorkspaceNotFound("Workspace item not found.")
            if self._name_first_prompt(connection, scope, chat_id, content):
                timestamp = _now()
                connection.execute(
                    "UPDATE chats SET updated_at=? WHERE id=?", (timestamp, chat_id)
                )
                connection.execute(
                    "UPDATE projects SET updated_at=? WHERE id=?", (timestamp, scope)
                )

    def visible_chat_ids(self, chat_ids):
        """Filter a bounded server-owned run snapshot without reading
        transcripts."""
        if (
            not isinstance(chat_ids, list)
            or len(chat_ids) > 256
            or any(not isinstance(identifier, str) for identifier in chat_ids)
        ):
            raise ValueError("Provide a bounded list of chat IDs.")
        if not chat_ids:
            return set()
        with self._connection() as connection:
            placeholders = ",".join("?" for _ in chat_ids)
            return {
                row[0]
                for row in connection.execute(
                    f"SELECT id FROM visible_chats WHERE id IN ({placeholders})",
                    chat_ids,
                )
            }

    def research_inputs(self, chat_id: str, project_id: str | None = None):
        """Read only this chat/project before any external planning or
        retrieval."""
        with self._connection() as connection:
            scope = self._scope_for_chat(connection, chat_id)
            public_project = self._public_project_id(connection, scope)
            if project_id is not None:
                self._project(connection, project_id)
                if public_project != project_id:
                    raise WorkspaceNotFound("Workspace item not found.")
            detail = self._detail(connection, scope, chat_id)
            if public_project is not None:
                context = self.context(public_project)
            else:
                context = {
                    "messages": [],
                    "reports": [],
                    "sources": [],
                    "boundaries": {"user_context_is_evidence": False},
                }
            context = self._active_chat_context(connection, scope, detail, context)
            # Intake may use only this conversation's bounded user preferences,
            # never other project chats, assistant prose, report text or sources.
            from labcat.intake import harmful_manufacture
            from labcat.science import request_violation

            intake_messages = []
            recent_user_indices = [
                index
                for index, item in enumerate(detail["messages"])
                if item["role"] == "user"
            ][-4:]
            for index in recent_user_indices:
                item = detail["messages"][index]
                next_message = detail["messages"][index + 1 : index + 2]
                prior_intake = next_message[0].get("intake", {}) if next_message else {}
                violation = request_violation(item["content"])
                refused = bool(violation) or prior_intake.get("status") == "refused"
                reason = (
                    (
                        "harmful_manufacture"
                        if harmful_manufacture(item["content"])
                        else "research_boundary"
                    )
                    if violation
                    else prior_intake.get("reason_code")
                )
                intake_messages.append(
                    {
                        "role": "user",
                        "content": item["content"][:500],
                        "refused": refused,
                        "reason_code": reason,
                    }
                )
            context["intake_messages"] = intake_messages[-4:]
            return scope, context

    @staticmethod
    def _active_chat_context(connection, scope, detail, context):
        """Prioritize the active conversation before downstream model
        truncation.

        Saved report prose, account-local source identities and project
        pins are planning hints only. Retrieval must revalidate public
        evidence through an approved adapter; no scientific record is
        copied into a new report here.
        """
        chat_id = detail["chat"]["id"]
        context["project_pins"] = {
            "reports": [
                {
                    "id": report["id"],
                    "chat_id": report["chat_id"],
                    "title": report["title"][:120],
                    "pin": report.get("pin"),
                    "is_evidence": False,
                }
                for report in context.get("reports", [])
            ],
            "sources": [
                {
                    "id": source["id"],
                    "title": source["title"][:120],
                    "is_evidence": False,
                }
                for source in context.get("sources", [])
                if source["access_scope"] == "public"
            ],
            "is_evidence": False,
        }
        active_messages = [
            {
                "id": item["id"],
                "chat_id": chat_id,
                "role": item["role"],
                "content": item["content"][:1000],
                "content_truncated": len(item["content"]) > 1000,
                "is_evidence": False,
                "origin": "user_input" if item["role"] == "user" else "saved_response",
            }
            for item in detail["messages"][-20:]
        ]
        project_messages = [
            item
            for item in context.get("messages", [])
            if item.get("chat_id") != chat_id
        ]
        context["messages"] = (project_messages + active_messages)[
            -CONTEXT_LIMITS["messages"] :
        ]
        # Preserve priority at models.bounded_context's final last-ten boundary.
        context["chats"] = [
            item for item in context.get("chats", []) if item.get("id") != chat_id
        ][-(CONTEXT_LIMITS["chats"] - 1) :] + [detail["chat"]]
        latest = next(
            (
                report
                for report in reversed(detail["reports"])
                if report["stage"] in {"complete", "partial"}
            ),
            None,
        )
        selected_reports = [
            report
            for report in context.get("reports", [])
            if report["chat_id"] != chat_id
        ]
        if latest:
            active_report = {
                key: value for key, value in latest.items() if key != "result"
            }
            active_report["is_evidence"] = False
            active_report["pi_summary"] = active_report["pi_summary"][:1500]
            active_report["technical_audit"] = active_report["technical_audit"][:4000]
            active_report["source_ids"] = active_report["source_ids"][:100]
            selected_reports.append(active_report)
        context["reports"] = selected_reports[-CONTEXT_LIMITS["reports"] :]
        latest_source_ids = set(latest["source_ids"]) if latest else set()
        verified_sources = [
            source
            for source in detail["sources"]
            if source["provenance_status"] == "verified"
            and source["access_scope"] == "public"
        ]
        # Latest-report material sources win the last-items model budget, ahead
        # of an accumulated collection of background references from older turns.
        active_sources = sorted(
            verified_sources,
            key=lambda source: (
                source["id"] in latest_source_ids,
                source.get("kind") != "discovery_reference",
            ),
        )[-CONTEXT_LIMITS["sources"] :]
        active_ids = {source["id"] for source in active_sources}
        selected_sources = [
            source
            for source in context.get("sources", [])
            if source["id"] not in active_ids and source["access_scope"] == "public"
        ]
        for source in active_sources:
            item = {
                key: source[key]
                for key in (
                    "id",
                    "title",
                    "url",
                    "source_name",
                    "access_scope",
                    "provenance_status",
                    "chat_ids",
                    "report_ids",
                )
            }
            for key, limit in (
                ("title", 300),
                ("url", 2048),
                ("source_name", 120),
                ("access_scope", 80),
                ("chat_ids", 100),
                ("report_ids", 100),
            ):
                item[key] = item[key][:limit]
            item["is_evidence"] = False
            item["reuse_requires_adapter_validation"] = True
            selected_sources.append(item)
        for source in selected_sources:
            source["is_evidence"] = False
            source["reuse_requires_adapter_validation"] = True
        context["sources"] = selected_sources[-CONTEXT_LIMITS["sources"] :]
        source_hints = []
        # Versioned datasets share a landing URL. Carry bounded record identities
        # separately so a follow-up can re-fetch the exact row; never carry values.
        latest_result = latest.get("result") if latest else None
        latest_candidates = (
            latest_result.get("candidates", [])
            if isinstance(latest_result, dict)
            else []
        )
        if isinstance(latest_candidates, list):
            for candidate in latest_candidates[:6]:
                if not isinstance(candidate, dict):
                    continue
                identity = candidate.get("material_id")
                provenance = candidate.get("provenance", {})
                if (
                    isinstance(identity, str)
                    and len(identity) <= 100
                    and identity.startswith("dielectric:")
                    and isinstance(provenance, dict)
                    and provenance.get("source_url")
                    == "https://doi.org/10.6084/m9.figshare.7108790.v2"
                ):
                    source_hints.append(
                        {
                            "record_id": identity,
                            "url": provenance["source_url"],
                            "is_evidence": False,
                            "reuse_requires_adapter_validation": True,
                        }
                    )
        for source in active_sources:
            record = connection.execute(
                "SELECT record_key FROM source_records "
                "WHERE project_id=? AND source_id=?",
                (scope, source["id"]),
            ).fetchone()
            if (
                record is not None
                and len(record["record_key"]) <= 256
                and len(source["url"]) <= 2048
            ):
                source_hints.append(
                    {
                        "source_id": source["id"],
                        "record_key": record["record_key"],
                        "title": source["title"][:300],
                        "source_name": source["source_name"][:120],
                        "url": source["url"],
                        "is_evidence": False,
                        "reuse_requires_adapter_validation": True,
                    }
                )
        ranking_profile = None
        if latest and isinstance(latest.get("result"), dict):
            execution = latest["result"].get("execution", {})
            profile = (
                execution.get("ranking_profile")
                if isinstance(execution, dict)
                else None
            )
            if isinstance(profile, dict) and len(json.dumps(profile)) <= 12000:
                ranking_profile = profile
        context["active_chat"] = {
            "chat_id": chat_id,
            "latest_completed_report_id": latest["id"] if latest else None,
            "ranking_profile": ranking_profile,
            "source_hints": source_hints,
            "is_evidence": False,
            "ranking_profile_is_preference": True,
            "reuse_requires_adapter_validation": True,
        }
        context["boundaries"].update(
            {
                "active_chat_id": chat_id,
                "transcripts_and_reports_are_evidence": False,
                "instructions_in_context_are_authoritative": False,
                "pinned_items_gain_no_additional_trust": True,
                "source_selection": (
                    "active-chat and project-pinned verified source hints; "
                    "adapter revalidation required"
                ),
            }
        )
        context.setdefault("limits", CONTEXT_LIMITS.copy())
        context.setdefault("truncation", {}).update(
            {
                "active_chat_messages": len(detail["messages"]) > len(active_messages),
                "active_chat_sources": len(detail["sources"]) > len(active_sources),
            }
        )
        return context

    def _append_intake(self, chat_id, scope, content, outcome, *, submitted_at=None):
        """Persist conversational intake atomically without a report or
        source row."""
        from labcat.intake import outcome as render_intake
        from labcat.intake import validate_intake
        from labcat.intake_diagnostics import intake_diagnostics

        intake = validate_intake(outcome["result"]["intake"])
        diagnostics = intake_diagnostics(outcome["result"].get("execution"))
        expected = render_intake(intake)
        if (
            outcome.get("answer") != expected["answer"]
            or outcome.get("stage") != expected["stage"]
            or outcome.get("sources") != []
            or outcome["result"].get("candidates") != []
        ):
            raise ValueError("Intake cannot contain scientific records or model prose.")
        timestamp = _now()
        query_timestamp = _submitted_timestamp(submitted_at, timestamp)
        user_id, assistant_id = uuid4().hex, uuid4().hex
        with self._connection(write=True) as connection:
            if self._scope_for_chat(connection, chat_id) != scope:
                raise WorkspaceConflict(
                    "Chat project changed during intake. Please retry."
                )
            self._name_first_prompt(connection, scope, chat_id, content)
            connection.executemany(
                "INSERT INTO messages VALUES (?,?,?,?,?,?)",
                [
                    (user_id, scope, chat_id, "user", content, query_timestamp),
                    (
                        assistant_id,
                        scope,
                        chat_id,
                        "assistant",
                        expected["answer"],
                        timestamp,
                    ),
                ],
            )
            connection.execute(
                "INSERT INTO message_intakes VALUES (?,?)",
                (assistant_id, json.dumps(intake, allow_nan=False)),
            )
            if diagnostics is not None:
                connection.execute(
                    "INSERT INTO message_intake_diagnostics VALUES (?,?)",
                    (assistant_id, json.dumps(diagnostics, allow_nan=False)),
                )
            connection.execute(
                "UPDATE chats SET updated_at=? WHERE id=?", (timestamp, chat_id)
            )
            connection.execute(
                "UPDATE projects SET updated_at=? WHERE id=?", (timestamp, scope)
            )
            return self._detail(connection, scope, chat_id)

    def append_research(
        self,
        chat_id: str,
        scope: str,
        content: str,
        outcome: dict,
        *,
        submitted_at: str | None = None,
    ):
        """Save an outcome and its server-owned query time, never client
        metadata."""
        intake = outcome.get("result", {}).get("intake")
        if isinstance(intake, dict) and intake.get("status") != "accepted":
            return self._append_intake(
                chat_id, scope, content, outcome, submitted_at=submitted_at
            )
        if outcome.get("stage") not in {"complete", "partial", "blocked"}:
            raise ValueError("Research returned an unsupported stage.")
        for field in ("answer", "pi_summary", "technical_audit"):
            if not isinstance(outcome.get(field), str):
                raise ValueError("Research returned an invalid report.")
        sources = outcome.get("sources", [])
        # Eight public indexes (up to 80 references), 12 shortlist records,
        # 36 comparison records, methodology and six article follow-ups must
        # coexist without silently dropping either side of a discrepancy.
        # This bounds stored citations only; retrieval/tool budgets are unchanged.
        if not isinstance(sources, list) or len(sources) > 144:
            raise ValueError("Research returned an invalid source set.")
        # Encoding here rejects non-finite scientific values before the transaction.
        result = json.dumps(outcome.get("result", {}), allow_nan=False)
        timestamp = _now()
        query_timestamp = _submitted_timestamp(submitted_at, timestamp)
        user_id, assistant_id, report_id = (uuid4().hex for _ in range(3))
        with self._connection(write=True) as connection:
            if self._scope_for_chat(connection, chat_id) != scope:
                raise WorkspaceConflict(
                    "Chat project changed during research. "
                    "Please retry in its current project."
                )
            self._name_first_prompt(connection, scope, chat_id, content)
            connection.executemany(
                "INSERT INTO messages VALUES (?,?,?,?,?,?)",
                [
                    (user_id, scope, chat_id, "user", content, query_timestamp),
                    (
                        assistant_id,
                        scope,
                        chat_id,
                        "assistant",
                        outcome["answer"],
                        timestamp,
                    ),
                ],
            )
            connection.execute(
                "INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    report_id,
                    scope,
                    chat_id,
                    assistant_id,
                    (
                        "Public reference discovery"
                        if outcome.get("result", {}).get("public_discovery")
                        and not outcome.get("result", {}).get("candidates")
                        and not outcome.get("result", {})
                        .get("literature_evaluation", {})
                        .get("ranked_candidates")
                        else "Materials screening report"
                    ),
                    outcome["stage"],
                    outcome["pi_summary"],
                    outcome["technical_audit"],
                    timestamp,
                ),
            )
            connection.execute(
                "INSERT INTO research_runs VALUES (?,?,?)", (report_id, scope, result)
            )
            for source in sources:
                required = (
                    "title",
                    "url",
                    "source_name",
                    "access_scope",
                    "provenance_status",
                )
                if not isinstance(source, dict) or any(
                    not isinstance(source.get(key), str) for key in required
                ):
                    raise ValueError("Research returned invalid source metadata.")
                if (
                    source["access_scope"] != "public"
                    or source["provenance_status"] != "verified"
                ):
                    raise ValueError(
                        "Only verified public adapter sources may be retained."
                    )
                annotation = None
                if source.get("kind") == "discovery_reference":
                    annotation = discovery_annotation(source)
                    record_key = discovery_version(source)
                else:
                    identity = {
                        key: source[key] for key in ("url", "source_name", "title")
                    }
                    record_key = hashlib.sha256(
                        json.dumps(identity, sort_keys=True).encode()
                    ).hexdigest()
                existing = connection.execute(
                    "SELECT source_id FROM source_records "
                    "WHERE project_id=? AND record_key=?",
                    (scope, record_key),
                ).fetchone()
                if existing:
                    source_id = existing[0]
                else:
                    source_id = uuid4().hex
                    connection.execute(
                        "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
                        (
                            source_id,
                            scope,
                            source["title"],
                            source["url"],
                            source["source_name"],
                            "public",
                            "verified",
                            timestamp,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO source_records VALUES (?,?,?)",
                        (scope, source_id, record_key),
                    )
                connection.execute(
                    "INSERT OR IGNORE INTO chat_sources VALUES (?,?,?)",
                    (scope, chat_id, source_id),
                )
                if annotation is not None:
                    serialized_annotation = json.dumps(annotation, allow_nan=False)
                    connection.execute(
                        "INSERT OR IGNORE INTO source_annotations VALUES (?,?,?)",
                        (source_id, scope, serialized_annotation),
                    )
                connection.execute(
                    "INSERT OR IGNORE INTO report_sources VALUES (?,?,?)",
                    (scope, report_id, source_id),
                )
            connection.execute(
                "UPDATE chats SET updated_at=? WHERE id=?", (timestamp, chat_id)
            )
            connection.execute(
                "UPDATE projects SET updated_at=? WHERE id=?", (timestamp, scope)
            )
            return self._detail(connection, scope, chat_id)

    def move_chat(self, chat_id: str, project_id: str | None) -> dict[str, Any]:
        return self.update_chat(chat_id, project_id=project_id)

    def update_chat(
        self, chat_id: str, *, project_id=_UNCHANGED, title=None
    ) -> dict[str, Any]:
        """Move history atomically; preserve other chats' sources and
        source pins."""
        with self._connection(write=True) as connection:
            old_scope = self._scope_for_chat(connection, chat_id)
            old_project = self._public_project_id(connection, old_scope)
            if project_id is _UNCHANGED:
                project_id = old_project
            if project_id is not None:
                self._project(connection, project_id)
            if title is not None:
                connection.execute(
                    "UPDATE chats SET title=?,updated_at=? WHERE id=?",
                    (title, _now(), chat_id),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO manual_chat_titles VALUES (?)", (chat_id,)
                )
            if old_project == project_id:
                return self._detail(connection, old_scope, chat_id)
            new_scope = (
                project_id
                if project_id is not None
                else self._new_private_scope(connection)
            )
            # All composite foreign keys are checked again at transaction commit.
            connection.execute("PRAGMA defer_foreign_keys=ON")
            chat_links = connection.execute(
                "SELECT source_id FROM chat_sources WHERE project_id=? AND chat_id=?",
                (old_scope, chat_id),
            ).fetchall()
            report_links = connection.execute(
                "SELECT rs.report_id,rs.source_id FROM report_sources rs "
                "JOIN reports r ON r.id=rs.report_id AND r.project_id=rs.project_id "
                "WHERE r.project_id=? AND r.chat_id=?",
                (old_scope, chat_id),
            ).fetchall()
            source_ids = {row[0] for row in chat_links} | {
                row[1] for row in report_links
            }
            copied_sources = {}
            for source_id in sorted(source_ids):
                identity = connection.execute(
                    "SELECT record_key FROM source_records "
                    "WHERE project_id=? AND source_id=?",
                    (old_scope, source_id),
                ).fetchone()
                existing = (
                    connection.execute(
                        "SELECT source_id FROM source_records "
                        "WHERE project_id=? AND record_key=?",
                        (new_scope, identity[0]),
                    ).fetchone()
                    if identity
                    else None
                )
                if existing:
                    copied_sources[source_id] = existing[0]
                    continue
                copy_id = uuid4().hex
                connection.execute(
                    "INSERT INTO sources "
                    "SELECT ?,?,title,url,source_name,access_scope,provenance_status,"
                    "created_at FROM sources WHERE id=? AND project_id=?",
                    (copy_id, new_scope, source_id, old_scope),
                )
                copied_sources[source_id] = copy_id
                connection.execute(
                    "INSERT INTO source_annotations "
                    "SELECT ?,?,annotation_json FROM source_annotations "
                    "WHERE source_id=? AND project_id=?",
                    (copy_id, new_scope, source_id, old_scope),
                )
                if identity:
                    connection.execute(
                        "INSERT INTO source_records VALUES (?,?,?)",
                        (new_scope, copy_id, identity[0]),
                    )
            # Pins stay in their original project. Report pins cannot outlive a move;
            # source pins continue referring to the original source records there.
            connection.execute(
                "DELETE FROM report_pins WHERE project_id=? AND report_id IN "
                "(SELECT id FROM reports WHERE project_id=? AND chat_id=?)",
                (old_scope, old_scope, chat_id),
            )
            connection.execute(
                "DELETE FROM tracked_report_pins WHERE project_id=? AND chat_id=?",
                (old_scope, chat_id),
            )
            connection.execute(
                "DELETE FROM report_sources WHERE project_id=? AND report_id IN "
                "(SELECT id FROM reports WHERE project_id=? AND chat_id=?)",
                (old_scope, old_scope, chat_id),
            )
            connection.execute(
                "DELETE FROM chat_sources WHERE project_id=? AND chat_id=?",
                (old_scope, chat_id),
            )
            timestamp = _now()
            connection.execute(
                "UPDATE chats SET project_id=?,updated_at=? WHERE id=?",
                (new_scope, timestamp, chat_id),
            )
            connection.execute(
                "UPDATE messages SET project_id=? WHERE chat_id=?",
                (new_scope, chat_id),
            )
            connection.execute(
                "UPDATE research_runs SET project_id=? WHERE report_id IN "
                "(SELECT id FROM reports WHERE chat_id=?)",
                (new_scope, chat_id),
            )
            connection.execute(
                "UPDATE reports SET project_id=? WHERE chat_id=?",
                (new_scope, chat_id),
            )
            connection.executemany(
                "INSERT INTO chat_sources VALUES (?,?,?)",
                [(new_scope, chat_id, copied_sources[row[0]]) for row in chat_links],
            )
            connection.executemany(
                "INSERT INTO report_sources VALUES (?,?,?)",
                [(new_scope, row[0], copied_sources[row[1]]) for row in report_links],
            )
            connection.execute(
                "UPDATE projects SET updated_at=? WHERE id IN (?,?)",
                (timestamp, old_scope, new_scope),
            )
            return self._detail(connection, new_scope, chat_id)

    def contents(self, project_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            self._project(connection, project_id)
            return {
                "chats": self._chats(connection, project_id),
                "reports": self._pinned_reports(connection, project_id),
                "sources": self._sources(connection, project_id, pinned=True),
            }

    @staticmethod
    def _pinned_reports(connection, project_id: str):
        """One card per pin; a snapshot and a live pin may share a
        revision."""
        pinned_reports = []
        for report in WorkspaceStore._reports(connection, project_id, pinned=True):
            for pin in (report["snapshot_pin"], report["tracking_pin"]):
                if pin is not None:
                    pinned_reports.append({**report, "pin": pin})
        return sorted(
            pinned_reports,
            key=lambda report: (report["pin"]["created_at"], report["pin"]["id"]),
        )

    def set_report_tracking(
        self, project_id: str, chat_id: str, *, tracking: bool = True
    ):
        """Follow future completed revisions without changing saved
        snapshots."""
        with self._connection(write=True) as connection:
            self._project(connection, project_id)
            self._chat(connection, project_id, chat_id)
            if tracking:
                if self._latest_report(connection, project_id, chat_id) is None:
                    raise WorkspacePinConflict(
                        "Generate a completed report before tracking this chat."
                    )
                timestamp = _now()
                connection.execute(
                    "INSERT OR IGNORE INTO tracked_report_pins VALUES (?,?,?,?,?)",
                    (uuid4().hex, project_id, chat_id, timestamp, timestamp),
                )
            else:
                connection.execute(
                    "DELETE FROM tracked_report_pins WHERE project_id=? AND chat_id=?",
                    (project_id, chat_id),
                )
            return self._tracking_pin(connection, project_id, chat_id)

    def replace_report_snapshot(
        self,
        project_id: str,
        pin_id: str,
        *,
        expected_report_id: str,
        report_id: str,
    ):
        """Explicit compare-and-swap changes only a pin's immutable
        revision."""
        with self._connection(write=True) as connection:
            self._project(connection, project_id)
            current = connection.execute(
                "SELECT i.*,p.created_at,r.chat_id FROM report_pin_identities i "
                "JOIN report_pins p ON p.project_id=i.project_id "
                "AND p.report_id=i.report_id "
                "JOIN visible_reports r ON r.project_id=i.project_id "
                "AND r.id=i.report_id "
                "WHERE i.id=? AND i.project_id=?",
                (pin_id, project_id),
            ).fetchone()
            if current is None:
                raise WorkspaceNotFound("Workspace item not found.")
            if current["report_id"] != expected_report_id:
                raise WorkspacePinConflict(
                    "This snapshot changed. Reload project contents before updating it."
                )
            target = connection.execute(
                "SELECT id FROM visible_reports WHERE project_id=? AND chat_id=? "
                "AND id=? AND stage IN ('complete','partial')",
                (project_id, current["chat_id"], report_id),
            ).fetchone()
            if target is None:
                raise WorkspaceNotFound("Workspace item not found.")
            if report_id == expected_report_id:
                return self._snapshot_pin(
                    connection, project_id, report_id, current["chat_id"]
                )
            duplicate = connection.execute(
                "SELECT 1 FROM report_pins WHERE project_id=? AND report_id=?",
                (project_id, report_id),
            ).fetchone()
            if duplicate:
                raise WorkspacePinConflict(
                    "That report revision already has a snapshot in this project."
                )
            # Deleting the old pin cascades its identity inside this transaction.
            # Reinsert the same identity and original pin date for the new target.
            connection.execute(
                "DELETE FROM report_pins WHERE project_id=? AND report_id=?",
                (project_id, expected_report_id),
            )
            connection.execute(
                "INSERT INTO report_pins VALUES (?,?,?)",
                (project_id, report_id, current["created_at"]),
            )
            connection.execute(
                "INSERT INTO report_pin_identities VALUES (?,?,?,?)",
                (pin_id, project_id, report_id, _now()),
            )
            return self._snapshot_pin(
                connection, project_id, report_id, current["chat_id"]
            )

    def set_pin(
        self, project_id: str, kind: str, target_id: str, *, pinned: bool = True
    ) -> dict[str, str]:
        # Table names come only from this fixed mapping, never request interpolation.
        tables = {
            "report": ("visible_reports", "report_pins", "report_id"),
            "source": ("visible_sources", "source_pins", "source_id"),
        }
        if kind not in tables:
            raise ValueError("Unsupported pin kind.")
        table, pin_table, column = tables[kind]
        with self._connection(write=True) as connection:
            self._project(connection, project_id)
            row = connection.execute(
                f"SELECT id FROM {table} WHERE id=? AND project_id=?",
                (target_id, project_id),
            ).fetchone()
            if row is None:
                raise WorkspaceNotFound("Workspace item not found.")
            if pinned:
                connection.execute(
                    f"INSERT OR IGNORE INTO {pin_table} VALUES (?,?,?)",
                    (project_id, target_id, _now()),
                )
                if kind == "report":
                    connection.execute(
                        "INSERT OR IGNORE INTO report_pin_identities "
                        "SELECT ?,project_id,report_id,created_at FROM report_pins "
                        "WHERE project_id=? AND report_id=?",
                        (uuid4().hex, project_id, target_id),
                    )
            else:
                connection.execute(
                    f"DELETE FROM {pin_table} WHERE project_id=? AND {column}=?",
                    (project_id, target_id),
                )
        return {"kind": kind, "target_id": target_id, "project_id": project_id}

    def context(self, project_id: str) -> dict[str, Any]:
        """Bound reusable context, retaining its trust labels and
        project boundary."""
        with self._connection() as connection:
            project = self._project(connection, project_id)
            chats = self._chats(connection, project_id)
            reports = self._pinned_reports(connection, project_id)
            sources = [
                source
                for source in self._sources(connection, project_id, pinned=True)
                if source["provenance_status"] == "verified"
            ]
            message_count = connection.execute(
                "SELECT COUNT(*) FROM messages m WHERE project_id=? AND EXISTS "
                "(SELECT 1 FROM visible_chats c WHERE c.id=m.chat_id AND "
                "c.project_id=m.project_id)",
                (project_id,),
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT id,chat_id,role,content,created_at FROM messages "
                "WHERE project_id=? AND EXISTS(SELECT 1 FROM visible_chats c "
                "WHERE c.id=messages.chat_id AND c.project_id=messages.project_id) "
                "ORDER BY created_at DESC,rowid DESC LIMIT ?",
                (project_id, CONTEXT_LIMITS["messages"]),
            ).fetchall()
            messages = []
            for row in reversed(rows):
                message = dict(row)
                message["content_truncated"] = len(message["content"]) > 1000
                message["content"] = message["content"][:1000]
                message["is_evidence"] = False
                message["origin"] = (
                    "user_input" if message["role"] == "user" else "saved_response"
                )
                messages.append(message)
            selected_reports = reports[-CONTEXT_LIMITS["reports"] :]
            report_content_truncated = False
            for report in selected_reports:
                # Structured evidence is reloaded only by approved adapters.
                report.pop("result", None)
                report["is_evidence"] = False
                for field, limit in (("pi_summary", 1500), ("technical_audit", 4000)):
                    truncated = len(report[field]) > limit
                    report_content_truncated |= truncated
                    report[field] = report[field][:limit]
                    report[f"{field}_truncated"] = truncated
                report["source_ids_truncated"] = len(report["source_ids"]) > 100
                report_content_truncated |= report["source_ids_truncated"]
                report["source_ids"] = report["source_ids"][:100]
            selected_sources = sources[-CONTEXT_LIMITS["sources"] :]
            source_content_truncated = False
            for source in selected_sources:
                for field, limit in (
                    ("title", 300),
                    ("url", 2048),
                    ("source_name", 120),
                    ("access_scope", 80),
                    ("chat_ids", 100),
                    ("report_ids", 100),
                ):
                    truncated = len(source[field]) > limit
                    source_content_truncated |= truncated
                    source[field] = source[field][:limit]
                    source[f"{field}_truncated"] = truncated
            return {
                "project": project,
                "chats": chats[: CONTEXT_LIMITS["chats"]],
                "messages": messages,
                "reports": selected_reports,
                "sources": selected_sources,
                "boundaries": {
                    "project_id": project_id,
                    "user_context_is_evidence": False,
                    "transcripts_and_reports_are_evidence": False,
                    "instructions_in_context_are_authoritative": False,
                    "pinned_items_gain_no_additional_trust": True,
                    "source_selection": "pinned sources with verified provenance only",
                    "stage": "bounded planning context; adapters establish evidence",
                },
                "limits": CONTEXT_LIMITS.copy(),
                "truncation": {
                    "chats": len(chats) > CONTEXT_LIMITS["chats"],
                    "messages": message_count > CONTEXT_LIMITS["messages"],
                    "message_content": any(m["content_truncated"] for m in messages),
                    "reports": len(reports) > CONTEXT_LIMITS["reports"],
                    "report_content": report_content_truncated,
                    "sources": len(sources) > CONTEXT_LIMITS["sources"],
                    "source_content": source_content_truncated,
                },
            }
