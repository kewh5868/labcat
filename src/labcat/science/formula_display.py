"""Conservative formula labels; never a composition parser or evidence
source.

The fixed order follows IUPAC's 2005 Red Book Table VI in the formula
direction (IR-2.15.3.1). The supported subset is elements 1–103, cross-
checked against ``Element.iupac_ordering`` in pymatgen v2025.6.14. No
runtime dependency, numerical electronegativity estimate, formula
reduction, or candidate-specific alias is used.

See ``docs/formula-display.md`` for scope, primary references, and
limitations.
"""

from __future__ import annotations

import re

FORMULA_DISPLAY_VERSION = "iupac-2005-flat-v1"

# Table VI, reversed arrow direction for formula display. Deliberately limit the
# table to the independently checked 1–103 subset; unsupported symbols keep their
# source spelling rather than receiving an invented or alphabetical fallback.
_ELEMENT_ORDER = (
    "Rn Xe Kr Ar Ne He "
    "Fr Cs Rb K Na Li Ra Ba Sr Ca Mg Be "
    "Lr No Md Fm Es Cf Bk Cm Am Pu Np U Pa Th Ac "
    "Lu Yb Tm Er Ho Dy Tb Gd Eu Sm Pm Nd Pr Ce La Y Sc "
    "Hf Zr Ti Ta Nb V W Mo Cr Re Tc Mn Os Ru Fe Ir Rh Co "
    "Pt Pd Ni Au Ag Cu Hg Cd Zn Tl In Ga Al B Pb Sn Ge Si C "
    "Bi Sb As P N H Po Te Se S O At I Br Cl F"
).split()
_ELEMENT_RANK = {symbol: rank for rank, symbol in enumerate(_ELEMENT_ORDER)}
_TOKEN = re.compile(r"([A-Z][a-z]?)([1-9][0-9]*)?")
_FLAT_FORMULA = re.compile(r"(?:[A-Z][a-z]?(?:[1-9][0-9]*)?)+")
_MAX_FORMULA_LENGTH = 160


def flat_formula_tokens(value: str) -> tuple[tuple[str, str], ...] | None:
    """Return conservative display tokens, or ``None`` to retain source
    notation.

    Each tuple contains an element symbol and its exact integer count
    text. An empty count is implicit one. This validator establishes no
    chemical validity, phase, bonding, valence, measurement, or material
    identity. It is suitable for typography only when the caller already
    knows the string is a formula field.

    Repeated symbols may encode bonding or separate sites and are
    rejected, as are decimal counts, groups, charges, isotopes, hydrates
    and variables. Carbon plus hydrogen and ternary hydrogen formulas
    allow count typography here; their potentially meaningful source
    ordering is preserved by display_formula.
    """
    if (
        not value
        or len(value) > _MAX_FORMULA_LENGTH
        or _FLAT_FORMULA.fullmatch(value) is None
    ):
        return None

    tokens = tuple((match[0], match[1]) for match in _TOKEN.findall(value))
    symbols = {symbol for symbol, _ in tokens}
    if len(symbols) != len(tokens) or not symbols.issubset(_ELEMENT_RANK):
        return None
    return tokens


def display_formula(value: str) -> str:
    """Order eligible formula tokens without changing or reducing any
    count.

    Original source fields, lookup identities and structure bytes must
    remain unchanged. Unsupported or ambiguous notation is returned
    byte-for-byte.
    """
    tokens = flat_formula_tokens(value)
    if tokens is None:
        return value
    symbols = {symbol for symbol, _ in tokens}
    if "H" in symbols and ("C" in symbols or len(symbols) > 2):
        return value
    return "".join(
        symbol + count
        for symbol, count in sorted(tokens, key=lambda token: _ELEMENT_RANK[token[0]])
    )
