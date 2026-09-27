"""Complete PDFs from one saved chat snapshot, without research or
remote access."""

import re
from html import escape

from labcat.config import ReportLayout
from labcat.report_exports import (
    ACCENTS,
    ExportError,
    ExportUnavailable,
    _content,
    _pdf_document,
    _pdf_fonts,
    _pdf_story,
    _safe_source_url,
    _source_details,
    _source_records,
    _text,
)
from labcat.science.report_sources import report_scoped_sources
from labcat.science.reporting import citation_references

MAX_CHAT_CHARACTERS = 8_000_000
MAX_CHAT_MESSAGES = 10_000
MAX_CHAT_REPORTS = 5_000
MAX_CHAT_SOURCES = 10_000
MAX_CHAT_PAGES = 2_000
MAX_CHAT_PDF_BYTES = 64 * 1024 * 1024


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ExportError("The saved chat has an unsupported identity.")
    return value


def _string(value, maximum=300):
    if not isinstance(value, str) or len(value) > maximum:
        raise ExportError("The saved chat contains invalid text or metadata.")
    return value


def _snapshot(detail):
    """Validate all memberships before producing any part of the
    document."""
    try:
        chat = detail["chat"]
        identifier = _identity(chat["id"])
        for field in ("title", "created_at", "updated_at"):
            _string(chat[field])
        messages, reports, sources = (
            detail["messages"],
            detail["reports"],
            detail["sources"],
        )
        for rows, limit in (
            (messages, MAX_CHAT_MESSAGES),
            (reports, MAX_CHAT_REPORTS),
            (sources, MAX_CHAT_SOURCES),
        ):
            if not isinstance(rows, list):
                raise ExportError("The saved chat history is incomplete.")
            if len(rows) > limit:
                raise ExportError("The complete chat exceeds the export size limit.")
        by_message = {}
        characters = sum(
            len(chat[field]) for field in ("title", "created_at", "updated_at")
        )
        for message in messages:
            key = _identity(message["id"])
            if (
                key in by_message
                or message["chat_id"] != identifier
                or message["role"] not in {"user", "assistant"}
            ):
                raise ExportError("The saved message membership cannot be verified.")
            content = message["content"]
            if not isinstance(content, str):
                raise ExportError("The saved chat contains invalid message text.")
            characters += len(content)
            characters += len(_string(message["created_at"]))
            by_message[key] = message
        by_source = {}
        for source in sources:
            key = _string(source["id"], 128)
            if (
                not key
                or key in by_source
                or source["project_id"] != chat["project_id"]
                or not isinstance(source["chat_ids"], list)
                or identifier not in source["chat_ids"]
            ):
                raise ExportError("The saved source membership cannot be verified.")
            by_source[key] = source
        attached, seen, used_sources = {}, set(), set()
        for saved in reports:
            key = _identity(saved["id"])
            message = by_message.get(saved["message_id"])
            if (
                key in seen
                or message is None
                or message["id"] in attached
                or message["role"] != "assistant"
                or message.get("report_id") != key
                or saved["chat_id"] != identifier
                or saved["project_id"] != chat["project_id"]
                or not isinstance(saved["source_ids"], list)
                or any(not isinstance(item, str) for item in saved["source_ids"])
                or len(set(saved["source_ids"])) != len(saved["source_ids"])
            ):
                raise ExportError("The saved report membership cannot be verified.")
            scoped = [by_source[source_id] for source_id in saved["source_ids"]]
            result = saved.get("result")
            result = result if isinstance(result, dict) else {}
            # Recover only historical annotations bound to these existing source IDs.
            scoped = report_scoped_sources(result, scoped)
            report = {**saved, "sources": scoped}
            metadata, selected = _content(report, "all")
            approved = {
                source["url"]
                for source in scoped
                if source.get("access_scope") == "public"
                and source.get("provenance_status") == "verified"
                and _safe_source_url(source.get("url"))
            }
            report["references"] = [
                reference
                for reference in citation_references(result, scoped)
                if reference["url"] in approved
            ]
            characters += sum(len(_text(value)) for value in selected.values())
            characters += sum(len(value) for value in metadata.values())
            attached[message["id"]] = metadata, selected, approved, report
            used_sources.update(saved["source_ids"])
            seen.add(key)
        if any(
            message.get("report_id") is not None and message["id"] not in attached
            for message in messages
        ):
            raise ExportError("A saved report is missing from this chat history.")
        extras = []
        for key, source in by_source.items():
            if key not in used_sources:
                record = _source_records({"sources": [source]})[0]
                characters += len(_text(record))
                extras.append(record)
        if characters > MAX_CHAT_CHARACTERS:
            raise ExportError("The complete chat exceeds the export size limit.")
        return chat, messages, attached, extras
    except ExportError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        RecursionError,
        OverflowError,
    ):
        raise ExportError("The saved chat history cannot be exported safely.") from None


