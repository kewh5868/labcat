"""Persistent setup progress and short-lived, credential-bound
readiness.

The progress file contains no credentials and cannot authorize model
use. A successful provider metadata check is held only in this process
and expires.
"""

import hashlib
import json
import time
from datetime import UTC, datetime

from labcat.credentials import (
    ConnectionBusy,
    ConnectionError,
    atomic_write,
    read_private_file,
    unique_json_object,
)
from labcat.provider_catalog import API_KEY_PROVIDERS

STEPS = {"model", "compute", "sources", "review"}
AUTHENTICATED_PROVIDERS = {"chatgpt", *API_KEY_PROVIDERS, "bedrock"}
READINESS_SECONDS = 300


class SetupRequired(ConnectionError):
    """Research needs a selected, verified language-model connection."""


class SetupState:
    def __init__(self, manager, workspace_path):
        self.manager = manager
        self.path = workspace_path.with_suffix(".setup.json")
        self.progress = {"version": 1, "completed": False, "current_step": "model"}
        self._verified = None
        self._error = None
        try:
            document = json.loads(
                read_private_file(self.path, 4096),
                object_pairs_hook=unique_json_object,
            )
            if (
                not isinstance(document, dict)
                or set(document) != set(self.progress)
                or type(document["version"]) is not int
                or document["version"] != 1
                or type(document["completed"]) is not bool
                or document["current_step"] not in STEPS
            ):
                raise ValueError
            self.progress = document
        except (ConnectionError, OSError, ValueError, TypeError, RecursionError):
            # Damaged or absent progress never confers account readiness.
            pass

    def _connection(self):
        status = self.manager.status()
        profile = status["profile"]
        provider = profile["provider"]
        identifier = status["active_account_id"]
        account = next((a for a in status["accounts"] if a["id"] == identifier), None)
        credential_state = (
            account["credential_state"]
            if account
            else status["credentials"].get(provider, "missing")
        )
        slot = (
            "oauth_" + identifier
            if provider == "chatgpt" and identifier
            else self.manager._model_slot(provider)
        )
        secret = (
            self.manager.vault.get(slot)
            if provider in API_KEY_PROVIDERS or provider == "chatgpt" and identifier
            else None
        )
        expiration = None
        if provider == "chatgpt" and secret:
            from labcat.agent_connections import _unpack
            from labcat.chatgpt_auth import goose_token_cache

            try:
                expiration = datetime.fromisoformat(
                    goose_token_cache(_unpack(secret))["expires_at"]
                ).timestamp()
            except (ConnectionError, ValueError, TypeError):
                expiration = 0
        fingerprint = hashlib.sha256(
            json.dumps(
                [profile, identifier, credential_state, secret], sort_keys=True
            ).encode()
        ).hexdigest()
        model = {
            "status": "verification_required",
            "provider": provider,
            "model": profile["model"],
            "account_id": identifier,
            "message": "Verify this account and selected model to continue.",
            "checked_at": None,
        }
        if provider not in AUTHENTICATED_PROVIDERS:
            model.update(
                status="not_connected",
                message="Connect a language-model account before starting research.",
            )
        elif credential_state == "locked":
            model.update(
                status="credentials_locked",
                message="Unlock your saved credentials to reconnect the model.",
            )
        elif provider != "bedrock" and not secret:
            model.update(
                status="not_connected",
                message="Sign in or add the selected provider's API credential.",
            )
        elif not profile["model"]:
            model.update(
                status="model_required", message="Choose a model for this connection."
            )
        elif not profile["allow_paid_inference"]:
            model.update(
                status="consent_required",
                message="Allow this provider to receive research context first.",
            )
        elif provider == "chatgpt" and not self.manager.agent.uses_goose:
            model.update(
                status="error",
                message="Use the Docker application for ChatGPT account connections.",
            )
        return model, fingerprint, expiration

    def status(self):
        with self.manager._lock:
            model, fingerprint, expiration = self._connection()
            if model["status"] == "verification_required":
                if (
                    self._verified
                    and self._verified["fingerprint"] == fingerprint
                    and time.monotonic() < self._verified["expires"]
                    and (expiration is None or expiration > time.time())
                ):
                    model.update(
                        status="ready",
                        message="Account and model verified. No inference was run.",
                        checked_at=self._verified["checked_at"],
                    )
                elif self._error and self._error[0] == fingerprint:
                    model.update(status="error", message=self._error[1])
            return {
                **self.progress,
                "required": True,
                "can_research": model["status"] == "ready",
                "model": model,
                "optional": {
                    "compute": (
                        "aws_bedrock" if model["provider"] == "bedrock" else "local"
                    ),
                    "aws_required": False,
                    "data_apis_required": False,
                },
            }

    def save_progress(self, request):
        if (
            not isinstance(request, dict)
            or set(request) != {"current_step"}
            or not isinstance(request["current_step"], str)
            or request["current_step"] not in STEPS
        ):
            raise ConnectionError("Choose a supported setup step.")
        with self.manager._lock:
            progress = {**self.progress, "current_step": request["current_step"]}
            atomic_write(self.path, progress)
            self.progress = progress
            return self.status()

    def invalidate(self, message=None):
        with self.manager._lock:
            self._verified = None
            self._error = None
            if message:
                _, fingerprint, _ = self._connection()
                self._error = (fingerprint, message)

    def verify(self):
        # Match the authentication lock order, preventing a concurrent account
        # edit or token replacement from inheriting another credential's check.
        if not self.manager.agent._auth_lock.acquire(blocking=False):
            raise ConnectionBusy("A model connection operation is already in progress.")
        try:
            with self.manager._lock:
                model, _, _ = self._connection()
                self.invalidate()
                if model["status"] != "verification_required":
                    return self.status()
                result = self.manager.test("model")
                _, fingerprint, expiration = self._connection()
                if result["status"] == "ok" and (
                    expiration is None or expiration > time.time()
                ):
                    self._verified = {
                        "fingerprint": fingerprint,
                        "expires": time.monotonic() + READINESS_SECONDS,
                        "checked_at": datetime.now(UTC).isoformat(),
                    }
                else:
                    self._error = (
                        fingerprint,
                        (
                            "The saved sign-in has expired. Reconnect this account."
                            if result["status"] == "ok"
                            else result["message"]
                        ),
                    )
                return self.status()
        finally:
            self.manager.agent._auth_lock.release()

    def require_ready(self):
        state = self.status()
        if not state["can_research"] and state["model"]["status"] in {
            "verification_required",
            "error",
        }:
            state = self.verify()
        if not state["can_research"]:
            raise SetupRequired(state["model"]["message"])
        return state

    def complete(self):
        state = self.verify()
        if not state["can_research"]:
            raise SetupRequired(state["model"]["message"])
        with self.manager._lock:
            # Verification is credential-bound; a changed account cannot finish
            # setup by racing a successful response for the previous account.
            if not self.status()["can_research"]:
                raise SetupRequired("The connection changed. Verify it again.")
            progress = {"version": 1, "completed": True, "current_step": "review"}
            atomic_write(self.path, progress)
            self.progress = progress
            return self.status()
