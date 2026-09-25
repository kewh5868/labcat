"""Optional public composition labels, kept separate from scientific
evidence.

Only report-bound candidate identities can supply lookup hints. A
returned name labels a composition; it never verifies phase, properties
or ranking suitability.
"""

import hashlib
import math
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from labcat.public_sources import PublicSourceError, _fetch, _json
from labcat.science.formula_display import display_formula, flat_formula_tokens
from labcat.science.rebuild_snapshot import canonical
from labcat.science.report_sources import report_scoped_sources
from labcat.science.reporting import _candidate_leads, approved_citation_url
from labcat.untrusted_text import source_instruction_reason

MAX_TARGETS = 112
MAX_LOOKUPS = 12
MAX_SECONDS = 12
MAX_CACHE = 256
POSITIVE_TTL = 24 * 60 * 60
NEGATIVE_TTL = 5 * 60
_NETWORK_SLOTS = threading.BoundedSemaphore(2)


class ChemicalNameRequest(BaseModel):
    """A caller can request saved identities, never submit names or
    formulas."""

    model_config = ConfigDict(extra="forbid")


def formula_key(formula):
    """Exact unreduced atom counts; never molecular or phase
    equivalence."""
    if not isinstance(formula, str):
        return None
    parts = flat_formula_tokens(formula)
    if not parts or not 2 <= len(parts) <= 12:
        return None
    counts = tuple(sorted((symbol, int(count or "1")) for symbol, count in parts))
    if any(count > 10000 for _, count in counts):
        return None
    return counts


def _literal_formula_hint(value):
    """Untyped labels need more than an all-capital abbreviation."""
    parts = flat_formula_tokens(value) if isinstance(value, str) else None
    return bool(
        formula_key(value) is not None
        and parts
        and (re.search(r"[0-9]", value) or any(len(symbol) == 2 for symbol, _ in parts))
    )


def component_formulas(value):
    """Split bounded literal composition labels; never assign core/shell
    roles."""
    if not isinstance(value, str) or len(value) > 160:
        return []
    value = value.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉∕⁄", "0123456789//"))
    parts = re.split(r"[/@]", value)
    if not 2 <= len(parts) <= 3:
        return []
    formulas = []
    for part in parts:
        formula = re.sub(r"(?<=[A-Za-z])\s+(?=\d)", "", part.strip())
        if not _literal_formula_hint(formula):
            return []
        formulas.append(display_formula(formula))
    return formulas


def lookup_eligible(formula):
    counts = formula_key(formula)
    if counts is None:
        return False
    # A formula alone cannot select an organic isomer. The deliberately narrow
    # initial adapter omits carbon/hydrogen compositions, mixtures and morphology.
    return not {"C", "H"}.issubset(dict(counts))


def safe_name(name):
    if (
        not isinstance(name, str)
        or not 3 <= len(name) <= 200
        or name != name.strip()
        or any(unicodedata.category(char).startswith("C") for char in name)
        or any(char in name for char in "<>|{}\\")
        or re.search(r"https?://|www\.", name, re.I)
        or not re.search(r"[a-z]{3}", name, re.I)
        or flat_formula_tokens(name) is not None
        or source_instruction_reason(name)
    ):
        return None
    return name


