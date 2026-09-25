"""Bounded findings prose from retained evidence and assessments.

Callers supply validated candidates, a rebound literature evaluation,
and the report's public citation references. This presentation layer
makes no new scientific assessment, identity join, ranking decision, or
model request.
"""

import math
import re

from labcat.science.evidence_comparison import (
    compare_observations,
    evidence_method,
)
from labcat.science.formula_display import display_formula

# Keep core report imports independent of the optional web preference API.
_LABELS = {
    "application_fit": "Application relevance",
    "demonstrated_use": "Demonstrated use",
    "stability": "Thermodynamic stability",
    "ambient_phase_stability": "Room-temperature phase stability",
    "operational_stability": "Operational stability",
    "band_gap": "Band gap",
    "dielectric_total": "Total dielectric response",
    "dielectric_electronic": "Electronic dielectric response",
    "density": "Density",
    "bulk_modulus": "Bulk modulus",
    "shear_modulus": "Shear modulus",
    "nsites": "Cell site count",
    "metallicity": "Metallic character",
    "direct_gap": "Direct band gap",
    "simplicity": "Composition simplicity",
    "evidence_quality": "Supported-field completeness",
    "element_screen": "Element screening",
}
_PROPERTIES = {
    "stability": ("energy above hull", "energy_above_hull_ev_atom", "eV/atom"),
    "band_gap": ("band gap", "band_gap_ev", "eV"),
    "dielectric_total": ("total dielectric scalar", "dielectric_total", ""),
    "dielectric_electronic": (
        "electronic dielectric scalar",
        "dielectric_electronic",
        "",
    ),
    "density": ("density", "density_g_cm3", "g/cm³"),
    "bulk_modulus": ("bulk modulus (VRH)", "bulk_modulus_gpa", "GPa"),
    "shear_modulus": ("shear modulus (VRH)", "shear_modulus_gpa", "GPa"),
    "nsites": ("cell site count", "nsites", ""),
    "metallicity": ("metallic character", "is_metal", ""),
    "direct_gap": ("direct band gap", "is_gap_direct", ""),
}
_ADVERSE_KEYS = {
    "application_fit",
    "stability",
    "ambient_phase_stability",
    "operational_stability",
}
_JUDGMENTS = {
    "supports": "support",
    "mixed": "mixed evidence",
    "concern": "concern",
    "unknown": "unresolved",
}


def _text(value, limit=240):
    text = " ".join(str(value).split()).replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _name(value):
    return _text(display_formula(_text(value, 160)), 160)


def _candidate_heading(kind, index, name):
    # Headings use the report renderer's small literal dialect. Keep the full
    # source name in the following paragraph, without interpreting its markup.
    title = " ".join(
        "".join(
            char if char.isalnum() or char in " .,/&()—–·-" else " "
            for char in _name(name)
        ).split()
    )
    prefix = f"{kind} {index}"
    return prefix + (f" — {title[: 95 - len(prefix)].rstrip()}" if title else "") + ":"


def _paragraphs(parts):
    lines = []
    for part in parts:
        if part:
            lines += [part, ""]
    return lines


def _label(key):
    return _text(_LABELS.get(key, str(key).replace("_", " ").capitalize()), 100)


def _join(items):
    return (
        ", ".join(items[:-1]) + " and " + items[-1]
        if len(items) > 1
        else "".join(items)
    )


def _refs(references):
    # The reference list is already public and report-scoped. Only identifiers
    # from its fixed citation dialect are allowed to become structural markers.
    by_url = {}
    for row in references:
        if re.fullmatch(r"[RS][1-9][0-9]*", str(row.get("id", ""))):
            by_url.setdefault(row["url"], row["id"])
    return by_url


def _cite(url, references):
    identifier = references.get(url)
    return f" [{identifier}]" if identifier else ""


def _literature_identity(row, references, leads):
    urls = [
        assessment.get("citation", assessment).get("url")
        for item in row["criteria"]
        for assessment in item["assessments"]
    ]
    urls += [
        item.get("url") for item in leads.get(row["lead_id"], {}).get("citations", [])
    ]
    citations = list(dict.fromkeys(_cite(url, references) for url in urls))
    return _name(row["name"]) + "".join(citations[:3])


def _source_excerpt(lead, references, *, retained=(), assessed=False):
    """Quote existing lead context without converting the mention into
    support."""
    for citation in lead.get("citations", []):
        reference = _cite(citation.get("url"), references)
        if reference and citation.get("quote"):
            quote = _text(citation["quote"], 480)
            if any(quote in paragraph for paragraph in retained):
                continue
            return (
                (
                    "Public-source context: "
                    if assessed
                    else "What the source describes (quoted context): "
                )
                + f"“{quote}”{reference}. "
                + (
                    "Read this passage within its reported phase and conditions. "
                    if assessed
                    else "This is source context, not an assessed suitability finding. "
                )
            )
    return ""


