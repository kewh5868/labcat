"""Approved public sources; raw user/model text never reaches this
module."""

import hashlib
import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import threading
import time
from datetime import UTC, datetime
from importlib.resources import files
from urllib.parse import urlencode

from labcat.credentials import unique_json_object

from .preferences import (
    matches_composition_scope,
    validate_formula,
    validate_search_filters,
)
from .rebuild_snapshot import COHORT, UPSTREAM_SHA256, canonical

MP_HOST = "api.materialsproject.org"
MP_PATH = "/materials/summary/"
MAX_BYTES = 2_000_000
MAX_PROBE_BYTES = 16_384
MAX_RECORDS = 100
NETWORK_SECONDS = 18
SNAPSHOT_SHA256 = "4d1d6f4ee3153199822420a6599c80e300052454e71003badf541c3d8dbf8a4e"
MP_FIELDS = (
    "material_id",
    "formula_pretty",
    "elements",
    "nsites",
    "symmetry",
    "band_gap",
    "e_total",
    "e_electronic",
    "energy_above_hull",
    "is_stable",
    "deprecated",
    "origins",
    "last_updated",
    "density",
    "bulk_modulus",
    "shear_modulus",
    "is_metal",
    "is_gap_direct",
)
PAPER_URL = "https://www.nature.com/articles/sdata2016134"
MP_DOCS_URL = (
    "https://docs.materialsproject.org/downloading-data/using-the-api/querying-data"
)


class SourceError(ValueError):
    """A public source is unavailable or does not satisfy the data
    contract."""


def _number(value, *, minimum=0, maximum=1_000_000):
    if (
        type(value) not in (int, float)
        or not minimum <= value <= maximum
        or not math.isfinite(value)
    ):
        return None
    return float(value)


def _identity(material_id, formula):
    if not isinstance(material_id, str) or not re.fullmatch(
        r"mp-\d{1,10}", material_id
    ):
        raise SourceError("Source record has no supported Materials Project identity.")
    try:
        elements = validate_formula(formula)
    except ValueError as error:
        raise SourceError(str(error)) from None
    return material_id, formula, elements


def _record(fields: dict, *, mode: str, provenance: dict) -> dict:
    snapshot = mode == "public_snapshot"
    identity = fields.get("material_id")
    formula = fields.get("formula" if snapshot else "formula_pretty")
    material_id, formula, elements = _identity(identity, formula)
    if not snapshot and fields.get("deprecated") is not False:
        raise SourceError(
            "Source record is deprecated or has unknown deprecation status."
        )
    if not snapshot and fields.get("elements") != elements:
        # API element order is not meaningful; compare sets after type validation.
        supplied = fields.get("elements")
        if not isinstance(supplied, list) or any(
            not isinstance(e, str) for e in supplied
        ):
            raise SourceError("Source composition is missing or malformed.")
        if sorted(set(supplied)) != elements:
            raise SourceError("Source formula and element fields disagree.")
    mapping = {
        "band_gap_ev": "band_gap",
        "dielectric_total": "poly_total" if snapshot else "e_total",
        "dielectric_electronic": "poly_electronic" if snapshot else "e_electronic",
        "energy_above_hull_ev_atom": "energy_above_hull",
    }
    values = {name: _number(fields.get(field)) for name, field in mapping.items()}
    values["density_g_cm3"] = _number(fields.get("density"))
    for name, field in (
        ("bulk_modulus_gpa", "bulk_modulus"),
        ("shear_modulus_gpa", "shear_modulus"),
    ):
        value = fields.get(field)
        values[name] = _number(value.get("vrh")) if isinstance(value, dict) else None
    booleans = {
        name: fields.get(name) if type(fields.get(name)) is bool else None
        for name in ("is_metal", "is_gap_direct")
    }
    nsites = fields.get("nsites")
    if type(nsites) is not int or not 1 <= nsites <= 1_000_000:
        nsites = None
    space_group = (
        fields.get("space_group")
        if snapshot
        else (fields.get("symmetry") or {}).get("number")
    )
    if type(space_group) is not int or not 1 <= space_group <= 230:
        space_group = None
    potential = fields.get("pot_ferroelectric") if snapshot else None
    if type(potential) is not bool:
        potential = None
    stable = fields.get("is_stable") if not snapshot else None
    if type(stable) is not bool:
        stable = None
    issues = []
    hull = values["energy_above_hull_ev_atom"]
    if hull is not None and stable is not None and stable != (hull <= 1e-8):
        values["energy_above_hull_ev_atom"] = None
        issues.append(
            "Conflicting source stability indicators; stability scoring omitted."
        )
    for name, field in mapping.items():
        if fields.get(field) is not None and values[name] is None:
            issues.append(
                f"Invalid or conflicting source field {field}; treated as unknown."
            )
    method = (
        "DFPT with GGA/PBE(+U); scalar is the reported arithmetic mean "
        "of tensor eigenvalues"
        if snapshot
        else "Materials Project computed summary; exact task methodology "
        "requires follow-up"
    )
    return {
        "material_id": material_id,
        "formula": formula,
        "elements": elements,
        "space_group_number": space_group,
        "nsites": nsites,
        **values,
        **booleans,
        "potential_ferroelectric": potential,
        "hazard_status": "unassessed",
        "thin_film_status": "unassessed",
        "method": method,
        "source_fields": {**mapping, "nsites": "nsites"},
        "source_mode": mode,
        "provenance": provenance,
        "issues": issues,
    }


