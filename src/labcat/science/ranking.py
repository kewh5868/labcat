"""Deterministic utility ranking; preferences never supply material
properties."""

import math
import re
from copy import deepcopy

from labcat.config import DEFAULT_TARGET_BAND_GAP_TOLERANCE_EV, AppConfig

from .evidence_comparison import compare_and_select_records
from .preferences import composition_key

# Screening preferences, not a toxicology database. Keep this versioned and
# disclose the exact set in every ranking audit; never call surviving rows safe.
ELEMENT_PRESET_VERSION = "conservative-elements-v2"
EXCLUDED_ELEMENTS = (
    "Ac",
    "Am",
    "As",
    "At",
    "Be",
    "Bk",
    "Cd",
    "Cf",
    "Cm",
    "Es",
    "Fm",
    "Fr",
    "Hg",
    "Lr",
    "Md",
    "No",
    "Np",
    "Pa",
    "Pb",
    "Pm",
    "Po",
    "Pu",
    "Ra",
    "Rn",
    "Tc",
    "Th",
    "Tl",
    "U",
)
GAP_ANCHOR_EV = 8.0
HULL_ANCHOR_EV_ATOM = 0.1
TOTAL_DIELECTRIC_ANCHOR = 50.0
ELECTRONIC_DIELECTRIC_ANCHOR = 10.0
HIGH_K_REFERENCE = 4.0  # Screening preference, not a measured material property.
SHORTLIST_SIZE = 12
SCORE_SCALE = {
    "minimum": 0,
    "maximum": 1,
    "label": "Derived overall utility",
    "meaning": "Preference utility; not confidence or probability",
    "anchors": [
        {"value": 0, "color": "#F8D7DA"},
        {"value": 0.5, "color": "#FFF0C2"},
        {"value": 1, "color": "#D5EDDD"},
    ],
}
SUPPORTED_CRITERIA = frozenset(
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


def score_color(score: object) -> str | None:
    """Absolute utility colors; the best available candidate is not
    rescaled."""
    if (
        type(score) not in (int, float)
        or not math.isfinite(score)
        or not 0 <= score <= 1
    ):
        return None
    anchors = SCORE_SCALE["anchors"]
    low, high = anchors[:2] if score <= 0.5 else anchors[1:]
    ratio = (score - low["value"]) / (high["value"] - low["value"])
    channels = [
        round(
            int(low["color"][offset : offset + 2], 16) * (1 - ratio)
            + int(high["color"][offset : offset + 2], 16) * ratio
        )
        for offset in (1, 3, 5)
    ]
    return "#" + "".join(f"{value:02X}" for value in channels)


def score_band(score: object) -> str:
    if score_color(score) is None:
        return "unscored"
    return "low" if score < 1 / 3 else "medium" if score < 2 / 3 else "high"


def _weights(config: AppConfig, importance: dict | None) -> tuple[dict, dict]:
    raw = config.to_dict()["ranking"] if importance is None else importance
    if not isinstance(raw, dict) or not raw or len(raw) > 100:
        raise ValueError("Ranking importance must be a bounded, nonempty mapping.")
    for key, value in raw.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key):
            raise ValueError("Unsupported ranking criterion identifier.")
        if (
            type(value) not in (int, float)
            or not 0 <= value <= 1
            or not math.isfinite(value)
        ):
            raise ValueError("Ranking importance must be finite and between 0 and 1.")
    total = math.fsum(raw.values())
    if total <= 0:
        raise ValueError("At least one ranking importance must be positive.")
    return dict(raw), {key: value / total for key, value in raw.items()}


def _stability_assessment(hull):
    """Describe only the reviewed hull scalar; prose cannot populate
    other scopes."""
    return {
        "schema": "stability-assessment-v1",
        "thermodynamic": {
            "status": "available" if hull is not None else "unknown",
            "energy_above_hull_ev_atom": hull,
            "scope": "Source-calculated energy above competing phases under "
            "the source's calculation assumptions, in eV/atom.",
            "interpretation": (
                "Thermodynamic stability is unknown: no valid hull energy supplied."
                if hull is None
                else (
                    "Zero source hull energy does not establish room-temperature "
                    "phase stability, kinetic persistence or operational stability."
                    if hull == 0
                    else "Positive source hull energy reduces thermodynamic utility; "
                    "it does not establish a degradation rate or prove instability "
                    "at room temperature or under operating conditions."
                )
            ),
        },
        "ambient_phase": {
            "status": "unknown",
            "reason": "Room-temperature phase stability is unknown: no approved "
            "adapter has verified phase persistence under stated ambient "
            "conditions for this record.",
        },
        "operational": {
            "status": "unknown",
            "reason": "Operational stability is unknown: no approved adapter has "
            "verified stability for the intended environment, temperature, "
            "illumination or load, and duration.",
        },
    }


