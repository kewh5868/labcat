"""Report-scoped public structure downloads; callers cannot submit
scientific data."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response

from labcat.structures import StructureConnectionRequired, StructureUnavailable
from labcat.workspace_api import Identifier, _call

MaterialIdentifier = Annotated[
    str,
    Path(
        min_length=1,
        max_length=86,
        pattern=(
            r"^(?:mp-\d{1,10}|nomad:[A-Za-z0-9_-]{1,80}|"
            r"dielectric:mp-\d{1,10}(?::row\d{1,4})?|"
            r"hybrid3:[1-9][0-9]{0,8}:dataset[1-9][0-9]{0,8}:"
            r"subset[1-9][0-9]{0,8})$"
        ),
    ),
]
LeadIdentifier = Annotated[
    str, Path(min_length=29, max_length=29, pattern=r"^lead-[a-f0-9]{24}$")
]


def create_structures_router(store):
    router = APIRouter(prefix="/api/chats/{chat_id}/reports/{report_id}/structures")

    def run(operation, *args):
        try:
            return _call(operation, *args)
        except StructureConnectionRequired as error:
            raise HTTPException(409, str(error)) from None
        except StructureUnavailable as error:
            messages = {
                "structure_access_unverified": (
                    "The repository did not confirm public, non-embargoed access "
                    "for this exact structure. It was not imported."
                ),
                "structure_source_unavailable": (
                    "The public repository could not complete this request. "
                    "Try again shortly."
                ),
                "structure_busy": (
                    "Two structures are already loading. Try again shortly."
                ),
                "structure_missing": (
                    "This public system has no atomic-structure datasets."
                ),
                "structure_ambiguous": (
                    "Several equally close structures are available; the saved "
                    "record does not identify a unique structure."
                ),
                "structure_search_incomplete": (
                    "The source has more structure datasets than the bounded "
                    "search can inspect. Structure matching remains incomplete."
                ),
                "structure_invalid": (
                    "No compatible, validated structure is available for this "
                    "exact saved record. No substitute was generated."
                ),
                "structure_reference_unsupported": (
                    "The public sources could not resolve an unambiguous "
                    "composition for this candidate. Exact cited structures "
                    "remain available; no formula or phase was guessed."
                ),
            }
            code = error.code if error.code in messages else "structure_invalid"
            raise HTTPException(
                422, {"code": code, "message": messages[code]}
            ) from None

    @router.get("")
    def list_structures(chat_id: Identifier, report_id: Identifier):
        return run(store.list, chat_id, report_id)

    @router.post("/references/{lead_id}")
    def find_reference_structures(
        chat_id: Identifier, report_id: Identifier, lead_id: LeadIdentifier
    ):
        return run(store.find_references, chat_id, report_id, lead_id)

    @router.post("/{material_id}")
    def retrieve_structure(
        chat_id: Identifier, report_id: Identifier, material_id: MaterialIdentifier
    ):
        return run(store.retrieve, chat_id, report_id, material_id)

    def content(chat_id, report_id, material_id, attachment, original=False):
        data, metadata = run(
            store.original_content if original else store.content,
            chat_id,
            report_id,
            material_id,
        )
        return Response(
            data,
            media_type="chemical/x-cif" if attachment else "text/plain",
            headers={
                "Content-Disposition": ("attachment" if attachment else "inline")
                + '; filename="'
                + metadata["filename"]
                + '"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Structure-SHA256": metadata["sha256"],
            },
        )

    @router.get("/{material_id}/download")
    def download_structure(
        chat_id: Identifier, report_id: Identifier, material_id: MaterialIdentifier
    ):
        return content(chat_id, report_id, material_id, True)

    @router.get("/{material_id}/content")
    def inline_structure(
        chat_id: Identifier, report_id: Identifier, material_id: MaterialIdentifier
    ):
        return content(chat_id, report_id, material_id, False)

    @router.get("/{material_id}/original")
    def original_structure(
        chat_id: Identifier, report_id: Identifier, material_id: MaterialIdentifier
    ):
        return content(chat_id, report_id, material_id, True, original=True)

    return router
