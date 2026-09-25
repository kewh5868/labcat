"""Public name resolution for reference lookup, never phase or property
evidence.

PubChem's exact-name record must return one CID and independently
include the requested name among its synonyms. We keep a bounded source
receipt; neither a model's chemical memory nor a name-to-formula table
can assign composition.
"""

import hashlib
import math
import re
import time
import unicodedata
from datetime import UTC, datetime
from urllib.parse import quote

from labcat.public_sources import PublicSourceError, _fetch, _json
from labcat.science.nomad import _composition
from labcat.untrusted_text import source_instruction_reason

_FIELDS = {
    "source_id",
    "record_id",
    "url",
    "query_name",
    "matched_name",
    "formula",
    "retrieved_at",
    "property_url",
    "synonyms_url",
    "property_sha256",
    "synonyms_sha256",
    "scope",
    "phase_match",
}
_UNSUPPORTED_NAMES = re.compile(
    r"\b(?:co)?poly\s*\(|"
    r"\b(?:composites?|blends?|mixtures?|polymers?|copolymers?|"
    r"core[- ]?shell|quantum[- ]?dots?|nanocrystals?|nanoparticles?|"
    r"nanorods?|nanowires?|nanosheets?|nanotubes?|clusters?)\b",
    re.I,
)


def _normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def eligible_name(name):
    """Accept a bounded compound-name hint without assigning any
    chemistry."""
    if (
        not isinstance(name, str)
        or not 3 <= len(name) <= 120
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 (),.'-]*", name)
        or source_instruction_reason(name)
        or not re.search(r"[a-z]{3}", name)
        or _UNSUPPORTED_NAMES.search(name)
    ):
        return False
    for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", name):
        # Oxidation-state numerals may occur in compound names. Formula-like
        # fragments require the separate literal-formula path; stripping their
        # morphology or incomplete count would change the user's identity hint.
        if re.fullmatch(r"[IVXLCDM]+", token):
            continue
        try:
            elements = _composition(token)
        except (ValueError, TypeError, OverflowError):
            continue
        if len(elements) > 1 or any(char.isdigit() for char in token):
            return False
    return True


def _valid_formula(formula):
    return (
        isinstance(formula, str)
        and len(formula) <= 120
        and re.fullmatch(r"(?:[A-Z][a-z]?[0-9]*)+", formula) is not None
        and len(_composition(formula)) >= 2
    )


def validate_resolution(receipt, name):
    """Revalidate a saved receipt's identity scope; return its formula
    or None.

    Response hashes are provenance checks, not proof of phase or
    property facts. The caller also verifies the containing cache
    against its saved integrity hash.
    """
    if (
        not eligible_name(name)
        or not isinstance(receipt, dict)
        or set(receipt) != _FIELDS
        or any(not isinstance(value, str) for value in receipt.values())
    ):
        return None
    try:
        cid = receipt["record_id"]
        matched = receipt["matched_name"]
        if (
            receipt["source_id"] != "pubchem"
            or re.fullmatch(r"[1-9][0-9]{0,9}", cid) is None
            or receipt["query_name"] != name
            or not 1 <= len(matched) <= 120
            or source_instruction_reason(matched)
            or _normalized(matched) != _normalized(name)
            or not _valid_formula(receipt["formula"])
            or receipt["scope"] != "composition_reference_only"
            or receipt["phase_match"] != "unverified"
            or receipt["url"] != f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
            or receipt["property_url"]
            != "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
            + quote(name, safe="")
            + "/property/MolecularFormula/JSON?name_type=complete"
            or receipt["synonyms_url"]
            != (
                "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/"
                f"{cid}/synonyms/JSON"
            )
            or any(
                re.fullmatch(r"[0-9a-f]{64}", receipt[field]) is None
                for field in ("property_sha256", "synonyms_sha256")
            )
            or len(receipt["retrieved_at"]) > 50
        ):
            return None
        retrieved = datetime.fromisoformat(receipt["retrieved_at"])
        if retrieved.tzinfo is None or retrieved.utcoffset().total_seconds() != 0:
            return None
        return receipt["formula"]
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
        return None


def lookup_name(name, deadline):
    """Return an identity receipt, or None; all failures leave the
    report intact."""
    now = time.monotonic()
    if not eligible_name(name) or type(deadline) not in {int, float}:
        return None
    try:
        if not math.isfinite(deadline) or deadline <= now:
            return None
    except OverflowError:
        return None
    deadline = min(deadline, now + 5)
    try:
        raw, url = _fetch("pubchem_identity", {"name": name}, deadline)
        if len(raw) > 65536:
            return None
        rows = _json(raw).get("PropertyTable", {}).get("Properties")
        if not isinstance(rows, list) or len(rows) != 1:
            return None
        row = rows[0]
        cid, formula = row.get("CID"), row.get("MolecularFormula")
        if type(cid) is not int or not 0 < cid < 10**10:
            return None
        # Mixtures, charges, isotopes and incomplete compositions remain unsupported.
        if not _valid_formula(formula) or time.monotonic() >= deadline:
            return None
        aliases_raw, aliases_url = _fetch("pubchem_synonyms", {"cid": cid}, deadline)
        if len(aliases_raw) > 262144:
            return None
        info = _json(aliases_raw).get("InformationList", {}).get("Information")
        if (
            not isinstance(info, list)
            or len(info) != 1
            or type(info[0].get("CID")) is not int
            or info[0]["CID"] != cid
        ):
            return None
        aliases = info[0].get("Synonym")
        if not isinstance(aliases, list) or len(aliases) > 5000:
            return None
        matched = next(
            (
                alias
                for alias in aliases
                if isinstance(alias, str)
                and len(alias) <= 120
                and not source_instruction_reason(alias)
                and _normalized(alias) == _normalized(name)
            ),
            None,
        )
        if matched is None:
            return None
        receipt = {
            "source_id": "pubchem",
            "record_id": str(cid),
            "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
            "query_name": name,
            "matched_name": matched,
            "formula": formula,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "property_url": url,
            "synonyms_url": aliases_url,
            "property_sha256": hashlib.sha256(raw).hexdigest(),
            "synonyms_sha256": hashlib.sha256(aliases_raw).hexdigest(),
            "scope": "composition_reference_only",
            "phase_match": "unverified",
        }
        return receipt if validate_resolution(receipt, name) is not None else None
    except (
        PublicSourceError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OverflowError,
        RecursionError,
    ):
        return None