def reviewed_goal_preferences(scope, profile, authority):
    """Canonical preference diagnostics, shared with saved report
    rendering."""
    from labcat.research_intent import review_only_attributes

    if not isinstance(authority, str) or authority not in {"inferred", "profile"}:
        raise ValueError("Invalid semantic goal review authority.")
    reviewed = review_only_attributes(scope, profile)
    return {
        "version": "semantic-goals-v1",
        "authority": authority,
        "scope": deepcopy(scope),
        "requested_goals": deepcopy(scope["goals"]),
        "review_only_attributes": reviewed,
        "unscored_attributes": (
            [row["attribute_id"] for row in reviewed] if authority == "inferred" else []
        ),
        "interpretation": (
            "Unsupported requested directions are unscored. Selected weights and "
            "source measurements remain unchanged; no inverse utility or target "
            "anchor was invented."
            if authority == "inferred"
            else "The selected ranking profile remains authoritative. Requested "
            "goal mismatches are annotated without changing its utilities, "
            "weights or screening parameters."
        ),
    }


def _review_goals(goal_review, profile):
    if goal_review is None:
        return None
    from labcat.research_intent import validate_scope

    if not isinstance(goal_review, dict) or set(goal_review) != {
        "scope",
        "prompt",
        "authority",
    }:
        raise ValueError("Invalid semantic goal review preferences.")
    scope = validate_scope(goal_review["scope"], goal_review["prompt"])
    return reviewed_goal_preferences(scope, profile, goal_review["authority"])


