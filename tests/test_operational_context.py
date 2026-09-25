"""Synthetic operating-condition wording; no material facts or live
requests."""

from copy import deepcopy

import pytest
from test_preliminary_ranking import data_for, propose

from labcat.agent_tools import ResearchToolSession
from labcat.science.literature_evaluation import (
    _criterion_relevant,
    evaluate_candidates,
    validate_evaluation,
)


@pytest.mark.parametrize(
    "description",
    [
        "has limited stability under humid and oxidative conditions",
        "is unstable in moist air",
        "remains stable under oxidizing conditions",
        "shows instability after exposure to humid air",
        "has limited stability upon repeated adsorption-desorption cycles",
        "remains stable during charge-discharge cycles",
        "has limited stability after thermal cycles",
        "shows instability during mechanical cycles",
    ],
)
def test_condition_scoped_stability_is_reviewable(description):
    quote = f"TESTONLY-Alpha {description}."
    assert _criterion_relevant(quote, "TESTONLY-Alpha", "operational_stability")
    assert not _criterion_relevant(quote, "TESTONLY-Alpha", "stability")
    assert not _criterion_relevant(quote, "TESTONLY-Alpha", "ambient_phase_stability")


@pytest.mark.parametrize(
    "quote",
    [
        "TESTONLY-Alpha is discussed in humid air.",
        "TESTONLY-Alpha is stable without specified operating conditions.",
        "TESTONLY-Alpha has thermodynamic stability under standard conditions.",
        "TESTONLY-Alpha has a stable computed phase in vacuum.",
        "TESTONLY-Alpha is stable. Another sample fails in moist air.",
        "TESTONLY-Alpha is stable; another sample fails in moist air.",
        "TESTONLY-Alpha is stable whereas another sample fails in moist air.",
        "TESTONLY-Alpha is stable while another sample fails in moist air.",
        "TESTONLY-Alpha has stable oxidative catalytic activity.",
        "TESTONLY-Alpha was synthesized in moist air.",
        "TESTONLY-Alpha is a stable synthesis intermediate in moist air.",
    ],
)
def test_unbound_or_wrong_scope_words_do_not_supply_operational_context(quote):
    assert not _criterion_relevant(quote, "TESTONLY-Alpha", "operational_stability")


def test_review_anchor_exposes_adverse_conclusion_without_assigning_a_judgment():
    method = (
        "TESTONLY-Alpha was tested for gas uptake under humidity and varied "
        "conditions in an extended study that compared a wide range of "
        "experimental environments and adsorption protocols."
    )
    conclusion = (
        "The study finds limited stability of TESTONLY-Alpha under humid and "
        "oxidative conditions and upon multiple adsorption-desorption cycles."
    )
    data = data_for(
        [("TESTONLY-Alpha", method + " " + conclusion)],
        importance={"operational_stability": 1},
    )
    # Exercise the real worklist selector against retained source documents.
    session = object.__new__(ResearchToolSession)
    session._accepted_leads = data["leads"]
    session._evaluation_preferences = lambda: (data["profile"], None)
    session._request_preferences = lambda: {}
    session._assessment_documents = lambda: data["documents"]
    session._review_task_cache = None
    task = next(
        task
        for task in session._review_tasks()
        if task["criterion_id"] == "operational_stability"
    )
    assert task["quote_anchor"] == conclusion
    assert "judgment" not in task and "interpretation" not in task
    original = deepcopy(data)

    def evaluate(judgment):
        row = {
            **propose(data, 0, "operational_stability", judgment),
            "quote": task["quote_anchor"],
        }
        return evaluate_candidates(
            {"evaluations": [row]},
            data["leads"],
            data["references"],
            data["profile"],
            admission_checks=True,
        )

    unknown = evaluate("unknown")
    assert unknown["feedback"][0]["status"] == "accepted"
    assert unknown["evaluation"]["ranked_candidates"][0]["coverage"] == 0
    concern = evaluate("concern")
    assert concern["feedback"][0]["status"] == "accepted"
    ranked = concern["evaluation"]["ranked_candidates"][0]
    assert ranked["coverage"] == 1
    assert ranked["priority_tier"] == 2
    assert ranked["priority_score"] == 0
    assert not concern["evaluation"]["properties_verified"]
    assert (
        validate_evaluation(
            concern["evaluation"], data["leads"], data["references"], data["profile"]
        )
        == concern["evaluation"]
    )
    assert data == original
