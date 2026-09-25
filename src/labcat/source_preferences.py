"""Non-secret source selections; public-only boundaries are not
configurable."""

import json
import sqlite3

from labcat.credentials import ConnectionError

SOURCE_IDS = (
    "public_dielectric",
    "hybrid3",
    "nomad",
    "europe_pmc",
    "arxiv",
    "wikipedia",
    "openalex",
    "chemrxiv",
)


class SourceConnectionRequired(ConnectionError):
    """A selected authenticated data API has no verified current
    credential."""


def require_source_selection(value: dict, connections=None) -> None:
    if value["materials_project_mode"] == "api":
        if connections is None:
            raise SourceConnectionRequired(
                "Add and test a Materials Project API key in Connections first."
            )
        connections.require_source_connection("materials_project")


def default_source_preferences() -> dict:
    return {
        "search_public_references": True,
        "enabled_sources": list(SOURCE_IDS),
        "materials_project_mode": "auto",
        "max_results_per_source": 5,
    }


def validate_source_preferences(value: dict) -> dict:
    """Accept bounded selections, never URLs, credentials, policies or
    evidence."""
    if (
        not isinstance(value, dict)
        or value.keys() != default_source_preferences().keys()
    ):
        raise ValueError("Provide the supported public source preferences only.")
    if type(value["search_public_references"]) is not bool:
        raise ValueError("Public reference search must be enabled or disabled.")
    enabled = value["enabled_sources"]
    if (
        not isinstance(enabled, list)
        or len(enabled) > len(SOURCE_IDS)
        or any(not isinstance(item, str) or item not in SOURCE_IDS for item in enabled)
        or len(set(enabled)) != len(enabled)
    ):
        raise ValueError("Select each supported public source at most once.")
    if value["materials_project_mode"] not in ("auto", "snapshot", "api", "off"):
        raise ValueError("Choose auto, api or off for Materials Project.")
    limit = value["max_results_per_source"]
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("Choose between 1 and 10 references per source.")
    return {**value, "enabled_sources": enabled.copy()}


class SourcePreferencesStore:
    """Persist validated preferences with the workspace transaction
    guarantees."""

    def __init__(self, workspace):
        self.workspace = workspace

    def initialize(self):
        with self.workspace._connection(write=True) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS source_preferences "
                "(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)"
            )

    def load(self) -> dict:
        with self.workspace._connection() as connection:
            row = connection.execute(
                "SELECT value FROM source_preferences WHERE id=1"
            ).fetchone()
        if row is None:
            return default_source_preferences()
        try:
            return validate_source_preferences(json.loads(row[0]))
        except (ValueError, TypeError, RecursionError) as error:
            raise sqlite3.DatabaseError(
                "Stored source preferences are invalid."
            ) from error

    def save(self, value: dict, *, connections=None) -> dict:
        validated = validate_source_preferences(value)
        require_source_selection(validated, connections)
        with self.workspace._connection(write=True) as connection:
            connection.execute(
                "INSERT INTO source_preferences(id,value) VALUES(1,?) "
                "ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                (json.dumps(validated, allow_nan=False),),
            )
        return validated


def create_source_settings_router(store: SourcePreferencesStore, connections=None):
    """The host application enforces its local Host and Origin
    boundaries."""
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api")

    @router.get("/source-settings")
    def get_source_settings():
        try:
            return store.load()
        except sqlite3.Error as error:
            raise HTTPException(
                503, "Saved source preferences are unavailable."
            ) from error

    @router.put("/source-settings")
    def save_source_settings(request: dict):
        try:
            return store.save(request, connections=connections)
        except SourceConnectionRequired as error:
            raise HTTPException(
                409,
                {
                    "code": "source_connection_required",
                    "message": str(error),
                    "setup_required": False,
                },
            ) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except sqlite3.Error as error:
            raise HTTPException(503, "Unable to save source preferences.") from error

    return router
