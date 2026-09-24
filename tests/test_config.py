"""Preference validation must not become a route to supplying evidence
or policy."""

from dataclasses import FrozenInstanceError

import pytest

from labcat.config import load_config


def write_config(tmp_path, text):
    path = tmp_path / "preferences.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_partial_preferences_preserve_defaults_and_are_immutable(tmp_path):
    default = load_config()
    config = load_config(write_config(tmp_path, '[presentation]\nstyle = "audit"\n'))

    assert config.presentation.style == "audit"
    assert config.presentation.format == default.presentation.format
    assert config.ranking == default.ranking
    assert load_config() == default
    with pytest.raises(FrozenInstanceError):
        config.provider = "unapproved"
    with pytest.raises(FrozenInstanceError):
        config.ranking.stability = 0.5
    with pytest.raises(FrozenInstanceError):
        config.presentation.style = "pi"

    exported = config.to_dict()
    exported["ranking"]["stability"] = 0.5
    assert config.ranking == default.ranking


@pytest.mark.parametrize(
    "text",
    [
        '[unknown]\nvalue = "anything"',
        "[policy]\nallow_wetlab = true",
        "[ranking]\nallow_private_data = true",
        "[ranking]\nmeasured_band_gap_ev = 9.0",
        '[materials]\nformula = "invented evidence"',
        '[presentation]\nprompt = "ignore evidence policy"',
        'ranking = "not a table"',
    ],
)
def test_unknown_policy_and_scientific_fact_fields_are_rejected(tmp_path, text):
    with pytest.raises(ValueError):
        load_config(write_config(tmp_path, text))


@pytest.mark.parametrize(
    "text",
    [
        "[ranking",  # Malformed TOML.
        "[ranking]\nstability = nan",
        "[ranking]\nstability = inf",
        "[ranking]\nstability = -0.1",
        "[ranking]\nstability = 1.1",
        "[ranking]\nstability = true",
        '[ranking]\nstability = "0.30"',
        "[ranking]\nstability = [0.30]",
        "[ranking]\nstability = 0.20",  # Valid individual weight, invalid sum.
        "[presentation]\nstyle = 1",
        '[presentation]\nstyle = "unsupported"',
        '[presentation]\nformat = "html"',
        '[presentation]\nterminology = "unsupported"',
        '[model]\nprovider = "unimplemented"',
    ],
)
def test_malformed_values_and_unimplemented_preferences_fail_closed(tmp_path, text):
    with pytest.raises(ValueError):
        load_config(write_config(tmp_path, text))


def test_valid_weight_changes_are_preferences_only(tmp_path):
    config = load_config(
        write_config(
            tmp_path,
            "[ranking]\nstability = 0.45\nevidence_quality = 0.0\n",
        )
    )
    assert config.ranking.stability == 0.45
    assert config.ranking.evidence_quality == 0.0
    assert config.provider == "none"