def load_snapshot() -> tuple[list[dict], dict]:
    raw = (
        files("labcat.science")
        .joinpath("data/mp_dielectric_snapshot.json")
        .read_bytes()
    )
    if hashlib.sha256(raw).hexdigest() != SNAPSHOT_SHA256:
        raise SourceError(
            "Bundled public snapshot checksum failed; no facts were used."
        )
    data = json.loads(raw)
    if (
        data.get("schema_version") != 1
        or data.get("upstream_sha256") != UPSTREAM_SHA256
    ):
        raise SourceError("Unsupported public snapshot provenance.")
    records = []
    for entry in data["records"]:
        fields = entry["fields"]
        if hashlib.sha256(canonical(fields)).hexdigest() != entry["fields_sha256"]:
            raise SourceError("A public snapshot record failed its integrity check.")
        provenance = {
            "source_url": data["source_url"],
            "dataset_version": data["dataset_version"],
            "retrieved_at": data["license_checked_on"],
            "upstream_sha256": UPSTREAM_SHA256,
            "upstream_row_index": entry["upstream_row_index"],
            "upstream_row_sha256": entry["upstream_row_sha256"],
            "raw_fields_sha256": entry["fields_sha256"],
            "raw_fields": fields,
            "method_reference": PAPER_URL,
        }
        records.append(_record(fields, mode="public_snapshot", provenance=provenance))
    return records, {
        "mode": "public_snapshot",
        "source_url": data["source_url"],
        "dataset_version": data["dataset_version"],
        "snapshot_sha256": SNAPSHOT_SHA256,
        "cohort_formulas": list(COHORT),
        "records_retrieved": len(records),
        "absent_cohort_formulas": data["absent_cohort_formulas"],
        "coverage": (
            "Fixed historical cohort; not an exhaustive Materials Project search."
        ),
    }


def _public_addresses(deadline: float) -> list[str]:
    result = []
    error = []
    complete = threading.Event()

    def resolve():
        try:
            result.extend(socket.getaddrinfo(MP_HOST, 443, type=socket.SOCK_STREAM))
        except OSError:
            error.append(True)
        finally:
            complete.set()

    threading.Thread(target=resolve, daemon=True, name="mp-public-dns").start()
    if not complete.wait(max(0, min(4, deadline - time.monotonic()))) or error:
        raise SourceError("Materials Project DNS lookup was unavailable.")
    addresses = sorted({item[4][0] for item in result})
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise SourceError("Materials Project resolved to a prohibited network address.")
    return addresses


