"""Source-neutral property preferences; weights are never material
evidence.

Repository field names below are adapter mapping references, not a source policy.
Definitions and reference mappings:
https://docs.nomad-lab.eu/
https://materialsproject.github.io/emmet/_reference/emmet.core.summary.SummaryDoc.html
https://docs.materialsproject.org/downloading-data/using-the-api/querying-data
https://docs.materialsproject.org/methodology/materials-methodology/elasticity
https://docs.materialsproject.org/methodology/materials-methodology/dielectricity
https://docs.materialsproject.org/methodology/materials-methodology/electronic-structure
"""

import re
from copy import deepcopy

SUPPORTED_ATTRIBUTES = frozenset(
    {
        "stability",
        "band_gap",
        "element_screen",
        "simplicity",
        "evidence_quality",
        "dielectric_total",
        "dielectric_electronic",
        "nsites",
        "density",
        "bulk_modulus",
        "shear_modulus",
        "metallicity",
        "direct_gap",
    }
)


_ATTRIBUTES = (
    (
        "stability",
        "Thermodynamic stability",
        "Stability & evidence",
        "energy_above_hull",
        "Energy above the lowest-energy competing phase mixture (eV/atom). "
        "Lower values score higher; this does not establish stability under "
        "your processing conditions.",
    ),
    (
        "ambient_phase_stability",
        "Room-temperature phase stability",
        "Stability & evidence",
        None,
        "Whether the identified phase persists at room temperature under stated "
        "conditions. Current adapters do not verify this evidence; unknown is "
        "not stable. A zero hull energy is not a substitute.",
    ),
    (
        "operational_stability",
        "Operational stability",
        "Stability & evidence",
        None,
        "Retention of the relevant phase and properties during operation, with "
        "temperature, environment, illumination or load, and duration specified. "
        "Current adapters do not verify this evidence; unknown is not stable.",
    ),
    (
        "formation_energy",
        "Formation energy",
        "Stability & evidence",
        "formation_energy_per_atom",
        "Energy change relative to the constituent elements (eV/atom). "
        "Useful for comparing formation energetics, but a negative value alone "
        "does not establish stability against other compounds.",
    ),
    (
        "evidence_quality",
        "Supported-field completeness",
        "Stability & evidence",
        None,
        "Fraction of seven supported property fields present in each retrieved "
        "record. More populated fields score higher. This uses a fixed field "
        "set, independent of selected ranking weights; it does not measure "
        "source credibility, measurement accuracy or scientific confidence.",
    ),
    (
        "element_screen",
        "Element screening",
        "Composition & structure",
        None,
        "Checks the source-reported composition against a conservative "
        "element exclusion list. Any positive importance excludes matches; "
        "passing the screen does not establish compound safety.",
    ),
    (
        "simplicity",
        "Composition simplicity",
        "Composition & structure",
        "nelements",
        "Number of distinct elements in the reported composition. Fewer "
        "elements score higher; this does not measure synthesis difficulty.",
    ),
    (
        "nsites",
        "Cell site count",
        "Composition & structure",
        "nsites",
        "Number of atomic sites in the reported unit cell. Fewer sites score "
        "higher; cell conventions and supercells can change this count.",
    ),
    (
        "density",
        "Density",
        "Composition & structure",
        "density",
        "Mass per unit volume (g/cm³). Lower reported density scores higher "
        "in this ranking; phase, temperature and porosity affect comparisons.",
    ),
    (
        "volume",
        "Cell volume",
        "Composition & structure",
        "volume",
        "Volume of the reported unit cell (Å³). Compare compatible cell "
        "conventions and compositions; a larger cell need not mean more porosity.",
    ),
    (
        "band_gap",
        "Band gap",
        "Electronic & optoelectronic",
        "band_gap",
        "Energy separation between valence and conduction bands (eV). "
        "Scores either a wider gap or closeness to an explicit target gap. "
        "Target and tolerance are ranking preferences, not measured values; "
        "computational method and optical versus fundamental gap must be "
        "distinguished.",
    ),
    (
        "direct_gap",
        "Direct gap character",
        "Electronic & optoelectronic",
        "is_gap_direct",
        "Whether the band edges occur at the same crystal momentum. "
        "A reported direct gap scores higher; it does not by itself "
        "establish efficient light emission or absorption.",
    ),
    (
        "solution_processability",
        "Solution processability",
        "Processing & operating conditions",
        None,
        "Preference for preparation from a solution. Public evidence must identify "
        "the composition, solvent, processing conditions and resulting material. "
        "This qualitative criterion is retained for source review but is not "
        "numerically scored by the current adapters.",
    ),
    (
        "metallicity",
        "Metallicity",
        "Electronic & optoelectronic",
        "is_metal",
        "Whether the source classifies a material as metallic. Reported "
        "metals score higher when selected; this is not a conductivity measurement.",
    ),
    (
        "conduction_band_edge",
        "Conduction band edge",
        "Electronic & optoelectronic",
        "cbm",
        "Energy of the conduction-band minimum (eV). A shared energy "
        "reference is required before comparing band alignment across sources.",
    ),
    (
        "valence_band_edge",
        "Valence band edge",
        "Electronic & optoelectronic",
        "vbm",
        "Energy of the valence-band maximum (eV). A shared energy reference "
        "is required before comparing band alignment across sources.",
    ),
    (
        "fermi_energy",
        "Fermi energy",
        "Electronic & optoelectronic",
        "efermi",
        "Electronic chemical potential reported by the source (eV). "
        "Interpret it with the energy reference, temperature and carrier conditions.",
    ),
    (
        "refractive_index",
        "Refractive index",
        "Electronic & optoelectronic",
        "n",
        "Optical phase index describing light propagation in a material. "
        "Wavelength, polarization and measurement or calculation method "
        "are needed for meaningful comparison.",
    ),
    (
        "dielectric_total",
        "Total dielectric response",
        "Dielectric & piezoelectric",
        "e_total",
        "Relative permittivity including electronic and ionic contributions. "
        "Larger reported scalars score higher; frequency, direction and "
        "dielectric loss remain separate considerations.",
    ),
    (
        "dielectric_electronic",
        "Electronic dielectric response",
        "Dielectric & piezoelectric",
        "e_electronic",
        "Relative permittivity from electronic polarization with ions held "
        "fixed. Larger reported scalars score higher; this is distinct from "
        "the total low-frequency response.",
    ),
    (
        "dielectric_ionic",
        "Ionic dielectric response",
        "Dielectric & piezoelectric",
        "e_ionic",
        "Contribution to relative permittivity from ionic displacements. "
        "Interpret it with crystal phase, direction and the source's frequency limit.",
    ),
    (
        "piezoelectric_response",
        "Maximum piezoelectric response",
        "Dielectric & piezoelectric",
        "e_ij_max",
        "Largest reported piezoelectric response under the source's tensor "
        "convention. Check direction, units and whether the source reports "
        "a stress or strain coefficient.",
    ),
    (
        "bulk_modulus",
        "Bulk modulus",
        "Mechanical",
        "bulk_modulus",
        "Resistance to uniform compression (GPa). Larger reported bulk "
        "moduli score higher; compare compatible phase, temperature and "
        "averaging conventions.",
    ),
    (
        "shear_modulus",
        "Shear modulus",
        "Mechanical",
        "shear_modulus",
        "Resistance to shape change under shear (GPa). Larger reported "
        "shear moduli score higher; stiffness is distinct from toughness or ductility.",
    ),
    (
        "elastic_anisotropy",
        "Elastic anisotropy",
        "Mechanical",
        "universal_anisotropy",
        "Variation of elastic stiffness with direction, summarized by the "
        "source's anisotropy index. Compare the same index definition and phase.",
    ),
    (
        "poisson_ratio",
        "Poisson ratio",
        "Mechanical",
        "homogeneous_poisson",
        "Negative ratio of transverse strain to axial strain under loading. "
        "Direction and averaging convention matter when comparing materials.",
    ),
    (
        "magnetization",
        "Total magnetization",
        "Magnetic",
        "total_magnetization",
        "Net magnetic moment of the reported cell or sample. Check units "
        "and normalization, including whether the value is per cell, atom or volume.",
    ),
    (
        "magnetic_ordering",
        "Magnetic ordering",
        "Magnetic",
        "ordering",
        "Arrangement of magnetic moments, such as ferro- or antiferromagnetic "
        "order. This is a categorical property that depends on phase and conditions.",
    ),
    (
        "magnetic_site_count",
        "Magnetic site count",
        "Magnetic",
        "num_magnetic_sites",
        "Number of sites classified as magnetic in the reported cell. "
        "The moment threshold and cell definition affect this count.",
    ),
    (
        "surface_energy",
        "Surface energy",
        "Surface",
        "weighted_surface_energy",
        "Energy cost per unit area of forming a surface. Facet, termination "
        "and reconstruction matter; a weighted average depends on the assumed shape.",
    ),
    (
        "work_function",
        "Work function",
        "Surface",
        "weighted_work_function",
        "Energy needed to remove an electron to vacuum (eV). Surface facet, "
        "termination and adsorbates affect the value and must accompany comparisons.",
    ),
)


