"""Controlled score mechanics, using explicitly synthetic source
statements.

These fixtures establish no material facts or scientific retrieval
success. The private retained-source replay is kept separately from
these unit tests.
"""

from copy import deepcopy

import pytest
from test_preliminary_ranking import data_for, propose

from labcat.science.literature_evaluation import (
    evaluate_candidates,
    validate_evaluation,
)


def with_weights(data, proposals, importance):
    before = deepcopy((data, proposals))
    profile = {**data["profile"], "importance": importance}
    evaluated = evaluate_candidates(
        {"evaluations": proposals},
        data["leads"],
        data["references"],
        profile,
        admission_checks=True,
    )
    bundle = evaluated["evaluation"]
    assert len(evaluated["accepted_proposals"]) == len(proposals)
    assert (
        validate_evaluation(bundle, data["leads"], data["references"], profile)
        == bundle
    )
    assert (data, proposals) == before
    return bundle["ranked_candidates"]


def test_same_evidence_opposing_attribute_fits_reverse_when_weights_change():
    data = data_for(
        [
            (
                "TESTONLY-Alpha",
                "TESTONLY-Alpha has favorable density but limited solution processing.",
            ),
            (
                "TESTONLY-Beta",
                "TESTONLY-Beta has unfavorable density but useful solution processing.",
            ),
        ],
        importance={"density": 0.5, "solution_processability": 0.5},
    )
    proposals = [
        propose(data, 0, "density"),
        propose(data, 0, "solution_processability", "concern"),
        propose(data, 1, "density", "concern"),
        propose(data, 1, "solution_processability"),
    ]
    density_first = with_weights(
        data, proposals, {"density": 0.8, "solution_processability": 0.2}
    )
    processing_first = with_weights(
        data, proposals, {"density": 0.2, "solution_processability": 0.8}
    )
    assert [row["name"] for row in density_first] == [
        "TESTONLY-Alpha",
        "TESTONLY-Beta",
    ]
    assert [row["name"] for row in processing_first] == [
        "TESTONLY-Beta",
        "TESTONLY-Alpha",
    ]
    for rows in (density_first, processing_first):
        assert [row["priority_score"] for row in rows] == [0.8, 0.2]
        assert all(row["coverage"] == 1 for row in rows)
        assert all(row["ranking_basis"] == "attribute" for row in rows)


def test_same_sparse_evidence_can_change_order_through_weighted_coverage():
    data = data_for(
        [
            (
                "TESTONLY-Alpha",
                "TESTONLY-Alpha is discussed for this application without properties.",
            ),
            (
                "TESTONLY-Beta",
                "TESTONLY-Beta has favorable density for the requested goal.",
            ),
        ],
        importance={"density": 0.5, "solution_processability": 0.5},
    )
    proposals = [propose(data, 0), propose(data, 1, "density")]
    low = with_weights(
        data, proposals, {"density": 0.1, "solution_processability": 0.9}
    )
    high = with_weights(
        data, proposals, {"density": 0.9, "solution_processability": 0.1}
    )
    assert low[0]["name"] == "TESTONLY-Alpha"
    assert high[0]["name"] == "TESTONLY-Beta"
    for rows, coverage in ((low, 0.1), (high, 0.9)):
        alpha = next(row for row in rows if row["name"] == "TESTONLY-Alpha")
        beta = next(row for row in rows if row["name"] == "TESTONLY-Beta")
        assert alpha["coverage"] == 0 and alpha["observed_fit"] is None
        assert alpha["priority_score"] == pytest.approx(0.7 + 0.05 + 0.1 / 3)
        assert beta["coverage"] == coverage and beta["observed_fit"] == 1
        assert beta["priority_score"] == pytest.approx(
            (1 - coverage) * 0.225 + coverage
        )
        # This is an evidence-coverage change, not proof of a physical tradeoff.
        assert "solution_processability" in beta["unknown_criteria"]
        assert len(beta["stability_unknown"]) == 3


def test_reweighting_wholly_unknown_attributes_cannot_invent_ordering_changes():
    data = data_for(
        [
            ("TESTONLY-Alpha", "TESTONLY-Alpha is discussed for this application."),
            ("TESTONLY-Beta", "TESTONLY-Beta is mentioned without relevant evidence."),
        ],
        importance={"density": 0.5, "solution_processability": 0.5},
    )
    proposals = [propose(data, 0)]
    low = with_weights(data, proposals, {"density": 0.01, "solution_processability": 1})
    high = with_weights(
        data, proposals, {"density": 1, "solution_processability": 0.01}
    )
    assert low == high
    assert all(row["coverage"] == 0 for row in low)
