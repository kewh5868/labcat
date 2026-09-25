"""Browser login through the isolated worker and a callback-only
loopback port.

The workspace process does not launch Goose. Only a freshly completed
worker flow can return credentials, over the existing private
authenticated channel. The public callback listener returns fixed text
and never echoes OAuth queries.
"""

import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from labcat.chatgpt_auth import (
    ChatGPTAuthBroker,
    ChatGPTAuthError,
    ChatGPTSetupError,
    validate_auth_document,
)
from labcat.goose_browser_auth import validate_authorize_url
from labcat.goose_worker_client import _worker_request, remote_enabled

CALLBACK_PORT = 1456
FLOW_FIELDS = {"flow_id", "status", "method", "verification_url", "user_code"}


def browser_login_enabled():
    return remote_enabled() and os.environ.get("LABCAT_GOOSE_BROWSER_AUTH") == "1"


def _request(path, body):
    try:
        result = _worker_request(path, body)
        if not isinstance(result, dict) or result.get("status") == "failed":
            raise ValueError
        return result
    except Exception:
        raise ChatGPTAuthError(
            "Goose browser sign-in could not be completed. Start sign-in again."
        ) from None


def _flow(value, expected_id=None):
    if (
        not isinstance(value, dict)
        or set(value) != FLOW_FIELDS
        or value.get("method") != "browser"
        or value.get("user_code") is not None
        or not isinstance(value.get("flow_id"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", value["flow_id"])
        or (expected_id is not None and value["flow_id"] != expected_id)
    ):
        raise ChatGPTAuthError("The Goose sign-in response was unavailable.")
    if not isinstance(value.get("status"), str) or value["status"] not in {
        "pending",
        "complete",
        "cancelled",
        "expired",
        "error",
        "consumed",
    }:
        raise ChatGPTAuthError("The Goose sign-in response was unavailable.")
    validate_authorize_url(value.get("verification_url"))
    return value


class WorkerChatGPTAuthBroker:
    def __init__(self):
        # This helper only reads account/model metadata after Goose login. Its
        # implementation accepts no research or agent-tool requests.
        self.metadata_reader = ChatGPTAuthBroker()
        self.flow_id = None

    def start(self):
        if os.environ.get("LABCAT_OAUTH_CALLBACK_PORT", "1455") != "1455":
            raise ChatGPTSetupError("chatgpt_callback_unavailable")
        flow = _flow(_request("/auth/start", {}))
        self.flow_id = flow["flow_id"]
        return flow

    def poll(self, flow_id):
        return _flow(_request("/auth/poll", {"flow_id": flow_id}), flow_id)

    def cancel(self, flow_id):
        return _flow(_request("/auth/cancel", {"flow_id": flow_id}), flow_id)

    def take_credentials(self, flow_id):
        value = _request("/auth/take", {"flow_id": flow_id})
        if set(value) != {"credentials"}:
            raise ChatGPTAuthError("Completed sign-in credentials are unavailable.")
        return validate_auth_document(value["credentials"])

    def metadata(self, document):
        return self.metadata_reader.metadata(document)

    def close(self):
        if self.flow_id:
            try:
                self.cancel(self.flow_id)
            except ChatGPTAuthError:
                pass
        self.metadata_reader.close()


class CallbackHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        pass

    def do_GET(self):
        status = 400
        try:
            if self.headers.get_all("Host", []) not in (
                ["localhost:1455"],
                ["127.0.0.1:1455"],
            ):
                raise PermissionError
            parsed = urlsplit(self.path)
            if (
                len(self.path) > 8192
                or any(ord(char) <= 32 or ord(char) >= 127 for char in self.path)
                or parsed.scheme
                or parsed.netloc
                or parsed.fragment
                or parsed.path != "/auth/callback"
            ):
                raise ValueError
            result = _request("/auth/callback", {"path": self.path})
            code = result.get("callback_status")
            if type(code) is int and code in {200, 400, 403, 409, 502, 503}:
                status = code
        except ValueError:
            status = 400
        except PermissionError:
            status = 403
        except Exception:
            status = 503
        message = (
            "Sign-in received. Return to Labcat while Goose finishes connecting. "
            "You can close this tab."
            if status == 200
            else "Sign-in could not be received. Return to Labcat and start again."
        )
        raw = (
            "<!doctype html><meta charset=utf-8><title>Labcat sign-in</title>"
            "<h1>ChatGPT connection</h1><p>" + message + "</p>"
        ).encode()
        self.send_response(status)
        for name, value in {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": str(len(raw)),
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        }.items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(raw)
        except OSError:
            pass


def start_callback_relay():
    if not browser_login_enabled():
        return None
    server = ThreadingHTTPServer(("0.0.0.0", CALLBACK_PORT), CallbackHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
