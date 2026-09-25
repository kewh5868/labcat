"""Fixed private-container transport; the workspace process never
launches Goose.

Only the named worker receives the selected model credential and bounded
task context. A short-lived callback port exposes a closed intake
decision and two actions for one random job capability. No arbitrary
worker/callback URL is accepted.
"""

import hmac
import json
import os
import secrets
import stat
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from labcat.agent_rejections import parent_rejection_reply
from labcat.agent_tools import valid_lead_arguments, valid_search_arguments
from labcat.credentials import unique_json_object
from labcat.goose_runtime import (
    FAILURE_CODES,
    GOOSE_VERSION,
    MAX_RUNTIME_SECONDS,
    GooseRuntimeError,
    _aws_credentials,
)
from labcat.models import ModelError, bounded_context
from labcat.research_intent import valid_assessment_arguments
from labcat.science.literature_evaluation import (
    valid_evaluation_transport_arguments,
)

WORKER_ORIGIN = "http://goose-worker:8765"
CALLBACK_HOST = "0.0.0.0"
CALLBACK_PORT = 8766
CHANNEL_KEY_PATH = Path("/run/labcat-channel/key")
MAX_WIRE_BYTES = 128_000
MAX_CALLBACK_BYTES = 32_000
MAX_CALLBACK_CALLS = 8
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


class _CallbackServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@contextmanager
def _callbacks(session, job_id: str, token: str):
    """Publish the fixed tools on the private network for this one
    request."""
    definitions = session.tool_definitions()
    names = {
        "assess_research_intent",
        "search_public_references",
        "propose_candidate_leads",
        "evaluate_candidate_fit",
        "generate_ranked_report",
    }
    trace = []
    lock = threading.Lock()
    closed = threading.Event()
    deadline = time.monotonic() + MAX_RUNTIME_SECONDS + 5

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def _send(self, status, value):
            raw = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(raw)
            except OSError:
                pass

        def do_POST(self):
            if (
                closed.is_set()
                or time.monotonic() >= deadline
                or self.headers.get("Origin")
                or self.headers.get("Referer")
                or self.headers.get("Host") != "labcat:8766"
                or len(self.headers.get_all("Authorization", [])) != 1
                or not hmac.compare_digest(
                    self.headers.get("Authorization", "").encode(),
                    ("Bearer " + token).encode(),
                )
            ):
                self._send(403, {"status": "rejected"})
                return
            try:
                if len(
                    self.headers.get_all("Content-Length", [])
                ) != 1 or self.headers.get("Transfer-Encoding"):
                    raise ValueError
                length = int(self.headers["Content-Length"])
                if not 0 < length <= MAX_CALLBACK_BYTES:
                    raise ValueError
                body = json.loads(
                    self.rfile.read(length), object_pairs_hook=unique_json_object
                )
                if self.path == f"/{job_id}/tools/list" and body == {}:
                    result = {"tools": definitions}
                elif self.path == f"/{job_id}/tools/call" and (
                    isinstance(body, dict)
                    and set(body) == {"name", "arguments"}
                    and isinstance(body["name"], str)
                    and body["name"] in names
                    and type(body["arguments"]) is dict
                    and (
                        (
                            body["name"] == "assess_research_intent"
                            and valid_assessment_arguments(body["arguments"])
                        )
                        or (
                            body["name"] == "generate_ranked_report"
                            and not body["arguments"]
                        )
                        or (
                            body["name"] == "search_public_references"
                            and valid_search_arguments(body["arguments"])
                        )
                        or (
                            body["name"] == "propose_candidate_leads"
                            and valid_lead_arguments(body["arguments"])
                        )
                        or (
                            body["name"] == "evaluate_candidate_fit"
                            and valid_evaluation_transport_arguments(body["arguments"])
                        )
                    )
                ):
                    with lock:
                        if (
                            closed.is_set()
                            or time.monotonic() >= deadline
                            or len(trace) >= MAX_CALLBACK_CALLS
                        ):
                            raise ValueError
                        record = {"tool": body["name"], "status": "started"}
                        trace.append(record)
                        try:
                            result = session.call(body["name"], body["arguments"])
                            record["status"] = (
                                "rejected"
                                if result.get("status") == "rejected"
                                else "completed"
                            )
                        except Exception as error:
                            result = parent_rejection_reply(error)
                            record["status"] = "rejected"
                else:
                    raise ValueError
                if (
                    not isinstance(result, dict)
                    or len(json.dumps(result, allow_nan=False).encode())
                    > MAX_CALLBACK_BYTES
                ):
                    raise ValueError
                self._send(200, result)
            except Exception:
                self._send(400, {"status": "rejected"})

    try:
        server = _CallbackServer((CALLBACK_HOST, CALLBACK_PORT), Handler)
    except OSError:
        raise ModelError(
            "Another isolated research request is already active."
        ) from None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield trace
    finally:
        closed.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _safe_result(value: dict, trace: list, *, report_retained=False) -> dict:
    from labcat.agent_connections import _safe_run_record

    allowed = {
        "runtime",
        "version",
        "status",
        "usage",
        "usage_scope",
        "account_quota",
        "tool_trace",
        "provider_internal_retries_possible",
        "refreshed_chatgpt_tokens",
        "worker_rejection_diagnostics",
        "stop_reason",
    }
    if (
        not isinstance(value, dict)
        or set(value) - allowed
        or value.get("runtime") != "goose"
        or value.get("version") != GOOSE_VERSION
        or not isinstance(value.get("status"), str)
        or value["status"] not in {"completed", "stopped_after_report"}
        or value.get("usage_scope") != "this_run"
        or value.get("account_quota") is not None
    ):
        raise ModelError(_SAFE_FAILURE)
    stopped = value["status"] == "stopped_after_report"
    if stopped:
        if (
            report_retained is not True
            or not any(
                row.get("tool") == "generate_ranked_report"
                and row.get("status") == "completed"
                for row in trace
            )
            or value.get("stop_reason") != "server_report_retained"
            or value.get("usage") is not None
        ):
            raise ModelError(_SAFE_FAILURE)
    elif "stop_reason" in value:
        raise ModelError(_SAFE_FAILURE)
    record = _safe_run_record(
        {
            "provider": "goose",
            "model": "metadata",
            "recorded_at": "this_run",
            "status": value["status"],
            "usage": value.get("usage"),
        }
    )
    if record is None:
        raise ModelError(_SAFE_FAILURE)
    diagnostics = _worker_diagnostics(value)
    return {
        "runtime": "goose",
        "version": GOOSE_VERSION,
        "status": value["status"],
        "usage": record["usage"],
        "usage_scope": "this_run",
        "account_quota": None,
        "tool_trace": [dict(item) for item in trace],
        "provider_internal_retries_possible": True,
        "isolation": "separate_container",
        **({"stop_reason": "server_report_retained"} if stopped else {}),
        **(
            {"worker_rejection_diagnostics": diagnostics}
            if diagnostics is not None
            else {}
        ),
        **(
            {"refreshed_chatgpt_tokens": value["refreshed_chatgpt_tokens"]}
            if value.get("refreshed_chatgpt_tokens") is not None
            else {}
        ),
    }


