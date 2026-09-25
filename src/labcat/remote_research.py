"""Headless research through the existing local service and its
connection vault.

The container launcher executes this client inside the application
container. There are no configurable destinations, proxies, credentials
or redirect handling.
"""

import http.client
import json
import re
from http.cookies import CookieError, SimpleCookie

MAX_RESPONSE_BYTES = 4_000_000


class ServerResearchError(ValueError):
    """A local server request failed without exposing response or
    account data."""


def _request(method, path, *, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=180)
    try:
        connection.request(
            method,
            path,
            body=body,
            headers={"Accept": "application/json", **(headers or {})},
        )
        response = connection.getresponse()
        if response.status == 409:
            raise ServerResearchError(
                "Connect and verify a model account in application setup first. "
                "Unlock saved credentials after restarting the application."
            )
        if response.status in {502, 504}:
            raise ServerResearchError(
                "The research model request failed. Check the connection and "
                "available quota in the application before trying again. "
                "No automatic retry was made."
            )
        if response.status != 200:
            raise ServerResearchError(
                "The local research request was not completed. Check the prompt, "
                "ranking profile and application connection settings."
            )
        if (
            response.getheader("Content-Type", "").split(";", 1)[0]
            != "application/json"
            or response.getheader("Content-Encoding", "identity") != "identity"
        ):
            raise ServerResearchError("The local service returned an invalid response.")
        length = response.getheader("Content-Length")
        if length and (not length.isdigit() or int(length) > MAX_RESPONSE_BYTES):
            raise ServerResearchError("The local report exceeded its response limit.")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ServerResearchError("The local report exceeded its response limit.")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ServerResearchError("The local service returned an invalid response.")
        return result, response.getheader("Set-Cookie", "")
    except ServerResearchError:
        raise
    except (OSError, http.client.HTTPException, UnicodeError, ValueError):
        raise ServerResearchError(
            "The local research service is unavailable. Start Labcat, complete "
            "model setup, then retry. The request was not automatically retried."
        ) from None
    finally:
        connection.close()


def run_server_research(prompt: str, ranking_profile_id: str | None = None) -> dict:
    """Submit one stateless run; the server owns criteria, sources and
    credentials."""
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 20000:
        raise ServerResearchError("Enter a research prompt of up to 20,000 characters.")
    if ranking_profile_id is not None and not re.fullmatch(
        r"[A-Za-z0-9_-]{1,64}", ranking_profile_id
    ):
        raise ServerResearchError("Choose a saved ranking profile identifier.")
    session, cookie_header = _request("GET", "/api/session")
    token = session.get("csrf_token")
    try:
        cookie = SimpleCookie(cookie_header)
        cookie_token = cookie["labcat_session"].value
    except (CookieError, KeyError):
        raise ServerResearchError(
            "The local application session was unavailable."
        ) from None
    if (
        not isinstance(token, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token)
        or cookie_token != token
    ):
        raise ServerResearchError("The local application session was unavailable.")
    payload = {"prompt": prompt, "ranking_profile_id": ranking_profile_id or "infer"}
    outcome, _ = _request(
        "POST",
        "/api/research",
        body=json.dumps(payload, allow_nan=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-CSRF-Token": token,
            "Cookie": f"labcat_session={token}",
        },
    )
    if not all(
        isinstance(outcome.get(field), str)
        for field in ("pi_summary", "technical_audit")
    ):
        raise ServerResearchError("The local service returned an invalid report.")
    return outcome