EXPLORATORY_CLASSES = (
    (
        "polymers",
        "Polymers",
        ("density", "bulk_modulus", "shear_modulus", "dielectric_total"),
    ),
    (
        "perovskites",
        "Perovskites",
        ("stability", "band_gap", "dielectric_total", "piezoelectric_response"),
    ),
    (
        "perovskitoids",
        "Perovskitoids",
        ("stability", "band_gap", "dielectric_total", "refractive_index"),
    ),
    (
        "ceramic_oxides",
        "Ceramic Oxides",
        ("stability", "bulk_modulus", "shear_modulus", "dielectric_total"),
    ),
    (
        "metals_metal_alloys",
        "Metals & Metal Alloys",
        ("stability", "density", "bulk_modulus", "shear_modulus", "metallicity"),
    ),
    ("mofs", "MOFs", ("stability", "density", "volume", "surface_energy")),
    (
        "high_entropy_alloys",
        "High-Entropy Alloys",
        ("stability", "formation_energy", "density", "bulk_modulus", "shear_modulus"),
    ),
    (
        "semiconductor_nanocrystals",
        "Semiconductor Nanocrystals (Quantum Dots)",
        ("band_gap", "direct_gap", "refractive_index", "surface_energy"),
    ),
    (
        "organic_electronic_materials",
        "Organic Electronic Materials",
        ("band_gap", "direct_gap", "refractive_index", "solution_processability"),
    ),
    (
        "two_dimensional_materials",
        "Two-Dimensional Materials",
        ("band_gap", "direct_gap", "surface_energy", "shear_modulus"),
    ),
    (
        "polymer_matrix_composites",
        "Polymer Matrix Composites",
        ("density", "bulk_modulus", "shear_modulus", "elastic_anisotropy"),
    ),
    (
        "ceramic_matrix_composites",
        "Ceramic Matrix Composites",
        ("density", "bulk_modulus", "shear_modulus", "elastic_anisotropy"),
    ),
    (
        "biomaterials",
        "Biomaterials",
        ("density", "bulk_modulus", "shear_modulus", "surface_energy"),
    ),
    (
        "elastomers",
        "Elastomers",
        ("density", "shear_modulus", "poisson_ratio", "dielectric_total"),
    ),
    (
        "liquid_crystals",
        "Liquid Crystals",
        ("refractive_index", "dielectric_total", "dielectric_electronic", "density"),
    ),
    (
        "thermosets",
        "Thermosets",
        ("density", "bulk_modulus", "shear_modulus", "dielectric_total"),
    ),
    (
        "thermoplastics",
        "Thermoplastics",
        ("density", "bulk_modulus", "shear_modulus", "dielectric_total"),
    ),
)


