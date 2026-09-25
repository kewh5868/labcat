"""Literal public abstract name/formula pairs, never phase or property
evidence."""

import hashlib
import math
import re
import time
import unicodedata
from datetime import UTC, datetime

from labcat.chemical_names import formula_key, lookup_eligible, safe_name
from labcat.public_sources import (
    PublicSourceError,
    _abstract_text,
    _fetch,
    _json,
    _text,
)

# Lexical admission only: these words never map a formula to a generated name.
_ELEMENTS = frozenset(
    "hydrogen helium lithium beryllium boron carbon nitrogen oxygen fluorine neon "
    "sodium magnesium aluminium aluminum silicon phosphorus sulfur sulphur chlorine "
    "argon potassium calcium scandium titanium vanadium chromium manganese iron "
    "cobalt nickel copper zinc gallium germanium arsenic selenium bromine krypton "
    "rubidium strontium yttrium zirconium niobium molybdenum technetium ruthenium "
    "rhodium palladium silver cadmium indium tin antimony tellurium iodine xenon "
    "caesium cesium barium lanthanum cerium praseodymium neodymium promethium "
    "samarium europium gadolinium terbium dysprosium holmium erbium thulium "
    "ytterbium lutetium hafnium tantalum tungsten rhenium osmium iridium platinum "
    "gold mercury thallium lead bismuth polonium astatine radon francium radium "
    "actinium thorium protactinium uranium neptunium plutonium americium curium "
    "berkelium californium einsteinium fermium mendelevium nobelium lawrencium".split()
)
_ANION = re.compile(
    r"(?:(?:mono|di|tri|tetra|penta|hexa|hepta|octa|ortho|meta|pyro|thio|oxy)-?)*"
    r"(?:oxide|sulfide|sulphide|nitride|phosphide|carbide|boride|silicide|selenide|"
    r"telluride|fluoride|chloride|bromide|iodide|hydride|borate|phosphate|sulfate|"
    r"sulphate|nitrate|carbonate|silicate|aluminate|titanate|zirconate|niobate|"
    r"tantalate|molybdate|tungstate|ferrite|antimonate|vanadate)"
)
_WORD = r"[A-Za-z][A-Za-z-]*(?:\([IVX]+\))?"
_FORMULA = r"(?:[A-Z][a-z]?[ ]*[0-9]*[ ]*){1,12}"


def _chemical_word(word):
    word = re.sub(r"\([IVX]+\)$", "", word).casefold()
    return word in _ELEMENTS or _ANION.fullmatch(word) is not None


def _written_name(value):
    words = value.strip().split()
    if not 2 <= len(words) <= 6 or not all(_chemical_word(word) for word in words):
        return None
    if not any(_ANION.fullmatch(word.casefold()) for word in words):
        return None
    return safe_name(" ".join(words))


def extract_pairs(text, formula):
    """Extract explicit adjacent pairs without deriving names from
    chemistry.

    Supported prose is name (formula), formula (name), or formula,
    name,. Arbitrary nearby titles, application labels, reduced ratios,
    hydrates and mixtures are intentionally insufficient for this
    display-only identity.
    """
    if not lookup_eligible(formula):
        return []
    plain = _abstract_text(text)
    if not plain:
        return []
    plain = unicodedata.normalize("NFKC", plain)
    key = formula_key(formula)
    matches = []
    patterns = (
        rf"(?P<name>{_WORD}(?:\s+{_WORD}){{1,5}})\s*\((?P<formula>{_FORMULA})\)",
        rf"(?<![\w./+\-])(?P<formula>{_FORMULA})\s*\("
        rf"(?P<name>{_WORD}(?:\s+{_WORD}){{1,5}})\)",
        rf"(?<![\w./+\-])(?P<formula>{_FORMULA}),\s*"
        rf"(?P<name>{_WORD}(?:\s+{_WORD}){{1,5}}),",
    )
    for index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, plain):
            matched_formula = match["formula"].replace(" ", "")
            if formula_key(matched_formula) != key:
                continue
            if re.match(r"\s*(?:[0-9·/+@]|\.[0-9]|-[A-Za-z0-9])", plain[match.end() :]):
                continue
            candidate = match["name"]
            if index == 0:
                # The greedy left phrase may include ordinary prose. Keep only
                # its maximal chemical suffix, with no morphology stripping.
                words = candidate.split()
                if re.search(
                    r"\b(?:doped|coated|modified|hydrated|mixture|composite)\b",
                    candidate,
                    re.I,
                ):
                    continue
                while words and not all(_chemical_word(word) for word in words):
                    words.pop(0)
                candidate = " ".join(words)
                prefix = plain[max(0, match.start("name") - 35) : match.start("name")]
                if re.search(
                    r"(?:doped|coated|modified|hydrated|mixture|composite)[ -]*$",
                    prefix,
                    re.I,
                ):
                    continue
            name = _written_name(candidate)
            if name:
                matches.append(
                    {"name": name, "formula": matched_formula, "quote": match[0]}
                )
    unique = {row["name"].casefold(): row for row in matches}
    return list(unique.values())