def _worker_diagnostics(value):
    from labcat.goose_runtime import safe_worker_rejection_diagnostics

    if "worker_rejection_diagnostics" not in value:
        return None
    try:
        return safe_worker_rejection_diagnostics(value["worker_rejection_diagnostics"])
    except (TypeError, ValueError):
        raise ModelError(_SAFE_FAILURE) from None


def run_remote_goose(
    profile, secret, prompt, *, context=None, tool_session, chatgpt_tokens=None
) -> dict:
    """Call one fixed worker once; never fall back to a process in the
    workspace."""
    from labcat.models import MAX_PROMPT_CHARS

    if not isinstance(prompt, str) or not 1 <= len(prompt) <= MAX_PROMPT_CHARS:
        raise ModelError("A text prompt of 1 to 20,000 characters is required.")
    if not remote_enabled():
        raise ModelError("Use the isolated Docker worker for Goose research.")
    from labcat.science import request_violation

    if request_violation(prompt):
        raise ModelError("This request cannot be sent to the research worker.")
    _channel_key()
    job_id, token = secrets.token_hex(16), secrets.token_hex(32)
    body = {
        "job_id": job_id,
        "callback_token": token,
        "profile": profile,
        "secret": secret,
        "prompt": prompt,
        "context": bounded_context(context),
        "chatgpt_tokens": chatgpt_tokens,
        "build_plan": tool_session.build_plan,
        "aws_credentials": (
            _aws_credentials(profile) if profile.get("provider") == "bedrock" else None
        ),
    }
    with _callbacks(tool_session, job_id, token) as trace:
        response = _worker_request("/run", body)
    if response.get("status") == "failed":
        if set(response) - {
            "status",
            "message",
            "refreshed_chatgpt_tokens",
            "failure_code",
            "worker_rejection_diagnostics",
        }:
            raise ModelError(_SAFE_FAILURE)
        code = response.get("failure_code", "worker_failed")
        if not isinstance(code, str) or code not in FAILURE_CODES:
            raise ModelError(_SAFE_FAILURE)
        raise GooseRuntimeError(
            _SAFE_FAILURE,
            response.get("refreshed_chatgpt_tokens"),
            failure_code=code,
            worker_rejection_diagnostics=_worker_diagnostics(response),
        )
    if set(response) != {"status", "result"} or response["status"] != "completed":
        raise ModelError(_SAFE_FAILURE)
    if (
        isinstance(response["result"], dict)
        and response["result"].get("refreshed_chatgpt_tokens") is not None
        and chatgpt_tokens is None
    ):
        raise ModelError(_SAFE_FAILURE)
    return _safe_result(
        response["result"],
        trace,
        report_retained=getattr(tool_session, "report_retained", False) is True,
    )
