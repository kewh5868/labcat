"""Persist non-secret report preferences; evidence policy is not
configurable."""

import json
import sqlite3
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException

from labcat.config import AppConfig, config_from_mapping, validate_layout
from labcat.workspace import WorkspaceStore


def preferences(config: AppConfig) -> dict[str, Any]:
    """Expose only the two editable preference groups."""
    values = config.to_dict()
    return {key: values[key] for key in ("ranking", "presentation")}


def validate_preferences(value: dict[str, Any], base: AppConfig) -> AppConfig:
    """Require a complete preference snapshot, rejecting policy/fact
    fields."""
    expected = preferences(base)
    if not isinstance(value, dict) or value.keys() != expected.keys():
        raise ValueError("Provide only ranking and presentation preferences.")
    value = deepcopy(value)
    for section, fields in expected.items():
        group = value[section]
        if section == "presentation" and isinstance(group, dict):
            # Old clients and saved preferences predate layout/output choices.
            # Preserve the current layout instead of resetting it on legacy PUTs.
            group.setdefault("layout", fields["layout"])
            group.setdefault("outputs", fields["outputs"])
            group["layout"] = asdict(
                validate_layout(group["layout"], base.presentation.layout)
            )
        if not isinstance(group, dict) or group.keys() != fields.keys():
            raise ValueError(f"Provide all supported {section} preferences only.")
    return config_from_mapping({**value, "model": {"provider": base.provider}})


class SettingsStore:
    """Use workspace transactions and keep invalid stored data
    intact."""

    def __init__(self, workspace: WorkspaceStore, defaults: AppConfig):
        self.workspace = workspace
        self.defaults = defaults

    def load(self) -> AppConfig:
        with self.workspace._connection() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE id=1"
            ).fetchone()
        if row is None:
            return self.defaults
        try:
            value = json.loads(row[0])
            # Earlier stored profiles predate selectable report exports.
            if isinstance(value, dict) and isinstance(value.get("presentation"), dict):
                value["presentation"].setdefault("outputs", ["pi", "audit"])
            return validate_preferences(value, self.defaults)
        except (ValueError, TypeError) as error:
            # Do not silently replace corrupted preferences with fresh defaults.
            raise sqlite3.DatabaseError("Stored preferences are invalid.") from error

    def save(self, value: dict[str, Any]) -> AppConfig:
        config = validate_preferences(value, self.load())
        serialized = json.dumps(preferences(config), allow_nan=False)
        with self.workspace._connection(write=True) as connection:
            connection.execute(
                "INSERT INTO app_settings(id,value) VALUES(1,?) "
                "ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                (serialized,),
            )
        return config


def create_settings_router(store: SettingsStore) -> APIRouter:
    """Use the containing application's local Host and Origin
    protection."""
    router = APIRouter(prefix="/api")

    @router.get("/settings")
    def get_settings():
        try:
            return preferences(store.load())
        except sqlite3.Error as error:
            raise HTTPException(503, "Saved preferences are unavailable.") from error

    @router.put("/settings")
    def save_settings(request: dict[str, Any]):
        try:
            return preferences(store.save(request))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except sqlite3.Error as error:
            raise HTTPException(503, "Unable to save preferences.") from error

    return router
