"""On-demand structures from exact public shortlist identities, never
raw scripts.

Only numeric cell/position data and chemical symbols cross the adapter
boundary. Downloads are explicitly derived P1 CIFs, not the upstream
file or a phase match. NOMAD lengths use metres; MP Structure
dictionaries use angstroms.
"""

import base64
import hashlib
import json
import math
import re
import threading
import time
import zipfile
import zlib
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urlsplit

from labcat.credentials import ConnectionError as CredentialConnectionError
from labcat.public_sources import (
    _ELEMENTS,
    MAX_SECONDS,
    PublicSourceError,
    _fetch,
    _json,
    _search_hybrid3,
    _search_nomad,
)
from labcat.science import dielectric, hybrid3, structure_identity
from labcat.science.candidate_leads import _document
from labcat.science.formula_display import display_formula, flat_formula_tokens
from labcat.science.nomad import _composition, _path
from labcat.science.rebuild_snapshot import canonical
from labcat.science.reporting import (
    _candidate_leads,
    validated_literature_evaluation,
)
from labcat.science.retrieval_budget import repository_budget
from labcat.science.sources import (
    MAX_RECORDS,
    MP_FIELDS,
    MP_HOST,
    MP_PATH,
    SourceError,
    _request_mp_data,
)
from labcat.workspace import WorkspaceNotFound

MAX_SITES = 2000
MAX_REFERENCE_RECORDS = 3
MAX_DISCOVERY_LEADS = 12
MAX_DISCOVERY_SECONDS = 18
_NETWORK_SLOTS = threading.BoundedSemaphore(2)
_IDENTITY = re.compile(
    r"(?:mp-\d{1,10}|nomad:[A-Za-z0-9_-]{1,80}|dielectric:mp-\d{1,10}(?::row\d{1,4})?"
    r"|hybrid3:[1-9][0-9]{0,8}:dataset[1-9][0-9]{0,8}:subset[1-9][0-9]{0,8})"
)
_DIGEST = re.compile(r"[a-f0-9]{64}")
_CAVEATS = [
    "Derived CIF: validated source coordinates are written as a full P1 cell; "
    "this is not an original uploaded file or a symmetry determination.",
    "Retrieved on demand after the report. The source may have changed; "
    "structure retrieval does not update the saved ranking or prove phase matching.",
    "Only ordered, fully occupied, three-dimensional periodic structures within "
    "the viewer size limit are supported. Bonds shown by the viewer are illustrative.",
]
_REFERENCE_CAVEAT = (
    "Reference structure only: composition does not establish the candidate's "
    "phase, molecular identity, morphology, processing conditions or measured "
    "properties. The saved report and ranking are unchanged."
)


def _typed_formula(reference):
    """Only the compound-identity adapters supply typed source
    formulas."""
    if (
        not isinstance(reference, dict)
        or reference.get("source_id") not in {"nomad", "hybrid3"}
        or _document(reference) is None
        or reference["metadata"].get("record_type") != "compound_identity"
    ):
        return None
    formula = reference["metadata"].get("formula")
    try:
        _composition(formula)
    except (ValueError, TypeError, OverflowError):
        return None
    return formula


def _lead_formula(lead, references=()):
    """Resolve only through a cited typed record, including its own
    aliases.

    Publication labels can be valid element tokens. A parsable name
    cannot establish composition, and multiple source assignments are
    not collapsed into a guessed composition or molecular identity.
    """
    citations = {
        (citation["source_id"], citation["record_id"], citation["url"])
        for citation in lead.get("citations", [])
    }
    formulas = set()
    for reference in references:
        if (
            reference.get("source_id"),
            reference.get("record_id"),
            reference.get("url"),
        ) not in citations:
            continue
        if formula := _typed_formula(reference):
            formulas.add(formula)
    return next(iter(formulas)) if len(formulas) == 1 else None


def _formula_hint(lead, references):
    """A literal formula can select records; only returned records
    supply facts.

    Preserve the stronger cited identity contract when present,
    including an ambiguous assignment. Mixed-case, multi-element
    formulas may use implicit atom counts (CdS, InAs). All-capital
    abbreviations and single-element labels still need a separate
    identity record; repository matches validate every hint.
    """
    assigned = _lead_formula(lead, references)
    if assigned is not None:
        return _reference_formula(assigned, lead["name"])
    citations = {
        (item["source_id"], item["record_id"], item["url"])
        for item in lead["citations"]
    }
    if any(
        _typed_formula(reference) is not None
        and (
            reference.get("source_id"),
            reference.get("record_id"),
            reference.get("url"),
        )
        in citations
        for reference in references
    ):
        return None
    spelling = lead["name"].translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
    parenthesized = re.fullmatch(r"(.+?)\s+\(((?:[A-Z][a-z]?\d*){2,})\)", spelling)
    explicit = parenthesized is not None and structure_identity.eligible_name(
        parenthesized[1]
    )
    if explicit:
        spelling = parenthesized[2]
    if re.fullmatch(r"(?:[A-Z][a-z]?\d*){2,}", spelling) is None:
        return None
    try:
        if len(_composition(spelling)) < 2:
            return None
        if not explicit and not any(c.isdigit() for c in spelling):
            tokens = flat_formula_tokens(spelling)
            # Properly cased symbols distinguish CdS/InAs from all-capital
            # publication abbreviations such as PI/NO. The bounded symbol set
            # also rejects CDs (carbon-dot shorthand), not cadmium sulfide CdS.
            if tokens is None or not any(len(symbol) == 2 for symbol, _ in tokens):
                return None
        return _reference_formula(spelling, lead["name"])
    except (ValueError, TypeError, OverflowError):
        return None


def _component_leads(lead):
    """Derive navigation hints from a validated cited composite label
    only.

    These are not new shortlist candidates or composition evidence.
    Independent repository records must still validate each complete
    formula. Slash order alone does not establish core/shell roles or an
    assembled structure.
    """
    if lead.get("_structure_component"):
        return []
    spelling = lead["name"].translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉∕⁄", "0123456789//"))
    parts = re.split(r"[/@]", spelling)
    if not 2 <= len(parts) <= 3:
        return []
    formulas = []
    for part in parts:
        # Public article typography often separates a subscript from its atom.
        formula = re.sub(r"(?<=[A-Za-z])\s+(?=\d)", "", part.strip())
        if re.fullmatch(r"(?:[A-Z][a-z]?\d*){2,}", formula) is None:
            return []
        # Components are query hints under the same symbol/abbreviation rules
        # as standalone formulas, never a shortcut around identity safeguards.
        if _formula_hint({"name": formula, "citations": []}, []) is None:
            return []
        if formula not in formulas:
            formulas.append(formula)
    if len(formulas) < 2:
        return []
    children = []
    for index, formula in enumerate(formulas, 1):
        identity = (
            "component-"
            + hashlib.sha256(
                canonical([lead["id"], lead["name"], lead["citations"], index, formula])
            ).hexdigest()[:24]
        )
        children.append(
            {
                "id": identity,
                "name": formula,
                "citations": lead["citations"],
                "_structure_component": {
                    "lead_id": lead["id"],
                    "name": lead["name"],
                    "component_id": identity,
                    "formula": formula,
                    "label": f"Component {index}",
                },
            }
        )
    return children


def _structure_lookup_leads(leads):
    return [scope for lead in leads for scope in (lead, *_component_leads(lead))]


def _lookup_formula(lead, references):
    component = lead.get("_structure_component")
    return component["formula"] if component else _formula_hint(lead, references)


def _name_lookup_eligible(lead, references):
    """Named lookup cannot bypass an unsupported or ambiguous typed
    identity."""
    citations = {
        (item["source_id"], item["record_id"], item["url"])
        for item in lead["citations"]
    }
    return structure_identity.eligible_name(lead["name"]) and not any(
        _typed_formula(reference) is not None
        and (
            reference.get("source_id"),
            reference.get("record_id"),
            reference.get("url"),
        )
        in citations
        for reference in references
    )


def _matches_reference_formula(source_formula, formula, *, hint_only=False):
    """Do not reduce explicit molecular atom counts from an untyped
    hint."""
    try:
        return _composition(source_formula) == _composition(formula) and (
            not hint_only or display_formula(source_formula) == display_formula(formula)
        )
    except (ValueError, TypeError, OverflowError):
        return False


def _mp_reference(reference, formula):
    """Revalidate the narrow MP adapter record without trusting saved
    labels."""
    if not isinstance(reference, dict) or set(reference) != {
        "source_id",
        "record_id",
        "formula",
        "url",
        "response_sha256",
        "request_url",
    }:
        return None
    identity = reference.get("record_id")
    if (
        reference.get("source_id") != "materials_project"
        or not isinstance(identity, str)
        or re.fullmatch(r"mp-\d{1,10}", identity) is None
        or reference.get("url") != "https://materialsproject.org/materials/" + identity
        or not isinstance(reference.get("response_sha256"), str)
        or _DIGEST.fullmatch(reference["response_sha256"]) is None
        or not _matches_reference_formula(reference.get("formula"), formula)
        or not isinstance(reference.get("request_url"), str)
        or len(reference["request_url"]) > 4096
    ):
        return None
    try:
        request = urlsplit(reference["request_url"])
        query = parse_qs(request.query)
        if (
            request.scheme != "https"
            or request.netloc != MP_HOST
            or request.path != MP_PATH
            or request.fragment
            or any(ord(c) < 32 for c in reference["request_url"])
            or set(query)
            != {
                "formula",
                "deprecated",
                "id_format",
                "_fields",
                "_limit",
                "_skip",
                "_sort_fields",
            }
            or len(query["formula"]) != 1
            or not _matches_reference_formula(query["formula"][0], formula)
            or query["deprecated"] != ["false"]
            or query["id_format"] != ["legacy"]
            or query["_limit"] != [str(MAX_RECORDS)]
            or query["_fields"] != [",".join(MP_FIELDS)]
            or query["_skip"] != ["0"]
            or query["_sort_fields"] != ["material_id"]
        ):
            return None
    except (ValueError, TypeError):
        return None
    return {
        "material_id": identity,
        "formula": reference["formula"],
        "source_mode": "live_materials_project",
    }


