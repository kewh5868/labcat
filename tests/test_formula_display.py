"""Formula presentation is deterministic and cannot modify source
quantities."""

from itertools import permutations

import pytest

from labcat.science.formula_display import display_formula, flat_formula_tokens


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("O2Si", "SiO2"),
        ("ClNa", "NaCl"),
        ("O3TiBa", "BaTiO3"),
        ("FeLiO4P", "LiFePO4"),
        ("O3Al2", "Al2O3"),
        ("O2Hf", "HfO2"),
        ("AsGa", "GaAs"),
        ("NZr", "ZrN"),
        ("C4Si", "SiC4"),
        ("CO3Ca", "CaCO3"),
        ("O4SNa2", "Na2SO4"),
        ("O7Zr2La2", "La2Zr2O7"),
        ("O2U", "UO2"),
        ("AuCu", "AuCu"),
        ("CuAu", "AuCu"),
        ("H3Al", "AlH3"),
        ("ClH", "HCl"),
        ("H3N", "NH3"),
        ("O2H2", "H2O2"),
        ("O1Si1", "Si1O1"),
        ("O12Fe8", "Fe8O12"),
        ("SiO2", "SiO2"),
        ("C60", "C60"),
        ("Fe", "Fe"),
    ],
)
def test_inorganic_display_convention(source, expected):
    assert display_formula(source) == expected
    assert display_formula(expected) == expected


@pytest.mark.parametrize(
    "source",
    [
        "",
        "silica",
        "O2Xx",
        "O2Rf",
        "OgF2",
        "UuoF2",
        "O2Si0",
        "O2Si01",
        "O2Si1.0",
        "Ba0.5Sr0.5TiO3",
        "Fe1-xO",
        "ABO3",
        "MxOy",
        "Ca(OH)2",
        "[Fe(CN)6]4-",
        "Fe3+",
        "SO4^2-",
        "O₂Si",
        "¹³CO2",
        "D2O",
        "CuSO4·5H2O",
        "CuSO4.5H2O",
        "CuSO4*5H2O",
        "(C2H4)n",
        "CH3CH2OH",
        "CCl3COOH",
        "NH4NO3",
        "FeOFe2O3",
        "O2 Si",
        " O2Si",
        "O2Si ",
        "O2Si\n",
        "alpha-SiO2",
        "SiO2(s)",
        "2SiO2",
        "Si/O2",
        "<SiO2>",
        "SiO2<script>",
        "https://example.org/O2Si",
        "nomad:O2Si",
        "O2Si" * 50,
    ],
)
def test_ambiguous_unsupported_or_nonformula_notation_is_preserved(source):
    assert flat_formula_tokens(source) is None
    assert display_formula(source) == source


@pytest.mark.parametrize(
    "source", ["C2H6O", "H6C2O", "C6H12O6", "NaOH", "HNO3", "O4SH2", "HOCl", "N2H5Cl"]
)
def test_flat_condensed_or_acid_notation_allows_typography_but_no_reordering(source):
    assert flat_formula_tokens(source) is not None
    assert display_formula(source) == source


def test_token_api_preserves_explicit_counts_and_order_for_typography():
    assert flat_formula_tokens("O12Fe8Li1P") == (
        ("O", "12"),
        ("Fe", "8"),
        ("Li", "1"),
        ("P", ""),
    )


def test_permutations_conserve_exact_stoichiometric_tokens():
    # Algorithm invariant, independent of a named material or retrieved result.
    tokens = ("O12", "Fe8", "Li1", "P3")
    before = {("O", "12"), ("Fe", "8"), ("Li", "1"), ("P", "3")}
    rendered = set()
    for permuted in permutations(tokens):
        result = display_formula("".join(permuted))
        assert set(flat_formula_tokens(result)) == before
        assert display_formula(result) == result
        rendered.add(result)
    assert rendered == {"Li1Fe8P3O12"}


def test_large_integer_tokens_are_never_parsed_or_rounded():
    count = "1234567890" * 7
    assert display_formula(f"O{count}Si") == f"SiO{count}"
