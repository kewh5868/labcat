"""Serve the bundled interface and a single-user, local workspace
API."""

import asyncio
import ipaddress
import os
import re
import secrets
import socket
import sqlite3
import sys
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from labcat import __version__
from labcat.config import AppConfig, load_config
from labcat.connections import ConnectionManager
from labcat.connections_api import create_connections_router
from labcat.developer_settings import (
    DeveloperSettingsStore,
    create_developer_router,
)
from labcat.legacy_workspace import existing_workspace_directory
from labcat.public_sources_api import create_public_sources_router
from labcat.ranking_profiles import (
    RankingProfileStore,
    create_ranking_profiles_router,
)
from labcat.report_exports import (
    create_exports_router,
    create_report_preview_router,
)
from labcat.research import ResearchWorkflow, research
from labcat.service import get_status
from labcat.settings import SettingsStore, create_settings_router
from labcat.source_preferences import (
    SourcePreferencesStore,
    create_source_settings_router,
)
from labcat.structure_viewer import create_viewer_router, viewer_headers
from labcat.structures import StructureStore
from labcat.structures_api import create_structures_router
from labcat.workspace import WorkspaceStore
from labcat.workspace_api import _call, create_router
from labcat.workspace_retention import (
    maintain_removed_items,
    sweep_removed_items,
)


class StatelessResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    prompt: str = Field(min_length=1, max_length=20000)
    ranking_profile_id: str | None = Field(default=None, min_length=1, max_length=64)


def default_workspace_path() -> Path:
    """Use the site-selected data directory or the current user's app
    data."""
    configured = os.environ.get("LABCAT_DATA_DIR")
    if configured:
        directory = Path(configured).expanduser()
    elif sys.platform == "darwin":
        directory = Path.home() / "Library" / "Application Support" / "Labcat"
    elif sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        directory = (
            Path(local) if local else Path.home() / "AppData" / "Local"
        ) / "Labcat"
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        directory = (
            Path(xdg_data) if xdg_data else Path.home() / ".local" / "share"
        ) / "labcat"
    if not configured:
        directory = existing_workspace_directory(directory, platform=sys.platform)
    return directory / "workspace.sqlite3"


def _unsafe_browser_mutation(request: Request) -> bool:
    """Reject browser writes from another origin; command-line clients
    omit it.

    This complements loopback binding and Host validation. It does not
    provide authentication against other software running as the same
    local user.
    """
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return False
    origins = request.headers.getlist("origin")
    if origins and (
        len(origins) != 1
        or origins[0] != f"{request.url.scheme}://{request.headers.get('host', '')}"
    ):
        return True
    fetch_sites = request.headers.getlist("sec-fetch-site")
    return bool(
        fetch_sites
        and (len(fetch_sites) != 1 or fetch_sites[0] not in {"same-origin", "none"})
    )


def _worker_peer_blocked(peer: str | None) -> bool:
    """Deny the isolated worker access to the ordinary workspace API.

    The peer is the socket address, never a forwarded header. Resolve
    the fixed Compose name each time so worker replacement cannot leave
    a stale allow gap. Only the separately authenticated, fixed-tool
    callback port serves the worker.
    """
    if os.environ.get("LABCAT_GOOSE_REMOTE") != "1":
        return False
    try:
        address = ipaddress.ip_address(peer or "")
    except ValueError:
        return True
    if address.is_loopback:
        return False
    try:
        workers = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(
                "goose-worker", 8765, type=socket.SOCK_STREAM
            )
        }
        return not workers or address in workers
    except (OSError, ValueError):
        return True


