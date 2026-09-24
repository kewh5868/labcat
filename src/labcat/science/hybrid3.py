"""Bounded public HybriD³ band-gap datasets; no inferred cohorts or
saved fallback.

The official schema defines primary/secondary numerical values and fixed
subset conditions. Only selected scientific metadata survives; account,
synthesis prose, remote instructions, file links and unrelated fields
are discarded.
"""

import hashlib
import math
import re
import unicodedata
import zipfile
import zlib
from datetime import UTC, datetime

from labcat.public_sources import (
    PublicSourceError,
    _fetch,
    _json,
    _remaining,
    _text,
    _word_set,
)

from .preferences import (
    composition_key,
    derive_search_filters,
    requires_unmapped_scope_evidence,
    validate_formula,
    validate_search_filters,
)
from .rebuild_snapshot import canonical
from .retrieval_budget import bounded_deadline
from .sources import SourceError

API_URL = "https://materials.hybrid3.duke.edu/materials/datasets/"
SCHEMA_URL = "https://hybrid3-database.readthedocs.io/en/latest/database.html"
FILTER_SCHEMA_URL = (
    "https://github.com/HybriD3-database/MatD3/blob/master/materials/views.py"
)
MAX_SECONDS = 18
PAGE_SIZE = 40
MAX_PAGES = 6
MAX_RECORDS = 480
MAX_SUBSETS = 24
STRUCTURE_PAGE_SIZE = 12
MAX_STRUCTURE_PAGES = 4
IDENTITY = re.compile(
    r"hybrid3:([1-9][0-9]{0,8}):dataset([1-9][0-9]{0,8}):subset([1-9][0-9]{0,8})"
)
GAP_PROPERTIES = frozenset(
    {
        "band gap (fundamental)",
        "band gap (optical, theory)",
        "band gap (optical, transmission)",
        "band gap (optical, diffuse reflectance)",
        "band gap (optical, integrating sphere)",
        "band gap (band edge difference)",
        "band gap (fundamental, calculated) (dft-hse06+soc)",
    }
)
_CRYSTAL_SYSTEMS = frozenset(
    {
        "triclinic",
        "monoclinic",
        "orthorhombic",
        "tetragonal",
        "trigonal",
        "hexagonal",
        "cubic",
    }
)
# Request class words only select independently returned source metadata. Neither
# a formula pattern nor the HybriD³ database name establishes a material class.
_CLASS_WORDS = frozenset(
    {
        "perovskite",
        "polymer",
        "halide",
        "oxide",
        "nitride",
        "sulfide",
        "chalcogenide",
        "semiconductor",
        "metal",
        "alloy",
        "ceramic",
        "zeolite",
        "mof",
        "framework",
        "monolayer",
        "nanoparticle",
        "nanotube",
        "graphene",
    }
)
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?"
_SCALAR = re.compile(rf"(?P<value>{_NUMBER})(?: \(±(?P<error>{_NUMBER})\))?")
_BASE_CAVEATS = [
    "Bounded sample of public band-gap datasets, not an exhaustive materials search.",
    "Optical and fundamental gaps, methods, samples and phases remain distinct; "
    "source datasets are not interchangeable measurements.",
    "Thermodynamic and operational stability, solution processability, compound "
    "safety and device performance are unassessed by this scalar adapter.",
    "Class matches use explicit source names or linked reference titles; "
    "database membership and composition do not establish crystal topology.",
]


def supports_query(query, material_class=None):
    """Decline classes outside this scalar adapter's reviewed identity
    scope."""
    if not isinstance(query, str) or len(query) > 20_000:
        return False
    if requires_unmapped_scope_evidence(query, material_class):
        return False
    if re.search(
        r"\b(?:polymers?|composites?|biomaterials?|elastomers?|thermosets?|"
        r"thermoplastics?|mofs?|metal[ -]organic|liquid[ -]crystals?|"
        r"high[ -]entropy|perovskitoids?|quantum[ -]dots?|"
        r"nanoparticles?|nanotubes?|monolayers?|graphene|zeolites?)\b",
        query,
        re.I,
    ):
        return False
    classes = _word_set(query) & _CLASS_WORDS
    hints = derive_search_filters(query, material_class)
    return bool(classes or hints.get("formula") or hints.get("chemsys"))