def _search_mp_references(formula, key, deadline, *, hint_only=False):
    """Use the approved summary adapter; no numerical evidence is
    introduced."""
    with repository_budget(seconds=max(0, deadline - time.monotonic())):
        payload, digest, request_url = _request_mp_data(key, {"formula": formula})
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
        raise SourceError("Invalid Materials Project reference response.")
    references, identities = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise SourceError("Invalid Materials Project reference identity.")
        reference = {
            "source_id": "materials_project",
            "record_id": row.get("material_id"),
            "formula": row.get("formula_pretty"),
            "url": "https://materialsproject.org/materials/"
            + str(row.get("material_id")),
            "response_sha256": digest,
            "request_url": request_url,
        }
        candidate = _mp_reference(reference, formula)
        if (
            candidate is None
            or not _matches_reference_formula(
                row.get("formula_pretty"), formula, hint_only=hint_only
            )
            or row.get("deprecated") is not False
            or not isinstance(row.get("elements"), list)
            or any(not isinstance(element, str) for element in row["elements"])
            or sorted(row["elements"])
            != [element for element, _ in _composition(formula)]
            or candidate["material_id"] in identities
        ):
            raise SourceError("Invalid Materials Project reference identity.")
        identities.add(candidate["material_id"])
        references.append(reference)
    return references[:MAX_REFERENCE_RECORDS]


def _reference_formula(formula, name):
    """Preserve composite expressions and explicit molecule/cluster
    counts."""
    if formula is None or any(
        operator in name for operator in ("/", "∕", "⁄", "@", ":", "+")
    ):
        return None
    composition = _composition(formula)
    if len(composition) == 1 and formula != composition[0][0]:
        return None
    # A source may store only an elemental ratio for a named molecule/cluster.
    # Use the name only to refuse that information loss, never to assign atoms
    # to an alias whose typed source formula is chemically different.
    spelling = name.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
    try:
        if (
            len(composition) == 1
            and _composition(spelling) == composition
            and spelling != composition[0][0]
        ):
            return None
    except (ValueError, OverflowError):
        pass
    return formula


def _nomad_reference(reference, formula):
    """Only approved, exact repository identities become structure
    selectors."""
    if (
        not isinstance(reference, dict)
        or reference.get("source_id") != "nomad"
        or _document(reference) is None
    ):
        return None
    identity = "nomad:" + reference["record_id"]
    source_formula = reference["metadata"].get("formula")
    try:
        if (
            _IDENTITY.fullmatch(identity) is None
            or reference["metadata"].get("record_type") != "compound_identity"
            or _composition(source_formula) != _composition(formula)
        ):
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    return {
        "material_id": identity,
        "formula": source_formula,
        "source_mode": "live_nomad",
    }


def _hybrid3_system(reference, formula):
    """A cited public compound system authorizes only its exact
    repository ID."""
    if (
        not isinstance(reference, dict)
        or reference.get("source_id") != "hybrid3"
        or _typed_formula(reference) is None
        or re.fullmatch(r"[1-9][0-9]{0,8}", reference.get("record_id", "")) is None
        or _composition(reference["metadata"]["formula"]) != _composition(formula)
    ):
        return None
    return int(reference["record_id"])


def _repository_reference(reference, formula):
    if (
        isinstance(reference, dict)
        and reference.get("source_id") == "materials_project"
    ):
        return _mp_reference(reference, formula)
    if not isinstance(reference, dict) or reference.get("source_id") != "hybrid3":
        return _nomad_reference(reference, formula)
    system = _hybrid3_system(reference, formula)
    detail = reference.get("metadata", {}).get("structure_record")
    if (
        system is None
        or not isinstance(detail, dict)
        or set(detail)
        != {"dataset_id", "subset_id", "crystal_system", "response_sha256"}
        or any(
            type(detail[key]) is not int or not 0 < detail[key] < 1_000_000_000
            for key in ("dataset_id", "subset_id")
        )
        or detail["crystal_system"] not in hybrid3._CRYSTAL_SYSTEMS
        or not isinstance(detail["response_sha256"], str)
        or _DIGEST.fullmatch(detail["response_sha256"]) is None
    ):
        return None
    return {
        "material_id": (
            f"hybrid3:{system}:dataset{detail['dataset_id']}"
            f":subset{detail['subset_id']}"
        ),
        "formula": reference["metadata"]["formula"],
        "source_mode": "live_hybrid3_structure",
        "structure_reference": {"system_id": system, **detail},
    }


def _hybrid3_reference_records(reference, formula, deadline):
    """Discover crystallography for the cited system, without needing a
    gap record."""
    system_id = _hybrid3_system(reference, formula)
    if system_id is None:
        return []
    rows, digest = hybrid3._structure_datasets(system_id, deadline)
    references = []
    identities = set()
    for row in rows:
        if not _hybrid3_structure_row(row, system_id, formula):
            continue
        for subset in row["subsets"]:
            if not _hybrid3_structure_subset(subset):
                continue
            item = {
                **reference,
                "metadata": {
                    **reference["metadata"],
                    "structure_record": {
                        "dataset_id": row["pk"],
                        "subset_id": subset["pk"],
                        "crystal_system": subset["crystal_system"],
                        "response_sha256": digest,
                    },
                },
            }
            record = _repository_reference(item, formula)
            if record is None or record["material_id"] in identities:
                raise ValueError("Ambiguous public crystallography identity")
            identities.add(record["material_id"])
            references.append(item)
    # These remain distinct, explicitly unverified phases; no automatic choice.
    return references[:MAX_REFERENCE_RECORDS]


def _hybrid3_structure_row(row, system_id, formula):
    if not isinstance(row, dict):
        return False
    system, prop, unit = (
        row.get(key) for key in ("system", "primary_property", "primary_unit")
    )
    try:
        return (
            row.get("visible") is True
            and type(row.get("pk")) is int
            and 0 < row["pk"] < 1_000_000_000
            and isinstance(system, dict)
            and type(system.get("id")) is int
            and system.get("id") == system_id
            and _composition(system.get("formula")) == _composition(formula)
            and isinstance(prop, dict)
            and prop.get("name") == "atomic structure"
            and isinstance(unit, dict)
            and unit.get("label") == "Å"
            and type(row.get("is_experimental")) is bool
            and isinstance(row.get("subsets"), list)
            and 1 <= len(row["subsets"]) <= hybrid3.MAX_SUBSETS
        )
    except (ValueError, TypeError, OverflowError):
        return False


def _hybrid3_structure_subset(subset):
    return (
        isinstance(subset, dict)
        and type(subset.get("pk")) is int
        and 0 < subset["pk"] < 1_000_000_000
        and subset.get("crystal_system") in hybrid3._CRYSTAL_SYSTEMS
        and isinstance(subset.get("datapoints"), list)
        and 6 <= len(subset["datapoints"]) <= 2009
    )


class StructureUnavailable(ValueError):
    """A structure cannot be safely represented within the supported
    scope."""

    def __init__(self, message, *, code="structure_invalid"):
        super().__init__(message)
        self.code = code


class StructureConnectionRequired(ValueError):
    """The exact source needs a verified connection."""


def _number(value, maximum=1_000_000):
    if (
        type(value) not in {int, float}
        or not math.isfinite(value)
        or abs(value) > maximum
    ):
        raise StructureUnavailable("The structure contains invalid numeric data.")
    return float(value)


def _vector(value, scale=1.0):
    if not isinstance(value, list) or len(value) != 3:
        raise StructureUnavailable("The structure has an unsupported coordinate shape.")
    return [_number(_number(item) * scale) for item in value]


def _dot(a, b):
    return math.fsum(x * y for x, y in zip(a, b, strict=True))


def _cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _cell(value, scale=1.0):
    if not isinstance(value, list) or len(value) != 3:
        raise StructureUnavailable("A complete periodic lattice is required.")
    vectors = [_vector(vector, scale) for vector in value]
    lengths = [math.sqrt(_dot(vector, vector)) for vector in vectors]
    determinant = _dot(vectors[0], _cross(vectors[1], vectors[2]))
    if (
        any(not 0.1 <= length <= 1000 for length in lengths)
        or determinant / math.prod(lengths) < 1e-6
    ):
        raise StructureUnavailable("The lattice is degenerate or exceeds size limits.")
    return vectors


def _fractional(position, cell):
    determinant = _dot(cell[0], _cross(cell[1], cell[2]))
    return [
        _number(_dot(position, _cross(cell[j], cell[k])) / determinant)
        for j, k in ((1, 2), (2, 0), (0, 1))
    ]


def _sites(elements, coordinates, cell, *, cartesian=False, scale=1.0):
    if (
        not isinstance(elements, list)
        or not isinstance(coordinates, list)
        or not 1 <= len(elements) <= MAX_SITES
        or len(elements) != len(coordinates)
        or any(
            not isinstance(symbol, str) or symbol not in _ELEMENTS
            for symbol in elements
        )
    ):
        raise StructureUnavailable("Unsupported atom identities or structure size.")
    result = []
    for element, value in zip(elements, coordinates, strict=True):
        vector = _vector(value, scale)
        fractional = _fractional(vector, cell) if cartesian else vector
        result.append([element, [component % 1.0 for component in fractional]])
    return result


def _check_composition(sites, formula):
    counts = Counter(site[0] for site in sites)
    structure_formula = "".join(
        element + str(count) for element, count in sorted(counts.items())
    )
    if _composition(structure_formula) != _composition(formula):
        raise StructureUnavailable(
            "Structure composition differs from the saved material."
        )


def _source(identity):
    if identity.startswith("hybrid3:"):
        match = hybrid3.IDENTITY.fullmatch(identity)
        if match is None:
            raise StructureUnavailable("Unsupported public HybriD³ identity.")
        return "HybriD³", (
            "https://materials.hybrid3.duke.edu/materials/dataset/" + match[2]
        )
    if identity.startswith("dielectric:"):
        return "Public dielectric dataset", dielectric.DATASET_URL
    if identity.startswith("mp-"):
        return "Materials Project", "https://materialsproject.org/materials/" + identity
    return (
        "NOMAD",
        "https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/" + identity[6:],
    )