def _tier(row):
    # A legacy evaluation has no tier. Preserve its order while ensuring an
    # adverse source assessment can never be described as a favorable finding.
    return max(
        [row.get("priority_tier", 0)]
        + [
            {"concern": 2, "mixed": 1}.get(assessment["judgment"], 0)
            for item in row["criteria"]
            if item["criterion_id"] in _ADVERSE_KEYS
            for assessment in item["assessments"]
        ]
    )


def _supports(row):
    return [item for item in row["criteria"] if item["judgment"] == "supports"]


def _literature_opening(evaluation, references, leads):
    rows = evaluation["ranked_candidates"] or evaluation["unranked_candidates"]
    if not rows:
        return []
    first = rows[0]
    identity = _literature_identity(first, references, leads)
    supported = _supports(first)
    if _tier(first):
        state = (
            "reported application or stability concerns"
            if _tier(first) == 2
            else "mixed evidence"
        )
        text = (
            f"{identity} appears first in the literature order but has {state}. "
            "Resolve those assessments before advancing it; its position does not "
            "establish a preferred material."
        )
    elif supported:
        reasons = _join(
            [_label(item["criterion_id"]).lower() for item in supported[:2]]
        )
        text = (
            f"Start the literature review with {identity}: source-based "
            f"assessments support {reasons} under the selected goals. This is a "
            "conditional review recommendation, not verified application performance."
        )
    else:
        text = (
            f"{identity} is a starting point for source review, with no favorable "
            "criterion assessment establishing suitability. The retained order "
            "does not justify choosing it over the other unassessed leads."
        )
    if len(rows) > 1:
        other = rows[1]
        alternate = _literature_identity(other, references, leads)
        if first.get("rank") is not None and other.get("rank") == first["rank"]:
            text += (
                f" {alternate} shares its rank; the assessment does not "
                "distinguish a winner."
            )
        elif _tier(other):
            text += (
                f" {alternate}, next in the retained order, also needs its "
                "adverse or mixed assessments resolved."
            )
        elif _supports(other):
            text += f" {alternate} is the next-listed alternative for review."
        else:
            text += (
                f" {alternate} remains an unassessed alternative, "
                "not a supported substitute."
            )
    return [text]


def _assessment(item, references, *, audit):
    assessments = sorted(
        item["assessments"],
        key=lambda row: {"concern": 0, "mixed": 1, "unknown": 2, "supports": 3}[
            row["judgment"]
        ],
    )
    # Retain both sides of mixed evidence when they were assessed separately.
    selected = assessments[:1]
    if audit and item["judgment"] == "mixed":
        selected += [row for row in assessments if row["judgment"] == "supports"][:1]
    parts = []
    for row in selected:
        reference = _cite(row.get("citation", row).get("url"), references)
        if not reference:
            continue
        parts.append(
            f"{_JUDGMENTS[row['judgment']]} — "
            f"“{_text(row['interpretation'], 200)}”{reference}"
        )
    return f"{_label(item['criterion_id'])}: " + "; ".join(parts) if parts else ""


def _goal_description(definition):
    goal = definition.get("goal", {})
    relation = goal.get("relation")
    if relation == "target" and _number(goal.get("target_band_gap_ev")) is not None:
        return f"target {goal['target_band_gap_ev']:g} eV"
    return {"maximize": "maximize", "minimize": "minimize"}.get(relation, "")


def _literature_influence(row, definitions):
    """Explain the retained preferences without treating them as
    observations."""
    selected = sorted(
        (
            item
            for item in row["criteria"]
            if definitions.get(item["criterion_id"], {}).get("weight", 0) > 0
        ),
        key=lambda item: (
            -definitions[item["criterion_id"]]["weight"],
            item["criterion_id"],
        ),
    )
    if not selected:
        return []
    lines = []
    for item in selected:
        definition = definitions[item["criterion_id"]]
        goal = _goal_description(definition)
        status = _JUDGMENTS[item["judgment"]]
        lines.append(
            f"Selected criterion for {_name(row['name'])}: "
            f"{_label(item['criterion_id'])} "
            f"carries {definition['weight']:.1%} of attribute importance"
            + (f" ({goal})" if goal else "")
            + f"; the retained assessment is {status}. "
            + (
                "This weight has no supported attribute finding to act on yet."
                if item["judgment"] == "unknown"
                else ""
            )
        )
    if row.get("ranking_basis") in {"preliminary", "attribute", "blended"}:
        coverage = row["coverage"]
        if coverage == 0:
            lines.append(
                f"For {_name(row['name'])}, the priority remains entirely preliminary: "
                "none of the selected attribute importance has an assessed finding. "
                "Changing an attribute weight cannot supply the missing observation."
            )
        else:
            lines.append(
                f"For {_name(row['name'])}, assessed attributes supply {coverage:.1%} "
                "of the final priority blend"
                + (
                    f", with the remaining {1 - coverage:.1%} supplied by "
                    "preliminary application evidence."
                    if coverage < 1
                    else "; the preliminary score has no remaining share."
                )
                + " These are preference weights, not confidence in the material."
            )
    return lines


