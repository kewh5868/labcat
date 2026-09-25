"""JSmol's relaxed runtime stays separate from workspace and
credentials."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from labcat.web import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LABCAT_EDITION", "developer")
    assets = tmp_path / "static"
    viewer = assets / "structure-viewer"
    (viewer / "vendor").mkdir(parents=True)
    (assets / "index.html").write_text("Workspace")
    (viewer / "index.html").write_text("Viewer")
    (viewer / "vendor" / "test.js").write_text("// vendor")
    with TestClient(
        create_app(static_dir=assets, workspace_path=tmp_path / "workspace.sqlite3"),
        base_url="http://127.0.0.1:8123",
    ) as client:
        yield client


def test_viewer_is_opaque_and_only_vendor_assets_allow_cross_origin_reads(client):
    page = client.get("/structure-viewer/index.html")
    assert page.status_code == 200
    csp = page.headers["content-security-policy"]
    assert "sandbox allow-scripts;" in csp
    assert "allow-same-origin" not in csp
    assert "connect-src http://127.0.0.1:8123/structure-viewer/vendor/;" in csp
    assert "frame-src 'none'" in csp
    assert "frame-ancestors 'self'" in csp
    assert "form-action 'none'" in csp
    assert "access-control-allow-origin" not in page.headers
    asset = client.get("/structure-viewer/vendor/test.js", headers={"Origin": "null"})
    assert asset.status_code == 200
    assert asset.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in asset.headers
    preflight = client.options(
        "/structure-viewer/vendor/test.js",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Requested-With",
        },
    )
    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-methods"] == "GET, HEAD"
    assert preflight.headers["access-control-allow-headers"] == "X-Requested-With"
    for path in ["/", "/api/session", "/api/projects"]:
        response = client.get(path, headers={"Origin": "null"})
        assert "unsafe-eval" not in response.headers["content-security-policy"]
        assert "access-control-allow-origin" not in response.headers
    assert (
        client.post(
            "/api/projects", json={"name": "No"}, headers={"Origin": "null"}
        ).status_code
        == 403
    )


def test_disabling_blocks_all_viewer_assets_without_changing_workspace(client):
    controls = client.get("/api/developer-settings").json()["settings"]
    controls["viewer_enabled"] = False
    token = client.get("/api/session").json()["csrf_token"]
    assert (
        client.put(
            "/api/developer-settings", json=controls, headers={"X-CSRF-Token": token}
        ).status_code
        == 200
    )
    for path in ["/structure-viewer/index.html", "/structure-viewer/vendor/test.js"]:
        assert client.get(path).status_code == 404
    assert client.get("/").status_code == 200
    assert client.get("/api/projects").json() == {"projects": []}


def test_viewer_does_not_serve_files_outside_its_static_tree(client):
    for path in [
        "/structure-viewer/%2E%2E/index.html",
        "/structure-viewer/vendor/%2E%2E/%2E%2E/index.html",
        "/structure-viewer/missing.js",
    ]:
        assert client.get(path).status_code == 404


def test_pinned_jsmol_vendor_assets_match_release_manifest():
    import hashlib

    root = Path(__file__).resolve().parents[1]
    vendor = root / "frontend/public/structure-viewer/vendor"
    manifest = json.loads((vendor / "manifest.json").read_text())
    assert manifest["version"] == "16.4.23"
    assert (
        manifest["archive_sha256"]
        == "1c4aa04d6b4fc96cfd1b2cb3649f5ba39048620a8358799bc1b78ee1041bc4b2"
    )
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((vendor / name).read_bytes()).hexdigest() == digest
