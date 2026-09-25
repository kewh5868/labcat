"""Synthetic adjacent method contexts; no material facts or live model
calls."""

import pytest
from test_literature_admission import assess, case

QUOTE = "We demonstrate a TESTONLY-Alpha device with useful optical output."


@pytest.mark.parametrize("judgment", ["supports", "mixed"])
@pytest.mark.parametrize(
    "text",
    [
        "Here we investigate TESTONLY-Alpha using numerical simulations. " + QUOTE,
        "We simulate TESTONLY-Alpha devices with a numerical model. " + QUOTE,
        "Here we propose a TESTONLY-Alpha device and investigate its performance "
        "using a numerical simulator software package. " + QUOTE,
        QUOTE + " This result is obtained from numerical simulations.",
        QUOTE + " Experimental realization of this device remains future work.",
        QUOTE + " This work motivates experimental realization of such devices.",
        "We investigate TESTONLY-Alpha using numerical simulations. "
        + QUOTE
        + " This work motivates experimental realization of such devices.",
        QUOTE + " This device was tested using numerical simulations.",
        "TESTONLY-Alpha devices were tested using numerical simulations. " + QUOTE,
        QUOTE + " This device was measured in computer simulations.",
        "TESTONLY-Alpha devices were tested numerically. " + QUOTE,
        QUOTE + " The TESTONLY-Alpha device was numerically simulated, "
        "whereas TESTONLY-Beta was fabricated and tested.",
        QUOTE + " This work experimentally measured TESTONLY-Beta "
        "and simulated TESTONLY-Alpha.",
    ],
)
def test_adjacent_method_cannot_be_trimmed_into_actual_use(text, judgment):
    data = case(text, quote=QUOTE, criterion="demonstrated_use")
    result = assess(data, judgment=judgment)
    assert result["feedback"][0]["reason"] == "demonstration_not_established"
    assert not result["accepted_proposals"]
    assert assess(data, judgment="unknown")["feedback"][0]["status"] == "accepted"
    # Existing records retain their original interpretation and arithmetic.
    assert assess(data, admission=False)["feedback"][0]["status"] == "accepted"


@pytest.mark.parametrize(
    "text,quote",
    [
        (
            "We simulated a comparison device. TESTONLY-Alpha was fabricated "
            "and tested in a working device.",
            "TESTONLY-Alpha was fabricated and tested in a working device.",
        ),
        (
            "We simulated TESTONLY-Alpha devices. We experimentally demonstrate "
            "TESTONLY-Alpha in fabricated devices.",
            "We experimentally demonstrate TESTONLY-Alpha in fabricated devices.",
        ),
        (
            "We demonstrate TESTONLY-Alpha experimentally. "
            "This study also uses numerical simulations for comparison.",
            "We demonstrate TESTONLY-Alpha experimentally.",
        ),
        (
            "TESTONLY-Alpha was fabricated and tested in a device. "
            + QUOTE
            + " This study includes numerical simulations.",
            "TESTONLY-Alpha was fabricated and tested in a device. " + QUOTE,
        ),
        (
            "We measured TESTONLY-Alpha devices and compared numerical models. "
            + QUOTE,
            QUOTE,
        ),
        (
            "Another material was simulated in a different device. " + QUOTE,
            QUOTE,
        ),
        (
            QUOTE + " Another sample requires future experimental validation.",
            QUOTE,
        ),
        (
            "We investigated a comparison using numerical simulations. " + QUOTE,
            QUOTE,
        ),
        ("We simulate TESTONLY-Beta devices. " + QUOTE, QUOTE),
        ("Here we simulate TESTONLY-Beta devices. " + QUOTE, QUOTE),
        (QUOTE + " TESTONLY-Beta was simulated in a device.", QUOTE),
        (
            "We fabricated and tested TESTONLY-Alpha devices. "
            + QUOTE
            + " This study includes numerical simulations.",
            QUOTE,
        ),
        (
            "We experimentally measured TESTONLY-Alpha in a device "
            "and simulated TESTONLY-Beta. " + QUOTE,
            QUOTE,
        ),
        (
            "TESTONLY-Alpha was fabricated and tested in a device. "
            + QUOTE
            + " This study also uses numerical simulations.",
            QUOTE,
        ),
        (
            "We simulate unrelated devices. An experimental prototype was "
            "fabricated in a separate study. " + QUOTE,
            QUOTE,
        ),
    ],
)
def test_explicit_actual_or_separate_computation_is_preserved(text, quote):
    result = assess(case(text, quote=quote, criterion="demonstrated_use"))
    assert result["feedback"][0]["status"] == "accepted"


def test_adjacent_method_does_not_change_application_relevance():
    text = "Here we simulate possible optoelectronic devices. " + QUOTE
    result = assess(case(text, quote=QUOTE, criterion="application_fit"))
    assert result["feedback"][0]["status"] == "accepted"