def _criterion_citations(item, references):
    return "".join(
        dict.fromkeys(
            _cite(assessment.get("citation", assessment).get("url"), references)
            for assessment in item["assessments"]
        )
    )


def _contrast_strength(left, right, references):
    left_items = {item["criterion_id"]: item for item in left["criteria"]}
    return sum(
        item["criterion_id"] in left_items
        and item["judgment"] != "unknown"
        and left_items[item["criterion_id"]]["judgment"] != "unknown"
        and item["judgment"] != left_items[item["criterion_id"]]["judgment"]
        and bool(_criterion_citations(item, references))
        and bool(_criterion_citations(left_items[item["criterion_id"]], references))
        for item in right["criteria"]
    )


def _literature_comparisons(rows, definitions, references):
    """Bound the main discussion to two contrasts among the leading
    three."""
    rows = rows[:3]
    if len(rows) < 2:
        return []
    lines = ["Comparison of the leading candidates:", ""]
    compared_context = False
    for index, other in enumerate(rows[1:], 1):
        # Prefer an actual assessed contrast to repeatedly comparing every
        # alternative with an unknown first row. Equal contrast counts retain
        # the earlier source order; this never changes the shortlist itself.
        first = max(
            rows[:index], key=lambda row: _contrast_strength(row, other, references)
        )
        first_items = {item["criterion_id"]: item for item in first["criteria"]}
        contrasts, gaps, shared = [], [], []
        for right in other["criteria"]:
            key = right["criterion_id"]
            left = first_items.get(key)
            if not left:
                continue
            left_ref, right_ref = (
                _criterion_citations(item, references) for item in (left, right)
            )
            left_known = left["judgment"] != "unknown" and bool(left_ref)
            right_known = right["judgment"] != "unknown" and bool(right_ref)
            weight = definitions.get(key, {}).get("weight", 0)
            relevance = (key in _ADVERSE_KEYS, weight)
            if left_known and right_known:
                entry = (relevance, key, left, right, left_ref, right_ref)
                (contrasts if left["judgment"] != right["judgment"] else shared).append(
                    entry
                )
            elif left_known != right_known and (weight > 0 or key in _ADVERSE_KEYS):
                gaps.append((relevance, key, left, right, left_ref, right_ref))
        title = f"{_name(first['name'])} compared with {_name(other['name'])}: "
        parts = []
        for _, key, left, right, left_ref, right_ref in sorted(
            contrasts, reverse=True, key=lambda entry: (entry[0], entry[1])
        )[:2]:
            parts.append(
                f"{_label(key)} has {_JUDGMENTS[left['judgment']]} for "
                f"{_name(first['name'])}{left_ref}, "
                + f"versus {_JUDGMENTS[right['judgment']]} for "
                f"{_name(other['name'])}{right_ref}."
            )
        if gaps:
            _, key, left, right, left_ref, right_ref = max(
                gaps, key=lambda entry: (entry[0], entry[1])
            )
            supported, unresolved = (
                (first, other)
                if left["judgment"] != "unknown" and left_ref
                else (other, first)
            )
            item, reference = (
                (left, left_ref) if supported is first else (right, right_ref)
            )
            parts.append(
                f"{_label(key)} has {_JUDGMENTS[item['judgment']]} for "
                f"{_name(supported['name'])}{reference}, "
                f"but remains unresolved for {_name(unresolved['name'])}; "
                "this is an evidence gap, not a measured inferiority."
            )
        if not parts and shared:
            _, key, left, _, left_ref, right_ref = max(
                shared, key=lambda entry: (entry[0], entry[1])
            )
            parts.append(
                f"Both have {_JUDGMENTS[left['judgment']]} for {_label(key).lower()}"
                f"{left_ref}{right_ref}; that shared qualitative assessment "
                "alone does not distinguish their performance."
            )
        if not parts:
            parts.append(
                "No shared, cited criterion assessment distinguishes these "
                "candidates; their order cannot establish a scientific preference."
            )
        if first.get("rank") is not None and first.get("rank") == other.get("rank"):
            parts.append(
                "They share the saved rank, so no winner is established by the ranking."
            )
        if _tier(first) != _tier(other):
            parts.append(
                "Their application/stability concern tiers differ; favorable "
                "attribute fit cannot cancel the retained adverse or mixed assessment."
            )
        if contrasts:
            compared_context = True
        lines += _paragraphs([title + " ".join(parts)])
    if compared_context:
        lines += _paragraphs(
            [
                "The cited phases, samples and conditions are not established as "
                "matching; these comparisons describe retained assessments, "
                "not measured differences in performance."
            ]
        )
    return lines