def _identity(value):
    if type(value) is not int or not 0 < value < 1_000_000_000:
        raise ValueError("Unsupported public dataset identity.")
    return value


def _scalar(value, *, scale=1.0, maximum=1000):
    """Reject ranges, bounds, approximations and expressions; retain
    explicit error."""
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError("Unsupported scalar representation.")
    match = _SCALAR.fullmatch(value.strip())
    if match is None:
        raise ValueError("Unsupported scalar representation.")
    number = float(match["value"]) * scale
    error = float(match["error"]) * scale if match["error"] else None
    if (
        not math.isfinite(number)
        or not 0 <= number <= maximum
        or (
            error is not None
            and (not math.isfinite(error) or not 0 <= error <= maximum)
        )
    ):
        raise ValueError("Scalar value exceeded its validation bounds.")
    return number, error


def _matches(formula, elements, filters):
    if filters.get("formula") and composition_key(formula) not in {
        composition_key(hint) for hint in filters["formula"].split(",")
    }:
        return False
    if filters.get("chemsys") and set(elements) not in [
        set(hint.split("-")) for hint in filters["chemsys"].split(",")
    ]:
        return False
    if filters.get("elements") and not set(filters["elements"].split(",")) <= set(
        elements
    ):
        return False
    return not set(filters.get("exclude_elements", "").split(",")) & set(elements)


def _class_field_match(text, term):
    """Use only an unnegated class mention within this individual source
    field.

    Mixed positive/negative mentions in one field are ambiguous for this
    lexical filter, so discard that field rather than infer which phase
    the title means.
    """
    normalized = re.sub(
        r"[\u2010-\u2015\u2212]", "-", unicodedata.normalize("NFKC", text).casefold()
    )
    if term not in _word_set(normalized):
        return False
    token = re.escape(term) + r"s?\b"
    negated = (
        r"\bnon[ -]*"
        + token
        + r"|\b(?:not|no|without|neither|excluding)\b"
        + r"(?:[ -]+\w+){0,4}[ -]+"
        + token
        + r"|\b"
        + token
        + r"[ -]+(?:free|absent|excluded)\b"
    )
    return re.search(negated, normalized) is None


def _metadata_text(row, system, classes):
    reference = row.get("reference") or {}
    if not isinstance(reference, dict):
        raise ValueError("Invalid dataset reference.")
    fields = {
        "system.compound_name": _text(system.get("compound_name"), 1000),
        "system.group": _text(system.get("group"), 1000),
        "reference.title": _text(reference.get("title"), 1000),
    }
    matches = [
        {"class": term, "field": field, "text": value}
        for term in sorted(classes)
        for field, value in fields.items()
        if value is not None and _class_field_match(value, term)
    ]
    if classes - {match["class"] for match in matches}:
        return None
    return {
        "compound_name": fields["system.compound_name"],
        "alternate_names": fields["system.group"],
        "reference_title": fields["reference.title"],
        "reference_id": _identity(reference.get("id")) if reference else None,
        "reference_doi": _text(reference.get("doi_isbn"), 200),
        "class_matches": matches,
    }


def _methods(row):
    experimental = row.get("is_experimental")
    if type(experimental) is not bool:
        raise ValueError("The experimental/theoretical qualifier is unavailable.")
    computational = row.get("computational", [])
    experiments = row.get("experimental", [])
    if any(
        not isinstance(values, list) or len(values) > 12
        for values in (computational, experiments)
    ):
        raise ValueError("Unsupported method metadata.")
    fields = ("code", "level_of_theory", "xc_functional", "level_of_relativity")
    calculations = [
        {key: text for key in fields if (text := _text(item.get(key), 300)) is not None}
        for item in computational
        if isinstance(item, dict)
    ]
    measurements = [
        text
        for item in experiments
        if isinstance(item, dict)
        and (text := _text(item.get("method"), 300)) is not None
    ]
    return {
        "is_experimental": experimental,
        "sample_type": _text(row.get("sample_type"), 100),
        "computational": calculations,
        "experimental_methods": measurements,
    }


