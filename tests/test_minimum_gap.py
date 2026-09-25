"""Application screening thresholds are preferences, never material
properties."""

from copy import deepcopy

import pytest

from labcat import science
from labcat.config import load_config
from labcat.science.ranking import rank_records


@pytest.fixture
def rows():
    # Deliberate numeric edge-case mutations of explicit offline source fixtures.
    records, _ = science.load_snapshot()
    records = deepcopy(records[:3])
    for row, gap in zip(records, [1.0, 2.0, None], strict=True):
        row["band_gap_ev"] = gap
    return records


def test_known_below_minimum_excluded_equal_included_missing_kept_for_review(rows):
    ranked, audit = rank_records(
        rows,
        load_config(),
        importance={"band_gap": 1, "dielectric_total": 1},
        application="high_k_screening",
        minimum_band_gap_ev=2,
    )
    assert [row["material_id"] for row in ranked] == [
        rows[1]["material_id"],
        rows[2]["material_id"],
    ]
    assert ranked[1]["score_analysis"]["status"] == "needs_evidence"
    assert ranked[1]["band_gap_ev"] is None
    assert audit["screening_preferences"]["minimum_band_gap_active"] is True
    exclusion = audit["excluded_records"][0]
    assert exclusion["material_id"] == rows[0]["material_id"]
    assert "below the saved screening minimum" in exclusion["reasons"][0]
    assert exclusion["provenance"] == rows[0]["provenance"]


@pytest.mark.parametrize(
    "weights,minimum",
    [
        ({"band_gap": 0, "dielectric_total": 1}, 2),
        ({"band_gap": 1, "dielectric_total": 1}, None),
    ],
)
def test_unselected_or_cleared_preference_does_not_filter(rows, weights, minimum):
    ranked, audit = rank_records(
        rows, load_config(), importance=weights, minimum_band_gap_ev=minimum
    )
    assert len(ranked) == len(rows)
    assert audit["screening_preferences"]["minimum_band_gap_active"] is False


@pytest.mark.parametrize(
    "minimum", [True, "2", -1, 101, float("nan"), float("inf"), {}]
)
def test_invalid_minimum_fails_before_retrieval(monkeypatch, minimum):
    monkeypatch.setattr(
        science,
        "retrieve_nomad",
        lambda _: pytest.fail("invalid threshold reached source"),
    )
    response = science.run_research(
        "Find oxide dielectric materials", load_config(), minimum_band_gap_ev=minimum
    )
    assert response["stage"] == "blocked" and response["sources"] == []


def test_source_query_continues_when_early_records_fail_preference(monkeypatch, rows):
    first = deepcopy(rows[0])
    later = deepcopy(rows[1])
    later["material_id"] = "dielectric:" + later["material_id"]
    calls = []
    monkeypatch.setattr(science, "retrieve_live", lambda *_: ([first], {}))
    monkeypatch.setattr(
        science,
        "retrieve_public_dielectric",
        lambda filters: (calls.append(filters) or [later], {}),
    )
    records, _ = science._retrieve_repositories(
        {"elements": "O"},
        mp_api_key="offline-fixture",
        mode="auto",
        allow_nomad=False,
        allow_public_dielectric=True,
        required_fields=("band_gap_ev",),
        minimum_band_gap_ev=2,
    )
    assert calls
    ranked, _ = rank_records(
        records, load_config(), importance={"band_gap": 1}, minimum_band_gap_ev=2
    )
    assert [row["material_id"] for row in ranked] == [later["material_id"]]