def _literature_candidate_lines(row, index, definitions, references, leads):
    known = [item for item in row["criteria"] if item["judgment"] != "unknown"]
    lines = [
        _candidate_heading("Candidate", index, row["name"]),
        "",
        _literature_identity(row, references, leads) + ".",
        "",
    ]
    for item in sorted(
        known,
        key=lambda item: (
            item["criterion_id"] not in _ADVERSE_KEYS,
            -definitions.get(item["criterion_id"], {}).get("weight", 0),
        ),
    ):
        assessment = _assessment(item, references, audit=True)
        if assessment:
            lines += _paragraphs([assessment + "."])
    if known:
        lines += _paragraphs(
            [
                _source_excerpt(
                    leads.get(row["lead_id"], {}),
                    references,
                    retained=lines,
                    assessed=True,
                ).rstrip()
            ]
        )
    if not known:
        lines += _paragraphs(
            [
                _source_excerpt(leads.get(row["lead_id"], {}), references),
                "Application relevance and selected attribute fit remain unresolved.",
            ]
        )
    unknown = [
        _label(item["criterion_id"])
        for item in row["criteria"]
        if item["judgment"] == "unknown"
        and definitions.get(item["criterion_id"], {}).get("weight", 0) > 0
    ]
    gaps = []
    if unknown:
        gaps.append(
            "What still needs checking: "
            + _join(unknown)
            + " for the relevant phase and conditions."
        )
    elif row.get("coverage", 0) > 0:
        gaps.append(
            "Verify that the selected attribute assessments apply to the "
            "intended phase and conditions."
        )
    if row.get("stability_unknown"):
        gaps.append("Stability remains incompletely assessed.")
    if any(item["judgment"] in {"concern", "mixed"} for item in known):
        gaps.append("Resolve the mixed or adverse assessments before advancing.")
    lines += _paragraphs([" ".join(gaps)])
    return lines


def _literature_discussion(evaluation, references, leads, *, audit):
    rows = (
        evaluation["ranked_candidates"] + evaluation["unranked_candidates"]
        if audit
        else evaluation["ranked_candidates"] or evaluation["unranked_candidates"]
    )
    definitions = {row["criterion_id"]: row for row in evaluation["criteria"]}
    selected = rows if audit else rows[:2]
    adverse = next((row for row in rows[len(selected) :] if _tier(row)), None)
    if adverse is not None:
        selected = [*selected, adverse]
    lines = []
    for index, row in enumerate(selected, 1):
        if audit:
            lines += _literature_candidate_lines(
                row, index, definitions, references, leads
            )
            continue
        identity = _literature_identity(row, references, leads)
        known = [item for item in row["criteria"] if item["judgment"] != "unknown"]
        adverse = [item for item in known if item["judgment"] in {"concern", "mixed"}]
        favorable = [item for item in known if item["judgment"] == "supports"]
        text = f"- {identity}. "
        for prefix, items in (
            ("Why consider it: source-based assessments of ", favorable),
            ("Main tradeoff: source-based assessments of ", adverse),
        ):
            reasons = [
                _assessment(item, references, audit=audit)
                for item in (items if audit else items[:1])
            ]
            if any(reasons):
                text += prefix + "; ".join(filter(None, reasons)) + ". "
        if not known:
            text += _source_excerpt(leads.get(row["lead_id"], {}), references)
            text += (
                "Application relevance and selected attribute fit remain unresolved. "
            )
        unknown = [
            _label(item["criterion_id"])
            for item in row["criteria"]
            if item["judgment"] == "unknown"
            and definitions.get(item["criterion_id"], {}).get("weight", 0) > 0
        ]
        if unknown:
            text += (
                "What still needs checking: "
                + _join(
                    unknown[:3]
                    + (
                        [f"{len(unknown) - 3} other selected criteria"]
                        if len(unknown) > 3
                        else []
                    )
                )
                + " for the relevant phase and conditions. "
            )
        elif row.get("coverage", 0) > 0:
            text += (
                "Selected attribute assessments are available; verify their "
                "applicability to the intended conditions. "
            )
        if row.get("stability_unknown"):
            text += "Stability remains incompletely assessed. "
        if adverse:
            text += (
                "Favorable passages do not cancel mixed or adverse assessments. "
                if favorable
                else "Resolve the mixed or adverse assessments before advancing. "
            )
        lines.append(text.rstrip())
    if audit:
        lines += _literature_comparisons(selected, definitions, references)
    else:
        comparison = _literature_tradeoff(selected, references)
        if comparison:
            lines.append(comparison)
    if any(item["judgment"] == "mixed" for row in selected for item in row["criteria"]):
        lines.append(
            "For mixed assessments, compare the cited phase, sample and "
            "operating conditions "
            "before treating the passages as a direct contradiction. The retained "
            "interpretations do not establish that those conditions match."
        )
    return lines


