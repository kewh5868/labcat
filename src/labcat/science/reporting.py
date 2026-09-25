"""Written reports compiled from validated evidence, never model or
prompt prose.

The text contract is deliberately small: paragraphs, ``Heading:`` lines,
bullets, and pipe tables with a separator row. The web and document
renderers interpret only this structure; cells contain plain text, not
HTML or executable Markdown.
"""

import hashlib
import math
import re
from copy import deepcopy
from html import unescape
from urllib.parse import urlsplit

from labcat.config import AppConfig
from labcat.science.evidence_comparison import (
    compare_observations,
    evidence_method,
    experimental_range_from_records,
)
from labcat.science.formula_display import display_formula
from labcat.science.ranking import (
    SCORE_SCALE,
    SUPPORTED_CRITERIA,
    reviewed_goal_preferences,
    score_band,
    score_color,
)
from labcat.science.rebuild_snapshot import canonical
from labcat.science.report_narrative import findings_lines, narrative_audit_lines
from labcat.science.report_properties import (
    grouped_explicit_property_ids,
    selected_property_ids,
)
from labcat.science.report_sources import report_scoped_sources

CRITERIA = {
    "stability": ("Thermodynamic stability", "energy_above_hull_ev_atom", "eV/atom"),
    "band_gap": ("Band gap", "band_gap_ev", "eV"),
    "dielectric_total": ("Total dielectric scalar", "dielectric_total", ""),
    "dielectric_electronic": (
        "Electronic dielectric scalar",
        "dielectric_electronic",
        "",
    ),
    "density": ("Density", "density_g_cm3", "g/cm³"),
    "bulk_modulus": ("Bulk modulus (VRH)", "bulk_modulus_gpa", "GPa"),
    "shear_modulus": ("Shear modulus (VRH)", "shear_modulus_gpa", "GPa"),
    "nsites": ("Cell site count", "nsites", ""),
    "metallicity": ("Metallic character", "is_metal", ""),
    "direct_gap": ("Direct band gap", "is_gap_direct", ""),
    "element_screen": ("Element screening", None, ""),
    "simplicity": ("Composition simplicity", None, ""),
    "evidence_quality": ("Supported-field completeness", None, ""),
}


PRESENTATION_VERSION = "report-presentation-v2"
_CITATION_HOSTS = {
    "materialsproject.org",
    "api.materialsproject.org",
    "docs.materialsproject.org",
    "www.nature.com",
    "datadryad.org",
    "api.figshare.com",
    "ndownloader.figshare.com",
    "materials.hybrid3.duke.edu",
    "nomad-lab.eu",
    "europepmc.org",
    "arxiv.org",
    "doi.org",
}


def approved_citation_url(value) -> bool:
    """Fixed public adapters only, with narrow paths for background
    providers."""
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.port not in {None, 443}
            or url.username
            or url.password
            or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
        ):
            return False
        if url.hostname in _CITATION_HOSTS:
            return True
        if url.query or url.fragment:
            return False
        if url.hostname == "openalex.org":
            return bool(re.fullmatch(r"/W[0-9]{1,15}", url.path))
        if url.hostname == "en.wikipedia.org" and url.path.startswith("/wiki/"):
            from labcat.extended_discovery import valid_wikipedia_url

            return valid_wikipedia_url(value)
        return False
    except (TypeError, ValueError, AttributeError):
        return False


def _public_source(source):
    return (
        isinstance(source, dict)
        and source.get("access_scope") == "public"
        and source.get("provenance_status") == "verified"
        and approved_citation_url(source.get("url"))
    )


def citation_references(result: dict, sources: list[dict]) -> list[dict]:
    """Readable citation labels bound to existing, approved public
    sources."""
    identities = {
        row["material_id"]: display_formula(row["formula"])
        for row in [
            *result.get("comparison_records", []),
            *result.get("review_records", []),
            *result.get("candidates", []),
        ]
    }
    references = _reference_map(sources)
    listed, seen = [], set()
    for source in sources:
        if not _public_source(source) or source.get("kind") == "discovery_reference":
            continue
        identifier = references.get(source.get("source_id"))
        if not identifier:
            continue
        seen.add(source["url"])
        title = (
            _text(identities[source.get("record_id")]) + " — public material record"
            if source.get("record_id") in identities
            else _citation_title(source.get("title", "Public source record"))
        )
        listed.append(
            {
                "id": identifier,
                "title": title,
                "url": source["url"],
                "source_name": _text(source.get("source_name", "Public source")),
                "kind": "material_evidence",
            }
        )
    discovery = sorted(
        (
            s
            for s in sources
            if _public_source(s) and s.get("kind") == "discovery_reference"
        ),
        key=lambda item: item["url"],
    )
    for source in discovery:
        if source["url"] in seen:
            continue
        seen.add(source["url"])
        listed.append(
            {
                "id": f"S{sum(s['kind'] == 'discovery_reference' for s in listed) + 1}",
                "title": _citation_title(source.get("title", "Public source record")),
                "url": source["url"],
                "source_name": _text(source.get("source_name", "Public source")),
                "kind": "discovery_reference",
            }
        )
    return listed


def _citation_title(value) -> str:
    """Remove inert publisher typography, leaving any other markup
    literal."""
    text = _text(value)
    for _ in range(2):
        text = unescape(text)
    return _text(re.sub(r"</?(?:sub|sup|i|b|em|strong)>", "", text, flags=re.I))


def _text(value) -> str:
    """Keep data on one structural line, including in source titles and
    cells."""
    return " ".join(str(value).split()).replace("|", "/")


def _label(criterion: str) -> str:
    return CRITERIA.get(
        criterion, (criterion.replace("_", " ").capitalize(), None, "")
    )[0]


def _number(value, unit="") -> str:
    if value is None:
        return "unknown"
    if type(value) is bool:
        return "yes" if value else "no"
    return f"{value:g}{(' ' + unit) if unit else ''}"


def _join(items: list[str]) -> str:
    if len(items) < 2:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    return [
        "| " + " | ".join(map(_text, headers)) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(map(_text, row)) + " |" for row in rows),
    ]


def _criteria(candidate: dict, *, limit: int | None = None) -> list[str]:
    positive = [
        key for key, value in candidate["score_contributions"].items() if value > 0
    ]
    positive.sort(key=lambda key: (-candidate["score_contributions"][key], key))
    return positive if limit is None else positive[:limit]


def _evidence(candidate: dict, criterion: str) -> str:
    label, field, unit = CRITERIA.get(criterion, (_label(criterion), None, ""))
    if field:
        # Stability utility uses a reported hull energy, not a claim of stability.
        if criterion == "stability":
            label = "Energy above hull"
        return f"{label}: {_number(candidate.get(field), unit)}"
    if criterion == "simplicity":
        return f"Composition: {len(candidate['elements'])} source-formula elements"
    if criterion == "element_screen":
        return "Element screen: no preset exclusion match; safety unassessed"
    if criterion == "evidence_quality":
        return (
            "Supported-field completeness: "
            f"{candidate['score_components'][criterion]:.0%} (derived)"
        )
    return label + ": unknown"


def _key_caveat(candidate: dict) -> str:
    missing = candidate["missing_selected_criteria"]
    if missing:
        return "Unscored: " + _missing_labels(missing, limit=2)
    return (
        candidate["caveats"][0]
        if candidate["caveats"]
        else "Application performance and compound safety unassessed"
    )


def _missing_evidence(candidate: dict) -> list[str]:
    return candidate.get(
        "missing_measurement_criteria", candidate["missing_selected_criteria"]
    )


def _goal_review(result: dict) -> dict | None:
    """Regenerate fixed diagnostics; saved preferences cannot supply
    report prose."""
    ranking = result.get("ranking", {})
    review = ranking.get("goal_review")
    if review is None:
        return None
    if not isinstance(review, dict):
        raise ValueError("Invalid saved goal preferences.")
    screening = ranking.get("screening_preferences", {})
    expected = reviewed_goal_preferences(
        review.get("scope"),
        {
            "importance": ranking.get("raw_importance"),
            "application": ranking.get("application"),
            **{
                key: screening.get(key)
                for key in (
                    "minimum_band_gap_ev",
                    "target_band_gap_ev",
                    "band_gap_tolerance_ev",
                )
            },
        },
        review.get("authority"),
    )
    if review != expected:
        raise ValueError(
            "Saved goal diagnostics disagree with the ranking preferences."
        )
    return expected


def _goal_lines(result: dict) -> list[str]:
    review = _goal_review(result)
    if not review or not review["requested_goals"]:
        return []
    lines = ["", "Requested ranking goals:", ""]
    lines.append(
        "; ".join(
            f"{_label(row['attribute_id'])}: {row['relation']}"
            for row in review["requested_goals"]
        )
        + ". These are requested preferences, not material measurements."
    )
    if review["review_only_attributes"]:
        preliminary = bool(_preliminary_outcome(result.get("literature_evaluation")))
        lines.append(
            ("Measured-property scoring: " if preliminary else "")
            + review["interpretation"]
        )
        if preliminary:
            lines.append(
                "The separate preliminary shortlist can still use valid qualitative "
                "assessments for these preferences; unassessed criteria remain unknown."
            )
        for row in review["review_only_attributes"]:
            prefix = (
                "Unscored by measured-property utilities"
                if preliminary and review["authority"] == "inferred"
                else (
                    "Unscored requested goal"
                    if review["authority"] == "inferred"
                    else "Request differs from the selected profile"
                )
            )
            lines.append(
                f"- {prefix} — {_label(row['attribute_id'])} "
                f"({row['relation']}): {row['reason']}"
            )
    return lines


def _missing_labels(criteria: list[str], *, limit: int) -> str:
    labels = ", ".join(_label(key) for key in criteria[:limit])
    if len(criteria) > limit:
        labels += f" (+{len(criteria) - limit}; see record details)"
    return labels


def _rationale(candidate: dict, criterion: str) -> str:
    """Turn a scored source field into a noun phrase for the PI
    narrative."""
    if criterion == "element_screen":
        return "the absence of an element-preset exclusion match"
    if criterion == "simplicity":
        return (
            "composition simplicity "
            f"({len(candidate['elements'])} distinct source-formula elements)"
        )
    if criterion == "evidence_quality":
        return (
            "supported-field completeness "
            f"({candidate['score_components'][criterion]:.0%}, derived)"
        )
    if criterion in {"metallicity", "direct_gap"}:
        return (
            "the source-reported metallic classification"
            if criterion == "metallicity"
            else "the source-reported direct gap"
        )
    label, value = _evidence(candidate, criterion).split(": ", 1)
    return f"a reported {label.lower()} of {value}"


def _reference_map(sources: list[dict]) -> dict[str, str]:
    return {
        source["source_id"]: f"R{index}"
        for index, source in enumerate(
            (
                source
                for source in sources
                if source.get("kind") != "discovery_reference"
                and _public_source(source)
                and isinstance(source.get("source_id"), str)
            ),
            1,
        )
    }


def _identity(candidate: dict, references: dict[str, str]) -> str:
    citations = " ".join(
        f"[{references[identifier]}]"
        for identifier in candidate.get("source_ids", [])
        if identifier in references
    )
    return _text(f"{display_formula(candidate['formula'])} {citations}".strip())


def _comparison_endpoint(endpoint: dict, sources: list[dict], references: dict) -> str:
    """Bind an alternative measurement to its retained adapter
    provenance."""
    if not isinstance(endpoint, dict):
        raise ValueError("Invalid saved evidence comparison endpoint.")
    value = endpoint.get("value")
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError("Invalid saved evidence comparison value.")
    hashes = ("raw_fields_sha256", "response_sha256")
    if any(
        not isinstance(endpoint.get(key), str)
        or re.fullmatch(r"[0-9a-f]{64}", endpoint[key]) is None
        for key in hashes
    ):
        raise ValueError("Invalid saved evidence comparison provenance.")
    for source in sources:
        source_id = source.get("source_id")
        if (
            source_id in references
            and source.get("record_id") == endpoint.get("material_id")
            and source.get("url") == endpoint.get("source_url")
            and all(
                source.get("provenance", {}).get(key) == endpoint[key] for key in hashes
            )
        ):
            return references[source_id]
    raise ValueError("An evidence comparison requires verified public citations.")


def _comparison_record(record: dict) -> dict:
    """Method and scope decisions must use the original hashed adapter
    fields."""
    if not isinstance(record, dict) or not isinstance(record.get("provenance"), dict):
        raise ValueError("Invalid saved evidence comparison record.")
    provenance = record["provenance"]
    raw = provenance.get("raw_fields")
    try:
        valid = isinstance(raw, dict) and hashlib.sha256(
            canonical(raw)
        ).hexdigest() == provenance.get("raw_fields_sha256")
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise ValueError("Saved evidence comparison raw fields failed validation.")
    if record.get("source_mode") == "live_hybrid3" and any(
        record.get(field) != raw.get(raw_field)
        for field, raw_field in (
            ("formula", "formula"),
            ("band_gap_ev", "band_gap_ev"),
            ("band_gap_kind", "property"),
        )
    ):
        raise ValueError("Saved comparison observation differs from its source fields.")
    return record