def _mp(candidate, key):
    payload, digest, request_url = _request_mp_data(
        key, structure_id=candidate["material_id"]
    )
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise StructureUnavailable("The source did not return one exact structure.")
    row = rows[0]
    if (
        row.get("material_id") != candidate["material_id"]
        or row.get("deprecated") is not False
    ):
        raise StructureUnavailable("The source identity is unavailable or deprecated.")
    if _composition(row.get("formula_pretty")) != _composition(candidate["formula"]):
        raise StructureUnavailable("The source composition changed since the report.")
    cell, sites = _pymatgen_geometry(row.get("structure"))
    if (
        not isinstance(row.get("elements"), list)
        or any(not isinstance(v, str) for v in row["elements"])
        or sorted(set(row["elements"])) != sorted({site[0] for site in sites})
    ):
        raise StructureUnavailable("The source atom identities are inconsistent.")
    return cell, sites, digest, request_url, "mp_summary_structure"


def _pymatgen_geometry(structure):
    """Read only inert numeric geometry; never instantiate upstream MSON
    classes."""
    if not isinstance(structure, dict) or not isinstance(
        structure.get("lattice"), dict
    ):
        raise StructureUnavailable(
            "No supported structure is available for this material."
        )
    lattice = structure["lattice"]
    if "pbc" in lattice and (
        not isinstance(lattice["pbc"], list)
        or len(lattice["pbc"]) != 3
        or any(value is not True for value in lattice["pbc"])
    ):
        raise StructureUnavailable("Only fully periodic structures are supported.")
    cell = _cell(lattice.get("matrix"))
    atoms = structure.get("sites")
    if not isinstance(atoms, list) or not 1 <= len(atoms) <= MAX_SITES:
        raise StructureUnavailable("Unsupported atom count.")
    elements, positions = [], []
    for atom in atoms:
        species = atom.get("species") if isinstance(atom, dict) else None
        if (
            not isinstance(species, list)
            or len(species) != 1
            or not isinstance(species[0], dict)
            or type(species[0].get("occu")) not in {int, float}
            or species[0]["occu"] != 1
        ):
            raise StructureUnavailable(
                "Disordered or partial-occupancy structures are not supported."
            )
        elements.append(species[0].get("element"))
        positions.append(atom.get("abc"))
    sites = _sites(elements, positions, cell)
    return cell, sites


def _dielectric(candidate):
    record = dielectric.retrieve_structure_source(candidate["material_id"])
    if not isinstance(record, dict) or not isinstance(record.get("provenance"), dict):
        raise StructureUnavailable("The exact public dataset record failed validation.")
    provenance = record.get("provenance", {})
    saved = candidate.get("provenance", {})
    if (
        record.get("material_id") != candidate["material_id"]
        or provenance.get("source_url") != dielectric.DATASET_URL
        or provenance.get("response_sha256") != dielectric.UPSTREAM_SHA256
        or provenance.get("dataset_version") != dielectric.DATASET_VERSION
        or not isinstance(saved, dict)
        or saved.get("source_url") != dielectric.DATASET_URL
        or any(
            key not in saved or provenance.get(key) != saved[key]
            for key in (
                "dataset_version",
                "source_record_id",
                "upstream_row_index",
                "response_sha256",
                "upstream_row_sha256",
            )
        )
        or not isinstance(provenance.get("upstream_row_sha256"), str)
        or _DIGEST.fullmatch(provenance["upstream_row_sha256"]) is None
    ):
        raise StructureUnavailable("The exact public dataset record failed validation.")
    if _composition(record.get("formula")) != _composition(candidate["formula"]):
        raise StructureUnavailable("The source composition differs from the report.")
    cell, sites = _pymatgen_geometry(record.get("structure"))
    _check_composition(sites, candidate["formula"])
    for nsites in (candidate.get("nsites"), record.get("nsites")):
        if nsites is not None and (type(nsites) is not int or nsites != len(sites)):
            raise StructureUnavailable("The source atom count differs from the report.")
    return (
        cell,
        sites,
        provenance["response_sha256"],
        dielectric.DATASET_URL,
        "public_dielectric_structure",
    )


def _hybrid3_reference_source(candidate):
    """Revalidate an exact public crystallography dataset before reading
    atoms."""
    saved = candidate.get("structure_reference")
    match = hybrid3.IDENTITY.fullmatch(candidate["material_id"])
    if (
        match is None
        or not isinstance(saved, dict)
        or set(saved)
        != {"system_id", "dataset_id", "subset_id", "crystal_system", "response_sha256"}
        or any(
            type(saved[key]) is not int or saved[key] != int(expected)
            for key, expected in zip(
                ("system_id", "dataset_id", "subset_id"), match.groups(), strict=True
            )
        )
        or not isinstance(saved["response_sha256"], str)
        or _DIGEST.fullmatch(saved["response_sha256"]) is None
        or saved["crystal_system"] not in hybrid3._CRYSTAL_SYSTEMS
    ):
        raise StructureUnavailable(
            "The discovered crystallography identity is invalid."
        )
    deadline = time.monotonic() + hybrid3.MAX_SECONDS
    raw, _ = _fetch("hybrid3_dataset", {"record_id": saved["dataset_id"]}, deadline)
    row = _json(raw)
    if (
        not _hybrid3_structure_row(row, saved["system_id"], candidate["formula"])
        or row["pk"] != saved["dataset_id"]
    ):
        raise StructureUnavailable(
            "The cited public crystallography record changed or is unavailable."
        )
    subset = next(
        (
            item
            for item in row["subsets"]
            if isinstance(item, dict) and item.get("pk") == saved["subset_id"]
        ),
        None,
    )
    if (
        not _hybrid3_structure_subset(subset)
        or subset["crystal_system"] != saved["crystal_system"]
    ):
        raise StructureUnavailable(
            "The cited crystallography subset changed after discovery."
        )
    common = {
        "material_id": candidate["material_id"],
        "formula": candidate["formula"],
        "input_unit": "angstrom",
    }
    if len(subset["datapoints"]) > 9:
        try:
            atoms, url = _fetch(
                "hybrid3_coordinates", {"record_id": saved["subset_id"]}, deadline
            )
            payload = _json(atoms)
            if payload.get("coordinates"):
                return {
                    **common,
                    "coordinates": payload,
                    "request_url": url,
                    "response_sha256": hashlib.sha256(
                        canonical(
                            {
                                "dataset": hashlib.sha256(raw).hexdigest(),
                                "coordinates": hashlib.sha256(atoms).hexdigest(),
                            }
                        )
                    ).hexdigest(),
                }
        except PublicSourceError:
            pass  # An independently public CIF attachment may still be available.
    from labcat.science.cif_files import read_dataset_cif

    archive, url = _fetch(
        "hybrid3_dataset_files", {"record_id": saved["dataset_id"]}, deadline
    )
    try:
        cif = read_dataset_cif(archive, candidate["formula"], saved["crystal_system"])
    except (ValueError, RuntimeError, OSError, zipfile.BadZipFile, zlib.error) as error:
        raise StructureUnavailable(
            "No unique supported public CIF was found in this dataset."
        ) from error
    return {
        **common,
        "cif": cif,
        "request_url": url,
        "response_sha256": hashlib.sha256(
            canonical(
                {
                    "dataset": hashlib.sha256(raw).hexdigest(),
                    "archive": cif["archive_sha256"],
                    "cif": cif["sha256"],
                }
            )
        ).hexdigest(),
        "structure_match": "composition_reference",
        "structure_source_url": (
            "https://materials.hybrid3.duke.edu/materials/dataset/"
            f"{saved['dataset_id']}"
        ),
        "structure_differences": [
            "Different or unspecified property crystal system.",
            "Different or unspecified measurement conditions.",
        ],
    }


def _hybrid3(candidate):
    record = (
        _hybrid3_reference_source(candidate)
        if candidate.get("source_mode") == "live_hybrid3_structure"
        else hybrid3.retrieve_structure_source(candidate)
    )
    if isinstance(record.get("cif"), dict):
        if (
            record.get("material_id") != candidate["material_id"]
            or record.get("input_unit") != "angstrom"
            or _composition(record.get("formula")) != _composition(candidate["formula"])
        ):
            raise StructureUnavailable(
                "CIF provenance differs from the saved material."
            )
        source_cif = record["cif"]
        cell = _cell(source_cif["cell"])
        sites = _sites(
            [site[0] for site in source_cif["sites"]],
            [site[1] for site in source_cif["sites"]],
            cell,
        )
        _check_composition(sites, candidate["formula"])
        extra = {
            "structure_match": record["structure_match"],
            "structure_source_url": record["structure_source_url"],
            "structure_differences": record["structure_differences"],
            "source_cif": {
                key: source_cif[key]
                for key in (
                    "filename",
                    "block",
                    "sha256",
                    "archive_sha256",
                    "original_base64",
                )
            },
        }
        _cif_provenance(extra)
        return (
            cell,
            sites,
            record["response_sha256"],
            record["request_url"],
            "hybrid3_public_cif",
            extra,
        )
    raw = record.get("coordinates")
    if (
        record.get("material_id") != candidate["material_id"]
        or record.get("input_unit") != "angstrom"
        or not isinstance(raw, dict)
        or raw.get("coord-type") not in {"atom", "atom_frac"}
    ):
        raise StructureUnavailable("Unsupported public atom coordinate convention.")

    def scalar(value):
        if (
            not isinstance(value, str)
            or len(value) > 40
            or re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?", value)
            is None
        ):
            raise StructureUnavailable("Unsupported numeric atom coordinates.")
        return _number(float(value))

    vectors, atoms = raw.get("vectors"), raw.get("coordinates")
    if (
        not isinstance(vectors, list)
        or len(vectors) != 3
        or any(not isinstance(v, list) or len(v) != 3 for v in vectors)
        or not isinstance(atoms, list)
        or not 1 <= len(atoms) <= MAX_SITES
        or any(not isinstance(atom, list) or len(atom) != 4 for atom in atoms)
    ):
        raise StructureUnavailable("Unsupported public atom-list shape.")
    cell = _cell([[scalar(value) for value in vector] for vector in vectors])
    sites = _sites(
        [atom[0] for atom in atoms],
        [[scalar(value) for value in atom[1:]] for atom in atoms],
        cell,
        cartesian=raw["coord-type"] == "atom",
    )
    _check_composition(sites, candidate["formula"])
    return (
        cell,
        sites,
        record["response_sha256"],
        record["request_url"],
        "hybrid3_public_atoms",
    )