def _literature_tradeoff(rows, references):
    """Compare only assessments already scoped to each candidate and
    criterion."""
    if len(rows) < 2:
        return ""
    first = rows[0]
    first_criteria = {item["criterion_id"]: item for item in first["criteria"]}
    for other in rows[1:]:
        for right in other["criteria"]:
            left = first_criteria.get(right["criterion_id"])
            if not left or {left["judgment"], right["judgment"]} not in (
                {"supports", "mixed"},
                {"supports", "concern"},
            ):
                continue
            identities = []
            for candidate, item in ((first, left), (other, right)):
                citations = list(
                    dict.fromkeys(
                        _cite(
                            assessment.get("citation", assessment).get("url"),
                            references,
                        )
                        for assessment in item["assessments"]
                    )
                )
                if not any(citations):
                    break
                identities.append(_name(candidate["name"]) + "".join(citations[:2]))
            if len(identities) != 2:
                continue
            return (
                f"One assessed tradeoff between {identities[0]} and "
                f"{identities[1]} is {_label(left['criterion_id']).lower()}: "
                f"the first has {_JUDGMENTS[left['judgment']]} in its assessments, "
                f"while the second has {_JUDGMENTS[right['judgment']]}. "
                "Use that difference to focus the next review; the cited phases "
                "and conditions still need matching before "
                "a direct material comparison."
            )
    return ""


def _number(value):
    if type(value) is bool:
        return "yes" if value else "no"
    return (
        f"{value:g}" if type(value) in {int, float} and math.isfinite(value) else None
    )


def _property(row, key):
    if key in _PROPERTIES:
        label, field, unit = _PROPERTIES[key]
        value = _number(row.get(field))
        return f"{label} {value}{(' ' + unit) if unit else ''}" if value else ""
    if key == "simplicity":
        return (
            f"{len(row.get('elements', []))} source-formula elements "
            "(composition simplicity)"
        )
    if key == "evidence_quality":
        value = row.get("score_components", {}).get(key)
        return (
            f"supported-field completeness {value:.0%} (derived)"
            if value is not None
            else ""
        )
    if key == "element_screen":
        return "no preset element-exclusion match (compound safety unassessed)"
    return ""


def _material_identity(row, references):
    return _name(row["formula"]) + _cite(
        row.get("provenance", {}).get("source_url"), references
    )


def _drivers(row):
    return sorted(
        (key for key, value in row["score_contributions"].items() if value > 0),
        key=lambda key: (-row["score_contributions"][key], key),
    )


def _required_gaps(row, result):
    analysis = row.get("score_analysis")
    if analysis is not None:
        return analysis["missing_required_criteria"]
    for view in ("technical", "summary"):
        for item in result.get("report_tables", {}).get(view, {}).get("rows", []):
            if item.get("material_id") == row["material_id"]:
                return item.get("score_analysis", {}).get(
                    "missing_required_criteria", []
                )
    return []


def _measured_opening(result, references):
    rows = result["candidates"]
    row = rows[0]
    identity = _material_identity(row, references)
    drivers = list(filter(None, (_property(row, key) for key in _drivers(row)[:2])))
    if _required_gaps(row, result):
        text = (
            f"{identity} leads the retained property order, but still needs "
            + _join([_label(key) for key in _required_gaps(row, result)])
            + " before it can support an application recommendation."
        )
    else:
        text = (
            f"Review {identity} first within the retained property shortlist "
            "under the selected preferences."
        )
    if drivers:
        text += " Its largest score contributions come from " + _join(drivers) + "."
    else:
        text += (
            " No selected criterion contributes positive utility, so first place "
            "alone is not a favorable performance finding."
        )
    if len(rows) > 1:
        other = rows[1]
        tied = row["score"] == other["score"] and bool(
            _required_gaps(row, result)
        ) == bool(_required_gaps(other, result))
        text += f" {_material_identity(other, references)} " + (
            "shares the leading score; that tie does not establish "
            "a scientific preference."
            if tied
            else "is the next-listed alternative; compare its evidence coverage "
            "before choosing between them."
        )
    return [text]