def rank_records(
    records: list[dict],
    config: AppConfig,
    *,
    importance: dict | None = None,
    application: str | None = None,
    minimum_band_gap_ev: float | None = None,
    target_band_gap_ev: float | None = None,
    band_gap_tolerance_ev: float | None = None,
    goal_review: dict | None = None,
) -> tuple[list[dict], dict]:
    """Normalize preferences once, counting unavailable criteria in the
    denominator."""
    if application is not None and (
        not isinstance(application, str)
        or not 1 <= len(application) <= 120
        or not application.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in application)
    ):
        raise ValueError("Unsupported ranking application preference.")
    if minimum_band_gap_ev is not None and (
        type(minimum_band_gap_ev) not in (int, float)
        or not math.isfinite(minimum_band_gap_ev)
        or not 0 <= minimum_band_gap_ev <= 100
    ):
        raise ValueError(
            "Minimum band gap must be a finite screening preference from 0 to 100 eV."
        )
    if target_band_gap_ev is not None and (
        type(target_band_gap_ev) not in (int, float)
        or not 0 <= target_band_gap_ev <= 100
        or not math.isfinite(target_band_gap_ev)
    ):
        raise ValueError(
            "Target band gap must be a finite preference from 0 to 100 eV."
        )
    if band_gap_tolerance_ev is not None and (
        type(band_gap_tolerance_ev) not in (int, float)
        or not 0 < band_gap_tolerance_ev <= 100
        or not math.isfinite(band_gap_tolerance_ev)
        or target_band_gap_ev is None
    ):
        raise ValueError(
            "Band-gap tolerance must be a finite preference above zero and at "
            "most 100 eV, with a target band gap enabled."
        )
    tolerance = (
        band_gap_tolerance_ev
        if band_gap_tolerance_ev is not None
        else DEFAULT_TARGET_BAND_GAP_TOLERANCE_EV
    )
    raw_importance, weights = _weights(config, importance)
    reviewed_goals = _review_goals(
        goal_review,
        {
            "importance": raw_importance,
            "application": application,
            "minimum_band_gap_ev": minimum_band_gap_ev,
            "target_band_gap_ev": target_band_gap_ev,
            "band_gap_tolerance_ev": band_gap_tolerance_ev,
        },
    )
    unscored_goals = (
        {
            row["attribute_id"]: row["reason"]
            for row in reviewed_goals["review_only_attributes"]
            if row["attribute_id"] in reviewed_goals["unscored_attributes"]
        }
        if reviewed_goals
        else {}
    )
    band_gap_active = raw_importance.get("band_gap", 0) > 0 and (
        "band_gap" not in unscored_goals
    )
    records, comparison_audit = compare_and_select_records(
        records,
        band_gap_active=band_gap_active,
        minimum_band_gap_ev=minimum_band_gap_ev if band_gap_active else None,
        target_band_gap_ev=target_band_gap_ev if band_gap_active else None,
    )
    high_k = application == "high_k_screening"
    required = [
        key
        for key in ("dielectric_total", "band_gap")
        if high_k and raw_importance.get(key, 0) > 0
    ]
    if (
        target_band_gap_ev is not None
        and raw_importance.get("band_gap", 0) > 0
        and "band_gap" not in required
    ):
        required.append("band_gap")
    eligible, excluded = (
        [],
        comparison_audit.pop("experimental_preference_excluded_records"),
    )
    seen = set()
    for record in records:
        material_id = record["material_id"]
        if material_id in seen:
            raise ValueError(
                "Conflicting duplicate material identity in source records."
            )
        seen.add(material_id)
        matches = sorted(set(record["elements"]) & set(EXCLUDED_ELEMENTS))
        reasons = []
        if (
            matches
            and raw_importance.get("element_screen", 0) > 0
            and "element_screen" not in unscored_goals
        ):
            reasons.append(
                "Matches the conservative element-exclusion preset: "
                + ", ".join(matches)
            )
        gap, dielectric = record.get("band_gap_ev"), record.get("dielectric_total")
        if (
            minimum_band_gap_ev is not None
            and band_gap_active
            and gap is not None
            and gap < minimum_band_gap_ev
        ):
            reasons.append(
                f"Source band gap {gap:g} eV is below the saved screening minimum "
                f"of {minimum_band_gap_ev:g} eV. This fails an application preference, "
                "not a universal material requirement."
            )
        if reasons:
            excluded.append(
                {
                    "material_id": material_id,
                    "formula": record["formula"],
                    "reasons": reasons,
                    "provenance": deepcopy(record.get("provenance", {})),
                    "evidence_comparison": deepcopy(record["evidence_comparison"]),
                }
            )
            continue
        raw_hull = record.get("energy_above_hull_ev_atom")
        hull = (
            float(raw_hull)
            if type(raw_hull) in (int, float)
            and 0 <= raw_hull <= 1_000_000
            and math.isfinite(raw_hull)
            else None
        )
        # Defense in depth for future adapters. Booleans, prose and malformed
        # energies do not become a claim of stability or a positive utility.
        record = {**record, "energy_above_hull_ev_atom": hull}
        stability = _stability_assessment(hull)
        electronic = record.get("dielectric_electronic")
        nsites = record.get("nsites")
        density = record.get("density_g_cm3")
        bulk = record.get("bulk_modulus_gpa")
        shear = record.get("shear_modulus_gpa")
        evidence_fields = (
            "band_gap_ev",
            "dielectric_total",
            "dielectric_electronic",
            "energy_above_hull_ev_atom",
            "density_g_cm3",
            "bulk_modulus_gpa",
            "shear_modulus_gpa",
        )
        coverage = sum(
            record.get(field) is not None for field in evidence_fields
        ) / len(evidence_fields)
        components = {
            "stability": (
                max(0.0, 1.0 - hull / HULL_ANCHOR_EV_ATOM) if hull is not None else 0.0
            ),
            "band_gap": min(1.0, gap / GAP_ANCHOR_EV) if gap is not None else 0.0,
            "element_screen": 0.0 if matches else 1.0,
            "simplicity": 1.0 / max(1, len(record["elements"]) - 1),
            "evidence_quality": coverage,
            "dielectric_total": (
                min(1.0, dielectric / TOTAL_DIELECTRIC_ANCHOR)
                if dielectric is not None
                else 0.0
            ),
            "dielectric_electronic": (
                min(1.0, electronic / ELECTRONIC_DIELECTRIC_ANCHOR)
                if electronic is not None
                else 0.0
            ),
            "nsites": 1.0 / nsites if nsites is not None else 0.0,
            "density": 1.0 / (1.0 + density / 10.0) if density is not None else 0.0,
            "bulk_modulus": min(1.0, bulk / 300.0) if bulk is not None else 0.0,
            "shear_modulus": min(1.0, shear / 200.0) if shear is not None else 0.0,
            "metallicity": float(record.get("is_metal") is True),
            "direct_gap": float(record.get("is_gap_direct") is True),
        }
        if target_band_gap_ev is not None and gap is not None:
            distance = abs(gap - target_band_gap_ev)
            # Compute as tolerance / hypot to avoid overflow for very small
            # valid tolerance scales. This is preference fit, never uncertainty.
            components["band_gap"] = (tolerance / math.hypot(tolerance, distance)) ** 2
        if high_k and dielectric is not None:
            components["dielectric_total"] = (
                min(
                    1.0,
                    math.log(dielectric / HIGH_K_REFERENCE)
                    / math.log(TOTAL_DIELECTRIC_ANCHOR / HIGH_K_REFERENCE),
                )
                if dielectric > HIGH_K_REFERENCE
                else 0.0
            )
        available = {
            key: key in SUPPORTED_CRITERIA
            and not (key == "evidence_quality" and coverage == 0)
            and not (key == "stability" and hull is None)
            and not (key == "dielectric_electronic" and electronic is None)
            and not (key == "nsites" and nsites is None)
            and not (key == "band_gap" and gap is None)
            and not (key == "dielectric_total" and dielectric is None)
            and not (key == "density" and density is None)
            and not (key == "bulk_modulus" and bulk is None)
            and not (key == "shear_modulus" and shear is None)
            and not (key == "metallicity" and record.get("is_metal") is None)
            and not (key == "direct_gap" and record.get("is_gap_direct") is None)
            for key in weights
        }
        evidence_available = dict(available)
        for key in unscored_goals:
            components[key] = 0.0
            available[key] = False
        contributions = {
            key: weight * components.get(key, 0.0) for key, weight in weights.items()
        }
        missing_selected = [
            key for key, weight in weights.items() if weight > 0 and not available[key]
        ]
        missing_measurements = [
            key
            for key, weight in weights.items()
            if weight > 0 and not evidence_available[key]
        ]
        selected_coverage = min(
            1.0,
            max(
                0.0,
                math.fsum(weight for key, weight in weights.items() if available[key]),
            ),
        )
        if selected_coverage <= 0:
            excluded.append(
                {
                    "material_id": material_id,
                    "formula": record["formula"],
                    "reasons": [
                        (
                            "No positively weighted criterion has both usable source "
                            "evidence and a supported requested utility; no overall "
                            "utility is assigned."
                            if unscored_goals
                            else "No positively weighted criterion has usable source "
                            "evidence; no overall utility is assigned."
                        )
                    ],
                    **(
                        {"unscored_goal_reasons": deepcopy(unscored_goals)}
                        if unscored_goals
                        else {}
                    ),
                    "provenance": deepcopy(record.get("provenance", {})),
                    "evidence_comparison": deepcopy(record["evidence_comparison"]),
                }
            )
            continue
        missing = [name for name in evidence_fields if record.get(name) is None]
        missing.extend(
            [
                "ambient_phase_stability",
                "operational_stability",
                "compound_hazard_assessment",
                "thin_film_performance",
            ]
        )
        caveats = [
            stability["thermodynamic"]["interpretation"],
            stability["ambient_phase"]["reason"],
            stability["operational"]["reason"],
        ]
        if raw_hull is not None and hull is None:
            caveats.append("Invalid source hull energy was treated as unknown.")
        if record.get("potential_ferroelectric") is True:
            caveats.append(
                "Dataset flags potential ferroelectricity; "
                "check phase/lattice response."
            )
        if record["evidence_comparison"]["evidence_method"] == "experimental":
            caveats.append(
                "Experimental observation applies to its reported sample, phase "
                "and measurement conditions; it is not universal material performance."
            )
        elif record["source_mode"] not in {"public_snapshot", "live_public_dielectric"}:
            caveats.append(
                "Exact task-level calculation methodology remains unresolved."
            )
        if missing_selected:
            caveats.append(
                "Unscored selected criteria: " + ", ".join(missing_selected) + "."
            )
        for key, reason in unscored_goals.items():
            caveats.append(f"Unscored requested goal ({key}): {reason}")
        caveats.extend(record["issues"])
        supported_score = min(1.0, max(0.0, math.fsum(contributions.values())))
        missing_required = [key for key in required if not available.get(key)]
        # Fit and coverage answer different questions. Missing values still
        # contribute zero to the supported score; they are not evidence of poor
        # material performance. The upper score holds known utilities fixed.
        analysis = {
            "observed_fit": min(1.0, supported_score / selected_coverage),
            "coverage": selected_coverage,
            "possible_upper_score": min(1.0, supported_score + 1 - selected_coverage),
            "required_criteria": required,
            "missing_required_criteria": missing_required,
            "status": "needs_evidence" if missing_required else "comparable",
        }
        if missing_required:
            unsupported_required = [
                key for key in missing_required if key in unscored_goals
            ]
            absent_required = [
                key for key in missing_required if not evidence_available.get(key)
            ]
            caveats.append(
                (
                    "Application comparison needs supported requested utilities for "
                    + ", ".join(unsupported_required)
                    + (
                        " and source evidence for " + ", ".join(absent_required)
                        if absent_required
                        else ""
                    )
                    if unsupported_required
                    else "Application comparison needs source evidence for "
                    + ", ".join(missing_required)
                )
                + "; this row is an evidence-review lead, "
                "not a supported application recommendation."
            )
        eligible.append(
            {
                **record,
                "stability_assessment": stability,
                "score": round(supported_score, 8),
                "score_analysis": analysis,
                "score_components": {key: components.get(key, 0.0) for key in weights},
                "score_contributions": contributions,
                "criterion_available": available,
                "missing_selected_criteria": missing_selected,
                **(
                    {
                        "criterion_evidence_available": evidence_available,
                        "supported_field_completeness": coverage,
                        "missing_measurement_criteria": missing_measurements,
                        "unscored_goal_reasons": deepcopy(unscored_goals),
                    }
                    if reviewed_goals
                    else {}
                ),
                "selected_weight_coverage": selected_coverage,
                "missing_data": missing,
                "caveats": caveats,
                "element_screen": {
                    "preset_matches": matches,
                    "hazard_assessment": "unassessed",
                },
            }
        )
    eligible.sort(
        key=lambda row: (
            row["score_analysis"]["status"] != "comparable",
            -row["score"],
            row["material_id"],
        )
    )
    shortlist, selected_formulas, alternatives = [], set(), []
    for row in eligible:
        composition = composition_key(row["formula"])
        if composition in selected_formulas:
            alternatives.append(row["material_id"])
            continue
        if len(shortlist) < SHORTLIST_SIZE:
            selected_formulas.add(composition)
            shortlist.append({**row, "rank": len(shortlist) + 1})
    unavailable = [
        key
        for key, weight in weights.items()
        if weight > 0 and not any(row["criterion_available"][key] for row in eligible)
    ]
    return shortlist, {
        "algorithm": (
            "public-materials-utility-v9"
            if reviewed_goals
            else "public-materials-utility-v8"
        ),
        **({"goal_review": reviewed_goals} if reviewed_goals else {}),
        **comparison_audit,
        "application": application,
        "required_comparison_criteria": required,
        "raw_importance": raw_importance,
        "weights": weights,
        "supported_criteria": sorted(SUPPORTED_CRITERIA),
        "screening_preferences": {
            "minimum_band_gap_ev": minimum_band_gap_ev,
            "minimum_band_gap_active": minimum_band_gap_ev is not None
            and band_gap_active,
            "target_band_gap_ev": target_band_gap_ev,
            "target_band_gap_active": target_band_gap_ev is not None
            and band_gap_active,
            "band_gap_tolerance_ev": (
                tolerance if target_band_gap_ev is not None else None
            ),
            "band_gap_tolerance_origin": (
                (
                    "provided_preference"
                    if band_gap_tolerance_ev is not None
                    else "application_default"
                )
                if target_band_gap_ev is not None
                else None
            ),
            "target_interpretation": "Target and tolerance are preferences. "
            "Tolerance is the gap distance at half utility, not a measured "
            "uncertainty or a hard acceptance range.",
            "unknown_band_gap": "Retained as missing evidence, never treated as "
            "meeting or failing the minimum or target.",
        },
        "unavailable_selected_criteria": unavailable,
        "stability_policy": {
            "version": "scoped-stability-v1",
            "thermodynamic": "Only validated source hull energy affects the "
            "thermodynamic stability utility; positive energy lowers that utility.",
            "ambient_phase": "Unknown until an approved adapter verifies the "
            "same material and phase under explicit room-temperature conditions.",
            "operational": "Unknown until an approved adapter verifies the "
            "same material and relevant operating conditions and duration.",
            "negative_studies": "Public passages remain attributed review leads. "
            "They cannot change scores until an approved adapter validates "
            "material identity, phase, conditions and the reported observation.",
            "unknown": "Unknown is not stable. Missing stability evidence "
            "contributes zero without declaring the material unstable.",
        },
        "normalization": {
            "stability": (
                f"max(0, 1 - energy_above_hull / {HULL_ANCHOR_EV_ATOM} eV/atom); "
                "unknown -> 0"
            ),
            "ambient_phase_stability": "No reviewed quantitative mapping; "
            "unavailable evidence contributes zero, not a stability claim.",
            "operational_stability": "No reviewed quantitative mapping; "
            "unavailable evidence contributes zero, not a stability claim.",
            "band_gap": (
                "1 / (1 + (abs(source band gap - "
                f"{target_band_gap_ev:g} eV) / {tolerance:g} eV)^2); "
                "target preference fit; unknown -> 0"
                if target_band_gap_ev is not None
                else f"min(1, band_gap / {GAP_ANCHOR_EV} eV)"
            ),
            "element_screen": (
                "1 for no preset match; matching records are excluded only when "
                "element screening has positive selected importance"
            ),
            "simplicity": "1 / max(1, distinct source-formula elements - 1)",
            "evidence_quality": (
                "Present fraction of supported gap, dielectric, hull, density, "
                "and elastic scalars; data completeness, not confidence"
            ),
            "dielectric_total": (
                f"clip(log(total dielectric / {HIGH_K_REFERENCE}) / "
                f"log({TOTAL_DIELECTRIC_ANCHOR} / {HIGH_K_REFERENCE}), 0, 1); "
                "values at or below the screening reference receive zero utility"
                if high_k
                else f"min(1, total dielectric / {TOTAL_DIELECTRIC_ANCHOR})"
            ),
            "dielectric_electronic": (
                f"min(1, electronic dielectric / {ELECTRONIC_DIELECTRIC_ANCHOR})"
            ),
            "nsites": "1 / source cell site count; not formula complexity",
            "density": "1 / (1 + density_g_cm3 / 10); preference for lower density",
            "bulk_modulus": (
                "min(1, bulk_modulus_gpa / 300); preference for higher stiffness"
            ),
            "shear_modulus": (
                "min(1, shear_modulus_gpa / 200); preference for higher stiffness"
            ),
            "metallicity": "1 if source reports metallic; 0 otherwise",
            "direct_gap": "1 if source reports a direct gap; 0 otherwise",
        },
        "anchor_status": (
            "Utility anchors and scores are application preferences/derivations, "
            "not measured properties or physical cutoffs."
        ),
        "unknown_treatment": (
            "Importance is normalized across all selected criteria, including "
            "unavailable ones. Missing values contribute zero; their weight is "
            "never redistributed to available criteria."
        ),
        "score_interpretation": (
            "Supported score = sum(weight * available utility). Fit on known criteria "
            "= supported score / selected importance coverage, shown separately and "
            "never used alone to promote sparse evidence. Possible upper score adds "
            "the missing weight, holding observed utilities fixed; this is not a "
            "confidence interval or predicted material performance."
        ),
        "score_eligibility": (
            "At least one positively weighted criterion requires usable source "
            "evidence. With none, the record receives no score or shortlist rank. "
            "A supported value with zero utility may still receive a score of zero."
        ),
        "score_scale": deepcopy(SCORE_SCALE),
        "tie_break": (
            "Records with the required comparison evidence first, then supported "
            "score descending, then source record ID lexicographically."
        ),
        "diversity": (
            "One phase per reduced elemental composition in the shortlist; "
            "no properties merged across phases."
        ),
        "excluded_element_preset": list(EXCLUDED_ELEMENTS),
        "excluded_element_preset_version": ELEMENT_PRESET_VERSION,
        "excluded_element_preset_status": (
            "Conservative application policy, incomplete; no compound toxicology claim."
        ),
        "eligible_records": len(eligible),
        "excluded_records": excluded,
        "alternative_phase_ids": alternatives,
        "shortlist_limit": SHORTLIST_SIZE,
        "scope": (
            "Validated records from the current bounded source query; no "
            "fixed material cohort."
        ),
    }
