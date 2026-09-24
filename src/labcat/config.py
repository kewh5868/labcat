"""Validate preferences separately from scientific evidence and safety
policy."""

import math
import tomllib
from dataclasses import asdict, dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

# Editable scoring scale, not a physical cutoff or measurement uncertainty.
DEFAULT_TARGET_BAND_GAP_TOLERANCE_EV = 0.2


@dataclass(frozen=True)
class RankingPreferences:
    """Utility weights; not material properties or calibrated
    science."""

    stability: float
    band_gap: float
    element_screen: float
    simplicity: float
    evidence_quality: float


@dataclass(frozen=True)
class ReportLayout:
    """Fixed rendering choices, never CSS, markup, paths or scientific
    facts."""

    page_size: str = "letter"
    font_family: str = "sans"
    font_size: int = 11
    line_spacing: str = "comfortable"
    accent: str = "sage"
    table_style: str = "striped"
    page_numbers: bool = True
    text_width: int = 88
    json_indent: int = 2


LAYOUT_CHOICES = {
    "page_size": ("letter", "a4"),
    "font_family": ("sans", "serif"),
    "font_size": (10, 11, 12),
    "line_spacing": ("compact", "comfortable"),
    "accent": ("sage", "teal", "slate"),
    "table_style": ("striped", "grid", "minimal"),
    "page_numbers": (False, True),
    "text_width": (72, 88, 100),
    "json_indent": (2, 4),
}


def validate_layout(value: dict, base: ReportLayout | None = None) -> ReportLayout:
    """Merge bounded partial layout preferences; reject arbitrary
    renderer input."""
    if not isinstance(value, dict) or value.keys() - LAYOUT_CHOICES.keys():
        raise ValueError("Choose only supported report appearance preferences.")
    merged = {**asdict(base or ReportLayout()), **value}
    for name, choices in LAYOUT_CHOICES.items():
        item = merged[name]
        expected = bool if name == "page_numbers" else type(choices[0])
        if type(item) is not expected or item not in choices:
            raise ValueError(f"Invalid report appearance {name}.")
    return ReportLayout(**merged)


@dataclass(frozen=True)
class Presentation:
    """Formatting choices shared by the command line and browser
    shell."""

    style: str
    format: str
    terminology: str
    verbosity: str = "standard"
    outputs: tuple[str, ...] = ("pi", "audit")
    layout: ReportLayout = field(default_factory=ReportLayout)


@dataclass(frozen=True)
class AppConfig:
    """Validated settings; no fields allow changing safety rules or
    adding facts."""

    ranking: RankingPreferences
    presentation: Presentation
    provider: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["presentation"]["outputs"] = list(self.presentation.outputs)
        return value


def load_config(path: Path | None = None) -> AppConfig:
    """Load an optional partial TOML override; reject unknown and
    invalid keys."""
    supplied = tomllib.loads(path.read_text(encoding="utf-8")) if path else {}
    return config_from_mapping(supplied)


def config_from_mapping(supplied: dict[str, Any]) -> AppConfig:
    """Validate preferences from TOML or storage through the same
    boundary."""
    defaults = tomllib.loads(
        files("labcat").joinpath("default.toml").read_text(encoding="utf-8")
    )
    if not isinstance(supplied, dict):
        raise ValueError("Configuration must contain preference tables.")
    for section, values in supplied.items():
        if section not in defaults or not isinstance(values, dict):
            raise ValueError("Unknown configuration section or invalid table.")
        if values.keys() - defaults[section].keys():
            raise ValueError(
                f"Unknown key in [{section}]; policy cannot be overridden."
            )
        defaults[section].update(values)

    weights = defaults["ranking"]
    for value in weights.values():
        if (
            type(value) not in (int, float)
            or value < 0
            or value > 1
            or not math.isfinite(value)
        ):
            raise ValueError("Ranking weights must be finite numbers between 0 and 1.")
    if not math.isclose(sum(weights.values()), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError("Ranking weights must sum to 1.")

    presentation = defaults["presentation"]
    choices = {
        "style": ("pi", "audit"),
        "format": ("text", "json", "pdf", "docx"),
        "terminology": ("general", "research", "specialist", "plain", "technical"),
        "verbosity": ("concise", "standard", "detailed"),
    }
    for name, allowed in choices.items():
        if presentation[name] not in allowed:
            raise ValueError(f"Invalid presentation {name}; choose from {allowed}.")
    outputs = presentation["outputs"]
    if (
        not isinstance(outputs, list)
        or not 1 <= len(outputs) <= 2
        or any(value not in ("pi", "audit") for value in outputs)
        or len(set(outputs)) != len(outputs)
    ):
        raise ValueError("Select Summary, Technical View, or both outputs.")
    presentation["outputs"] = tuple(outputs)
    presentation["layout"] = validate_layout(presentation["layout"])
    if defaults["model"]["provider"] != "none":
        raise ValueError(
            "TOML defaults use provider = 'none'; configure models in Connections."
        )
    return AppConfig(
        ranking=RankingPreferences(**weights),
        presentation=Presentation(**presentation),
        provider="none",
    )
