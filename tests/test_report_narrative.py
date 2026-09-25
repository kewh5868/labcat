"""Synthetic presentation fixtures only; no scientific recommendation
evidence."""

from copy import deepcopy

import pytest
from test_evidence_comparison_reporting import adapter_record, source_for

from labcat.config import load_config
from labcat.science.ranking import rank_records
from labcat.science.report_narrative import findings_lines, narrative_audit_lines
from labcat.science.reporting import citation_references


def literature_case(*rows):
    """Small renderer-contract data; source admission has separate
    tests."""
    definitions = [
        {
            "criterion_id": "application_fit",
            "label": "Application relevance",
            "weight": 0,
        },
        {"criterion_id": "band_gap", "label": "Band gap", "weight": 1},
        {
            "criterion_id": "operational_stability",
            "label": "Operational stability",
            "weight": 0,
        },
    ]
    evaluation = {
        "version": "literature-fit-v2",
        "ranked_candidates": [],
        "unranked_candidates": [],
        "criteria": definitions,
    }
    result = {"candidates": [], "candidate_leads": []}
    references = []
    for index, settings in enumerate(rows, 1):
        name = settings.get("name", f"TEST ONLY candidate {index}")
        url = f"https://openalex.org/W{index}"
        references.append({"id": f"S{index}", "url": url})
        result["candidate_leads"].append(
            {"id": str(index), "name": name, "citations": [{"url": url}]}
        )
        criteria = []
        for definition in definitions:
            key = definition["criterion_id"]
            judgment = settings.get(key, "unknown")
            assessments = (
                []
                if judgment == "unknown"
                else [
                    {
                        "judgment": judgment,
                        "interpretation": settings.get(
                            "interpretation",
                            f"TEST ONLY assessment for {name} and {key}.",
                        ),
                        "url": url,
                    }
                ]
            )
            criteria.append(
                {"criterion_id": key, "judgment": judgment, "assessments": assessments}
            )
        evaluation["ranked_candidates"].append(
            {
                "lead_id": str(index),
                "name": name,
                "rank": settings.get("rank", index),
                "priority_tier": settings.get("tier", 0),
                "priority_score": settings.get("score", 0.8),
                "coverage": int(settings.get("band_gap", "unknown") != "unknown"),
                "stability_unknown": (
                    ["operational_stability"]
                    if settings.get("operational_stability", "unknown") == "unknown"
                    else []
                ),
                "criteria": criteria,
            }
        )
    return result, evaluation, references


def prose(case, *, audit=False):
    return "\n".join(findings_lines(*case, audit=audit))


def audit_prose(case):
    return "\n".join(narrative_audit_lines(*case))


def test_supported_candidates_lead_with_named_reason_and_attributed_interpretation():
    case = literature_case(
        {"application_fit": "supports", "band_gap": "supports"},
        {"application_fit": "supports"},
    )
    original = deepcopy(case)
    summary = prose(case)
    assert summary.startswith("Findings and recommendations:\n")
    opening, discussion = summary.split("Interpretation and tradeoffs:")
    assert "Start the literature review with TEST ONLY candidate 1 [S1]" in opening
    assert "support application relevance and band gap" in opening
    assert "candidate 2 [S2] is the next-listed alternative" in opening
    assert (
        "Why consider it: source-based assessments of Application relevance"
        in discussion
    )
    assert "support — “TEST ONLY" in discussion
    assert "What still needs checking: Band gap" in discussion
    assert "Stability remains incompletely assessed" in discussion
    assert "Qualitative assessments cover" not in summary
    assert "Qualitative assessments cover" not in prose(case, audit=True)
    assert "Qualitative assessments cover 100%" in audit_prose(case)
    assert case == original


