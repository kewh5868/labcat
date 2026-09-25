"""Goose service for a separate container with no workspace or host
mounts.

This uses the same image as the app. Only a read-only, memory-backed
channel key is shared. Parent-owned public research tools are reached at
one fixed private service address with a per-job capability. Neither
service publishes these ports.
"""

import hmac
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from labcat.agent_rejections import WorkerRejectionError
from labcat.credentials import (
    ConnectionError,
    read_private_file,
    unique_json_object,
)
from labcat.goose_runtime import (
    FAILURE_CODES,
    MAX_TOOL_CALLS,
    RESEARCH_TOOLS,
    ModelError,
    run_goose,
    runtime_status,
)

CHANNEL_KEY = Path("/run/labcat-channel/key")
WORKER_PORT = 8765
CALLBACK_ORIGIN = "http://labcat:8766"
MAX_REQUEST = 128_000
MAX_RESPONSE = 64_000
_JOB_KEYS = {
    "job_id",
    "callback_token",
    "profile",
    "secret",
    "prompt",
    "context",
    "chatgpt_tokens",
    "build_plan",
    "aws_credentials",
}


class WorkerError(WorkerRejectionError):
    """Fixed failure safe for the parent service to display."""

    def __init__(self, message, *, reason_code=None):
        super().__init__(message)
        self.reason_code = reason_code


def _evaluation_rejection_reason(arguments):
    """Categorize an already rejected batch without retaining its
    contents."""
    from labcat.science.literature_evaluation import (
        MAX_EVALUATION_ARGUMENT_BYTES,
        MAX_EVALUATIONS,
    )

    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"evaluations"}
        or not isinstance(arguments["evaluations"], list)
        or len(arguments["evaluations"]) > MAX_EVALUATIONS
    ):
        return "evaluation_envelope"
    try:
        if (
            len(json.dumps(arguments, allow_nan=False).encode())
            > MAX_EVALUATION_ARGUMENT_BYTES
        ):
            return "evaluation_payload_size"
    except (TypeError, ValueError, RecursionError):
        return "evaluation_envelope"
    for row in arguments["evaluations"]:
        if not isinstance(row, dict):
            return "evaluation_envelope"
        quote, interpretation = row.get("quote"), row.get("interpretation")
        if not isinstance(quote, str) or not 12 <= len(quote) <= 480:
            return "evaluation_quote_length"
        if (
            not isinstance(interpretation, str)
            or not 1 <= len(interpretation) <= 200
            or any(c.isnumeric() or c in "<>{}`$" for c in interpretation)
            or re.search(
                r"https?://|www\.|\bdoi:|[a-z][a-z0-9+.-]*://", interpretation, re.I
            )
        ):
            return "evaluation_interpretation_format"
    return "invalid_arguments"


def _key():
    try:
        key = read_private_file(CHANNEL_KEY, 128).decode("ascii").strip()
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError
        return key
    except (OSError, ValueError, ConnectionError):
        raise WorkerError("The private agent channel is not ready.") from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WorkerError("The private agent channel cannot redirect.")


def _validate_aws(profile, value):
    if profile["provider"] != "bedrock":
        if value is not None:
            raise WorkerError("AWS credentials require the selected AWS provider.")
        return
    required = {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_EC2_METADATA_DISABLED",
        "BEDROCK_MAX_RETRIES",
    }
    if (
        not isinstance(value, dict)
        or set(value) not in (required, required | {"AWS_SESSION_TOKEN"})
        or any(
            not isinstance(item, str) or not 1 <= len(item) <= 20000
            for item in value.values()
        )
        or value["AWS_REGION"] != profile["aws_region"]
        or value["AWS_DEFAULT_REGION"] != profile["aws_region"]
        or value["AWS_EC2_METADATA_DISABLED"] != "true"
        or value["BEDROCK_MAX_RETRIES"] != "0"
    ):
        raise WorkerError("The selected AWS session is invalid.")