def render_chat_history(detail) -> tuple[bytes, str, str]:
    """Render all saved messages and report revisions from one scoped
    snapshot."""
    chat, messages, attached, extras = _snapshot(detail)
    try:
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import PageBreak, Paragraph, Spacer
        from reportlab.platypus.doctemplate import LayoutError
    except ImportError:
        raise ExportUnavailable(
            "PDF support is not installed in this deployment."
        ) from None
    _pdf_fonts()
    layout = ReportLayout()
    accent = ACCENTS[layout.accent][0]
    body = ParagraphStyle(
        "ChatBody",
        fontName="LabcatSans",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#223637"),
        spaceAfter=5,
    )
    heading = ParagraphStyle(
        "ChatHeading",
        parent=body,
        fontName="LabcatBold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor(accent),
        spaceBefore=12,
        keepWithNext=True,
    )
    title = ParagraphStyle(
        "ChatTitle",
        parent=heading,
        fontSize=23,
        leading=28,
        spaceAfter=10,
    )

    def literal(value, style=body, *, preserve_spacing=False):
        markup = escape(value)
        if preserve_spacing:
            markup = re.sub(
                r"^ +| {2,}| +$", lambda match: "&#160;" * len(match[0]), markup
            ).replace("\t", "&#160;" * 4)
        return Paragraph(markup, style)

    story = [
        literal("Labcat | Complete chat history", heading),
        literal(chat["title"] or "Untitled chat", title),
        literal("Chat: " + chat["id"]),
        literal("Created: " + chat["created_at"]),
        literal("Last saved: " + chat["updated_at"]),
        literal(f"{len(messages)} saved messages | {len(attached)} saved reports"),
        literal(
            "Messages are saved conversation text, not scientific evidence. "
            "Reports retain their saved summaries, technical views, shortlists "
            "and source records. No research or source retrieval was run "
            "for this export."
        ),
        Spacer(1, 10),
    ]
    if not messages:
        story.append(literal("No messages have been saved in this chat."))
    report_number = 0
    for number, message in enumerate(messages, 1):
        role = "User" if message["role"] == "user" else "Assistant"
        story.extend(
            [
                literal(f"Message {number} | {role}", heading),
                literal(message["created_at"]),
            ]
        )
        # Saved markup remains literal; indentation and blank lines are retained.
        # Chunk very long lines for bounded layout work; no characters are dropped.
        for line in message["content"].split("\n"):
            if not line:
                story.append(Spacer(1, body.leading))
            for offset in range(0, len(line), 4096):
                story.append(
                    literal(line[offset : offset + 4096], preserve_spacing=True)
                )
        if message["id"] in attached:
            report_number += 1
            metadata, selected, links, report = attached[message["id"]]
            try:
                report_story = _pdf_story(metadata, selected, links, layout, report)
            except ExportError:
                raise
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                raise ExportError(
                    "A saved report could not be formatted safely."
                ) from None
            story.extend(
                [
                    PageBreak(),
                    literal(f"Saved report revision {report_number}", heading),
                    *report_story,
                    PageBreak(),
                ]
            )
    if extras:
        story.append(literal("Additional saved chat sources", title))
        for number, source in enumerate(extras, 1):
            text = escape(f"{number}. {source['title']}")
            if source["url"]:
                text = f'<link href="{escape(source["url"], quote=True)}">{text}</link>'
            story.append(Paragraph(text, heading))
            story.extend(literal(line) for line in _source_details(source))
    # Avoid an empty final page after the final report's Sources section.
    if story and isinstance(story[-1], PageBreak):
        story.pop()
    try:
        payload = _pdf_document(
            story,
            layout,
            title="Labcat complete chat history",
            footer_text="Complete saved chat | messages, reports and sources",
            max_pages=MAX_CHAT_PAGES,
        )
    except ExportError:
        raise
    except (LayoutError, ValueError, TypeError, KeyError, OverflowError):
        raise ExportError(
            "The complete chat PDF could not be formatted safely."
        ) from None
    if len(payload) > MAX_CHAT_PDF_BYTES:
        raise ExportError("The complete chat exceeds the PDF file size limit.")
    return payload, "application/pdf", f"labcat-{chat['id']}-history.pdf"