def _conditions(subset):
    values = subset.get("fixed_values", [])
    if not isinstance(values, list) or len(values) > 12:
        raise ValueError("Unsupported subset conditions.")
    conditions = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Invalid subset condition.")
        prop, unit = value.get("physical_property"), value.get("unit")
        if not isinstance(prop, dict) or not isinstance(unit, dict):
            raise ValueError("Missing fixed-condition property or unit.")
        name, label = _text(prop.get("name"), 160), _text(unit.get("label"), 60)
        if name is None or label is None or value.get("upper_bound") is not None:
            raise ValueError("Unsupported fixed condition.")
        number, error = _scalar(value.get("formatted"), maximum=1_000_000)
        conditions.append(
            {"property": name, "value": number, "uncertainty": error, "unit": label}
        )
    return conditions


def _records(row, filters, classes, response_hash, request_url, retrieved_at):
    if not isinstance(row, dict) or row.get("visible") is not True:
        raise ValueError("Dataset is not explicitly public and visible.")
    dataset_id = _identity(row.get("pk"))
    system = row.get("system")
    if not isinstance(system, dict):
        raise ValueError("Dataset has no public system identity.")
    system_id = _identity(system.get("id"))
    formula = system.get("formula")
    elements = validate_formula(formula)
    if not _matches(formula, elements, filters):
        return [], "scope"
    metadata = _metadata_text(row, system, classes)
    if metadata is None:
        return [], "scope"
    prop, unit = row.get("primary_property"), row.get("primary_unit")
    if not isinstance(prop, dict) or not isinstance(unit, dict):
        raise ValueError("Dataset property/unit is unavailable.")
    name = prop.get("name")
    if not isinstance(name, str) or name.casefold() not in GAP_PROPERTIES:
        raise ValueError("Dataset does not expose a reviewed gap property.")
    label = unit.get("label")
    if label not in ("eV", "meV"):
        raise ValueError("Unsupported band-gap unit.")
    if (
        row.get("secondary_property") is not None
        or row.get("secondary_unit") is not None
    ):
        return [], "dependent"
    method = _methods(row)
    subsets = row.get("subsets")
    if not isinstance(subsets, list) or not 1 <= len(subsets) <= MAX_SUBSETS:
        raise ValueError("Unsupported dataset subset count.")
    records = []
    for subset in subsets:
        if not isinstance(subset, dict):
            continue
        try:
            subset_id = _identity(subset.get("pk"))
            datapoints = subset.get("datapoints")
            if not isinstance(datapoints, list) or len(datapoints) != 1:
                continue
            values = (
                datapoints[0].get("values") if isinstance(datapoints[0], dict) else None
            )
            if (
                not isinstance(values, list)
                or len(values) != 1
                or not isinstance(values[0], dict)
                or values[0].get("qualifier") != "primary"
            ):
                continue
            value, error = _scalar(
                values[0].get("formatted"), scale=0.001 if label == "meV" else 1
            )
            conditions = _conditions(subset)
        except (ValueError, TypeError, OverflowError):
            continue
        phase = subset.get("crystal_system")
        phase = phase if phase in _CRYSTAL_SYSTEMS else None
        selected = {
            "dataset_id": dataset_id,
            "system_id": system_id,
            "subset_id": subset_id,
            "formula": formula,
            "property": name,
            "property_id": _identity(prop.get("id")),
            "source_value": values[0]["formatted"],
            "input_unit": label,
            "band_gap_ev": value,
            "band_gap_uncertainty_ev": error,
            "crystal_system": phase,
            "subset_label": _text(subset.get("label"), 300),
            "space_group": _text(row.get("space_group"), 60),
            "conditions": conditions,
            **metadata,
            **method,
        }
        identity = f"hybrid3:{system_id}:dataset{dataset_id}:subset{subset_id}"
        method_label = "experimental" if method["is_experimental"] else "calculated"
        records.append(
            {
                "material_id": identity,
                "source_record_id": str(dataset_id),
                "formula": formula,
                "elements": elements,
                "band_gap_ev": value,
                "band_gap_uncertainty_ev": error,
                "band_gap_kind": name,
                "phase": phase,
                "nsites": None,
                "space_group_number": None,
                "is_gap_direct": None,
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
                "method": f"HybriD³ {method_label} {name}; "
                "source method and phase retained",
                "source_mode": "live_hybrid3",
                "source_fields": {
                    "formula": "system.formula",
                    "band_gap_ev": "subsets.datapoints.values[primary].formatted "
                    "with primary_unit",
                },
                "provenance": {
                    "source_url": (
                        "https://materials.hybrid3.duke.edu/materials/dataset/"
                        f"{dataset_id}"
                    ),
                    "request_url": request_url,
                    "retrieved_at": retrieved_at,
                    "response_sha256": response_hash,
                    "raw_fields_sha256": hashlib.sha256(
                        canonical(selected)
                    ).hexdigest(),
                    "raw_fields": selected,
                    "method_reference": SCHEMA_URL,
                    "dataset_version": "Live HybriD³ dataset; "
                    "immutable release not supplied",
                    "band_gap_input_unit": label,
                    "system_id": system_id,
                    "dataset_id": dataset_id,
                    "subset_id": subset_id,
                },
                "issues": [
                    f"Source reports {name} ({method_label}); "
                    "do not equate optical and fundamental gaps.",
                    *(
                        [
                            "Crystal system is not reported; "
                            "phase identity remains unknown."
                        ]
                        if phase is None
                        else []
                    ),
                    "Solution processing and stability are unassessed "
                    "by this band-gap dataset.",
                ],
            }
        )
    return records, "accepted" if records else "unsupported_scalar"