def _nomad(candidate):
    identity = candidate["material_id"][6:]
    body = {
        "owner": "public",
        "query": {"entry_id": identity},
        "pagination": {"page_size": 1},
        "required": {
            "metadata": {"entry_id": "*", "published": "*", "with_embargo": "*"},
            "run[-1]": {
                "system[-1]": {
                    "atoms": {
                        field: "*"
                        for field in (
                            "lattice_vectors",
                            "periodic",
                            "positions",
                            "labels",
                            "concentrations",
                        )
                    }
                }
            },
            "results": {
                "material": {"chemical_formula_reduced": "*", "structural_type": "*"},
                "properties": {
                    "structures": {
                        "structure_original": {
                            field: "*"
                            for field in (
                                "dimension_types",
                                "lattice_vectors",
                                "cartesian_site_positions",
                                "n_sites",
                                "species_at_sites",
                                "species",
                            )
                        }
                    }
                },
            },
        },
    }
    raw, request_url = _fetch(
        "nomad", {}, time.monotonic() + MAX_SECONDS, body, structure_archive=True
    )
    payload = _json(raw)
    rows = payload.get("data")
    if (
        payload.get("owner") != "public"
        or not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or rows[0].get("entry_id") != identity
    ):
        raise StructureUnavailable("No exact public structure was returned.")
    archive = rows[0].get("archive")
    metadata = _path(archive, "metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("entry_id") != identity
        or metadata.get("published") is not True
        or metadata.get("with_embargo") is not False
    ):
        raise StructureUnavailable(
            "The structure is not verified as public and non-embargoed.",
            code="structure_access_unverified",
        )
    formula = _path(archive, "results", "material", "chemical_formula_reduced")
    if (
        _composition(formula) != _composition(candidate["formula"])
        or _path(archive, "results", "material", "structural_type") != "bulk"
    ):
        raise StructureUnavailable(
            "The source structure differs from the saved material."
        )
    structure = _path(
        archive, "results", "properties", "structures", "structure_original"
    )
    if structure is None:
        # Older archives omit the representative result structure. Use only the
        # specifically requested terminal system; never scan frames for a match.
        runs = archive.get("run")
        systems = (
            runs[0].get("system")
            if isinstance(runs, list) and len(runs) == 1 and isinstance(runs[0], dict)
            else None
        )
        atoms = (
            systems[0].get("atoms")
            if isinstance(systems, list)
            and len(systems) == 1
            and isinstance(systems[0], dict)
            else None
        )
        if (
            not isinstance(atoms, dict)
            or not isinstance(atoms.get("periodic"), list)
            or len(atoms["periodic"]) != 3
            or any(v is not True for v in atoms["periodic"])
        ):
            raise StructureUnavailable(
                "No supported fully periodic structure is available."
            )
        cell = _cell(atoms.get("lattice_vectors"), 1e10)
        sites = _sites(
            atoms.get("labels"),
            atoms.get("positions"),
            cell,
            cartesian=True,
            scale=1e10,
        )
        concentrations = atoms.get("concentrations")
        if concentrations is not None and (
            not isinstance(concentrations, list)
            or len(concentrations) != len(sites)
            or any(
                type(value) not in {int, float} or value != 1
                for value in concentrations
            )
        ):
            raise StructureUnavailable("Partial-occupancy structures are unsupported.")
        return (
            cell,
            sites,
            hashlib.sha256(raw).hexdigest(),
            request_url,
            "nomad_terminal_system",
        )
    if (
        not isinstance(structure, dict)
        or structure.get("dimension_types") != [1, 1, 1]
        or any(type(v) is not int for v in structure.get("dimension_types", []))
    ):
        raise StructureUnavailable("Only fully periodic bulk structures are supported.")
    cell = _cell(structure.get("lattice_vectors"), 1e10)
    species = structure.get("species")
    if not isinstance(species, list) or not 1 <= len(species) <= MAX_SITES:
        raise StructureUnavailable("No supported atom species are available.")
    names = {}
    for item in species:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not re.fullmatch(r"[A-Za-z0-9_+-]{1,32}", item["name"])
            or item["name"] in names
            or not isinstance(item.get("chemical_symbols"), list)
            or len(item["chemical_symbols"]) != 1
            or not isinstance(item.get("concentration"), list)
            or len(item["concentration"]) != 1
            or type(item["concentration"][0]) not in {int, float}
            or item["concentration"][0] != 1
        ):
            raise StructureUnavailable("Disordered or unsupported atom species.")
        names[item["name"]] = item["chemical_symbols"][0]
    species_at_sites = structure.get("species_at_sites")
    if (
        not isinstance(species_at_sites, list)
        or not 1 <= len(species_at_sites) <= MAX_SITES
        or any(
            not isinstance(name, str) or name not in names for name in species_at_sites
        )
        or type(structure.get("n_sites")) is not int
        or structure["n_sites"] != len(species_at_sites)
    ):
        raise StructureUnavailable("The atom count or species map is inconsistent.")
    sites = _sites(
        [names[name] for name in species_at_sites],
        structure.get("cartesian_site_positions"),
        cell,
        cartesian=True,
        scale=1e10,
    )
    return (
        cell,
        sites,
        hashlib.sha256(raw).hexdigest(),
        request_url,
        "nomad_structure_original",
    )


def _cif_provenance(data):
    """Validate all retained attachment/provenance fields before cache
    or output."""
    source = data.get("source_cif")
    if not isinstance(source, dict) or set(source) != {
        "filename",
        "block",
        "sha256",
        "archive_sha256",
        "original_base64",
    }:
        raise StructureUnavailable("Unsupported source CIF provenance.")
    for key, pattern in (
        ("filename", r"[A-Za-z0-9_.-]{1,120}\.cif"),
        ("block", r"[A-Za-z0-9_.-]{1,80}"),
        ("sha256", r"[a-f0-9]{64}"),
        ("archive_sha256", r"[a-f0-9]{64}"),
    ):
        if not isinstance(source[key], str) or not re.fullmatch(
            pattern, source[key], re.I
        ):
            raise StructureUnavailable("Invalid source CIF provenance.")
    if (
        data.get("structure_match")
        not in {"source_metadata_match", "composition_reference"}
        or not isinstance(data.get("structure_source_url"), str)
        or not re.fullmatch(
            r"https://materials\.hybrid3\.duke\.edu/materials/dataset/[1-9][0-9]{0,8}",
            data["structure_source_url"],
        )
    ):
        raise StructureUnavailable("Invalid structure match provenance.")
    differences = data.get("structure_differences")
    allowed = {
        "Different source publication.",
        "Experimental structure; calculated property.",
        "Calculated structure; experimental property.",
        "Different sample type.",
        "Different or unspecified property crystal system.",
        "Different or unspecified measurement conditions.",
    }
    if (
        not isinstance(differences, list)
        or len(differences) > len(allowed)
        or any(
            not isinstance(value, str) or value not in allowed for value in differences
        )
        or len(set(differences)) != len(differences)
        or bool(differences) != (data["structure_match"] == "composition_reference")
    ):
        raise StructureUnavailable("Invalid structure match differences.")
    encoded = source["original_base64"]
    if not isinstance(encoded, str) or not 1 <= len(encoded) <= 1_333_336:
        raise StructureUnavailable("Source CIF exceeds its storage budget.")
    try:
        original = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise StructureUnavailable("Source CIF failed its integrity check.") from None
    if (
        not 1 <= len(original) <= 1_000_000
        or hashlib.sha256(original).hexdigest() != source["sha256"]
    ):
        raise StructureUnavailable("Source CIF failed its integrity check.")
    return original


def _cif(data):
    if data.get("representation") == "hybrid3_public_cif":
        _cif_provenance(data)
    cell = _cell(data["cell"])
    sites = _sites(
        [site[0] for site in data["sites"]], [site[1] for site in data["sites"]], cell
    )
    lengths = [math.sqrt(_dot(vector, vector)) for vector in cell]
    angles = [
        math.degrees(
            math.acos(
                max(-1, min(1, _dot(cell[i], cell[j]) / (lengths[i] * lengths[j])))
            )
        )
        for i, j in ((1, 2), (0, 2), (0, 1))
    ]
    lines = [
        "# Labcat derived coordinate export; not an original source file.",
        "# Full atom list in P1; symmetry has not been determined.",
        "# Source: "
        + (
            data["structure_source_url"]
            if data.get("representation") == "hybrid3_public_cif"
            else _source(data["material_id"])[1]
        ),
        "# Retrieved: " + data["retrieved_at"],
        "# Source response SHA256: " + data["response_sha256"],
        "data_labcat_structure",
        "_symmetry_space_group_name_H-M 'P 1'",
        "_symmetry_Int_Tables_number 1",
    ]
    lines.extend(
        f"_cell_length_{axis} {value:.12g}"
        for axis, value in zip("abc", lengths, strict=True)
    )
    lines.extend(
        f"_cell_angle_{axis} {value:.12g}"
        for axis, value in zip(("alpha", "beta", "gamma"), angles, strict=True)
    )
    lines.extend(
        [
            "loop_",
            "_symmetry_equiv_pos_as_xyz",
            "'x,y,z'",
            "loop_",
            "_atom_site_label",
            "_atom_site_type_symbol",
            "_atom_site_fract_x",
            "_atom_site_fract_y",
            "_atom_site_fract_z",
            "_atom_site_occupancy",
        ]
    )
    for index, (element, fractional) in enumerate(sites, 1):
        lines.append(
            f"{element}{index} {element} "
            + " ".join(f"{v:.12f}" for v in fractional)
            + " 1"
        )
    return ("\n".join(lines) + "\n").encode("ascii")


