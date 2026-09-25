"""Goose-owned browser OAuth in a private, memory-backed configure
process.

The PTY answers only configure's first two menus, then stops at model
selection. No model test, prompt, tool, host credential or persisted
Goose profile is used. Only the worker calls this broker; credential
handoff is never a public route.
"""

import copy
import http.client
import json
import os
import re
import select
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from labcat.chatgpt_auth import (
    AUTH_DOCUMENT_LIMIT,
    ChatGPTAuthError,
    ChatGPTSetupError,
    _is_tmpfs,
    _jwt_payload,
    _private_directory,
    _private_write,
    validate_auth_document,
)
from labcat.credentials import unique_json_object

GOOSE_BINARY = Path("/usr/local/bin/goose")
FLOW_TTL_SECONDS = 300
START_TIMEOUT_SECONDS = 25
MAX_OUTPUT = 256_000
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT = "http://localhost:1455/auth/callback"
FLOW_DIRECTORY_ENV = "LABCAT_GOOSE_AUTH_FLOW_DIR"
_SAFE_ERROR = "Goose could not complete ChatGPT sign-in. Start sign-in again."
_ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")
_CALLBACK_OK = (
    b"<!doctype html><meta charset=utf-8><title>Labcat sign-in</title>"
    b"<p>Sign-in received. Return to Labcat to check the connection.</p>"
)
_CALLBACK_FAILED = (
    b"<!doctype html><meta charset=utf-8><title>Labcat sign-in</title>"
    b"<p>This sign-in could not be completed. Return to Labcat and start again.</p>"
)


def _fail():
    raise ChatGPTAuthError(_SAFE_ERROR) from None


def validate_authorize_url(value):
    """Accept the same pinned Goose PKCE provider/callback as the
    standalone probe."""
    try:
        if not isinstance(value, str) or len(value) > 8192:
            _fail()
        if any(ord(char) <= 32 or ord(char) >= 127 for char in value):
            _fail()
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.netloc != "auth.openai.com"
            or url.path != "/oauth/authorize"
            or url.fragment
        ):
            _fail()
        query = parse_qs(url.query, strict_parsing=True, keep_blank_values=True)
        if any(len(values) != 1 for values in query.values()):
            _fail()
        expected = {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "code_challenge_method": "S256",
        }
        if any(query.get(key) != [item] for key, item in expected.items()):
            _fail()
        for key in ("state", "code_challenge"):
            items = query.get(key, [])
            if len(items) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{20,256}", items[0]):
                _fail()
        return value
    except (ValueError, TypeError):
        _fail()


def _owned_directory(path):
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        _fail()
    status = path.stat()
    if (
        not stat.S_ISDIR(status.st_mode)
        or stat.S_IMODE(status.st_mode) != 0o700
        or status.st_uid != os.getuid()
    ):
        _fail()


def _private_read(path, root, limit):
    """Check ownership and permissions on the opened inode, not just its
    name."""
    try:
        if root not in path.parents:
            _fail()
        for directory in path.parents:
            _owned_directory(directory)
            if directory == root:
                break
        descriptor = os.open(
            path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(descriptor, "rb") as stream:
            status = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(status.st_mode)
                or stat.S_IMODE(status.st_mode) != 0o600
                or status.st_uid != os.getuid()
                or status.st_nlink != 1
            ):
                _fail()
            value = stream.read(limit + 1)
        if len(value) > limit:
            _fail()
        return value
    except (OSError, ValueError):
        _fail()