def _request_mp_data(
    api_key: str,
    filters: dict | None = None,
    *,
    metadata_only: bool = False,
    structure_id: str | None = None,
) -> tuple[dict, str, str]:
    """Fixed host/path, public IP, verified TLS; no redirects or
    environment proxy."""
    if not isinstance(api_key, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{16,256}", api_key
    ):
        raise SourceError("Materials Project API key format is invalid.")
    filters = validate_search_filters(filters)
    if type(metadata_only) is not bool or (metadata_only and filters):
        raise SourceError("Unsupported Materials Project connection probe options.")
    if structure_id is not None and (
        not isinstance(structure_id, str)
        or not re.fullmatch(r"mp-\d{1,10}", structure_id)
        or metadata_only
        or filters
    ):
        raise SourceError("Unsupported Materials Project structure identity.")
    byte_limit = MAX_PROBE_BYTES if metadata_only else MAX_BYTES
    # Sampling preferences belong to Labcat, not the provider's API schema.
    # Keep the provider's deterministic ID sampling; composition preferences
    # still apply during local ranking. Forwarding this internal flag makes the
    # live endpoint reject otherwise valid searches with HTTP 400.
    request_filters = {
        key: value
        for key, value in filters.items()
        if key not in {"prefer_simple", "composition_scope"}
    }
    # The official SummaryRester range mapping uses nelements_min/max for
    # num_elements. Translate our internal scope instead of leaking it upstream.
    # https://materialsproject.github.io/api/_modules/mp_api/client/routes/materials/summary.html
    if filters.get("composition_scope") == "multi_element":
        request_filters["nelements_min"] = "2"
    elif filters.get("composition_scope") == "single_element":
        request_filters.update(nelements_min="1", nelements_max="1")
    query = urlencode(
        {
            **request_filters,
            **({"material_ids": structure_id} if structure_id else {}),
            "deprecated": "false",
            # Keep existing saved evidence IDs stable after the upstream AlphaID
            # default changed. The source must return, not locally invent, IDs.
            "id_format": "legacy",
            "_fields": (
                "material_id,formula_pretty,elements,deprecated,structure,last_updated"
                if structure_id
                else "material_id" if metadata_only else ",".join(MP_FIELDS)
            ),
            "_limit": 1 if metadata_only or structure_id else MAX_RECORDS,
            "_skip": 0,
            "_sort_fields": "material_id",
        }
    )
    path = MP_PATH + "?" + query
    from .retrieval_budget import bounded_deadline

    try:
        deadline = bounded_deadline(NETWORK_SECONDS)
    except ValueError as error:
        raise SourceError("The public repository time budget was exhausted.") from error
    addresses = _public_addresses(deadline)
    connection = http.client.HTTPSConnection(MP_HOST, timeout=NETWORK_SECONDS)
    try:
        remaining = max(0.1, deadline - time.monotonic())
        raw_socket = socket.create_connection((addresses[0], 443), timeout=remaining)
        try:
            secured_socket = ssl.create_default_context().wrap_socket(
                raw_socket, server_hostname=MP_HOST
            )
            connection.sock = secured_socket
        except Exception:
            raw_socket.close()
            raise
        secured_socket.settimeout(max(0.1, deadline - time.monotonic()))
        connection.request(
            "GET",
            path,
            headers={
                "X-API-KEY": api_key,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "Labcat/0.1 public-materials-triage",
            },
        )
        secured_socket.settimeout(max(0.1, deadline - time.monotonic()))
        response = connection.getresponse()
        if response.status != 200:
            raise SourceError(
                f"Materials Project returned HTTP {response.status}; "
                "no response text or credentials retained."
            )
        if (
            response.getheader("Content-Type", "").split(";", 1)[0].strip()
            != "application/json"
        ):
            raise SourceError("Materials Project returned an unsupported content type.")
        if response.getheader("Content-Encoding", "identity") != "identity":
            raise SourceError(
                "Compressed Materials Project responses are not accepted."
            )
        length = response.getheader("Content-Length")
        if length and (not length.isdigit() or int(length) > byte_limit):
            raise SourceError("Materials Project response exceeded the size budget.")
        pieces = []
        size = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SourceError("Materials Project exceeded the time budget.")
            secured_socket.settimeout(remaining)
            chunk = response.read1(min(65536, byte_limit + 1 - size))
            if not chunk:
                break
            pieces.append(chunk)
            size += len(chunk)
            if size > byte_limit:
                raise SourceError(
                    "Materials Project response exceeded the size budget."
                )
        raw = b"".join(pieces)
        return (
            json.loads(raw, object_pairs_hook=unique_json_object),
            hashlib.sha256(raw).hexdigest(),
            "https://" + MP_HOST + path,
        )
    except SourceError:
        raise
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise SourceError(
            "Materials Project public API request failed; "
            "no credentials or response text retained."
        ) from error
    finally:
        connection.close()


