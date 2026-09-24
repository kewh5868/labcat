"""Compare adapter-verified observations without inventing material
equivalence.

Only HybriD³ currently supplies a reviewed experimental qualifier and
the sample/property/condition fields needed for within-source
comparisons. Other sources can be shown alongside it, but composition
alone never grants priority.
"""

import math
from collections import defaultdict

from .preferences import composition_key

VERSION = "experimental-precedence-v1"
MAX_COMPARISON_PAIRS = 24
MAX_COMPARISON_RECORDS = 36
_COMPUTED_SOURCES = frozenset(
    {"public_snapshot", "live_public_dielectric", "live_materials_project"}
)
_GAP_KINDS = {
    "band gap (fundamental)": "fundamental",
    "band gap (fundamental, calculated) (dft-hse06+soc)": "fundamental",
    "band gap (optical, theory)": "optical",
    "band gap (optical, transmission)": "optical",
    "band gap (optical, diffuse reflectance)": "optical",
    "band gap (optical, integrating sphere)": "optical",
    "band gap (band edge difference)": "band_edge_difference",
}


def _raw(record):
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return {}
    value = provenance.get("raw_fields", {})
    return value if isinstance(value, dict) else {}


def evidence_method(record):
    """Method classification uses adapter fields, never a narrative
    keyword."""
    if record.get("source_mode") == "live_hybrid3":
        flag = _raw(record).get("is_experimental")
        if type(flag) is bool:
            return "experimental" if flag else "computed"
    if record.get("source_mode") in _COMPUTED_SOURCES:
        return "computed"
    return "unknown"


def _text(value):
    return (
        value.strip().casefold() if isinstance(value, str) and value.strip() else None
    )


def _context_text(value):
    text = _text(value)
    return (
        None
        if text
        in {
            "unknown",
            "unspecified",
            "not specified",
            "n/a",
            "none",
            "null",
            "-",
            "?",
            "default",
            "dataset",
            "subset",
            "sample",
            "phase",
        }
        else text
    )


def _conditions(raw):
    rows = raw.get("conditions")
    if not isinstance(rows, list) or not rows:
        return None
    values = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        number, error = row.get("value"), row.get("uncertainty")
        name, unit = _text(row.get("property")), _text(row.get("unit"))
        if (
            not name
            or not unit
            or type(number) not in (int, float)
            or not math.isfinite(number)
            or (
                error is not None
                and (
                    type(error) not in (int, float)
                    or not math.isfinite(error)
                    or error < 0
                )
            )
        ):
            return None
        # No assumed room temperature, pressure, unit conversion or omission.
        values.append((name, float(number), unit, repr(error)))
    return tuple(sorted(values)) if len(set(values)) == len(values) else None


def _scope(record):
    raw = _raw(record)
    system = raw.get("system_id")
    return {
        "source": record.get("source_mode"),
        "system": system if type(system) is int and system > 0 else None,
        "property": _GAP_KINDS.get(_text(raw.get("property"))),
        "phase label": _context_text(raw.get("subset_label")),
        "crystal system": _context_text(raw.get("crystal_system")),
        "space group": _context_text(raw.get("space_group")),
        "sample type": _context_text(raw.get("sample_type")),
        "conditions": _conditions(raw),
    }


def _key(record):
    scope = _scope(record)
    if scope["source"] != "live_hybrid3" or any(
        value is None for value in scope.values()
    ):
        return None
    return (composition_key(record["formula"]), *scope.values())


def _value(record):
    value = record.get("band_gap_ev")
    return (
        float(value)
        if type(value) in (int, float) and math.isfinite(value) and value >= 0
        else None
    )


def _endpoint(record):
    provenance = record.get("provenance", {})
    return {
        "material_id": record["material_id"],
        "formula": record["formula"],
        "value": _value(record),
        "source_url": provenance.get("source_url"),
        "source_mode": record.get("source_mode"),
        "raw_fields_sha256": provenance.get("raw_fields_sha256"),
        "response_sha256": provenance.get("response_sha256"),
        "property_kind": record.get("band_gap_kind"),
    }


def _comparison(experiment, calculation):
    left, right = _scope(experiment), _scope(calculation)
    reasons = []
    if left["source"] != "live_hybrid3" or right["source"] != "live_hybrid3":
        reasons.append(
            "Cross-source material, phase and condition equivalence is unverified."
        )
    else:
        for field in left:
            if field == "source":
                continue
            if left[field] is None or right[field] is None:
                reasons.append(
                    f"Explicit {field} is missing; equivalence is unverified."
                )
            elif left[field] != right[field]:
                reasons.append(f"Source {field} differs.")
    return {
        "property": "band_gap_ev",
        "property_label": "Band gap",
        "unit": "eV",
        "experimental": _endpoint(experiment),
        "computed": _endpoint(calculation),
        "status": "not_comparable" if reasons else "comparable",
        "delta_computed_minus_experimental": (
            None if reasons else _value(calculation) - _value(experiment)
        ),
        "reasons": reasons
        or [
            "Source system, composition, gap kind, phase label, crystal system, "
            "space group, sample type and explicit fixed conditions match. "
            "This metadata match is not an independent structure determination."
        ],
    }


