"""Isolated, provider-owned ChatGPT device login; never a research/tool
runner.

Protocol: OpenAI Codex 0.154.0 app-server. Only freshly issued
credentials in this broker's private memory-backed directory are read.
The caller encrypts the returned auth document; it must never serialize
it in a public API response.

https://learn.chatgpt.com/docs/app-server
https://learn.chatgpt.com/docs/auth
"""

import base64
import copy
import json
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from labcat.credentials import (
    ConnectionError,
    read_private_file,
    unique_json_object,
)

CODEX_VERSION = "0.154.0"
AUTH_DOCUMENT_LIMIT = 24_000
MAX_PROTOCOL_LINE = 256_000
FLOW_TTL_SECONDS = 600
RPC_TIMEOUT_SECONDS = 25
VERIFICATION_URL = "https://auth.openai.com/codex/device"
_SAFE_ERROR = "ChatGPT connection could not be completed. Start sign-in again."
_ALLOWED_REQUESTS = frozenset(
    {
        "initialize",
        "account/login/start",
        "account/login/cancel",
        "account/read",
        "account/rateLimits/read",
        "account/usage/read",
        "model/list",
    }
)


class ChatGPTAuthError(ConnectionError):
    """A public-safe error; upstream messages and credentials are never
    attached."""


class ChatGPTSetupError(ChatGPTAuthError):
    """Fixed local runtime diagnostics, separate from
    provider/authentication errors."""

    def __init__(self, code):
        messages = {
            "chatgpt_storage_unavailable": (
                "ChatGPT sign-in requires the Docker application's "
                "memory-backed credential storage."
            ),
            "chatgpt_helper_unavailable": (
                "The supported ChatGPT sign-in helper is unavailable. "
                "Start the current Docker application image."
            ),
            "chatgpt_callback_unavailable": (
                "ChatGPT browser sign-in requires local port 1455. Free that "
                "port, then restart the supplied launcher with "
                "LABCAT_OAUTH_CALLBACK_PORT=1455. Other providers remain usable."
            ),
        }
        self.code = code
        super().__init__(messages[code])


def _fail():
    raise ChatGPTAuthError(_SAFE_ERROR) from None


def _json(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False)


def _jwt_payload(token):
    if not isinstance(token, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token
    ):
        _fail()
    try:
        encoded = token.split(".")[1]
        value = json.loads(
            base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_"),
            object_pairs_hook=unique_json_object,
        )
        if not isinstance(value, dict):
            _fail()
        return value
    except (ValueError, UnicodeError, RecursionError):
        _fail()


def validate_auth_document(value: object) -> dict:
    """Validate internal Codex file shape; never accept it from a public
    route.

    JWT decoding checks structure/expiry metadata only. It is not
    signature verification or an authority for account identity.
    Provider authentication remains the responsibility of the pinned
    Codex/Goose clients.
    """
    if not isinstance(value, dict) or set(value) - {
        "auth_mode",
        "OPENAI_API_KEY",
        "tokens",
        "last_refresh",
    }:
        _fail()
    if value.get("auth_mode") is not None and value["auth_mode"] != "chatgpt":
        _fail()
    if value.get("OPENAI_API_KEY") is not None:
        _fail()
    tokens = value.get("tokens")
    if not isinstance(tokens, dict) or set(tokens) != {
        "access_token",
        "refresh_token",
        "id_token",
        "account_id",
    }:
        _fail()
    for key in ("access_token", "refresh_token", "id_token"):
        secret = tokens[key]
        if not isinstance(secret, str) or not re.fullmatch(r"[!-~]{8,12000}", secret):
            _fail()
    account = tokens["account_id"]
    if not isinstance(account, str) or not re.fullmatch(
        r"[A-Za-z0-9_.:-]{1,200}", account
    ):
        _fail()
    claims = _jwt_payload(tokens["access_token"])
    expiration = claims.get("exp")
    if type(expiration) is not int or not 0 < expiration < 253402300800:
        _fail()
    _jwt_payload(tokens["id_token"])
    refreshed = value.get("last_refresh")
    if refreshed is not None:
        try:
            if not isinstance(refreshed, str) or len(refreshed) > 64:
                _fail()
            parsed = datetime.fromisoformat(refreshed.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                _fail()
        except ValueError:
            _fail()
    result = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": dict(tokens),
        "last_refresh": refreshed,
    }
    if len(_json(result).encode()) > AUTH_DOCUMENT_LIMIT:
        _fail()
    return result


