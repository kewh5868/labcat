"""Discover an existing pre-upgrade workspace without moving private
files.

Only default host locations use this compatibility lookup. Explicit site
data directories are authoritative. A selected directory keeps its
database, journal, settings and encrypted credentials together; no
credential bytes are inspected.
"""

import stat
from pathlib import Path

_LEGACY_DESKTOP_DIRECTORY = "Lila Labagent"
_LEGACY_UNIX_DIRECTORY = "lila-labagent"
_WORKSPACE_FILES = (
    "workspace.sqlite3",
    "workspace.connections.json",
    "workspace.credentials.enc.json",
    "workspace.setup.json",
)


def _mode(path: Path) -> int | None:
    try:
        return path.lstat().st_mode
    except FileNotFoundError:
        return None


def existing_workspace_directory(preferred: Path, *, platform: str) -> Path:
    """Prefer Labcat; otherwise reuse a recognized older workspace in
    place.

    Existing canonical paths always win, including an explicitly
    prepared empty directory. Do not merge two workspaces, follow legacy
    symlinks, create paths, copy secrets or move a database that another
    process might still be using. Permission errors propagate instead of
    silently opening an empty workspace.
    """
    if _mode(preferred) is not None:
        return preferred
    legacy_name = (
        _LEGACY_DESKTOP_DIRECTORY
        if platform in {"darwin", "win32"}
        else _LEGACY_UNIX_DIRECTORY
    )
    legacy = preferred.with_name(legacy_name)
    mode = _mode(legacy)
    if mode is None or not stat.S_ISDIR(mode):
        return preferred
    for filename in _WORKSPACE_FILES:
        mode = _mode(legacy / filename)
        if mode is not None and stat.S_ISREG(mode):
            return legacy
    return preferred