def lookup_pubchem(formula, deadline):
    """Accept exactly one PubChem CID and a matching complete molecular
    formula."""
    if not lookup_eligible(formula) or type(deadline) not in {int, float}:
        return None
    now = time.monotonic()
    if not math.isfinite(deadline) or deadline <= now:
        return None
    deadline = min(deadline, now + 4)
    try:
        raw, query_url = _fetch("pubchem_formula", {"formula": formula}, deadline)
        if len(raw) > 65536:
            return None
        data = _json(raw)
        if set(data) != {"IdentifierList"}:
            return None
        identifiers = data["IdentifierList"]
        if not isinstance(identifiers, dict) or set(identifiers) != {"CID"}:
            return None
        cids = identifiers["CID"]
        if (
            not isinstance(cids, list)
            or len(cids) != 1
            or type(cids[0]) is not int
            or not 0 < cids[0] < 10**10
            or time.monotonic() >= deadline
        ):
            return None
        cid = cids[0]
        properties_raw, property_url = _fetch("pubchem_names", {"cid": cid}, deadline)
        if len(properties_raw) > 65536 or time.monotonic() >= deadline:
            return None
        data = _json(properties_raw)
        rows = data.get("PropertyTable", {}).get("Properties")
        if (
            not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], dict)
        ):
            return None
        row = rows[0]
        if (
            type(row.get("CID")) is not int
            or row["CID"] != cid
            or formula_key(row.get("MolecularFormula")) != formula_key(formula)
        ):
            return None
        field = next(
            (key for key in ("Title", "IUPACName") if safe_name(row.get(key))), None
        )
        if field is None:
            return None
        expected_query = (
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/fastformula/"
            + quote(formula, safe="")
            + "/cids/JSON?MaxRecords=3"
        )
        expected_property = (
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/"
            "property/MolecularFormula,IUPACName,Title/JSON"
        )
        if query_url != expected_query or property_url != expected_property:
            return None
        return {
            "formula": row["MolecularFormula"],
            "name": row[field],
            "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
            "source_name": "PubChem",
            "provenance": {
                "source_id": "pubchem",
                "record_id": str(cid),
                "query_formula": formula,
                "name_field": field,
                "request_url": query_url,
                "property_url": property_url,
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "property_sha256": hashlib.sha256(properties_raw).hexdigest(),
                "retrieved_at": datetime.now(UTC).isoformat(),
                "scope": "composition_name_only",
                "phase_match": "unverified",
            },
        }
    except (
        PublicSourceError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        return None


def lookup_pubchem_exact(formula, deadline):
    """Resolve an exact public formula synonym, never choose among
    formula hits."""
    if not lookup_eligible(formula) or type(deadline) not in {int, float}:
        return None
    if not math.isfinite(deadline) or deadline <= time.monotonic():
        return None
    deadline = min(deadline, time.monotonic() + 3)
    try:
        raw, query_url = _fetch("pubchem_identity", {"name": formula}, deadline)
        if len(raw) > 65536 or time.monotonic() >= deadline:
            return None
        rows = _json(raw).get("PropertyTable", {}).get("Properties")
        if (
            not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], dict)
        ):
            return None
        cid = rows[0].get("CID")
        if (
            type(cid) is not int
            or not 0 < cid < 10**10
            or formula_key(rows[0].get("MolecularFormula")) != formula_key(formula)
        ):
            return None
        properties_raw, property_url = _fetch("pubchem_names", {"cid": cid}, deadline)
        if len(properties_raw) > 65536 or time.monotonic() >= deadline:
            return None
        properties = _json(properties_raw).get("PropertyTable", {}).get("Properties")
        if (
            not isinstance(properties, list)
            or len(properties) != 1
            or not isinstance(properties[0], dict)
        ):
            return None
        row = properties[0]
        if (
            type(row.get("CID")) is not int
            or row["CID"] != cid
            or formula_key(row.get("MolecularFormula")) != formula_key(formula)
        ):
            return None
        field = next(
            (key for key in ("Title", "IUPACName") if safe_name(row.get(key))), None
        )
        expected_query = (
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
            + quote(formula, safe="")
            + "/property/MolecularFormula/JSON?name_type=complete"
        )
        expected_property = (
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/"
            "property/MolecularFormula,IUPACName,Title/JSON"
        )
        if (
            field is None
            or query_url != expected_query
            or property_url != expected_property
        ):
            return None
        return {
            "formula": row["MolecularFormula"],
            "name": row[field],
            "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
            "source_name": "PubChem",
            "provenance": {
                "source_id": "pubchem",
                "record_id": str(cid),
                "query_formula": formula,
                "name_field": field,
                "request_url": query_url,
                "property_url": property_url,
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "property_sha256": hashlib.sha256(properties_raw).hexdigest(),
                "retrieved_at": datetime.now(UTC).isoformat(),
                "scope": "composition_name_only",
                "phase_match": "unverified",
                "identity_method": "exact_public_formula_synonym",
            },
        }
    except (
        PublicSourceError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        return None


def _targets(report):
    result, sources = report.get("result"), report.get("sources", [])
    if not isinstance(result, dict) or report.get("legacy"):
        return []
    sources = report_scoped_sources(result, sources)
    leads = _candidate_leads(result, sources)
    candidates = result.get("candidates", [])
    if not isinstance(candidates, list) or len(candidates) > 100:
        return []
    targets = []
    # The presentation renderer has already rebound each numeric row to its
    # exact public provenance. Never consume unrendered caller-supplied fields.
    tables = result.get("report_tables", {})
    rows = tables.get("technical", {}).get("rows", [])
    if tables.get("schema") == "ranking-tables-v1":
        for row in rows:
            matches = [
                candidate
                for candidate in candidates
                if candidate.get("material_id") == row.get("material_id")
                and candidate.get("formula") == row.get("source_formula")
            ]
            if len(matches) != 1 or formula_key(row.get("source_formula")) is None:
                continue
            candidate = matches[0]
            targets.append(
                {
                    "kind": "material",
                    "id": row["material_id"],
                    "formula": display_formula(candidate["formula"]),
                    "candidate": candidate,
                }
            )
    source_names = {
        (
            source.get("source_id"),
            source.get("record_id"),
            source.get("url"),
        ): source.get("source_name")
        for source in sources
    }
    for lead in leads:
        formula = lead["name"].translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
        components = component_formulas(formula)
        if formula_key(formula) is not None and not _literal_formula_hint(formula):
            continue
        if not components and formula_key(formula) is None:
            pair = re.fullmatch(r"(.+?) \(((?:[A-Z][a-z]?[0-9]*)+)\)", formula)
            formula = pair[2] if pair else ""
        for index, item in enumerate(components or [formula], 1):
            if formula_key(item) is None:
                continue
            targets.append(
                {
                    "kind": "lead",
                    "id": lead["id"],
                    "formula": display_formula(item),
                    "lead": lead,
                    "source_names": source_names,
                    **(
                        {"parent_formula": lead["name"], "component_index": index}
                        if components
                        else {}
                    ),
                }
            )
    return targets[:MAX_TARGETS]


def _label(target, receipt):
    if (
        not isinstance(receipt, dict)
        or formula_key(receipt.get("formula")) != formula_key(target["formula"])
        or safe_name(receipt.get("name")) is None
        or not isinstance(receipt.get("source_name"), str)
        or not 1 <= len(receipt["source_name"]) <= 120
        or source_instruction_reason(receipt["source_name"])
    ):
        return None
    url = receipt.get("url")
    if (
        not isinstance(url, str)
        or len(url) > 2048
        or not (
            re.fullmatch(
                r"https://pubchem\.ncbi\.nlm\.nih\.gov/compound/[1-9][0-9]{0,9}", url
            )
            or approved_citation_url(url)
        )
    ):
        return None
    return {
        "kind": target["kind"],
        "id": target["id"],
        "formula": target["formula"],
        "name": receipt["name"],
        "url": url,
        "source_name": receipt["source_name"],
        **(
            {
                "parent_formula": target["parent_formula"],
                "component_index": target["component_index"],
            }
            if "component_index" in target
            else {}
        ),
    }


def _offline(target):
    try:
        candidate = target.get("candidate")
        if candidate:
            provenance = candidate.get("provenance", {})
            raw = provenance.get("raw_fields")
            if not isinstance(raw, dict):
                return None
            ids = [raw.get(key) for key in ("system_id", "dataset_id", "subset_id")]
            if any(type(value) is not int or not 0 < value < 10**9 for value in ids):
                return None
            system, dataset, subset = ids
            if (
                candidate["material_id"]
                == f"hybrid3:{system}:dataset{dataset}:subset{subset}"
                and provenance.get("source_url")
                == f"https://materials.hybrid3.duke.edu/materials/dataset/{dataset}"
                and raw.get("formula") == candidate["formula"]
                and provenance.get("raw_fields_sha256")
                == hashlib.sha256(canonical(raw)).hexdigest()
            ):
                return _label(
                    target,
                    {
                        "formula": raw["formula"],
                        "name": raw.get("compound_name"),
                        "url": provenance["source_url"],
                        "source_name": "HybriD³",
                    },
                )
        lead = target.get("lead")
        if lead:
            from labcat.science.chemical_name_literature import extract_pairs

            matches = []
            for citation in lead["citations"]:
                for pair in extract_pairs(citation["quote"], target["formula"]):
                    label = _label(
                        target,
                        {
                            "formula": pair["formula"],
                            "name": pair["name"],
                            "url": citation["url"],
                            "source_name": target["source_names"].get(
                                (
                                    citation["source_id"],
                                    citation["record_id"],
                                    citation["url"],
                                )
                            ),
                        },
                    )
                    if label:
                        matches.append(label)
            if len({item["name"].casefold() for item in matches}) == 1:
                return matches[0]
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        pass  # Optional names cannot make a valid scientific report unreadable.
    return None


def offline_names(report):
    """Use only validated report-bound source metadata; no network or
    mutations."""
    try:
        return [name for target in _targets(report) if (name := _offline(target))]
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return []


class ChemicalNameResolver:
    """Small, process-local public receipt cache; no saved research is
    rewritten."""

    def __init__(self):
        self._cache = OrderedDict()
        self._lock = threading.RLock()

    def _get(self, key):
        with self._lock:
            item = self._cache.get(key)
            if item is None:
                return False, None
            expires, receipt = item
            if expires <= time.monotonic():
                del self._cache[key]
                return False, None
            self._cache.move_to_end(key)
            return True, deepcopy(receipt)

    def _save(self, key, receipt):
        ttl = POSITIVE_TTL if receipt else NEGATIVE_TTL
        with self._lock:
            self._cache[key] = (time.monotonic() + ttl, deepcopy(receipt))
            self._cache.move_to_end(key)
            while len(self._cache) > MAX_CACHE:
                self._cache.popitem(last=False)

    def _resolve(self, target, deadline, allow_literature, allow_openalex):
        """One independent formula lookup with a bounded fallback
        budget."""
        formula = target["formula"]
        target_deadline = min(deadline, time.monotonic() + 6)
        receipt = lookup_pubchem_exact(formula, target_deadline)
        if receipt is None or ";" in receipt["name"]:
            from labcat.science import chemical_name_literature

            lookups = []
            if allow_literature:
                lookups.append(chemical_name_literature.lookup_formula)
            if allow_openalex:
                lookups.append(chemical_name_literature.lookup_openalex_formula)
            for operation in lookups:
                if time.monotonic() >= target_deadline:
                    break
                try:
                    written = operation(
                        formula, min(target_deadline, time.monotonic() + 3)
                    )
                except (
                    PublicSourceError,
                    ValueError,
                    TypeError,
                    KeyError,
                    AttributeError,
                    OverflowError,
                    RecursionError,
                ):
                    written = None
                if written is not None and _label(target, written):
                    receipt = written
                    break
        if receipt is None and time.monotonic() < target_deadline:
            receipt = lookup_pubchem(
                formula, min(target_deadline, time.monotonic() + 2)
            )
        if receipt is not None and _label(target, receipt) is None:
            receipt = None
        return receipt

    def names(
        self, report, *, lookup=False, allow_literature=True, allow_openalex=False
    ):
        try:
            targets = _targets(report)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            return []
        deadline = time.monotonic() + MAX_SECONDS
        acquired = lookup and _NETWORK_SLOTS.acquire(blocking=False)
        found, pending = {}, OrderedDict()
        try:
            for index, target in enumerate(targets):
                offline = _offline(target)
                if offline:
                    found[index] = offline
                    continue
                formula = target["formula"]
                # Selection policy is part of the cache key; disabled adapters
                # cannot inherit a previous enabled lookup.
                key = (formula_key(formula), allow_literature, allow_openalex)
                hit, receipt = self._get(key)
                if hit:
                    if receipt is not None and (label := _label(target, receipt)):
                        found[index] = label
                elif acquired and lookup_eligible(formula):
                    if key in pending:
                        pending[key][1].append((index, target))
                    elif len(pending) < MAX_LOOKUPS:
                        pending[key] = (target, [(index, target)])
            # A slow optional source must not consume the entire report budget
            # before later candidates or component names are attempted. Requests
            # still share the 12-second deadline, 12-formula cap and global gate.
            if pending:
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = {
                        key: pool.submit(
                            self._resolve,
                            target,
                            deadline,
                            allow_literature,
                            allow_openalex,
                        )
                        for key, (target, _) in pending.items()
                    }
                    for key, future in futures.items():
                        receipt = future.result()
                        self._save(key, receipt)
                        for index, target in pending[key][1]:
                            if receipt is not None and (
                                label := _label(target, receipt)
                            ):
                                found[index] = label
            return [found[index] for index in sorted(found)]
        finally:
            if acquired:
                _NETWORK_SLOTS.release()