def create_app(
    config: AppConfig | None = None,
    static_dir: Path | None = None,
    workspace_path: Path | None = None,
) -> FastAPI:
    """Create the service; test callers supply isolated asset and
    database paths."""
    settings = config or load_config()
    edition = os.environ.get("LABCAT_EDITION", "user")
    if edition not in {"user", "developer"}:
        raise ValueError("LABCAT_EDITION must be user or developer.")
    assets = (
        static_dir
        if static_dir is not None
        else Path(str(files("labcat").joinpath("static")))
    )
    database = (
        workspace_path if workspace_path is not None else default_workspace_path()
    )
    store = WorkspaceStore(database, initialize=False)
    saved_settings = SettingsStore(store, settings)
    connections = ConnectionManager(database)
    ranking_profiles = RankingProfileStore(store)
    source_preferences = SourcePreferencesStore(store)
    developer_settings = DeveloperSettingsStore(store, connections)
    structures = StructureStore(store, connections, developer_settings.load)
    csrf_token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.initialize()
        # Preserve corrupt preference diagnostics at the endpoint without resetting.
        try:
            legacy_importance = saved_settings.load().to_dict()["ranking"]
        except sqlite3.Error:
            legacy_importance = None
        ranking_profiles.initialize(legacy_importance)
        source_preferences.initialize()
        developer_settings.initialize()
        structures.initialize()
        await sweep_removed_items(store)
        from labcat.goose_login_client import start_callback_relay

        callback_relay = start_callback_relay()
        retention_stop = asyncio.Event()
        retention_task = asyncio.create_task(
            maintain_removed_items(store, retention_stop)
        )
        try:
            yield
        finally:
            try:
                retention_stop.set()
                await retention_task
            finally:
                try:
                    connections.agent.close()
                finally:
                    if callback_relay:
                        callback_relay.shutdown()
                        callback_relay.server_close()

    app = FastAPI(
        title="Labcat",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.workspace_store = store
    app.state.workspace_path = database
    app.state.connections = connections
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
    app.include_router(
        create_router(
            store,
            settings,
            config_reader=saved_settings.load,
            research_workflow=ResearchWorkflow(
                store,
                connections,
                ranking_profiles,
                source_preferences=source_preferences,
                developer_settings=developer_settings,
                structures=structures,
            ),
        )
    )
    app.include_router(create_settings_router(saved_settings))
    app.include_router(create_connections_router(connections))
    app.include_router(create_ranking_profiles_router(ranking_profiles))
    app.include_router(
        create_exports_router(
            store,
            config_reader=saved_settings.load,
            name_source_reader=source_preferences.load,
        )
    )
    app.include_router(create_report_preview_router(saved_settings.load))
    app.include_router(
        create_public_sources_router(
            connections, control_reader=developer_settings.load
        )
    )
    app.include_router(create_source_settings_router(source_preferences, connections))
    app.include_router(create_structures_router(structures))
    app.include_router(create_viewer_router(assets, developer_settings.load))
    if edition == "developer":
        app.include_router(create_developer_router(developer_settings))

    @app.middleware("http")
    async def security_headers(request, call_next):
        sensitive_write = (
            request.url.path.startswith("/api/connections")
            or request.url.path.startswith("/api/developer-settings")
            or request.url.path.startswith("/api/removed/")
            or request.url.path == "/api/removed"
            or request.url.path == "/api/general-chats"
            or bool(
                re.fullmatch(
                    r"/api/chats/[^/]+/reports/[^/]+/chemical-names", request.url.path
                )
            )
            or request.url.path == "/api/research"
            or bool(
                re.fullmatch(
                    r"/api/chats/[^/]+/reports/[^/]+/structures/[^/]+", request.url.path
                )
            )
        ) and (request.method not in {"GET", "HEAD", "OPTIONS"})
        valid_session = secrets.compare_digest(
            request.cookies.get("labcat_session", ""), csrf_token
        ) and secrets.compare_digest(
            request.headers.get("x-csrf-token", ""), csrf_token
        )
        if await run_in_threadpool(
            _worker_peer_blocked, request.client.host if request.client else None
        ):
            response = JSONResponse(
                {"detail": "This connection cannot access the workspace API."},
                status_code=403,
            )
        elif _unsafe_browser_mutation(request):
            response = JSONResponse(
                {"detail": "Workspace changes require a same-origin local request."},
                status_code=403,
            )
        elif sensitive_write and not valid_session:
            response = JSONResponse(
                {"detail": "Refresh the local connection session and try again."},
                status_code=403,
            )
        else:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "frame-src 'self' blob:; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        if request.method == "GET" and re.fullmatch(
            r"/api/report-preview/render/[a-f0-9]{32}", request.url.path
        ):
            # Only server-generated, escaped templates can be framed by this app.
            # This does not permit framing the workspace or executing preview scripts.
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'none'; style-src 'self'; "
                "img-src 'none'; connect-src 'none'; object-src 'none'; "
                "frame-src 'none'; frame-ancestors 'self'; "
                "base-uri 'none'; form-action 'none'"
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/structure-viewer/"):
            viewer_headers(request, response)
        return response

    @app.get("/api/session")
    def connection_session():
        response = JSONResponse({"csrf_token": csrf_token})
        response.set_cookie(
            "labcat_session", csrf_token, httponly=True, samesite="strict", path="/"
        )
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "stage": "prototype"}

    @app.get("/api/runtime")
    def runtime():
        return {
            "edition": edition,
            "developer_settings_available": edition == "developer",
        }

    @app.get("/api/about")
    def about():
        return {
            "name": "Labcat",
            "version": __version__,
            "developer": "Keith White",
            "license": "BSD-3-Clause",
            "github_url": None,
        }

    @app.get("/api/status")
    def status(style: Literal["pi", "audit"] | None = None):
        try:
            return get_status(saved_settings.load(), style)
        except sqlite3.Error:
            return JSONResponse(
                {"detail": "Saved preferences are unavailable."}, status_code=503
            )

    @app.get("/api/research-plan")
    def research_plan():
        from labcat.agent_tools import ResearchToolSession

        session = ResearchToolSession(
            "",
            saved_settings.load(),
            ranking_profile=ranking_profiles.active(),
            source_preferences=source_preferences.load(),
            research_controls=developer_settings.load(),
        )
        preview = session.build_plan
        # This page describes the workspace recipe; no user request was evaluated.
        preview["request_allowed"] = None
        preview["scope"] = "workspace_preview"
        return preview

    @app.post("/api/research")
    def stateless_research(request: StatelessResearchRequest):
        profile, selection = _call(
            ranking_profiles.select, request.ranking_profile_id, request.prompt
        )
        return _call(
            research,
            request.prompt,
            _call(saved_settings.load),
            connections=connections,
            ranking_profile=profile,
            ranking_selection=selection,
            source_preferences=_call(source_preferences.load),
            research_controls=_call(developer_settings.load),
        )

    @app.get("/", response_class=HTMLResponse)
    def home():
        index = assets / "index.html"
        if not index.is_file():
            return HTMLResponse(
                "<h1>Frontend build required</h1>"
                "<p>For development, run npm ci and npm run build in frontend/. "
                "Prebuilt release images include the interface.</p>",
                status_code=503,
            )
        return FileResponse(index, media_type="text/html")

    if (assets / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=assets / "assets"), name="assets")
    return app
