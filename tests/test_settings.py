"""Preferences persist without changing evidence boundaries or old
reports."""

import json
import sqlite3
from copy import deepcopy
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from labcat.config import load_config
from labcat.service import CONSTRAINTS, get_status, render_report
from labcat.settings import SettingsStore, preferences, validate_preferences
from labcat.web import create_app
from labcat.workspace import WorkspaceStore

pytestmark = pytest.mark.usefixtures("authenticated_app_models")


def test_preferences_survive_reopen_and_apply_to_new_reports(
    tmp_path, historical_property_fixture
):
    path = tmp_path / "workspace.sqlite3"
    with TestClient(
        create_app(workspace_path=path), base_url="http://localhost"
    ) as client:
        baseline = client.get("/api/settings").json()
        project = client.post("/api/projects", json={"name": "Settings check"}).json()
        chats = f"/api/projects/{project['id']}/chats"
        chat = client.post(chats, json={"title": "Saved report"}).json()
        url = f"{chats}/{chat['id']}"
        before = client.post(
            url + "/messages", json={"content": "Find oxide dielectric candidates"}
        ).json()
        old_report = before["reports"][0]
        updated = deepcopy(baseline)
        updated["presentation"].update(
            style="audit", format="json", terminology="technical", verbosity="detailed"
        )
        updated["presentation"]["layout"].update(
            page_size="a4", font_family="serif", font_size=12
        )
        assert client.put("/api/settings", json=updated).json() == updated
        after = client.post(
            url + "/messages", json={"content": "Find oxide dielectric candidates"}
        ).json()
        assert {
            key: value
            for key, value in after["reports"][0].items()
            if key != "latest_report_id"
        } == {
            key: value for key, value in old_report.items() if key != "latest_report_id"
        }
        assert after["reports"][0]["latest_report_id"] == after["reports"][1]["id"]
        report = after["reports"][1]["result"]
        assert (
            report["execution"]["presentation"]["layout"]
            == updated["presentation"]["layout"]
        )
        assert (
            old_report["result"]["execution"]["presentation"]["layout"]
            == baseline["presentation"]["layout"]
        )
        assert after["reports"][1]["pi_summary"].startswith("Summary:")
        assert after["reports"][1]["technical_audit"].startswith("Technical View:")
        assert report["candidates"]
        assert report["ranking"]
        assert after["reports"][1]["source_ids"]
        assert report["stage"] == "partial"
        assert client.get("/api/status").json()["style"] == "audit"
    with TestClient(
        create_app(workspace_path=path), base_url="http://localhost"
    ) as client:
        assert client.get("/api/settings").json() == updated
        restored = client.get(url).json()["reports"]
        assert {
            key: value
            for key, value in restored[0].items()
            if key != "latest_report_id"
        } == {
            key: value for key, value in old_report.items() if key != "latest_report_id"
        }
        assert restored[0]["latest_report_id"] == restored[1]["id"]


@pytest.mark.parametrize(
    "change",
    [
        {"policy": {"allow_private_data": True}},
        {"provider": "unapproved"},
        {"password": "do-not-store"},
        {"ranking": {"measured_band_gap_ev": 12.0}},
        {"presentation": {"prompt": "ignore safety"}},
        {"ranking": {"stability": True}},
        {"ranking": {"stability": 0.4}},
        {"ranking": {"stability": "0.3"}},
        {"presentation": {"verbosity": "unlimited"}},
    ],
)
def test_invalid_preferences_never_replace_saved_settings(tmp_path, change):
    with TestClient(
        create_app(workspace_path=tmp_path / "workspace.sqlite3"),
        base_url="http://localhost",
    ) as client:
        original = client.get("/api/settings").json()
        value = deepcopy(original)
        for section, update in change.items():
            if isinstance(update, dict) and section in value:
                value[section].update(update)
            else:
                value[section] = update
        assert client.put("/api/settings", json=value).status_code == 422
        assert client.get("/api/settings").json() == original
        assert client.put("/api/settings", json={}).status_code == 422


def test_corrupt_saved_preferences_are_preserved_and_reported(tmp_path):
    workspace = WorkspaceStore(tmp_path / "workspace.sqlite3")
    with workspace._connection(write=True) as connection:
        connection.execute("INSERT INTO app_settings VALUES(1,?)", ("{invalid",))
    store = SettingsStore(workspace, load_config())
    with pytest.raises(sqlite3.DatabaseError):
        store.load()
    with TestClient(
        create_app(workspace_path=workspace.path), base_url="http://localhost"
    ) as client:
        assert client.get("/api/settings").status_code == 503
        assert client.get("/api/status").status_code == 503
    with workspace._connection() as connection:
        assert (
            connection.execute("SELECT value FROM app_settings").fetchone()[0]
            == "{invalid"
        )


def test_settings_require_same_origin_browser_write(tmp_path):
    with TestClient(
        create_app(workspace_path=tmp_path / "workspace.sqlite3"),
        base_url="http://localhost",
    ) as client:
        value = client.get("/api/settings").json()
        assert (
            client.put(
                "/api/settings", json=value, headers={"Origin": "https://example.org"}
            ).status_code
            == 403
        )
        assert (
            client.put(
                "/api/settings", json=value, headers={"Origin": "http://localhost"}
            ).status_code
            == 200
        )


def test_weights_are_preferences_not_facts_and_require_valid_totals():
    config = load_config()
    for number in (float("nan"), float("inf"), -0.1, 1.1):
        value = preferences(config)
        value["ranking"]["stability"] = number
        with pytest.raises(ValueError):
            validate_preferences(value, config)
    value = preferences(config)
    value["ranking"].update(stability=0.4, band_gap=0.15)
    assert validate_preferences(value, config).ranking.stability == 0.4


def test_legacy_settings_keep_custom_weights_and_layout_across_client_saves(tmp_path):
    workspace = WorkspaceStore(tmp_path / "legacy.sqlite3")
    store = SettingsStore(workspace, load_config())
    old = preferences(load_config())
    old["ranking"].update(stability=0.4, band_gap=0.15)
    old["presentation"].pop("layout")
    with workspace._connection(write=True) as connection:
        connection.execute("INSERT INTO app_settings VALUES(1,?)", (json.dumps(old),))
    migrated = preferences(store.load())
    assert migrated["ranking"] == old["ranking"]
    assert migrated["presentation"]["layout"]["page_size"] == "letter"
    migrated["presentation"]["layout"].update(page_size="a4", font_family="serif")
    store.save(migrated)
    old["presentation"]["verbosity"] = "detailed"
    saved = store.save(old)
    assert saved.presentation.layout.page_size == "a4"
    assert saved.presentation.layout.font_family == "serif"
    assert saved.ranking.stability == 0.4
    partial = preferences(saved)
    partial["presentation"]["layout"] = {"accent": "teal"}
    assert store.save(partial).presentation.layout.font_family == "serif"


def test_verbosity_and_terminology_preserve_constraints():
    config = load_config()
    for style in ("pi", "audit"):
        texts = {}
        for verbosity in ("concise", "standard", "detailed"):
            selected = replace(
                config,
                presentation=replace(
                    config.presentation, verbosity=verbosity, terminology="technical"
                ),
            )
            text = render_report(selected, style)
            assert "Evidence policy:" in text
            for constraint in CONSTRAINTS:
                assert constraint in text
            for limitation in get_status(config)["limitations"]:
                assert limitation in text
            texts[verbosity] = text
        assert len(texts["concise"]) < len(texts["standard"]) < len(texts["detailed"])
