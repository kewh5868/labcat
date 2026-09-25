"""Local JSmol assets in an opaque sandbox, separate from the workspace
policy."""

import sqlite3

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response


def create_viewer_router(assets, control_reader):
    router = APIRouter()
    root = (assets / "structure-viewer").resolve()

    @router.options("/structure-viewer/vendor/{path:path}")
    def asset_preflight(path: str):
        return Response(status_code=204)

    @router.api_route("/structure-viewer/{path:path}", methods=["GET", "HEAD"])
    def viewer_asset(path: str):
        try:
            enabled = control_reader()["viewer_enabled"]
        except (sqlite3.Error, KeyError):
            raise HTTPException(
                503, "Structure viewer settings are unavailable."
            ) from None
        if not enabled:
            raise HTTPException(404, "The structure viewer is disabled.")
        file = (root / path).resolve()
        if not path or not file.is_relative_to(root) or not file.is_file():
            raise HTTPException(404, "Viewer asset not found.")
        return FileResponse(file)

    return router


def viewer_headers(request, response):
    # J2S compiles its bundled classes with eval. Only this opaque iframe gets
    # that permission. All networking is confined to public, local vendor assets;
    # no workspace API, external host, PHP relay, credentials or native bridge.
    origin = str(request.base_url).rstrip("/")
    assets = origin + "/structure-viewer/"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; sandbox allow-scripts; "
        f"script-src {assets} 'unsafe-eval' 'unsafe-inline'; "
        f"connect-src {assets}vendor/; "
        f"img-src {assets}vendor/ data:; style-src 'unsafe-inline' {assets}; "
        "frame-src 'none'; worker-src 'none'; object-src 'none'; "
        "frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
    )
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), usb=(), payment=()"
    )
    if request.url.path.startswith("/structure-viewer/vendor/"):
        # An opaque frame has Origin:null. Never enable CORS for any API route.
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, HEAD"
        response.headers["Access-Control-Allow-Headers"] = "X-Requested-With"