def _comparison_lines(result: dict, sources: list[dict], *, audit: bool) -> list[str]:
    """Display original experiment/calculation values without inventing
    a join."""
    candidates = result.get("candidates", [])
    shortlisted = {row["material_id"] for row in candidates}
    contexts = [(row, row.get("evidence_comparison"), True) for row in candidates] + [
        (row, row, False)
        for row in result.get("ranking", {}).get("evidence_comparisons", [])
        if row.get("material_id") not in shortlisted
    ]
    references = _reference_map(sources)
    seen, comparisons = set(), []
    retained_records = {
        row["material_id"]: row
        for row in [*candidates, *result.get("comparison_records", [])]
    }
    fields = {
        field: (label, unit)
        for label, field, unit in CRITERIA.values()
        if field is not None
    }
    for context, metadata, is_shortlisted in contexts:
        if metadata is None:
            continue  # Historical reports retain their original evidence contract.
        if (
            not isinstance(metadata, dict)
            or metadata.get("version") != "experimental-precedence-v1"
            or not isinstance(metadata.get("comparisons"), list)
            or len(metadata["comparisons"]) > 100
        ):
            raise ValueError("Invalid saved evidence comparison.")
        spread = metadata.get("experimental_range")
        if metadata["comparisons"] or spread is not None:
            original_context = _comparison_record(
                retained_records.get(context.get("material_id"))
            )
            if context.get("formula") != original_context.get("formula"):
                raise ValueError("Saved comparison material context has changed.")
        if spread is not None:
            if (
                not isinstance(spread, dict)
                or spread.get("unit") != "eV"
                or type(spread.get("count")) is not int
                or spread["count"] < 2
                or any(
                    type(spread.get(key)) not in {int, float}
                    or not math.isfinite(spread[key])
                    for key in ("minimum", "maximum")
                )
                or not isinstance(spread.get("record_ids"), list)
                or not 1 <= len(spread["record_ids"]) <= 2
                or any(
                    not isinstance(identity, str) or identity not in retained_records
                    for identity in spread["record_ids"]
                )
            ):
                raise ValueError("Invalid saved experimental spread.")
            extrema = [
                _comparison_record(retained_records[identity])
                for identity in spread["record_ids"]
            ]
            context_record = retained_records.get(context.get("material_id"))
            if not isinstance(context_record, dict) or (
                is_shortlisted and evidence_method(context_record) != "experimental"
            ):
                raise ValueError("Experimental spread requires matched experiments.")
            _comparison_record(context_record)
            verified_spread = experimental_range_from_records(
                extrema, context=context_record
            )
            if any(spread.get(key) != value for key, value in verified_spread.items()):
                raise ValueError(
                    "Saved experimental spread disagrees with its records."
                )
            values, citations = [], []
            for record in extrema:
                provenance = record.get("provenance", {})
                value = record.get("band_gap_ev")
                citation = _comparison_endpoint(
                    {
                        "material_id": record["material_id"],
                        "value": value,
                        "source_url": provenance.get("source_url"),
                        "raw_fields_sha256": provenance.get("raw_fields_sha256"),
                        "response_sha256": provenance.get("response_sha256"),
                    },
                    sources,
                    references,
                )
                values.append(value)
                citations.append(f"[{citation}]")
            if spread.get("minimum") != min(values) or spread.get("maximum") != max(
                values
            ):
                raise ValueError(
                    "Saved experimental spread disagrees with its records."
                )
            identity = ("experimental_range", *sorted(spread["record_ids"]))
            if identity not in seen:
                seen.add(identity)
                comparisons.append(
                    f"{display_formula(context['formula'])} · experimental band-gap "
                    f"spread: {_number(min(values))}–{_number(max(values), 'eV')} "
                    f"{' '.join(citations)}. Reported extrema of comparable "
                    "source experiments; not an uncertainty interval."
                )
        for pair in metadata["comparisons"]:
            if not isinstance(pair, dict) or pair.get("property") not in fields:
                raise ValueError("Invalid saved evidence comparison property.")
            label, unit = fields[pair["property"]]
            if pair.get("unit") != unit:
                raise ValueError("Invalid saved evidence comparison unit.")
            experiment, computation = pair.get("experimental"), pair.get("computed")
            for endpoint, expected_method in (
                (experiment, "experimental"),
                (computation, "computed"),
            ):
                record = (
                    retained_records.get(endpoint.get("material_id"))
                    if isinstance(endpoint, dict)
                    else None
                )
                _comparison_record(record)
                if (
                    not isinstance(record, dict)
                    or endpoint.get("value") != record.get(pair["property"])
                    or endpoint.get("formula") != record.get("formula")
                    or endpoint.get("source_mode") != record.get("source_mode")
                    or any(
                        endpoint.get(key) != record.get("provenance", {}).get(key)
                        for key in (
                            "source_url",
                            "raw_fields_sha256",
                            "response_sha256",
                        )
                    )
                    or evidence_method(record) != expected_method
                ):
                    raise ValueError(
                        "Saved evidence comparison disagrees with its source record."
                    )
            recomputed = compare_observations(
                retained_records[experiment["material_id"]],
                retained_records[computation["material_id"]],
            )
            if pair != recomputed:
                raise ValueError(
                    "Saved evidence comparison disagrees with verified source context."
                )
            if (
                is_shortlisted
                and pair["status"] == "comparable"
                and context["material_id"] != experiment["material_id"]
            ):
                raise ValueError(
                    "Comparable experimental evidence must supply the ranking record."
                )
            experiment_ref = _comparison_endpoint(experiment, sources, references)
            computation_ref = _comparison_endpoint(computation, sources, references)
            identity = (
                pair["property"],
                experiment["material_id"],
                computation["material_id"],
            )
            if identity in seen:
                continue
            seen.add(identity)
            reasons = pair.get("reasons")
            if (
                not isinstance(reasons, list)
                or len(reasons) > 20
                or any(
                    not isinstance(reason, str) or len(reason) > 1000
                    for reason in reasons
                )
            ):
                raise ValueError("Invalid saved evidence comparison conditions.")
            delta = pair.get("delta_computed_minus_experimental")
            if pair.get("status") == "comparable":
                if (
                    type(delta) not in {int, float}
                    or not math.isfinite(delta)
                    or not math.isclose(
                        delta, computation["value"] - experiment["value"], abs_tol=1e-9
                    )
                ):
                    raise ValueError("Invalid saved evidence comparison difference.")
                difference = (
                    f"Computed − experimental: {delta:+g}"
                    f"{(' ' + unit) if unit else ''}."
                )
                if metadata.get("experimental_precedence_applied") is True:
                    basis = (
                        "Experimental evidence used for screening and recommendations."
                        if is_shortlisted
                        else "Experimental evidence used for screening; "
                        "this material was not shortlisted."
                    )
                else:
                    basis = (
                        "Experimental evidence is preferred when applicable "
                        "to the selected criterion."
                    )
            elif pair.get("status") == "not_comparable" and delta is None:
                difference = "No direct numerical comparison."
                basis = "Conditions are not matched; values are not substituted."
                method = evidence_method(original_context)
                if is_shortlisted:
                    basis += (
                        f" Retained ranking record: {method}."
                        if method != "unknown"
                        else " The retained ranking record's method is unknown."
                    )
            else:
                raise ValueError("Invalid saved evidence comparison status.")
            material = display_formula(
                context.get("formula", experiment.get("formula", ""))
            )
            line = (
                f"{material} · {label}: experimental "
                f"{_number(experiment['value'], unit)} "
                f"[{experiment_ref}]; computed {_number(computation['value'], unit)} "
                f"[{computation_ref}]. {difference} {basis}"
            )
            if reasons and (audit or pair["status"] == "not_comparable"):
                line += " " + " ".join(_text(reason) for reason in reasons)
            comparisons.append(_text(line))
    policy = result.get("ranking", {}).get("evidence_comparison_policy", {})
    policy = policy if isinstance(policy, dict) else {}
    omitted = policy.get("omitted_pairs", 0)
    omitted_ranges = policy.get("omitted_experimental_ranges", 0)
    has_omissions = any(
        type(value) is int and value > 0 for value in (omitted, omitted_ranges)
    )
    if not comparisons and not has_omissions:
        return []
    shown = comparisons if audit else comparisons[:3]
    lines = ["", "Experimental and computed evidence:", ""]
    lines.extend("- " + line for line in shown)
    if len(shown) < len(comparisons):
        lines.append(
            f"The Technical Overview lists all {len(comparisons)} "
            "retained comparison notes."
        )
    if type(omitted) is int and omitted > 0:
        lines.append(
            f"{omitted} additional experiment/calculation pairs exceeded the "
            "comparison display limit."
        )
    if type(omitted_ranges) is int and omitted_ranges > 0:
        lines.append(
            f"{omitted_ranges} experimental ranges exceeded the supporting-record "
            "display limit."
        )
    if has_omissions:
        lines.append(
            "All supplied experiments still informed screening before display "
            "limits were applied."
        )
    return lines


def _property_cell(
    candidate: dict, criterion: str, weight: float, citations: list
) -> dict:
    """Snapshot a selected property separately from its derived ranking
    utility."""
    _, field, unit = CRITERIA.get(criterion, (_label(criterion), None, ""))
    available = candidate.get(
        "criterion_evidence_available", candidate["criterion_available"]
    ).get(criterion, False)
    value = None
    if not available:
        status = "unknown" if criterion in SUPPORTED_CRITERIA else "unavailable"
        display = "Unknown" if status == "unknown" else "Unavailable (unsupported)"
    else:
        status = "available"
        if field:
            value = candidate.get(field)
            display = _number(value)
            if (
                criterion == "band_gap"
                and candidate.get("source_mode") == "live_hybrid3"
            ):
                raw = candidate.get("provenance", {}).get("raw_fields", {})
                kind = candidate.get("band_gap_kind", "").lower()
                qualifiers = []
                if type(raw.get("is_experimental")) is bool:
                    qualifiers.append(
                        "experimental" if raw["is_experimental"] else "calculated"
                    )
                if "optical" in kind:
                    qualifiers.append("optical")
                elif "fundamental" in kind:
                    qualifiers.append("fundamental")
                uncertainty = candidate.get("band_gap_uncertainty_ev")
                if (
                    type(uncertainty) in (int, float)
                    and math.isfinite(uncertainty)
                    and uncertainty >= 0
                ):
                    display += f" ± {_number(uncertainty)} (source uncertainty)"
                if qualifiers:
                    display += " · " + ", ".join(qualifiers)
        elif criterion == "simplicity":
            value = len(candidate["elements"])
            display = f"{value} source-formula elements"
        elif criterion == "element_screen":
            value = not candidate["element_screen"]["preset_matches"]
            display = "No exclusion match; safety unassessed"
        else:
            value = candidate.get(
                "supported_field_completeness", candidate["score_components"][criterion]
            )
            display = f"{value:.0%} supported-field completeness (derived)"
        display += " " + " ".join(f"[{identifier}]" for identifier in citations)
    reason = candidate.get("unscored_goal_reasons", {}).get(criterion)
    if reason:
        display += " · Unscored goal: " + reason
    return {
        "value": value,
        "unit": unit,
        "status": status,
        "display": _text(display),
        "utility": candidate["score_components"].get(criterion, 0.0),
        "contribution": candidate["score_contributions"].get(criterion, 0.0),
        "weight": weight,
        "citation_ids": citations if available else [],
    }


