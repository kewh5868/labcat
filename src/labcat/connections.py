"""Nonsecret connection profiles and explicit, non-inference readiness
checks."""

import hashlib
import json
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from labcat.aws import AWSConnectionError, check_connection
from labcat.credentials import (
    SLOTS,
    ConnectionError,
    CredentialVault,
    atomic_write,
    read_private_file,
    unique_json_object,
    validate_secrets,
)
from labcat.models import (
    ModelError,
    Plan,
    plan_with_model,
    request_json,
    validate_ollama_url,
)
from labcat.provider_catalog import API_KEY_PROVIDERS, MODEL_LIST_ENDPOINTS

PROVIDERS = ("none", "ollama", *API_KEY_PROVIDERS, "bedrock", "chatgpt")
DEFAULT_PROFILE = {
    "provider": "none",
    "model": "",
    "ollama_url": "http://127.0.0.1:11434",
    "aws_profile": "default",
    "aws_region": "us-west-2",
    "allow_paid_inference": False,
}


def validate_profile(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != set(DEFAULT_PROFILE):
        raise ConnectionError("Supply the complete supported connection profile.")
    if value["provider"] not in PROVIDERS:
        raise ConnectionError("Choose a supported model provider.")
    if type(value["allow_paid_inference"]) is not bool:
        raise ConnectionError("Hosted inference consent must be an explicit boolean.")
    for key, pattern in (
        ("model", r"[A-Za-z0-9_.:/-]{0,200}"),
        ("aws_profile", r"[A-Za-z0-9_.@+-]{1,128}"),
        ("aws_region", r"[a-z0-9-]{1,64}"),
    ):
        if not isinstance(value[key], str) or not re.fullmatch(pattern, value[key]):
            raise ConnectionError("A connection identifier is invalid.")
    if not isinstance(value["ollama_url"], str):
        raise ConnectionError("A local Ollama address is required.")
    try:
        local_url = validate_ollama_url(value["ollama_url"])
    except ModelError as error:
        raise ConnectionError(str(error)) from None
    if value["provider"] == "ollama" and "cloud" in value["model"].lower():
        raise ConnectionError("Choose a downloaded local Ollama model.")
    if value["provider"] in {"none", "ollama"} and value["allow_paid_inference"]:
        raise ConnectionError("Local providers do not use hosted inference consent.")
    return {**value, "ollama_url": local_url}


class ConnectionManager:
    """One manager per local application process; files are workspace-
    specific."""

    def __init__(self, workspace_path: Path):
        workspace_path = Path(workspace_path)
        self.profile_path = workspace_path.with_suffix(".connections.json")
        self.pending_path = workspace_path.with_suffix(".pending.connections.json")
        self.vault = CredentialVault(
            workspace_path.with_suffix(".credentials.enc.json")
        )
        self._lock = threading.RLock()
        self._profile = dict(DEFAULT_PROFILE)
        self._configured = False
        self._accounts: list[dict] = []
        self._active_account_id: str | None = None
        self._local_override = False
        self._warnings: list[str] = []
        self._mp_verified = None
        self._mp_error = None
        self._mp_generation = 0
        self._mp_probe_lock = threading.Lock()
        from labcat.agent_connections import AgentConnections

        self.agent = AgentConnections(self, workspace_path)
        if self.profile_path.exists() or self.profile_path.is_symlink():
            try:
                value = json.loads(
                    read_private_file(self.profile_path, 32768),
                    object_pairs_hook=unique_json_object,
                )
                if not isinstance(value, dict) or type(value.get("version")) is not int:
                    raise ValueError
                if value["version"] == 1 and set(value) == {"version", "profile"}:
                    accounts, active = [], None
                elif value["version"] == 2 and set(value) == {
                    "version",
                    "profile",
                    "accounts",
                    "active_account_id",
                }:
                    accounts = self._validate_accounts(value["accounts"])
                    active = value["active_account_id"]
                    if active is not None and not any(
                        a["id"] == active for a in accounts
                    ):
                        raise ValueError
                    selected = next((a for a in accounts if a["id"] == active), None)
                    if selected and selected["profile"] != value["profile"]:
                        raise ValueError
                else:
                    raise ValueError
                self._profile = validate_profile(value["profile"])
                self._accounts, self._active_account_id = accounts, active
                self._configured = True
            except (ConnectionError, ValueError, TypeError, RecursionError):
                self._warnings.append(
                    "The saved connection profile could not be read. "
                    "Local computation is active; save a valid profile to recover."
                )
        if self.pending_path.exists() or self.pending_path.is_symlink():
            self._local_override = True
            self._warnings.append(
                "A previous connection change did not finish. Local computation "
                "is active; review and explicitly save or select a connection."
            )
        from labcat.onboarding import SetupState

        self.setup = SetupState(self, workspace_path)

    @staticmethod
    def _validate_accounts(value):
        if not isinstance(value, list) or len(value) > 12:
            raise ConnectionError("Save at most twelve named model connections.")
        seen, accounts = set(), []
        for account in value:
            if not isinstance(account, dict) or set(account) != {
                "id",
                "label",
                "profile",
            }:
                raise ConnectionError("Invalid saved connection.")
            identifier, label = account["id"], account["label"]
            if (
                not isinstance(identifier, str)
                or not re.fullmatch(r"[a-f0-9]{32}", identifier)
                or identifier in seen
                or not isinstance(label, str)
                or not 1 <= len(label.strip()) <= 80
                or any(ord(c) < 32 for c in label)
            ):
                raise ConnectionError(
                    "Use a short connection name without control characters."
                )
            profile = validate_profile(account["profile"])
            if profile["provider"] == "none":
                raise ConnectionError("Choose a model provider for a named connection.")
            seen.add(identifier)
            accounts.append(
                {"id": identifier, "label": label.strip(), "profile": profile}
            )
        return accounts

    def _write_state(self, profile, accounts, active):
        if hasattr(self, "setup"):
            self.setup.invalidate()
        atomic_write(
            self.profile_path,
            {
                "version": 2,
                "profile": profile,
                "accounts": accounts,
                "active_account_id": active,
            },
        )
        if self.pending_path.is_symlink():
            raise ConnectionError("Connection storage cannot use symbolic links.")
        try:
            self.pending_path.unlink(missing_ok=True)
        except OSError:
            raise ConnectionError(
                "The connection change could not be finalized."
            ) from None

    def _change_credentials_and_state(
        self, profile, accounts, active, values, forget, storage
    ):
        """A nonsecret marker makes an interrupted two-file update fail
        closed."""
        if "materials_project" in values or "materials_project" in forget:
            self._invalidate_materials_project()
        checkpoint = self.vault.checkpoint()
        atomic_write(self.pending_path, {"pending": True})
        try:
            self.vault.update(values, forget, storage)
            self._write_state(profile, accounts, active)
        except ConnectionError:
            try:
                self.vault.restore(checkpoint)
            except ConnectionError:
                self.vault.session.clear()
                self.vault._encrypted = {}
                self.vault._fernet = None
            self._local_override = True
            self._warnings = [
                "The connection change failed. Local computation is active; "
                "review the saved connection and retry."
            ]
            raise

    def _model_slot(self, provider):
        if not self._local_override and self._active_account_id:
            return "account_" + self._active_account_id
        return provider

    def _credential_states(self):
        states = self.vault.slots()
        result = {slot: states.get(slot, "missing") for slot in SLOTS}
        provider = self._profile["provider"]
        if self._active_account_id and not self._local_override and provider in SLOTS:
            result[provider] = states.get(self._model_slot(provider), "missing")
        return result

    def _account_states(self):
        states = self.vault.slots()
        return [
            {
                **account,
                "profile": dict(account["profile"]),
                "credential_state": (
                    states.get("oauth_" + account["id"], "missing")
                    if account["profile"]["provider"] == "chatgpt"
                    else (
                        states.get("account_" + account["id"], "missing")
                        if account["profile"]["provider"] in SLOTS
                        else "not_required"
                    )
                ),
            }
            for account in self._accounts
        ]

    def save_account(self, request, identifier=None):
        if (
            not isinstance(request, dict)
            or set(request) - {"label", "profile", "secret_storage", "api_key"}
            or not {"label", "profile", "secret_storage"} <= set(request)
        ):
            raise ConnectionError(
                "Supply a connection name, provider and storage choice."
            )
        if not isinstance(request["secret_storage"], str) or request[
            "secret_storage"
        ] not in {"session", "encrypted"}:
            raise ConnectionError("Choose session or encrypted credential storage.")
        if identifier is not None and not isinstance(identifier, str):
            raise ConnectionError("Unknown model connection.")
        with self._lock:
            existing = next((a for a in self._accounts if a["id"] == identifier), None)
            if identifier is not None and existing is None:
                raise ConnectionError("Unknown model connection.")
            identifier = identifier or uuid4().hex
            value = {
                "id": identifier,
                "label": request["label"],
                "profile": request["profile"],
            }
            accounts = self._validate_accounts(
                [a for a in self._accounts if a["id"] != identifier] + [value]
            )
            value = next(a for a in accounts if a["id"] == identifier)
            provider = value["profile"]["provider"]
            if existing and existing["profile"]["provider"] != provider:
                raise ConnectionError(
                    "Create a separate connection for another provider."
                )
            key = request.get("api_key", "")
            if not isinstance(key, str):
                raise ConnectionError("Supply an API key as text.")
            if key and provider not in SLOTS:
                raise ConnectionError(
                    "This provider uses its local service or AWS profile."
                )
            values = {"account_" + identifier: key} if key else {}
            validate_secrets(values)
            self._change_credentials_and_state(
                value["profile"],
                accounts,
                identifier,
                values,
                [],
                request["secret_storage"],
            )
            self._profile, self._accounts = value["profile"], accounts
            self._active_account_id = identifier
            self._configured, self._local_override = True, False
            self._warnings = []
            return self.status()

    def select_account(self, identifier):
        with self._lock:
            account = next((a for a in self._accounts if a["id"] == identifier), None)
            if account is None:
                raise ConnectionError("Unknown model connection.")
            self._write_state(account["profile"], self._accounts, identifier)
            self._profile, self._active_account_id = account["profile"], identifier
            self._configured, self._local_override = True, False
            self._warnings = []
            return self.status()

    def apply_default_account(self, identifier) -> bool:
        """Apply a deployment default only before an explicit connection
        choice.

        A direct provider and local/recovery mode are selections too,
        even when they have no named account ID. Check and select under
        the same lock.
        """
        with self._lock:
            if (
                identifier is None
                or self._configured
                or self._local_override
                or self._warnings
                or self._active_account_id is not None
                or self._profile["provider"] != "none"
            ):
                return False
            self.select_account(identifier)
            return True

    def status(self) -> dict:
        with self._lock:
            return {
                "configured": self._configured,
                "profile": dict(
                    DEFAULT_PROFILE if self._local_override else self._profile
                ),
                "credentials": self._credential_states(),
                "accounts": self._account_states(),
                "active_account_id": (
                    None if self._local_override else self._active_account_id
                ),
                "vault": self.vault.status(),
                "using_local_defaults": self._local_override,
                "warnings": self._warnings + self.vault.warnings,
                "source_connections": self.source_connections(),
            }

    @staticmethod
    def _source_fingerprint(secret):
        return hashlib.sha256(secret.encode("utf-8")).digest() if secret else None

    def _invalidate_materials_project(self):
        """Verification never survives a credential or vault lifecycle
        change."""
        self._mp_verified = None
        self._mp_error = None
        self._mp_generation += 1

    def source_connections(self) -> dict:
        """Nonsecret, process-local readiness for optional authenticated
        sources."""
        with self._lock:
            state = self.vault.slots().get("materials_project", "missing")
            secret = self.vault.get("materials_project")
            fingerprint = self._source_fingerprint(secret)
            if self._mp_verified and self._mp_verified["fingerprint"] != fingerprint:
                self._mp_verified = None
            if self._mp_error and self._mp_error["fingerprint"] != fingerprint:
                self._mp_error = None
            status, message = (
                "verification_required",
                "The saved API key will be checked when research or structure "
                "retrieval needs Materials Project. You can also verify it here.",
            )
            if state == "locked":
                status, message = (
                    "locked",
                    "Unlock the saved API key in Connections, then test it.",
                )
            elif not secret:
                status, message = (
                    "not_configured",
                    "Add and test a Materials Project API key in Connections.",
                )
            elif self._mp_verified:
                status, message = (
                    "ready",
                    "The current API key passed a public connection test "
                    "in this session.",
                )
            elif self._mp_error:
                status, message = (
                    "error",
                    "The source connection failed. Review and test it in Connections.",
                )
            return {
                "materials_project": {
                    "status": status,
                    "selectable": status == "ready",
                    "requires_credentials": True,
                    "verified_at": (
                        self._mp_verified["verified_at"] if status == "ready" else None
                    ),
                    "message": message,
                }
            }

    def require_source_connection(self, source: str) -> None:
        from labcat.source_preferences import SourceConnectionRequired

        if (
            source != "materials_project"
            or not self.source_connections()[source]["selectable"]
        ):
            raise SourceConnectionRequired(
                "Verify the Materials Project API key in Connections before selecting "
                "this API, or choose automatic/keyless sources."
            )

    def materials_project_key(self, mode: str) -> str | None:
        """The application may only send a key that is verified in this
        process."""
        from labcat.source_preferences import SourceConnectionRequired

        if mode not in {"auto", "api", "off", "snapshot"}:
            raise SourceConnectionRequired("Choose a supported source mode.")
        with self._lock:
            if mode in {"off", "snapshot"}:
                return None
            if mode == "api":
                self.require_source_connection("materials_project")
            if self.source_connections()["materials_project"]["selectable"]:
                return self.vault.get("materials_project")
            return None

    def prepare_materials_project(self, mode: str) -> None:
        """Recheck a saved key once when research explicitly needs this
        source.

        Readiness remains process-local and bound to the current
        credential. Status reads never perform network access; a failed
        check is not retried by every candidate in the same run. Manual
        verification can retry it.
        """
        if mode not in {"auto", "api"}:
            return
        from labcat.science.retrieval_budget import bounded_deadline, repository_budget

        try:
            deadline = bounded_deadline(18)
        except ValueError:
            raise ConnectionError(
                "The source connection check exceeded its time budget."
            ) from None
        if not self._mp_probe_lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise ConnectionError("The source connection check is already in progress.")
        try:
            if self.source_connections()["materials_project"]["status"] == (
                "verification_required"
            ):
                with repository_budget(seconds=max(0, deadline - time.monotonic())):
                    self.test("materials_project")
        except ValueError:
            raise ConnectionError(
                "The source connection check could not complete within its budget."
            ) from None
        finally:
            self._mp_probe_lock.release()

    def observe_source_result(self, outcome: dict, used_key: str | None) -> None:
        """A failed real source request invalidates only the credential
        it used."""
        if not used_key:
            return
        attempts = (
            outcome.get("result", {})
            .get("retrieval", {})
            .get("repository_attempts", [])
        )
        if not any(
            row.get("repository") == "materials_project"
            and row.get("status") == "unavailable"
            for row in attempts
        ):
            return
        with self._lock:
            fingerprint = self._source_fingerprint(used_key)
            if fingerprint == self._source_fingerprint(
                self.vault.get("materials_project")
            ):
                self._invalidate_materials_project()
                self._mp_error = {"fingerprint": fingerprint}

    def configure(self, request: object) -> dict:
        if (
            not isinstance(request, dict)
            or set(request) - {"profile", "secret_storage", "secrets", "forget_secrets"}
            or not {"profile", "secret_storage"} <= set(request)
        ):
            raise ConnectionError("Unsupported connection settings.")
        profile = validate_profile(request["profile"])
        storage = request["secret_storage"]
        if not isinstance(storage, str) or storage not in {"session", "encrypted"}:
            raise ConnectionError("Choose session or encrypted credential storage.")
        secrets = validate_secrets(request.get("secrets", {}))
        if set(secrets) - set(SLOTS):
            raise ConnectionError("Use the account settings to change that credential.")
        forget = request.get("forget_secrets", [])
        if not isinstance(forget, list) or any(slot not in SLOTS for slot in forget):
            raise ConnectionError("Unsupported credential removal request.")
        if set(forget) & set(secrets):
            raise ConnectionError(
                "Do not save and forget the same credential together."
            )
        with self._lock:
            accounts = [dict(account) for account in self._accounts]
            active = self._active_account_id
            selected = next(
                (account for account in accounts if account["id"] == active), None
            )
            if selected and selected["profile"]["provider"] == profile["provider"]:
                selected["profile"] = profile
                provider = profile["provider"]
                slot = "account_" + selected["id"]
                if provider in secrets:
                    secrets[slot] = secrets.pop(provider)
                forget = [slot if name == provider else name for name in forget]
            else:
                active = None
            self._change_credentials_and_state(
                profile, accounts, active, secrets, forget, storage
            )
            self._accounts, self._active_account_id = accounts, active
            self._profile = profile
            self._configured = True
            self._local_override = False
            self._warnings = []
            return self.status()

    def configure_source(self, source: str, request: object) -> dict:
        """Change one source credential without rewriting model or setup
        state."""
        if source != "materials_project" or not isinstance(request, dict):
            raise ConnectionError("Choose a supported source connection.")
        forget = set(request) == {"forget"} and request["forget"] is True
        if not forget and (
            set(request) - {"api_key", "secret_storage"}
            or "secret_storage" not in request
        ):
            raise ConnectionError("Supply only a source API key and storage choice.")
        storage = "session" if forget else request["secret_storage"]
        if not isinstance(storage, str) or storage not in {"session", "encrypted"}:
            raise ConnectionError("Choose session or encrypted credential storage.")
        if "api_key" in request:
            validate_secrets({source: request["api_key"]})
        with self._lock:
            values = {}
            if not forget:
                key = request.get("api_key", self.vault.get(source))
                if not key:
                    raise ConnectionError(
                        "Enter an API key or unlock the saved source key first."
                    )
                values = {source: key}
            self._invalidate_materials_project()
            # This is a single atomic vault update, with no profile-file write.
            # Removing the slot before replacing it also removes a previous
            # encrypted copy when the user explicitly chooses session storage.
            self.vault.update(values, [source], storage)
            return self.status()

    def local_defaults(self, persist: bool = False) -> dict:
        if type(persist) is not bool:
            raise ConnectionError("Choose whether local defaults should be remembered.")
        with self._lock:
            if persist:
                self._write_state(dict(DEFAULT_PROFILE), self._accounts, None)
                self._active_account_id = None
                self._profile = dict(DEFAULT_PROFILE)
                self._configured = True
                self._local_override = False
                self._warnings = []
            else:
                self._local_override = True
            return self.status()

    def vault_action(self, request: object) -> dict:
        if not isinstance(request, dict):
            raise ConnectionError("Unsupported vault request.")
        action = request.get("action")
        if not isinstance(action, str):
            raise ConnectionError("Unsupported vault action.")
        with self._lock:
            self.setup.invalidate()
            self._invalidate_materials_project()
            if action in {"create", "unlock"} and set(request) == {
                "action",
                "passphrase",
            }:
                if action == "create":
                    self.vault.create(request["passphrase"])
                else:
                    self.vault.unlock(request["passphrase"])
            elif action == "lock" and set(request) == {"action"}:
                self.agent.cancel_pending()
                self.vault.lock()
            elif (
                action == "reset"
                and set(request) == {"action", "confirm"}
                and request["confirm"] is True
            ):
                self.agent.cancel_pending()
                self.vault.reset()
            else:
                raise ConnectionError("Unsupported or unconfirmed vault action.")
            return self.status()

    def get_secret(self, slot: str) -> str | None:
        """Internal adapter access only; never expose this method in an
        API route."""
        with self._lock:
            return self.vault.get(slot)

    def plan(self, prompt: str, context: dict | None = None) -> Plan:
        self.setup.require_ready()
        with self._lock:
            profile = dict(DEFAULT_PROFILE if self._local_override else self._profile)
            secret = (
                self.vault.get(self._model_slot(profile["provider"]))
                if profile["provider"] in SLOTS
                else None
            )
        return plan_with_model(profile, secret, prompt, context=context)

    def test(self, target: str) -> dict:
        """Explicit metadata/read-only checks.

        No model invocation or provisioning.
        """
        if target not in {"materials_project", "model", "aws"}:
            raise ConnectionError("Unsupported connection test.")
        result = {
            "target": target,
            "status": "ok",
            "message": "",
            "billable": False,
            "inference_tested": False,
        }
        with self._lock:
            profile = dict(DEFAULT_PROFILE if self._local_override else self._profile)
            slot = (
                "materials_project"
                if target == "materials_project"
                else self._model_slot(profile["provider"])
            )
            secret = (
                self.vault.get(slot)
                if slot in SLOTS or slot.startswith("account_")
                else None
            )
            if target == "materials_project":
                self._invalidate_materials_project()
                source_generation = self._mp_generation
        try:
            if (
                target == "aws"
                or target == "model"
                and profile["provider"] == "bedrock"
            ):
                if target == "model":
                    from labcat.aws import requires_mantle

                    if requires_mantle(profile["model"]):
                        raise ModelError(
                            "This model requires Bedrock Mantle bearer-token access, "
                            "which this AWS session connection does not support. "
                            "Choose another model from the returned catalog."
                        )
                check_connection(profile["aws_profile"], profile["aws_region"])
                if target == "model":
                    catalog = self.list_models()
                    self._check_model(catalog["models"], profile["model"], "id")
                result["message"] = (
                    "AWS credentials accepted. No identity details retained. "
                    "Bedrock model authorization and inference have not been tested."
                )
            elif target == "materials_project":
                from labcat.science.sources import SourceError, probe_connection

                if not secret:
                    result.update(
                        status="not_configured",
                        message="Materials Project key is missing or locked.",
                    )
                    return result
                try:
                    probe_connection(secret)
                except SourceError as error:
                    with self._lock:
                        if (
                            source_generation == self._mp_generation
                            and self._source_fingerprint(secret)
                            == self._source_fingerprint(
                                self.vault.get("materials_project")
                            )
                        ):
                            self._mp_error = {
                                "fingerprint": self._source_fingerprint(secret)
                            }
                    result.update(status="error", message=str(error))
                    return result
                with self._lock:
                    if (
                        source_generation != self._mp_generation
                        or self._source_fingerprint(secret)
                        != self._source_fingerprint(self.vault.get("materials_project"))
                    ):
                        result.update(
                            status="error",
                            message="The API credential changed during its check. "
                            "Test the current connection again.",
                        )
                        return result
                    self._mp_verified = {
                        "fingerprint": self._source_fingerprint(secret),
                        "verified_at": datetime.now(UTC).isoformat(),
                    }
                result["message"] = (
                    "Materials Project public API responded. No inference was run."
                )
            else:
                provider = profile["provider"]
                if provider == "none":
                    result["message"] = (
                        "Local deterministic mode is ready. "
                        "No model is selected or invoked."
                    )
                elif provider == "chatgpt":
                    catalog = self.agent.models()
                    self._check_model(catalog["models"], profile["model"], "id")
                    result["message"] = (
                        "ChatGPT account and model catalog responded. "
                        "No model inference was run."
                    )
                elif provider == "ollama":
                    data = request_json(
                        validate_ollama_url(profile["ollama_url"]) + "/api/tags"
                    )
                    self._check_model(data.get("models"), profile["model"], "name")
                    result["message"] = (
                        "Local Ollama model listing responded. "
                        "Inference has not been tested."
                    )
                else:
                    if not secret:
                        result.update(
                            status="not_configured",
                            message="The model credential is missing or locked.",
                        )
                        return result
                    endpoint = MODEL_LIST_ENDPOINTS[provider]
                    headers = (
                        {"x-api-key": secret, "anthropic-version": "2023-06-01"}
                        if provider == "anthropic"
                        else {"Authorization": "Bearer " + secret}
                    )
                    data = request_json(endpoint, headers=headers)
                    self._check_model(data.get("data"), profile["model"], "id")
                    result["message"] = (
                        "Provider model listing responded. This does not prove "
                        "inference authorization, available quota or "
                        "structured-output compatibility."
                    )
        except (ModelError, AWSConnectionError, ConnectionError) as error:
            result.update(status="error", message=str(error))
        return result

    def list_models(self) -> dict:
        """Explicit metadata request; never invokes a model or reveals a
        key."""
        if self.status()["profile"]["provider"] == "chatgpt":
            return self.agent.models()
        with self._lock:
            profile = dict(DEFAULT_PROFILE if self._local_override else self._profile)
            provider = profile["provider"]
            secret = (
                self.vault.get(self._model_slot(provider))
                if provider in SLOTS
                else None
            )
        try:
            if provider == "none":
                models = []
            elif provider == "bedrock":
                from labcat.aws import model_options

                models = model_options(profile["aws_profile"], profile["aws_region"])
            else:
                if provider == "ollama":
                    data = request_json(
                        validate_ollama_url(profile["ollama_url"]) + "/api/tags"
                    )
                    values, field = data.get("models"), "name"
                else:
                    if not secret:
                        raise ModelError(
                            "Save or unlock a credential before listing models."
                        )
                    endpoint = MODEL_LIST_ENDPOINTS[provider]
                    headers = (
                        {"x-api-key": secret, "anthropic-version": "2023-06-01"}
                        if provider == "anthropic"
                        else {"Authorization": "Bearer " + secret}
                    )
                    data = request_json(endpoint, headers=headers)
                    values, field = data.get("data"), "id"
                if not isinstance(values, list):
                    raise ModelError("Provider returned an unsupported model listing.")
                models = [
                    {"id": row[field], "label": row[field]}
                    for row in values[:200]
                    if isinstance(row, dict)
                    and isinstance(row.get(field), str)
                    and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", row[field])
                    and not (provider == "ollama" and "cloud" in row[field].lower())
                ]
            return {
                "provider": provider,
                "models": models,
                "inference_tested": False,
                "message": (
                    "Provider catalog only. A listed model may require additional "
                    "access or may not support this application's planning protocol. "
                    "Use a custom identifier if your authorized model is not listed."
                    + (
                        " Bedrock includes up to 200 active inference profiles when "
                        "the account permits ListInferenceProfiles; otherwise only "
                        "foundation models are available. Mantle/bearer-token models "
                        "are not supported by this AWS session connection."
                        if provider == "bedrock"
                        else ""
                    )
                ),
            }
        except (ModelError, AWSConnectionError) as error:
            raise ConnectionError(str(error)) from None

    @staticmethod
    def _check_model(values, model: str, field: str):
        if not isinstance(values, list) or any(
            not isinstance(item, dict) for item in values
        ):
            raise ModelError("Provider returned an unsupported model listing.")
        if not model:
            raise ModelError(
                "The service responded. Choose a model identifier before planning."
            )
        if not any(item.get(field) == model for item in values):
            raise ModelError(
                "The selected model was not in the returned listing. "
                "Check its identifier and account access; inference was not tested."
            )