def _comparison_notes(row, result, references, *, audit=False):
    records = {
        item["material_id"]: item
        for item in [
            *result.get("candidates", []),
            *result.get("comparison_records", []),
        ]
    }
    notes = []
    comparable = False
    for pair in row.get("evidence_comparison", {}).get("comparisons", []):
        experiment = records.get(pair.get("experimental", {}).get("material_id"))
        calculation = records.get(pair.get("computed", {}).get("material_id"))
        if (
            not experiment
            or not calculation
            or row["material_id"]
            not in {experiment["material_id"], calculation["material_id"]}
        ):
            continue
        verified = compare_observations(experiment, calculation)
        if pair != verified:
            raise ValueError(
                "Narrative comparison disagrees with retained observations."
            )
        if pair["status"] != "comparable":
            note = (
                "The retained experiment and calculation lack matching source "
                "context; their values cannot be substituted or treated as "
                "a direct discrepancy."
            )
            if note not in notes:
                notes.append(note)
            if not audit:
                return [note]
            continue
        if row["material_id"] != experiment["material_id"]:
            raise ValueError(
                "Narrative recommendation must retain the matched experimental record."
            )
        experiment_ref = _cite(experiment["provenance"]["source_url"], references)
        calculation_ref = _cite(calculation["provenance"]["source_url"], references)
        if not experiment_ref or not calculation_ref:
            continue
        note = (
            "The retained experimental band gap is "
            f"{experiment['band_gap_ev']:g} eV{experiment_ref}; "
            "the matched computed value is "
            f"{calculation['band_gap_ev']:g} eV{calculation_ref}. "
            "The computed value differs by "
            f"{pair['delta_computed_minus_experimental']:+g} eV "
            "under the matching source context."
        )
        comparable = True
        if note not in notes:
            notes.append(note)
        if not audit:
            break
    if comparable:
        notes.append(
            "Keep the experimental record as the screening basis; "
            "this comparison does not establish agreement in other properties."
        )
    return notes


def _stability_note(row):
    labels = {
        "thermodynamic": "Thermodynamic stability",
        "ambient_phase": "Ambient phase stability",
        "operational": "Operational stability",
    }
    assessments = row.get("stability_assessment", {})
    parts, unknown = [], []
    for key, label in labels.items():
        item = assessments.get(key, {})
        status = item.get("status", "unknown")
        if key == "thermodynamic" and row.get("energy_above_hull_ev_atom") is not None:
            status = item.get("status", "available")
        if status == "unknown":
            unknown.append(label.lower())
        elif item.get("interpretation") or item.get("reason"):
            text = _text(item.get("interpretation") or item["reason"])
            parts.append(f"{label} assessment ({_text(status, 40)}): “{text}”.")
        else:
            parts.append(f"{label} assessment: {_text(status, 40)}.")
    if unknown:
        parts.append("What still needs checking: " + _join(unknown) + ".")
    return " ".join(parts)


def _measured_context(row, references):
    """Use adapter-scoped fields, never infer common conditions from
    formula."""
    details = []
    if row.get("phase"):
        details.append(f"reported phase/crystal system “{_text(row['phase'], 100)}”")
    if row.get("band_gap_kind"):
        details.append(f"gap type “{_text(row['band_gap_kind'], 120)}”")
    if row.get("source_mode") == "live_hybrid3":
        raw = row.get("provenance", {}).get("raw_fields", {})
        if raw.get("subset_label"):
            details.append(f"source phase label “{_text(raw['subset_label'], 100)}”")
        if raw.get("sample_type"):
            details.append(f"sample “{_text(raw['sample_type'], 100)}”")
        conditions = []
        for condition in raw.get("conditions", []):
            value = _number(condition.get("value"))
            if (
                value is not None
                and condition.get("property")
                and condition.get("unit")
            ):
                conditions.append(
                    f"{_text(condition['property'], 80)} {value} "
                    f"{_text(condition['unit'], 40)}"
                )
        if conditions:
            details.append("reported conditions " + _join(conditions))
    if not details:
        return ""
    return (
        f"Evidence scope for {_material_identity(row, references)}: "
        + "; ".join(details)
        + ". These observations apply to this source record; they do not establish "
        "the behavior of every phase or processing route of the composition."
    )


def _measured_influence(row, result, references):
    weights = result.get("ranking", {}).get("weights", {})
    available = row.get("criterion_available", {})
    lines = []
    for key in sorted(weights, key=lambda key: (-weights[key], key)):
        if (
            weights[key] <= 0
            or not available.get(key)
            or key not in row["score_contributions"]
        ):
            continue
        observation = _property(row, key)
        if not observation:
            continue
        lines.append(
            f"Criterion contribution for {_material_identity(row, references)}: "
            f"{_label(key)} has {weights[key]:.1%} of selected importance. "
            + (
                f"The source value is {observation}; "
                if key in _PROPERTIES
                else f"the derived screening feature is {observation}; "
            )
            + f"its saved contribution is {row['score_contributions'][key]:.4f} "
            "on the 0–1 utility scale. "
            + (
                "A zero contribution here comes from the assessed utility, "
                "not a missing observation."
                if row["score_contributions"][key] == 0
                else ""
            )
        )
    if (
        weights.get("band_gap", 0) > 0
        and row.get("band_gap_ev") is not None
        and result.get("ranking", {})
        .get("screening_preferences", {})
        .get("target_band_gap_active")
    ):
        preference = result["ranking"]["screening_preferences"]
        lines.append(
            f"For {_name(row['formula'])}, band-gap utility is evaluated against "
            f"the selected target of {preference['target_band_gap_ev']:g} eV, "
            "with a preference tolerance of "
            f"{preference['band_gap_tolerance_ev']:g} eV. "
            "A larger gap is therefore not automatically preferred; this tolerance "
            "is not an experimental uncertainty."
        )
    return lines