class StructureStore:
    """Cache one validated representation per report/candidate, with FK
    cleanup."""

    def __init__(self, workspace, connections, control_reader):
        self.workspace = workspace
        self.connections = connections
        self.control_reader = control_reader

    def initialize(self):
        with self.workspace._connection(write=True) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS report_structures ("
                "report_id TEXT NOT NULL, material_id TEXT NOT NULL, "
                "structure_json TEXT NOT NULL, sha256 TEXT NOT NULL, "
                "PRIMARY KEY(report_id, material_id), "
                "FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS report_structure_references ("
                "report_id TEXT NOT NULL, lead_id TEXT NOT NULL, "
                "lookup_json TEXT NOT NULL, sha256 TEXT NOT NULL, "
                "PRIMARY KEY(report_id, lead_id), "
                "FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE)"
            )

    def _result(self, connection, chat_id, report_id):
        row = connection.execute(
            "SELECT rr.outcome_json FROM visible_reports r "
            "LEFT JOIN research_runs rr ON r.id=rr.report_id "
            "WHERE r.id=? AND r.chat_id=?",
            (report_id, chat_id),
        ).fetchone()
        if row is None:
            raise WorkspaceNotFound("Saved report not found.")
        try:
            result = json.loads(row[0]) if row[0] is not None else {}
            if not isinstance(result, dict):
                raise ValueError("unsupported report")
            return result
        except (ValueError, TypeError, RecursionError) as error:
            raise StructureUnavailable("The saved report cannot be read.") from error

    def _literature(self, connection, report_id, result):
        if not result.get("candidate_leads"):
            return [], [], {}
        sources = []
        for row in connection.execute(
            "SELECT s.*,a.annotation_json FROM report_sources rs "
            "JOIN sources s ON s.id=rs.source_id AND s.project_id=rs.project_id "
            "LEFT JOIN source_annotations a ON a.source_id=s.id "
            "AND a.project_id=s.project_id WHERE rs.report_id=?",
            (report_id,),
        ):
            source = dict(row)
            if source.pop("annotation_json") is not None:
                source.update(json.loads(row["annotation_json"]))
            sources.append(source)

        from labcat.science.report_sources import (
            VERSION_PREFIX,
            report_scoped_sources,
        )

        for source in sources:
            version = connection.execute(
                "SELECT record_key FROM source_records "
                "WHERE source_id=? AND project_id=?",
                (source["id"], source["project_id"]),
            ).fetchone()
            if version is not None and version[0].startswith(VERSION_PREFIX):
                source["evidence_version"] = version[0]
        sources = report_scoped_sources(result, sources)
        leads = _candidate_leads(result, sources)
        ranks = {}
        try:
            evaluation = validated_literature_evaluation(result, sources)
            if evaluation:
                ranks = {
                    row["lead_id"]: row["rank"]
                    for row in evaluation["ranked_candidates"]
                }
                order = {identity: index for index, identity in enumerate(ranks)}
                leads.sort(key=lambda lead: order.get(lead["id"], len(order)))
        except (ValueError, TypeError, KeyError, AttributeError):
            pass  # A corrupt evaluation cannot authorize identities or ranks.
        return leads, sources, ranks

    def _name_resolution(self, connection, report_id, lead):
        """Read a source receipt without fetching or trusting cached
        formulas."""
        row = connection.execute(
            "SELECT lookup_json,sha256 FROM report_structure_references "
            "WHERE report_id=? AND lead_id=?",
            (report_id, lead["id"]),
        ).fetchone()
        if row is None:
            return None, None
        data = json.loads(row[0])
        if not isinstance(data, dict) or data.get("version") != 4:
            return None, None
        if (
            set(data)
            != {
                "version",
                "lead_id",
                "name",
                "formula",
                "references",
                "failed_sources",
                "identity_resolution",
                "identity_status",
            }
            or data["lead_id"] != lead["id"]
            or data["name"] != lead["name"]
            or data["identity_status"] not in {"resolved", "unresolved", "unavailable"}
            or hashlib.sha256(canonical(data)).hexdigest() != row[1]
        ):
            raise ValueError("Invalid public name resolution cache")
        if data["identity_status"] in {"unresolved", "unavailable"}:
            expected_failures = (
                ["materials_project"]
                if data["identity_status"] == "unavailable"
                else []
            )
            if (
                data["identity_resolution"] is not None
                or data["formula"] is not None
                or data["references"] != []
                or data["failed_sources"] != expected_failures
            ):
                raise ValueError("Invalid unresolved public name lookup")
            return data["identity_status"], None
        formula = structure_identity.validate_resolution(
            data["identity_resolution"], lead["name"]
        )
        if formula is None or data["formula"] != formula:
            raise ValueError("Invalid public name identity receipt")
        return "resolved", data["identity_resolution"]

    def _save_reference_lookup(self, chat_id, report_id, lead, initial_formula, data):
        encoded = canonical(data)
        with self.workspace._connection(write=True) as connection:
            current = self._result(connection, chat_id, report_id)
            current_leads, current_sources, _ = self._literature(
                connection, report_id, current
            )
            if (
                lead not in _structure_lookup_leads(current_leads)
                or _lookup_formula(lead, current_sources) != initial_formula
                or (
                    data["version"] == 4
                    and not _name_lookup_eligible(lead, current_sources)
                )
            ):
                raise WorkspaceNotFound("The saved candidate is no longer available.")
            connection.execute(
                "INSERT OR REPLACE INTO report_structure_references VALUES (?,?,?,?)",
                (
                    report_id,
                    lead["id"],
                    encoded.decode(),
                    hashlib.sha256(encoded).hexdigest(),
                ),
            )

    def _reference_lookup(
        self,
        connection,
        report_id,
        lead,
        formula,
        *,
        with_status=False,
        hint_only=False,
    ):
        if formula is None:
            # Older caches were allowed to interpret publication aliases as
            # formulas. Keep their bytes but do not advertise that association.
            return (None, []) if with_status else None
        row = connection.execute(
            "SELECT lookup_json,sha256 FROM report_structure_references "
            "WHERE report_id=? AND lead_id=?",
            (report_id, lead["id"]),
        ).fetchone()
        if row is None:
            return (None, []) if with_status else None
        data = json.loads(row[0])
        if hint_only and isinstance(data, dict) and data.get("version") not in {3, 4}:
            # Old caches could mistake aliases for formulas. Re-query through
            # the current adapter contract before offering their associations.
            return (None, []) if with_status else None
        if (
            not isinstance(data, dict)
            or data.get("version") not in {1, 2, 3, 4}
            or set(data)
            != (
                {"version", "lead_id", "name", "formula", "references"}
                | ({"failed_sources"} if data["version"] in {2, 3, 4} else set())
                | (
                    {"identity_resolution", "identity_status"}
                    if data["version"] == 4
                    else set()
                )
            )
            or data["lead_id"] != lead["id"]
            or data["name"] != lead["name"]
            # Existing caches may use the candidate's former formula spelling.
            # Permit only display reordering of the same unreduced counts after
            # the cited typed formula has independently authorized this lookup.
            or not isinstance(data["formula"], str)
            or display_formula(data["formula"]) != display_formula(formula)
            or not isinstance(data["references"], list)
            or len(data["references"]) > MAX_REFERENCE_RECORDS
            or (
                data["version"] in {2, 3, 4}
                and (
                    not isinstance(data["failed_sources"], list)
                    or any(
                        source not in {"nomad", "hybrid3", "materials_project"}
                        for source in data["failed_sources"]
                    )
                    or len(set(data["failed_sources"])) != len(data["failed_sources"])
                )
            )
            or hashlib.sha256(canonical(data)).hexdigest() != row[1]
        ):
            raise ValueError("Invalid reference lookup")
        if data["version"] == 4:
            status, receipt = self._name_resolution(connection, report_id, lead)
            if status != "resolved" or receipt["formula"] != formula:
                raise ValueError("Invalid resolved reference formula")
        records, identities = [], set()
        for reference in data["references"]:
            record = _repository_reference(reference, data["formula"])
            if (
                record is None
                or record["material_id"] in identities
                or not _matches_reference_formula(
                    record["formula"], formula, hint_only=hint_only
                )
            ):
                raise ValueError("Invalid reference record")
            if reference["source_id"] == "hybrid3":
                # A matching formula in another public system never becomes a
                # cited record or an established candidate phase.
                record["reference_relation"] = (
                    "cited_repository_record"
                    if any(
                        (
                            reference["source_id"],
                            reference["record_id"],
                            reference["url"],
                        )
                        == (
                            citation["source_id"],
                            citation["record_id"],
                            citation["url"],
                        )
                        for citation in lead["citations"]
                    )
                    else "composition_reference"
                )
            identities.add(record["material_id"])
            records.append(record)
        return (records, data.get("failed_sources", [])) if with_status else records

    def _literature_structures(self, connection, report_id, result):
        leads, sources, ranks = self._literature(connection, report_id, result)
        numeric = {
            row.get("material_id"): row
            for row in result.get("candidates", [])
            if isinstance(row, dict) and isinstance(row.get("material_id"), str)
        }

        def compatible(record):
            original = numeric.get(record["material_id"])
            if original is None:
                return True
            try:
                return _composition(original.get("formula")) == _composition(
                    record["formula"]
                )
            except (ValueError, TypeError, OverflowError):
                return False

        by_source = {
            (source.get("source_id"), source.get("record_id")): source
            for source in sources
        }
        records, options = {}, []
        for lead in _structure_lookup_leads(leads):
            component = lead.get("_structure_component")
            assigned_formula = _lead_formula(lead, sources)
            formula = _lookup_formula(lead, sources)
            hint_only = bool(component) or assigned_formula is None
            name_eligible = formula is None and _name_lookup_eligible(lead, sources)
            identity_status = None
            if name_eligible:
                identity_status, receipt = self._name_resolution(
                    connection, report_id, lead
                )
                if receipt is not None:
                    formula = receipt["formula"]
            cited = []
            for citation in lead["citations"]:
                reference = by_source.get(
                    (citation["source_id"], citation["record_id"])
                )
                source_formula = _typed_formula(reference)
                if (
                    source_formula is not None
                    and not any(
                        _matches_reference_formula(
                            source_formula, child["name"], hint_only=True
                        )
                        for child in _component_leads(lead)
                    )
                    and (
                        not component
                        or _matches_reference_formula(
                            source_formula, formula, hint_only=True
                        )
                    )
                    and (record := _nomad_reference(reference, source_formula))
                    and compatible(record)
                ):
                    cited.append(record)
            lookup, failures = self._reference_lookup(
                connection,
                report_id,
                lead,
                formula,
                with_status=True,
                hint_only=hint_only,
            )
            if lookup is not None:
                lookup = [record for record in lookup if compatible(record)]
                # HybriD³ lookups enumerate the exact cited system. Composition
                # fallback searches remain a different, conservative relation.
                cited.extend(
                    record
                    for record in lookup
                    if record.get("reference_relation") == "cited_repository_record"
                )
                lookup = [
                    record
                    for record in lookup
                    if record.get("reference_relation") != "cited_repository_record"
                ]
            # Existing exact public shortlist identities already carry adapter
            # composition. Attach references without copying or rescoring data.
            linked_ids = {record["material_id"] for record in [*cited, *(lookup or [])]}
            numeric_matches = [
                row
                for row in numeric.values()
                if formula is not None
                and row["material_id"] not in linked_ids
                and self._supported(row)
                and _matches_reference_formula(
                    row.get("formula"), formula, hint_only=hint_only
                )
            ][:MAX_REFERENCE_RECORDS]
            if numeric_matches:
                lookup = [*(lookup or []), *numeric_matches]
            for relation, group in (
                ("cited_repository_record", cited),
                ("composition_reference", lookup or []),
            ):
                for record in group:
                    actual_relation = "component_reference" if component else relation
                    saved = records.setdefault(
                        record["material_id"],
                        {
                            **record,
                            "literature_association": {
                                "relation": actual_relation,
                                "phase_match": "unverified",
                                "lead_ids": [],
                                "lead_names": [],
                            },
                        },
                    )
                    association = saved["literature_association"]
                    if actual_relation == "component_reference":
                        association["relation"] = actual_relation
                        link = {
                            key: component[key]
                            for key in ("lead_id", "component_id", "formula", "label")
                        }
                        links = association.setdefault("components", [])
                        if link not in links:
                            links.append(link)
                    elif (
                        relation == "composition_reference"
                        and association["relation"] != "component_reference"
                    ):
                        association["relation"] = relation
                    parent = component or {"lead_id": lead["id"], "name": lead["name"]}
                    if parent["lead_id"] not in association["lead_ids"]:
                        association["lead_ids"].append(parent["lead_id"])
                        association["lead_names"].append(parent["name"])
            status = (
                "cited_record_available"
                if cited
                else (
                    "references_found"
                    if lookup
                    else (
                        "reference_lookup_failed"
                        if failures or identity_status == "unavailable"
                        else (
                            "no_reference_matches"
                            if lookup is not None or identity_status == "unresolved"
                            else (
                                "reference_lookup_available"
                                if formula
                                or (name_eligible and identity_status is None)
                                else "unsupported"
                            )
                        )
                    )
                )
            )
            option = {"lead_id": lead["id"], "name": lead["name"], "status": status}
            if lead["id"] in ranks:
                option["rank"] = ranks[lead["id"]]
            if status == "unsupported":
                option["reason"] = (
                    "A composite expression or explicit molecular/cluster "
                    "atom count "
                    "cannot be reduced to a bulk composition reference. "
                    "No cross-record search is supported."
                    if assigned_formula is not None
                    else "No unambiguous typed composition or supported literal "
                    "formula search hint is available. Material names and aliases "
                    "require an independent public identity record."
                )
            elif status == "no_reference_matches":
                option["reason"] = (
                    "The bounded public name lookup did not establish one exact "
                    "compound composition. Retry the public lookup to check again; "
                    "no name or phase was guessed."
                    if identity_status == "unresolved"
                    else "The bounded public repository search returned no matching "
                    "reference records. "
                    "This does not establish that no structure exists."
                )
            elif status == "reference_lookup_failed":
                option["reason"] = (
                    "A public structure source was unavailable or failed validation. "
                    "Retry reference discovery; the saved report is unchanged."
                )
            if component:
                parent = next(
                    item for item in options if item["lead_id"] == component["lead_id"]
                )
                entry = {
                    key: component[key] for key in ("component_id", "formula", "label")
                }
                entry["status"] = status
                if "reason" in option:
                    entry["reason"] = option["reason"]
                parent.setdefault("components", []).append(entry)
            else:
                options.append(option)
        for option in options:
            if "components" not in option:
                continue
            statuses = [item["status"] for item in option["components"]]
            if option["status"] not in {"references_found", "cited_record_available"}:
                option["status"] = next(
                    (
                        status
                        for status in (
                            "references_found",
                            "cited_record_available",
                            "reference_lookup_available",
                            "reference_lookup_failed",
                            "no_reference_matches",
                        )
                        if status in statuses
                    ),
                    "unsupported",
                )
            option["reason"] = (
                "Separate component references do not represent the assembled "
                "heterostructure, interface or nanoparticle. Phase and morphology "
                "remain unverified."
            )
        return list(records.values()), options

    def _candidates(self, connection, chat_id, report_id):
        result = self._result(connection, chat_id, report_id)
        try:
            candidates = result.get("candidates", [])
            if not isinstance(candidates, list) or len(candidates) > 100:
                raise ValueError("unsupported shortlist")
            identities = [
                item.get("material_id") for item in candidates if isinstance(item, dict)
            ]
            if (
                len(identities) != len(candidates)
                or any(not isinstance(identity, str) for identity in identities)
                or len(set(identities)) != len(identities)
            ):
                raise ValueError("unsupported identities")
            literature, _ = self._literature_structures(connection, report_id, result)
            # Exact saved quantitative identities remain authoritative. Adding
            # association metadata never changes their provenance or properties.
            merged = {
                candidate["material_id"]: {
                    key: value
                    for key, value in candidate.items()
                    if key != "literature_association"
                }
                for candidate in candidates
            }
            for candidate in literature:
                if candidate["material_id"] in merged:
                    merged[candidate["material_id"]]["literature_association"] = (
                        candidate["literature_association"]
                    )
                else:
                    merged[candidate["material_id"]] = candidate
            return list(merged.values())
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RecursionError,
        ) as error:
            raise StructureUnavailable(
                "The saved shortlist cannot supply structure identities."
            ) from error

    def _candidate(self, connection, chat_id, report_id, material_id):
        for candidate in self._candidates(connection, chat_id, report_id):
            if candidate["material_id"] == material_id:
                return candidate
        raise WorkspaceNotFound("The material is not in this saved shortlist.")

    def _supported(self, candidate):
        identity = candidate.get("material_id")
        return (
            isinstance(identity, str)
            and bool(_IDENTITY.fullmatch(identity))
            and (
                identity.startswith("mp-")
                and candidate.get("source_mode")
                in {"live_materials_project", "public_snapshot"}
                or identity.startswith("nomad:")
                and candidate.get("source_mode") == "live_nomad"
                or identity.startswith("dielectric:")
                and candidate.get("source_mode") == "live_public_dielectric"
                or identity.startswith("hybrid3:")
                and candidate.get("source_mode")
                in {"live_hybrid3", "live_hybrid3_structure"}
            )
        )

    def _cached(self, connection, report_id, identity):
        row = connection.execute(
            "SELECT structure_json,sha256 FROM report_structures "
            "WHERE report_id=? AND material_id=?",
            (report_id, identity),
        ).fetchone()
        if row is None:
            return None
        try:
            data = json.loads(row[0])
            if (
                not _IDENTITY.fullmatch(identity)
                or data["material_id"] != identity
                or data["version"] != 1
                or (
                    data["representation"] == "hybrid3_public_cif"
                    and not identity.startswith("hybrid3:")
                )
                or data["representation"]
                not in {
                    "mp_summary_structure",
                    "nomad_structure_original",
                    "nomad_terminal_system",
                    "public_dielectric_structure",
                    "hybrid3_public_atoms",
                    "hybrid3_public_cif",
                }
                or not _DIGEST.fullmatch(data["response_sha256"])
                or not re.fullmatch(r"[0-9T:.+Z-]{10,40}", data["retrieved_at"])
                or hashlib.sha256(canonical(data)).hexdigest() != row[1]
            ):
                raise ValueError("integrity")
            _cif(data)
            return data
        except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
            raise StructureUnavailable(
                "The cached structure failed its integrity check."
            ) from error

    def _mp_readiness(self):
        try:
            return self.connections.source_connections()["materials_project"]
        except CredentialConnectionError:
            return {"status": "error", "selectable": False}

    def _metadata(self, candidate, report_id, chat_id, data=None):
        identity = candidate["material_id"]
        source_formula = candidate.get("formula", "")
        if not isinstance(source_formula, str):
            raise StructureUnavailable("The saved material formula is invalid.")
        supported = self._supported(candidate)
        name, url = _source(identity) if supported else ("Unsupported source", "")
        base = {
            "material_id": identity,
            "formula": display_formula(source_formula),
            "source_formula": source_formula,
            "source_name": name,
            "source_url": url,
            "status": "not_loaded" if supported else "unsupported",
            "caveats": list(_CAVEATS),
        }
        if association := candidate.get("literature_association"):
            base["literature_association"] = association
            base["caveats"].append(_REFERENCE_CAVEAT)
            if association.get("components"):
                base["caveats"].append(
                    "Independent component reference: this is not an assembled "
                    "heterostructure, interface or core–shell nanoparticle. "
                    "Component order does not establish core/shell roles."
                )
        if data is not None:
            _check_composition(data["sites"], candidate["formula"])
            prefix = (
                f"/api/chats/{quote(chat_id, safe='')}/reports/"
                f"{quote(report_id, safe='')}/structures/{quote(identity, safe='')}"
            )
            base.update(
                status="ready",
                id=identity,
                filename=identity.replace(":", "-") + "-derived.cif",
                download_url=prefix + "/download",
                content_url=prefix + "/content",
                sha256=hashlib.sha256(_cif(data)).hexdigest(),
                response_sha256=data["response_sha256"],
                retrieved_at=data["retrieved_at"],
                n_sites=len(data["sites"]),
                format="cif",
                derived=True,
                representation=data["representation"],
            )
            if data["representation"] == "nomad_terminal_system":
                base["caveats"].append(
                    "The normalized representative structure was absent. This is "
                    "the last system in the entry's last recorded run, not a "
                    "verified representative of every property in the report."
                )
            elif data["representation"] == "public_dielectric_structure":
                base["caveats"].append(
                    "The exact historical bulk-crystal dataset supplies the periodic "
                    "lattice convention; absent per-axis periodicity flags are not "
                    "a fresh determination of dimensionality. No current Materials "
                    "Project structure or property was joined to this release."
                )
            elif data["representation"] == "hybrid3_public_atoms":
                base["caveats"].append(
                    "Explicit source atom entries from a unique structure dataset "
                    "matched by system, publication, sample and crystal system. "
                    "This does not prove identical microscopic phase, disorder "
                    "or experimental processing history."
                )
            elif data["representation"] == "hybrid3_public_cif":
                base.update(
                    {
                        key: data[key]
                        for key in (
                            "structure_match",
                            "structure_source_url",
                            "structure_differences",
                        )
                    }
                )
                base["source_cif"] = {
                    key: value
                    for key, value in data["source_cif"].items()
                    if key != "original_base64"
                }
                base["source_cif"]["download_url"] = prefix + "/original"
                base["caveats"].append(
                    "The viewer and derived download expand the selected source CIF "
                    "block using its explicit symmetry. The original attachment "
                    "retains the source file and may contain other CIF blocks."
                )
                base["caveats"].append(
                    "Composition-matched reference structure: the crystallography "
                    "metadata differs from the ranked property record. It is not "
                    "evidence of that property's phase or measurement conditions."
                    if data["structure_match"] == "composition_reference"
                    else "Source metadata matches the property record; identical "
                    "microscopic phase and processing history are not established."
                )
        elif not supported:
            base["reason"] = (
                "No approved structure adapter is available for this source identity."
            )
        elif identity.startswith("mp-"):
            connection = self._mp_readiness()
            if connection.get("status") == "verification_required" and callable(
                getattr(self.connections, "prepare_materials_project", None)
            ):
                # This nonsecret state means a configured, unlocked key. Keep
                # the explicit retrieve action reachable; it performs the probe.
                base["reason"] = (
                    "The saved API key will be verified when you open this structure."
                )
            elif not connection["selectable"]:
                base.update(
                    status="connection_required",
                    reason="Verify the source API key in Connections to retrieve "
                    "this structure.",
                )
        return base

    def list(self, chat_id, report_id):
        with self.workspace._connection() as connection:
            records = [
                self._metadata(
                    candidate,
                    report_id,
                    chat_id,
                    self._cached(connection, report_id, candidate["material_id"]),
                )
                for candidate in self._candidates(connection, chat_id, report_id)
            ]
            _, literature = self._literature_structures(
                connection, report_id, self._result(connection, chat_id, report_id)
            )
        return {
            "viewer_enabled": self.control_reader()["viewer_enabled"],
            "structures": records,
            "literature_candidates": literature,
        }

    def find_references(
        self,
        chat_id,
        report_id,
        lead_id,
        *,
        enabled_sources=None,
        materials_project_mode=None,
        _deadline=None,
    ):
        """Look up the whole candidate and its independent cited
        components."""
        deadline = min(_deadline or float("inf"), time.monotonic() + MAX_SECONDS)
        with self.workspace._connection() as connection:
            result = self._result(connection, chat_id, report_id)
            try:
                leads, sources, _ = self._literature(connection, report_id, result)
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                raise StructureUnavailable(
                    "The saved candidate cannot be verified."
                ) from error
            lead = next((item for item in leads if item["id"] == lead_id), None)
            if lead is None:
                raise WorkspaceNotFound("The candidate is not in this saved shortlist.")
            children = _component_leads(lead)
        if not children:
            return self._find_reference(
                chat_id,
                report_id,
                lead_id,
                enabled_sources=enabled_sources,
                materials_project_mode=materials_project_mode,
                _deadline=deadline,
            )
        scopes = children
        if _formula_hint(lead, sources) or _name_lookup_eligible(lead, sources):
            scopes = [lead, *children]
        for index, scope in enumerate(scopes):
            now = time.monotonic()
            if now >= deadline:
                break
            # Reserve each component a share: one slow source must not consume
            # the entire candidate's allowance before its sibling is attempted.
            component_deadline = now + (deadline - now) / (len(scopes) - index)
            try:
                self._find_reference(
                    chat_id,
                    report_id,
                    scope["id"],
                    enabled_sources=enabled_sources,
                    materials_project_mode=materials_project_mode,
                    _deadline=component_deadline,
                )
            except StructureUnavailable:
                continue
        return self.list(chat_id, report_id)

    def _find_reference(
        self,
        chat_id,
        report_id,
        lead_id,
        *,
        enabled_sources=None,
        materials_project_mode=None,
        _deadline=None,
    ):
        """Resolve cited repositories first, then a bounded composition
        fallback."""
        allowed = (
            {"hybrid3", "nomad"}
            if enabled_sources is None
            else set(enabled_sources) & {"hybrid3", "nomad"}
        )
        allow_mp = materials_project_mode in {None, "auto", "api"}
        deadline = (
            min(_deadline, time.monotonic() + MAX_SECONDS)
            if _deadline is not None
            else time.monotonic() + MAX_SECONDS
        )
        with self.workspace._connection() as connection:
            result = self._result(connection, chat_id, report_id)
            try:
                leads, sources, _ = self._literature(connection, report_id, result)
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                raise StructureUnavailable(
                    "The saved candidate cannot be verified."
                ) from error
            lead = next(
                (
                    item
                    for item in _structure_lookup_leads(leads)
                    if item["id"] == lead_id
                ),
                None,
            )
            if lead is None:
                raise WorkspaceNotFound("The candidate is not in this saved shortlist.")
            initial_formula = formula = _lookup_formula(lead, sources)
            hint_only = (
                bool(lead.get("_structure_component"))
                or _lead_formula(lead, sources) is None
            )
            name_eligible = formula is None and _name_lookup_eligible(lead, sources)
            identity_resolution = None
            if name_eligible:
                try:
                    _, identity_resolution = self._name_resolution(
                        connection, report_id, lead
                    )
                except (ValueError, TypeError, KeyError) as error:
                    raise StructureUnavailable(
                        "The saved public name lookup is invalid."
                    ) from error
                if identity_resolution is not None:
                    formula = identity_resolution["formula"]
            if formula is None and not name_eligible:
                raise StructureUnavailable(
                    "No complete source-bound formula is available "
                    "for reference lookup.",
                    code="structure_reference_unsupported",
                )
            try:
                cached = self._reference_lookup(
                    connection, report_id, lead, formula, hint_only=hint_only
                )
            except (ValueError, TypeError, KeyError) as error:
                raise StructureUnavailable(
                    "The saved reference lookup is invalid."
                ) from error
            numeric_match = any(
                isinstance(row, dict)
                and self._supported(row)
                and _matches_reference_formula(
                    row.get("formula"), formula, hint_only=hint_only
                )
                for row in result.get("candidates", [])
            )
        if cached or numeric_match:
            return self.list(chat_id, report_id)
        if not allowed and not allow_mp:
            return self.list(chat_id, report_id)
        if not _NETWORK_SLOTS.acquire(blocking=False):
            raise StructureUnavailable(
                "Two structures are already loading.", code="structure_busy"
            )
        try:
            prepare_failed = False
            if allow_mp:
                prepare = getattr(self.connections, "prepare_materials_project", None)
                if prepare is not None:
                    try:
                        with repository_budget(
                            seconds=max(0, deadline - time.monotonic())
                        ):
                            prepare(materials_project_mode or "auto")
                    except (SourceError, ValueError, CredentialConnectionError):
                        prepare_failed = True
                mp_connection = self._mp_readiness()
                prepare_failed = (
                    prepare_failed or mp_connection.get("status") == "error"
                )
                if mp_connection["selectable"]:
                    allowed.add("materials_project")
            if not allowed:
                if prepare_failed:
                    data = {
                        "version": 3,
                        "lead_id": lead_id,
                        "name": lead["name"],
                        "formula": formula,
                        "references": [],
                        "failed_sources": ["materials_project"],
                    }
                    if identity_resolution is not None:
                        data.update(
                            version=4,
                            identity_resolution=identity_resolution,
                            identity_status="resolved",
                        )
                    elif formula is None:
                        data.update(
                            version=4,
                            identity_resolution=None,
                            identity_status="unavailable",
                        )
                    self._save_reference_lookup(
                        chat_id, report_id, lead, initial_formula, data
                    )
                return self.list(chat_id, report_id)
            if formula is None:
                identity_resolution = structure_identity.lookup_name(
                    lead["name"], deadline
                )
                formula = structure_identity.validate_resolution(
                    identity_resolution, lead["name"]
                )
                data = {
                    "version": 4,
                    "lead_id": lead_id,
                    "name": lead["name"],
                    "formula": formula,
                    "references": [],
                    "failed_sources": [],
                    "identity_status": "resolved" if formula else "unresolved",
                    "identity_resolution": identity_resolution if formula else None,
                }
                if formula is None and prepare_failed:
                    data.update(
                        identity_status="unavailable",
                        failed_sources=["materials_project"],
                    )
                if formula is None or any(
                    isinstance(row, dict)
                    and self._supported(row)
                    and _matches_reference_formula(
                        row.get("formula"), formula, hint_only=True
                    )
                    for row in result.get("candidates", [])
                ):
                    self._save_reference_lookup(
                        chat_id, report_id, lead, initial_formula, data
                    )
                    return self.list(chat_id, report_id)
            citations = {
                (item["source_id"], item["record_id"], item["url"])
                for item in lead["citations"]
            }
            cited = [
                source
                for source in sources
                if (source.get("source_id"), source.get("record_id"), source.get("url"))
                in citations
            ]
            if any(_nomad_reference(source, formula) for source in cited):
                return self.list(chat_id, report_id)
            references = []
            failures = ["materials_project"] if prepare_failed else []
            inspected_systems = set()
            if "hybrid3" in allowed:
                for source in cited:
                    system = _hybrid3_system(source, formula)
                    if system is None or system in inspected_systems:
                        continue
                    inspected_systems.add(system)
                    try:
                        # Reserve time for an independent repository when one
                        # source is slow. All adapters receive the shared bound.
                        source_deadline = min(
                            deadline,
                            time.monotonic()
                            + max(
                                0.1,
                                (deadline - time.monotonic())
                                / (2 + len(allowed - {"hybrid3"})),
                            ),
                        )
                        references.extend(
                            _hybrid3_reference_records(source, formula, source_deadline)
                        )
                    except (
                        PublicSourceError,
                        SourceError,
                        ValueError,
                        TypeError,
                        KeyError,
                        OverflowError,
                        RecursionError,
                    ):
                        failures.append("hybrid3")
                    if references or time.monotonic() >= deadline:
                        break
                if not references and time.monotonic() < deadline:
                    try:
                        fallback_deadline = min(
                            deadline,
                            time.monotonic()
                            + max(
                                0.1,
                                (deadline - time.monotonic())
                                / (1 + len(allowed - {"hybrid3"})),
                            ),
                        )
                        alternatives, _ = _search_hybrid3(
                            formula, MAX_REFERENCE_RECORDS, fallback_deadline
                        )
                        if (
                            not isinstance(alternatives, list)
                            or len(alternatives) > MAX_REFERENCE_RECORDS
                        ):
                            raise ValueError("Too many public compound identities")
                        inspected_alternatives = 0
                        for source in alternatives:
                            system = _hybrid3_system(source, formula)
                            if system is None or not _matches_reference_formula(
                                source["metadata"]["formula"],
                                formula,
                                hint_only=hint_only,
                            ):
                                raise ValueError("Invalid public compound identity")
                            if system in inspected_systems:
                                continue
                            inspected_systems.add(system)
                            references.extend(
                                _hybrid3_reference_records(
                                    source, formula, fallback_deadline
                                )
                            )
                            inspected_alternatives += 1
                            if (
                                references
                                or inspected_alternatives >= 2
                                or time.monotonic() >= fallback_deadline
                            ):
                                break
                    except (
                        PublicSourceError,
                        SourceError,
                        ValueError,
                        TypeError,
                        KeyError,
                        OverflowError,
                        RecursionError,
                    ):
                        failures.append("hybrid3")
            if (
                not references
                and "materials_project" in allowed
                and time.monotonic() < deadline
            ):
                try:
                    key = self.connections.materials_project_key("api")
                    if key is None:
                        raise SourceError("A verified source connection is required.")
                    mp_deadline = min(
                        deadline,
                        time.monotonic()
                        + (deadline - time.monotonic())
                        / (2 if "nomad" in allowed else 1),
                    )
                    references = _search_mp_references(
                        formula, key, mp_deadline, hint_only=hint_only
                    )
                except (
                    SourceError,
                    ValueError,
                    TypeError,
                    KeyError,
                    OverflowError,
                    RecursionError,
                ):
                    references = []
                    failures.append("materials_project")
            if not references and "nomad" in allowed and time.monotonic() < deadline:
                try:
                    references, _ = _search_nomad(
                        formula, MAX_REFERENCE_RECORDS, deadline
                    )
                    if (
                        not isinstance(references, list)
                        or len(references) > MAX_REFERENCE_RECORDS
                    ):
                        raise ValueError("Too many reference identities")
                    if any(
                        _nomad_reference(reference, formula) is None
                        or not _matches_reference_formula(
                            reference["metadata"]["formula"],
                            formula,
                            hint_only=hint_only,
                        )
                        for reference in references
                    ):
                        raise ValueError("Invalid public reference identity")
                except (
                    PublicSourceError,
                    ValueError,
                    TypeError,
                    KeyError,
                    OverflowError,
                    RecursionError,
                ):
                    references = []
                    failures.append("nomad")
            identities = set()
            for reference in references:
                record = _repository_reference(reference, formula)
                if (
                    record is None
                    or record["material_id"] in identities
                    or not _matches_reference_formula(
                        record["formula"], formula, hint_only=hint_only
                    )
                ):
                    raise StructureUnavailable(
                        "The reference search failed validation."
                    )
                identities.add(record["material_id"])
            data = {
                "version": 3,
                "lead_id": lead_id,
                "name": lead["name"],
                "formula": formula,
                "references": references[:MAX_REFERENCE_RECORDS],
                "failed_sources": sorted(set(failures)),
            }
            if identity_resolution is not None:
                data.update(
                    version=4,
                    identity_resolution=identity_resolution,
                    identity_status="resolved",
                )
            self._save_reference_lookup(chat_id, report_id, lead, initial_formula, data)
            if failures and not references:
                raise StructureUnavailable(
                    "The public repositories could not complete the reference search.",
                    code="structure_source_unavailable",
                )
            return self.list(chat_id, report_id)
        finally:
            _NETWORK_SLOTS.release()

    def discover_references(
        self, chat_id, report_id, *, enabled_sources=None, materials_project_mode=None
    ):
        """Best-effort post-report discovery; no atoms, inferred
        formulas or reranking.

        At most twelve ranked leads share eighteen seconds of public
        adapter time. Completed, empty and failed lookups are retained;
        explicit user retries remain available without repeating the
        work whenever a report is opened.
        """
        deadline = time.monotonic() + MAX_DISCOVERY_SECONDS
        listed = self.list(chat_id, report_id)
        pending = [
            item
            for item in listed["literature_candidates"]
            if item["status"] == "reference_lookup_available"
            or any(
                component["status"] == "reference_lookup_available"
                for component in item.get("components", [])
            )
        ][:MAX_DISCOVERY_LEADS]
        for lead in pending:
            if time.monotonic() >= deadline:
                break
            try:
                self.find_references(
                    chat_id,
                    report_id,
                    lead["lead_id"],
                    enabled_sources=enabled_sources,
                    materials_project_mode=materials_project_mode,
                    _deadline=deadline,
                )
            except StructureUnavailable:
                # Optional discovery cannot discard a saved research report, and
                # one repository/lead failure does not block independent results.
                continue
        return self.list(chat_id, report_id)

    def retrieve(self, chat_id, report_id, material_id):
        with self.workspace._connection() as connection:
            candidate = self._candidate(connection, chat_id, report_id, material_id)
            cached = self._cached(connection, report_id, material_id)
        if cached is not None:
            return self._metadata(candidate, report_id, chat_id, cached)
        if not self._supported(candidate):
            raise StructureUnavailable(
                "No approved structure adapter supports this saved candidate."
            )
        if not _NETWORK_SLOTS.acquire(blocking=False):
            raise StructureUnavailable(
                "Two structures are already loading. Please retry shortly.",
                code="structure_busy",
            )
        try:
            try:
                extra = {}
                if material_id.startswith("dielectric:"):
                    cell, sites, digest, _, representation = _dielectric(candidate)
                elif material_id.startswith("hybrid3:"):
                    result = _hybrid3(candidate)
                    cell, sites, digest, _, representation = result[:5]
                    if len(result) == 6:
                        extra = result[5]
                elif material_id.startswith("mp-"):
                    with repository_budget(seconds=MAX_SECONDS):
                        prepare = getattr(
                            self.connections, "prepare_materials_project", None
                        )
                        if prepare is not None:
                            prepare("api")
                        key = self.connections.materials_project_key("api")
                        if not key:
                            raise StructureConnectionRequired(
                                "Verify the source API connection first."
                            )
                        cell, sites, digest, _, representation = _mp(candidate, key)
                else:
                    cell, sites, digest, _, representation = _nomad(candidate)
                _check_composition(sites, candidate["formula"])
                data = {
                    "version": 1,
                    "material_id": material_id,
                    "cell": cell,
                    "sites": sites,
                    "representation": representation,
                    "response_sha256": digest,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    **extra,
                }
                _cif(data)
            except (StructureUnavailable, StructureConnectionRequired):
                raise
            except hybrid3.StructureSourceError as error:
                raise StructureUnavailable(str(error), code=error.code) from error
            except PublicSourceError as error:
                raise StructureUnavailable(
                    "The public repository could not complete this request. "
                    "Retry shortly; no substitute structure was generated.",
                    code="structure_source_unavailable",
                ) from error
            except (
                SourceError,
                CredentialConnectionError,
                ValueError,
                TypeError,
                KeyError,
                OverflowError,
                RecursionError,
            ) as error:
                raise StructureUnavailable(
                    "The public structure was unavailable or failed validation; "
                    "no substitute was generated."
                ) from error
            with self.workspace._connection(write=True) as connection:
                self._candidate(connection, chat_id, report_id, material_id)
                encoded = canonical(data)
                connection.execute(
                    "INSERT OR IGNORE INTO report_structures VALUES (?,?,?,?)",
                    (
                        report_id,
                        material_id,
                        encoded.decode(),
                        hashlib.sha256(encoded).hexdigest(),
                    ),
                )
                cached = self._cached(connection, report_id, material_id)
            return self._metadata(candidate, report_id, chat_id, cached)
        finally:
            _NETWORK_SLOTS.release()

    def content(self, chat_id, report_id, material_id):
        with self.workspace._connection() as connection:
            candidate = self._candidate(connection, chat_id, report_id, material_id)
            data = self._cached(connection, report_id, material_id)
        if data is None:
            raise WorkspaceNotFound("Retrieve the structure before downloading it.")
        return _cif(data), self._metadata(candidate, report_id, chat_id, data)

    def original_content(self, chat_id, report_id, material_id):
        with self.workspace._connection() as connection:
            self._candidate(connection, chat_id, report_id, material_id)
            data = self._cached(connection, report_id, material_id)
        if data is None or data["representation"] != "hybrid3_public_cif":
            raise WorkspaceNotFound("No original CIF was retained for this structure.")
        return _cif_provenance(data), {
            "filename": data["source_cif"]["filename"],
            "sha256": data["source_cif"]["sha256"],
        }
