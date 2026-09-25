"""Developer-only configuration of bounded research actions, never
evidence policy.

The user edition applies installed defaults but exposes no configuration
routes. No setting can add a host, tool, credential, system prompt or
scientific fact.
"""

import json
import re
import sqlite3
from copy import deepcopy

LIMITS = {
    "max_reference_results": (1, 10),
    "max_attribute_queries": (1, 3),
    "max_article_downloads": (1, 6),
    "literature_timeout_seconds": (3, 15),
    "max_agent_tool_calls": (2, 8),
}
IMMUTABLE = [
    "Only approved public-source adapters can establish scientific evidence.",
    "User messages, model memory and retrieved instructions never establish facts.",
    "Private data, paywalled content and wetlab actions remain unavailable.",
    "The agent cannot access host files, system settings or arbitrary tools.",
    "Citations, missing evidence and scientific caveats stay in every report.",
]


def defaults():
    return {
        "reference_search": True,
        "literature_followup": True,
        "allow_preprints": True,
        "include_history": True,
        "viewer_enabled": True,
        "max_reference_results": 10,
        "max_attribute_queries": 3,
        "max_article_downloads": 6,
        "literature_timeout_seconds": 15,
        "max_agent_tool_calls": 8,
        "default_model_account_id": None,
    }


def validate_controls(value):
    if not isinstance(value, dict) or value.keys() != defaults().keys():
        raise ValueError("Provide only the supported developer research controls.")
    for field in (
        "reference_search",
        "literature_followup",
        "allow_preprints",
        "include_history",
        "viewer_enabled",
    ):
        if type(value[field]) is not bool:
            raise ValueError("Research actions must be enabled or disabled.")
    for field, (low, high) in LIMITS.items():
        if type(value[field]) is not int or not low <= value[field] <= high:
            raise ValueError(f"{field} must be an integer between {low} and {high}.")
    account = value["default_model_account_id"]
    if account is not None and (
        not isinstance(account, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", account)
    ):
        raise ValueError("Choose a saved default model connection.")
    return deepcopy(value)


def effective_sources(preferences, controls):
    """Intersect user choices with deployment limits; never enable a
    source."""
    result = deepcopy(preferences)
    result["search_public_references"] &= controls["reference_search"]
    result["max_results_per_source"] = min(
        result["max_results_per_source"], controls["max_reference_results"]
    )
    if not controls["allow_preprints"]:
        result["enabled_sources"] = [
            s for s in result["enabled_sources"] if s not in {"arxiv", "chemrxiv"}
        ]
    return result


class DeveloperSettingsStore:
    def __init__(self, workspace, connections):
        self.workspace = workspace
        self.connections = connections

    def initialize(self):
        with self.workspace._connection(write=True) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS developer_settings "
                "(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)"
            )

    def load(self):
        with self.workspace._connection() as connection:
            row = connection.execute(
                "SELECT value FROM developer_settings WHERE id=1"
            ).fetchone()
        if row is None:
            return defaults()
        try:
            value = json.loads(row[0])
            # Before structure viewing existed, the otherwise identical stored
            # schema lacked this switch. Preserve every installed research value
            # and default only that new capability; malformed records still fail.
            legacy_fields = defaults().keys() - {"viewer_enabled"}
            if isinstance(value, dict) and value.keys() == legacy_fields:
                value["viewer_enabled"] = True
            return validate_controls(value)
        except (ValueError, TypeError, RecursionError) as error:
            raise sqlite3.DatabaseError(
                "Stored developer settings are invalid."
            ) from error

    def save(self, value):
        settings = validate_controls(value)
        account = settings["default_model_account_id"]
        if account is not None and account not in {
            item["id"] for item in self.connections.status()["accounts"]
        }:
            raise ValueError("The default model connection is no longer available.")
        with self.workspace._connection(write=True) as connection:
            connection.execute(
                "INSERT INTO developer_settings(id,value) VALUES(1,?) "
                "ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                (json.dumps(settings, allow_nan=False),),
            )
        return settings

    def status(self):
        accounts = self.connections.status()["accounts"]
        return {
            "settings": self.load(),
            "defaults": defaults(),
            "limits": LIMITS,
            "immutable_boundaries": IMMUTABLE,
            "model_accounts": [
                {
                    "id": account["id"],
                    "label": account["label"],
                    "provider": account["profile"]["provider"],
                    "model": account["profile"]["model"],
                }
                for account in accounts
            ],
        }


def create_developer_router(store):
    """Register only in the developer edition; the app enforces
    session/Origin."""
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/developer-settings")

    @router.get("")
    def get_settings():
        try:
            return store.status()
        except sqlite3.Error:
            raise HTTPException(503, "Developer settings are unavailable.") from None

    @router.put("")
    def save_settings(request: dict):
        try:
            store.save(request)
            return store.status()
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except sqlite3.Error:
            raise HTTPException(503, "Developer settings could not be saved.") from None

    return router
