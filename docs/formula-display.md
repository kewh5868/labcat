# Formula labels

Report tables and structure labels may reorder a simple inorganic composition
for readability. This changes presentation only: source formulas, evidence,
material identifiers, stoichiometry, ranking and structure-file bytes retain
their original values. The version is `iupac-2005-flat-v1`.

The fixed sequence uses the formula direction of Table VI in IUPAC's _Nomenclature
of Inorganic Chemistry (2005)_. IR-2.15.3.1 defines the direction; IR-1.6.3 notes
that several ordering principles can be acceptable for compounds with more than
two elements. We choose a consistent display convention, without claiming a
unique chemically preferred formula or deriving bonding/oxidation states.
[IUPAC Red Book, sections IR-1.6.3 and IR-2.15.3.1, Table VI](https://iupac.org/wp-content/uploads/2016/07/Red_Book_2005.pdf)

The compact element sequence in `science/formula_display.py` supports elements
1–103. It was cross-checked against `Element.iupac_ordering` in pymatgen
v2025.6.14; pymatgen is not a runtime dependency. Unsupported symbols retain
their original notation.
[pymatgen ordering documentation](https://pymatgen.org/pymatgen.core.html#pymatgen.core.periodic_table.ElementBase.iupac_ordering),
[versioned periodic-table data](https://github.com/materialsproject/pymatgen/blob/v2025.6.14/src/pymatgen/core/periodic_table.json.gz)

| Source composition label | Display label |
| ------------------------ | ------------- |
| O2Si                     | SiO2          |
| ClNa                     | NaCl          |
| O3TiBa                   | BaTiO3        |
| FeLiO4P                  | LiFePO4       |

These are formatting examples, not experimental results or evidence of a phase.
Only complete flat formulas with unique supported element symbols and positive
integer counts are eligible. Exact count text is preserved, including explicit
ones; numbers are never rounded, combined or reduced.

Parentheses, charges, hydrates, decimal counts, variables, isotopes, repeated
element tokens, carbon-plus-hydrogen formulas, and other hydrogen-containing
formulas with three or more elements are preserved. These can convey grouping,
bonding, acid/hydroxide notation or other meaning a composition string cannot
resolve. Names, URLs and record identifiers must never be sent to this helper
as if they were formula fields. The shared `flat_formula_tokens` validator also
supports count subscripts in known formula labels; typography is not validation
of chemical identity.