def test_unknown_prior_is_never_recommended_as_suitable_and_ties_are_honest():
    case = literature_case({"rank": 1}, {"rank": 1})
    text = prose(case)
    assert "no favorable criterion assessment establishing suitability" in text
    assert "shares its rank" in text
    assert "Start the literature review" not in text
    assert "next-listed alternative for review" not in text
    assert "What still needs checking: Band gap" in text


def test_high_adverse_score_cannot_supplant_server_order_or_become_recommendation():
    case = literature_case(
        {"name": "TEST ONLY supported", "application_fit": "supports", "score": 0.4},
        {
            "name": "TEST ONLY concern",
            "application_fit": "supports",
            "operational_stability": "concern",
            "tier": 2,
            "score": 0.99,
        },
    )
    text = prose(case)
    assert text.index("TEST ONLY supported") < text.index("TEST ONLY concern")
    assert (
        "next in the retained order, also needs its adverse "
        "or mixed assessments resolved" in text
    )
    assert "Operational stability: concern" in text
    assert "Favorable passages do not cancel" in text
    case[1]["ranked_candidates"].reverse()
    # A historical order beginning with a concern is not a recommendation.
    text = prose(case)
    assert "appears first in the literature order but has reported" in text
    assert "Start the literature review" not in text


def test_mixed_assessments_keep_both_sides_and_do_not_invent_matching_conditions():
    case = literature_case({"application_fit": "mixed", "tier": 1})
    item = case[1]["ranked_candidates"][0]["criteria"][0]
    item["assessments"] = [
        {
            "judgment": "supports",
            "interpretation": "TEST ONLY favorable assessment.",
            "url": case[2][0]["url"],
        },
        {
            "judgment": "concern",
            "interpretation": "TEST ONLY adverse assessment.",
            "url": case[2][0]["url"],
        },
    ]
    text = prose(case, audit=True)
    assert "favorable assessment" in text and "adverse assessment" in text
    assert "do not establish that those conditions match" in text
    assert "has reported application or stability concerns" in text


def test_candidates_never_inherit_another_materials_assessment_or_citation():
    case = literature_case(
        {
            "name": "TEST ONLY Alpha",
            "application_fit": "supports",
            "interpretation": "TEST ONLY Alpha-specific interpretation.",
        },
        {
            "name": "TEST ONLY Beta",
            "operational_stability": "concern",
            "tier": 2,
            "interpretation": "TEST ONLY Beta-specific interpretation.",
        },
    )
    text = prose(case, audit=True)
    alpha, beta = text.split("Candidate 1 — TEST ONLY Alpha:", 1)[1].split(
        "Candidate 2 — TEST ONLY Beta:"
    )
    beta = beta.split("Comparison of the leading candidates:")[0]
    assert "Alpha-specific" in alpha and "[S1]" in alpha
    assert "Beta-specific" not in alpha and "[S2]" not in alpha
    assert "Beta-specific" in beta and "[S2]" in beta
    assert "Alpha-specific" not in beta and "[S1]" not in beta


def test_source_text_stays_on_one_bounded_structural_line():
    case = literature_case(
        {
            "name": "TEST ONLY\nInjected heading:\n| pipe |",
            "application_fit": "supports",
            "interpretation": "TEST ONLY\n- injected bullet\r\n" + "word " * 1000,
        }
    )
    lines = findings_lines(*case, audit=True)
    assert all(
        "\n" not in line and "\r" not in line and "|" not in line for line in lines
    )
    assert not any(
        line.startswith(("Injected heading:", "- injected bullet")) for line in lines
    )
    assert max(map(len, lines)) < 1500


def measured_case(*records):
    ranked, ranking = rank_records(
        list(records), load_config(), importance={"band_gap": 1}
    )
    result = {
        "candidates": ranked,
        "ranking": ranking,
        "comparison_records": list(records),
    }
    sources = [source_for(row) for row in records]
    return result, None, citation_references(result, sources)


