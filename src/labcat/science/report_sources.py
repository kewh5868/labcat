"""Immutable discovery annotations and report-scoped historical source
replay.

These hashes identify stored versions, not signed evidence. Scientific
claims still require the existing adapter, passage and canonical
evaluation validators.
"""

import hashlib
import json
from copy import deepcopy

ANNOTATION_FIELDS = (
    "kind",
    "is_material_evidence",
    "source_id",
    "record_id",
    "metadata",
    "provenance",
)
VERSION_PREFIX = "discovery-v1:"
_IDENTITY_FIELDS = (
    "source_id",
    "record_id",
    "url",
    "title",
    "source_name",
    "kind",
    "access_scope",
    "provenance_status",
)


def discovery_annotation(source: dict) -> dict:
    """Copy only the bounded scientific annotation already allowed in
    storage."""
    if (
        source.get("kind") != "discovery_reference"
        or source.get("is_material_evidence") is not False
    ):
        raise ValueError("Discovery references cannot be material evidence.")
    annotation = {key: source[key] for key in ANNOTATION_FIELDS if key in source}
    if len(json.dumps(annotation, allow_nan=False)) > 20000:
        raise ValueError("Public source annotation exceeds its size limit.")
    return deepcopy(annotation)


def discovery_version(source: dict) -> str:
    """Keep distinct retrieved responses/passages distinct within each
    project."""
    value = {
        "identity": {key: source[key] for key in ("url", "source_name", "title")},
        "annotation": discovery_annotation(source),
    }
    encoded = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    return VERSION_PREFIX + hashlib.sha256(encoded).hexdigest()


def _identity(source):
    values = tuple(source.get(key) for key in _IDENTITY_FIELDS)
    if (
        any(value is not None and not isinstance(value, str) for value in values)
        or source.get("kind") != "discovery_reference"
        or source.get("is_material_evidence") is not False
        or source.get("access_scope") != "public"
        or source.get("provenance_status") != "verified"
    ):
        raise ValueError("Invalid report discovery source identity.")
    return values


def report_scoped_sources(result: dict, sources: list[dict]) -> list[dict]:
    """Bind an immutable run snapshot to its already-linked source
    identities.

    Callers must supply sources linked to this report, never all project
    sources. Old workspaces deduplicated by URL/title, retaining the
    first annotation. Only those unversioned workspace rows may recover
    their annotation from the run snapshot. New versioned rows and
    direct adapter inputs must match exactly. Workspace identities,
    memberships and pin fields never come from the snapshot.
    """
    if (
        not isinstance(sources, list)
        or len(sources) > 1000
        or any(not isinstance(source, dict) for source in sources)
    ):
        raise ValueError("The report source list is invalid.")
    discovery = result.get("public_discovery")
    if not isinstance(discovery, dict) or "references" not in discovery:
        return deepcopy(sources)
    snapshot = discovery["references"]
    if not isinstance(snapshot, list) or len(snapshot) > 80:
        raise ValueError("The report source snapshot is invalid.")
    retained = {}
    for source in sources:
        if source.get("kind") == "discovery_reference":
            key = _identity(source)
            if key in retained:
                raise ValueError("Ambiguous report source membership.")
            retained[key] = source
    resolved, seen = [], set()
    for reference in snapshot:
        if not isinstance(reference, dict):
            raise ValueError("The report source snapshot is invalid.")
        if reference.get("kind") != "discovery_reference":
            # Combined reports can retain quantitative adapter records here too.
            # This resolver owns discovery annotations only: never import a
            # numeric record from the snapshot or change its canonical evidence.
            continue
        key = _identity(reference)
        if key in seen or key not in retained:
            raise ValueError("The report source snapshot is not uniquely linked.")
        seen.add(key)
        stored = retained[key]
        annotation = discovery_annotation(reference)
        stored_annotation = discovery_annotation(stored)
        version = stored.get("evidence_version")
        if version is not None:
            if version != discovery_version(stored) or version != discovery_version(
                reference
            ):
                raise ValueError("The saved source version does not match its report.")
        elif "id" not in stored or "project_id" not in stored:
            if annotation != stored_annotation:
                raise ValueError("The report source annotation does not match.")
        resolved.append({**deepcopy(stored), **annotation})
    return [
        deepcopy(source)
        for source in sources
        if source.get("kind") != "discovery_reference"
    ] + resolved