def retrieve_live(filters=None, *, system_ids=(), query=""):
    """Read at most six public gap pages; hints constrain, never supply
    evidence."""
    try:
        filters = validate_search_filters(filters)
        if set(filters) & {"material_ids", "entry_ids", "is_metal", "has_props"}:
            raise ValueError("Unsupported HybriD³ filter.")
        if not isinstance(system_ids, (list, tuple)) or len(system_ids) > 20:
            raise ValueError("Unsupported system hints.")
        system_ids = {_identity(value) for value in system_ids}
        if not isinstance(query, str) or len(query) > 20_000:
            raise ValueError("Unsupported class query.")
    except (ValueError, TypeError):
        raise SourceError("Unsupported or invalid HybriD³ search hints.") from None
    classes = _word_set(query) & _CLASS_WORDS
    structural = classes & {
        "perovskite",
        "polymer",
        "zeolite",
        "mof",
        "framework",
        "monolayer",
        "nanoparticle",
        "nanotube",
        "graphene",
    }
    if structural:
        classes = structural
    metadata = {
        "mode": "live_hybrid3",
        "request_url": API_URL,
        "query_filters": filters,
        "system_id_hints": sorted(system_ids),
        "class_hints": sorted(classes),
        "records_retrieved": 0,
        "records_examined": 0,
        "records_rejected": 0,
        "records_filtered": 0,
        "dependent_datasets_skipped": 0,
        "sample_limit": PAGE_SIZE * MAX_PAGES,
        "sample_truncated": None,
        "repository_total": None,
        "pages_read": 0,
        "responses": [],
        "caveats": list(_BASE_CAVEATS),
    }
    if query and not supports_query(query):
        metadata["scope_supported"] = False
        metadata["caveats"].append(
            "This request's material class is outside the reviewed HybriD³ "
            "scalar scope; no unrelated database candidates were substituted."
        )
        return [], metadata
    metadata["scope_supported"] = True
    records, seen = [], set()
    try:
        deadline = bounded_deadline(MAX_SECONDS)
        for page in range(1, MAX_PAGES + 1):
            _remaining(deadline)
            raw, url = _fetch(
                "hybrid3_datasets",
                {
                    "primary_property__name__contains": "band gap",
                    "page": page,
                    "page_size": PAGE_SIZE,
                },
                deadline,
            )
            payload = _json(raw)
            rows, total = payload.get("results"), payload.get("count")
            if (
                not isinstance(rows, list)
                or len(rows) > PAGE_SIZE
                or type(total) is not int
                or not 0 <= total <= 1_000_000
            ):
                raise ValueError("Unsupported public dataset page.")
            digest = hashlib.sha256(raw).hexdigest()
            timestamp = datetime.now(UTC).isoformat()
            metadata["responses"].append(
                {
                    "request_url": url,
                    "response_sha256": digest,
                    "retrieved_at": timestamp,
                }
            )
            metadata["pages_read"] += 1
            metadata["repository_total"] = total
            for row in rows:
                _remaining(deadline)
                metadata["records_examined"] += 1
                try:
                    normalized, status = _records(
                        row, filters, classes, digest, url, timestamp
                    )
                except (ValueError, TypeError, KeyError, OverflowError):
                    metadata["records_rejected"] += 1
                    continue
                if status == "scope":
                    metadata["records_filtered"] += 1
                elif status == "dependent":
                    metadata["dependent_datasets_skipped"] += 1
                elif status == "unsupported_scalar":
                    metadata["records_rejected"] += 1
                for record in normalized:
                    if record["material_id"] not in seen and len(records) < MAX_RECORDS:
                        records.append(record)
                        seen.add(record["material_id"])
            # Never follow response URLs. The next page is built from this fixed route.
            if payload.get("next") is None:
                break
        metadata["sample_truncated"] = (
            payload.get("next") is not None or len(records) >= MAX_RECORDS
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        OSError,
        RuntimeError,
        RecursionError,
    ):
        raise SourceError(
            "Public HybriD³ gap datasets were unavailable or failed validation; "
            "no saved candidates were substituted."
        ) from None
    if filters.get("prefer_simple") or system_ids:
        records.sort(
            key=lambda record: (
                record["provenance"]["system_id"] not in system_ids,
                len(record["elements"]) if filters.get("prefer_simple") else 0,
                record["material_id"],
            )
        )
    metadata["records_retrieved"] = len(records)
    metadata["distinct_systems"] = len(
        {record["provenance"]["system_id"] for record in records}
    )
    metadata["system_id_hints_matched"] = sorted(
        system_ids & {record["provenance"]["system_id"] for record in records}
    )
    return records, metadata