def _validate_job(value):
    from labcat.connections import validate_profile
    from labcat.models import MAX_PROMPT_CHARS

    if not isinstance(value, dict) or set(value) != _JOB_KEYS:
        raise WorkerError("The agent request shape is invalid.")
    for key, pattern in (
        ("job_id", r"[a-f0-9]{32}"),
        ("callback_token", r"[a-f0-9]{64}"),
    ):
        if not isinstance(value[key], str) or not re.fullmatch(pattern, value[key]):
            raise WorkerError("The agent request identity is invalid.")
    profile = validate_profile(value["profile"])
    if profile["provider"] == "none":
        raise WorkerError("Local defaults do not invoke the model worker.")
    if (
        not isinstance(value["prompt"], str)
        or not 1 <= len(value["prompt"]) <= MAX_PROMPT_CHARS
    ):
        raise WorkerError("The agent prompt is invalid.")
    if value["context"] is not None and not isinstance(value["context"], dict):
        raise WorkerError("The agent context is invalid.")
    if not isinstance(value["build_plan"], dict):
        raise WorkerError("The server Build Plan is invalid.")
    if value["secret"] is not None and (
        not isinstance(value["secret"], str) or len(value["secret"]) > 8192
    ):
        raise WorkerError("The selected credential is invalid.")
    if profile["provider"] == "chatgpt":
        tokens = value["chatgpt_tokens"]
        if not isinstance(tokens, dict) or set(tokens) != {
            "access_token",
            "refresh_token",
            "id_token",
            "account_id",
            "expires_at",
        }:
            raise WorkerError("The ChatGPT connection is invalid.")
    elif value["chatgpt_tokens"] is not None:
        raise WorkerError("ChatGPT credentials require the selected provider.")
    _validate_aws(profile, value["aws_credentials"])
    return {**value, "profile": profile}