def test_measured_findings_use_selected_experimental_record_and_retained_comparison():
    case = measured_case(adapter_record(1, 2.0, True), adapter_record(2, 1.5, False))
    text = prose(case)
    assert "Review SiO2 [R1] first" in text
    assert "largest score contributions come from band gap 2 eV" in text
    assert "experimental source record reports band gap 2 eV" in text
    assert "experimental band gap is 2 eV [R1]" in text
    assert "matched computed value is 1.5 eV [R2]" in text
    assert "differs by -0.5 eV" in text
    assert "100% of selected importance" in text
    assert "Keep the experimental record as the screening basis" in text


def test_unmatched_records_do_not_gain_discrepancy_or_experimental_substitution():
    case = measured_case(
        adapter_record(1, 2.0, True),
        adapter_record(2, 1.5, False, phase="TEST ONLY other phase"),
    )
    text = prose(case)
    assert "lack matching source context" in text
    assert "differs by" not in text
    assert "Keep the experimental record" not in text


def test_changed_comparison_cannot_become_findings():
    case = measured_case(adapter_record(1, 2.0, True), adapter_record(2, 1.5, False))
    pair = case[0]["candidates"][0]["evidence_comparison"]["comparisons"][0]
    pair["delta_computed_minus_experimental"] = 0.5
    with pytest.raises(ValueError, match="comparison"):
        prose(case)


def test_measured_ties_and_required_gaps_are_preserved():
    case = measured_case(
        adapter_record(1, 2.0, False), adapter_record(2, 2.0, False, formula="TiO2")
    )
    assert "shares the leading score" in prose(case)
    for row in case[0]["candidates"]:
        row["score_analysis"]["missing_required_criteria"] = ["dielectric_total"]
        row["missing_selected_criteria"] = ["dielectric_total"]
    text = prose(case)
    assert (
        "still needs Total dielectric response before it can support "
        "an application recommendation" in text
    )
    assert "Resolve missing Total dielectric response evidence" in text


def test_legacy_leads_and_empty_evidence_get_useful_review_actions():
    case = literature_case({})
    result, _, references = case
    text = prose((result, None, references))
    assert (
        "public passages identify TEST ONLY candidate 1 [S1] as leads for review"
        in text
    )
    assert "mention alone does not establish application suitability" in text
    assert "actual demonstration of the intended use" in text
    empty = prose(({}, None, []))
    assert "does not yet establish a preferred material" in empty
    assert "source counts and material mentions cannot decide suitability" in empty


def test_legacy_literature_keeps_unknown_candidates_unranked():
    case = literature_case({})
    evaluation = case[1]
    evaluation["version"] = "literature-fit-v1"
    evaluation["unranked_candidates"] = evaluation.pop("ranked_candidates")
    evaluation["ranked_candidates"] = []
    text = prose(case)
    assert "no favorable criterion assessment establishing suitability" in text
    assert "shares its rank" not in text


def test_shared_criterion_tradeoff_is_cited_without_joining_scientific_contexts():
    case = literature_case(
        {"name": "TEST ONLY Alpha", "band_gap": "supports"},
        {"name": "TEST ONLY Beta", "band_gap": "mixed"},
    )
    text = prose(case)
    assert "One assessed tradeoff between TEST ONLY Alpha [S1]" in text
    assert "TEST ONLY Beta [S2] is band gap" in text
    assert "first has support" in text and "second has mixed evidence" in text
    assert "conditions still need matching before a direct material comparison" in text
    case = literature_case({"band_gap": "supports"}, {"application_fit": "supports"})
    assert "One assessed tradeoff" not in prose(case)


def test_derived_criteria_are_not_attributed_as_source_reported_properties():
    record = adapter_record(1, 2.0, True)
    ranked, ranking = rank_records(
        [record], load_config(), importance={"simplicity": 1, "evidence_quality": 1}
    )
    result = {"candidates": ranked, "ranking": ranking}
    text = prose((result, None, citation_references(result, [source_for(record)])))
    assert "The ranking also favors" in text
    assert "source-formula elements (composition simplicity)" in text
    assert "supported-field completeness" in text
    assert "source record reports" not in text