def _capture_browser(value):
    """BROWSER helper mode: capture only this flow's validated
    authorization URL."""
    temporary = None
    try:
        value = validate_authorize_url(value)
        root = Path(os.environ.get(FLOW_DIRECTORY_ENV, ""))
        _owned_directory(root)
        if not _is_tmpfs(root) or not re.fullmatch(
            r"labcat-chatgpt-[A-Za-z0-9_-]+", root.name
        ):
            _fail()
        target = root / "browser-url"
        if target.exists():
            if _private_read(target, root, 8192).decode("ascii") != value:
                _fail()
            return
        descriptor, temporary = tempfile.mkstemp(prefix=".browser-", dir=root)
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(value)
        os.replace(temporary, target)
        temporary = None
    except (OSError, ValueError, UnicodeError):
        _fail()
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def _cache_credentials(directory):
    try:
        value = json.loads(
            _private_read(
                directory / "config/chatgpt_codex/tokens.json",
                directory,
                AUTH_DOCUMENT_LIMIT,
            ),
            object_pairs_hook=unique_json_object,
        )
        if not isinstance(value, dict) or set(value) != {
            "access_token",
            "refresh_token",
            "id_token",
            "account_id",
            "expires_at",
        }:
            _fail()
        document = validate_auth_document(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    key: item for key, item in value.items() if key != "expires_at"
                },
                "last_refresh": datetime.now(UTC).isoformat(),
            }
        )
        if not isinstance(value["expires_at"], str) or len(value["expires_at"]) > 64:
            _fail()
        expiration = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
        claims = _jwt_payload(document["tokens"]["access_token"])
        # Goose derives its cache deadline from expires_in plus receipt time,
        # which can include sub-seconds and need not equal the JWT's exp claim.
        if (
            expiration.tzinfo is None
            or expiration <= datetime.now(UTC)
            or claims["exp"] <= datetime.now(UTC).timestamp()
        ):
            _fail()
        # Decode only to reject a contradictory cache. Goose verifies OAuth;
        # JWT decoding here does not authenticate the account or its claims.
        for key in ("access_token", "id_token"):
            payload = _jwt_payload(document["tokens"][key])
            identity = payload.get("https://api.openai.com/auth", {})
            if (
                not isinstance(identity, dict)
                or identity.get("chatgpt_account_id", document["tokens"]["account_id"])
                != document["tokens"]["account_id"]
                or payload.get("chatgpt_account_id", document["tokens"]["account_id"])
                != document["tokens"]["account_id"]
            ):
                _fail()
        return document
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        _fail()


class _GooseConfigureSession:
    """One bounded PTY; no configure model selection or test is ever
    answered."""

    def __init__(self, temporary_root, *, process_factory=None, clock=None):
        self.directory = _private_directory(temporary_root)
        self.process = None
        self.master = None
        self._reader = None
        self._lock = threading.RLock()
        self._process_lock = threading.Lock()
        self._cancelled = threading.Event()
        self._ready = threading.Event()
        self._clock = clock or time.monotonic
        self._deadline = self._clock() + FLOW_TTL_SECONDS
        self._url = None
        self._status = "pending"
        self._credentials = None
        slave = None
        try:
            if not GOOSE_BINARY.is_file():
                raise ChatGPTSetupError("chatgpt_helper_unavailable")
            # Unix-only runtime imports stay lazy so the package imports on Windows.
            import pty

            (self.directory / "config").mkdir(mode=0o700)
            _private_write(
                self.directory / "config/config.yaml",
                "GOOSE_PROVIDER: chatgpt_codex\nextensions: {}\n",
            )
            environment = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "TERM": "xterm-256color",
                "LANG": "C.UTF-8",
                "HOME": str(self.directory),
                "GOOSE_PATH_ROOT": str(self.directory),
                "XDG_CONFIG_HOME": str(self.directory),
                "XDG_DATA_HOME": str(self.directory),
                "XDG_CACHE_HOME": str(self.directory),
                "TMPDIR": str(self.directory),
                "GOOSE_DISABLE_KEYRING": "1",
                "GOOSE_TELEMETRY_OFF": "1",
                "GOOSE_TELEMETRY_ENABLED": "false",
                "CONTEXT_FILE_NAMES": "[]",
                "HTTPS_PROXY": "http://goose-egress:8780",
                "HTTP_PROXY": "http://goose-egress:8780",
                "NO_PROXY": "127.0.0.1,localhost",
                # Docker's private tmpfs is deliberately noexec. Launch the
                # installed interpreter directly using webbrowser's %s argument
                # placeholder; never execute a helper from writable storage.
                "BROWSER": shlex.quote(sys.executable)
                + " -I -m labcat.goose_browser_auth capture %s",
                FLOW_DIRECTORY_ENV: str(self.directory),
            }
            self.master, slave = pty.openpty()
            self.process = (process_factory or subprocess.Popen)(
                [str(GOOSE_BINARY), "configure"],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=self.directory,
                env=environment,
                start_new_session=True,
                umask=0o077,
            )
            os.close(slave)
            slave = None
            self._reader = threading.Thread(target=self._run, daemon=True)
            self._reader.start()
        except Exception as error:
            if slave is not None:
                os.close(slave)
            self.close()
            if isinstance(error, ChatGPTSetupError):
                raise
            _fail()

    def _stop_process(self):
        with self._process_lock:
            if self.process is not None:
                if self.process.poll() is None:
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                self.process.wait(timeout=5)

    def _run(self):
        prompts = [
            b"What would you like to configure?",
            b"Which model provider should we use?",
        ]
        pending = b""
        output_size = 0
        credentials = None
        try:
            while (
                not self._cancelled.is_set()
                and self._clock() < self._deadline
                and self.process.poll() is None
            ):
                target = self.directory / "browser-url"
                if target.exists():
                    url = validate_authorize_url(
                        _private_read(target, self.directory, 8192).decode("ascii")
                    )
                    with self._lock:
                        if self._url is not None and url != self._url:
                            _fail()
                        self._url = url
                        self._ready.set()
                if not select.select([self.master], [], [], 0.1)[0]:
                    continue
                data = os.read(self.master, 8192)
                if not data:
                    break
                output_size += len(data)
                if output_size > MAX_OUTPUT:
                    _fail()
                pending += data
                clean = _ANSI.sub(b"", pending)
                if prompts and prompts[0] in clean:
                    prompts.pop(0)
                    os.write(self.master, b"\r")
                    pending = b""
                elif not prompts and b"Select a model:" in clean:
                    # configure otherwise runs a weather-tool connectivity test.
                    # Stop the entire process group before reading its token cache.
                    self._stop_process()
                    credentials = _cache_credentials(self.directory)
                    break
        except Exception:
            credentials = None
        finally:
            try:
                self._stop_process()
            except Exception:
                credentials = None
            if self.master is not None:
                os.close(self.master)
                self.master = None
            shutil.rmtree(self.directory, ignore_errors=True)
            with self._lock:
                if self._cancelled.is_set():
                    self._status = "cancelled"
                elif self._clock() >= self._deadline:
                    self._status = "expired"
                else:
                    self._status = "complete" if credentials else "error"
                self._credentials = credentials if self._status == "complete" else None
                self._ready.set()

    def start(self):
        if not self._ready.wait(START_TIMEOUT_SECONDS):
            self.close()
            _fail()
        with self._lock:
            if self._status not in {"pending", "complete"} or self._url is None:
                _fail()
            return self._url

    def poll(self):
        with self._lock:
            return self._status

    def credentials(self):
        with self._lock:
            if self._status != "complete" or self._credentials is None:
                _fail()
            return copy.deepcopy(self._credentials)

    def close(self):
        self._cancelled.set()
        try:
            self._stop_process()
        finally:
            if self._reader and self._reader is not threading.current_thread():
                self._reader.join(timeout=6)
            if self.master is not None and not self._reader:
                os.close(self.master)
                self.master = None
            shutil.rmtree(self.directory, ignore_errors=True)
            with self._lock:
                self._credentials = None
                self._status = "cancelled"


