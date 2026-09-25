"""Follow-up descriptions come from bound documents and validated
judgments."""

from copy import deepcopy

import pytest
from test_preassessment_attribute_evidence import evaluate, prepare

from labcat.science.reporting import _attribute_lines


@pytest.mark.parametrize("assessed", [False, True])
def test_followup_usage_comes_from_canonical_body_citations_not_saved_flags(
    monkeypatch, assessed
):
    session, reply, _, _ = prepare(monkeypatch, {"band_gap": 0.5, "density": 0.5})
    outcome = evaluate(session, reply) if assessed else session.finalize()
    result, sources = outcome["result"], outcome["sources"]
    before = deepcopy(result["literature_evaluation"])
    # Deliberately contradict orchestration notes. They cannot establish use.
    result["attribute_research"].update(
        used_for_ranking=not assessed,
        assessment_judgments_count=999,
        assessment_documents_available=999,
        available_for_assessment=not assessed,
    )
    for audit in (False, True):
        text = "\n".join(_attribute_lines(result, sources, audit=audit))
        assert "2 complete source-bound body passages" in text
        assert "999" not in text
        assert "Repository properties were checked before" not in text
        assert "excerpts do not change scores" not in text
        if assessed:
            assert "4 non-unknown assessments cite these body passages" in text
            assert "do not create measured property values" in text
            assert "No informative assessment cites" not in text
        else:
            assert "No informative assessment cites these body passages" in text
            assert "Retrieved excerpts alone do not change screening priority" in text
        if audit:
            assert "first general application assessment is retained before" in text
            assert "Cropped or unbound excerpts remain review leads" in text
    assert result["literature_evaluation"] == before


def test_unavailable_followup_cannot_claim_body_evidence_from_flag(monkeypatch):
    session, _, _, _ = prepare(monkeypatch, {"band_gap": 1}, unavailable=True)
    outcome = session.finalize()
    outcome["result"]["attribute_research"].update(
        used_for_ranking=True,
        available_for_assessment=True,
        assessment_judgments_count=999,
    )
    text = "\n".join(
        _attribute_lines(outcome["result"], outcome["sources"], audit=True)
    )
    assert "0 complete source-bound body passages" in text
    assert "No informative assessment cites" in text
    assert "Body-passage assessment attempts: 0" in text


def test_legacy_followup_keeps_review_only_wording_without_version_marker():
    result = {
        "attribute_research": {
            "status": "complete",
            "attributes": [],
            "used_for_ranking": True,
        }
    }
    summary = "\n".join(_attribute_lines(result, [], audit=False))
    technical = "\n".join(_attribute_lines(result, [], audit=True))
    assert (
        "review leads do not fill missing properties or change the ranking" in summary
    )
    assert "Repository properties were checked before" in technical
    assert "excerpts do not change scores" in technical


def test_tampered_body_judgment_cannot_support_a_followup_use_claim(monkeypatch):
    session, reply, _, _ = prepare(monkeypatch, {"band_gap": 0.5, "density": 0.5})
    outcome = evaluate(session, reply)
    row = outcome["result"]["literature_evaluation"]["proposals"][-1]
    row["quote"] = "TEST ONLY invented passage absent from the bound source."
    with pytest.raises(ValueError):
        _attribute_lines(outcome["result"], outcome["sources"], audit=False)