def _formula_query(formula):
    # Search hints only: words here cannot become names or evidence. Requiring
    # an explicit adjacent name/formula pair below is still mandatory. This
    # avoids short formulas such as CdS being swamped by unrelated abbreviations.
    terms = {
        "O": "oxide",
        "S": "sulfide",
        "Se": "selenide",
        "Te": "telluride",
        "N": "nitride",
        "P": "phosphide",
        "As": "arsenide",
        "F": "fluoride",
        "Cl": "chloride",
        "Br": "bromide",
        "I": "iodide",
    }
    composition = formula_key(formula)
    query = f"TITLE_ABS:{formula}"
    if composition and len(composition) == 2:
        hints = [terms[element] for element, _ in composition if element in terms]
        if hints:
            query += " AND (" + " OR ".join(f"TITLE_ABS:{hint}" for hint in hints) + ")"
    return query


def lookup_formula(formula: str, deadline: float) -> dict | None:
    """Read at most five public abstracts through the fixed Europe PMC
    adapter."""
    if (
        not lookup_eligible(formula)
        or type(deadline) not in {int, float}
        or not math.isfinite(deadline)
        or deadline <= time.monotonic()
    ):
        return None
    deadline = min(deadline, time.monotonic() + 5)
    try:
        raw, url = _fetch(
            "europe_pmc",
            {
                "query": _formula_query(formula),
                "format": "json",
                "pageSize": 5,
                "resultType": "core",
            },
            deadline,
        )
        rows = _json(raw).get("resultList", {}).get("result")
        if not isinstance(rows, list) or len(rows) > 5 or time.monotonic() >= deadline:
            return None
        receipts = []
        for row in rows:
            if not isinstance(row, dict) or row.get("source") not in {"MED", "PMC"}:
                continue
            identity = row.get("id")
            pattern = (
                r"[1-9][0-9]{0,11}"
                if row["source"] == "MED"
                else r"PMC[1-9][0-9]{0,11}"
            )
            title = _text(row.get("title"), 1000)
            if (
                not isinstance(identity, str)
                or not re.fullmatch(pattern, identity)
                or not title
            ):
                continue
            pairs = extract_pairs(row.get("abstractText"), formula)
            if len(pairs) != 1:
                continue
            pair = pairs[0]
            receipts.append(
                {
                    "formula": pair["formula"],
                    "name": pair["name"],
                    "url": f"https://europepmc.org/article/{row['source']}/{identity}",
                    "source_name": "Europe PMC",
                    "provenance": {
                        "source_id": "europe_pmc",
                        "record_id": identity,
                        "request_url": url,
                        "response_sha256": hashlib.sha256(raw).hexdigest(),
                        "title": title,
                        "quote": pair["quote"],
                        "retrieved_at": datetime.now(UTC).isoformat(),
                        "scope": "composition_name_only",
                        "phase_match": "unverified",
                        "full_text_read": False,
                    },
                }
            )
        if len({item["name"].casefold() for item in receipts}) == 1:
            return receipts[0]
    except (
        PublicSourceError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OverflowError,
    ):
        return None
    return None


def lookup_openalex_formula(formula: str, deadline: float) -> dict | None:
    """Use a bounded public indexed abstract when that source is
    selected."""
    if (
        not lookup_eligible(formula)
        or type(deadline) not in {int, float}
        or not math.isfinite(deadline)
        or deadline <= time.monotonic()
    ):
        return None
    from labcat.extended_discovery import _abstract

    try:
        raw, url = _fetch(
            "openalex",
            {
                "search": formula,
                "per-page": 5,
                "select": "id,title,abstract_inverted_index,is_retracted,type",
            },
            min(deadline, time.monotonic() + 4),
        )
        rows = _json(raw).get("results")
        if not isinstance(rows, list) or len(rows) > 5 or time.monotonic() >= deadline:
            return None
        receipts = []
        for row in rows:
            if not isinstance(row, dict) or row.get("is_retracted") is not False:
                continue
            identity = row.get("id")
            title = _text(row.get("title"), 1000)
            if (
                not isinstance(identity, str)
                or not re.fullmatch(r"https://openalex.org/W[1-9][0-9]{0,14}", identity)
                or not title
                or row.get("type") not in {"article", "review"}
            ):
                continue
            pairs = extract_pairs(
                _abstract(row.get("abstract_inverted_index")), formula
            )
            if len(pairs) != 1:
                continue
            pair = pairs[0]
            receipts.append(
                {
                    "formula": pair["formula"],
                    "name": pair["name"],
                    "url": identity,
                    "source_name": "OpenAlex",
                    "provenance": {
                        "source_id": "openalex",
                        "record_id": identity.rsplit("/", 1)[-1],
                        "request_url": url,
                        "response_sha256": hashlib.sha256(raw).hexdigest(),
                        "title": title,
                        "quote": pair["quote"],
                        "retrieved_at": datetime.now(UTC).isoformat(),
                        "scope": "composition_name_only",
                        "phase_match": "unverified",
                        "full_text_read": False,
                    },
                }
            )
        if len({item["name"].casefold() for item in receipts}) == 1:
            return receipts[0]
    except (
        PublicSourceError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OverflowError,
    ):
        return None
    return None
