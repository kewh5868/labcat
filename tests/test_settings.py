"""Preferences persist without changing evidence boundaries or old
reports."""

import json
from dataclasses import replace

import pytest

from labcat.config import load_config
from labcat.service import CONSTRAINTS, get_status, render_report
from labcat.settings import SettingsStore, preferences, validate_preferences
from labcat.workspace import WorkspaceStore


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
