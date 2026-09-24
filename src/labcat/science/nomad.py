"""Bounded, anonymous NOMAD bulk-property queries; no saved candidate
fallback.

The official NOMAD results schema defines BandGap.value in joules:
https://github.com/FAIRmat-NFDI/nomad/blob/develop/nomad/datamodel/results.py
Only reviewed scalar fields become evidence. Source prose is never executed.
"""

import hashlib
import math
import re
from datetime import UTC, datetime

from labcat.public_sources import MAX_SECONDS, _fetch, _json

from .preferences import composition_key as _composition
from .preferences import validate_formula, validate_search_filters
from .rebuild_snapshot import canonical
from .retrieval_budget import bounded_deadline
from .sources import SourceError

SCHEMA_URL = (
    "https://github.com/FAIRmat-NFDI/nomad/blob/develop/nomad/datamodel/results.py"
)
API_URL = "https://nomad-lab.eu/prod/v1/api/v1/entries/query"
JOULES_PER_EV = 1.602176634e-19  # Exact SI conversion, not a material property.
# Quantitative candidates have a separate budget from public reference cards.
# One page still obeys the existing transport byte limit and shared deadline.
MAX_CANDIDATE_RECORDS = 100
INCLUDE = [
    "entry_id",
    "upload_id",
    "published",
    "with_embargo",
    "results.material.chemical_formula_reduced",
    "results.material.elements",
    "results.material.structural_type",
    "results.material.symmetry.space_group_number",
    "results.properties.electronic.band_gap.value",
    "results.properties.electronic.band_gap.type",
    "results.properties.electronic.band_gap.index",
    "results.properties.structures.structure_original.n_sites",
]


def _query(filters):
    groups = []
    if filters.get("formula"):
        groups = [validate_formula(f) for f in filters["formula"].split(",")]
    elif filters.get("chemsys"):
        groups = [s.split("-") for s in filters["chemsys"].split(",")]
    if groups:
        composition = {
            "or": [
                {
                    "results.material.elements": {"all": sorted(set(group))},
                    "results.material.n_elements": len(set(group)),
                }
                for group in groups
            ]
        }
    elif filters.get("elements"):
        composition = {
            "results.material.elements": {"all": filters["elements"].split(",")}
        }
    elif filters.get("entry_ids"):
        composition = {"entry_id": {"any": filters["entry_ids"].split(",")}}
    else:
        return None
    # Query only entries with a reviewed gap field. The upper bound is a request
    # budget/validation choice; zero gaps remain valid. NOMAD rejects gte:0 alone.
    return {
        "and": [
            composition,
            *(
                [{"results.material.n_elements:gte": 2}]
                if filters.get("elements") and len(filters["elements"].split(",")) == 1
                else []
            ),
            *(
                [
                    {
                        "not": {
                            "results.material.elements": {
                                "any": filters["exclude_elements"].split(",")
                            }
                        }
                    }
                ]
                if filters.get("exclude_elements")
                else []
            ),
            *(
                [{"entry_id": {"any": filters["entry_ids"].split(",")}}]
                if filters.get("entry_ids") and (groups or filters.get("elements"))
                else []
            ),
            {"results.material.structural_type": "bulk"},
            {"results.properties.electronic.band_gap.value:lte": 1000 * JOULES_PER_EV},
        ]
    }


def _matches(formula, elements, filters):
    if (
        filters.get("elements")
        and len(filters["elements"].split(",")) == 1
        and len(elements) < 2
    ):
        return False
    if filters.get("formula"):
        return _composition(formula) in {
            _composition(value) for value in filters["formula"].split(",")
        }
    if filters.get("chemsys"):
        return set(elements) in [
            set(value.split("-")) for value in filters["chemsys"].split(",")
        ]
    return (
        set(filters["elements"].split(",")) <= set(elements)
        if filters.get("elements")
        else bool(filters.get("entry_ids"))
    )


def _path(value, *parts):
    for part in parts:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _integer(value, maximum):
    return value if type(value) is int and 1 <= value <= maximum else None


def _gap(gaps):
    if not isinstance(gaps, list) or not 1 <= len(gaps) <= 20:
        return None, None, "Band gap is missing or has an unsupported representation."
    values, types = [], []
    for gap in gaps:
        value = gap.get("value") if isinstance(gap, dict) else None
        if (
            type(value) not in {int, float}
            or not math.isfinite(value)
            or not 0 <= value <= 1000 * JOULES_PER_EV
        ):
            return None, None, "Band-gap values failed scalar/unit-range validation."
        values.append(value / JOULES_PER_EV)
        types.append(gap.get("type"))
    if any(
        not math.isclose(value, values[0], rel_tol=1e-9, abs_tol=1e-9)
        for value in values
    ):
        return (
            None,
            None,
            (
                "Multiple reported band-gap values disagree; no method or spin channel "
                "was selected, averaged, or substituted."
            ),
        )
    direct = None
    if all(kind == types[0] for kind in types) and types[0] in {"direct", "indirect"}:
        direct = types[0] == "direct"
    return values[0], direct, None