def goose_token_cache(auth_document: object) -> dict:
    """Translate internal credentials to Goose's private temporary cache
    shape."""
    tokens = validate_auth_document(auth_document)["tokens"]
    expiration = _jwt_payload(tokens["access_token"])["exp"]
    return {
        **tokens,
        "expires_at": datetime.fromtimestamp(expiration, UTC).isoformat(),
    }


def update_from_goose_tokens(auth_document: object, cache: object) -> dict:
    """Preserve refreshed Goose credentials for the same internal OAuth
    account."""
    previous = validate_auth_document(auth_document)
    if not isinstance(cache, dict) or set(cache) != {
        "access_token",
        "refresh_token",
        "id_token",
        "account_id",
        "expires_at",
    }:
        _fail()
    if cache["account_id"] != previous["tokens"]["account_id"]:
        _fail()
    updated = {
        **previous,
        "tokens": {
            key: cache[key]
            for key in ("access_token", "refresh_token", "id_token", "account_id")
        },
        "last_refresh": datetime.now(UTC).isoformat(),
    }
    if updated["tokens"]["id_token"] is None:
        updated["tokens"]["id_token"] = previous["tokens"]["id_token"]
    return validate_auth_document(updated)


def _is_tmpfs(root: Path) -> bool:
    """Require an explicit memory filesystem, not an ordinary temporary
    folder."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        mounts = Path("/proc/self/mountinfo").read_text().splitlines()
        matches = []
        for line in mounts:
            before, after = line.split(" - ", 1)
            raw_path = before.split()[4]
            mount_path = Path(
                re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), raw_path)
            )
            if root == mount_path or mount_path in root.parents:
                matches.append((len(str(mount_path)), after.split()[0]))
        return bool(matches) and max(matches)[1] in {"tmpfs", "ramfs"}
    except (OSError, ValueError, IndexError):
        return False


def _private_directory(root: Path) -> Path:
    if not root.is_absolute():
        raise ChatGPTSetupError("chatgpt_storage_unavailable")
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ChatGPTSetupError("chatgpt_storage_unavailable")
    if not root.is_dir() or not _is_tmpfs(root):
        raise ChatGPTSetupError("chatgpt_storage_unavailable")
    try:
        directory = Path(tempfile.mkdtemp(prefix="labcat-chatgpt-", dir=root))
        directory.chmod(0o700)
        return directory
    except OSError:
        _fail()


def _private_write(path: Path, value: str):
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
    except OSError:
        _fail()


class _CodexSession:
    """Bounded line protocol with an immutable method allowlist and no
    tools."""

    def __init__(self, binary: Path, temporary_root: Path, auth_document=None):
        self.directory = _private_directory(temporary_root)
        self.process = None
        self._queue = queue.Queue(maxsize=128)
        self._notifications = []
        self._sequence = 0
        self._broken = threading.Event()
        self._lock = threading.RLock()
        self._reader = None
        try:
            if not binary.is_absolute() or not binary.is_file():
                raise ChatGPTSetupError("chatgpt_helper_unavailable")
            _private_write(
                self.directory / "config.toml",
                'cli_auth_credentials_store = "file"\n'
                'model_provider = "openai"\n'
                "check_for_update_on_startup = false\n"
                "[analytics]\nenabled = false\n",
            )
            if auth_document is not None:
                _private_write(
                    self.directory / "auth.json",
                    _json(validate_auth_document(auth_document)),
                )
            # No inherited API keys, proxy URLs, cookies, home, custom endpoint,
            # project settings, or host credential stores enter this process.
            environment = {
                "HOME": str(self.directory),
                "CODEX_HOME": str(self.directory),
                "XDG_CONFIG_HOME": str(self.directory),
                "XDG_DATA_HOME": str(self.directory),
                "XDG_CACHE_HOME": str(self.directory),
                "TMPDIR": str(self.directory),
                "TMP": str(self.directory),
                "TEMP": str(self.directory),
                "PATH": os.pathsep.join((str(binary.parent), "/usr/bin", "/bin")),
                "LANG": "C.UTF-8",
                "NO_COLOR": "1",
            }
            version = subprocess.run(
                [str(binary), "--version"],
                cwd=self.directory,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            if (
                version.returncode
                or version.stdout.strip() != f"codex-cli {CODEX_VERSION}".encode()
            ):
                raise ChatGPTSetupError("chatgpt_helper_unavailable")
            self.process = subprocess.Popen(
                [str(binary), "app-server", "--listen", "stdio://"],
                cwd=self.directory,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._reader = threading.Thread(target=self._read, daemon=True)
            self._reader.start()
            self.request(
                "initialize",
                {
                    "clientInfo": {"name": "labcat", "version": "0.1.0"},
                    "capabilities": {"experimentalApi": False},
                },
            )
            self._send({"method": "initialized"})
        except ChatGPTSetupError:
            self.close()
            raise
        except Exception:
            self.close()
            raise ChatGPTAuthError(_SAFE_ERROR) from None

    def _read(self):
        try:
            while self.process and self.process.stdout:
                line = self.process.stdout.readline(MAX_PROTOCOL_LINE + 1)
                if not line:
                    break
                if len(line) > MAX_PROTOCOL_LINE:
                    break
                message = json.loads(line, object_pairs_hook=unique_json_object)
                if not isinstance(message, dict):
                    break
                self._queue.put_nowait(message)
            self._broken.set()
        except (OSError, ValueError, UnicodeError, RecursionError, queue.Full):
            self._broken.set()

    def _send(self, value):
        try:
            if (
                not self.process
                or not self.process.stdin
                or self.process.poll() is not None
            ):
                _fail()
            self.process.stdin.write((_json(value) + "\n").encode())
            self.process.stdin.flush()
        except (OSError, ValueError):
            _fail()

    def _remember(self, message):
        # This broker never starts an agent or accepts a server tool request.
        if "method" in message and "id" in message:
            self._send(
                {
                    "id": message["id"],
                    "error": {
                        "code": -32601,
                        "message": "This client does not execute tools.",
                    },
                }
            )
        elif message.get("method") == "account/login/completed":
            if len(self._notifications) >= 4:
                _fail()
            self._notifications.append(message.get("params"))

    def request(self, method, params=None):
        if method not in _ALLOWED_REQUESTS:
            _fail()
        with self._lock:
            self._sequence += 1
            request_id = self._sequence
            self._send({"id": request_id, "method": method, "params": params or {}})
            deadline = time.monotonic() + RPC_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                try:
                    message = self._queue.get(timeout=0.1)
                except queue.Empty:
                    if self._broken.is_set():
                        _fail()
                    continue
                if message.get("id") == request_id and "method" not in message:
                    if "error" in message or "result" not in message:
                        _fail()
                    return message["result"]
                self._remember(message)
            _fail()

    def notifications(self):
        with self._lock:
            while True:
                try:
                    self._remember(self._queue.get_nowait())
                except queue.Empty:
                    break
            events, self._notifications = self._notifications, []
            if not events and self._broken.is_set():
                _fail()
            return events

    def credentials(self):
        try:
            return validate_auth_document(
                json.loads(
                    read_private_file(
                        self.directory / "auth.json", AUTH_DOCUMENT_LIMIT
                    ),
                    object_pairs_hook=unique_json_object,
                )
            )
        except Exception:
            _fail()

    def close(self):
        with self._lock:
            process, self.process = self.process, None
            if process is not None:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                        process.wait(timeout=2)
                    except (OSError, subprocess.TimeoutExpired):
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=2)
                        except (OSError, subprocess.TimeoutExpired):
                            pass
                for stream in (process.stdin, process.stdout):
                    if stream:
                        stream.close()
            if self._reader and self._reader is not threading.current_thread():
                self._reader.join(timeout=1)
            if self.directory.exists():
                shutil.rmtree(self.directory)


def _safe_label(value, maximum=120):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        _fail()
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _fail()
    return value


def _window(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        _fail()
    percent = value.get("usedPercent")
    if (
        type(percent) not in (int, float)
        or not math.isfinite(percent)
        or not 0 <= percent <= 100
    ):
        _fail()
    result = {"used_percent": percent, "remaining_percent": 100 - percent}
    for source, target in (
        ("windowDurationMins", "window_minutes"),
        ("resetsAt", "resets_at"),
    ):
        number = value.get(source)
        if number is not None and (
            type(number) is not int or not 0 <= number <= 253402300800
        ):
            _fail()
        result[target] = number
    return result


def _rate_limits(value, account_id):
    if not isinstance(value, dict):
        _fail()
    if value.get("accountId") is not None and value["accountId"] != account_id:
        _fail()
    buckets = value.get("rateLimitsByLimitId")
    if buckets is None:
        buckets = {"codex": value.get("rateLimits")}
    if not isinstance(buckets, dict) or not 1 <= len(buckets) <= 32:
        _fail()
    result = []
    for key, bucket in buckets.items():
        if not isinstance(bucket, dict):
            _fail()
        identifier = _safe_label(bucket.get("limitId") or key, 80)
        label = _safe_label(bucket.get("limitName") or identifier, 120)
        result.append(
            {
                "id": identifier,
                "label": label,
                "primary": _window(bucket.get("primary")),
                "secondary": _window(bucket.get("secondary")),
            }
        )
    return result


def _token_activity(value):
    if not isinstance(value, dict) or not isinstance(value.get("summary"), dict):
        _fail()
    result = {}
    for key in (
        "lifetimeTokens",
        "peakDailyTokens",
        "longestRunningTurnSec",
        "currentStreakDays",
        "longestStreakDays",
    ):
        number = value["summary"].get(key)
        if number is not None and (
            type(number) is not int or not 0 <= number <= 2**63 - 1
        ):
            _fail()
        result[key] = number
    return result


class ChatGPTAuthBroker:
    """One pending sign-in per broker.

    Call close() at application shutdown.     ``take_credentials`` is
    internal-only and consumes a completed flow exactly     once.
    ``metadata`` returns ``(public_metadata, refreshed_auth_document)``;
    the caller must persist the second value securely, including partial
    reads.
    """

    def __init__(
        self,
        binary: Path | None = None,
        temporary_root: Path | None = None,
        *,
        session_factory=None,
        clock=None,
    ):
        self.binary = Path(
            binary or os.environ.get("LABCAT_CODEX_BINARY", "/usr/local/bin/codex")
        )
        self.temporary_root = Path(
            temporary_root or os.environ.get("LABCAT_AUTH_TMPDIR", "/tmp")
        )
        self._session_factory = session_factory or _CodexSession
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._flow = None
        self._timer = None

    def _public(self):
        return {
            key: self._flow[key]
            for key in ("flow_id", "status", "verification_url", "user_code")
        }

    def _finish(self, status):
        self._flow["status"] = status
        if self._flow["session"] is not None:
            try:
                self._flow["session"].close()
            except Exception:
                status = "error"
                self._flow["status"] = status
            finally:
                self._flow["session"] = None
        if status != "complete":
            self._flow["credentials"] = None
        if self._timer and status != "complete":
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

    def start(self) -> dict:
        with self._lock:
            if self._flow and self._flow["status"] in {"pending", "complete"}:
                self.cancel(self._flow["flow_id"])
            session = None
            try:
                session = self._session_factory(self.binary, self.temporary_root)
                result = session.request(
                    "account/login/start", {"type": "chatgptDeviceCode"}
                )
                if (
                    not isinstance(result, dict)
                    or result.get("type") != "chatgptDeviceCode"
                ):
                    _fail()
                login_id = _safe_label(result.get("loginId"), 128)
                code = result.get("userCode")
                if (
                    result.get("verificationUrl") != VERIFICATION_URL
                    or not isinstance(code, str)
                    or not re.fullmatch(r"[A-Z0-9-]{4,32}", code)
                ):
                    _fail()
                self._flow = {
                    "flow_id": uuid4().hex,
                    "status": "pending",
                    "verification_url": VERIFICATION_URL,
                    "user_code": code,
                    "login_id": login_id,
                    "session": session,
                    "expires": self._clock() + FLOW_TTL_SECONDS,
                    "credentials": None,
                }
                self._timer = threading.Timer(
                    FLOW_TTL_SECONDS, self._expire, args=(self._flow["flow_id"],)
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
                raise ChatGPTAuthError(_SAFE_ERROR) from None

    def poll(self, flow_id: str) -> dict:
        with self._lock:
            self._current(flow_id)
            if self._flow["status"] != "pending":
                return self._public()
            try:
                for event in self._flow["session"].notifications():
                    if (
                        not isinstance(event, dict)
                        or event.get("loginId") != self._flow["login_id"]
                    ):
                        continue
                    if event.get("success") is not True:
                        self._finish("error")
                        break
                    self._flow["credentials"] = self._flow["session"].credentials()
                    self._finish("complete")
                    break
            except Exception:
                self._finish("error")
            return self._public()

    def cancel(self, flow_id: str) -> dict:
        with self._lock:
            self._current(flow_id)
            if self._flow["status"] == "pending":
                # Killing the private helper stops its polling even if its
                # network connection cannot acknowledge login cancellation.
                self._finish("cancelled")
            elif self._flow["status"] == "complete":
                self._finish("cancelled")
            self._flow["credentials"] = None
            return self._public()

    def take_credentials(self, flow_id: str) -> dict:
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

    def metadata(self, auth_document: object) -> tuple[dict, dict]:
        auth = validate_auth_document(auth_document)
        public = {
            "models": [],
            "account_ready": False,
            "rate_limits": None,
            "token_activity": None,
            "notices": [],
            "inference_tested": False,
        }
        # Serialize refreshes for this broker; callers must also serialize
        # applying returned credentials to the associated account vault slot.
        with self._lock:
            session = None
            try:
                session = self._session_factory(self.binary, self.temporary_root, auth)
                try:
                    account = session.request("account/read", {"refreshToken": True})
                    if (
                        not isinstance(account, dict)
                        or not isinstance(account.get("account"), dict)
                        or account["account"].get("type") != "chatgpt"
                    ):
                        _fail()
                    public["account_ready"] = True
                except ChatGPTAuthError:
                    public["notices"].append(
                        "ChatGPT account readiness is unavailable. "
                        "Reconnect if requests fail."
                    )
                try:
                    models, seen, cursor = [], set(), None
                    for _ in range(8):
                        page = session.request(
                            "model/list",
                            {
                                "limit": 50,
                                "includeHidden": False,
                                **({"cursor": cursor} if cursor else {}),
                            },
                        )
                        if (
                            not isinstance(page, dict)
                            or not isinstance(page.get("data"), list)
                            or len(page["data"]) > 100
                        ):
                            _fail()
                        for model in page["data"]:
                            if (
                                not isinstance(model, dict)
                                or model.get("hidden", False) is not False
                            ):
                                continue
                            identifier = _safe_label(
                                model.get("model") or model.get("id"), 200
                            )
                            if not re.fullmatch(r"[A-Za-z0-9_.:/-]+", identifier):
                                _fail()
                            label = _safe_label(model.get("displayName") or identifier)
                            efforts = model.get("supportedReasoningEfforts", [])
                            if not isinstance(efforts, list) or len(efforts) > 12:
                                _fail()
                            levels = [
                                _safe_label(e.get("reasoningEffort"), 32)
                                for e in efforts
                                if isinstance(e, dict)
                            ]
                            if identifier not in seen:
                                models.append(
                                    {
                                        "id": identifier,
                                        "label": label,
                                        "default": model.get("isDefault") is True,
                                        "reasoning_efforts": levels,
                                    }
                                )
                                seen.add(identifier)
                        cursor = page.get("nextCursor")
                        if cursor is None:
                            break
                        _safe_label(cursor, 512)
                    else:
                        _fail()
                    public["models"] = models
                except ChatGPTAuthError:
                    public["notices"].append("The account model list is unavailable.")
                try:
                    public["rate_limits"] = _rate_limits(
                        session.request("account/rateLimits/read"),
                        auth["tokens"]["account_id"],
                    )
                except ChatGPTAuthError:
                    public["notices"].append(
                        "Account usage limits are unavailable; "
                        "no remaining-token balance is inferred."
                    )
                try:
                    public["token_activity"] = _token_activity(
                        session.request("account/usage/read")
                    )
                except ChatGPTAuthError:
                    public["notices"].append(
                        "Account token activity is unavailable "
                        "for this connection helper."
                    )
                # Read even when metadata is partially unavailable: refresh
                # token rotation may already have succeeded inside Codex.
                refreshed = session.credentials()
                if refreshed["tokens"]["account_id"] != auth["tokens"]["account_id"]:
                    _fail()
                return public, copy.deepcopy(refreshed)
            except Exception:
                raise ChatGPTAuthError(_SAFE_ERROR) from None
            finally:
                if session:
                    try:
                        session.close()
                    except Exception:
                        raise ChatGPTAuthError(_SAFE_ERROR) from None

    def close(self):
        with self._lock:
            if self._flow:
                self.cancel(self._flow["flow_id"])
            if self._timer:
                self._timer.cancel()
                self._timer = None