def _request_mp(api_key: str, filters: dict | None = None) -> tuple[dict, str, str]:
    """Preserve the scientific adapter entry point and its fixed field
    contract."""
    return _request_mp_data(api_key, filters)


def probe_connection(api_key: str) -> dict:
    """Check one public legacy ID through the same hardened source
    transport.

    Only a count and the requested format leave this helper. Response
    bodies, request headers, arbitrary URLs and credentials are never
    retained.
    """
    payload, _, _ = _request_mp_data(api_key, metadata_only=True)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > 1:
        raise SourceError("Materials Project returned an unsupported probe response.")
    if any(
        not isinstance(row, dict)
        or not isinstance(row.get("material_id"), str)
        or not re.fullmatch(r"mp-\d{1,10}", row["material_id"])
        for row in rows
    ):
        raise SourceError(
            "Materials Project did not return the requested legacy identity format."
        )
    return {"records_checked": len(rows), "id_format": "legacy"}


def retrieve_live(api_key: str, filters: dict | None = None) -> tuple[list[dict], dict]:
    filters = validate_search_filters(filters)
    if "entry_ids" in filters:
        raise SourceError("Unsupported identity filter for this repository.")
    payload, digest, query_url = (
        _request_mp(api_key, filters) if filters else _request_mp(api_key)
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise SourceError("Materials Project response has no supported record list.")
    rows = payload["data"]
    if len(rows) > MAX_RECORDS:
        raise SourceError("Materials Project returned too many records.")
    retrieved = datetime.now(UTC).isoformat()
    records, rejected = [], 0
    seen, duplicate_ids = set(), set()
    for row in rows:
        identity = row.get("material_id") if isinstance(row, dict) else None
        if isinstance(identity, str):
            if identity in seen:
                duplicate_ids.add(identity)
            seen.add(identity)
    for raw in rows:
        if not isinstance(raw, dict) or (
            isinstance(raw.get("material_id"), str)
            and raw["material_id"] in duplicate_ids
        ):
            # Repeated source identities may have contradictory versions/values.
            # Do not arbitrarily select one or merge their properties.
            rejected += 1
            continue
        # Unknown narrative fields and embedded instructions are not accepted.
        fields = {key: raw.get(key) for key in MP_FIELDS if key != "origins"}
        if not isinstance(fields.get("symmetry"), dict):
            fields["symmetry"] = {}
        fields["symmetry"] = {"number": fields["symmetry"].get("number")}
        updated = fields.get("last_updated")
        fields["last_updated"] = (
            updated
            if isinstance(updated, str) and re.fullmatch(r"[0-9T:.+Z-]{10,40}", updated)
            else None
        )
        try:
            record = _record(fields, mode="live_materials_project", provenance={})
            if not matches_composition_scope(
                record["formula"], filters.get("composition_scope")
            ):
                raise SourceError("Source record does not match the composition scope.")
            if "material_ids" in filters and record["material_id"] not in filters[
                "material_ids"
            ].split(","):
                raise SourceError(
                    "Source record does not match the prior material identity."
                )
            if "formula" in filters and record["formula"] not in filters[
                "formula"
            ].split(","):
                raise SourceError(
                    "Source record does not match the formula search hint."
                )
            if "elements" in filters and not set(filters["elements"].split(",")) <= set(
                record["elements"]
            ):
                raise SourceError(
                    "Source record does not match the element search hint."
                )
            if (
                "elements" in filters
                and len(filters["elements"].split(",")) == 1
                and not filters.get("formula")
                and not filters.get("chemsys")
                and len(record["elements"]) < 2
            ):
                # Compound-class discovery must not substitute the pure element.
                # An explicit formula/system request retains elemental records.
                continue
            if "chemsys" in filters and "-".join(record["elements"]) not in filters[
                "chemsys"
            ].split(","):
                raise SourceError(
                    "Source record does not match the chemical-system search hint."
                )
            if "is_metal" in filters and record["is_metal"] is not (
                filters["is_metal"] == "true"
            ):
                raise SourceError(
                    "Source record does not support the selected metallicity filter."
                )
            # Keep raw accepted scalar values, never malformed narrative payloads.
            # The digest covers the allowlisted input before invalid fields are dropped.
            accepted_fields = {
                "material_id": record["material_id"],
                "formula_pretty": record["formula"],
                "elements": record["elements"],
                "deprecated": False,
                "last_updated": fields["last_updated"],
                "symmetry": {"number": record["space_group_number"]},
                "nsites": record["nsites"],
            }
            accepted_fields.update(
                {
                    source_field: fields[source_field]
                    for field, source_field in record["source_fields"].items()
                    if field != "nsites" and record[field] is not None
                }
            )
            if type(fields.get("is_stable")) is bool:
                accepted_fields["is_stable"] = fields["is_stable"]
            for normal, source in (
                ("density_g_cm3", "density"),
                ("bulk_modulus_gpa", "bulk_modulus"),
                ("shear_modulus_gpa", "shear_modulus"),
            ):
                if record[normal] is not None:
                    accepted_fields[source] = (
                        {"vrh": record[normal]}
                        if "modulus" in source
                        else record[normal]
                    )
                    record["source_fields"][normal] = (
                        source + ".vrh" if "modulus" in source else source
                    )
            for name in ("is_metal", "is_gap_direct"):
                if record[name] is not None:
                    accepted_fields[name] = record[name]
                    record["source_fields"][name] = name
            provenance = {
                "source_url": "https://materialsproject.org/materials/"
                + record["material_id"],
                "query_url": query_url,
                "retrieved_at": retrieved,
                "response_sha256": digest,
                "raw_fields_sha256": hashlib.sha256(canonical(fields)).hexdigest(),
                "raw_fields": accepted_fields,
                "raw_fields_note": (
                    "Only validated scalar fields are retained; the field digest "
                    "covers all allowlisted input before invalid values were dropped."
                ),
                "method_reference": MP_DOCS_URL,
                "dataset_version": "live summary; exact database release unavailable",
            }
            record["provenance"] = provenance
            records.append(record)
        except (SourceError, TypeError, ValueError):
            rejected += 1
    return records, {
        "mode": "live_materials_project",
        "source_url": query_url,
        "response_sha256": digest,
        "retrieved_at": retrieved,
        "search_filters": filters,
        "records_retrieved": len(records),
        "records_rejected": rejected,
        "record_limit": MAX_RECORDS,
        "coverage": (
            "One bounded live API page matching validated search preferences; "
            "not exhaustive and not restricted to a fixed formula cohort. "
            "No cross-version joins or saved candidate substitutions."
        ),
    }