def _score_analysis(candidate: dict, result: dict) -> dict:
    """Explain saved utilities without reranking or filling unknown
    properties."""
    coverage = candidate["selected_weight_coverage"]
    score = candidate["score"]
    if (
        type(coverage) not in {int, float}
        or not math.isfinite(coverage)
        or not 0 < coverage <= 1 + 1e-7
    ):
        raise ValueError("Invalid saved criterion coverage.")
    coverage = min(1.0, coverage)
    analysis = candidate.get("score_analysis")
    if analysis is None:
        # Older records lack application diagnostics. Use only their saved
        # profile/weights/availability, preserving the original score and order.
        execution = result.get("execution", {})
        profile = execution.get("ranking_profile", {})
        weights = result.get("ranking", {}).get("weights", {})
        required = [
            key
            for key in ("dielectric_total", "band_gap")
            if isinstance(profile, dict)
            and profile.get("application") == "high_k_screening"
            and weights.get(key, 0) > 0
        ]
        missing = [
            key for key in required if not candidate["criterion_available"].get(key)
        ]
        return {
            "observed_fit": min(1.0, score / coverage),
            "coverage": coverage,
            "possible_upper_score": min(1.0, score + 1 - coverage),
            "required_criteria": required,
            "missing_required_criteria": missing,
            "status": "needs_evidence" if missing else "comparable",
        }
    if not isinstance(analysis, dict) or set(analysis) != {
        "observed_fit",
        "coverage",
        "possible_upper_score",
        "required_criteria",
        "missing_required_criteria",
        "status",
    }:
        raise ValueError("Invalid saved score analysis.")
    for key in ("observed_fit", "coverage", "possible_upper_score"):
        value = analysis[key]
        if (
            type(value) not in {int, float}
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ValueError("Invalid saved score analysis fraction.")
    for key in ("required_criteria", "missing_required_criteria"):
        value = analysis[key]
        if (
            not isinstance(value, list)
            or len(value) > 100
            or any(
                not isinstance(item, str)
                or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", item) is None
                for item in value
            )
            or len(set(value)) != len(value)
        ):
            raise ValueError("Invalid saved score analysis criteria.")
    required, missing = (
        analysis["required_criteria"],
        analysis["missing_required_criteria"],
    )
    if (
        abs(analysis["coverage"] - coverage) > 1e-7
        or abs(analysis["observed_fit"] * coverage - score) > 1e-7
        or abs(analysis["possible_upper_score"] - min(1.0, score + 1 - coverage)) > 1e-7
        or missing
        != [key for key in required if not candidate["criterion_available"].get(key)]
        or analysis["status"] != ("needs_evidence" if missing else "comparable")
    ):
        raise ValueError("Saved score analysis disagrees with its evidence coverage.")
    return deepcopy(analysis)


def _analysis_label(analysis: dict) -> str:
    if analysis["missing_required_criteria"]:
        return "Needs application evidence"
    if analysis["coverage"] < 1 - 1e-7:
        return "Partial criterion coverage"
    return "Selected criteria covered"


def _analysis_note(candidate: dict, result: dict) -> str:
    analysis = _score_analysis(candidate, result)
    has_unscored_goals = bool(candidate.get("unscored_goal_reasons"))
    note = (
        "Evidence with supported requested utilities covers "
        if has_unscored_goals
        else "Usable evidence covers "
    ) + f"{analysis['coverage']:.1%} of selected importance. "
    if analysis["missing_required_criteria"]:
        unsupported = [
            key
            for key in analysis["missing_required_criteria"]
            if key in candidate.get("unscored_goal_reasons", {})
        ]
        missing = [
            key
            for key in analysis["missing_required_criteria"]
            if key in _missing_evidence(candidate)
        ]
        if unsupported:
            note += (
                "Application comparison needs supported requested utilities for "
                + _join([_label(key) for key in unsupported])
                + ". "
            )
        if missing:
            note += (
                "Application comparison still needs "
                + _join([_label(key) for key in missing])
                + " evidence. "
            )
    return note.rstrip()


def _summary_caveat(candidate: dict, analysis: dict) -> str:
    if candidate.get("unscored_goal_reasons"):
        note = (
            "Requested utility unsupported: "
            + _missing_labels(list(candidate["unscored_goal_reasons"]), limit=2)
            + "."
        )
    elif analysis["missing_required_criteria"]:
        note = (
            "Needs "
            + _join([_label(key) for key in analysis["missing_required_criteria"]])
            + " evidence."
        )
    else:
        note = _key_caveat(candidate)
    return _text(f"{analysis['coverage']:.0%} coverage. " + note)


def report_tables(result: dict, sources: list[dict]) -> dict:
    """Plain structured tables shared by the UI, text, and document
    renderers."""
    references = _reference_map(sources)
    review = _goal_review(result)
    expected_unscored = (
        {
            row["attribute_id"]: row["reason"]
            for row in review["review_only_attributes"]
            if row["attribute_id"] in review["unscored_attributes"]
        }
        if review
        else None
    )
    evidence = {
        source["source_id"]: source
        for source in sources
        if source.get("source_id") in references
    }
    criteria = [
        key
        for key, weight in result.get("ranking", {}).get("weights", {}).items()
        if weight > 0
    ]
    common = [
        {"id": "rank", "label": "Rank", "kind": "rank"},
        {"id": "material", "label": "Material", "kind": "identity"},
        {"id": "score", "label": "Supported score", "kind": "score"},
    ]
    technical_columns = common + [
        {
            "id": key,
            "label": ("Energy above hull" if key == "stability" else _label(key))
            + (
                f" ({CRITERIA[key][2]})" if key in CRITERIA and CRITERIA[key][2] else ""
            ),
            "kind": "property",
            "unit": CRITERIA.get(key, (None, None, ""))[2],
        }
        for key in criteria
    ]
    rows = []
    for candidate in result.get("candidates", []):
        if review and candidate.get("unscored_goal_reasons") != expected_unscored:
            raise ValueError(
                "Saved candidate goal diagnostics disagree with preferences."
            )
        analysis = _score_analysis(candidate, result)
        provenance = candidate.get("provenance", {})
        digest = provenance.get("raw_fields_sha256")
        citations = [
            references[identifier]
            for identifier in candidate.get("source_ids", [])
            if identifier in references
            and evidence[identifier].get("record_id") == candidate["material_id"]
            and evidence[identifier].get("url") == provenance.get("source_url")
            and isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest)
            and evidence[identifier].get("provenance", {}).get("raw_fields_sha256")
            == digest
        ]
        if not citations or score_color(candidate.get("score")) is None:
            raise ValueError(
                "A scored report row requires verified public citations "
                "and a valid utility."
            )
        if candidate.get("selected_weight_coverage", 0) <= 0:
            raise ValueError(
                "A scored report row requires evidence for a selected criterion."
            )
        rows.append(
            {
                "rank": candidate["rank"],
                "material_id": _text(candidate["material_id"]),
                "formula": _text(display_formula(candidate["formula"])),
                "source_formula": _text(candidate["formula"]),
                "material": _identity(candidate, references),
                "score": candidate["score"],
                "score_color": score_color(candidate["score"]),
                "score_band": score_band(candidate["score"]),
                "score_analysis": analysis,
                "properties": {
                    key: _property_cell(
                        candidate, key, result["ranking"]["weights"][key], citations
                    )
                    for key in criteria
                },
                "citation_ids": citations,
                "rationale": _text(
                    _join([_rationale(candidate, key) for key in _criteria(candidate)])
                )
                or "No positive utility contribution from supported selected values.",
                "caveats": [_text(note) for note in candidate["caveats"]],
                "missing_criteria": list(candidate["missing_selected_criteria"]),
                "selected_weight_coverage": candidate["selected_weight_coverage"],
                "leading": _text(
                    "; ".join(
                        _evidence(candidate, key)
                        for key in _criteria(candidate, limit=2)
                    )
                )
                or "No positive contribution",
                "caveat": _summary_caveat(candidate, analysis),
            }
        )
    return {
        "schema": "ranking-tables-v1",
        "score_scale": deepcopy(SCORE_SCALE),
        "summary": {
            "columns": common
            + [
                {"id": "leading", "label": "Leading criteria", "kind": "text"},
                {"id": "caveat", "label": "Key caveat", "kind": "text"},
            ],
            "rows": deepcopy(rows[:3]),
        },
        "technical": {"columns": technical_columns, "rows": rows},
    }


def _structured_table(table: dict) -> list[str]:
    return _table(
        [column["label"] for column in table["columns"]],
        [
            [
                (
                    row["properties"][column["id"]]["display"]
                    if column["kind"] == "property"
                    else (
                        f"{row['score']:.4f}"
                        if column["id"] == "score"
                        else str(row[column["id"]])
                    )
                )
                for column in table["columns"]
            ]
            for row in table["rows"]
        ],
    )


def _references(
    sources: list[dict],
    references: dict[str, str],
    displayed: list[dict],
    comparison_records: list[dict] | None = None,
) -> list[str]:
    displayed = [*displayed, *(comparison_records or [])]
    used = {source_id for row in displayed for source_id in row.get("source_ids", [])}
    approved = citation_references({"candidates": displayed}, sources)
    selected_ids = {
        references[source_id] for source_id in used if source_id in references
    }
    selected = [source for source in approved if source["id"] in selected_ids]
    if not selected:
        return []
    return [
        "",
        "Public references:",
        *[
            f"- [{source['id']}] {source['title']} · {source['source_name']}"
            for source in selected
        ],
    ]


def _source_coverage_lines(result: dict) -> list[str]:
    """Report source failures without repeating exception messages or
    raw URLs."""
    from labcat.public_sources import catalog

    labels = {row["id"]: row["name"] for row in catalog()}
    labels["materials_project"] = "Materials Project"
    retrieval = result.get("retrieval", {})
    retrieval = retrieval if isinstance(retrieval, dict) else {}
    discovery = result.get("public_discovery", {})
    discovery = discovery if isinstance(discovery, dict) else {}
    leads = retrieval.get("discovery_leads", {})
    leads = leads if isinstance(leads, dict) else {}
    refresh = retrieval.get("chat_source_refresh", {})
    refresh = refresh if isinstance(refresh, dict) else {}
    unavailable, exhausted = [], []
    for attempts, identifier, stage in (
        (retrieval.get("repository_attempts"), "repository", "property search"),
        (discovery.get("source_statuses"), "source_id", "reference search"),
        (leads.get("attempts"), "repository", "candidate lookup"),
        (refresh.get("attempts"), "repository", "saved-source refresh"),
    ):
        for attempt in attempts if isinstance(attempts, list) else []:
            if not isinstance(attempt, dict):
                continue
            source_id = attempt.get(identifier)
            label = labels.get(source_id) if isinstance(source_id, str) else None
            if label is None:
                continue  # Unrecognized source identifiers are never prose.
            status = attempt.get("status")
            if not isinstance(status, str):
                continue
            note = f"{label} ({stage})"
            if status in {"unavailable", "blocked", "failed"}:
                unavailable.append(note)
            elif status == "budget_exhausted":
                exhausted.append(note)
    unavailable = list(dict.fromkeys(unavailable))
    exhausted = list(dict.fromkeys(exhausted))
    if not unavailable and not exhausted:
        return []
    lines = ["", "Source availability:", ""]
    if unavailable:
        lines.append(
            "Unavailable or failed validation: " + "; ".join(unavailable) + "."
        )
    if exhausted:
        lines.append("Retrieval time limit reached: " + "; ".join(exhausted) + ".")
    retained = bool(result.get("candidates") or result.get("candidate_leads"))
    lines.append(
        ("Completed results are retained. " if retained else "")
        + "Coverage is incomplete; a failed lookup does not establish that "
        "evidence is absent. Missing properties remain unfilled and are not "
        "treated as measured zeros."
    )
    return lines


def _discovery(result: dict, sources: list[dict], *, audit: bool) -> list[str]:
    discovery = result.get("public_discovery")
    if not isinstance(discovery, dict):
        return []
    references = [
        ref
        for ref in citation_references(result, sources)
        if ref["kind"] == "discovery_reference"
    ]
    if not references:
        return [
            "",
            "Public literature:",
            "No additional public references were retained for this run.",
        ]
    shown = references[: 6 if audit else 2]
    evaluation = result.get("literature_evaluation")
    preliminary = bool(_preliminary_outcome(evaluation))
    interpreted = preliminary and any(
        row["judgment"] != "unknown" for row in evaluation["proposals"]
    )
    lines = [
        "",
        "Public literature:",
        (
            f"{len(references)} references were retained. Selected passages inform "
            "preliminary screening priority through attributed assessments; these "
            "references are not measured-property evidence. Other references remain "
            "unassessed review leads."
            if interpreted
            else (
                f"{len(references)} references were retained. Retrieved "
                "passages supply "
                "the candidate names. No non-unknown criterion judgments were "
                "retained; "
                "screening priorities use the disclosed preliminary review prior. "
                "These "
                "references are not measured-property evidence."
                if preliminary
                else f"{len(references)} references were retained. These are "
                "review leads, "
                f"not scored material-property evidence."
            )
        ),
    ]
    for source in shown:
        lines.append(f"- [{source['id']}] {source['title']} · {source['source_name']}")
    if len(shown) < len(references):
        lines.append(
            f"The source list and JSON archive retain all {len(references)} references."
        )
    return lines