def _measured_comparisons(result, references):
    rows = result["candidates"][:3]
    if len(rows) < 2:
        return []
    weights = result.get("ranking", {}).get("weights", {})
    first = rows[0]
    lines = ["Comparison of the leading property records:", ""]
    compared_observations = False
    for other in rows[1:]:
        differences, shared, gaps = [], [], []
        for key, weight in weights.items():
            if weight <= 0:
                continue
            left_available, right_available = (
                candidate.get("criterion_available", {}).get(key, False)
                for candidate in (first, other)
            )
            if (
                left_available
                and right_available
                and all(
                    key in candidate["score_contributions"]
                    for candidate in (first, other)
                )
            ):
                delta = (
                    first["score_contributions"][key]
                    - other["score_contributions"][key]
                )
                (differences if delta else shared).append((abs(delta), key))
            elif left_available != right_available:
                gaps.append(
                    (
                        weight,
                        key,
                        first if left_available else other,
                        other if left_available else first,
                    )
                )
        parts = []
        for _, key in sorted(differences, reverse=True)[:2]:
            left_value, right_value = (
                _property(candidate, key) for candidate in (first, other)
            )
            if not left_value or not right_value:
                continue
            parts.append(
                f"{_label(key)}: "
                f"{_material_identity(first, references)} has {left_value}, "
                f"versus {right_value} for {_material_identity(other, references)}."
            )
        if gaps:
            _, key, observed, missing = max(
                gaps, key=lambda entry: (entry[0], entry[1])
            )
            parts.append(
                f"{_label(key)} is usable for "
                f"{_material_identity(observed, references)} "
                f"but unresolved for {_name(missing['formula'])}. "
                "The missing value is not a measured zero "
                "or evidence of inferior performance."
            )
        if not parts and shared:
            _, key = max(shared, key=lambda entry: (weights[entry[1]], entry[1]))
            parts.append(
                f"Their retained {_label(key).lower()} evidence has equal utility "
                "under the selected preferences; this criterion "
                "does not distinguish their screening utility."
            )
        if not parts:
            parts.append(
                "There is no common usable selected property supporting "
                "a direct comparison of screening utility."
            )
        if first["score"] == other["score"]:
            parts.append(
                "Their supported scores are tied; a display order alone "
                "does not establish a scientific preference."
            )
        if bool(_required_gaps(first, result)) != bool(_required_gaps(other, result)):
            parts.append(
                "Their required-evidence completeness differs, "
                "which takes precedence over score in the retained order."
            )
        if differences:
            compared_observations = True
        lines += _paragraphs(
            [
                f"{_material_identity(first, references)} compared with "
                f"{_material_identity(other, references)}: " + " ".join(parts)
            ]
        )
    if compared_observations:
        lines += _paragraphs(
            [
                "These are separate source observations, not measurements from "
                "a matched comparative experiment; method, phase and conditions "
                "still matter."
            ]
        )
    return lines


def _measured_discussion(result, references, *, audit, compare=True):
    lines = []
    rows = result["candidates"] if audit else result["candidates"][:2]
    for index, row in enumerate(rows, 1):
        method = evidence_method(row)
        description = {
            "experimental": "experimental source record",
            "computed": "computed source record",
            "unknown": "source record with unresolved method",
        }[method]
        keys = (
            [
                key
                for key, available in row.get("criterion_available", {}).items()
                if available
            ]
            if audit and "criterion_available" in row
            else _drivers(row)[:2]
        )
        properties = [_property(row, key) for key in keys if key in _PROPERTIES]
        derived = [_property(row, key) for key in keys if key not in _PROPERTIES]
        if audit:
            lines += [
                _candidate_heading("Property record", index, row["formula"]),
                "",
                f"{_material_identity(row, references)}.",
                "",
            ]
        text = (
            "" if audit else f"- {_material_identity(row, references)}. "
        ) + f"The {description} "
        text += (
            "reports " + _join(list(filter(None, properties))) + ". "
            if any(properties)
            else "does not supply a property driving the positive score. "
        )
        if any(derived):
            text += (
                "The ranking also favors " + _join(list(filter(None, derived))) + ". "
            )
        if audit:
            # The observations and the source conditions form separate readable
            # paragraphs; arithmetic belongs in the analysis appendix.
            lines += _paragraphs([text.rstrip(), _measured_context(row, references)])
            text = ""
        else:
            text += (
                f"Usable scoring evidence covers "
                f"{row['selected_weight_coverage']:.0%} "
                "of selected importance. "
            )
        missing = row.get(
            "missing_measurement_criteria", row.get("missing_selected_criteria", [])
        )
        if missing:
            text += (
                "Resolve missing "
                + _join([_label(key) for key in missing[:3]])
                + " evidence before interpreting the score as overall fit. "
            )
        unsupported = row.get("unscored_goal_reasons", {})
        if unsupported:
            text += (
                "The requested scoring rule is unsupported for "
                + _join([_label(key) for key in list(unsupported)[:3]])
                + ". "
            )
        stability = _stability_note(row)
        comparison = _comparison_notes(row, result, references, audit=audit)
        if audit:
            lines += _paragraphs([text.rstrip(), stability, *comparison])
        else:
            text += stability + " " + " ".join(comparison)
            lines.append(text.rstrip())
        if audit and not comparison:
            lines += _paragraphs(
                [
                    "Check the reported phase and conditions against the intended "
                    "application before advancing this record."
                ]
            )
    if audit and compare:
        lines += _measured_comparisons(result, references)
    return lines