class StructureSourceError(SourceError):
    """A fixed structure outcome, distinct from a public transport
    failure."""

    def __init__(self, message, *, code):
        super().__init__(message)
        self.code = code


def _structure_datasets(system_id, deadline):
    """Read a complete bounded index without following provider
    pagination URLs."""
    rows, digests, identities = [], [], set()
    total = None
    for page in range(1, MAX_STRUCTURE_PAGES + 1):
        raw, _ = _fetch(
            "hybrid3_datasets",
            {
                "system": system_id,
                "primary_property__name": "atomic structure",
                "page": page,
                "page_size": STRUCTURE_PAGE_SIZE,
            },
            deadline,
        )
        payload = _json(raw)
        batch, count = payload.get("results"), payload.get("count")
        if (
            not isinstance(batch, list)
            or len(batch) > STRUCTURE_PAGE_SIZE
            or type(count) is not int
            or not 0 <= count <= 1_000_000
            or (total is not None and total != count)
        ):
            raise ValueError("Unsupported or changing structure index.")
        total = count
        for row in batch:
            identity = _identity(row.get("pk")) if isinstance(row, dict) else None
            if identity is None or identity in identities:
                raise ValueError("Ambiguous repeated structure dataset identity.")
            identities.add(identity)
        rows.extend(batch)
        digests.append(hashlib.sha256(raw).hexdigest())
        if payload.get("next") is None:
            if len(rows) != total:
                raise ValueError("Incomplete structure index.")
            return rows, hashlib.sha256(canonical(digests)).hexdigest()
    raise StructureSourceError(
        "The structure index exceeds the bounded search; matching is incomplete.",
        code="structure_search_incomplete",
    )


