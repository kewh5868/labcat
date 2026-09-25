"""Project routes for a local single-user UI; source creation is not
exposed."""

import sqlite3
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from labcat.config import AppConfig
from labcat.credentials import ConnectionBusy, ConnectionError
from labcat.models import ModelBusy, ModelError
from labcat.onboarding import SetupRequired
from labcat.ranking_profiles import RankingProfileNotFound
from labcat.research_progress import ResearchInProgress
from labcat.source_preferences import SourceConnectionRequired
from labcat.workspace import (
    SEARCH_QUERY_LIMIT,
    SEARCH_RESULT_LIMIT,
    WorkspaceConflict,
    WorkspaceGeneralChatsConflict,
    WorkspaceNotFound,
    WorkspacePinConflict,
    WorkspaceRemovedConflict,
    WorkspaceRestoreConflict,
    WorkspaceStore,
)

Identifier = Annotated[str, Path(min_length=1, max_length=64)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectCreate(RequestModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class ChatCreate(RequestModel):
    title: str = Field(min_length=1, max_length=160)


class GlobalChatCreate(ChatCreate):
    project_id: str | None = Field(default=None, min_length=1, max_length=64)


class ChatUpdate(RequestModel):
    project_id: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set or (
            "title" in self.model_fields_set and self.title is None
        ):
            raise ValueError("Provide a title or project assignment.")
        return self


class ProjectUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("Provide a project name or description.")
        return self


class MessageCreate(RequestModel):
    content: str = Field(min_length=1, max_length=20000)
    search_reference_structures: bool | None = Field(default=None, strict=True)
    ranking_profile_id: str | None = Field(default=None, min_length=1, max_length=64)
    run_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )


class PinCreate(RequestModel):
    kind: Literal["report", "source"]
    target_id: str = Field(min_length=1, max_length=64)


class ReportSnapshotUpdate(RequestModel):
    expected_report_id: str = Field(min_length=1, max_length=64)
    report_id: str = Field(min_length=1, max_length=64)


class WorkspacePreferences(RequestModel):
    confirm_removal: bool = Field(strict=True)


class GeneralChatsClear(RequestModel):
    confirm: bool = Field(strict=True)
    snapshot: list[Annotated[str, Field(strict=True, min_length=1, max_length=64)]]

    @model_validator(mode="after")
    def require_reviewed_confirmation(self):
        if self.confirm is not True:
            raise ValueError("Clearing general chats requires explicit confirmation.")
        if len(self.snapshot) != len(set(self.snapshot)):
            raise ValueError("Provide a unique list of reviewed general-chat IDs.")
        return self


class PermanentDelete(RequestModel):
    confirm: bool = Field(strict=True)

    @model_validator(mode="after")
    def require_confirmation(self):
        if self.confirm is not True:
            raise ValueError("Permanent deletion requires explicit confirmation.")
        return self


class PermanentDeleteAll(PermanentDelete):
    snapshot: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except SetupRequired as error:
        raise HTTPException(
            409,
            {
                "code": "model_setup_required",
                "message": str(error),
                "setup_required": True,
            },
        ) from None
    except SourceConnectionRequired as error:
        raise HTTPException(
            409,
            {
                "code": "source_connection_required",
                "message": str(error),
                "setup_required": False,
            },
        ) from None
    except (ModelBusy, ConnectionBusy):
        raise HTTPException(
            409,
            {
                "code": "model_connection_busy",
                "message": (
                    "The model connection is busy. Wait for the account check "
                    "or current research to finish, then send this request again. "
                    "No model request was submitted."
                ),
                "setup_required": False,
            },
        ) from None
    except (ModelError, ConnectionError):
        raise HTTPException(
            502,
            {
                "code": "model_execution_failed",
                "message": "The model connection failed. Check Connections and retry.",
                "setup_required": False,
            },
        ) from None
    except WorkspaceNotFound as error:
        raise HTTPException(404, "Workspace item not found.") from error
    except RankingProfileNotFound as error:
        raise HTTPException(
            404, "Ranking profile not found. Choose an available profile."
        ) from error
    except WorkspaceConflict as error:
        raise HTTPException(
            409, "This chat moved during research. Please retry in its current project."
        ) from error
    except (
        WorkspaceGeneralChatsConflict,
        WorkspacePinConflict,
        WorkspaceRemovedConflict,
        ResearchInProgress,
    ) as error:
        raise HTTPException(409, str(error)) from error
    except WorkspaceRestoreConflict as error:
        raise HTTPException(
            409, "Restore the project before restoring this chat."
        ) from error
    except sqlite3.Error as error:
        raise HTTPException(
            503, "Workspace storage is unavailable. Please retry."
        ) from error


def create_router(
    store: WorkspaceStore,
    config: AppConfig,
    config_reader: Callable[[], AppConfig] | None = None,
    research_workflow=None,
) -> APIRouter:
    """The containing app must enforce its local Host/Origin
    boundary."""
    router = APIRouter(prefix="/api")

    def current_config():
        return _call(config_reader) if config_reader is not None else config

    @router.get("/workspace/search")
    def search_workspace(
        q: Annotated[str, Query(max_length=SEARCH_QUERY_LIMIT)] = "",
        limit: Annotated[int, Query(ge=1, le=SEARCH_RESULT_LIMIT)] = 20,
    ):
        return _call(store.search, q, limit)

    @router.get("/research-runs")
    def running_research():
        if research_workflow is None:
            return {"runs": []}
        runs = research_workflow.progress.running()
        visible = _call(store.visible_chat_ids, [row["chat_id"] for row in runs])
        return {"runs": [row for row in runs if row["chat_id"] in visible]}

    @router.get("/chats")
    def all_chats():
        return {"chats": _call(store.list_all_chats)}

    @router.post("/chats", status_code=201)
    def create_global_chat(request: GlobalChatCreate):
        return _call(store.create_global_chat, request.title, request.project_id)

    @router.delete("/general-chats")
    def clear_general_chats(request: GeneralChatsClear):
        if research_workflow is not None and any(
            research_workflow.progress.busy(chat_id) for chat_id in request.snapshot
        ):
            raise HTTPException(
                409,
                "A general chat is still researching. "
                "Wait for it to finish, then try again.",
            )
        return _call(
            store.archive_general_chats,
            confirm=request.confirm,
            snapshot=request.snapshot,
        )

    @router.get("/chats/{chat_id}")
    def global_chat(chat_id: Identifier):
        return _call(store.get_global_chat, chat_id)

    @router.get("/chats/{chat_id}/research-status")
    def research_status(chat_id: Identifier, run_id: str | None = None):
        _call(store.get_global_chat, chat_id)
        if research_workflow is None:
            raise HTTPException(503, "Research progress is unavailable.")
        return research_workflow.progress.snapshot(chat_id, run_id)

    @router.post("/chats/{chat_id}/messages", status_code=201)
    def global_message(chat_id: Identifier, request: MessageCreate):
        if research_workflow is not None:
            return _call(
                research_workflow.respond,
                chat_id,
                request.content,
                current_config(),
                ranking_profile_id=request.ranking_profile_id,
                **(
                    {"search_reference_structures": request.search_reference_structures}
                    if request.search_reference_structures is not None
                    else {}
                ),
                **({"run_id": request.run_id} if request.run_id is not None else {}),
            )
        if request.ranking_profile_id is not None:
            raise HTTPException(
                422, "Ranking profile selection requires the research workflow."
            )
        return _call(
            store.append_global_message, chat_id, request.content, current_config()
        )

    @router.patch("/chats/{chat_id}")
    def update_chat(chat_id: Identifier, request: ChatUpdate):
        return _call(
            store.update_chat, chat_id, **request.model_dump(exclude_unset=True)
        )

    @router.delete("/chats/{chat_id}", status_code=204)
    def remove_chat(chat_id: Identifier):
        _call(store.archive_chat, chat_id)
        return Response(status_code=204)

    @router.post("/chats/{chat_id}/restore")
    def restore_chat(chat_id: Identifier):
        return _call(store.restore_chat, chat_id)

    @router.get("/projects")
    def projects():
        return {"projects": _call(store.list_projects)}

    @router.post("/projects", status_code=201)
    def create_project(request: ProjectCreate):
        return _call(store.create_project, request.name, request.description)

    @router.patch("/projects/{project_id}")
    def update_project(project_id: Identifier, request: ProjectUpdate):
        return _call(
            store.update_project, project_id, **request.model_dump(exclude_unset=True)
        )

    @router.delete("/projects/{project_id}", status_code=204)
    def remove_project(project_id: Identifier):
        _call(store.archive_project, project_id)
        return Response(status_code=204)

    @router.post("/projects/{project_id}/restore")
    def restore_project(project_id: Identifier):
        return _call(store.restore_project, project_id)

    @router.get("/removed")
    def removed_items():
        return _call(store.removed_items)

    @router.delete("/removed", status_code=204)
    def purge_removed(request: PermanentDeleteAll):
        _call(store.purge_removed, confirm=request.confirm, snapshot=request.snapshot)
        return Response(status_code=204)

    @router.delete("/removed/projects/{project_id}", status_code=204)
    def purge_project(project_id: Identifier, request: PermanentDelete):
        _call(store.purge_project, project_id, confirm=request.confirm)
        return Response(status_code=204)

    @router.delete("/removed/chats/{chat_id}", status_code=204)
    def purge_chat(chat_id: Identifier, request: PermanentDelete):
        _call(store.purge_chat, chat_id, confirm=request.confirm)
        return Response(status_code=204)

    @router.get("/workspace/preferences")
    def workspace_preferences():
        return _call(store.workspace_preferences)

    @router.put("/workspace/preferences")
    def save_workspace_preferences(request: WorkspacePreferences):
        return _call(
            store.save_workspace_preferences, confirm_removal=request.confirm_removal
        )

    @router.post("/projects/{project_id}/draft-chat")
    def project_draft(project_id: Identifier):
        return _call(store.project_draft, project_id)

    @router.get("/projects/{project_id}/chats")
    def chats(project_id: Identifier):
        return {"chats": _call(store.list_chats, project_id)}

    @router.post("/projects/{project_id}/chats", status_code=201)
    def create_chat(project_id: Identifier, request: ChatCreate):
        return _call(store.create_chat, project_id, request.title)

    @router.get("/projects/{project_id}/chats/{chat_id}")
    def chat(project_id: Identifier, chat_id: Identifier):
        return _call(store.get_chat, project_id, chat_id)

    @router.post("/projects/{project_id}/chats/{chat_id}/messages", status_code=201)
    def message(project_id: Identifier, chat_id: Identifier, request: MessageCreate):
        if research_workflow is not None:
            return _call(
                research_workflow.respond,
                chat_id,
                request.content,
                current_config(),
                project_id,
                ranking_profile_id=request.ranking_profile_id,
                **(
                    {"search_reference_structures": request.search_reference_structures}
                    if request.search_reference_structures is not None
                    else {}
                ),
                **({"run_id": request.run_id} if request.run_id is not None else {}),
            )
        if request.ranking_profile_id is not None:
            raise HTTPException(
                422, "Ranking profile selection requires the research workflow."
            )
        return _call(
            store.append_message, project_id, chat_id, request.content, current_config()
        )

    @router.get("/projects/{project_id}/contents")
    def contents(project_id: Identifier):
        return _call(store.contents, project_id)

    @router.get("/projects/{project_id}/context")
    def context(project_id: Identifier):
        return _call(store.context, project_id)

    @router.post("/projects/{project_id}/pins", status_code=201)
    def pin(project_id: Identifier, request: PinCreate):
        return _call(store.set_pin, project_id, request.kind, request.target_id)

    @router.put("/projects/{project_id}/tracked-reports/{chat_id}")
    def track_report(project_id: Identifier, chat_id: Identifier):
        return _call(store.set_report_tracking, project_id, chat_id)

    @router.delete("/projects/{project_id}/tracked-reports/{chat_id}", status_code=204)
    def stop_tracking_report(project_id: Identifier, chat_id: Identifier):
        _call(store.set_report_tracking, project_id, chat_id, tracking=False)
        return Response(status_code=204)

    @router.put("/projects/{project_id}/report-pins/{pin_id}")
    def update_snapshot(
        project_id: Identifier, pin_id: Identifier, request: ReportSnapshotUpdate
    ):
        return _call(
            store.replace_report_snapshot,
            project_id,
            pin_id,
            expected_report_id=request.expected_report_id,
            report_id=request.report_id,
        )

    @router.delete("/projects/{project_id}/pins/{kind}/{target_id}", status_code=204)
    def unpin(
        project_id: Identifier,
        kind: Literal["report", "source"],
        target_id: Identifier,
    ):
        _call(store.set_pin, project_id, kind, target_id, pinned=False)
        return Response(status_code=204)

    return router