def narrative_audit_lines(result, literature, references) -> list[str]:
    """Retain score arithmetic separately from candidate-facing
    interpretation."""
    references = _refs(references)
    lines = []
    if literature:
        definitions = {row["criterion_id"]: row for row in literature["criteria"]}
        rows = literature["ranked_candidates"] + literature["unranked_candidates"]
        for index, row in enumerate(rows, 1):
            lines += [
                _candidate_heading("Candidate score", index, row["name"]),
                "",
            ]
            lines += _paragraphs(
                [
                    f"Qualitative assessments cover {row['coverage']:.0%} of "
                    "selected attribute importance; this is evidence coverage, "
                    "not a probability of success.",
                    *_literature_influence(row, definitions),
                ]
            )
    for index, row in enumerate(result.get("candidates", []), 1):
        lines += [
            _candidate_heading("Property record score", index, row["formula"]),
            "",
        ]
        lines += _paragraphs(
            [
                f"Usable scoring evidence covers "
                f"{row['selected_weight_coverage']:.0%} of selected importance.",
                *_measured_influence(row, result, references),
            ]
        )
    return ["Candidate scoring details:", "", *lines] if lines else []


def findings_lines(result, literature, references, *, audit=False) -> list[str]:
    """Return two split-able findings/discussion sections without
    changing inputs.

    ``literature`` is ``validated_literature_evaluation(...)`` or
    ``None``; ``references`` is ``citation_references(result,
    sources)``. Existing report validation remains authoritative for
    record provenance and saved scoring.
    """
    references = _refs(references)
    leads = {row["id"]: row for row in result.get("candidate_leads", [])}
    opening, discussion = [], []
    if literature:
        opening += _literature_opening(literature, references, leads)
        discussion += _literature_discussion(literature, references, leads, audit=audit)
    if result.get("candidates"):
        if not literature:
            opening += _measured_opening(result, references)
            discussion += _measured_discussion(result, references, audit=audit)
        elif audit:
            discussion += [
                "Supporting property evidence:",
                "",
                "These records retain their source-specific identity, phase and "
                "conditions. They require a validated match before supporting "
                "a material or structure in the literature shortlist.",
                "",
                *_measured_discussion(result, references, audit=True, compare=False),
            ]
    if not opening:
        cited = []
        contexts = []
        for lead in list(leads.values())[: 3 if audit else 2]:
            citations = list(
                dict.fromkeys(
                    _cite(item.get("url"), references)
                    for item in lead.get("citations", [])
                )
            )
            if any(citations):
                cited.append(_name(lead["name"]) + "".join(citations[:2]))
                excerpt = _source_excerpt(lead, references)
                if excerpt:
                    contexts.append(f"- {_name(lead['name'])}. {excerpt.rstrip()}")
        opening = [
            (
                "The public passages identify "
                + _join(cited)
                + " as leads for review. "
                "Their mention alone does not establish application suitability "
                "or a preferred candidate."
                if cited
                else "The retained evidence does not yet establish "
                "a preferred material. "
                "The next useful decision is which candidate has source evidence "
                "for the properties and conditions required by the application."
            )
        ]
        discussion = [
            *contexts,
            "Review the cited candidate passages for an actual demonstration "
            "of the intended use, then establish the selected properties and "
            "stability of the relevant phase under the intended conditions. "
            "Keep unsupported attributes unresolved until those observations "
            "are available; source counts and material mentions "
            "cannot decide suitability.",
        ]
    return [
        "Findings and recommendations:",
        "",
        *opening,
        "",
        "Interpretation and tradeoffs:",
        "",
        *discussion,
    ]
