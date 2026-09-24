"""Check the installed scaffold's metadata and packaged typing
marker."""

import tomllib
from importlib.metadata import distribution
from importlib.resources import files
from pathlib import Path

import labcat


def test_installed_metadata_matches_project():
    project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
    installed = distribution("labcat")
    assert installed.metadata["Name"] == project["name"]
    assert installed.version == project["version"] == labcat.__version__
    assert [(entry.name, entry.value) for entry in installed.entry_points] == [
        ("labcat", "labcat.cli:main")
    ]
    assert not [entry for entry in installed.requires or [] if "extra ==" not in entry]


def test_package_includes_typing_marker():
    assert (files("labcat") / "py.typed").is_file()


def test_package_includes_default_preferences():
    assert (files("labcat") / "default.toml").is_file()
