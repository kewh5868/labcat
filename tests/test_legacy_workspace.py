"""Upgrade discovery preserves private workspace files without rewriting
them."""

import hashlib
from pathlib import Path

import pytest

from labcat.legacy_workspace import (
    _LEGACY_DESKTOP_DIRECTORY,
    _LEGACY_UNIX_DIRECTORY,
    existing_workspace_directory,
)


@pytest.mark.parametrize(
    ("platform", "preferred_name", "legacy_name"),
    [
        ("darwin", "Labcat", _LEGACY_DESKTOP_DIRECTORY),
        ("win32", "Labcat", _LEGACY_DESKTOP_DIRECTORY),
        ("linux", "labcat", _LEGACY_UNIX_DIRECTORY),
    ],
)
def test_existing_workspace_and_credentials_stay_together_unchanged(
    tmp_path, platform, preferred_name, legacy_name
):
    preferred = tmp_path / preferred_name
    legacy = tmp_path / legacy_name
    legacy.mkdir()
    fixture = {
        "workspace.sqlite3": b"synthetic database fixture",
        "workspace.sqlite3-wal": b"synthetic journal fixture",
        "workspace.credentials.enc.json": b"synthetic ciphertext fixture",
        "workspace.connections.json": b"synthetic account fixture",
        "workspace.setup.json": b"synthetic setup fixture",
    }
    for name, value in fixture.items():
        (legacy / name).write_bytes(value)
    before = {
        name: hashlib.sha256((legacy / name).read_bytes()).hexdigest()
        for name in fixture
    }
    assert existing_workspace_directory(preferred, platform=platform) == legacy
    assert not preferred.exists()
    assert set(path.name for path in legacy.iterdir()) == set(fixture)
    assert {
        name: hashlib.sha256((legacy / name).read_bytes()).hexdigest()
        for name in fixture
    } == before


def test_fresh_install_and_unrelated_legacy_directory_choose_canonical(tmp_path):
    preferred = tmp_path / "Labcat"
    assert existing_workspace_directory(preferred, platform="darwin") == preferred
    assert not list(tmp_path.iterdir())
    legacy = tmp_path / _LEGACY_DESKTOP_DIRECTORY
    legacy.mkdir()
    (legacy / "unrelated.txt").write_text("unrelated")
    assert existing_workspace_directory(preferred, platform="darwin") == preferred
    assert not preferred.exists()


@pytest.mark.parametrize(
    "filename", ["workspace.connections.json", "workspace.credentials.enc.json"]
)
def test_partial_workspace_with_saved_connections_is_not_lost(tmp_path, filename):
    preferred = tmp_path / "labcat"
    legacy = tmp_path / _LEGACY_UNIX_DIRECTORY
    legacy.mkdir()
    (legacy / filename).write_text("synthetic private fixture")
    assert existing_workspace_directory(preferred, platform="linux") == legacy


def test_canonical_directory_wins_without_merging_an_older_workspace(tmp_path):
    preferred = tmp_path / "Labcat"
    preferred.mkdir()
    legacy = tmp_path / _LEGACY_DESKTOP_DIRECTORY
    legacy.mkdir()
    (legacy / "workspace.sqlite3").write_text("synthetic old data")
    assert existing_workspace_directory(preferred, platform="darwin") == preferred
    assert not list(preferred.iterdir())
    assert (legacy / "workspace.sqlite3").read_text() == "synthetic old data"


@pytest.mark.parametrize("link_directory", [False, True])
def test_legacy_symlinks_do_not_redirect_workspace_discovery(tmp_path, link_directory):
    preferred = tmp_path / "Labcat"
    legacy = tmp_path / _LEGACY_DESKTOP_DIRECTORY
    other = tmp_path / "other"
    other.mkdir()
    database = other / "workspace.sqlite3"
    database.write_text("synthetic unrelated data")
    if link_directory:
        legacy.symlink_to(other, target_is_directory=True)
    else:
        legacy.mkdir()
        (legacy / "workspace.sqlite3").symlink_to(database)
    assert existing_workspace_directory(preferred, platform="darwin") == preferred
    assert database.read_text() == "synthetic unrelated data"
    assert not preferred.exists()


def test_unreadable_legacy_location_is_not_silently_replaced(tmp_path, monkeypatch):
    preferred = tmp_path / "Labcat"
    legacy = tmp_path / _LEGACY_DESKTOP_DIRECTORY
    original = Path.lstat

    def blocked(path):
        if path == legacy:
            raise PermissionError("synthetic access restriction")
        return original(path)

    monkeypatch.setattr(Path, "lstat", blocked)
    with pytest.raises(PermissionError):
        existing_workspace_directory(preferred, platform="darwin")
    assert not preferred.exists()