class GooseBrowserAuthBroker:
    """Single browser flow, five-minute lifetime, consume-once secret
    handoff."""

    def __init__(self, temporary_root=None, *, session_factory=None, clock=None):
        self.temporary_root = Path(
            temporary_root or os.environ.get("LABCAT_AUTH_TMPDIR", "/tmp")
        )
        self._session_factory = session_factory or _GooseConfigureSession
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._flow = None
        self._timer = None

    def _public(self):
        return {
            **{
                key: self._flow[key]
                for key in ("flow_id", "status", "verification_url")
            },
            "method": "browser",
            "user_code": None,
        }

    def _finish(self, status):
        self._flow["status"] = status
        session, self._flow["session"] = self._flow["session"], None
        try:
            if session:
                session.close()
        except Exception:
            self._flow["status"] = "error"
        if self._flow["status"] != "complete":
            self._flow["credentials"] = None
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def _expire(self, flow_id=None):
        with self._lock:
            if (
                self._flow
                and (flow_id is None or self._flow["flow_id"] == flow_id)
                and self._flow["status"] in {"pending", "complete"}
            ):
                self._finish("expired")

    def _current(self, flow_id):
        if not self._flow or self._flow["flow_id"] != flow_id:
            raise ChatGPTAuthError("This ChatGPT sign-in is no longer available.")
        if (
            self._flow["status"] in {"pending", "complete"}
            and self._clock() >= self._flow["expires"]
        ):
            self._finish("expired")

    def start(self):
        with self._lock:
            if self._flow and self._flow["status"] in {"pending", "complete"}:
                self._finish("cancelled")
            session = None
            try:
                started = self._clock()
                session = self._session_factory(self.temporary_root)
                url = validate_authorize_url(session.start())
                self._flow = {
                    "flow_id": uuid4().hex,
                    "status": "pending",
                    "verification_url": url,
                    "session": session,
                    "credentials": None,
                    "expires": started + FLOW_TTL_SECONDS,
                }
                self._timer = threading.Timer(
                    max(0, self._flow["expires"] - self._clock()),
                    self._expire,
                    args=(self._flow["flow_id"],),
                )
                self._timer.daemon = True
                self._timer.start()
                return self._public()
            except Exception as error:
                if session:
                    try:
                        session.close()
                    except Exception:
                        pass
                if isinstance(error, ChatGPTSetupError):
                    raise
                _fail()

    def poll(self, flow_id):
        with self._lock:
            self._current(flow_id)
            if self._flow["status"] == "pending":
                try:
                    status = self._flow["session"].poll()
                    if status == "complete":
                        self._flow["credentials"] = validate_auth_document(
                            self._flow["session"].credentials()
                        )
                        self._finish("complete")
                    elif status in {"error", "expired", "cancelled"}:
                        self._finish(status)
                    elif status != "pending":
                        self._finish("error")
                except Exception:
                    self._finish("error")
            return self._public()

    def cancel(self, flow_id):
        with self._lock:
            self._current(flow_id)
            if self._flow["status"] in {"pending", "complete"}:
                self._finish("cancelled")
            return self._public()

    def take_credentials(self, flow_id):
        with self._lock:
            self.poll(flow_id)
            if self._flow["status"] != "complete" or self._flow["credentials"] is None:
                raise ChatGPTAuthError(
                    "Complete ChatGPT sign-in before saving this connection."
                )
            credentials = self._flow["credentials"]
            self._flow["credentials"] = None
            self._flow["status"] = "consumed"
            if self._timer:
                self._timer.cancel()
                self._timer = None
            return validate_auth_document(credentials)

    def relay_callback(self, path):
        """Forward only the current provider state to its fixed loopback
        listener.

        Provider response HTML is discarded. A callback is not a success
        claim; only configure reaching model selection can complete the
        public flow.
        """
        with self._lock:
            connection = None
            try:
                if not self._flow:
                    return 409, _CALLBACK_FAILED
                self._current(self._flow["flow_id"])
                if self._flow["status"] != "pending":
                    return 409, _CALLBACK_FAILED
                if (
                    not isinstance(path, str)
                    or len(path) > 8192
                    or any(ord(char) <= 32 or ord(char) >= 127 for char in path)
                ):
                    return 400, _CALLBACK_FAILED
                url = urlsplit(path)
                if (
                    url.scheme
                    or url.netloc
                    or url.fragment
                    or url.path != "/auth/callback"
                ):
                    return 400, _CALLBACK_FAILED
                query = parse_qs(url.query, strict_parsing=True, keep_blank_values=True)
                expected_state = parse_qs(
                    urlsplit(self._flow["verification_url"]).query
                )["state"]
                if (
                    query.get("state") != expected_state
                    or any(len(values) != 1 for values in query.values())
                    or set(query)
                    - {"state", "code", "scope", "error", "error_description"}
                    or ("code" in query) == ("error" in query)
                    or any(
                        any(ord(char) < 32 or ord(char) > 126 for char in value)
                        for values in query.values()
                        for value in values
                    )
                ):
                    return 400, _CALLBACK_FAILED
                if not query.get("code", query.get("error"))[0]:
                    return 400, _CALLBACK_FAILED
                connection = http.client.HTTPConnection("127.0.0.1", 1455, timeout=10)
                connection.request("GET", path, headers={"Host": "localhost:1455"})
                response = connection.getresponse()
                body = response.read(64_001)
                if len(body) > 64_000 or not 200 <= response.status < 300:
                    return 502, _CALLBACK_FAILED
                return 200, _CALLBACK_OK
            except (OSError, ValueError, TypeError, http.client.HTTPException):
                return 503, _CALLBACK_FAILED
            finally:
                if connection:
                    connection.close()

    def close(self):
        with self._lock:
            if self._flow and self._flow["status"] in {"pending", "complete"}:
                self._finish("cancelled")
            if self._timer:
                self._timer.cancel()
                self._timer = None


def main():
    """Only a child Goose BROWSER command may invoke the capture
    mode."""
    if len(sys.argv) != 3 or sys.argv[1] != "capture":
        return 2
    try:
        _capture_browser(sys.argv[2])
        return 0
    except Exception:
        # Never print URLs, OAuth codes, local paths, or exception tracebacks.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