def retrieve_structure_source(candidate):
    """Read public atoms or a bounded original crystallography
    attachment.

    An independent crystallography record may be a composition
    reference. It never becomes the report's property phase or changes
    the saved ranking.
    """
    try:
        match = IDENTITY.fullmatch(candidate["material_id"])
        saved = candidate["provenance"]["raw_fields"]
        if match is None or candidate.get("source_mode") != "live_hybrid3":
            raise ValueError("Unsupported HybriD³ identity.")
        system_id, dataset_id, subset_id = map(int, match.groups())
        if any(
            saved.get(key) != expected
            for key, expected in (
                ("system_id", system_id),
                ("dataset_id", dataset_id),
                ("subset_id", subset_id),
            )
        ):
            raise ValueError("Saved dataset identity disagrees with the candidate.")
        deadline = bounded_deadline(MAX_SECONDS)
        raw, url = _fetch("hybrid3_dataset", {"record_id": dataset_id}, deadline)
        classes = {item["class"] for item in saved.get("class_matches", [])}
        normalized, _ = _records(
            _json(raw),
            {},
            classes,
            hashlib.sha256(raw).hexdigest(),
            url,
            datetime.now(UTC).isoformat(),
        )
        current = next(
            (r for r in normalized if r["material_id"] == candidate["material_id"]),
            None,
        )
        if current is None or current["provenance"]["raw_fields"] != saved:
            raise ValueError("The source band-gap dataset changed after the report.")
        rows, datasets_digest = _structure_datasets(system_id, deadline)
        if not rows:
            raise StructureSourceError(
                "The public system has no atomic-structure datasets.",
                code="structure_missing",
            )
        matches, references = [], []
        for row in rows:
            if not isinstance(row, dict) or row.get("visible") is not True:
                continue
            system, prop, unit, reference = (
                row.get(key)
                for key in ("system", "primary_property", "primary_unit", "reference")
            )
            if any(
                not isinstance(value, dict) for value in (system, prop, unit, reference)
            ):
                continue
            if (
                system.get("id") != system_id
                or composition_key(system.get("formula"))
                != composition_key(candidate["formula"])
                or prop.get("name") != "atomic structure"
                or unit.get("label") != "Å"
                or type(row.get("is_experimental")) is not bool
            ):
                continue
            _identity(reference.get("id"))
            subsets = row.get("subsets")
            if not isinstance(subsets, list) or len(subsets) > MAX_SUBSETS:
                continue
            for subset in subsets:
                if (
                    not isinstance(subset, dict)
                    or subset.get("crystal_system") not in _CRYSTAL_SYSTEMS
                ):
                    continue
                points = subset.get("datapoints")
                if not isinstance(points, list) or not 6 <= len(points) <= 2009:
                    continue
                differences = []
                if reference.get("id") != saved.get("reference_id"):
                    differences.append("Different source publication.")
                if row["is_experimental"] is not saved.get("is_experimental"):
                    differences.append(
                        "Experimental structure; calculated property."
                        if row["is_experimental"]
                        else "Calculated structure; experimental property."
                    )
                if row.get("sample_type") != saved.get("sample_type"):
                    differences.append("Different sample type.")
                if subset["crystal_system"] != saved.get("crystal_system"):
                    differences.append(
                        "Different or unspecified property crystal system."
                    )
                try:
                    conditions_match = _conditions(subset) == saved.get(
                        "conditions", []
                    )
                except (ValueError, TypeError, KeyError, OverflowError):
                    # Unsupported/ranged conditions cannot establish a metadata
                    # match, but do not invalidate a separately validated CIF.
                    conditions_match = False
                if not conditions_match:
                    differences.append(
                        "Different or unspecified measurement conditions."
                    )
                pair = (_identity(row.get("pk")), _identity(subset.get("pk")))
                references.append(
                    {
                        "pair": pair,
                        "crystal_system": subset["crystal_system"],
                        "differences": differences,
                    }
                )
                if not differences and len(points) > 9:
                    matches.append(pair)
        if len(matches) == 1:
            structure_dataset, structure_subset = matches[0]
            coordinates, coordinate_url = _fetch(
                "hybrid3_coordinates", {"record_id": structure_subset}, deadline
            )
            atom_payload = _json(coordinates)
            if atom_payload.get("coordinates"):
                return {
                    "material_id": candidate["material_id"],
                    "formula": candidate["formula"],
                    "coordinates": atom_payload,
                    "input_unit": "angstrom",
                    "response_sha256": hashlib.sha256(
                        canonical(
                            {
                                "datasets": datasets_digest,
                                "coordinates": hashlib.sha256(coordinates).hexdigest(),
                            }
                        )
                    ).hexdigest(),
                    "request_url": coordinate_url,
                    "structure_dataset_id": structure_dataset,
                    "structure_subset_id": structure_subset,
                }
        # Prefer records with the fewest explicitly recorded metadata differences.
        # At most two equally close subsets/files are inspected. More matches or
        # multiple valid CIF blocks are ambiguous, not permission to pick a phase.
        if not references:
            raise ValueError("No composition-matched crystallography is available.")
        best = min(len(item["differences"]) for item in references)
        references = [item for item in references if len(item["differences"]) == best]
        if len(references) > 2:
            raise StructureSourceError(
                "Too many equally close reference structures remain.",
                code="structure_ambiguous",
            )
        from .cif_files import read_dataset_cif

        valid, archives = [], {}
        for option in references:
            structure_dataset, structure_subset = option["pair"]
            if structure_dataset not in archives:
                archives[structure_dataset] = _fetch(
                    "hybrid3_dataset_files", {"record_id": structure_dataset}, deadline
                )
            archive, archive_url = archives[structure_dataset]
            try:
                cif = read_dataset_cif(
                    archive, candidate["formula"], option["crystal_system"]
                )
            except (ValueError, RuntimeError, OSError, zipfile.BadZipFile, zlib.error):
                continue
            valid.append((option, cif, archive_url))
        if len(valid) != 1:
            raise ValueError("No unique supported CIF reference was found.")
        option, cif, archive_url = valid[0]
        structure_dataset, structure_subset = option["pair"]
        response_hash = hashlib.sha256(
            canonical(
                {
                    "dataset_response_sha256": datasets_digest,
                    "archive_response_sha256": cif["archive_sha256"],
                    "source_cif_sha256": cif["sha256"],
                    "source_cif_block": cif["block"],
                    "structure_dataset_id": structure_dataset,
                    "structure_subset_id": structure_subset,
                }
            )
        ).hexdigest()
        return {
            "material_id": candidate["material_id"],
            "formula": candidate["formula"],
            "cif": cif,
            "input_unit": "angstrom",
            "response_sha256": response_hash,
            "request_url": archive_url,
            "structure_dataset_id": structure_dataset,
            "structure_subset_id": structure_subset,
            "structure_source_url": (
                "https://materials.hybrid3.duke.edu/materials/dataset/"
                f"{structure_dataset}"
            ),
            "structure_match": (
                "composition_reference"
                if option["differences"]
                else "source_metadata_match"
            ),
            "structure_differences": option["differences"],
        }
    except (PublicSourceError, StructureSourceError):
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        StopIteration,
        OverflowError,
        OSError,
        RuntimeError,
        RecursionError,
    ):
        raise SourceError(
            "A unique validated public HybriD³ atom list or crystallography "
            "reference was unavailable within the source and structure limits."
        ) from None
