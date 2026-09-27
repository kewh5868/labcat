"""Account-bound Goose execution and provider-owned ChatGPT
authentication.

No OAuth credential is returned by this module's public methods. The
only persistent secret representation is the application's authenticated
vault.
"""

import base64
import hashlib
import json
import math
import os
import threading
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from labcat.credentials import (
    ConnectionBusy,
    ConnectionError,
    atomic_write,
    read_private_file,
    unique_json_object,
)
from labcat.models import ModelError
from labcat.provider_catalog import API_KEY_PROVIDERS


def _safe_run_record(value):
    if not isinstance(value, dict):
        return None
    if any(
        not isinstance(value.get(key), str)
        or not 1 <= len(value[key]) <= 200
        or any(ord(c) < 32 for c in value[key])
        for key in ("provider", "model", "recorded_at", "status")
    ):
        return None
    usage = value.get("usage")
    if usage is not None:
        if not isinstance(usage, dict):
            return None
        filtered = {}
        for key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cache_read_input_tokens",
            "cache_write_input_tokens",
            "cost_usd",
        ):
            number = usage.get(key)
            if number is not None and (
                type(number) not in (int, float)
                or not math.isfinite(number)
                or not 0 <= number <= 10**12
            ):
                return None
            filtered[key] = number
        usage = filtered
    return {
        **{key: value[key] for key in ("provider", "model", "recorded_at", "status")},
        "usage": usage,
    }


def _pack(value):
    raw = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
    encoded = base64.urlsafe_b64encode(raw).decode()
    if len(encoded) > 32768:
        raise ConnectionError("The sign-in response exceeded its credential limit.")
    return encoded


def _unpack(value):
    try:
        from labcat.chatgpt_auth import validate_auth_document

        return validate_auth_document(
            json.loads(
                base64.b64decode(value, altchars=b"-_", validate=True),
                object_pairs_hook=unique_json_object,
            )
        )
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ConnectionError("Saved ChatGPT credentials need a new sign-in.") from None