def _excerpt(text: str, limit: int) -> str:
    """Shorten a literal passage at a word boundary, never paraphrase
    it."""
    text = _text(text)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _candidate_leads(result: dict, sources: list[dict]) -> list[dict]:
    """Rebind saved literal mentions to their approved source
    passages."""
    leads = result.get("candidate_leads", [])
    if not leads:
        return []
    from labcat.science.candidate_leads import (
        discovery_documents,
        validate_candidate_leads,
    )

    if not isinstance(leads, list) or len(leads) > 12:
        raise ValueError("The saved candidate-lead list is invalid.")
    if any(
        not isinstance(lead, dict) or not isinstance(lead.get("citations"), list)
        for lead in leads
    ):
        raise ValueError("The saved candidate lead is invalid.")
    sources = report_scoped_sources(result, sources)
    references = [source for source in sources if _public_source(source)]
    preferred_documents = list(
        dict.fromkeys(
            citation.get("document_id")
            for lead in leads
            if isinstance(lead, dict)
            for citation in lead.get("citations", [])
            if isinstance(citation, dict)
        )
    )
    documents = discovery_documents(
        references, preferred_document_ids=preferred_documents
    )
    validated, seen = [], set()
    for lead in leads:
        if not isinstance(lead, dict) or not isinstance(lead.get("citations"), list):
            raise ValueError("The saved candidate lead is invalid.")
        missing = lead.get("missing_criteria")
        if (
            not isinstance(missing, list)
            or len(missing) > 103
            or any(
                not isinstance(key, str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
                for key in missing
            )
            or len(set(missing)) != len(missing)
            or not {
                "stability",
                "ambient_phase_stability",
                "operational_stability",
            }.issubset(missing)
        ):
            raise ValueError("The saved candidate-lead evidence gaps are invalid.")
        proposals = []
        name = lead.get("name")
        if not isinstance(name, str) or not 1 <= len(name) <= 120:
            raise ValueError("The saved candidate-lead name is invalid.")
        for citation in lead["citations"]:
            if not isinstance(citation, dict) or not isinstance(
                citation.get("quote"), str
            ):
                raise ValueError("The saved candidate-lead citation is invalid.")
            # Later citations may use another capitalization of the same name.
            # Recover only literal spellings, then let the source validator
            # check whole-mention boundaries and the complete quote.
            folded, offsets = "", {0: 0}
            for index, character in enumerate(citation["quote"]):
                folded += character.casefold()
                offsets[len(folded)] = index + 1
            spellings = dict.fromkeys(
                citation["quote"][offsets[match.start()] : offsets[match.end()]]
                for match in re.finditer(re.escape(name.casefold()), folded)
                if match.start() in offsets and match.end() in offsets
            )
            # Preserve the first selected spelling, even when its passage also
            # contains another capitalization before that exact mention.
            if name in spellings:
                spellings = {name: None, **spellings}
            proposals.extend(
                {
                    "document_id": citation.get("document_id"),
                    "name": spelling,
                    "quote": citation["quote"],
                }
                for spelling in spellings
            )
        recovered = validate_candidate_leads(proposals, documents, references)
        # Rendering cannot upgrade flags, attach unsupported fields or change
        # source passages. A corrupt snapshot falls back to its archived prose.
        if (
            len(recovered) != 1
            or {**recovered[0], "missing_criteria": missing} != lead
            or lead["id"] in seen
        ):
            raise ValueError("The saved candidate lead cannot be verified.")
        validated.append(lead)
        seen.add(lead["id"])
    return validated


def _lead_gap_labels(lead: dict) -> list[str]:
    names = {
        "stability": "Thermodynamic stability",
        "ambient_phase_stability": "Room-temperature phase stability",
        "operational_stability": "Operational stability",
    }
    return [names.get(key, _label(key)) for key in lead["missing_criteria"]]


def _candidate_lead_lines(
    result: dict, sources: list[dict], *, audit: bool
) -> list[str]:
    leads = _candidate_leads(result, sources)
    if not leads:
        return []
    references = {ref["url"]: ref for ref in citation_references(result, sources)}
    shown = leads if audit else leads[:5]
    lines = [
        "",
        "Source-grounded candidates:",
        "",
        f"Public sources name {len(leads)} candidate leads for further review. "
        "These are cited mentions: material identity, properties and suitability "
        "for the requested use remain unverified. A passage may describe a "
        "comparison or a rejected material. Review order is not a performance "
        "ranking; no scores are assigned.",
        "",
        *_table(
            [
                "Review order",
                "Candidate",
                "Source",
                "Supporting quote",
                "Missing measurements",
            ],
            [
                [
                    str(index),
                    lead["name"],
                    _excerpt(lead["title"], 160 if audit else 100)
                    + f" [{references[lead['url']]['id']}]",
                    "“" + _excerpt(lead["quote"], 240 if audit else 180) + "”",
                    "; ".join(_lead_gap_labels(lead)),
                ]
                for index, lead in enumerate(shown, 1)
            ],
        ),
        "",
        "Missing measurements and condition-matched evidence remain unresolved. "
        "Thermodynamic, room-temperature phase and operational stability are "
        "unverified; unknown does not mean stable. No application suitability "
        "or experimental recommendation is established by these mentions.",
    ]
    if not audit:
        lines.append(
            f"This compact table shows {len(shown)} of {len(leads)} leads. "
            "Technical View retains every lead, full supporting quotations "
            "and all evidence gaps."
        )
        return lines
    lines += ["", "Candidate evidence gaps:"]
    for index, lead in enumerate(leads, 1):
        lines += ["", f"Review {index} · {_text(lead['name'])}:"]
        for citation in lead["citations"]:
            source = references[citation["url"]]
            lines += [
                f"Source: {_text(citation['title'])} [{source['id']}]",
                "“" + _text(citation["quote"]) + "”",
            ]
        lines += [
            "Missing measurements: " + "; ".join(_lead_gap_labels(lead)) + ".",
            *["- " + _text(caution) for caution in lead["cautions"]],
        ]
    return lines


def validated_literature_evaluation(result: dict, sources: list[dict]) -> dict | None:
    """Rebind interpreted fit to saved passages and the actual selected
    profile."""
    if "literature_evaluation" not in result:
        return None
    from labcat.science.literature_evaluation import (
        evaluation_goals,
        validate_evaluation,
    )

    sources = report_scoped_sources(result, sources)
    ranking = result.get("ranking", {})
    profile = result.get("execution", {}).get("ranking_profile")
    if not isinstance(profile, dict):
        profile = {
            "importance": ranking.get("raw_importance", ranking.get("weights", {})),
            "application": ranking.get("application"),
            **ranking.get("screening_preferences", {}),
        }
    return validate_evaluation(
        result["literature_evaluation"],
        _candidate_leads(result, sources),
        [source for source in sources if _public_source(source)],
        profile,
        goals=evaluation_goals(
            result.get("execution", {}).get("semantic_scope"),
            result.get("execution", {}).get("ranking_selection"),
        ),
    )


def _literature_assessment_text(
    criterion: dict, references: dict, *, detailed=False
) -> str:
    judgments = {
        "supports": "Supports fit",
        "mixed": "Mixed evidence",
        "concern": "Concern",
        "unknown": "Unknown",
    }
    label = judgments[criterion["judgment"]]
    items = []
    assessments = criterion["assessments"]
    for assessment in assessments if detailed else assessments[:2]:
        citation = assessment.get("citation", assessment)
        reference = references.get(citation["url"])
        if reference is None:
            raise ValueError(
                "A literature assessment requires a verified public citation."
            )
        text = _text(assessment["interpretation"])
        if not detailed:
            text = _excerpt(text, 140)
        items.append(text + f" [{reference['id']}]")
    text = label + (": " + "; ".join(dict.fromkeys(items)) if items else "")
    if not detailed and len(assessments) > 2:
        text += f" (+{len(assessments) - 2} assessments in Technical Overview)"
    return text


def _literature_lines(
    evaluation: dict | None, sources: list[dict], *, audit: bool, leads=(), result=None
) -> list[str]:
    if not evaluation:
        return []
    if evaluation["version"] == "literature-fit-v2":
        return _preliminary_literature_lines(
            evaluation, sources, audit=audit, leads=leads, result=result
        )
    ranked = evaluation["ranked_candidates"]
    unranked = evaluation["unranked_candidates"]
    if not ranked and not unranked:
        return []
    references = {row["url"]: row for row in citation_references({}, sources)}
    criteria = {row["criterion_id"]: row for row in evaluation["criteria"]}
    mentions = {row["id"]: row for row in leads}

    def criterion_label(key):
        criterion = criteria[key]
        goal = criterion["goal"]
        target = goal.get("target_band_gap_ev")
        preference = (
            "target " + _number(target, "eV")
            if goal["relation"] == "target" and target is not None
            else goal["relation"]
        )
        return criterion["label"] + " (" + preference + ")"

    def material(row):
        citations = dict.fromkeys(
            references[item["url"]]["id"]
            for item in mentions.get(row["lead_id"], {}).get("citations", [])
            if item["url"] in references
        )
        return (
            _text(row["name"])
            + " "
            + " ".join(f"[{identifier}]" for identifier in citations)
        )

    lines = (
        ["", "Provisional literature shortlist:", ""]
        if ranked
        else ["", "Literature assessment:", ""]
    )
    lines += [
        "The model evaluated cited public passages against the selected criteria. "
        "The provisional order reflects interpreted fit supported by those passages, "
        "not measured material performance or citation counts. Missing criteria "
        "remain unknown; equal supported fit receives the same rank.",
    ]
    if ranked:
        rows = []
        for row in ranked:
            selected = [
                item
                for item in row["criteria"]
                if criteria[item["criterion_id"]]["weight"] > 0
            ]
            assessed = [item for item in selected if item["judgment"] != "unknown"]
            # Keep the overview compact; every criterion is expanded below.
            highlighted = sorted(
                assessed,
                key=lambda item: (
                    item["judgment"] != "concern",
                    -criteria[item["criterion_id"]]["weight"],
                ),
            )[:2]
            criterion_text = (
                "; ".join(
                    criterion_label(item["criterion_id"])
                    + " — "
                    + _literature_assessment_text(item, references)
                    for item in highlighted
                )
                or "No selected criterion assessment"
            )
            stability = [
                item
                for item in row["criteria"]
                if item["criterion_id"]
                in {"stability", "ambient_phase_stability", "operational_stability"}
            ]
            concerns = [
                item for item in stability if item["judgment"] in {"mixed", "concern"}
            ]
            stability_text = "; ".join(
                criteria[item["criterion_id"]]["label"]
                + " — "
                + _literature_assessment_text(item, references)
                for item in concerns
            )
            unknown_stability = [
                criteria[item["criterion_id"]]["label"]
                for item in stability
                if item["judgment"] == "unknown"
            ]
            if unknown_stability:
                stability_text += (
                    ("; " if stability_text else "")
                    + "Unknown: "
                    + ", ".join(unknown_stability)
                )
            if not stability_text:
                stability_text = (
                    "Stability discussed in cited passages; confirm the "
                    "reported conditions."
                )
            unknown = [
                criteria[key]["label"]
                for key in row["unknown_criteria"]
                if key in criteria and criteria[key]["weight"] > 0
            ]
            rows.append(
                [
                    str(row["rank"]),
                    material(row),
                    f"{row['fit_lower_bound']:.0%} supported fit; "
                    f"{row['fit_lower_bound']:.0%}–{row['fit_upper_bound']:.0%} bound",
                    criterion_text,
                    f"{row['coverage']:.0%} assessed; {len(unknown)} unknown "
                    + ("criterion" if len(unknown) == 1 else "criteria"),
                    stability_text,
                ]
            )
        lines += [
            "",
            *_table(
                [
                    "Provisional rank",
                    "Material",
                    "Literature fit",
                    "Selected criterion assessments",
                    "Assessment coverage",
                    "Stability & uncertainty",
                ],
                rows,
            ),
        ]
        lines += [
            "",
            "Supported fit uses the selected weights and the passage judgments. "
            "Coverage is the share of selected importance with a cited assessment. "
            "The bound holds assessed judgments fixed and allows unknown criteria "
            "to vary; it is not a confidence interval or a measured performance range.",
        ]
    if unranked:
        lines += ["", "Materials still needing a criterion assessment:"]
        lines.extend(
            "- "
            + material(row)
            + ": no supported assessment of a selected criterion; no fit rank assigned."
            for row in unranked
        )
    if not audit:
        lines += [
            "The Technical Overview includes each criterion assessment and its "
            "supporting passage."
        ]
        return lines
    lines += ["", "Literature criterion assessments:"]
    used = set()
    for row in [*ranked, *unranked]:
        lines += ["", material(row) + ":"]
        if row["observed_fit"] is not None:
            lines.append(
                f"Fit among assessed criteria: {row['observed_fit']:.0%}. "
                "This excludes unknown criteria and is not the ranking score."
            )
        lines += _table(
            [
                "Criterion",
                "Selected importance",
                "Passage assessment",
                "Remaining uncertainty",
            ],
            [
                [
                    criterion_label(item["criterion_id"]),
                    f"{criteria[item['criterion_id']]['weight']:.1%}",
                    _literature_assessment_text(
                        {**item, "assessments": [assessment] if assessment else []},
                        references,
                        detailed=True,
                    ),
                    (
                        "No cited assessment; unknown is not a favorable result."
                        if item["judgment"] == "unknown"
                        else "Interpretation of the cited source; confirm material "
                        "identity, phase and conditions."
                    ),
                ]
                for item in row["criteria"]
                for assessment in item["assessments"] or [None]
            ],
        )
        seen_passages = set()
        for item in row["criteria"]:
            for assessment in item["assessments"]:
                citation = assessment.get("citation", assessment)
                reference = references[citation["url"]]
                used.add(citation["url"])
                identity = (citation["url"], citation["quote"])
                if identity not in seen_passages:
                    lines.append(
                        f"- Supporting passage [{reference['id']}]: "
                        f"“{_excerpt(citation['quote'], 300)}”"
                    )
                    seen_passages.add(identity)
    lines += ["", "Literature assessment references:"]
    lines.extend(
        f"- [{row['id']}] {row['title']} · {row['source_name']}"
        for url, row in references.items()
        if url in used
    )
    return lines


def screening_priority_presentation(row: dict) -> dict[str, str]:
    """Style a validated v2 review score without interpreting missing
    evidence."""
    percentage = f"{row['priority_score']:.0%}"
    if row["priority_tier"] == 2:
        label, state, fill = "Concern reported", "concern", "#F8D7DA"
    elif row["priority_tier"] == 1:
        label, state, fill = "Mixed evidence", "mixed", "#FFE0B2"
    elif (
        row["general_evidence"]["application_fit"] == "unknown"
        and row["general_evidence"]["demonstrated_use"] == "unknown"
        and row["coverage"] == 0
    ):
        label, state, fill = "Unassessed review prior", "unassessed", "#EDF0F2"
    else:
        label, state = "Assessed review priority", "assessed"
        # The shared palette's warm-to-green half communicates relative review
        # priority; red is reserved here for actual application/stability concerns.
        fill = score_color(0.5 + int(percentage[:-1]) / 200)
    return {"text": percentage + " · " + label, "state": state, "fill": fill}


def _preliminary_literature_lines(
    evaluation: dict, sources: list[dict], *, audit: bool, leads=(), result=None
) -> list[str]:
    """Present review priority separately from measured-property
    performance.

    Only a previously rebound v2 evaluation reaches this renderer. All
    numbers below come from its deterministic calculation, never saved
    model prose.
    """
    ranked = evaluation["ranked_candidates"]
    if not ranked:
        return []
    references = {row["url"]: row for row in citation_references({}, sources)}
    definitions = {row["criterion_id"]: row for row in evaluation["criteria"]}
    mentions = {row["id"]: row for row in leads}
    # Scope contributes preference IDs only; numerical targets are not values.
    from labcat.science.literature_evaluation import evaluation_goals

    execution = (result or {}).get("execution", {})
    selection = execution.get("ranking_selection", {})
    scope = execution.get("semantic_scope")
    goals = evaluation_goals(scope, selection)
    mode = selection.get("mode") if isinstance(selection, dict) else None
    requested = list(scope["goals"]) if mode == "semantic_inferred" else []
    semantic_ids = {goal["attribute_id"] for goal in requested}
    # Do not add semantic synonyms back through their mirrored adjustment rows.
    # The lexical path still supplies explicit IDs when it has no semantic scope.
    if mode in {"inferred", "semantic_inferred"}:
        requested += [
            {**item, "attribute_id": item["attribute"]}
            for item in selection.get("preference_adjustments", [])
            if isinstance(item, dict)
            and item.get("status") == "applied_preference"
            and isinstance(item.get("attribute"), str)
            and item["attribute"] not in semantic_ids
        ]
    explicit_ids = grouped_explicit_property_ids(evaluation["criteria"], requested)
    property_ids = selected_property_ids(
        evaluation["criteria"],
        explicit_ids=explicit_ids,
        application_ids=[
            goal["attribute_id"]
            for goal in goals
            if goal["attribute_id"] not in semantic_ids
        ],
    )
    tier_labels = {
        0: "No recorded application/stability concern",
        1: "Mixed evidence",
        2: "Concern reported",
    }
    basis_labels = {
        "preliminary": "Baseline only",
        "blended": "Attribute-refined",
        "attribute": "Assessed attributes",
    }

    def material(row):
        identifiers = dict.fromkeys(
            references[item["url"]]["id"]
            for item in mentions.get(row["lead_id"], {}).get("citations", [])
            if item["url"] in references
        )
        return (
            _text(display_formula(row["name"]))
            + " "
            + " ".join(f"[{identifier}]" for identifier in identifiers)
        )

    def criterion_label(key):
        definition = definitions[key]
        goal = definition["goal"]
        target = goal.get("target_band_gap_ev")
        preference = (
            "target " + _number(target, "eV")
            if goal["relation"] == "target" and target is not None
            else goal["relation"]
        )
        return definition["label"] + " (" + preference + ")"

    def compact_assessment(item):
        # One concise reason per table cell; all interpretations and their
        # conflicts remain in the criterion-by-criterion audit below.
        ordered = sorted(
            item["assessments"],
            key=lambda assessment: {
                "concern": 0,
                "mixed": 1,
                "unknown": 2,
                "supports": 3,
            }[assessment["judgment"]],
        )
        return _literature_assessment_text(
            {
                **item,
                "assessments": [
                    {
                        **assessment,
                        "interpretation": _excerpt(assessment["interpretation"], 100),
                    }
                    for assessment in ordered[:1]
                ],
            },
            references,
        )

    def relevant_properties(row):
        """Admitted quotations retain units, methods and device context.

        Never turn interpretation into a measurement, join another phase
        by formula, or relabel a device efficiency as an intrinsic
        property.
        """
        by_id = {item["criterion_id"]: item for item in row["criteria"]}
        cells = []
        for key in property_ids:
            item = by_id[key]
            label = definitions[key]["label"]
            assessments = sorted(
                item["assessments"],
                key=lambda a: {"concern": 0, "mixed": 1, "supports": 2, "unknown": 3}[
                    a["judgment"]
                ],
            )
            if not assessments:
                cells.append(label + " — Not reported")
                continue
            assessment = assessments[0]
            reference = references.get(assessment["url"])
            if reference is None:
                raise ValueError(
                    "A property passage requires a verified public citation."
                )
            quote = _text(assessment["quote"]).replace(" ▪ ", " • ")
            cell = label + " — Source passage: “" + quote + f"” [{reference['id']}]"
            if item["judgment"] == "mixed":
                cell += " (conflicting assessments; see analysis)"
            elif len(assessments) > 1:
                cell += f" (+{len(assessments) - 1} passages in analysis)"
            cells.append(cell)
        return " ▪ ".join(cells) or "No material properties selected"

    lines = [
        "",
        "Candidate shortlist:",
        "",
        "Screening priority starts with cited application discussion and use, then "
        "is refined by available evidence for the selected attributes. It is a "
        "priority for further review, not measured performance, a probability or "
        "confidence. Missing attributes retain the preliminary score rather than "
        "counting as poor performance.",
        "Reported application or stability concerns are placed after candidates "
        "without those adverse assessments, regardless of score. Unknown stability "
        "is not established stability. Equal tier and score receive the same rank.",
        "Color key: gray marks an unassessed review prior; warm-to-green shades "
        "show lower-to-higher assessed review priority; amber marks mixed evidence "
        "and red marks a reported application or stability concern. Labels carry "
        "the same meaning without color. A missing concern is not a favorable finding.",
    ]
    rows = []
    for row in ranked:
        by_id = {item["criterion_id"]: item for item in row["criteria"]}
        general = [
            by_id[key]
            for key in ("application_fit", "demonstrated_use")
            if by_id[key]["judgment"] != "unknown"
        ]
        why = (
            "; ".join(
                definitions[item["criterion_id"]]["label"]
                + " — "
                + compact_assessment(item)
                for item in general[:1]
            )
            or "Named in retrieved discussion; application relevance and use "
            "unassessed."
        )
        if len(general) > 1:
            why += (
                "; demonstrated use: "
                + {
                    "supports": "supported",
                    "mixed": "mixed",
                    "concern": "concern",
                }[by_id["demonstrated_use"]["judgment"]]
            )
        attributes = [
            item
            for item in row["criteria"]
            if definitions[item["criterion_id"]]["weight"] > 0
        ]
        unknown = sum(item["judgment"] == "unknown" for item in attributes)
        concerns = [
            item
            for item in row["criteria"]
            if item["criterion_id"]
            in {
                "application_fit",
                "stability",
                "ambient_phase_stability",
                "operational_stability",
            }
            and any(a["judgment"] in {"mixed", "concern"} for a in item["assessments"])
        ]
        concerns.sort(
            key=lambda item: min(
                {"concern": 0, "mixed": 1, "unknown": 2, "supports": 3}[
                    assessment["judgment"]
                ]
                for assessment in item["assessments"]
            )
        )
        caution = "; ".join(
            definitions[item["criterion_id"]]["label"]
            + " — "
            + compact_assessment(item)
            for item in concerns[:1]
        )
        if len(concerns) > 1:
            caution += f"; {len(concerns) - 1} more in Technical Overview"
        if row["stability_unknown"]:
            caution += ("; " if caution else "") + "Stability evidence incomplete"
        if not caution:
            caution = "Check cited phase, conditions and stability interpretation."
        rows.append(
            [
                str(row["rank"]),
                material(row),
                screening_priority_presentation(row)["text"],
                why,
                (
                    relevant_properties(row)
                    if audit
                    else f"{row['coverage']:.0%} assessed · "
                    f"{basis_labels[row['ranking_basis']]}; "
                    f"{unknown} unknown "
                    + ("criterion" if unknown == 1 else "criteria")
                ),
                caution,
            ]
        )
    lines += [
        "",
        *_table(
            [
                "Rank",
                "Material",
                "Screening priority",
                "Why considered",
                "Relevant properties" if audit else "Attribute evidence",
                "Stability / key caveat",
            ],
            rows,
        ),
        "",
        "The same preliminary rules apply across material classes. When application "
        "discussion is unassessed, its fixed review prior is disclosed in Technical "
        "Overview; it is not evidence of suitability. Distinct supporting works "
        "make only a capped contribution. Source passages and model interpretations "
        "remain distinguishable from verified measurements.",
    ]
    if audit:
        lines += [
            "Relevant properties: up to three selected properties, with explicit "
            "request goals first, then profile importance. Source passages keep "
            "their reported units, method and device context; they are not "
            "extracted measurements. Device efficiency is not an intrinsic "
            "material property. Not reported means no retained passage for this "
            "candidate and property, not a measured zero.",
        ]
    if any(
        screening_priority_presentation(row)["state"] == "unassessed" for row in ranked
    ):
        lines.append(
            "Unassessed review prior: the displayed 22% comes from the same fixed "
            "0.225 default for unknown application relevance and demonstrated use "
            "with no assessed selected attributes. It is not 22% suitability, a "
            "success rate, or a favorable assessment. These rows need assessment; "
            "their matching scores do not distinguish the candidates."
        )
    if not audit:
        lines.append(
            "Technical Overview retains the full calculation, selected attributes, "
            "adverse assessments and supporting passages for every candidate."
        )
        return lines
    lines += [
        "",
        "Preliminary ranking method:",
        "Algorithm: literature-fit-v2. Baseline B = 0.70 × application relevance "
        "+ 0.20 × demonstrated use + 0.10 × min(distinct corroborating works / 3, 1). "
        "General judgments map support to 1, mixed to 0.5, concern to 0; unknown "
        "uses 0.25 as an explicit review prior, not a measured value or favorable "
        "finding. Application relevance and demonstrated use do not consume the "
        "selected attribute weights.",
        "With both general judgments unknown, no corroboration and no assessed "
        "selected attributes, P = B = 0.70 × 0.25 + 0.20 × 0.25 = 0.225 "
        "(22.5%, displayed as 22% after rounding). An unassessed prior is shown "
        "in neutral gray; no absence of concern is treated as a positive assessment.",
        "Attribute coverage c = sum of normalized selected weights with a cited "
        "non-unknown assessment. Attribute fit A = sum(weight × assessed utility) / c. "
        "Screening priority P = (1 − c) × B + c × A; when c = 0, P = B and A is "
        "undefined. Unknown attributes do not receive invented utilities. More "
        "attribute evidence can raise or lower priority while replacing the "
        "baseline in proportion to its selected importance.",
        "Adverse tier: 0 = no adverse application/stability assessment, 1 = mixed, "
        "2 = concern. The strongest adverse assessment is retained, including "
        "stability criteria with zero selected weight. Sort by tier ascending, "
        "then priority descending; identical tier and score tie. Name and source "
        "identity only order tied rows and do not break the scientific tie.",
        "Corroboration counts distinct works with support or mixed application "
        "assessments, grouping matching DOIs or normalized titles across indexes; "
        "a URL is used only when both identifiers are missing. Wikipedia does not "
        "contribute to this count. The capped count "
        "is not a popularity score, proof of independent replication or a "
        "credibility assessment.",
        "",
        "Candidate calculations and evidence:",
    ]
    used = set()
    for row in ranked:
        general = row["general_evidence"]
        utilities = {
            "supports": 1,
            "mixed": 0.5,
            "concern": 0,
            "unknown": general["unknown_utility"],
        }
        observed = (
            "unknown" if row["observed_fit"] is None else f"{row['observed_fit']:.4f}"
        )
        lines += [
            "",
            material(row) + ":",
            f"Baseline B = {row['preliminary_score']:.4f}; "
            f"attribute fit A = {observed}; "
            f"attribute coverage c = {row['coverage']:.4f}; "
            f"screening priority P = {row['priority_score']:.4f}. "
            f"Tier {row['priority_tier']}: {tier_labels[row['priority_tier']]}. "
            f"Ranking basis: {basis_labels[row['ranking_basis']]}. "
            f"Application utility R = {utilities[general['application_fit']]:.4f}; "
            "demonstrated-use utility U = "
            f"{utilities[general['demonstrated_use']]:.4f}. "
            f"Distinct corroborating works: {general['corroborating_work_count']}; "
            f"capped corroboration: {general['corroboration']:.4f}.",
            *_table(
                [
                    "Criterion",
                    "Selected importance",
                    "Passage assessment",
                    "Remaining uncertainty",
                ],
                [
                    [
                        criterion_label(item["criterion_id"]),
                        (
                            "Preliminary component"
                            if item["criterion_id"]
                            in {"application_fit", "demonstrated_use"}
                            else f"{definitions[item['criterion_id']]['weight']:.1%}"
                        ),
                        _literature_assessment_text(
                            {**item, "assessments": [assessment] if assessment else []},
                            references,
                            detailed=True,
                        ),
                        (
                            "Unassessed; the general review prior applies, "
                            "not a favorable finding."
                            if item["judgment"] == "unknown"
                            and item["criterion_id"]
                            in {"application_fit", "demonstrated_use"}
                            else (
                                "No cited assessment; this attribute remains unknown."
                                if item["judgment"] == "unknown"
                                else "Source-based interpretation; confirm material "
                                "identity, "
                                "phase, method and conditions."
                            )
                        ),
                    ]
                    for item in row["criteria"]
                    for assessment in item["assessments"] or [None]
                ],
            ),
        ]
        seen = set()
        for citation in [
            *mentions.get(row["lead_id"], {}).get("citations", []),
            *(
                assessment.get("citation", assessment)
                for item in row["criteria"]
                for assessment in item["assessments"]
            ),
        ]:
            identity = (citation["url"], citation["quote"])
            if identity in seen:
                continue
            seen.add(identity)
            used.add(citation["url"])
            lines.append(
                f"- Supporting passage [{references[citation['url']]['id']}]: "
                f"“{_text(citation['quote'])}”"
            )
    lines += ["", "Candidate assessment references:"]
    lines.extend(
        f"- [{row['id']}] {row['title']} · {row['source_name']}"
        for url, row in references.items()
        if url in used
    )
    return lines


def _preliminary_outcome(literature: dict | None) -> str | None:
    if not literature or literature.get("version") != "literature-fit-v2":
        return None
    rows = literature["ranked_candidates"]
    if not rows:
        return None
    assessed = sum(row["coverage"] > 0 for row in rows)
    return (
        f"{len(rows)} candidates ranked for review from retrieved public-source "
        f"passages; {assessed} have assessments for selected attributes. "
        "The shortlist includes candidates needing further evidence, with "
        "application and stability concerns identified separately."
    )


def _preliminary_property_diagnostic(value, *, scoped=True) -> str:
    """Scope legacy property-stage notices without editing archived
    diagnostics."""
    note = _text(value)
    replacements = {
        "No scored material shortlist was generated.": (
            "No separate measured-property shortlist was generated."
        ),
        "No scored shortlist was produced.": (
            "No separate measured-property shortlist was produced."
        ),
        "Retrieved records did not yield an eligible scored candidate.": (
            "Retrieved property records did not yield an eligible scored "
            "property record."
        ),
        "No material properties, stability assessments or ranking scores "
        "were established for this question. Reference order is not a "
        "ranking of material performance.": (
            "No quantitative material properties or verified stability observations "
            "were established by the property-retrieval stage. Preliminary "
            "screening priority uses separately attributed source interpretations."
        ),
    }
    for original, replacement in replacements.items():
        note = note.replace(original, replacement)
    return ("Measured-property evidence: " if scoped else "") + note


def _attribute_lines(
    result: dict, sources: list[dict], *, audit: bool, detailed: bool = False
) -> list[str]:
    followup = result.get("attribute_research")
    if not isinstance(followup, dict) or followup.get("status") in {
        "not_needed",
        "disabled",
    }:
        return []
    attributes = followup.get("attributes", [])
    passages = [p for attribute in attributes for p in attribute.get("passages", [])]
    articles = {p["source_url"] for p in passages}
    lines = ["", "Literature follow-up:"]
    current_context = followup.get("assessment_context_version") in {
        "attribute-passages-v1",
        "attribute-passages-v2",
    }
    if current_context:
        from labcat.science.candidate_leads import _body_documents

        # Saved status flags describe orchestration, never proof that evidence
        # entered a score. Rebind both the body documents and accepted judgments.
        body_ids = {
            document["document_id"]
            for source in sources
            if _public_source(source)
            for document, _ in _body_documents(source)
        }
        evaluation = validated_literature_evaluation(result, sources) or {}
        judgments = [
            proposal
            for proposal in evaluation.get("proposals", [])
            if proposal["document_id"] in body_ids
        ]
        informative = sum(proposal["judgment"] != "unknown" for proposal in judgments)
        lines.append(
            f"Targeted follow-up retained {len(passages)} passages from "
            f"{len(articles)} open-access articles. "
            f"{len(body_ids)} complete source-bound body passages are retained "
            "for qualitative attribute assessment."
        )
        if informative:
            lines.append(
                f"{informative} non-unknown assessments cite these body passages "
                "in the saved qualitative evaluation. These interpretations can "
                "affect screening priority or concern tiers where the corresponding "
                "criterion applies. They do not create measured property values."
            )
        else:
            lines.append(
                "No informative assessment cites these body passages in the saved "
                "evaluation. Retrieved excerpts alone do not change screening "
                "priority or fill missing measured properties."
            )
        from labcat.research import _targeted_abstract_documents

        abstract_ids = {
            document["document_id"]
            for document in _targeted_abstract_documents(followup, sources)
        }
        if abstract_ids:
            selected = {row["attribute_id"] for row in attributes}
            abstract_judgments = [
                row
                for row in evaluation.get("proposals", [])
                if row["document_id"] in abstract_ids
                and row["criterion_id"] in selected
            ]
            abstract_informative = sum(
                row["judgment"] != "unknown" for row in abstract_judgments
            )
            lines.append(
                f"Targeted follow-up also retained {len(abstract_ids)} public "
                f"abstracts. {abstract_informative} non-unknown selected-attribute "
                "assessments cite these abstracts in the saved evaluation. "
                "These are qualitative interpretations, not measured values; "
                "no publisher full text was downloaded for these references."
            )
        if not audit:
            return lines
        lines.append(
            "In this workflow, the first general application assessment is retained "
            "before targeted follow-up is offered for attribute refinement. "
            "Full-text availability does not establish matching material phase, "
            "sample, conditions, units or method. Cropped or unbound excerpts "
            "remain review leads and cannot authorize an assessment. "
            f"Body-passage assessment attempts: {len(judgments)}; "
            f"informative judgments: {informative}; "
            f"explicit unknown judgments: {len(judgments) - informative}."
        )
    elif not audit:
        lines.append(
            f"Targeted follow-up retained {len(passages)} passages from "
            f"{len(articles)} open-access articles. These unverified review "
            "leads do not fill missing properties or change "
            + (
                "the screening priority."
                if _preliminary_outcome(result.get("literature_evaluation"))
                else "the ranking."
            )
        )
        return lines
    else:
        lines.append(
            "Repository properties were checked before targeted literature "
            "searches. Material phase, sample, units and method remain unverified; "
            "excerpts do not change scores."
        )
    labels = {
        "review_leads": "Review leads found",
        "abstract_review_leads": "Public abstracts retained for review",
        "no_results": "No matching passage",
        "not_supported": "Not supported",
        "budget_exhausted": "Lookup limit reached",
        "unavailable": "Source unavailable",
        "not_found": "No matching passage",
    }
    for attribute in attributes:
        status = labels.get(
            attribute["status"], attribute["status"].replace("_", " ").capitalize()
        )
        lines.append(
            f"- {_label(attribute['attribute_id'])}: {status}; "
            f"{attribute.get('articles_read', 0)} articles skimmed, "
            f"{len(attribute.get('passages', []))} passages retained."
            + (
                f" {len(attribute['abstract_source_urls'])} public abstracts retained."
                if attribute.get("abstract_source_urls")
                else ""
            )
        )
    references = {ref["url"]: ref for ref in citation_references(result, sources)}
    for attribute in attributes:
        for passage in attribute.get("passages", [])[: 2 if detailed else 1]:
            source = references.get(passage["source_url"])
            if source is None:
                continue
            lines += [
                "",
                f"{_label(attribute['attribute_id'])} · [{source['id']}]:",
                "“" + _excerpt(passage["text"], 600 if detailed else 280) + "”",
                _text(
                    passage.get(
                        "caveat",
                        "Review applicability to the shortlisted material "
                        "before using this passage.",
                    )
                ),
            ]
    if passages:
        lines.append(
            "The full passages, source sections and retrieval provenance "
            "remain in Audit details and the JSON archive."
        )
    return lines


def _screening_note(result: dict) -> str | None:
    """Describe only the saved, validated screening decision, never
    today's default."""
    preferences = result.get("ranking", {}).get("screening_preferences")
    if not isinstance(preferences, dict):
        return None
    target = preferences.get("target_band_gap_ev")
    tolerance = preferences.get("band_gap_tolerance_ev")
    target_note = ""
    if (
        preferences.get("target_band_gap_active") is True
        and type(target) in (int, float)
        and math.isfinite(target)
        and 0 <= target <= 100
        and type(tolerance) in (int, float)
        and math.isfinite(tolerance)
        and 0 < tolerance <= 100
    ):
        target_note = (
            f"Requested band-gap target: {target:g} eV. Ranking favors retrieved "
            f"gaps nearer this target, with {tolerance:g} eV as the soft preference "
            "scale (half band-gap utility at that distance). These settings are "
            "preferences, not measurements, uncertainty or an acceptance window. "
            "Source methods and missing properties still need review."
        )
    minimum = preferences.get("minimum_band_gap_ev")
    if (
        preferences.get("minimum_band_gap_active") is not True
        or type(minimum) not in (int, float)
        or not math.isfinite(minimum)
        or not 0 <= minimum <= 100
    ):
        return target_note or None
    return (
        f"Saved screening preference: minimum band gap {minimum:g} eV, inclusive. "
        "Records with a known source band gap below this value were excluded; "
        "the threshold itself is an application preference, not a scientific "
        "measurement. Unknown band gaps remain for evidence review and are not "
        "treated as meeting or failing the minimum. Exclusion reasons remain "
        "in Audit details. " + target_note
    )


def _stability_note(result: dict) -> str | None:
    """Expose separate stability gaps without upgrading a hull value to
    a claim."""
    assessments = [
        row.get("stability_assessment") for row in result.get("candidates", [])
    ]
    if not assessments or not all(
        isinstance(value, dict) and value.get("schema") == "stability-assessment-v1"
        for value in assessments
    ):
        return None  # Historical reports keep their original evidence contract.
    unknown = []
    for key, label in (
        ("ambient_phase", "room-temperature phase stability"),
        ("operational", "stability under operating conditions"),
    ):
        count = sum(
            value.get(key, {}).get("status") == "unknown" for value in assessments
        )
        if count:
            unknown.append(
                f"{label} is unassessed for {count} of {len(assessments)} candidates"
            )
    if not unknown:
        return None
    return (
        "; ".join(unknown).capitalize()
        + ". Energy above hull describes the source calculation's thermodynamic "
        "comparison; a zero value does not establish stability in air, moisture, "
        "heat or light. Review phase- and condition-matched stability evidence "
        "before treating a candidate as suitable."
    )


def _research_completion_lines(result: dict) -> list[str]:
    execution = result.get("execution", {})
    if (
        execution.get("model_stopped_after_report") is True
        and execution.get("stop_reason") == "server_report_retained"
        and isinstance(execution.get("agent"), dict)
        and execution["agent"].get("status") == "stopped_after_report"
    ):
        return [
            "",
            "Research completion:",
            "",
            "The server retained this report, then stopped the model process. "
            "Final inference usage was unavailable. Existing assessment gaps "
            "remain unchanged; report generation does not establish scientific "
            "suitability.",
        ]
    if result.get("execution", {}).get("model_interrupted") is not True:
        return []
    return [
        "",
        "Research completion:",
        "",
        (
            "Model-led research stopped before completion. The server retained the "
            "available evidence and completed the configured public-source stages "
            "without another model call. This partial report may have fewer candidate "
            "leads and incomplete assessments or search coverage."
            if result.get("execution", {}).get("completion_version")
            == "bounded-recovery-v2"
            or _preliminary_outcome(result.get("literature_evaluation"))
            else "The model connection stopped after the request was assessed. "
            "The server "
            "completed the configured public-source stages without another model call. "
            "This partial report may have fewer candidate leads and incomplete "
            "search coverage."
        ),
    ]


def _candidate_assessment_lines(result: dict, literature: dict | None) -> list[str]:
    """Count retained general judgments from the validated v2 bundle
    only.

    Provider completion and cached plan counters do not prove
    assessments were submitted. Explicit unknown judgments count as
    submitted; missing ones do not. Older v2 reports need no metadata
    migration and v1 output is unchanged.
    """
    if (
        not isinstance(literature, dict)
        or literature.get("version") != "literature-fit-v2"
    ):
        return []
    rows = [*literature["ranked_candidates"], *literature["unranked_candidates"]]
    general = ("application_fit", "demonstrated_use")
    retained = {
        (proposal["lead_id"], proposal["criterion_id"])
        for proposal in literature["proposals"]
        if proposal["criterion_id"] in general
    }
    missing = [
        sum((row["lead_id"], criterion) not in retained for criterion in general)
        for row in rows
    ]
    count = sum(missing)
    if not count:
        return []
    provider_completed = (
        result.get("execution", {}).get("agent", {}).get("status") == "completed"
    )
    return [
        "",
        "Candidate assessment:",
        "",
        (
            "The provider run completed, but candidate assessment is incomplete. "
            if provider_completed
            else "Candidate assessment is incomplete. "
        )
        + f"{count} application relevance or demonstrated use "
        + ("judgment is" if count == 1 else "judgments are")
        + f" missing across {sum(value > 0 for value in missing)} of {len(rows)} "
        "candidates. The general screening calculation uses the disclosed "
        "review prior for these missing judgments.",
    ]


def _review_record_lines(
    result: dict, sources: list[dict], *, audit: bool
) -> list[str]:
    records = result.get("review_records", [])
    if not records:
        return []
    if not isinstance(records, list) or len(records) > 12 or result.get("candidates"):
        raise ValueError("Invalid unscored source-record display.")
    review = _goal_review(result)
    if not review or not review["unscored_attributes"]:
        raise ValueError("Unscored source records require reviewed goal preferences.")
    references = _reference_map(sources)
    seen, entries = set(), []
    for record in records:
        _comparison_record(record)
        identifier = record["material_id"]
        if identifier in seen or "rank" in record or "score" in record:
            raise ValueError("Unscored source records must not carry a ranking.")
        seen.add(identifier)
        provenance = record["provenance"]
        citations = [
            references[source["source_id"]]
            for source in sources
            if source.get("source_id") in references
            and source["source_id"] in record.get("source_ids", [])
            and source.get("record_id") == identifier
            and source.get("url") == provenance.get("source_url")
            and all(
                source.get("provenance", {}).get(key) == provenance.get(key)
                for key in ("raw_fields_sha256", "response_sha256")
            )
        ]
        if not citations:
            raise ValueError("Unscored source records require verified citations.")
        values = [
            ("Energy above hull" if key == "stability" else label)
            + ": "
            + _number(record[field], unit)
            for key, (label, field, unit) in CRITERIA.items()
            if field
            and record.get(field) is not None
            and result["ranking"]["weights"].get(key, 0) > 0
        ]
        entries.append(
            "- "
            + _text(display_formula(record["formula"]))
            + " "
            + " ".join(f"[{value}]" for value in citations)
            + ": "
            + ("; ".join(values) or "No selected scalar property was available.")
        )
    shown = entries if audit else entries[:3]
    return [
        "",
        "Unscored material evidence:",
        "",
        "These source records retain their reported values for review. No rank or "
        "overall score is assigned because no selected criterion has both usable "
        "evidence and a supported requested scoring rule.",
        *shown,
        *(
            [
                f"Showing {len(shown)} of {len(entries)} retained records; "
                "the Technical Overview includes the full retained set."
            ]
            if len(shown) < len(entries)
            else []
        ),
    ]


def _summary(
    result: dict, config: AppConfig, sources: list[dict], literature: dict | None = None
) -> str:
    candidates = result.get("candidates", [])
    references = _reference_map(sources)
    preliminary = _preliminary_outcome(literature)
    lines = [
        "Summary:",
        "",
        preliminary or _text(result.get("summary", result.get("reason", ""))),
    ]
    lines += _source_coverage_lines(result)
    lines += _research_completion_lines(result)
    lines += _candidate_assessment_lines(result, literature)
    lines += _goal_lines(result)
    if not preliminary:
        lines += _review_record_lines(result, sources, audit=False)
    lines += _literature_lines(
        literature,
        sources,
        audit=False,
        leads=result.get("candidate_leads", []),
        result=result,
    )
    if preliminary:
        lines += _review_record_lines(result, sources, audit=False)
    screening = _screening_note(result)
    if screening:
        lines += ["", screening]
    if not candidates:
        # Discovery can replace the headline with a reference count. Retain the
        # quantitative failure/coverage reason so a useful bibliography cannot
        # disguise an unavailable adapter or an unconfigured source connection.
        seen = set(map(_text, lines))
        for reason in (
            result.get("reason"),
            result.get("retrieval", {}).get("reason"),
            result.get("ranking", {}).get("reason"),
        ):
            if reason and _text(reason) not in seen:
                lines += [
                    "",
                    (
                        _preliminary_property_diagnostic(reason)
                        if preliminary
                        else _text(reason)
                    ),
                ]
                seen.add(_text(reason))
        lines += [
            "",
            (
                "The candidate shortlist above provides a preliminary review order. "
                "No separate measured-property ranking was produced; missing "
                "measurements and phase-matched comparisons remain evidence gaps."
                if preliminary
                else (
                    "The provisional literature shortlist above is available "
                    "for review. "
                    "No separate measured-property ranking was produced; reported "
                    "measurements, phase matching and unassessed criteria still need "
                    "verification."
                    if literature and literature["ranked_candidates"]
                    else "There is not enough validated, relevant property evidence to "
                    "recommend a ranked material shortlist from this run. "
                    "The next step "
                    "is to review the public-source coverage and resolve the missing "
                    "evidence before selecting candidates for experiments."
                )
            ),
        ]
        if not literature:
            lines += _candidate_lead_lines(result, sources, audit=False)
        lines += _comparison_lines(result, sources, audit=False)
        lines += _references(
            sources,
            references,
            result.get("review_records", []),
            result.get("comparison_records"),
        )
        discovery = result.get("public_discovery", {})
        seen.update(map(_text, discovery.get("caveats", [])))
        limitations = []
        for note in result.get("limitations", []):
            clean = _text(note)
            if clean and clean not in seen:
                limitations.append(
                    _preliminary_property_diagnostic(clean, scoped=False)
                    if preliminary
                    else clean
                )
                seen.add(clean)
        if limitations:
            lines += ["", "Evidence limits:", "", " ".join(limitations)]
        lines += _attribute_lines(result, sources, audit=False)
        lines += _discovery(result, sources, audit=False)
        return "\n".join(lines) + "\n"

    leader = candidates[0]
    leading = [_rationale(leader, key) for key in _criteria(leader, limit=2)]
    if all(
        _score_analysis(row, result)["status"] == "needs_evidence" for row in candidates
    ):
        lines += [
            "",
            "All listed records lack required application evidence or a supported "
            "requested scoring rule and remain "
            "evidence-review leads, not supported application recommendations.",
        ]
    lines += [
        "",
        f"{_identity(leader, references)} is the first candidate to review "
        f"under the selected ranking preferences, with a supported score of "
        f"{leader['score']:.4f}. "
        + (
            f"Its score is driven most by {_join(leading)}. "
            if leading
            else "No selected criterion contributes a positive utility. "
        )
        + _analysis_note(leader, result),
    ]
    tied = [row for row in candidates[1:] if row["score"] == leader["score"]]
    if tied:
        lines += [
            "",
            "The leading score is tied with "
            + _join([_identity(row, references) for row in tied])
            + ". Record identifiers determine the displayed order within this "
            "tie; the score does not establish a scientific preference between them.",
        ]
    elif len(candidates) > 1 and config.presentation.verbosity != "concise":
        runner = candidates[1]
        lines += [
            "",
            f"{_identity(runner, references)} is the next-ranked alternative "
            f"(supported score {runner['score']:.4f}). "
            + (
                "Its leading contribution is "
                f"{_rationale(runner, _criteria(runner)[0])}. "
                if _criteria(runner)
                else "Its selected criteria add no positive utility. "
            )
            + "Compare the missing "
            "criteria and source methods before interpreting this score difference.",
        ]
    shown = candidates[:3]
    lines += ["", "Supporting property records:" if literature else "Shortlist:"]
    lines += _structured_table(result["report_tables"]["summary"])
    lines += [
        "",
        f"This compact table shows {len(shown)} of {len(candidates)} "
        "shortlisted compositions. The Technical View contains all records, "
        "evidence coverage and methods.",
    ]
    lines += _comparison_lines(result, sources, audit=False)
    stability = _stability_note(result)
    if stability:
        lines += ["", "Stability review:", "", stability]
    missing = sorted({key for row in candidates for key in _missing_evidence(row)})
    lines += ["", "Research limitations:", ""]
    if missing:
        lines.append(
            "Evidence is missing for one or more shortlisted candidates in "
            + _join([_label(key) for key in missing])
            + ". Missing criteria add no supported contribution and their weights "
            "are not redistributed. This records an evidence gap, not a measured "
            "zero. Missing evidence is not evidence of poor material performance."
        )
    if result.get("ranking", {}).get("weights", {}).get("evidence_quality", 0) > 0:
        lines.append(
            "Supported-field completeness (the evidence_quality criterion) counts "
            "available fields in the application's fixed supported-property set. "
            "Selected importance coverage instead measures the share of this "
            "profile's weight with usable evidence; it appears in the Technical "
            "View record details. Neither measure is scientific confidence."
        )
    lines += [
        "The search is bounded rather than exhaustive. Scores are derived "
        "preferences, not measurements, confidence estimates or probabilities "
        "of experimental success. Composition and bulk calculations do not "
        "establish a material class or device, film, processing or nanoscale "
        "performance; compound safety remains unassessed. Review the underlying "
        "public records and missing properties before an experimental decision.",
    ]
    if config.presentation.terminology in {"technical", "specialist"}:
        lines += [
            "",
            "Utilities are normalized across all selected criteria; source "
            "phases and calculation methods remain distinct. No cross-phase "
            "property joins or uncertainty calibration were performed.",
        ]
    elif config.presentation.terminology == "research":
        lines += [
            "",
            "The weighted score compares available source properties against "
            "the chosen preferences. It cannot replace validation of the "
            "reported phase and calculation method.",
        ]
    if config.presentation.verbosity == "detailed":
        notes = list(dict.fromkeys(note for row in shown for note in row["caveats"]))
        if notes:
            lines += [
                "",
                "For the displayed candidates, " + " ".join(map(_text, notes)),
            ]
    lines += _references(
        sources, references, shown + tied, result.get("comparison_records")
    )
    if not literature:
        lines += _candidate_lead_lines(result, sources, audit=False)
    lines += _attribute_lines(result, sources, audit=False)
    lines += _discovery(result, sources, audit=False)
    return "\n".join(lines) + "\n"


def _overview(
    result: dict, config: AppConfig, sources: list[dict], literature: dict | None = None
) -> str:
    candidates = result.get("candidates", [])
    references = _reference_map(sources)
    ranking = result.get("ranking", {})
    execution = result.get("execution", {})
    preliminary = _preliminary_outcome(literature)
    detailed = config.presentation.verbosity == "detailed"
    lines = [
        "Technical View:",
        "",
        "Scope and outcome:",
        "",
        preliminary or _text(result.get("summary", result.get("reason", ""))),
    ]
    lines += _source_coverage_lines(result)
    lines += _research_completion_lines(result)
    lines += _candidate_assessment_lines(result, literature)
    lines += _goal_lines(result)
    if not preliminary:
        lines += _review_record_lines(result, sources, audit=True)
    lines += _literature_lines(
        literature,
        sources,
        audit=True,
        leads=result.get("candidate_leads", []),
        result=result,
    )
    if preliminary:
        lines += _review_record_lines(result, sources, audit=True)
    profile = execution.get("ranking_profile")
    if isinstance(profile, dict):
        name = profile.get("name")
        label = (
            _text(name)[:120]
            if isinstance(name, str) and name.strip()
            else "Saved ranking preferences"
        )
        lines += ["Ranking profile: " + label + "."]
    if candidates:
        stability = _stability_note(result)
        if stability:
            lines += ["", "Stability review:", "", stability]
        shared_caveats = [
            note
            for note in candidates[0]["caveats"]
            if all(note in row["caveats"] for row in candidates)
        ]
        lines += [
            "",
            "Supporting property records:" if literature else "Expanded shortlist:",
            *_structured_table(result["report_tables"]["technical"]),
            "",
            "Supported score sums the weighted contributions of known criteria on an "
            "absolute 0–1 scale. It is not a probability, confidence estimate "
            "or measured property. Unknown and unsupported criteria add no "
            "supported contribution; their weights are not redistributed. "
            "Missing evidence is not evidence of poor material performance.",
            "",
            "Candidate comparison:",
        ]
        for candidate in candidates:
            analysis = _score_analysis(candidate, result)
            lines += [
                "",
                _identity(candidate, references) + ":",
                f"Supported score {candidate['score']:.4f}. Leading contributions: "
                + (
                    _join(
                        [
                            _rationale(candidate, key)
                            for key in _criteria(candidate, limit=2)
                        ]
                    )
                    or "No positive contribution"
                )
                + ".",
                (
                    "Requested utility review"
                    if candidate.get("unscored_goal_reasons")
                    else _analysis_label(analysis)
                )
                + ". "
                + _analysis_note(candidate, result),
                f"Fit on known criteria: {analysis['observed_fit']:.4f}; "
                "the observed part of the profile only, not overall application "
                "suitability.",
                "Missing selected criteria: "
                + (
                    _join([_label(key) for key in _missing_evidence(candidate)])
                    or "None among selected criteria"
                )
                + ".",
            ]
            if analysis["coverage"] < 1 - 1e-7:
                lines.append(
                    (
                        "Unscored-criteria score bound: "
                        if candidate.get("unscored_goal_reasons")
                        else "Missing-criteria score range: "
                    )
                    + f"{candidate['score']:.4f}–"
                    f"{analysis['possible_upper_score']:.4f} "
                    "with known utilities held fixed."
                    + (
                        " Unsupported requested utilities require a reviewed scoring "
                        "rule; additional measurements alone cannot fill this weight."
                        if candidate.get("unscored_goal_reasons")
                        else ""
                    )
                )
            for note in list(dict.fromkeys(candidate["caveats"])):
                if note in shared_caveats:
                    continue
                lines.append("- " + _text(note))
            if detailed:
                available = [
                    _evidence(candidate, key)
                    for key, (_, field, _) in CRITERIA.items()
                    if field and candidate.get(field) is not None
                ]
                lines.extend("- " + item for item in available)
        missing = sorted({key for row in candidates for key in _missing_evidence(row)})
        lines += ["", "Next evidence checks:"]
        if shared_caveats:
            lines.extend("- " + _text(note) for note in dict.fromkeys(shared_caveats))
        if missing:
            lines.append(
                "Prioritize "
                + _join([_label(key) for key in missing])
                + " in source records with matching composition, phase and "
                "method. Treat the current order as provisional until these "
                "gaps are assessed."
            )
        lines.append(
            "Compare the source calculations and material phases before an "
            "experimental decision. Bulk composition matches do not establish "
            "device, film, processing or nanoscale performance, and compound "
            "safety remains unassessed."
        )
    else:
        lines += [
            "",
            (
                "The candidate shortlist above provides a preliminary review order. "
                "No separate measured-property ranking was produced."
                if preliminary
                else (
                    "A provisional literature shortlist is shown above. No separate "
                    "measured-property ranking was produced."
                    if literature and literature["ranked_candidates"]
                    else "No scored shortlist was produced. No scientific candidate "
                    "rows "
                    "were substituted."
                )
            ),
        ]
        reason = result.get("reason") or ranking.get("reason")
        if reason and reason != result.get("summary"):
            lines.append(
                _preliminary_property_diagnostic(reason)
                if preliminary
                else _text(reason)
            )
    lines += _comparison_lines(result, sources, audit=True)
    if not literature:
        lines += _candidate_lead_lines(result, sources, audit=True)
    lines += [
        "",
        "Measured-property ranking method:" if preliminary else "Ranking method:",
    ]
    if preliminary:
        lines.append(
            "This section describes the separate property table. Preliminary "
            "screening follows the method above and does not require complete "
            "measured attributes."
        )
    screening = _screening_note(result)
    if screening:
        lines.append(screening)
    weights = ranking.get("weights", {})
    if weights:
        lines.append(
            "Selected importance: "
            + "; ".join(
                f"{_label(key)} {weight:.1%}"
                for key, weight in weights.items()
                if weight > 0
            )
            + "."
        )
    lines.append(
        "In the separate property table, coverage is the fraction of selected "
        "importance with usable property evidence for each record."
        if preliminary
        else "Selected importance coverage is the fraction of the profile's total "
        "weight with usable evidence. It is shown separately for each candidate."
    )
    if any(_score_analysis(row, result)["coverage"] < 1 - 1e-7 for row in candidates):
        lines.append(
            "Fit on known criteria divides the supported score by coverage. "
            "The missing-criteria score range holds known utilities fixed and lets "
            "each missing utility vary from 0 to 1. This is a mathematical bound, "
            "not a prediction or confidence interval; no missing property is filled."
        )
    if weights.get("evidence_quality", 0) > 0:
        lines.append(
            "Supported-field completeness (the evidence_quality criterion) is "
            "the fraction of seven supported property fields present: band "
            "gap, total and electronic dielectric scalars, energy above hull, "
            "density, bulk modulus and shear modulus. It uses this fixed field "
            "set regardless of the selected ranking profile. Both completeness "
            "measures are derived, not scientific confidence, measurement "
            "accuracy or evidence quality assessments."
        )
    if config.presentation.terminology in {"technical", "specialist"}:
        lines.append(
            ("Measured-property utilities" if preliminary else "Utilities")
            + " use the recorded fixed anchors; no uncertainty "
            "calibration, cross-phase property joins or missing-weight "
            "redistribution is performed."
        )
    else:
        lines.append(
            "The separate property-table rules convert supported source properties "
            "into preference utilities. These are distinct from preliminary "
            "screening priority; neither score demonstrates fitness for the "
            "intended use."
            if preliminary
            else "The scoring rules convert supported source properties into "
            "preference utilities. The strongest available score does not "
            "demonstrate fitness for the intended use."
        )
    if detailed:
        for key, rule in ranking.get("normalization", {}).items():
            if weights.get(key, 0) > 0:
                lines.append("- " + _label(key) + ": " + _text(rule))
    retrieval = result.get("retrieval", {})
    lines += ["", "Retrieval and methods:"]
    repository = retrieval.get("selected_repository")
    if repository:
        lines.append(
            "Quantitative source: "
            + {
                "nomad": "NOMAD public archive",
                "materials_project": "Materials Project",
                "public_dielectric": (
                    "Public dielectric dataset (historical calculations)"
                ),
                "multiple_public_repositories": "Multiple public repositories",
            }.get(repository, _text(repository))
            + "."
        )
    count = retrieval.get("records_retrieved")
    if type(count) is int:
        lines.append(
            f"{count} quantitative property records retrieved; {len(candidates)} "
            "entries in the separate measured-property table. The preliminary "
            f"shortlist contains {len(literature['ranked_candidates'])} cited "
            "candidates. Retrieval is bounded, not an exhaustive search."
            if preliminary
            else f"{count} public records retrieved; {len(candidates)} distinct "
            f"compositions shortlisted. This is a bounded sample, not an "
            f"exhaustive search."
        )
    methods = list(dict.fromkeys(_text(row["method"]) for row in candidates))
    lines.extend("- " + method for method in methods)
    excluded = ranking.get("excluded_records", [])
    if excluded:
        lines.append(
            f"{len(excluded)} records were excluded by the saved eligibility "
            f"or element-screening rules. Full reasons remain in Audit details."
        )
    alternatives = ranking.get("alternative_phase_ids", [])
    if alternatives:
        lines.append(
            f"{len(alternatives)} alternate records were omitted to retain one "
            f"record per formula; properties were not merged across phases."
        )
    lines += _attribute_lines(result, sources, audit=True, detailed=detailed)
    lines += _references(
        sources,
        references,
        candidates + result.get("review_records", []),
        result.get("comparison_records"),
    )
    lines += _discovery(result, sources, audit=True)
    lines += [
        "",
        "Audit archive:",
        "Record identifiers, full source URLs, raw source fields, response "
        "hashes, complete passages and execution metadata are retained in "
        "Audit details and the JSON archive. They are not additional "
        "scientific evidence.",
    ]
    return "\n".join(lines) + "\n"


def _first_table(lines: list[str]) -> list[str]:
    """Extract a generated shortlist, without parsing source or model
    prose."""
    for index, line in enumerate(lines[:-1]):
        if line.startswith("| ") and lines[index + 1].startswith("| ---"):
            end = index + 2
            while end < len(lines) and lines[end].startswith("| "):
                end += 1
            return lines[index:end]
    return []


def _without_lines(lines: list[str], removed: list[str]) -> list[str]:
    """Remove one exact renderer-produced block; retain all other audit
    text."""
    if removed:
        for index in range(len(lines) - len(removed) + 1):
            if lines[index : index + len(removed)] == removed:
                return lines[:index] + lines[index + len(removed) :]
    return lines


def _results_first(
    result: dict,
    sources: list[dict],
    literature: dict | None,
    text: str,
    *,
    audit: bool,
) -> str:
    """Separate the decision-facing report from its complete analysis
    appendix.

    Every table and supporting detail is produced by the existing
    validated renderers. This changes presentation only, never
    candidates, scores, cited observations or stored reports. The screen
    collapses the final appendix; downloads retain its complete text in
    the same order.
    """
    narrative = findings_lines(
        result, literature, citation_references(result, sources), audit=audit
    )
    discussion_start = next(
        (
            i
            for i, line in enumerate(narrative)
            if line == "Interpretation and tradeoffs:"
        ),
        len(narrative),
    )
    opening, discussion = narrative[:discussion_start], narrative[discussion_start:]
    details = text.splitlines()[2:]
    supporting_discussion = []
    if literature and "Supporting property evidence:" in discussion:
        support_start = discussion.index("Supporting property evidence:")
        supporting_discussion = discussion[support_start:]
        discussion = discussion[:support_start]
    shortlists = []
    if literature:
        table = _first_table(
            _literature_lines(
                literature,
                sources,
                audit=audit,
                leads=result.get("candidate_leads", []),
                result=result,
            )
        )
        if table:
            heading = (
                "Candidate shortlist:"
                if _preliminary_outcome(literature)
                else "Provisional literature shortlist:"
            )
            shortlists.append((heading, table))
    if result.get("candidates"):
        table = _structured_table(
            result["report_tables"]["technical" if audit else "summary"]
        )
        if table:
            shortlists.append(
                (
                    (
                        "Supporting property records:"
                        if literature
                        else "Expanded shortlist:" if audit else "Shortlist:"
                    ),
                    table,
                )
            )
    elif not literature:
        table = _first_table(_candidate_lead_lines(result, sources, audit=audit))
        if table:
            shortlists.append(("Source-grounded candidates:", table))
    for heading, table in shortlists:
        details = _without_lines(details, table)
        # Keep the explanation of each table in the appendix, without leaving
        # an empty second shortlist heading after moving its rows to the front.
        details = [
            "How to read the " + heading[:-1].lower() + ":" if line == heading else line
            for line in details
        ]
    lines = ["Technical View:" if audit else "Summary:", "", *opening]
    if shortlists:
        heading, table = shortlists[0]
        lines += ["", heading, "", *table]
    lines += ["", *discussion]
    comparisons = _comparison_lines(result, sources, audit=audit)
    if comparisons:
        details = _without_lines(details, comparisons)
        if literature:
            supporting_discussion += comparisons
        else:
            lines += comparisons
    for heading, table in shortlists[1:]:
        details = [
            heading,
            "",
            "These database records provide property and structure evidence. "
            "Their property score is separate from the application-based candidate "
            "ranking above. A shared composition alone does not confirm the same "
            "phase or suitability for the requested application.",
            "",
            *table,
            "",
            *supporting_discussion,
            "",
            *details,
        ]
    if not shortlists:
        retained = _review_record_lines(result, sources, audit=audit)
        lines += retained
        details = _without_lines(details, retained)
    if audit:
        details += narrative_audit_lines(
            result, literature, citation_references(result, sources)
        )
    lines += ["", "Search and analysis details:", "", *details]
    return "\n".join(lines).rstrip() + "\n"


def render_reports(
    result: dict, config: AppConfig, sources: list[dict]
) -> tuple[str, str]:
    """Report text stays readable; the caller retains full JSON in
    ``result``."""
    sources = report_scoped_sources(result, sources)
    result["report_tables"] = report_tables(result, sources)
    literature = validated_literature_evaluation(result, sources)
    if result.get("stage") == "blocked":
        reason = _text(result["reason"])
        summary = (
            "Summary:\n\n" + reason + "\n\nNo scientific shortlist was produced "
            "and no material-property claims were reported.\n"
        )
        return summary, _overview(result, config, sources, literature)
    return _results_first(
        result,
        sources,
        literature,
        _summary(result, config, sources, literature),
        audit=False,
    ), _results_first(
        result,
        sources,
        literature,
        _overview(result, config, sources, literature),
        audit=True,
    )