def compare_observations(experiment, calculation):
    """Recompute a saved pair from provenance-bound original adapter
    records.

    Callers must bind these records to their retained public source
    provenance. Pair labels, saved deltas and narrative method fields
    grant no authority.
    """
    if (
        not isinstance(experiment, dict)
        or not isinstance(calculation, dict)
        or evidence_method(experiment) != "experimental"
        or evidence_method(calculation) != "computed"
        or _value(experiment) is None
        or _value(calculation) is None
    ):
        raise ValueError(
            "Comparison requires explicit experimental and computed records."
        )
    try:
        same_composition = composition_key(experiment["formula"]) == composition_key(
            calculation["formula"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "Comparison requires validated material compositions."
        ) from error
    if not same_composition:
        raise ValueError(
            "Comparison observations have different material compositions."
        )
    return _comparison(experiment, calculation)


def experimental_scope_key(record):
    """Return a complete scope only for an explicitly experimental
    observation."""
    if (
        not isinstance(record, dict)
        or evidence_method(record) != "experimental"
        or _value(record) is None
    ):
        return None
    try:
        return _key(record)
    except (KeyError, TypeError, ValueError):
        return None


def experimental_range_from_records(records, *, context=None):
    """Recompute retained experimental extrema without claiming an
    unseen count.

    ``records`` are the one or two retained extrema, not necessarily
    every experiment evaluated at initial ranking. No original
    population count or selection reason can be validated from those
    extrema alone.
    """
    if not isinstance(records, list) or not 1 <= len(records) <= 2:
        raise ValueError("Experimental range requires retained extrema.")
    keys = [experimental_scope_key(record) for record in records]
    if keys[0] is None or any(key != keys[0] for key in keys):
        raise ValueError("Experimental range requires matching experimental scopes.")
    if context is not None:
        if (
            not isinstance(context, dict)
            or evidence_method(context) not in {"experimental", "computed"}
            or _key(context) != keys[0]
        ):
            raise ValueError("Experimental range does not match its material context.")
    identities = [record["material_id"] for record in records]
    if len(set(identities)) != len(identities):
        raise ValueError("Experimental range extrema must have distinct identities.")
    values = [_value(record) for record in records]
    return {
        "minimum": min(values),
        "maximum": max(values),
        "unit": "eV",
        "record_ids": sorted(identities),
    }


def compare_and_select_records(
    records, *, band_gap_active=True, minimum_band_gap_ev=None, target_band_gap_ev=None
):
    """Prefer intact experimental records before eligibility and utility
    scoring.

    The full supplied experiment set determines precedence. Presentation
    bounds apply only afterwards and cannot rescue a favorable computed
    alternative.
    """
    by_id = {row["material_id"]: row for row in records}
    if len(by_id) != len(records):
        raise ValueError("Conflicting duplicate material identity in source records.")
    groups, compositions = defaultdict(list), defaultdict(list)
    metadata, suppressed = {}, {}
    for row in records:
        method = evidence_method(row)
        identity = row["material_id"]
        metadata[identity] = {
            "version": VERSION,
            "evidence_method": method,
            "recommendation_basis": method,
            "selection_reason": (
                "Experimental source record; no verified comparable "
                "calculation was supplied."
                if method == "experimental"
                else (
                    "Computed source record; no applicable comparable "
                    "experiment was supplied."
                    if method == "computed"
                    else "Source method is unclassified; no experimental "
                    "preference is inferred."
                )
            ),
            "experimental_precedence_applied": False,
            "experimental_record_ids": [],
            "computed_record_ids": [],
            "comparisons": [],
            "experimental_range": None,
        }
        if _value(row) is not None:
            compositions[composition_key(row["formula"])].append(row)
            if method in {"experimental", "computed"} and (key := _key(row)):
                groups[key].append(row)

    ranges = []
    for rows in groups.values():
        experiments = [row for row in rows if evidence_method(row) == "experimental"]
        calculations = [row for row in rows if evidence_method(row) == "computed"]
        if not experiments:
            continue
        if len(experiments) == 1 and not calculations:
            continue
        failures = [
            row
            for row in experiments
            if band_gap_active
            and minimum_band_gap_ev is not None
            and _value(row) < minimum_band_gap_ev
        ]
        if failures:
            selected = min(failures, key=lambda row: (_value(row), row["material_id"]))
            reason = (
                "At least one comparable experiment fails the active minimum; "
                "the lowest is retained."
            )
        elif band_gap_active and target_band_gap_ev is not None:
            selected = min(
                experiments,
                key=lambda row: (
                    -abs(_value(row) - target_band_gap_ev),
                    row["material_id"],
                ),
            )
            reason = (
                "Comparable experiments are retained conservatively using "
                "the least favorable target fit."
            )
        else:
            selected = min(
                experiments, key=lambda row: (_value(row), row["material_id"])
            )
            reason = (
                "Comparable experiments are retained conservatively using "
                "the lowest reported gap."
            )
        selected_id = selected["material_id"]
        if len(experiments) == 1:
            reason = (
                "Applicable experimental evidence takes precedence over "
                "comparable computed evidence."
            )
        for row in rows:
            identity = row["material_id"]
            metadata[identity]["experimental_precedence_applied"] = bool(calculations)
            metadata[identity]["recommendation_basis"] = "experimental"
            metadata[identity]["selection_reason"] = reason + (
                " The intact experimental record is used; unrelated computed "
                "properties are not merged."
            )
            if identity != selected_id:
                suppressed[identity] = {
                    "material_id": identity,
                    "formula": row["formula"],
                    "reasons": [
                        f"Experimental evidence preference selects {selected_id}. "
                        f"{reason}"
                    ],
                    "provenance": {
                        name: row.get("provenance", {}).get(name)
                        for name in (
                            "source_url",
                            "response_sha256",
                            "raw_fields_sha256",
                        )
                    },
                }
        if len(experiments) > 1:
            extrema = [
                min(experiments, key=lambda row: (_value(row), row["material_id"])),
                max(experiments, key=lambda row: (_value(row), row["material_id"])),
            ]
            ranges.append((rows, extrema, len(experiments)))

    pair_count = 0
    pair_groups = []
    for rows in sorted(
        compositions.values(),
        key=lambda group: min(row["material_id"] for row in group),
    ):
        experiments = [row for row in rows if evidence_method(row) == "experimental"]
        calculations = [row for row in rows if evidence_method(row) == "computed"]
        pair_count += len(experiments) * len(calculations)
        pair_groups.append(
            (
                sorted(experiments, key=lambda row: row["material_id"]),
                sorted(calculations, key=lambda row: row["material_id"]),
            )
        )
    retained_ids, displayed = set(), []
    # Generate only bounded displayed objects, even for a large source batch.
    keys = {identity: _key(row) for identity, row in by_id.items()}
    for comparable in (True, False):
        for is_suppressed in (False, True):
            for experiments, calculations in pair_groups:
                for exp in experiments:
                    if (exp["material_id"] in suppressed) != is_suppressed:
                        continue
                    for calc in calculations:
                        if len(displayed) >= MAX_COMPARISON_PAIRS:
                            break
                        left, right = exp["material_id"], calc["material_id"]
                        matches = keys[left] is not None and keys[left] == keys[right]
                        if matches != comparable:
                            continue
                        identities = {left, right}
                        if len(retained_ids | identities) > MAX_COMPARISON_RECORDS:
                            continue
                        pair = compare_observations(exp, calc)
                        displayed.append(pair)
                        retained_ids.update(identities)
                        for identity in identities:
                            metadata[identity]["comparisons"].append(pair)
    omitted_ranges = 0
    for rows, extrema, count in ranges:
        identities = {row["material_id"] for row in extrema}
        if len(retained_ids | identities) > MAX_COMPARISON_RECORDS:
            omitted_ranges += 1
            continue
        retained_ids.update(identities)
        for row in rows:
            metadata[row["material_id"]]["experimental_range"] = {
                "minimum": _value(extrema[0]),
                "maximum": _value(extrema[1]),
                "unit": "eV",
                "record_ids": sorted(identities),
                "count": count,
                "interpretation": "Range of comparable source experiments, "
                "not an uncertainty interval.",
            }
    for item in metadata.values():
        for kind in ("experimental", "computed"):
            item[f"{kind}_record_ids"] = sorted(
                {pair[kind]["material_id"] for pair in item["comparisons"]}
            )
    selected_records = [
        {**row, "evidence_comparison": metadata[row["material_id"]]}
        for row in records
        if row["material_id"] not in suppressed
    ]
    audit = {
        "evidence_comparison_policy": {
            "version": VERSION,
            "preference": "Applicable experimental data before filtering and ranking; "
            "no averaging or cross-phase property merging.",
            "matching": "Same verified HybriD³ system/composition, gap kind, "
            "explicit phase label/crystal system/space group/sample type "
            "and fixed conditions.",
            "multiple_experiments": "Minimum failures first, otherwise least "
            "favorable active target fit or lowest gap; all supplied experiments "
            "participate before display limits.",
            "unknown": "Unclassified methods and unmatched phases, gap kinds or "
            "conditions do not establish a discrepancy or grant experimental "
            "precedence.",
            "displayed_pairs": len(displayed),
            "omitted_pairs": pair_count - len(displayed),
            "omitted_experimental_ranges": omitted_ranges,
            "pair_limit": MAX_COMPARISON_PAIRS,
            "record_limit": MAX_COMPARISON_RECORDS,
        },
        "evidence_comparisons": [
            {
                "material_id": identity,
                "formula": by_id[identity]["formula"],
                "selected_for_ranking": identity not in suppressed,
                **metadata[identity],
            }
            for identity in sorted(retained_ids)
        ],
        "comparison_record_ids": sorted(retained_ids),
        "experimental_preference_excluded_records": list(suppressed.values()),
    }
    return selected_records, audit