class AgentConnections:
    def __init__(self, manager, workspace_path: Path):
        from labcat.goose_worker_client import initialize_channel

        initialize_channel()
        self.manager = manager
        self.usage_path = workspace_path.with_suffix(".agent-usage.json")
        self._auth = None
        self._flows = {}
        self._auth_lock = threading.RLock()
        self._auth_epoch = 0
        self._run_lock = threading.Lock()
        self._running_oauth_account = None
        self._credential_revisions = {}
        self._claude_sessions = {}
        self._claude_revisions = {}
        self._claude_locks = {}
        self._model_metadata = {}

    @property
    def uses_goose(self):
        return os.environ.get("LABCAT_AGENT_ENGINE", "direct") == "goose"

    def runtime_status(self):
        from labcat.goose_worker_client import runtime_status

        value = runtime_status()
        return {
            "engine": "goose" if self.uses_goose else "direct",
            "available": value["available"] if self.uses_goose else True,
            "version": value["version"],
            "tools": [
                "search_public_references",
                "propose_candidate_leads",
                "generate_ranked_report",
            ],
            "message": (
                "Goose can call only the configured public-source and ranking stages."
                if self.uses_goose
                else "This Python installation uses bounded model planning. "
                "The Docker application includes Goose."
            ),
        }

    def _broker(self):
        if self._auth is None:
            from labcat.chatgpt_auth import ChatGPTAuthBroker
            from labcat.goose_login_client import (
                WorkerChatGPTAuthBroker,
                browser_login_enabled,
            )

            self._auth = (
                WorkerChatGPTAuthBroker()
                if browser_login_enabled()
                else ChatGPTAuthBroker()
            )
        return self._auth

    def _account(self, identifier):
        account = next(
            (a for a in self.manager._accounts if a["id"] == identifier), None
        )
        if account is None or account["profile"]["provider"] != "chatgpt":
            raise ConnectionError("Choose a saved ChatGPT connection first.")
        return account

    def start_login(self, identifier, request):
        if not isinstance(request, dict) or set(request) != {"secret_storage"}:
            raise ConnectionError("Choose sign-in credential storage.")
        storage = request["secret_storage"]
        if not isinstance(storage, str) or storage not in {"session", "encrypted"}:
            raise ConnectionError("Choose session or encrypted credential storage.")
        with self._auth_lock:
            with self.manager._lock:
                self._account(identifier)
                if (
                    storage == "encrypted"
                    and not self.manager.vault.status()["available"]
                ):
                    raise ConnectionError(
                        "Unlock the credential vault before signing in."
                    )
                epoch = self._auth_epoch
            self._flows = {
                key: flow for key, flow in self._flows.items() if not flow["completed"]
            }
            for flow_id, pending in tuple(self._flows.items()):
                if pending["account_id"] != identifier or pending["storage"] != storage:
                    # An explicit account/storage choice replaces only the old
                    # challenge. Saved credentials remain bound to their account.
                    self.login_action(pending["account_id"], flow_id, "cancel")
                    continue
                # A remounted UI or interrupted start response can rediscover its
                # challenge without creating another provider login. Poll through
                # the normal path so completed credentials are saved exactly once.
                current = self.login_action(identifier, flow_id, "poll")
                if current["status"] in {"pending", "complete"}:
                    return current
                # Terminal broker states remove stale manager entries in
                # login_action, allowing recovery after the provider deadline.
            flow = self._broker().start()
            with self.manager._lock:
                if epoch != self._auth_epoch:
                    self._broker().cancel(flow["flow_id"])
                    raise ConnectionError(
                        "Credential storage changed. Start sign-in again."
                    )
                self._flows[flow["flow_id"]] = {
                    "account_id": identifier,
                    "storage": storage,
                    "completed": False,
                    "epoch": epoch,
                }
            return flow

    def login_action(self, identifier, flow_id, action):
        if action not in {"poll", "cancel"}:
            raise ConnectionError("Choose a supported sign-in action.")
        with self._auth_lock:
            flow = self._flows.get(flow_id)
            if not flow or flow["account_id"] != identifier:
                raise ConnectionError("This sign-in is unavailable for that account.")
            if flow["completed"]:
                return {"flow_id": flow_id, "status": "complete"}
            if action == "cancel":
                self._broker().cancel(flow_id)
                del self._flows[flow_id]
                return {"flow_id": flow_id, "status": "cancelled"}
            value = self._broker().poll(flow_id)
            if value["status"] == "complete":
                auth = self._broker().take_credentials(flow_id)
                try:
                    with self.manager._lock:
                        if flow["epoch"] != self._auth_epoch:
                            raise ConnectionError(
                                "Credential storage changed. Start sign-in again."
                            )
                        self._account(identifier)
                        self.manager.vault.update(
                            {"oauth_" + identifier: _pack(auth)}, [], flow["storage"]
                        )
                        self._credential_revisions[identifier] = (
                            self._credential_revisions.get(identifier, 0) + 1
                        )
                        if self.manager._active_account_id == identifier:
                            self.manager.setup.invalidate()
                    # A repeated poll never repeats a sign-in or secret write.
                    flow["completed"] = True
                except ConnectionError:
                    self._flows.pop(flow_id, None)
                    raise
            elif value["status"] in {"error", "expired", "cancelled"}:
                del self._flows[flow_id]
            return value

    def cancel_pending(self):
        # Called while the manager lock is held; avoid an inverted lock order.
        # Broker cancellation removes temporary credentials even if a poll raced.
        self._auth_epoch += 1
        self._model_metadata.clear()
        if self._auth:
            for identifier in tuple(self._flows):
                self._auth.cancel(identifier)
        self._flows.clear()

    def close(self):
        self.cancel_pending()
        if self._auth:
            self._auth.close()

    def forget_login(self, identifier):
        with self._auth_lock, self.manager._lock:
            self._account(identifier)
            for flow_id, flow in tuple(self._flows.items()):
                if flow["account_id"] == identifier:
                    self._broker().cancel(flow_id)
                    del self._flows[flow_id]
            slot = "oauth_" + identifier
            if self.manager.vault.status()["locked"]:
                # End this session without requiring access to the optional vault.
                # The returned locked state still advertises the retained login.
                self.manager.vault.forget_session(slot)
            else:
                self.manager.vault.update({}, [slot], "session")
            self._credential_revisions[identifier] = (
                self._credential_revisions.get(identifier, 0) + 1
            )
            if self.manager._active_account_id == identifier:
                self.manager.setup.invalidate()
            return self.manager.status()

    def _credential_snapshot(self, identifier):
        with self.manager._lock:
            self._account(identifier)
            slot = "oauth_" + identifier
            packed = self.manager.vault.get(slot)
            if not packed:
                raise ConnectionError(
                    "Sign in to ChatGPT or unlock its saved credentials."
                )
            return _unpack(packed), packed, self.manager.vault.slots()[slot]

    def _credential_revision(self, identifier):
        return self._auth_epoch, self._credential_revisions.get(identifier, 0)

    def require_account_available(self, identifier):
        with self.manager._lock:
            if identifier is not None and identifier == self._running_oauth_account:
                raise ConnectionBusy(
                    "This account is in use by research. Choose another account "
                    "or wait for that research to finish."
                )

    def _save_refreshed(
        self,
        identifier,
        old,
        document,
        storage,
        *,
        revision=None,
        ignore_superseded=False,
    ):
        with self.manager._lock:
            slot = "oauth_" + identifier
            # A concurrent sign-out, lock or new sign-in wins over this response.
            if self.manager.vault.get(slot) != old or (
                revision is not None
                and revision != self._credential_revision(identifier)
            ):
                if ignore_superseded:
                    return
                raise ConnectionError(
                    "The account changed during this request. Reload it."
                )
            self.manager.vault.update({slot: _pack(document)}, [], storage)

    def metadata(self, identifier, *, include_usage=True):
        from labcat.chatgpt_auth import METADATA_TIMEOUT_SECONDS, goose_token_cache

        deadline = time.monotonic() + METADATA_TIMEOUT_SECONDS
        if not self._auth_lock.acquire(timeout=METADATA_TIMEOUT_SECONDS):
            raise ConnectionBusy("A model connection operation is already in progress.")
        try:
            with self.manager._lock:
                self.require_account_available(identifier)
                document, old, storage = self._credential_snapshot(identifier)
                revision = self._credential_revision(identifier)
                fingerprint = hashlib.sha256(old.encode()).digest()
                cached = self._model_metadata.get(identifier)
                if (
                    not include_usage
                    and cached is not None
                    and cached["revision"] == revision
                    and cached["storage"] == storage
                    and cached["fingerprint"] == fingerprint
                    and time.monotonic() < cached["expires"]
                    and time.time() < cached["token_expiration"]
                ):
                    return deepcopy(cached["public"])
                # A new provider check supersedes older cached discovery even
                # if its response is unavailable or the account was revoked.
                self._model_metadata.pop(identifier, None)
            public, refreshed = self._broker().metadata(
                document, include_usage=include_usage, deadline=deadline
            )
            with self.manager._lock:
                self._save_refreshed(
                    identifier, old, refreshed, storage, revision=revision
                )
                if (
                    not include_usage
                    and public.get("account_ready") is True
                    and public.get("models")
                ):
                    self._model_metadata[identifier] = {
                        "revision": revision,
                        "storage": storage,
                        "fingerprint": hashlib.sha256(
                            _pack(refreshed).encode()
                        ).digest(),
                        "expires": time.monotonic() + 30,
                        "token_expiration": datetime.fromisoformat(
                            goose_token_cache(refreshed)["expires_at"]
                        ).timestamp(),
                        "public": deepcopy(public),
                    }
            return public
        finally:
            self._auth_lock.release()

    def claude_status(self, identifier, *, logout=False):
        """Only native sign-in readiness crosses the worker boundary."""
        with self.manager._lock:
            account = next(
                (a for a in self.manager._accounts if a["id"] == identifier), None
            )
            if not account or account["profile"]["provider"] != "claude_code":
                raise ConnectionError("Choose a saved Claude Code account.")
            lock = self._claude_locks.setdefault(identifier, threading.Lock())
        # The panel and model catalog can probe together. Serialize each account's
        # native operations without blocking selection or another account's probe.
        # Logout shares this lock, so an older read cannot restore its session.
        with lock:
            return self._claude_status_locked(identifier, logout=logout)

    def _claude_status_locked(self, identifier, *, logout=False):
        from labcat.goose_worker_client import _worker_request

        with self.manager._lock:
            account = next(
                (a for a in self.manager._accounts if a["id"] == identifier), None
            )
            if not account or account["profile"]["provider"] != "claude_code":
                raise ConnectionError("Choose a saved Claude Code account.")
            revision = self._claude_revisions.get(identifier, 0) + 1
            self._claude_revisions[identifier] = revision
            if logout:
                self._claude_sessions.pop(identifier, None)
                if self.manager._active_account_id == identifier:
                    self.manager.setup.invalidate()
        try:
            value = _worker_request(
                "/claude/logout" if logout else "/claude/status",
                {"account_id": identifier},
            )
            import re

            if (
                set(value) != {"available", "signed_in", "session_id", "message"}
                or type(value["available"]) is not bool
                or type(value["signed_in"]) is not bool
                or not isinstance(value["message"], str)
                or len(value["message"]) > 400
                or (
                    value["signed_in"]
                    and (
                        not value["available"]
                        or not isinstance(value["session_id"], str)
                        or not re.fullmatch(r"[a-f0-9]{32}", value["session_id"])
                    )
                )
                or (not value["signed_in"] and value["session_id"] is not None)
            ):
                raise ValueError
        except (ModelError, ValueError, TypeError, KeyError):
            raise ConnectionError(
                "The native Claude Code connection could not be checked. Use the "
                "current Docker application."
            ) from None
        with self.manager._lock:
            if self._claude_revisions.get(identifier) != revision:
                raise ConnectionError(
                    "The Claude Code connection changed during its check. "
                    "Check the current session again."
                )
            previous = self._claude_sessions.get(identifier)
            self._claude_sessions[identifier] = value
            if previous != value and self.manager._active_account_id == identifier:
                self.manager.setup.invalidate()
        return {key: value[key] for key in ("available", "signed_in", "message")}

    def claude_models(self, identifier=None):
        from labcat.claude_auth import MODELS

        if identifier is None:
            identifier = self.manager.status()["active_account_id"]
        state = self.claude_status(identifier)
        if not state["signed_in"]:
            raise ConnectionError(state["message"])
        return {
            "provider": "claude_code",
            "models": [dict(row) for row in MODELS],
            "message": (
                "Claude Code model aliases. Sign-in is present; model entitlement, "
                "quota and inference have not been tested."
            ),
            "inference_tested": False,
        }

    def models(self, identifier=None):
        if identifier is None:
            identifier = self.manager.status()["active_account_id"]
        data = self.metadata(identifier, include_usage=False)
        if data.get("account_ready") is not True:
            raise ConnectionError(
                "ChatGPT sign-in could not be verified. Reconnect this account."
            )
        return {
            "provider": "chatgpt",
            "models": [{"id": m["id"], "label": m["label"]} for m in data["models"]],
            "message": (
                "Models reported by your ChatGPT connection. No inference was run."
            ),
            "inference_tested": False,
        }

    def usage(self):
        status = self.manager.status()
        identifier, provider = (
            status["active_account_id"],
            status["profile"]["provider"],
        )
        data = {
            "account_id": identifier,
            "provider": provider,
            "rate_limits": None,
            "token_activity": None,
            "last_run": None,
            "notices": [],
            "inference_tested": False,
        }
        if provider == "chatgpt":
            account = next(
                (item for item in status["accounts"] if item["id"] == identifier),
                None,
            )
            credential_state = account.get("credential_state") if account else None
            if credential_state not in {"session", "encrypted"}:
                data["notices"].append(
                    "Unlock the credential vault to check this ChatGPT account."
                    if credential_state == "locked"
                    else "Sign in to this saved ChatGPT connection before checking "
                    "account allowance. No account request was made."
                )
            else:
                metadata = self.metadata(identifier)
                data.update(
                    {
                        key: metadata[key]
                        for key in ("rate_limits", "token_activity", "notices")
                    }
                )
        else:
            data["notices"].append(
                "Account-wide remaining quota is not exposed by this connection. "
                "Reported per-run tokens are shown when available."
            )
        try:
            saved = json.loads(read_private_file(self.usage_path, 100_000))
            if isinstance(saved, dict):
                record = saved.get(identifier or provider)
                data["last_run"] = _safe_run_record(record)
        except (ConnectionError, ValueError, OSError):
            pass
        return data

    def _record_usage(self, identifier, provider, model, result):
        record = _safe_run_record(
            {
                "provider": provider,
                "model": model,
                "recorded_at": datetime.now(UTC).isoformat(),
                "usage": deepcopy(result.get("usage")),
                "status": result.get("status"),
            }
        )
        if record is None:
            raise ConnectionError("The reported usage could not be validated.")
        with self.manager._lock:
            try:
                saved = json.loads(read_private_file(self.usage_path, 100_000))
            except (ConnectionError, ValueError, OSError):
                saved = {}
            if not isinstance(saved, dict):
                saved = {}
            saved[identifier or provider] = record
            atomic_write(self.usage_path, saved)

    def run(self, prompt, context, tool_session):
        from labcat.models import ModelBusy

        if not self._run_lock.acquire(blocking=False):
            raise ModelBusy("A model connection operation is already in progress.")
        try:
            # Fail promptly for a competing metadata operation; never queue inference.
            if not self._auth_lock.acquire(blocking=False):
                raise ModelBusy("A model connection operation is already in progress.")
            self._auth_lock.release()
            return self._run_locked(prompt, context, tool_session)
        finally:
            with self.manager._lock:
                self._running_oauth_account = None
            self._run_lock.release()

    def _run_locked(self, prompt, context, tool_session):
        from labcat.goose_worker_client import run_remote_goose
        from labcat.models import ModelBusy

        if not self._auth_lock.acquire(blocking=False):
            raise ModelBusy("A model connection operation is already in progress.")
        try:
            verified = self.manager.setup.require_ready()
            with self.manager._lock:
                snapshot = self.manager._capture_verified_connection(verified)
                profile, identifier = snapshot["profile"], snapshot["account_id"]
                provider = profile["provider"]
                secret = snapshot["secret"] if provider in API_KEY_PROVIDERS else None
                tokens, old, storage, revision = None, None, None, None
                if provider == "chatgpt":
                    from labcat.chatgpt_auth import goose_token_cache

                    old, storage = snapshot["secret"], snapshot["storage"]
                    document = _unpack(old)
                    tokens = goose_token_cache(document)
                    revision = self._credential_revision(identifier)
                    self._running_oauth_account = identifier
        finally:
            self._auth_lock.release()
        try:
            result = run_remote_goose(
                profile,
                secret,
                prompt,
                context=context,
                tool_session=tool_session,
                chatgpt_tokens=tokens,
                **(
                    {
                        "claude_account_id": identifier,
                        "claude_session_id": snapshot["claude_session_id"],
                    }
                    if provider == "claude_code"
                    else {}
                ),
            )
        except ModelError as error:
            # Bind this diagnostic to the profile actually sent to the worker;
            # never recover model identity from provider prose or a later selection.
            error.research_attempt = {"provider": provider, "model": profile["model"]}
            error.connection_generation = snapshot["generation"]
            refreshed = getattr(error, "refreshed_chatgpt_tokens", None)
            if refreshed is not None and provider == "chatgpt":
                from labcat.chatgpt_auth import update_from_goose_tokens

                self._save_refreshed(
                    identifier,
                    old,
                    update_from_goose_tokens(document, refreshed),
                    storage,
                    revision=revision,
                    ignore_superseded=True,
                )
            raise
        result = dict(result)
        refreshed = result.pop("refreshed_chatgpt_tokens", None)
        if refreshed is not None:
            from labcat.chatgpt_auth import update_from_goose_tokens

            self._save_refreshed(
                identifier,
                old,
                update_from_goose_tokens(document, refreshed),
                storage,
                revision=revision,
                ignore_superseded=True,
            )
        self._record_usage(identifier, provider, profile["model"], result)
        return {
            **result,
            "account_id": identifier,
            "provider": provider,
            "model": profile["model"],
        }