def test_legacy_property_gap_uses_prevalidated_table_analysis():
    case = measured_case(adapter_record(1, 2.0, True))
    row = case[0]["candidates"][0]
    row.pop("score_analysis")
    case[0]["report_tables"] = {
        "technical": {
            "rows": [
                {
                    "material_id": row["material_id"],
                    "score_analysis": {
                        "missing_required_criteria": ["dielectric_total"]
                    },
                }
            ]
        }
    }
    assert "still needs Total dielectric response" in prose(case)


def test_stability_assessment_is_preserved_when_hull_energy_is_missing():
    case = measured_case(adapter_record(1, 2.0, True))
    row = case[0]["candidates"][0]
    row["stability_assessment"]["operational"] = {
        "status": "concern",
        "interpretation": "TEST ONLY scoped stability concern.",
    }
    text = prose(case)
    assert "Operational stability assessment (concern)" in text
    assert "TEST ONLY scoped stability concern" in text
    assert "thermodynamic stability and ambient phase stability" in text
    assert "operational stability remain unresolved" not in text


def test_literature_opening_does_not_promote_unlinked_property_records():
    result, evaluation, references = literature_case({"application_fit": "supports"})
    measured, _, property_references = measured_case(adapter_record(1, 2.0, True))
    result.update(measured)
    case = result, evaluation, references + property_references
    text = prose(case)
    opening = text.split("Interpretation and tradeoffs:")[0]
    assert "TEST ONLY candidate" in opening
    assert "SiO2" not in text
    technical = prose(case, audit=True)
    assert "Supporting property evidence:" in technical
    assert "Property record 1 — SiO2:" in technical
    assert "require a validated match" in technical
    assert "Review SiO2" not in technical
    assert "Comparison of the leading property records:" not in technical
    assert "band gap 2 eV [S1]" not in text


@pytest.mark.parametrize("evaluated", [False, True])
def test_unassessed_leads_explain_found_source_context_without_promoting_it(evaluated):
    result, evaluation, references = literature_case({})
    lead = result["candidate_leads"][0]
    lead["citations"][0]["quote"] = (
        "TEST ONLY candidate 1 is a comparison in this synthetic discussion. "
        "No suitability is established."
    )
    text = prose((result, evaluation if evaluated else None, references))
    assert "What the source describes (quoted context)" in text
    assert "No suitability is established.” [S1]" in text
    assert "not an assessed suitability finding" in text
    assert "Start the literature review" not in text


def test_technical_literature_discusses_every_candidate_and_weighted_tradeoffs():
    case = literature_case(
        {"name": "TEST ONLY Alpha", "band_gap": "supports"},
        {
            "name": "TEST ONLY Beta",
            "band_gap": "mixed",
            "operational_stability": "concern",
            "tier": 2,
        },
        {
            "name": "TEST ONLY Gamma",
            "band_gap": "concern",
            "operational_stability": "supports",
        },
        {"name": "TEST ONLY Delta", "application_fit": "supports"},
    )
    case[1]["criteria"][1]["weight"] = 0.75
    case[1]["criteria"][1]["goal"] = {"relation": "target", "target_band_gap_ev": 1.78}
    case[1]["criteria"][2]["weight"] = 0.25
    for row in case[1]["ranked_candidates"]:
        row["coverage"] = sum(
            definition["weight"]
            for definition, item in zip(
                case[1]["criteria"], row["criteria"], strict=True
            )
            if item["judgment"] != "unknown"
        )
        row["ranking_basis"] = "blended"
    original = deepcopy(case)
    summary, technical = prose(case), prose(case, audit=True)
    assert len(technical) > len(summary)
    for index, name in enumerate(("Alpha", "Beta", "Gamma", "Delta"), 1):
        assert f"Candidate {index} — TEST ONLY {name}:\n\n" in technical
    assert "- TEST ONLY Delta" not in summary
    assert technical.count(" compared with ") == 2
    assert "Comparison of the leading candidates:" not in summary
    arithmetic = audit_prose(case)
    assert "carries 75.0% of attribute importance (target 1.78 eV)" in arithmetic
    assert "carries 25.0% of attribute importance" in arithmetic
    assert "remaining 25.0% supplied by preliminary application evidence" in arithmetic
    assert "attribute importance" not in technical
    assert "support for TEST ONLY Alpha [S1], versus mixed evidence" in technical
    assert "concern for TEST ONLY Beta [S2]" in technical
    assert "favorable attribute fit cannot cancel" in technical
    assert case == original, "expanded discussion cannot alter rankings or evidence"