def _record(row, filters, response_hash, retrieved_at):
    if (
        not isinstance(row, dict)
        or row.get("published") is not True
        or row.get("with_embargo") is not False
        or any(
            not isinstance(row.get(key), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", row[key])
            for key in ("entry_id", "upload_id")
        )
    ):
        raise ValueError("Unverified public entry identity.")
    material = _path(row, "results", "material")
    if not isinstance(material, dict) or material.get("structural_type") != "bulk":
        raise ValueError("Entry is not a verified bulk structure.")
    formula = material.get("chemical_formula_reduced")
    elements = validate_formula(formula)
    source_elements = material.get("elements")
    if (
        not isinstance(source_elements, list)
        or any(not isinstance(element, str) for element in source_elements)
        or sorted(set(source_elements)) != elements
        or not _matches(formula, elements, filters)
    ):
        raise ValueError("Source composition does not match validated search hints.")
    if set(elements) & set(filters.get("exclude_elements", "").split(",")):
        raise ValueError(
            "Source composition matches the requested exclusion preference."
        )
    gap, direct, issue = _gap(
        _path(row, "results", "properties", "electronic", "band_gap")
    )
    identity = row["entry_id"]
    if filters.get("entry_ids") and identity not in filters["entry_ids"].split(","):
        raise ValueError("Entry does not match the requested prior source identity.")
    # Preserve only requested structured fields; unexpected remote prose never
    # enters the evidence/audit record (the full transport response is hashed).
    selected = {
        "entry_id": identity,
        "upload_id": row["upload_id"],
        "published": True,
        "with_embargo": False,
        "formula": formula,
        "elements": elements,
        "structural_type": "bulk",
        "space_group_number": _path(material, "symmetry", "space_group_number"),
        "n_sites": _path(
            row, "results", "properties", "structures", "structure_original", "n_sites"
        ),
        "band_gap": [
            {key: item[key] for key in ("value", "type", "index") if key in item}
            for item in (
                _path(row, "results", "properties", "electronic", "band_gap") or []
            )
            if isinstance(item, dict)
        ][:20],
    }
    # Invalid source values must not persist as strings/instructions in raw_fields.
    selected["space_group_number"] = _integer(selected["space_group_number"], 230)
    selected["n_sites"] = _integer(selected["n_sites"], 1_000_000)
    selected["band_gap"] = [
        {
            key: value
            for key, value in item.items()
            if (key == "value" and type(value) in {float, int} and math.isfinite(value))
            or (key == "index" and type(value) is int and 0 <= value <= 20)
            or (key == "type" and value in ("direct", "indirect"))
        }
        for item in selected["band_gap"]
    ]
    return {
        "material_id": "nomad:" + identity,
        "formula": formula,
        "elements": elements,
        "nsites": selected["n_sites"],
        "space_group_number": selected["space_group_number"],
        "band_gap_ev": gap,
        "is_gap_direct": direct,
        "is_metal": None,
        "density_g_cm3": None,
        "bulk_modulus_gpa": None,
        "shear_modulus_gpa": None,
        "dielectric_total": None,
        "dielectric_electronic": None,
        "energy_above_hull_ev_atom": None,
        "potential_ferroelectric": None,
        "hazard_status": "unassessed",
        "thin_film_status": "unassessed",
        "method": "NOMAD normalized public bulk entry; method comparability unassessed",
        "source_mode": "live_nomad",
        "source_fields": {
            "formula": "results.material.chemical_formula_reduced",
            "band_gap_ev": (
                "results.properties.electronic.band_gap.value (J / exact J per eV)"
            ),
            "nsites": "results.properties.structures.structure_original.n_sites",
            "space_group_number": "results.material.symmetry.space_group_number",
            "is_gap_direct": "results.properties.electronic.band_gap.type",
        },
        "provenance": {
            "source_url": (
                "https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/"
                f"{identity}"
            ),
            "request_url": API_URL,
            "retrieved_at": retrieved_at,
            "response_sha256": response_hash,
            "raw_fields_sha256": hashlib.sha256(canonical(selected)).hexdigest(),
            "raw_fields": selected,
            "method_reference": SCHEMA_URL,
            "dataset_version": "Live NOMAD v1 response; immutable release not supplied",
            "band_gap_input_unit": "joule",
            "joules_per_electron_volt": JOULES_PER_EV,
        },
        "issues": [issue] if issue else [],
    }


def retrieve_live(filters=None):
    """Read one bounded public page.

    No credentials, arbitrary URLs, or fallback.
    """
    filters = validate_search_filters(filters)
    if "material_ids" in filters:
        raise SourceError("Unsupported identity filter for this repository.")
    query = _query(filters)
    metadata = {
        "mode": "live_nomad",
        "records_retrieved": 0,
        "records_received": 0,
        "records_rejected": 0,
        "sample_limit": MAX_CANDIDATE_RECORDS,
        "sample_limit_reached": False,
        "repository_total": None,
        "sample_truncated": None,
        "query_filters": filters,
        "request_url": API_URL,
        "sampling_order": (
            "distinct_element_count_ascending"
            if filters.get("prefer_simple")
            else "repository_default"
        ),
        "caveats": [
            "Bounded bulk-entry sample with reported gaps; "
            "not an exhaustive materials search.",
            "Dielectric response, stability, toxicity and "
            "application suitability are unassessed.",
            "Conflicting gap values remain unknown; "
            "entries and methods may not be comparable.",
        ],
    }
    if query is None or "is_metal" in filters:
        metadata["caveats"].append(
            "This adapter needs composition hints and cannot establish "
            "a metallicity class."
        )
        return [], metadata
    body = {
        "owner": "public",
        "query": query,
        "pagination": {
            "page_size": MAX_CANDIDATE_RECORDS,
            **(
                {"order_by": "results.material.n_elements", "order": "asc"}
                if filters.get("prefer_simple")
                else {}
            ),
        },
        "required": {"include": INCLUDE},
    }
    try:
        raw, _ = _fetch("nomad", {}, bounded_deadline(MAX_SECONDS), body)
        payload = _json(raw)
        rows = payload.get("data")
        if (
            payload.get("owner") != "public"
            or not isinstance(rows, list)
            or len(rows) > MAX_CANDIDATE_RECORDS
        ):
            raise ValueError("Invalid public response scope or budget.")
        pagination = payload.get("pagination", {})
        if not isinstance(pagination, dict):
            raise ValueError("Invalid public pagination metadata.")
        total = pagination.get("total")
        if total is not None and (
            type(total) is not int or not len(rows) <= total <= 1_000_000_000_000
        ):
            raise ValueError("Invalid public repository count.")
        cursor = pagination.get("next_page_after_value")
        if cursor is not None and (
            not isinstance(cursor, str) or not 0 < len(cursor) <= 1000
        ):
            raise ValueError("Invalid public pagination marker.")
        # Never follow a remote pagination cursor. The reported total describes
        # query matches, not validated records or distinct material compositions.
        truncated = (
            True
            if cursor or (total is not None and total > len(rows))
            else (False if total is not None else None)
        )
        if truncated:
            metadata["caveats"].append(
                "Additional repository matches were not retrieved; "
                "only one bounded page was examined."
            )
        elif truncated is None:
            metadata["caveats"].append(
                "The repository did not report a total; "
                "sample completeness could not be determined."
            )
        response_hash = hashlib.sha256(raw).hexdigest()
        retrieved_at = datetime.now(UTC).isoformat()
        records, rejected, seen, duplicate_ids = [], 0, set(), set()
        for row in rows:
            identity = row.get("entry_id") if isinstance(row, dict) else None
            if isinstance(identity, str):
                if identity in seen:
                    duplicate_ids.add(identity)
                seen.add(identity)
        for row in rows:
            try:
                if isinstance(row, dict) and row.get("entry_id") in duplicate_ids:
                    raise ValueError("Duplicate entry identity is ambiguous.")
                record = _record(row, filters, response_hash, retrieved_at)
                records.append(record)
            except (ValueError, TypeError, KeyError, OverflowError):
                rejected += 1
        metadata.update(
            records_retrieved=len(records),
            records_received=len(rows),
            records_rejected=rejected,
            sample_limit_reached=len(rows) == MAX_CANDIDATE_RECORDS,
            repository_total=total,
            sample_truncated=truncated,
            response_sha256=response_hash,
            retrieved_at=retrieved_at,
        )
        return records, metadata
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as error:
        raise SourceError(
            "Live public NOMAD retrieval failed validation or was unavailable; "
            "no saved candidates were substituted."
        ) from error
