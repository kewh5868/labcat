"""Optional public composition labels, kept separate from scientific
evidence.

Only report-bound candidate identities can supply lookup hints. A
returned name labels a composition; it never verifies phase, properties
or ranking suitability.
"""

from labcat.science.formula_display import flat_formula_tokens


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


def lookup_eligible(formula):
    counts = formula_key(formula)
    if counts is None:
        return False
    # A formula alone cannot select an organic isomer. The deliberately narrow
    # initial adapter omits carbon/hydrogen compositions, mixtures and morphology.
    return not {"C", "H"}.issubset(dict(counts))
