"""Account-bound Goose execution and provider-owned ChatGPT
authentication.

No OAuth credential is returned by this module's public methods. The
only persistent secret representation is the application's authenticated
vault.
"""

import base64
import json
import math
import os
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from labcat.credentials import (
    ConnectionError,
    atomic_write,
    read_private_file,
    unique_json_object,
)


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
                "Worker execution is introduced separately."
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
                # A remounted UI or interrupted start response can rediscover its
                # challenge without creating another provider login. Poll through
                # the normal path so completed credentials are saved exactly once.
                current = self.login_action(pending["account_id"], flow_id, "poll")
                same_account = pending["account_id"] == identifier
                same_storage = pending["storage"] == storage
                if (
                    same_account
                    and same_storage
                    and current["status"]
                    in {
                        "pending",
                        "complete",
                    }
                ):
                    return current
                if current["status"] == "pending":
                    if not same_account:
                        raise ConnectionError(
                            "Finish or cancel the sign-in for the other saved "
                            "ChatGPT connection first."
                        )
                    # An explicit new storage choice replaces an unfinished login;
                    # never reassign the old challenge's eventual credentials.
                    self.login_action(identifier, flow_id, "cancel")
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
            self.manager.vault.update({}, ["oauth_" + identifier], "session")
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

    def _save_refreshed(self, identifier, old, document, storage):
        with self.manager._lock:
            slot = "oauth_" + identifier
            # A concurrent sign-out, lock or new sign-in wins over this response.
            if self.manager.vault.get(slot) != old:
                raise ConnectionError(
                    "The account changed during this request. Reload it."
                )
            self.manager.vault.update({slot: _pack(document)}, [], storage)

    def metadata(self, identifier):
        with self._auth_lock:
            document, old, storage = self._credential_snapshot(identifier)
            public, refreshed = self._broker().metadata(document)
            self._save_refreshed(identifier, old, refreshed, storage)
            return public

    def models(self):
        identifier = self.manager.status()["active_account_id"]
        data = self.metadata(identifier)
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