def test_technical_literature_includes_criteria_beyond_the_first_two_and_unranked():
    case = literature_case({"application_fit": "supports", "band_gap": "supports"}, {})
    case[1]["version"] = "literature-fit-v1"
    unranked = case[1]["ranked_candidates"].pop()
    unranked["rank"] = None
    case[1]["unranked_candidates"].append(unranked)
    case[1]["ranked_candidates"][0]["criteria"].append(
        {
            "criterion_id": "density",
            "judgment": "supports",
            "assessments": [
                {
                    "judgment": "supports",
                    "url": case[2][0]["url"],
                    "interpretation": "TEST ONLY extra density interpretation.",
                }
            ],
        }
    )
    text = prose(case, audit=True)
    assert "TEST ONLY extra density interpretation" in text
    assert "Candidate 2 — TEST ONLY candidate 2:\n\nTEST ONLY candidate 2 [S2]" in text
    assert "shares the saved rank" not in text


def test_technical_sparse_ties_do_not_invent_comparison_or_stability():
    case = literature_case({"rank": 1}, {"rank": 1}, {"rank": 1})
    for row in case[1]["ranked_candidates"]:
        row["ranking_basis"] = "preliminary"
    text = prose(case, audit=True)
    assert (
        "No shared, cited criterion assessment distinguishes these candidates" in text
    )
    assert "They share the saved rank, so no winner is established" in text
    assert "priority remains entirely preliminary" in audit_prose(case)
    assert (
        "none of the selected attribute importance has an assessed finding"
        in audit_prose(case)
    )
    assert "Stability remains incompletely assessed" in text
    assert "support for TEST ONLY" not in text
    assert "demonstrated stability" not in text
    assert "Comparing" not in prose(({}, None, []), audit=True)


def test_technical_comparison_requires_candidate_specific_reference_for_judgment():
    case = literature_case({"band_gap": "supports"}, {"band_gap": "concern"})
    # A missing report reference cannot be borrowed from the other candidate.
    case[2].pop(0)
    comparison = next(
        line for line in findings_lines(*case, audit=True) if " compared with " in line
    )
    assert "concern for TEST ONLY candidate 2 [S2]" in comparison
    assert "unresolved for TEST ONLY candidate 1" in comparison
    assert "support for TEST ONLY candidate 1" not in comparison
    assert "[S1]" not in comparison


def test_technical_compares_assessed_alternatives_when_the_first_lead_is_unknown():
    case = literature_case({}, {"band_gap": "supports"}, {"band_gap": "concern"})
    text = prose(case, audit=True)
    assert "TEST ONLY candidate 2 compared with TEST ONLY candidate 3" in text
    assert "support for TEST ONLY candidate 2 [S2]" in text
    assert "concern for TEST ONLY candidate 3 [S3]" in text
    assert "no favorable criterion assessment establishing suitability" in text