def catalog() -> dict:
    attributes = []
    for identifier, label, category, field, description in _ATTRIBUTES:
        supported = identifier in SUPPORTED_ATTRIBUTES
        attributes.append(
            {
                "id": identifier,
                "label": label,
                "category": category,
                "description": description,
                "source_field": field,
                "supported": supported,
                "availability_note": (
                    "Validated source values can enter the property ranking. "
                    "Relevant cited passages can also inform the preliminary shortlist."
                    if supported
                    else "No numeric scoring rule is available. Relevant cited "
                    "passages can inform a qualitative shortlist assessment; "
                    "missing evidence remains unknown."
                ),
            }
        )
    return {
        "attributes": attributes,
        "material_classes": [
            {
                "id": "oxide_dielectrics",
                "label": "Oxide dielectrics",
                "scope": "Public discovery and connected property retrieval; "
                "ranking depends on verified property coverage.",
            },
            {
                "id": "structural_ceramics",
                "label": "Structural ceramics",
                "scope": "Public discovery for ceramics; quantitative ranking "
                "depends on available property records.",
            },
            {
                "id": "semiconductors",
                "label": "Semiconductors",
                "scope": "Public discovery for semiconductors; quantitative "
                "ranking depends on available property records.",
            },
            *(
                {
                    "id": identifier,
                    "label": label,
                    "scope": "Public discovery uses the research question. "
                    "Quantitative ranking requires supported public property "
                    "records; missing properties remain unknown.",
                }
                for identifier, label, _ in EXPLORATORY_CLASSES
            ),
            {
                "id": "custom",
                "label": "Custom class",
                "scope": "Custom preference label; public discovery uses the "
                "research question. A label does not establish material properties.",
            },
        ],
        "applications": [
            {
                "id": "thin_film_insulation",
                "label": "Thin-film insulation",
                "scope": "Screening, not process qualification",
            },
            {
                "id": "high_k_screening",
                "label": "High-k screening",
                "scope": "Screening, not measured device performance",
            },
            {
                "id": "stiffness",
                "label": "Structural stiffness",
                "scope": "Supported stiffness properties are scored when available; "
                "missing properties remain unknown",
            },
            {
                "id": "optoelectronics",
                "label": "Optoelectronics",
                "scope": "Exploratory; only supported attributes scored",
            },
            {
                "id": "property_exploration",
                "label": "Property exploration (customize priorities)",
                "scope": "Editable starting point, not a validated recommendation "
                "or added retrieval coverage",
            },
            {
                "id": "custom",
                "label": "Custom application",
                "scope": "Preference label only; no added data coverage",
            },
        ],
    }


