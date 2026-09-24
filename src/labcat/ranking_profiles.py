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

import hashlib
import json
import math
import re
from copy import deepcopy

from labcat.config import DEFAULT_TARGET_BAND_GAP_TOLERANCE_EV

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


ATTRIBUTE_IDS = frozenset(item[0] for item in _ATTRIBUTES)


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


_PRE_STABILITY_PRESETS = PRESETS


STABILITY_DEFAULT_IMPORTANCE = 0.3


PRESETS = tuple(
    (
        identifier,
        {
            **deepcopy(value),
            "importance": {
                **value["importance"],
                "stability": max(
                    STABILITY_DEFAULT_IMPORTANCE,
                    value["importance"].get("stability", 0),
                ),
                "ambient_phase_stability": STABILITY_DEFAULT_IMPORTANCE,
                "operational_stability": STABILITY_DEFAULT_IMPORTANCE,
            },
        },
    )
    for identifier, value in _PRE_STABILITY_PRESETS
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


DEFAULT_PROFILE_ID = "preset-oxide-high-k"


INFERENCE_VERSION = "catalog-goals-v3"


_CLASS_ALIASES = {
    "oxide_dielectrics": ("oxide dielectric", "oxide dielectrics"),
    "structural_ceramics": (
        "structural ceramic",
        "structural ceramics",
        "ceramic",
        "ceramics",
    ),
    "semiconductors": ("semiconductor", "semiconductors"),
    "polymers": ("polymer", "polymers"),
    "perovskites": ("perovskite", "perovskites"),
    "perovskitoids": ("perovskitoid", "perovskitoids"),
    "ceramic_oxides": (
        "ceramic oxide",
        "ceramic oxides",
        "oxide ceramic",
        "oxide ceramics",
    ),
    "metals_metal_alloys": (
        "metal",
        "metals",
        "alloy",
        "alloys",
        "metal alloy",
        "metal alloys",
        "metallic",
    ),
    "mofs": ("mof", "mofs", "metal organic framework", "metal organic frameworks"),
    "high_entropy_alloys": (
        "high entropy alloy",
        "high entropy alloys",
        "multi principal element alloy",
        "multi principal element alloys",
        "compositionally complex alloy",
        "compositionally complex alloys",
    ),
    "semiconductor_nanocrystals": (
        "semiconductor nanocrystal",
        "semiconductor nanocrystals",
        "quantum dot",
        "quantum dots",
        "qd",
        "qds",
        "nanocrystal",
        "nanocrystals",
    ),
    "organic_electronic_materials": (
        "organic semiconductor",
        "organic semiconductors",
        "organic photovoltaic",
        "organic photovoltaics",
        "organic electronic materials",
        "organic materials for photovoltaics",
        "organic materials for solar cells",
        "organic solar cell",
        "organic solar cells",
        "molecular semiconductor",
        "molecular semiconductors",
        "molecular donor acceptor",
        "small molecule semiconductor",
        "small molecule semiconductors",
        "opv",
        "opvs",
    ),
    "two_dimensional_materials": (
        "2d",
        "two dimensional",
        "monolayer",
        "monolayers",
        "atomically thin",
    ),
    "polymer_matrix_composites": (
        "polymer matrix composite",
        "polymer matrix composites",
    ),
    "ceramic_matrix_composites": (
        "ceramic matrix composite",
        "ceramic matrix composites",
    ),
    "biomaterials": ("biomaterial", "biomaterials"),
    "elastomers": ("elastomer", "elastomers"),
    "liquid_crystals": ("liquid crystal", "liquid crystals"),
    "thermosets": ("thermoset", "thermosets"),
    "thermoplastics": ("thermoplastic", "thermoplastics"),
}


_APPLICATION_ALIASES = {
    "thin_film_insulation": (
        "thin film",
        "thin films",
        "thin film insulation",
        "insulation",
    ),
    "high_k_screening": (
        "high k",
        "high k screening",
        "high permittivity",
        "high dielectric constant",
        "large dielectric constant",
    ),
    "stiffness": (
        "stiffness",
        "structural stiffness",
        "stiff",
        "high modulus",
        "high elastic modulus",
        "high bulk modulus",
        "high shear modulus",
    ),
    "optoelectronics": (
        "optoelectronic",
        "optoelectronics",
        "photovoltaic",
        "photovoltaics",
        "opv",
        "opvs",
        "solar cell",
        "solar cells",
        "light emitting",
        "photodetector",
        "photodetectors",
        "photodetection",
        "solar absorber",
        "solar absorbers",
        "solar absorption",
        "led",
        "leds",
    ),
    "property_exploration": ("property exploration",),
}


_APPLICATION_TEMPLATES = {
    "thin_film_insulation": "preset-oxide-thin-film",
    "high_k_screening": "preset-oxide-high-k",
    "stiffness": "preset-ceramic-stiffness",
    "optoelectronics": "preset-semiconductor-optoelectronics",
}


def _composed_profile(material_class: str, application: str, profiles: list[dict]):
    """Combine preference templates, without classifying any material as
    a fact."""
    template_id = _APPLICATION_TEMPLATES.get(application)
    template = next((p for p in profiles if p["id"] == template_id), None)
    if template is None:
        return None
    definitions = catalog()
    classes = {item["id"]: item["label"] for item in definitions["material_classes"]}
    applications = {item["id"]: item["label"] for item in definitions["applications"]}
    fingerprint = hashlib.sha256(
        json.dumps([material_class, application]).encode()
    ).hexdigest()[:24]
    composed = {
        **deepcopy(template),
        "id": f"inferred-{fingerprint}",
        "name": f"{classes.get(material_class, material_class)} · "
        f"{applications.get(application, application)}"[:120],
        "material_class": material_class,
        "application": application,
        "preset": False,
    }
    if (
        material_class == "organic_electronic_materials"
        and application == "optoelectronics"
    ):
        # Molecular donor/acceptor preferences do not request a crystal-momentum
        # direct-gap utility. Keep it editable without inferring that criterion.
        composed["importance"]["direct_gap"] = 0.0
    composed["normalized_weights"] = normalize_importance(composed["importance"])
    return composed


def compose_catalog_profile(material_class: str, application: str) -> dict:
    """Build one run's catalog preferences without editing saved
    profiles.

    Call with validated semantic request labels, never labels inferred
    from material evidence. A class/application pairing grants no source
    capability. Unknown applications are handled by the caller as
    property exploration.
    """
    definitions = catalog()
    classes = {item["id"]: item["label"] for item in definitions["material_classes"]}
    applications = {item["id"]: item["label"] for item in definitions["applications"]}
    if material_class not in classes or application not in applications:
        raise ValueError("Choose semantic preferences from the catalog.")
    profiles = [
        {**deepcopy(value), "id": identifier, "preset": True}
        for identifier, value in PRESETS
    ]
    matched = next(
        (
            item
            for item in profiles
            if item["material_class"] == material_class
            and item["application"] == application
        ),
        None,
    )
    selected = matched or _composed_profile(material_class, application, profiles)
    if selected is None:
        # Classes without a dedicated application template start with the same
        # source-neutral exploration preferences as the catalog's other classes.
        # No class-specific property optimum or material cohort is supplied.
        fingerprint = hashlib.sha256(
            json.dumps([material_class, application]).encode()
        ).hexdigest()[:24]
        selected = {
            "id": f"inferred-{fingerprint}",
            "name": f"{classes[material_class]} · {applications[application]}"[:120],
            "material_class": material_class,
            "application": application,
            "importance": {
                "evidence_quality": 0.5,
                "element_screen": 0.5,
            },
            "preset": False,
        }
    for attribute in (
        "stability",
        "ambient_phase_stability",
        "operational_stability",
    ):
        selected["importance"][attribute] = max(
            STABILITY_DEFAULT_IMPORTANCE, selected["importance"].get(attribute, 0)
        )
    selected["normalized_weights"] = normalize_importance(selected["importance"])
    return selected


def application_preferences(profile: dict, prompt: str):
    """Select photovoltaic review priorities, never an optimum or a
    measurement.

    Only per-run inferred profiles use these defaults. Explicit saved
    profiles remain authoritative. A band gap matters for a solar
    absorber, but without a requested target a larger gap is not
    automatically a better match.
    """
    selected = deepcopy(profile)
    if (
        selected.get("material_class") != "perovskites"
        or selected.get("application") != "optoelectronics"
        or not _hint_matches(
            prompt,
            {"photovoltaics"},
            {
                "photovoltaics": (
                    "solar cell",
                    "solar cells",
                    "solar absorber",
                    "solar absorbers",
                    "photovoltaic",
                    "photovoltaics",
                )
            },
        )
    ):
        return selected, []
    importance = selected["importance"]
    for attribute, value in (
        ("band_gap", 0.9),
        ("operational_stability", 0.9),
        ("ambient_phase_stability", 0.6),
    ):
        importance[attribute] = max(value, importance.get(attribute, 0))
    # Replace only generic template emphasis before explicit request goals are
    # applied. This is never used to edit the persisted profile or source values.
    importance["direct_gap"] = 0.2
    importance["refractive_index"] = 0.0
    selected["normalized_weights"] = normalize_importance(importance)
    return selected, [
        {
            "attribute": attribute,
            "status": "applied_application_preference",
            "relation": "consider" if attribute == "band_gap" else "maximize",
            "reason": "Photovoltaic absorber review prioritizes spectral match "
            "and phase/operating stability. No numeric optimum or "
            "measured material value is supplied by this preference.",
        }
        for attribute in (
            "band_gap",
            "operational_stability",
            "ambient_phase_stability",
        )
    ]


def apply_semantic_goals(profile: dict, prompt: str, goals: list[dict]):
    """Add validated goal preferences using fixed priorities, never
    model values.

    The semantic-intake validator binds each goal to the user's positive
    request. Numeric goals still use the existing whole-prompt parser so
    a selected short span cannot hide contradictory targets elsewhere in
    the request.
    """
    selected, adjustments = application_preferences(profile, prompt)
    priority_weights = {"primary": 1.0, "normal": 0.5, "secondary": 0.25}
    for goal in goals:
        attribute = goal["attribute_id"]
        if attribute not in ATTRIBUTE_IDS or goal["priority"] not in priority_weights:
            raise ValueError("Choose semantic goals from the preference catalog.")
        selected["importance"][attribute] = max(
            selected["importance"].get(attribute, 0),
            priority_weights[goal["priority"]],
        )
        adjustments.append(
            {
                "attribute": attribute,
                "status": "applied_preference",
                "priority": goal["priority"],
                "relation": goal.get("relation", "consider"),
                "request_span": goal["request_span"],
                "reason": "Added the requested catalog criterion using a fixed "
                "importance preference. No material value came from the model.",
            }
        )
    if any(goal["attribute_id"] == "band_gap" for goal in goals):
        numeric_profile, numeric_adjustments = prompt_preferences(selected, prompt)
        adjustments.extend(
            item
            for item in numeric_adjustments
            if item["attribute"] == "band_gap"
            and (
                item["status"] == "needs_clarification"
                or "target_band_gap_ev" in item
                or "minimum_band_gap_ev" in item
            )
        )
        for field in (
            "minimum_band_gap_ev",
            "target_band_gap_ev",
            "band_gap_tolerance_ev",
        ):
            if field in numeric_profile:
                selected[field] = numeric_profile[field]
    selected["normalized_weights"] = normalize_importance(selected["importance"])
    return selected, adjustments


def _preference_words(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def _request_text(prompt: str) -> str:
    """Remove citation hints and claim-bearing sentences from preference
    parsing."""
    text = re.sub(r"https?://\S+", " ", prompt).casefold()[:24000]
    text = re.sub(r"[‐‑‒–—]", "-", text)
    return " ".join(
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if not re.search(
            r"\b(?:according to|i (?:claim|read)|(?:source|paper|article|literature) "
            r"(?:says|states|reports|claims)|measured band[ -]?gap)\b",
            sentence,
        )
    )


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


def _hint_matches(prompt: str, values: set[str], aliases: dict) -> set[str]:
    """Keep specific phrases over contained generic ones (e.g. quantum
    dots)."""
    text = _preference_words(_request_text(prompt))
    spans: dict[tuple[int, int], set[str]] = {}
    for value in values:
        if value == "custom":
            continue
        phrases = aliases.get(value, (_preference_words(value),))
        for phrase in phrases:
            if not any(character.isalpha() for character in phrase):
                continue
            for match in re.finditer(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text):
                if _negated_preference(text, match.start(), match.end()):
                    # A negated specific phrase also suppresses the generic
                    # aliases inside it (e.g. 'not oxide ceramics').
                    spans.setdefault(match.span(), set())
                    continue
                if (
                    value == "metals_metal_alloys"
                    and phrase in {"metal", "metals"}
                    and re.match(
                        r"\s+(?:halide|oxide|organic|nitride|carbide|"
                        r"chalcogenide|sulfide|sulphide|selenide|telluride)\b",
                        text[match.end() :],
                    )
                ):
                    continue
                spans.setdefault(match.span(), set()).add(value)
    matched = set()
    furthest_end = -1
    # A sweep avoids quadratic comparisons for long, repeated user input.
    for start, end in sorted(spans, key=lambda span: (span[0], -span[1])):
        if end > furthest_end:
            matched.update(spans[(start, end)])
            furthest_end = end
    return matched


def _infer_profile(
    prompt: str, profiles: list[dict], active: dict
) -> tuple[dict, str, str]:
    classes = _hint_matches(
        prompt, {profile["material_class"] for profile in profiles}, _CLASS_ALIASES
    )
    oxide_dielectric_hint = "oxide_dielectrics" in classes
    # Broad descriptors can qualify a more specific requested family. These
    # preference hints cannot establish a candidate's composition or structure.
    qualifiers = {
        "semiconductors": {
            "perovskites",
            "perovskitoids",
            "semiconductor_nanocrystals",
            "organic_electronic_materials",
            "two_dimensional_materials",
        },
        "oxide_dielectrics": {"perovskites", "perovskitoids"},
        "structural_ceramics": {"perovskites", "perovskitoids", "ceramic_oxides"},
        "ceramic_oxides": {"perovskites", "perovskitoids"},
        "metals_metal_alloys": {"two_dimensional_materials"},
    }
    for generic, specific in qualifiers.items():
        if generic not in classes or not classes & specific:
            continue
        aliases = "(?:" + "|".join(map(re.escape, _CLASS_ALIASES[generic])) + ")"
        specific_aliases = (
            "(?:"
            + "|".join(
                re.escape(alias)
                for identifier in sorted(classes & specific)
                for alias in _CLASS_ALIASES[identifier]
            )
            + ")"
        )
        comparison = r"(?:versus|vs|or|and|with|against)"
        modifier = r"(?:\w+\s+){0,2}"
        subject = r"(?:\s+(?:materials?|candidates?|systems?))?"
        if not re.search(
            rf"\b{aliases}{subject}\s+{comparison}\s+{modifier}{specific_aliases}\b|"
            rf"\b{specific_aliases}{subject}\s+{comparison}\s+{modifier}{aliases}\b",
            _preference_words(_request_text(prompt)),
        ):
            classes.discard(generic)
    applications = _hint_matches(
        prompt, {profile["application"] for profile in profiles}, _APPLICATION_ALIASES
    )
    # Film geometry alone must not override a more explicit optical/electrical
    # application. An explicit insulation request remains an ambiguity.
    if (
        "thin_film_insulation" in applications
        and (
            applications & {"optoelectronics", "high_k_screening"}
            or not oxide_dielectric_hint
        )
        and not _hint_matches(prompt, {"insulation"}, {"insulation": ("insulation",)})
    ):
        applications.discard("thin_film_insulation")
    if len(classes) != 1 or len(applications) > 1:
        return (
            active,
            "fallback",
            (
                "The prompt does not identify one unambiguous material class and "
                "application. Used the active ranking profile for weights only; "
                "its material class does not restrict source queries. Choose a "
                "profile to override."
            ),
        )
    candidates = [p for p in profiles if p["material_class"] in classes]
    if applications:
        candidates = [p for p in candidates if p["application"] in applications]
        if not candidates:
            composed = _composed_profile(
                next(iter(classes)), next(iter(applications)), profiles
            )
            if composed is not None:
                return (
                    composed,
                    "inferred",
                    "Combined the requested material class with the catalog's "
                    "application priorities for this run. No saved profile changed. "
                    "These are search and ranking preferences; source evidence is "
                    "still required for every candidate and property.",
                )
    if len({p["application"] for p in candidates}) > 1:
        return (
            active,
            "fallback",
            "Several applications fit the material-class hint. Used the active "
            "ranking profile for weights only, without restricting source queries "
            "to its material class. Choose a profile or add an application preference.",
        )
    if any(p["id"] == active["id"] for p in candidates):
        return (
            active,
            "inferred",
            (
                "The active ranking profile matches the recognized preference hints. "
                "Its saved importance values were retained."
            ),
        )
    presets = [p for p in candidates if p["preset"]]
    if len(candidates) == 1 or len(presets) == 1:
        selected = candidates[0] if len(candidates) == 1 else presets[0]
        return (
            selected,
            "inferred",
            (
                "Matched the prompt's recognized preference hints to a saved "
                "ranking profile. Used its saved importance values and material "
                "class as search preferences; only retrieved public records can "
                "establish properties."
            ),
        )
    return (
        active,
        "fallback",
        (
            "The prompt's hints do not resolve to a single available ranking profile. "
            "Used the active ranking profile for weights only, without restricting "
            "source queries to its material class; choose a profile to override."
        ),
    )


def prompt_preferences(profile: dict, prompt: str) -> tuple[dict, list[dict]]:
    """Extract narrowly worded goals, never measured values or arbitrary
    weights.

    This is intentionally not a general numerical extractor. A requested
    target or minimum must be attached to a band-gap goal; nearby source
    claims, URLs, arbitrary JSON and weight assignments do not populate
    material records.
    """
    # Source claims embedded in a research request are not requested properties.
    # Keep their original text in chat, but omit claim-bearing sentences here.
    text = _request_text(prompt)
    requested = re.search(
        r"\b(find|screen|seek|seeking|looking for|want|would like|prefer|target|"
        r"aim|need|require|change|adjust|instead|compare|evaluate|assess|identify|"
        r"suggest|recommend|shortlist|select|explore|search|show|list)\b",
        text,
    )
    if not requested:
        return deepcopy(profile), []
    number = r"(?<![\w.])(?:\d{1,3}(?:\.\d{1,6})?|\.\d{1,6})(?![\w.])"
    gap = r"band[ -]?gap"
    target_patterns = (
        rf"{gap}\s+(?:(?:should|must)\s+be\s+|(?:of|is|at)\s+)?"
        rf"(?:around|about|approximately|near|close to|target(?:ed)?(?: at)?|~)"
        rf"\s*(?P<value>{number})\s*ev\b",
        rf"\b(?:target|targeting|aim(?:ing)? for)\s+(?:a\s+)?"
        rf"(?P<value>{number})\s*ev\s+{gap}\b",
        rf"{gap}\s+(?:should|must)\s+be\s+(?P<value>{number})\s*ev\b",
        rf"\btarget(?:ed)?\s+{gap}\s+(?:(?:of|is|at)\s+)?"
        rf"(?P<value>{number})\s*ev\b",
        rf"{gap}\s+(?:(?:of|is|around|about)\s+)?(?P<value>{number})\s*"
        rf"(?:±|\+/-)\s*{number}\s*ev\b",
    )
    minimum_pattern = (
        rf"{gap}\s+(?:(?:should|must)\s+be\s+|(?:of|is)\s+)?"
        rf"(?:at least|no less than|minimum(?: of)?|>=|≥)\s*"
        rf"(?P<value>{number})\s*ev\b"
    )
    targets = {
        float(match["value"])
        for pattern in target_patterns
        for match in re.finditer(pattern, text)
        if 0 <= float(match["value"]) <= 100
        and not _negated_preference(text, match.start(), match.end())
    }
    minimums = {
        float(match["value"])
        for match in re.finditer(minimum_pattern, text)
        if 0 <= float(match["value"]) <= 100
        and not _negated_preference(text, match.start(), match.end())
    }
    selected, adjustments = (
        application_preferences(profile, prompt)
        if str(profile.get("id", "")).startswith("inferred-")
        else (deepcopy(profile), [])
    )
    if len(targets) > 1 or len(minimums) > 1:
        adjustments.append(
            {
                "attribute": "band_gap",
                "status": "needs_clarification",
                "reason": "Several different band-gap goals were requested; "
                "the saved preference is unchanged. Choose one target or minimum.",
            }
        )
    elif targets:
        target = next(iter(targets))
        stated_tolerances = {
            float(match["value"])
            for match in re.finditer(
                rf"(?:±|\+/-|\+−)\s*(?P<value>{number})\s*ev\b", text
            )
        }
        tolerances = {value for value in stated_tolerances if 0 < value <= 100}
        if len(tolerances) > 1 or tolerances != stated_tolerances:
            adjustments.append(
                {
                    "attribute": "band_gap",
                    "status": "needs_clarification",
                    "reason": "The target tolerance is ambiguous or outside the "
                    "supported positive preference range; the saved band-gap "
                    "preference is unchanged.",
                }
            )
        else:
            tolerance = (
                next(iter(tolerances))
                if tolerances
                else DEFAULT_TARGET_BAND_GAP_TOLERANCE_EV
            )
            selected["target_band_gap_ev"] = target
            selected["band_gap_tolerance_ev"] = tolerance
            # A target replaces a stale minimum unless both were explicitly
            # requested in this turn. In particular, a lower optical target must
            # not be eliminated by an inherited insulation threshold.
            selected["minimum_band_gap_ev"] = next(iter(minimums)) if minimums else None
            selected["importance"]["band_gap"] = max(
                0.5, selected["importance"].get("band_gap", 0)
            )
            adjustments.append(
                {
                    "attribute": "band_gap",
                    "status": "applied_preference",
                    "target_band_gap_ev": target,
                    "band_gap_tolerance_ev": tolerance,
                    "tolerance_origin": (
                        "prompt_preference" if tolerances else "application_default"
                    ),
                    "reason": "The requested band gap is a target preference, "
                    "never source evidence. The tolerance is a soft ranking scale "
                    "(half band-gap utility at this distance), not a measured "
                    "uncertainty or a hard exclusion. "
                    + (
                        "Used the requested tolerance."
                        if tolerances
                        else "No tolerance was specified; used the editable "
                        f"{tolerance:g} eV application preference."
                    ),
                }
            )
    elif minimums:
        selected["minimum_band_gap_ev"] = next(iter(minimums))
        selected["target_band_gap_ev"] = None
        selected["band_gap_tolerance_ev"] = None
        selected["importance"]["band_gap"] = max(
            0.5, selected["importance"].get("band_gap", 0)
        )
        adjustments.append(
            {
                "attribute": "band_gap",
                "status": "applied_preference",
                "minimum_band_gap_ev": next(iter(minimums)),
                "reason": "Used the explicitly requested minimum as a screening "
                "preference. It does not supply a material's band-gap value.",
            }
        )
    for attribute, pattern, reason in (
        (
            "stability",
            r"\b(?:stable|thermodynamic(?:ally)? stabil(?:ity|e))\b",
            "Added the stability preference. Hull energy alone does not establish "
            "stability during processing or operation.",
        ),
        (
            "ambient_phase_stability",
            r"\b(?:room[ -]temperature|ambient)(?: phase)?[ -]stabil(?:ity|e)\b|"
            r"\bstable (?:phase )?(?:at|under) (?:room[ -]temperature|ambient)\b",
            "Retained room-temperature phase stability for public source review. "
            "It is separate from hull energy and remains unknown without evidence.",
        ),
        (
            "operational_stability",
            r"\b(?:operational|operating|device)[ -]stability\b|"
            r"\b(?:operationally stable|stable (?:during|under|in) "
            r"(?:operation|illumination|operating conditions|use))\b",
            "Retained stability under operating conditions for public source "
            "review. It remains unscored and unknown without suitable evidence.",
        ),
        (
            "band_gap",
            r"\b(?:wide|wider|large|larger|high)[ -]band[ -]?gaps?\b",
            "Used the requested wider-gap preference. No gap value is supplied "
            "by the prompt; an explicit numeric target still takes precedence.",
        ),
        (
            "dielectric_total",
            r"\b(?:high|higher|large|larger)[ -](?:permittivity|dielectric "
            r"(?:constant|response))\b|\bhigh[ -]k\b",
            "Used the requested larger total dielectric response preference. "
            "It does not establish dielectric loss or device performance.",
        ),
        (
            "simplicity",
            r"\b(?:simple|simpler)[ -]compositions?\b|\bfewer (?:distinct )?elements\b",
            "Used the requested preference for fewer distinct elements. "
            "This does not establish synthesis difficulty.",
        ),
        (
            "element_screen",
            r"\b(?:non[ -]?toxic|low[ -]toxicity|avoid toxic|exclude toxic)\b",
            "Retained the requested conservative element screen. Passing this "
            "screen is not evidence that a compound is safe.",
        ),
        (
            "bulk_modulus",
            r"\b(?:high|higher|large|larger)[ -]bulk modulus\b",
            "Used the requested larger bulk modulus preference; source evidence "
            "is required and this is not a toughness measurement.",
        ),
        (
            "shear_modulus",
            r"\b(?:high|higher|large|larger)[ -]shear modulus\b",
            "Used the requested larger shear modulus preference; source evidence "
            "is required and this is not a ductility measurement.",
        ),
        (
            "direct_gap",
            r"\bdirect[ -](?:band[ -]?)?gap\b",
            "Retained direct gap character as an explicit preference. It does "
            "not establish light-emission efficiency or absorption performance.",
        ),
        (
            "density",
            r"\b(?:(?:low(?:er)?|reduced|mass|bulk)[ -]+)?density\b",
            "Retained density as a ranking preference. The catalog favors lower "
            "source-reported mass density; no density value comes from the prompt.",
        ),
        (
            "solution_processability",
            r"\bsolution[\s‐‑‒–—-]+process(?:able|ability|ed|ing)\b",
            "Retained the requested processing preference for public source review. "
            "It remains unscored until a supported adapter supplies suitable evidence.",
        ),
    ):
        matches = list(re.finditer(pattern, text))
        if attribute == "density":
            # Only mass density is the catalog criterion. Other densities and
            # an explicit preference for higher density need different utilities.
            matches = [
                match
                for match in matches
                if not re.search(
                    r"\b(?:energy|power|current|charge|electron|carrier|spin|optical|"
                    r"number|surface|state|high(?:er)?|greater|maximum|"
                    r"increas(?:e|ed|ing))[ -]+$",
                    text[max(0, match.start() - 40) : match.start()],
                )
                and not re.match(r"\s+of\s+states\b", text[match.end() :])
            ]
        if any(
            not _negated_preference(text, match.start(), match.end())
            for match in matches
        ):
            selected["importance"][attribute] = max(
                0.5, selected["importance"].get(attribute, 0)
            )
            adjustments.append(
                {
                    "attribute": attribute,
                    "status": "applied_preference",
                    "reason": reason,
                }
            )
    if adjustments:
        selected["normalized_weights"] = normalize_importance(selected["importance"])
    return selected, adjustments


class RankingProfileNotFound(ValueError):
    """The requested profile does not exist."""


def normalize_importance(value: object) -> dict[str, float]:
    """All selected criteria share the denominator, including
    unsupported ones."""
    if not isinstance(value, dict) or not value or set(value) - ATTRIBUTE_IDS:
        raise ValueError("Choose attributes from the supported preference catalog.")
    if any(
        type(weight) not in {int, float}
        or not 0 <= weight <= 1
        or not math.isfinite(weight)
        for weight in value.values()
    ):
        raise ValueError("Each importance must be a finite number from zero to one.")
    total = math.fsum(value.values())
    if total <= 0:
        raise ValueError("At least one importance must be greater than zero.")
    return {name: weight / total for name, weight in value.items()}


def validate_profile(value: object) -> dict:
    required = {
        "name",
        "material_class",
        "application",
        "importance",
    }
    if (
        not isinstance(value, dict)
        or not required <= set(value)
        or set(value)
        - required
        - {"minimum_band_gap_ev", "target_band_gap_ev", "band_gap_tolerance_ev"}
    ):
        raise ValueError(
            "Provide name, material class, application, importance, and optionally "
            "minimum or target band-gap preferences."
        )
    cleaned = {}
    for name in ("name", "material_class", "application"):
        text = value[name]
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 120:
            raise ValueError("Profile names and labels must be 1–120 characters.")
        if any(ord(character) < 32 for character in text):
            raise ValueError(
                "Profile names and labels cannot contain control characters."
            )
        cleaned[name] = text.strip()
    normalize_importance(value["importance"])
    cleaned["importance"] = dict(value["importance"])
    if "minimum_band_gap_ev" in value:
        minimum = value["minimum_band_gap_ev"]
        if minimum is not None and (
            type(minimum) not in (int, float)
            or not 0 <= minimum <= 100
            or not math.isfinite(minimum)
        ):
            raise ValueError(
                "Minimum band gap must be a finite preference from 0 to 100 eV, "
                "or disabled."
            )
        # Preserve omission in older/custom profiles rather than silently adding
        # a default threshold or rewriting archived preference snapshots.
        cleaned["minimum_band_gap_ev"] = minimum
    if "target_band_gap_ev" in value:
        target = value["target_band_gap_ev"]
        if target is not None and (
            type(target) not in (int, float)
            or not 0 <= target <= 100
            or not math.isfinite(target)
        ):
            raise ValueError(
                "Target band gap must be a finite preference from 0 to 100 eV, "
                "or disabled."
            )
        cleaned["target_band_gap_ev"] = target
    if "band_gap_tolerance_ev" in value:
        tolerance = value["band_gap_tolerance_ev"]
        if tolerance is not None and (
            type(tolerance) not in (int, float)
            or not 0 < tolerance <= 100
            or not math.isfinite(tolerance)
            or value.get("target_band_gap_ev") is None
        ):
            raise ValueError(
                "Band-gap tolerance must be a finite preference above zero and "
                "at most 100 eV, with a target band gap enabled, or disabled."
            )
        cleaned["band_gap_tolerance_ev"] = tolerance
    return cleaned