def test_technical_measured_discussion_shows_actual_weight_dependent_tradeoffs():
    records = [
        adapter_record(1, 1.0, True),
        adapter_record(2, 3.0, False, formula="CaTiO3"),
    ]
    sources = [source_for(row) for row in records]
    texts, winners = [], []
    for importance in (
        {"band_gap": 0.8, "simplicity": 0.2},
        {"band_gap": 0.2, "simplicity": 0.8},
    ):
        ranked, ranking = rank_records(records, load_config(), importance=importance)
        result = {"candidates": ranked, "ranking": ranking}
        case = result, None, citation_references(result, sources)
        summary, technical = prose(case), prose(case, audit=True)
        assert "Comparison of the leading property records:" in technical
        assert "Comparison of the leading property records:" not in summary
        assert len(technical) > len(summary) * 1.5
        assert "Composition simplicity" in technical and "Band gap" in technical
        assert "saved contribution" not in technical
        assert "derived screening feature" in audit_prose(case)
        assert "not measurements from a matched comparative experiment" in technical
        winners.append(ranked[0]["formula"])
        texts.append(audit_prose(case))
    assert winners == ["CaTiO3", "SiO2"]
    assert "Band gap has 80.0% of selected importance" in texts[0]
    assert "Composition simplicity has 80.0% of selected importance" in texts[1]
    for contribution in ("0.3000", "0.1000"):
        assert "saved contribution is " + contribution in texts[0]
    for contribution in ("0.8000", "0.4000"):
        assert "saved contribution is " + contribution in texts[1]


def test_technical_measured_context_and_all_matched_discrepancies_are_retained():
    case = measured_case(
        adapter_record(1, 2.0, True),
        adapter_record(2, 1.5, False),
        adapter_record(3, 1.8, False),
    )
    technical = prose(case, audit=True)
    assert "source phase label “TEST ONLY matched phase”" in technical
    assert "sample “single crystal”" in technical
    assert "reported conditions temperature 300 K" in technical
    assert "gap type “band gap (fundamental)”" in technical
    assert "matched computed value is 1.5 eV" in technical
    assert "matched computed value is 1.8 eV" in technical
    assert "differs by -0.5 eV" in technical and "differs by -0.2 eV" in technical
    assert technical.count("Keep the experimental record as the screening basis") == 1
    assert "source context.\n\nThe retained experimental band gap" in technical
    assert "matched computed value is 1.8 eV" not in prose(case)


def test_technical_zero_utility_measurement_is_discussed_without_calling_it_missing():
    case = measured_case(
        adapter_record(1, 0.0, False),
        adapter_record(2, 0.0, False, formula="TiO2"),
    )
    text = prose(case, audit=True)
    assert "computed source record reports band gap 0 eV" in text
    assert "zero contribution here comes from the assessed utility" in audit_prose(case)
    assert "Their supported scores are tied" in text
    assert "this criterion does not distinguish their screening utility" in text
    assert "source record reports band gap" not in prose(case)


def test_technical_target_direction_is_preference_not_larger_gap_recommendation():
    records = [
        adapter_record(1, 1.8, True),
        adapter_record(2, 3, False, formula="TiO2"),
    ]
    ranked, ranking = rank_records(
        records,
        load_config(),
        importance={"band_gap": 1},
        target_band_gap_ev=1.8,
        band_gap_tolerance_ev=0.2,
    )
    result = {"candidates": ranked, "ranking": ranking}
    refs = citation_references(result, [source_for(row) for row in records])
    text = audit_prose((result, None, refs))
    assert "selected target of 1.8 eV" in text
    assert "preference tolerance of 0.2 eV" in text
    assert "larger gap is therefore not automatically preferred" in text
    assert "not an experimental uncertainty" in text
    assert ranked[0]["formula"] == "SiO2"