class _RemoteTools:
    def __init__(self, job):
        self.job_id = job["job_id"]
        self.token = job["callback_token"]
        self.build_plan = job["build_plan"]
        self._rejections = {}

    @property
    def rejection_diagnostics(self):
        return {
            "scope": "worker_reported",
            "rejections": [
                {"tool": name, "reason": reason, "count": count}
                for (name, reason), count in sorted(self._rejections.items())
            ],
        }

    def _post(self, route, body):
        request = Request(
            f"{CALLBACK_ORIGIN}/{self.job_id}/{route}",
            data=json.dumps(body, allow_nan=False).encode(),
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with build_opener(ProxyHandler({}), _NoRedirect()).open(
                request, timeout=65
            ) as response:
                raw = response.read(32_001)
            if len(raw) > 32_000:
                raise ValueError
            result = json.loads(raw, object_pairs_hook=unique_json_object)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except Exception:
            raise WorkerError("The configured research tool is unavailable.") from None

    def tool_definitions(self):
        from labcat.agent_tools import ResearchToolSession

        value = self._post("tools/list", {})
        expected = ResearchToolSession.tool_definitions()
        if value != {"tools": expected}:
            raise WorkerError("The research tool catalog is invalid.")
        return expected

    def call(self, name, arguments):
        from labcat.agent_tools import (
            valid_lead_arguments,
            valid_search_arguments,
        )
        from labcat.research_intent import valid_assessment_arguments
        from labcat.science.literature_evaluation import (
            valid_evaluation_transport_arguments,
        )

        assessment = name == "assess_research_intent" and valid_assessment_arguments(
            arguments
        )
        research_stage = name == "generate_ranked_report" and arguments == {}
        search = name == "search_public_references" and valid_search_arguments(
            arguments
        )
        leads = name == "propose_candidate_leads" and valid_lead_arguments(arguments)
        evaluation = (
            name == "evaluate_candidate_fit"
            and valid_evaluation_transport_arguments(arguments)
        )
        if not (assessment or research_stage or leads or search or evaluation):
            reason = (
                _evaluation_rejection_reason(arguments)
                if name == "evaluate_candidate_fit"
                else "invalid_arguments"
            )
            if (
                isinstance(name, str)
                and name in RESEARCH_TOOLS
                and sum(self._rejections.values()) < MAX_TOOL_CALLS
            ):
                key = (name, reason)
                self._rejections[key] = self._rejections.get(key, 0) + 1
            raise WorkerError(
                "Only configured public research stages may run.", reason_code=reason
            )
        return self._post("tools/call", {"name": name, "arguments": arguments})


def _run(job):
    remote = _RemoteTools(job)
    try:
        result = run_goose(
            job["profile"],
            job["secret"],
            job["prompt"],
            context=job["context"],
            tool_session=remote,
            chatgpt_tokens=job["chatgpt_tokens"],
            aws_credentials=job["aws_credentials"],
        )
        if remote.rejection_diagnostics["rejections"]:
            result["worker_rejection_diagnostics"] = remote.rejection_diagnostics
        return {"status": "completed", "result": result}
    except (ModelError, WorkerError) as error:
        code = getattr(error, "failure_code", "worker_failed")
        return {
            "status": "failed",
            "message": "The isolated model worker could not finish the request.",
            "failure_code": (
                code
                if isinstance(code, str) and code in FAILURE_CODES
                else "worker_failed"
            ),
            "refreshed_chatgpt_tokens": getattr(
                error, "refreshed_chatgpt_tokens", None
            ),
            **(
                {"worker_rejection_diagnostics": remote.rejection_diagnostics}
                if remote.rejection_diagnostics["rejections"]
                else {}
            ),
        }


def make_server():
    from labcat.goose_browser_auth import GooseBrowserAuthBroker

    active = threading.Lock()
    auth = GooseBrowserAuthBroker()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def _authenticated(self):
            try:
                return (
                    "Origin" not in self.headers
                    and len(self.headers.get_all("Authorization", [])) == 1
                    and hmac.compare_digest(
                        self.headers.get("Authorization", ""), "Bearer " + _key()
                    )
                )
            except WorkerError:
                return False

        def _send(self, status, value):
            raw = json.dumps(value, allow_nan=False).encode()
            if len(raw) > MAX_RESPONSE:
                status, raw = 500, b'{"status":"failed"}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(raw)
            except OSError:
                pass

        def do_GET(self):
            if not self._authenticated():
                self._send(403, {"status": "unavailable"})
            elif self.path != "/status":
                self._send(404, {"status": "unavailable"})
            else:
                self._send(
                    200,
                    {
                        **runtime_status(),
                        "isolation": "separate_container",
                        "busy": active.locked(),
                    },
                )

        def do_POST(self):
            if not self._authenticated():
                self._send(403, {"status": "unavailable"})
                return
            if self.path in {
                "/auth/start",
                "/auth/poll",
                "/auth/cancel",
                "/auth/take",
                "/auth/callback",
            }:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 12_000 or self.headers.get(
                        "Transfer-Encoding"
                    ):
                        raise ValueError
                    body = json.loads(
                        self.rfile.read(length), object_pairs_hook=unique_json_object
                    )
                    if not isinstance(body, dict):
                        raise ValueError
                    if self.path == "/auth/start" and body == {}:
                        value = auth.start()
                    elif self.path == "/auth/callback" and set(body) == {"path"}:
                        code, _html = auth.relay_callback(body["path"])
                        value = {"callback_status": code}
                    elif (
                        set(body) == {"flow_id"}
                        and isinstance(body["flow_id"], str)
                        and re.fullmatch(r"[a-f0-9]{32}", body["flow_id"])
                    ):
                        if self.path == "/auth/poll":
                            value = auth.poll(body["flow_id"])
                        elif self.path == "/auth/cancel":
                            value = auth.cancel(body["flow_id"])
                        elif self.path == "/auth/take":
                            value = {
                                "credentials": auth.take_credentials(body["flow_id"])
                            }
                        else:
                            raise ValueError
                    else:
                        raise ValueError
                    self._send(200, value)
                except Exception:
                    self._send(400, {"status": "failed"})
                return
            if self.path != "/run":
                self._send(404, {"status": "unavailable"})
                return
            if not active.acquire(blocking=False):
                self._send(409, {"status": "busy"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_REQUEST or self.headers.get(
                    "Transfer-Encoding"
                ):
                    raise WorkerError("Invalid request length.")
                job = _validate_job(
                    json.loads(
                        self.rfile.read(length), object_pairs_hook=unique_json_object
                    )
                )
                self._send(200, _run(job))
            except Exception:
                # Never serialize upstream exceptions, requests, or credentials.
                self._send(
                    400,
                    {"status": "failed", "message": "The agent request was rejected."},
                )
            finally:
                active.release()

    server = ThreadingHTTPServer(("0.0.0.0", WORKER_PORT), Handler)
    server.daemon_threads = True
    server.auth_broker = auth
    return server


def main():
    import sys

    if sys.argv[1:] == ["--health"]:
        request = Request(
            f"http://127.0.0.1:{WORKER_PORT}/status",
            headers={"Authorization": "Bearer " + _key()},
        )
        with build_opener(ProxyHandler({}), _NoRedirect()).open(
            request, timeout=3
        ) as response:
            if response.status != 200:
                raise SystemExit(1)
        return
    if sys.argv[1:]:
        raise SystemExit(2)
    os.umask(0o077)
    server = make_server()
    try:
        server.serve_forever()
    finally:
        server.auth_broker.close()
        server.server_close()


if __name__ == "__main__":
    main()
