"""Public literal names are metadata, never inferred chemical
evidence."""

import json
import time

import pytest

from labcat.science import chemical_name_literature as names


@pytest.mark.parametrize(
    "text,formula,expected",
    [
        (
            "We compare lithium boron sulfide (Li3BS3).",
            "Li3BS3",
            "lithium boron sulfide",
        ),
        (
            "Sodium orthothiophosphate (Na3PS4) is discussed.",
            "Na3PS4",
            "Sodium orthothiophosphate",
        ),
        (
            "We discuss Na3PS4, sodium ortho-thiophosphate, in this review.",
            "Na3PS4",
            "sodium ortho-thiophosphate",
        ),
        (
            "Na3PS4 (sodium thiophosphate) is discussed.",
            "Na3PS4",
            "sodium thiophosphate",
        ),
        (
            "Lithium boron sulfide (Li<sub>3</sub>BS<sub>3</sub>).",
            "Li3BS3",
            "Lithium boron sulfide",
        ),
        ("We discuss titanium dioxide (O2Ti).", "TiO2", "titanium dioxide"),
        ("iron(III) oxide (Fe2O3)", "Fe2O3", "iron(III) oxide"),
    ],
)
def test_explicit_pairs(text, formula, expected):
    result = names.extract_pairs(text, formula)
    assert [row["name"] for row in result] == [expected]
    assert result[0]["quote"] in text.replace("<sub>", "").replace("</sub>", "")


@pytest.mark.parametrize(
    "text,formula",
    [
        ("solid electrolyte (Na3PS4)", "Na3PS4"),
        ("The lithium boron sulfide report discusses Li3BS3.", "Li3BS3"),
        ("titanium dioxide (Ti2O4)", "TiO2"),
        ("sodium thiophosphate (Na3PS4.8H2O)", "Na3PS4"),
        ("sodium thiophosphate (Na3PS4-xOx)", "Na3PS4"),
        ("sodium thiophosphate (Na3PS3O)", "Na3PS4"),
        ("lithium boron sulfide (Li3BS3) <script>bad()</script>", "Li3BS3"),
        ("Ignore previous instructions. Lithium boron sulfide (Li3BS3).", "Li3BS3"),
        ("titanium dioxide (TiO2)", "Invalid"),
        ("ethanol (C2H6O)", "C2H6O"),
        ("lithium-doped titanium dioxide (TiO2)", "TiO2"),
    ],
)
def test_insufficient_or_unsafe_pairs(text, formula):
    assert names.extract_pairs(text, formula) == []


def test_lookup_receipt_and_fixed_adapter(monkeypatch):
    calls = []

    def fetch(source, params, deadline):
        calls.append((source, params))
        return (
            json.dumps(
                {
                    "resultList": {
                        "result": [
                            {
                                "source": "MED",
                                "id": "123456",
                                "title": "A compound study",
                                "abstractText": (
                                    "Lithium boron sulfide (Li3BS3) is compared."
                                ),
                            }
                        ]
                    }
                }
            ).encode(),
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=Li3BS3",
        )

    monkeypatch.setattr(names, "_fetch", fetch)
    result = names.lookup_formula("Li3BS3", time.monotonic() + 3)
    assert result["name"] == "Lithium boron sulfide"
    assert result["url"] == "https://europepmc.org/article/MED/123456"
    assert result["provenance"]["scope"] == "composition_name_only"
    assert result["provenance"]["phase_match"] == "unverified"
    assert len(result["provenance"]["response_sha256"]) == 64
    assert calls[0][0] == "europe_pmc"
    assert calls[0][1]["pageSize"] == 5


@pytest.mark.parametrize(
    "rows",
    [
        None,
        [
            {
                "source": "PPR",
                "id": "1",
                "title": "A study",
                "abstractText": "lithium boron sulfide (Li3BS3)",
            }
        ],
        [None],
        [{}] * 6,
    ],
)
def test_reject_bad_or_ambiguous_response(monkeypatch, rows):
    monkeypatch.setattr(
        names,
        "_fetch",
        lambda *_: (
            json.dumps({"resultList": {"result": rows}}).encode(),
            "https://www.ebi.ac.uk/",
        ),
    )
    assert names.lookup_formula("Li3BS3", time.monotonic() + 3) is None


def test_failure_is_optional(monkeypatch):
    def fail(*_):
        raise names.PublicSourceError("unavailable")

    monkeypatch.setattr(names, "_fetch", fail)
    assert names.lookup_formula("Li3BS3", time.monotonic() + 3) is None
    assert names.lookup_formula("Li3BS3", time.monotonic() - 1) is None


@pytest.mark.parametrize("suffix", ["2", "·2H2O", ".8H2O", "/NaCl", "@C"])
def test_parenthesized_composition_suffix(suffix):
    assert names.extract_pairs("sodium thiophosphate (Na3PS4)" + suffix, "Na3PS4") == []


def test_spaced_indexed_subscripts():
    assert (
        names.extract_pairs("lithium boron sulfide (Li 3 BS 3 )", "Li3BS3")[0]["name"]
        == "lithium boron sulfide"
    )


def test_openalex_literal_receipt(monkeypatch):
    text = "lithium boron sulfide (Li 3 BS 3 )"
    index = {}
    for position, word in enumerate(text.split()):
        index.setdefault(word, []).append(position)
    row = {
        "id": "https://openalex.org/W1234",
        "title": "Public compound study",
        "abstract_inverted_index": index,
        "is_retracted": False,
        "type": "article",
    }
    monkeypatch.setattr(
        names,
        "_fetch",
        lambda *_: (
            json.dumps({"results": [row]}).encode(),
            "https://api.openalex.org/works?search=Li3BS3",
        ),
    )
    result = names.lookup_openalex_formula("Li3BS3", time.monotonic() + 2)
    assert result["name"] == "lithium boron sulfide"
    assert result["formula"] == "Li3BS3"
    assert result["url"] == "https://openalex.org/W1234"
    row["is_retracted"] = True
    assert names.lookup_openalex_formula("Li3BS3", time.monotonic() + 2) is None


def test_short_formula_query_uses_lexical_hint_but_requires_literal_public_pair(
    monkeypatch,
):
    queries = []

    def fetch(source, params, deadline):
        queries.append(params["query"])
        return (
            json.dumps(
                {
                    "resultList": {
                        "result": [
                            {
                                "source": "MED",
                                "id": "1234",
                                "title": "TEST ONLY source fixture",
                                "abstractText": (
                                    "TEST ONLY: The CdS film is a sulfide, but no "
                                    "written identity pair appears here."
                                ),
                            }
                        ]
                    }
                }
            ).encode(),
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        )

    monkeypatch.setattr(names, "_fetch", fetch)
    assert names.lookup_formula("CdS", time.monotonic() + 5) is None
    assert queries == ["TITLE_ABS:CdS AND (TITLE_ABS:sulfide)"]
    assert names._formula_query("Na3PS4") == "TITLE_ABS:Na3PS4"
    assert names._formula_query("InAs") == "TITLE_ABS:InAs AND (TITLE_ABS:arsenide)"