def test_property_records_keep_distinct_identity_and_bounded_comparison():
    case = measured_case(
        *(
            adapter_record(index, float(index), False, formula=formula)
            for index, formula in enumerate(
                ("SiO2", "TiO2", "CaTiO3", "Al2O3", "MgO", "HfO2"), 1
            )
        )
    )
    text = prose(case, audit=True)
    for index, row in enumerate(case[0]["candidates"], 1):
        assert f"Property record {index} — {row['formula']}:\n\n" in text
        assert row["formula"] in text
    comparisons = text.split("Comparison of the leading property records:\n\n")[1]
    assert comparisons.count(" compared with ") == 2
    assert (
        comparisons.count("not measurements from a matched comparative experiment") == 1
    )
    assert "selected importance" not in comparisons
    assert "saved contribution" not in comparisons
    assert "0–1 utility scale" not in text
    assert "0–1 utility scale" in audit_prose(case)


def test_leakage_assessment_stays_with_its_candidate_without_inventing_cross_support():
    case = literature_case({"name": "TEST ONLY Alpha", "band_gap": "supports"}, {})
    case[1]["criteria"].append({"criterion_id": "leakage_current", "weight": 0.5})
    for index, row in enumerate(case[1]["ranked_candidates"]):
        row["criteria"].append(
            {
                "criterion_id": "leakage_current",
                "judgment": "concern" if index == 0 else "unknown",
                "assessments": (
                    [
                        {
                            "judgment": "concern",
                            "url": case[2][0]["url"],
                            "interpretation": (
                                "TEST ONLY leakage concern for this sample."
                            ),
                        }
                    ]
                    if index == 0
                    else []
                ),
            }
        )
    text = prose(case, audit=True)
    alpha, beta = text.split("Candidate 1 — TEST ONLY Alpha:")[1].split("Candidate 2 —")
    beta = beta.split("Comparison of the leading candidates:")[0]
    assert "Leakage current: concern" in alpha
    assert "TEST ONLY leakage concern for this sample.” [S1]" in alpha
    assert "Leakage current" in beta
    assert "leakage concern" not in beta and "[S1]" not in beta


def test_assessed_technical_candidate_keeps_one_bounded_cited_public_excerpt():
    case = literature_case(
        {"name": "TEST ONLY Alpha", "application_fit": "supports"},
        {"name": "TEST ONLY Beta", "band_gap": "supports"},
    )
    case[0]["candidate_leads"][0]["citations"][0]["quote"] = (
        "TEST ONLY source passage reports a dielectric scalar of 25 and "
        "a band gap of 4.0 eV for the stated sample. " + "Context " * 100
    )
    case[0]["candidate_leads"][0]["citations"].append(
        {"url": case[2][0]["url"], "quote": "TEST ONLY second source passage."}
    )
    text = prose(case, audit=True)
    alpha, beta = text.split("Candidate 1 — TEST ONLY Alpha:")[1].split(
        "Candidate 2 — TEST ONLY Beta:"
    )
    assert alpha.count("Public-source context:") == 1
    excerpt = next(
        line for line in alpha.splitlines() if "Public-source context:" in line
    )
    assert "dielectric scalar of 25" in excerpt and "band gap of 4.0 eV" in excerpt
    assert "…” [S1]" in excerpt and len(excerpt) < 600
    assert "second source passage" not in text
    assert "TEST ONLY source passage" not in beta
    assert "Public-source context:" not in prose(case)


def test_technical_source_excerpt_does_not_repeat_a_quote_already_in_assessment():
    quote = "TEST ONLY source-specific measured value under the reported conditions."
    case = literature_case({"band_gap": "supports", "interpretation": quote})
    case[0]["candidate_leads"][0]["citations"][0]["quote"] = quote
    technical = prose(case, audit=True)
    assert technical.count(quote) == 1
    assert "Public-source context:" not in technical


def test_assessed_candidate_excerpt_requires_its_own_report_reference():
    case = literature_case({"band_gap": "supports"})
    case[0]["candidate_leads"][0]["citations"][0][
        "quote"
    ] = "TEST ONLY passage without a retained report reference."
    case[2].clear()
    text = prose(case, audit=True)
    assert "Public-source context:" not in text
    assert "passage without a retained report reference" not in text
