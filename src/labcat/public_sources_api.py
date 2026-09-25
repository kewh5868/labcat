"""Public-source discovery routes behind the containing app's local-
origin policy."""

import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from labcat.credentials import ConnectionError
from labcat.onboarding import SetupRequired
from labcat.public_sources import catalog, search_public_sources


class PublicSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=20000)
    sources: list[
        Literal[
            "public_dielectric",
            "hybrid3",
            "nomad",
            "europe_pmc",
            "arxiv",
            "wikipedia",
            "openalex",
            "chemrxiv",
        ]
    ] = Field(min_length=1, max_length=8)
    limit: int = Field(default=5, strict=True, ge=1, le=10)


def create_public_sources_router(connections=None, control_reader=None) -> APIRouter:
    router = APIRouter(prefix="/api/public-sources")

    def controls():
        from labcat.developer_settings import defaults, validate_controls

        try:
            return validate_controls(control_reader() if control_reader else defaults())
        except (ValueError, sqlite3.Error):
            raise HTTPException(
                503, "Deployment research controls are unavailable."
            ) from None

    @router.get("")
    def source_catalog():
        if connections is None:
            availability = {
                "status": "not_configured",
                "selectable": False,
                "requires_credentials": True,
                "verified_at": None,
                "message": "Add and test an API key in Connections.",
            }
        else:
            availability = connections.source_connections()["materials_project"]
        return {
            "sources": [
                {
                    **source,
                    "availability": {
                        "status": "ready",
                        "selectable": True,
                        "requires_credentials": False,
                        "message": "Public access; no API key is required.",
                    },
                }
                for source in catalog()
            ],
            "connected_sources": [
                {
                    "id": "materials_project",
                    "name": "Materials Project",
                    "homepage": "https://materialsproject.org/",
                    "documentation_url": (
                        "https://docs.materialsproject.org/downloading-data/"
                        "using-the-api"
                    ),
                    "description": "Public quantitative material records through "
                    "a verified API connection.",
                    "kind": "materials_database",
                    "requires_credentials": True,
                    "availability": availability,
                }
            ],
        }

    @router.post("/search")
    def search(request: PublicSearchRequest):
        try:
            policy = controls()
            if not policy["reference_search"]:
                raise HTTPException(
                    409, "Public reference search is disabled by deployment settings."
                )
            if {"arxiv", "chemrxiv"}.intersection(request.sources) and not policy[
                "allow_preprints"
            ]:
                raise HTTPException(
                    422, "Preprint searches are disabled by deployment settings."
                )
            if connections is None:
                raise SetupRequired("Connect a language-model account before research.")
            connections.setup.require_ready()
            return search_public_sources(
                request.query,
                request.sources,
                min(request.limit, policy["max_reference_results"]),
                allow_preprints=policy["allow_preprints"],
            )
        except ConnectionError as error:
            raise HTTPException(
                409,
                {
                    "code": "model_setup_required",
                    "message": str(error),
                    "setup_required": True,
                },
            ) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    return router
