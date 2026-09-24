"""Fresh anonymous reads of one immutable, public dielectric dataset
release.

Only reviewed scalar columns become evidence. Never loads the historical
bundled fixture, chooses a candidate cohort, instantiates MSON objects,
or follows links from source rows. See docs/public-dielectric-dataset.md
for attribution and scope.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import re
import socket
import ssl
import zlib
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlsplit

from labcat.credentials import unique_json_object
from labcat.public_sources import _addresses, _remaining

from .preferences import composition_key, validate_formula, validate_search_filters
from .retrieval_budget import bounded_deadline
from .sources import SourceError

UPSTREAM_URL = "https://ndownloader.figshare.com/files/13213475"
UPSTREAM_SHA256 = "8eb24812148732786cd7c657eccfc6b5ee66533429c2cfbcc4f0059c0295e8b6"
DATASET_URL = "https://doi.org/10.6084/m9.figshare.7108790.v2"
DATASET_VERSION = "Figshare 7108790 version 2 (2018-10-08)"
PAPER_URL = "https://www.nature.com/articles/sdata2016134"
METHOD = (
    "Historical DFPT with GGA/PBE(+U); reported polycrystalline scalars are "
    "arithmetic means of dielectric-tensor eigenvalues"
)
MAX_COMPRESSED_BYTES = 1_000_000
MAX_UNCOMPRESSED_BYTES = 8_000_000
MAX_RECORDS = 1056
MAX_SECONDS = 18
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 500_000
_DOWNLOAD_HOST = "ndownloader.figshare.com"
_DOWNLOAD_PATH = "/files/13213475"
_OBJECT_HOST = "s3-eu-west-1.amazonaws.com"
_OBJECT_PATH = "/pfigshare-u-files/13213475/dielectric_constant.json.gz"
_SIGNED_QUERY_KEYS = {
    "X-Amz-Algorithm",
    "X-Amz-Credential",
    "X-Amz-Date",
    "X-Amz-Expires",
    "X-Amz-SignedHeaders",
    "X-Amz-Signature",
}
_COLUMNS = (
    "material_id",
    "formula",
    "nsites",
    "space_group",
    "volume",
    "structure",
    "band_gap",
    "e_electronic",
    "e_total",
    "n",
    "poly_electronic",
    "poly_total",
    "pot_ferroelectric",
    "cif",
    "meta",
    "poscar",
)
_NUMBER_FIELDS = {
    "band_gap_ev": ("band_gap", 1000),
    "dielectric_total": ("poly_total", 1_000_000),
    "dielectric_electronic": ("poly_electronic", 1_000_000),
    "refractive_index": ("n", 10_000),
    "cell_volume_angstrom3": ("volume", 1_000_000),
}


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _redirect_path(location):
    """Accept only the reviewed Figshare object; no source-supplied URL
    freedom."""
    if (
        not isinstance(location, str)
        or len(location) > 4096
        or any(ord(char) < 33 or ord(char) > 126 for char in location)
    ):
        raise ValueError("Unsupported public dataset redirect.")
    target = urlsplit(location)
    if (
        target.scheme != "https"
        or target.netloc != _OBJECT_HOST
        or target.path != _OBJECT_PATH
        or target.fragment
    ):
        raise ValueError("Unsupported public dataset redirect.")
    pairs = parse_qsl(
        target.query, keep_blank_values=True, strict_parsing=True, max_num_fields=6
    )
    query = dict(pairs)
    if (
        len(query) != len(pairs)
        or set(query) != _SIGNED_QUERY_KEYS
        or (
            query["X-Amz-Algorithm"] != "AWS4-HMAC-SHA256"
            or query["X-Amz-SignedHeaders"] != "host"
            or re.fullmatch(r"[a-fA-F0-9]{64}", query["X-Amz-Signature"]) is None
            or re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", query["X-Amz-Date"]) is None
            or re.fullmatch(r"[0-9]{1,6}", query["X-Amz-Expires"]) is None
            or not 1 <= int(query["X-Amz-Expires"]) <= 604800
            or re.fullmatch(
                r"[A-Za-z0-9]{1,128}/[0-9]{8}/eu-west-1/s3/aws4_request",
                query["X-Amz-Credential"],
            )
            is None
        )
    ):
        raise ValueError("Unsupported public dataset signed download.")
    return target.path + "?" + target.query


def _download(deadline):
    host, path = _DOWNLOAD_HOST, _DOWNLOAD_PATH
    for hop in range(2):
        connection = http.client.HTTPSConnection(host, timeout=_remaining(deadline))
        try:
            addresses = _addresses(host, deadline)
            raw_socket = socket.create_connection(
                (addresses[0], 443), timeout=_remaining(deadline)
            )
            try:
                raw_socket.settimeout(_remaining(deadline))
                secured = ssl.create_default_context().wrap_socket(
                    raw_socket, server_hostname=host
                )
                connection.sock = secured
            except Exception:
                raw_socket.close()
                raise
            secured.settimeout(_remaining(deadline))
            connection.request(
                "GET",
                path,
                headers={
                    "Accept": "application/gzip, application/octet-stream",
                    "Accept-Encoding": "identity",
                    "User-Agent": "Labcat/0.1 public-dielectric-dataset",
                },
            )
            secured.settimeout(_remaining(deadline))
            response = connection.getresponse()
            if response.status == 302 and hop == 0:
                path = _redirect_path(response.getheader("Location"))
                host = _OBJECT_HOST
                continue
            if response.status != 200:
                raise ValueError(
                    "Public dataset unavailable or redirected outside its route."
                )
            if (
                response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
                not in {
                    "application/gzip",
                    "application/x-gzip",
                    "application/octet-stream",
                }
                or response.getheader("Content-Encoding", "identity") != "identity"
            ):
                raise ValueError("Unsupported public dataset content type or encoding.")
            length = response.getheader("Content-Length")
            if length is not None and (
                re.fullmatch(r"[0-9]{1,9}", length) is None
                or int(length) > MAX_COMPRESSED_BYTES
            ):
                raise ValueError("Public dataset exceeded its compressed size budget.")
            chunks, size = [], 0
            while True:
                secured.settimeout(_remaining(deadline))
                chunk = response.read1(min(65536, MAX_COMPRESSED_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_COMPRESSED_BYTES:
                    raise ValueError(
                        "Public dataset exceeded its compressed size budget."
                    )
                chunks.append(chunk)
            if length is not None and size != int(length):
                raise ValueError("Public dataset response was truncated.")
            _remaining(deadline)
            return b"".join(chunks)
        finally:
            connection.close()
    raise ValueError("Public dataset redirect budget exhausted.")


def _finite_float(value):
    if len(value) > 64:
        raise ValueError("Public dataset numeric token exceeded its limit.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Public dataset contains a nonfinite number.")
    return number


def _bounded_int(value):
    if len(value) > 32:
        raise ValueError("Public dataset integer token exceeded its limit.")
    return int(value)


def _invalid_constant(_value):
    raise ValueError("Public dataset contains a nonfinite constant.")


def _json_limits(raw, deadline):
    # Check nesting before json.loads to bound recursion even in a corrupted file.
    depth, quoted, escaped = 0, False, False
    for index, char in enumerate(raw):
        if index % 65536 == 0:
            _remaining(deadline)
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (91, 123):
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("Public dataset JSON nesting exceeded its limit.")
        elif char in (93, 125):
            depth -= 1


def _decode(raw, deadline):
    if (
        not isinstance(raw, bytes)
        or len(raw) > MAX_COMPRESSED_BYTES
        or (hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256)
    ):
        raise ValueError(
            "Public dataset checksum or compressed size differs "
            "from the reviewed version."
        )
    decoder, output = zlib.decompressobj(16 + zlib.MAX_WBITS), bytearray()
    for offset in range(0, len(raw), 65536):
        _remaining(deadline)
        output.extend(
            decoder.decompress(
                raw[offset : offset + 65536], MAX_UNCOMPRESSED_BYTES + 1 - len(output)
            )
        )
        if len(output) > MAX_UNCOMPRESSED_BYTES or decoder.unconsumed_tail:
            raise ValueError("Public dataset exceeded its uncompressed size budget.")
    if not decoder.eof or decoder.unused_data:
        raise ValueError(
            "Public dataset has a truncated or multiple-member gzip stream."
        )
    _json_limits(output, deadline)
    payload = json.loads(
        output.decode("utf-8"),
        object_pairs_hook=unique_json_object,
        parse_constant=_invalid_constant,
        parse_int=_bounded_int,
        parse_float=_finite_float,
    )
    pending, count = [payload], 0
    while pending:
        value = pending.pop()
        count += 1
        if count % 4096 == 0:
            _remaining(deadline)
        if count > MAX_JSON_NODES:
            raise ValueError("Public dataset JSON node count exceeded its limit.")
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str) and len(value) > 200_000:
            raise ValueError("Public dataset string exceeded its limit.")
    if (
        not isinstance(payload, dict)
        or set(payload) != {"index", "columns", "data"}
        or (
            payload["columns"] != list(_COLUMNS)
            or not isinstance(payload["data"], list)
            or not 1 <= len(payload["data"]) <= MAX_RECORDS
            or not isinstance(payload["index"], list)
            or any(type(index) is not int for index in payload["index"])
            or payload["index"] != list(range(len(payload["data"])))
            or any(
                not isinstance(row, list) or len(row) != len(_COLUMNS)
                for row in payload["data"]
            )
        )
    ):
        raise ValueError(
            "Public dataset schema, index, or row count failed validation."
        )
    _remaining(deadline)
    return [dict(zip(_COLUMNS, row, strict=True)) for row in payload["data"]]


def _number(value, maximum):
    return (
        value
        if type(value) in (int, float)
        and math.isfinite(value)
        and 0 <= value <= maximum
        else None
    )


def _record(row, index, duplicate_ids, retrieved_at):
    source_id, formula = row["material_id"], row["formula"]
    if (
        not isinstance(source_id, str)
        or re.fullmatch(r"mp-[0-9]{1,10}", source_id) is None
    ):
        raise ValueError("Public dataset record identity is unsupported.")
    elements = validate_formula(formula)
    values, selected, issues = {}, {"material_id": source_id, "formula": formula}, []
    for target, (field, maximum) in _NUMBER_FIELDS.items():
        value = _number(row[field], maximum)
        if target in {"cell_volume_angstrom3", "refractive_index"} and value == 0:
            value = None
        values[target], selected[field] = value, value
        if row[field] is not None and value is None:
            issues.append(f"Invalid source field {field}; treated as unknown.")
    for field, maximum in (("nsites", 1_000_000), ("space_group", 230)):
        value = row[field]
        selected[field] = (
            value if type(value) is int and 1 <= value <= maximum else None
        )
        if value is not None and selected[field] is None:
            issues.append(f"Invalid source field {field}; treated as unknown.")
    potential = row["pot_ferroelectric"]
    selected["pot_ferroelectric"] = potential if type(potential) is bool else None
    if potential is not None and selected["pot_ferroelectric"] is None:
        issues.append("Invalid potential-ferroelectric flag; treated as unknown.")
    identity = "dielectric:" + source_id
    if source_id in duplicate_ids:
        identity += ":row" + str(index)
        issues.append(
            "Repeated original source identity; this versioned row remains separate."
        )
    return {
        "material_id": identity,
        "source_record_id": source_id,
        "formula": formula,
        "elements": elements,
        **values,
        "nsites": selected["nsites"],
        "space_group_number": selected["space_group"],
        "potential_ferroelectric": selected["pot_ferroelectric"],
        "energy_above_hull_ev_atom": None,
        "is_metal": None,
        "is_gap_direct": None,
        "density_g_cm3": None,
        "bulk_modulus_gpa": None,
        "shear_modulus_gpa": None,
        "hazard_status": "unassessed",
        "thin_film_status": "unassessed",
        "method": METHOD,
        "source_mode": "live_public_dielectric",
        "source_fields": {
            **{target: field for target, (field, _) in _NUMBER_FIELDS.items()},
            "formula": "formula",
            "nsites": "nsites",
            "space_group_number": "space_group",
            "potential_ferroelectric": "pot_ferroelectric",
        },
        "provenance": {
            "source_url": DATASET_URL,
            "request_url": UPSTREAM_URL,
            "dataset_version": DATASET_VERSION,
            "retrieved_at": retrieved_at,
            "source_record_id": source_id,
            "upstream_row_index": index,
            "response_sha256": UPSTREAM_SHA256,
            "upstream_sha256": UPSTREAM_SHA256,
            "upstream_row_sha256": hashlib.sha256(_canonical(row)).hexdigest(),
            "raw_fields_sha256": hashlib.sha256(_canonical(selected)).hexdigest(),
            "raw_fields": selected,
            "method_reference": PAPER_URL,
            "source_license": "MIT",
            "original_dataset_url": "https://doi.org/10.5061/dryad.ph81h",
        },
        "issues": issues,
    }


def _matches(record, filters):
    elements = set(record["elements"])
    if filters.get("formula") and composition_key(record["formula"]) not in {
        composition_key(formula) for formula in filters["formula"].split(",")
    }:
        return False
    if filters.get("chemsys") and elements not in [
        set(chemsys.split("-")) for chemsys in filters["chemsys"].split(",")
    ]:
        return False
    if filters.get("elements") and not set(filters["elements"].split(",")) <= elements:
        return False
    if (
        filters.get("elements")
        and len(filters["elements"].split(",")) == 1
        and not filters.get("formula")
        and not filters.get("chemsys")
        and len(elements) < 2
    ):
        return False
    if (
        filters.get("exclude_elements")
        and set(filters["exclude_elements"].split(",")) & elements
    ):
        return False
    if filters.get("material_ids") and record["source_record_id"] not in filters[
        "material_ids"
    ].split(","):
        return False
    return filters.get("has_props") != "dielectric" or any(
        record[field] is not None
        for field in ("dielectric_total", "dielectric_electronic")
    )


def retrieve_live(filters=None):
    """Fetch and inspect the entire pinned release; return every scope
    match.

    All supplied composition constraints are conjunctive. Unsupported
    properties or repository identity filters fail explicitly instead of
    broadening scope. No cache, bundled data, model claims, or prompt
    values supply evidence.
    """
    try:
        filters = validate_search_filters(filters)
        if (
            set(filters) & {"entry_ids", "is_metal"}
            or filters.get("has_props") == "elasticity"
        ):
            raise ValueError("Unsupported public dielectric dataset filter.")
    except ValueError:
        raise SourceError(
            "Unsupported or invalid filter for the public dielectric dataset."
        ) from None
    try:
        deadline = bounded_deadline(MAX_SECONDS)
        raw = _download(deadline)
        rows = _decode(raw, deadline)
        retrieved_at = datetime.now(UTC).isoformat()
        counts = Counter(
            row["material_id"] for row in rows if isinstance(row["material_id"], str)
        )
        duplicates = {identity for identity, count in counts.items() if count > 1}
        records, rejected, filtered = [], 0, 0
        for index, row in enumerate(rows):
            _remaining(deadline)
            try:
                record = _record(row, index, duplicates, retrieved_at)
            except (ValueError, TypeError, KeyError, OverflowError):
                rejected += 1
                continue
            if _matches(record, filters):
                records.append(record)
            else:
                filtered += 1
        if filters.get("prefer_simple"):
            records.sort(
                key=lambda record: (len(record["elements"]), record["material_id"])
            )
        _remaining(deadline)
        return records, {
            "mode": "live_public_dielectric",
            "source_url": DATASET_URL,
            "request_url": UPSTREAM_URL,
            "dataset_version": DATASET_VERSION,
            "response_sha256": UPSTREAM_SHA256,
            "retrieved_at": retrieved_at,
            "query_filters": filters,
            "records_retrieved": len(records),
            "records_examined": len(rows),
            "records_rejected": rejected,
            "records_filtered": filtered,
            "duplicate_source_ids_count": len(duplicates),
            "sampling_order": (
                "distinct_element_count_ascending"
                if filters.get("prefer_simple")
                else "versioned_dataset_row_order"
            ),
            "coverage": (
                "All matching rows from one historical public release; "
                "not an exhaustive materials search."
            ),
            "caveats": [
                "Historical calculated bulk phases from a fixed 2018 mirror of "
                "the 2017 study; not current database values "
                "or thin-film measurements.",
                "Thermodynamic stability, compound safety, and experimental "
                "thin-film performance are unassessed.",
                "Dielectric scalars average tensor eigenvalues; "
                "anisotropy and phase dependence require follow-up.",
                "Source structures and free-text fields are not interpreted "
                "or exposed by this scalar adapter.",
            ],
        }
    except (
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        OSError,
        RuntimeError,
        http.client.HTTPException,
        zlib.error,
    ):
        raise SourceError(
            "The public dielectric dataset was unavailable or failed validation; "
            "no saved candidates were substituted."
        ) from None


def retrieve_structure_source(material_id, *, deadline=None):
    """Return an exact-release structure as untrusted JSON for geometry
    validation.

    This is an internal adapter seam, not a structure-file endpoint. The
    caller must validate numeric lattice/site/species data and source
    composition before creating any downloadable structure. No MSON
    classes are instantiated here.
    """
    match = (
        re.fullmatch(r"dielectric:(mp-[0-9]{1,10})(?::row([0-9]{1,4}))?", material_id)
        if isinstance(material_id, str)
        else None
    )
    if match is None:
        raise SourceError("Unsupported public dielectric structure identity.")
    try:
        shared_deadline = bounded_deadline(MAX_SECONDS)
        deadline = (
            min(deadline, shared_deadline) if deadline is not None else shared_deadline
        )
        _remaining(deadline)
        rows = _decode(_download(deadline), deadline)
        matches = [
            (index, row)
            for index, row in enumerate(rows)
            if row["material_id"] == match[1]
        ]
        duplicate_ids = {match[1]} if len(matches) > 1 else set()
        for index, row in matches:
            if match[2] is not None and str(index) != match[2]:
                continue
            record = _record(row, index, duplicate_ids, datetime.now(UTC).isoformat())
            if record["material_id"] != material_id or not isinstance(
                row["structure"], dict
            ):
                continue
            _remaining(deadline)
            return {
                **{
                    key: record[key]
                    for key in (
                        "material_id",
                        "source_record_id",
                        "formula",
                        "nsites",
                        "space_group_number",
                        "provenance",
                    )
                },
                "structure": row["structure"],
                "structure_requires_validation": True,
            }
        raise ValueError("Exact public dielectric structure row was not available.")
    except (
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        OSError,
        RuntimeError,
        http.client.HTTPException,
        zlib.error,
    ):
        raise SourceError(
            "The exact-release public dielectric structure was unavailable "
            "or failed validation."
        ) from None
