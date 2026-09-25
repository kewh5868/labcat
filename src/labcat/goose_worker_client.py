"""Fixed private-container transport; the workspace process never
launches Goose.

Only the named worker receives the selected model credential and bounded
task context. A short-lived callback port exposes a closed intake
decision and two actions for one random job capability. No arbitrary
worker/callback URL is accepted.
"""

import json
import os
import secrets
import stat
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from labcat.credentials import unique_json_object
from labcat.goose_runtime import (
    GOOSE_VERSION,
    MAX_RUNTIME_SECONDS,
)
from labcat.models import ModelError

WORKER_ORIGIN = "http://goose-worker:8765"


CHANNEL_KEY_PATH = Path("/run/labcat-channel/key")


MAX_WIRE_BYTES = 128_000


_SAFE_FAILURE = (
    "The isolated research worker is unavailable or did not finish safely. "
    "No local Goose process was started and the model call was not retried."
)


def remote_enabled() -> bool:
    return os.environ.get("LABCAT_GOOSE_REMOTE") == "1"


def _channel_key() -> str:
    """Read only the deployment-owned channel key, never a caller's file
    path."""
    descriptor = None
    try:
        descriptor = os.open(CHANNEL_KEY_PATH, os.O_RDONLY | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid != os.getuid()
            or info.st_size not in {64, 65}
        ):
            raise ValueError
        raw = os.read(descriptor, 66).strip()
        value = raw.decode("ascii")
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError
        return value
    except (OSError, ValueError, AttributeError):
        raise ModelError(
            "The private research-worker channel is unavailable."
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def initialize_channel() -> None:
    """Bootstrap the channel as the parent; the worker mounts it read-
    only."""
    if not remote_enabled():
        return
    descriptor = None
    try:
        descriptor = os.open(
            CHANNEL_KEY_PATH,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        value = secrets.token_hex(32).encode("ascii")
        if os.write(descriptor, value) != len(value):
            raise OSError
        os.fsync(descriptor)
    except FileExistsError:
        pass
    except (OSError, AttributeError):
        raise ModelError(
            "Mount the private research-worker channel before startup."
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _channel_key()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelError(_SAFE_FAILURE)


def _worker_request(path: str, body: dict | None = None) -> dict:
    if not remote_enabled() or path not in {
        "/status",
        "/run",
        "/auth/start",
        "/auth/poll",
        "/auth/cancel",
        "/auth/take",
        "/auth/callback",
    }:
        raise ModelError(_SAFE_FAILURE)
    key = _channel_key()
    try:
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        if data is not None and len(data) > MAX_WIRE_BYTES:
            raise ValueError
        request = Request(
            WORKER_ORIGIN + path,
            data=data,
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="GET" if body is None else "POST",
        )
        with build_opener(ProxyHandler({}), _NoRedirect()).open(
            request, timeout=2 if path == "/status" else MAX_RUNTIME_SECONDS + 15
        ) as response:
            if response.status != 200:
                raise ValueError
            raw = response.read(MAX_WIRE_BYTES + 1)
        if len(raw) > MAX_WIRE_BYTES:
            raise ValueError
        value = json.loads(raw, object_pairs_hook=unique_json_object)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except Exception:
        raise ModelError(_SAFE_FAILURE) from None


def runtime_status() -> dict:
    """An authenticated worker probe, without a model call or local
    process launch."""
    ready = False
    if remote_enabled():
        try:
            status = _worker_request("/status")
            ready = (
                status.get("available") is True
                and status.get("version") == GOOSE_VERSION
                and status.get("engine") == "goose"
                and status.get("isolation") == "separate_container"
            )
        except ModelError:
            pass
    return {"available": ready, "version": GOOSE_VERSION, "engine": "goose"}