PRESETS = (
    (
        "preset-oxide-thin-film",
        {
            "name": "Oxide dielectrics · Thin-film insulation",
            "material_class": "oxide_dielectrics",
            "application": "thin_film_insulation",
            "importance": {
                "stability": 0.3,
                "band_gap": 0.25,
                "element_screen": 0.2,
                "simplicity": 0.1,
                "evidence_quality": 0.15,
                "dielectric_total": 0.0,
            },
        },
    ),
    (
        "preset-oxide-high-k",
        {
            "name": "Oxide dielectrics · High-k screening",
            "material_class": "oxide_dielectrics",
            "application": "high_k_screening",
            "minimum_band_gap_ev": 2.0,
            "importance": {
                "stability": 0.5,
                "band_gap": 0.6,
                "dielectric_total": 1.0,
                "dielectric_electronic": 0.0,
                "element_screen": 0.3,
                "simplicity": 0.2,
                "evidence_quality": 0.0,
            },
        },
    ),
    (
        "preset-ceramic-stiffness",
        {
            "name": "Structural ceramics · Stiffness (exploratory)",
            "material_class": "structural_ceramics",
            "application": "stiffness",
            "importance": {
                "bulk_modulus": 1.0,
                "shear_modulus": 1.0,
                "stability": 0.5,
                "evidence_quality": 0.5,
                "simplicity": 0.2,
            },
        },
    ),
    (
        "preset-semiconductor-optoelectronics",
        {
            "name": "Semiconductors · Optoelectronics (exploratory)",
            "material_class": "semiconductors",
            "application": "optoelectronics",
            "importance": {
                "band_gap": 0.5,
                "direct_gap": 1.0,
                "refractive_index": 0.5,
                "stability": 0.3,
                "evidence_quality": 0.5,
            },
        },
    ),
) + tuple(
    (
        f"preset-{identifier.replace('_', '-')}-exploration",
        {
            "name": f"{label} · Property exploration",
            "material_class": identifier,
            "application": "property_exploration",
            "importance": {
                "evidence_quality": 0.5,
                "element_screen": 0.5,
                **dict.fromkeys(attributes, 0.0),
            },
        },
    )
    for identifier, label, attributes in EXPLORATORY_CLASSES
)


_PRE_OPTICAL_PRESETS = PRESETS


PRESETS = tuple(
    (
        identifier,
        (
            {
                **deepcopy(value),
                "importance": {**value["importance"], "band_gap": 0.0},
            }
            if value["application"] == "optoelectronics"
            else value
        ),
    )
    for identifier, value in _PRE_OPTICAL_PRESETS
)


ATTRIBUTE_IDS = frozenset(item[0] for item in _ATTRIBUTES)


def _negated_preference(text: str, start: int, end: int) -> bool:
    """A bounded request negation, shared by class, application and goal
    hints."""
    return bool(
        re.search(
            r"\b(?:not(?:\s+(?:require|need|prefer|prioritize|target|use|consider|"
            r"include|select))?|need not be|without|no need for|avoid|exclude|"
            r"excluding|except|rather than|instead of|non)\s+"
            r"(?:(?:a|an|the|any|all)\s+)?$",
            text[max(0, start - 80) : start],
        )
        or re.match(
            r"\s+(?:(?:is|are)\s+)?not\s+"
            r"(?:needed|required|necessary|a priority)\b",
            text[end:],
        )
    )
