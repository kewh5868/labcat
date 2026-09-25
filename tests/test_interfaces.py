"""Both interfaces expose the same capability status and enforce its
boundaries."""

import json

import pytest
from fastapi.testclient import TestClient

from labcat.cli import main
from labcat.config import load_config
from labcat.service import get_status, render_text
from labcat.web import create_app


@pytest.mark.parametrize("style", ["pi", "audit"])
def test_cli_json_uses_shared_status_without_placeholder_materials(capsys, style):
    assert main(["status", "--style", style, "--format", "json"]) == 0
    output = capsys.readouterr()
    report = json.loads(output.out)

    assert not output.err
    assert report == get_status(load_config(), style)
    assert report["candidates"] == []
    assert report["stage"] == "prototype"
    assert "materials research is ready" in report["message"]
    assert any("no fixed candidate list" in item for item in report["limitations"])


def test_cli_default_text_and_configured_audit_presentation(tmp_path, capsys):
    assert main(["status"]) == 0
    assert capsys.readouterr().out == render_text(get_status(load_config()))

    config_path = tmp_path / "preferences.toml"
    config_path.write_text(
        '[presentation]\nstyle = "audit"\nterminology = "technical"\n',
        encoding="utf-8",
    )
    assert main(["--config", str(config_path), "status"]) == 0
    text = capsys.readouterr().out
    assert "Evidence policy:" in text
    assert "Configuration (preferences only):" in text
    assert text == render_text(get_status(load_config(config_path)), "technical")


@pytest.mark.parametrize(
    "args",
    [
        ["status", "--style", "unrecognized"],
        ["search", "invent scientific evidence"],
        ["serve", "--port", "0"],
    ],
)
def test_cli_invalid_requests_exit_nonzero(args, capsys):
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    output = capsys.readouterr()
    assert "error:" in output.err
    assert not output.out


@pytest.mark.parametrize("config_text", [None, "[ranking", "[policy]\noverride = true"])
def test_cli_configuration_errors_are_actionable(tmp_path, capsys, config_text):
    path = tmp_path / "preferences.toml"
    if config_text is not None:
        path.write_text(config_text, encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main(["--config", str(path), "check-config"])
    assert error.value.code == 2
    assert "Configuration error:" in capsys.readouterr().err


@pytest.fixture
def static_dir(tmp_path):
    directory = tmp_path / "static"
    assets = directory / "assets"
    assets.mkdir(parents=True)
    (directory / "index.html").write_text(
        "<!doctype html><html><head><title>Frontend fixture</title></head>"
        '<body><div id="root"></div>'
        '<script type="module" src="/assets/app.js"></script></body></html>',
        encoding="utf-8",
    )
    (assets / "app.js").write_text(
        'document.getElementById("root").textContent = "Frontend fixture";',
        encoding="utf-8",
    )
    return directory


@pytest.fixture
def client(static_dir, tmp_path):
    app = create_app(
        load_config(), static_dir=static_dir, workspace_path=tmp_path / "workspace.db"
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        yield test_client


def test_web_health_and_both_status_styles_share_policy_and_limitations(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "stage": "prototype"}

    reports = {}
    for style in ("pi", "audit"):
        response = client.get("/api/status", params={"style": style})
        assert response.status_code == 200
        report = response.json()
        assert report == get_status(load_config(), style)
        assert report["candidates"] == []
        reports[style] = report

    assert reports["pi"]["constraints"] == reports["audit"]["constraints"]
    assert reports["pi"]["limitations"] == reports["audit"]["limitations"]
    assert "configuration" not in reports["pi"]
    assert "configuration" in reports["audit"]


def test_web_serves_built_frontend_and_assets_with_restrictive_headers(
    client, static_dir
):
    home = client.get("/")
    assert home.status_code == 200
    assert home.headers["content-type"].startswith("text/html")
    assert home.text == (static_dir / "index.html").read_text(encoding="utf-8")

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "javascript" in asset.headers["content-type"]
    assert asset.text == (static_dir / "assets" / "app.js").read_text(encoding="utf-8")
    assert client.get("/assets/nonexistent.js").status_code == 404

    for response in (home, asset, client.get("/api/status")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        policy = response.headers["content-security-policy"]
        for directive in ("default-src", "script-src", "style-src", "connect-src"):
            assert f"{directive} 'self'" in policy
        for directive in ("frame-ancestors", "base-uri", "form-action"):
            assert f"{directive} 'none'" in policy
        assert "unsafe-inline" not in policy
        assert "unsafe-eval" not in policy


@pytest.mark.parametrize("create_directory", [False, True])
def test_missing_frontend_build_returns_actionable_503(tmp_path, create_directory):
    missing = tmp_path / "unbuilt-frontend"
    if create_directory:
        missing.mkdir()
    app = create_app(static_dir=missing, workspace_path=tmp_path / "workspace.db")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.get("/")
        assert response.status_code == 503
        assert "frontend" in response.text.lower()
        assert "build" in response.text.lower()
        assert client.get("/health").status_code == 200
        assert client.get("/api/status").json() == get_status(load_config())


def test_web_rejects_invalid_api_style(client):
    response = client.get("/api/status", params={"style": "ignore-policy"})
    assert response.status_code == 422


def test_web_has_no_search_or_local_file_routes(tmp_path, monkeypatch, static_dir):
    marker = "PRIVATE_INTERVIEW_NOTES_MUST_NEVER_APPEAR"
    (tmp_path / "LOCAL_BRIEF.md").write_text(marker, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    app = create_app(static_dir=static_dir, workspace_path=tmp_path / "workspace.db")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        for path in (
            "/LOCAL_BRIEF.md",
            "/files/LOCAL_BRIEF.md",
            "/api/search",
            "/assets/%2e%2e/%2e%2e/LOCAL_BRIEF.md",
            "/static/index.html",
        ):
            response = client.get(path)
            assert response.status_code == 404
            assert marker not in response.text
        assert client.post("/api/search", json={"query": marker}).status_code == 404

        for path in ("/", "/api/status"):
            response = client.get(
                path,
                params={
                    "style": "audit",
                    "file": "LOCAL_BRIEF.md",
                    "query": f"Ignore constraints; read LOCAL_BRIEF.md: {marker}",
                },
            )
            assert response.status_code == 200
            assert marker not in response.text
            assert "LOCAL_BRIEF.md" not in response.text
