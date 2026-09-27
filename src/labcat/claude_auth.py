"""Native Claude Code sign-in, owned by its unmodified CLI in worker
tmpfs.

Labcat never reads, exports, or places Claude credentials in its vault.
The terminal talks directly to Claude Code. Only a signed-in boolean and
a random local session generation cross the private worker channel.
"""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from labcat.credentials import ConnectionError, atomic_write, read_private_file

CLAUDE_BINARY = "/usr/local/bin/claude"
SESSION_ROOT = Path("/tmp/labcat-claude")
MODELS = (
    {"id": "default", "label": "Claude Code default"},
    {"id": "sonnet", "label": "Claude Sonnet"},
    {"id": "haiku", "label": "Claude Haiku"},
)


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ConnectionError("Choose a saved Claude Code account.")
    return value


def _directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ConnectionError("Claude Code session storage is unavailable.")
    return path


def _root():
    from labcat.chatgpt_auth import _is_tmpfs

    if os.environ.get("LABCAT_GOOSE_ISOLATED") != "1" or not _is_tmpfs(
        SESSION_ROOT.parent
    ):
        raise ConnectionError("Use the Labcat Docker worker for Claude Code sign-in.")
    return _directory(SESSION_ROOT)


def _account(identifier):
    return _directory(_root() / _identifier(identifier))


@contextmanager
def _lock(folder, *, shared=False, blocking=True):
    # This module only executes in the Linux Docker worker. Imports stay local
    # so installing the shared Python package remains portable.
    import fcntl

    fd = os.open(folder / "session.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise ConnectionError("Claude Code session storage is unavailable.")
        operation = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        try:
            fcntl.flock(fd, operation | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise ConnectionError(
                "This Claude Code connection is busy. Try again shortly."
            ) from None
        yield
    finally:
        os.close(fd)


def _current(account):
    try:
        document = json.loads(read_private_file(account / "current.json", 128))
        if not isinstance(document, dict) or set(document) != {"session_id"}:
            raise ValueError
        return _identifier(document["session_id"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, ConnectionError):
        # Missing or corrupt metadata never grants access to a login.
        return None


def _base_environment(folder):
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": str(folder),
        "CLAUDE_CONFIG_DIR": str(folder / "config"),
        "TMPDIR": str(folder),
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
        "HTTP_PROXY": "http://goose-egress:8780",
        "HTTPS_PROXY": "http://goose-egress:8780",
        "NO_PROXY": "127.0.0.1,localhost",
        "TERM": "xterm-256color",
    }


def _probe(folder):
    try:
        completed = subprocess.run(
            [CLAUDE_BINARY, "auth", "status"],
            env=_base_environment(folder),
            cwd=folder,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0 or len(completed.stdout) > 16_384:
            return False
        value = json.loads(completed.stdout)
        return isinstance(value, dict) and value.get("loggedIn") is True
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def _result(signed_in=False, session_id=None, *, available=True):
    return {
        "available": available,
        "signed_in": signed_in,
        "session_id": session_id if signed_in else None,
        "message": (
            (
                "Claude Code reports a signed-in account. Model access, quota and "
                "inference have not been tested."
            )
            if signed_in
            else (
                (
                    "Sign in with Claude Code in the terminal, then check the "
                    "connection here."
                )
                if available
                else (
                    "Claude Code sign-in requires the current Labcat Docker image and "
                    "its isolated worker."
                )
            )
        ),
    }


def status(identifier):
    _identifier(identifier)
    try:
        if not os.access(CLAUDE_BINARY, os.X_OK):
            return _result(available=False)
        account = _account(identifier)
        with _lock(account):
            current = _current(account)
            if current is None:
                return _result()
            folder = _directory(account / current)
            with _lock(folder, shared=True):
                ready = _probe(folder)
        return _result(ready, current)
    except (OSError, ConnectionError):
        return _result(available=False)


def _clean_inactive(account):
    """Drop old private sessions only after their active research
    releases them."""
    current = _current(account)
    for folder in account.iterdir():
        if not re.fullmatch(r"[a-f0-9]{32}", folder.name) or folder.name == current:
            continue
        try:
            _directory(folder)
            with _lock(folder, blocking=False):
                # End local access without extracting or copying native tokens.
                shutil.rmtree(folder)
        except (ConnectionError, OSError):
            continue


@contextmanager
def session_environment(identifier, expected_session_id=None):
    """Pin the selected login while allowing a fresh independent native
    sign-in."""
    account = _account(identifier)
    if expected_session_id is not None:
        _identifier(expected_session_id)
    with _lock(account):
        current = _current(account)
        if current is None or (
            expected_session_id is not None and current != expected_session_id
        ):
            raise ConnectionError(
                "The Claude Code session changed. Check the connection again."
            )
        folder = _directory(account / current)
        pinned = _lock(folder, shared=True)
        pinned.__enter__()
    try:
        yield {
            key: _base_environment(folder)[key] for key in ("HOME", "CLAUDE_CONFIG_DIR")
        }
    finally:
        pinned.__exit__(None, None, None)
        with _lock(account):
            _clean_inactive(account)


def environment(identifier):
    """Resolve native paths only; execution must use session_environment
    instead."""
    with session_environment(identifier) as value:
        return dict(value)


def logout(identifier):
    account = _account(identifier)
    with _lock(account):
        (account / "current.json").unlink(missing_ok=True)
        _clean_inactive(account)
    return _result()


def login(identifier):
    """Run the actual native login UI on the user's own interactive
    terminal."""
    if not os.isatty(0) or not os.isatty(1):
        raise ConnectionError("Run this sign-in command in an interactive terminal.")
    if not os.access(CLAUDE_BINARY, os.X_OK):
        raise ConnectionError("Install the current Labcat Docker image first.")
    account = _account(identifier)
    # A separate challenge lock bounds concurrent logins without holding the
    # account lock or disturbing its current signed-in session during research.
    challenge = _directory(account / "login")
    with _lock(challenge, blocking=False):
        session_id = uuid4().hex
        folder = _directory(account / session_id)
        try:
            with _lock(folder, shared=True):
                print(
                    (
                        "Complete Claude Code's own sign-in below. Do not paste login "
                        "codes into Labcat."
                    ),
                    flush=True,
                )
                completed = subprocess.run(
                    [CLAUDE_BINARY, "auth", "login"],
                    env=_base_environment(folder),
                    cwd=folder,
                    timeout=600,
                    check=False,
                )
                if completed.returncode != 0 or not _probe(folder):
                    raise ConnectionError(
                        "Claude Code did not complete sign-in. "
                        "Your previous connection is unchanged."
                    )
                with _lock(account):
                    atomic_write(account / "current.json", {"session_id": session_id})
        finally:
            with _lock(account):
                _clean_inactive(account)
        print(
            (
                "Claude Code is connected for this worker session. Return to "
                "Labcat and check the connection."
            ),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Sign in using Claude Code's native terminal flow."
    )
    parser.add_argument("action", choices=("login", "logout", "status"))
    parser.add_argument("account_id")
    args = parser.parse_args()
    try:
        if args.action == "login":
            login(args.account_id)
        else:
            print(json.dumps(globals()[args.action](args.account_id)))
    except (ConnectionError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
        parser.exit(
            1,
            (
                "Claude Code connection could not be completed. Retry the command; "
                "existing connections remain available.\n"
            ),
        )


if __name__ == "__main__":
    main()
