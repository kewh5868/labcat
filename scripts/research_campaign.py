"""Bounded, resumable live evaluations through the local application's
public API.

Initialize a frozen campaign offline, then explicitly run small paid
batches. No credentials are read, imported, refreshed, or exported by
this runner. An ambiguous submission is reconciled from its saved chat,
never submitted again.
"""

import argparse
import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from pathlib import Path
from runpy import run_path
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
GIB = 1024**3
MAX_RESPONSE = 8 * 1024**2
DEFAULT_END = "2026-09-21T18:00:00+00:00"
PENDING_ROOT = REPO / ".local/research-campaign-pending"
SECRET_KEY = re.compile(
    r"^(?:access_token|refresh_token|id_token|api_key|password|passphrase|secret|"
    r"authorization|cookie|set-cookie|credentials)$",
    re.I,
)
SECRET_VALUE = re.compile(
    r"(?i)\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{10,}|"
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
)


class Paused(Exception):
    """A bounded machine-readable reason, never raw remote exception
    text."""


class RequestFailed(Paused):
    def __init__(self, reason, status=None):
        self.reason, self.status = reason, status
        super().__init__(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def redact(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SECRET_KEY.fullmatch(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SECRET_VALUE.sub("[REDACTED]", value)
    return value


def save_new(path, value):
    """Write once.

    Failures and pre-submission intent are never overwritten.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = json_bytes(redact(value))
    if len(data) > MAX_RESPONSE * 2:
        raise Paused("artifact_too_large")
    with path.open("xb") as handle:
        os.chmod(path, 0o600)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def load(path):
    if path.stat().st_size > MAX_RESPONSE * 2:
        raise Paused("artifact_too_large")
    return json.loads(path.read_bytes())


def local_base(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.port is None
    ):
        raise Paused("invalid_local_address")
    return value.rstrip("/")


def fingerprint():
    # Freeze the evaluator AND the validators it imports. Dirty changes matter.
    paths = [
        REPO / "scripts/evaluate_live_prompts.py",
        REPO / "scripts/research_campaign.py",
        REPO / "docs/materials-evaluation-rubric.md",
    ]
    paths.extend((REPO / "src/labcat").rglob("*.py"))
    package = REPO / "src/labcat"
    # Include bundled scientific records and configuration at their real paths,
    # including future nested data directories. Viewer assets do not affect the
    # backend evidence/ranking contract and are verified separately in UI tests.
    for pattern in ("*.json", "*.toml"):
        paths.extend(
            path
            for path in package.rglob(pattern)
            if "static" not in path.relative_to(package).parts
        )
    return digest(
        json_bytes(
            {
                str(p.relative_to(REPO)): digest(p.read_bytes())
                for p in sorted(set(paths))
            }
        )
    )


def artifact_bytes(path):
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def resource_guard(campaign, manifest):
    if datetime.now(UTC) >= datetime.fromisoformat(manifest["ends_at"]):
        raise Paused("campaign_ended")
    if shutil.disk_usage(campaign).free < manifest["min_free_bytes"]:
        raise Paused("low_disk_space")
    # Reserve room for a full response and its assessment, not just today's size.
    artifact_root = Path(manifest.get("artifact_root", str(campaign)))
    used = artifact_bytes(artifact_root) - manifest.get("artifact_baseline_bytes", 0)
    if used + 4 * MAX_RESPONSE > manifest["artifact_budget_bytes"]:
        raise Paused("artifact_budget_reached")
    if fingerprint() != manifest["implementation_sha256"]:
        raise Paused("implementation_changed_create_new_campaign")
    if digest((campaign / "prompts.json").read_bytes()) != manifest["prompt_sha256"]:
        raise Paused("prompt_set_changed")


@contextmanager
def campaign_lock():
    """One OS-held lock across campaigns; process death releases it
    safely."""
    lock = REPO / ".local/research-campaign.lock"
    lock.parent.mkdir(exist_ok=True, mode=0o700)
    with lock.open("a+b") as handle:
        os.chmod(lock, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                if not handle.read(1):
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Paused("another_campaign_running") from None
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_worker():
    """Child process enforces bounded output; parent enforces wall
    time."""
    try:
        supplied = json.loads(sys.stdin.buffer.read(65537))
        base = local_base(supplied["base"])
        path, body = supplied["path"], supplied["body"]
        if not path.startswith("/api/") or "\n" in path or "\r" in path:
            raise Paused("invalid_api_path")
        opener = build_opener(
            ProxyHandler({}), HTTPCookieProcessor(CookieJar()), NoRedirects()
        )
        headers = {"Content-Type": "application/json", "Origin": base}
        if body is not None:
            with opener.open(base + "/api/session", timeout=15) as session:
                session_data = session.read(4097)
                if len(session_data) > 4096:
                    raise Paused("invalid_local_session")
                csrf = json.loads(session_data).get("csrf_token")
                if not isinstance(csrf, str) or not 16 <= len(csrf) <= 256:
                    raise Paused("invalid_local_session")
                headers["X-CSRF-Token"] = csrf
        request = Request(
            base + path,
            data=json_bytes(body) if body is not None else None,
            headers=headers,
        )
        with opener.open(request, timeout=240) as response:
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise Paused("response_too_large")
            if supplied.get("download"):
                if not path.endswith("/download") or len(data) > 2 * 1024**2:
                    raise Paused("invalid_structure_download")
                value = {
                    "base64": base64.b64encode(data).decode(),
                    "sha256": response.headers.get("X-Structure-SHA256"),
                    "content_type": response.headers.get("Content-Type", ""),
                }
            else:
                value = json.loads(data)
        print(json.dumps({"ok": True, "value": value}))
    except HTTPError as error:
        # Discard response body: it may echo secrets or arbitrary model text.
        print(json.dumps({"ok": False, "reason": "http_error", "status": error.code}))
    except Exception as error:
        reason = str(error) if isinstance(error, Paused) else "transport_error"
        print(json.dumps({"ok": False, "reason": reason}))


class LocalAPI:
    def __init__(self, base):
        self.base = local_base(base)

    def call(self, path, body=None, *, timeout=30, download=False):
        if getattr(self, "deadline", None) is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise RequestFailed("batch_deadline")
            timeout = min(timeout, remaining)
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "_request"],
                input=json.dumps(
                    {
                        "base": self.base,
                        "path": path,
                        "body": body,
                        "download": download,
                    }
                ),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise RequestFailed("request_deadline") from None
        if result.returncode or len(result.stdout) > MAX_RESPONSE * 2:
            raise RequestFailed("request_worker_failed")
        try:
            result = json.loads(result.stdout)
        except (ValueError, TypeError):
            raise RequestFailed("invalid_response") from None
        if not result.get("ok"):
            raise RequestFailed(
                result.get("reason", "transport_error"), result.get("status")
            )
        return result["value"]


def allowance_remaining(usage):
    values = []
    for bucket in usage.get("rate_limits") or []:
        for name in ("primary", "secondary"):
            value = (bucket.get(name) or {}).get("remaining_percent")
            if (
                type(value) in (float, int)
                and math.isfinite(value)
                and 0 <= value <= 100
            ):
                values.append(value)
    return min(values) if values else None


def ready(api, model):
    status = api.call("/api/connections/setup")
    current = status.get("model", {})
    if current.get("provider") != "chatgpt" or current.get("model") != model:
        raise Paused("selected_model_does_not_match")
    if current.get("status") == "verification_required":
        status = api.call("/api/connections/setup/verify", {})
    if (
        status.get("model", {}).get("model") != model
        or status.get("model", {}).get("provider") != "chatgpt"
    ):
        raise Paused("selected_model_does_not_match")
    if not status.get("can_research"):
        raise Paused("sign_in_or_connection_action_required")
    usage = api.call("/api/connections/usage", {})
    remaining = allowance_remaining(usage)
    if remaining is not None and remaining <= 0:
        raise Paused("provider_allowance_exhausted")
    return {
        "remaining_percent": remaining,
        "allowance_available": remaining is not None,
    }


def initialize(args):
    if args.campaign.exists():
        raise Paused("campaign_already_exists")
    end = datetime.fromisoformat(args.ends_at.replace("Z", "+00:00"))
    if (
        end.tzinfo is None
        or not 0 < (end - datetime.now(UTC)).total_seconds() <= 6 * 86400
    ):
        raise Paused("end_must_be_within_six_days")
    if args.holdout and not args.protocol_frozen:
        raise Paused("freeze_protocol_before_opening_holdout")
    if args.prompt_set.stat().st_size > MAX_RESPONSE:
        raise Paused("prompt_set_too_large")
    raw = args.prompt_set.read_bytes()
    if args.prompt_sha256 and digest(raw) != args.prompt_sha256:
        raise Paused("unexpected_prompt_hash")
    document = json.loads(raw)
    evaluator = run_path(str(REPO / "scripts/evaluate_live_prompts.py"))
    definitions = evaluator["validate_cases"](document["cases"])
    names = args.case or list(definitions)
    if len(set(names)) != len(names) or any(name not in definitions for name in names):
        raise Paused("invalid_case_selection")
    if not args.model or len(set(args.model)) != len(args.model):
        raise Paused("unique_models_required")
    # All campaigns in the same parent share a fixed incremental disk budget.
    args.campaign.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    budget_file = args.campaign.parent / "campaign-storage-budget.json"
    if not budget_file.exists():
        save_new(budget_file, {"baseline_bytes": artifact_bytes(args.campaign.parent)})
    budget = load(budget_file)
    args.campaign.mkdir(parents=True, mode=0o700)
    with (args.campaign / "prompts.json").open("xb") as handle:
        os.chmod(args.campaign / "prompts.json", 0o600)
        handle.write(raw)
    manifest = {
        "schema": "research-campaign-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "ends_at": end.isoformat(),
        "models": args.model,
        "cases": names,
        "prompt_sha256": digest(raw),
        "implementation_sha256": fingerprint(),
        "runtime_revision": args.runtime_revision,
        "project_prefix": args.project_prefix,
        "holdout": args.holdout,
        "acceptance_version": "materials-evaluation-v3",
        "min_free_bytes": 20 * GIB,
        "artifact_budget_bytes": 2 * GIB,
        "artifact_root": str(args.campaign.parent.resolve()),
        "artifact_baseline_bytes": budget["baseline_bytes"],
        "max_batch_cases": 4,
        "max_batch_seconds": 1200,
        "request_seconds": 240,
        "scientific_review": "pending",
        "runtime_revision_verified_by_runner": False,
    }
    save_new(args.campaign / "manifest.json", manifest)
    return {
        "status": "initialized_no_requests",
        "cases": len(names),
        "models": len(args.model),
        "prompt_sha256": digest(raw),
    }


def completed_detail(detail):
    if not isinstance(detail, dict):
        return False
    return bool(
        detail.get("reports")
        or any(
            item.get("role") == "assistant" and item.get("intake")
            for item in detail.get("messages", [])
        )
    )


def outcome(detail, case, model, evaluator):
    assessment = evaluator["assess"](detail, case)
    actual_model = assessment.get("model")
    if (
        isinstance(detail, dict)
        and detail.get("reports")
        and assessment.get("checks", {}).get("response_schema") is not False
        and (actual_model != model or assessment.get("provider") != "chatgpt")
    ):
        assessment["passed"] = False
        assessment.setdefault("checks", {})["expected_model"] = False
    return {
        "status": "assessed",
        "assessment": assessment,
        "independent_scientific_review": "pending",
        "structure_download_review": "not_exercised",
        "experimental_computed_review": "not_observed",
        "fixed_evidence_weight_review": "pending",
    }


def reconcile(api, folder, case, model, evaluator):
    intent = load(folder / "intent.json")
    progress = api.call(
        "/api/chats/"
        + quote(intent["chat_id"], safe="")
        + "/research-status?run_id="
        + intent["run_id"]
    )
    if progress.get("status") == "running":
        raise Paused("prior_submission_unresolved_no_resubmission")
    detail = api.call("/api/chats/" + quote(intent["chat_id"], safe=""))
    if completed_detail(detail):
        recovered = folder / "recovered-detail.json"
        if not recovered.exists():
            save_new(recovered, detail)
        result = outcome(load(recovered), case, model, evaluator)
        result["recovered_read_only"] = True
        save_new(folder / "reconciliation.json", result)
        return
    if progress.get("run_id") == intent["run_id"] and progress.get("status") in {
        "failed",
        "completed",
    }:
        save_new(
            folder / "reconciliation.json",
            {"status": "failed_without_report", "passed": False},
        )
        return
    raise Paused("prior_submission_unresolved_no_resubmission")


def model_interrupted(detail):
    if not isinstance(detail, dict):
        return False
    return any(
        report.get("result", {}).get("execution", {}).get("model_interrupted") is True
        for report in detail.get("reports", [])
    )


def global_pending_guard(api, reviewed=()):
    """A killed batch cannot hide an active request by starting a new
    campaign."""
    for pending_file in sorted(PENDING_ROOT.glob("*.json")):
        if pending_file.name.endswith((".done.json", ".reviewed.json")):
            continue
        done = pending_file.with_suffix(".done.json")
        pending = load(pending_file)
        if not done.exists():
            if pending["base"] != api.base:
                raise Paused("unresolved_submission_on_other_server")
            prefix = "/api/chats/" + quote(pending["chat_id"], safe="")
            state = api.call(prefix + "/research-status?run_id=" + pending["run_id"])
            if state.get("status") == "running":
                raise Paused("prior_submission_unresolved_no_resubmission")
            detail = api.call(prefix)
            terminal = state.get("run_id") == pending["run_id"] and state.get(
                "status"
            ) in {"completed", "failed"}
            if not terminal and not completed_detail(detail):
                raise Paused("prior_submission_unresolved_no_resubmission")
            save_new(
                done,
                {
                    "status": "server_terminal",
                    "model_interrupted": model_interrupted(detail),
                    "checked_at": datetime.now(UTC).isoformat(),
                },
            )
        if load(done).get("model_interrupted"):
            acknowledgment = pending_file.with_suffix(".reviewed.json")
            if not acknowledgment.exists():
                if pending["run_id"] not in reviewed:
                    raise Paused("model_interrupted_review_required")
                save_new(
                    acknowledgment,
                    {
                        "operator_reviewed": True,
                        "reviewed_at": datetime.now(UTC).isoformat(),
                    },
                )


def mark_pending(intent, base):
    path = PENDING_ROOT / (intent["run_id"] + ".json")
    save_new(
        path,
        {
            "base": base,
            "chat_id": intent["chat_id"],
            "run_id": intent["run_id"],
            "case": intent["case"],
        },
    )
    return path.with_suffix(".done.json")


def run_batch(args, *, api=None):
    campaign = args.campaign
    manifest = load(campaign / "manifest.json")
    resource_guard(campaign, manifest)
    if args.model not in manifest["models"]:
        raise Paused("model_not_in_frozen_campaign")
    if not 1 <= args.batch_size <= manifest["max_batch_cases"]:
        raise Paused("batch_case_limit")
    api = api or LocalAPI(args.server)
    evaluator = run_path(str(REPO / "scripts/evaluate_live_prompts.py"))
    definitions = load(campaign / "prompts.json")["cases"]
    model_dir = campaign / f"model-{manifest['models'].index(args.model) + 1}"
    model_dir.mkdir(exist_ok=True, mode=0o700)
    started = time.monotonic()
    api.deadline = started + manifest["max_batch_seconds"]
    event = {
        "started_at": datetime.now(UTC).isoformat(),
        "model": args.model,
        "submitted": 0,
        "reconciled": 0,
        "status": "batch_complete",
    }
    try:
        global_pending_guard(api, getattr(args, "reviewed_interruption", ()))
        # Reconcile all models first: a timed-out request can outlive its runner.
        for prior_dir in sorted(campaign.glob("model-*/case-*")):
            if (prior_dir / "intent.json").exists() and not (
                prior_dir / "reconciliation.json"
            ).exists():
                prior_result = (
                    load(prior_dir / "outcome.json")
                    if (prior_dir / "outcome.json").exists()
                    else {}
                )
                if prior_result.get("status") != "assessed":
                    prior_intent = load(prior_dir / "intent.json")
                    reconcile(
                        api,
                        prior_dir,
                        definitions[prior_intent["case"]],
                        prior_intent["model"],
                        evaluator,
                    )
                    event["reconciled"] += 1
        allowance = ready(api, args.model)
        sources = api.call("/api/source-settings")
        source_file = campaign / "source-settings.json"
        if source_file.exists():
            if load(source_file) != sources:
                raise Paused("source_settings_changed")
        else:
            save_new(source_file, sources)
        project_file = model_dir / "project.json"
        if not project_file.exists():
            project = api.call(
                "/api/projects",
                {
                    "name": manifest["project_prefix"] + " · " + args.model,
                    "description": (
                        "Frozen evaluation campaign; actual attempts "
                        "and failures retained."
                    ),
                },
            )
            save_new(project_file, {"id": project["id"]})
        project_id = load(project_file)["id"]
        for index, name in enumerate(manifest["cases"]):
            folder = model_dir / f"case-{index + 1:03d}"
            if (folder / "intent.json").exists():
                continue
            resource_guard(campaign, manifest)
            remaining_time = manifest["max_batch_seconds"] - (
                time.monotonic() - started
            )
            if (
                event["submitted"] >= args.batch_size
                or remaining_time < manifest["request_seconds"] + 90
            ):
                break
            allowance = ready(api, args.model)
            chat = api.call(
                "/api/projects/" + quote(project_id, safe="") + "/draft-chat", {}
            )
            intent = {
                "case": name,
                "model": args.model,
                "chat_id": chat["id"],
                "run_id": str(uuid4()),
                "created_at": datetime.now(UTC).isoformat(),
                "allowance": allowance,
            }
            save_new(folder / "intent.json", intent)  # durable BEFORE inference POST
            pending_done = mark_pending(intent, api.base)
            event["submitted"] += 1
            print(
                json.dumps({"status": "submitting", "case": name, "model": args.model}),
                flush=True,
            )
            try:
                detail = api.call(
                    "/api/chats/" + quote(chat["id"], safe="") + "/messages",
                    {
                        "content": definitions[name]["prompt"],
                        "ranking_profile_id": "infer",
                        "run_id": intent["run_id"],
                    },
                    timeout=manifest["request_seconds"],
                )
                save_new(
                    pending_done,
                    {
                        "status": "response_received",
                        "model_interrupted": model_interrupted(detail),
                    },
                )
                save_new(folder / "detail.json", detail)
                resource_guard(campaign, manifest)
                result = outcome(detail, definitions[name], args.model, evaluator)
                save_new(folder / "outcome.json", result)
                print(
                    json.dumps(
                        {
                            "status": "assessed",
                            "case": name,
                            "passed": result["assessment"]["passed"],
                        }
                    ),
                    flush=True,
                )
                if model_interrupted(detail):
                    raise Paused("model_interrupted_review_required")
                if (
                    result["assessment"].get("checks", {}).get("response_schema")
                    is False
                ):
                    # The evaluator returns before extracting model identity when
                    # canonical replay fails. Missing identity in that early result
                    # is not evidence that the provider ran a different model.
                    raise Paused("report_validation_failed")
                if (
                    result["assessment"].get("checks", {}).get("expected_model")
                    is False
                ):
                    raise Paused("returned_model_does_not_match")
            except RequestFailed as error:
                save_new(
                    folder / "outcome.json",
                    {
                        "status": "transport_uncertain",
                        "passed": False,
                        "reason": error.reason,
                        "http_status": error.status,
                    },
                )
                raise Paused("request_failed_reconcile_before_continuing") from None
        event["allowance"] = allowance
    except Paused as error:
        event.update(status="paused", reason=str(error))
    except (ValueError, KeyError, TypeError, AttributeError):
        event.update(status="paused", reason="invalid_response_schema")
    finally:
        event["elapsed_seconds"] = round(time.monotonic() - started, 2)
        save_new(campaign / "batches" / (str(uuid4()) + ".json"), event)
    return event


def validate_structure_download(download, metadata):
    """Check real bytes, hash and atom count; phase identity still needs
    review."""
    import gemmi

    content = base64.b64decode(download["base64"], validate=True)
    expected = metadata.get("sha256")
    if (
        not content
        or len(content) > 2 * 1024**2
        or not re.fullmatch(r"[a-f0-9]{64}", expected or "")
        or digest(content) != expected
        or download["sha256"] != expected
        or "chemical/x-cif" not in download["content_type"]
    ):
        raise Paused("structure_bytes_or_hash_invalid")
    document = gemmi.cif.read_string(content.decode("utf-8"))
    small = gemmi.make_small_structure_from_block(document.sole_block())
    if not small.sites or len(small.sites) != metadata.get("n_sites"):
        raise Paused("structure_atom_count_invalid")
    return {
        "sha256": expected,
        "bytes": len(content),
        "sites": len(small.sites),
        "representation": metadata.get("representation"),
        "derived": metadata.get("derived"),
        "phase_match_review": "pending",
    }


def audit_structures(args, *, api=None):
    """At most two exact report-owned records, without model calls or
    guessed IDs."""
    manifest = load(args.campaign / "manifest.json")
    resource_guard(args.campaign, manifest)
    api = api or LocalAPI(args.server)
    api.deadline = time.monotonic() + 300
    global_pending_guard(api)
    inspected = 0
    for detail_path in sorted(args.campaign.glob("model-*/case-*/*detail.json")):
        detail = load(detail_path)
        if not detail.get("reports"):
            continue
        report = detail["reports"][-1]
        prefix = (
            "/api/chats/"
            + quote(detail["chat"]["id"], safe="")
            + "/reports/"
            + quote(report["id"], safe="")
            + "/structures"
        )
        inventory_file = detail_path.parent / "structure-inventory.json"
        inventory = api.call(prefix)
        if not inventory_file.exists():
            save_new(inventory_file, inventory)
        for row in inventory.get("structures", []):
            identity = row["material_id"]
            result_path = (
                detail_path.parent
                / "structures"
                / (digest(identity.encode()) + ".json")
            )
            if result_path.exists():
                continue
            resource_guard(args.campaign, manifest)
            result = {
                "material_id": identity,
                "source": row.get("source_name"),
                "status": row.get("status"),
            }
            if row.get("status") in {"ready", "not_loaded"}:
                try:
                    endpoint = prefix + "/" + quote(identity, safe="")
                    metadata = api.call(endpoint, {}, timeout=90)
                    if (
                        metadata.get("material_id") != identity
                        or metadata.get("download_url") != endpoint + "/download"
                    ):
                        raise Paused("structure_identity_invalid")
                    download = api.call(endpoint + "/download", download=True)
                    result.update(
                        validate_structure_download(download, metadata),
                        status="download_verified",
                    )
                except RequestFailed as error:
                    result.update(
                        status="source_or_transport_unavailable",
                        http_status=error.status,
                    )
                except (Paused, ValueError, KeyError, RuntimeError):
                    result.update(status="download_validation_failed")
                inspected += 1
            save_new(result_path, result)
            if inspected >= 2:
                return {"status": "structure_batch_complete", "attempted": inspected}
    return {"status": "structure_batch_complete", "attempted": inspected}


def main():
    if sys.argv[1:] == ["_request"]:
        request_worker()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init", help="Freeze a campaign; makes no API requests")
    init.add_argument("--campaign", type=Path, required=True)
    init.add_argument("--prompt-set", type=Path, required=True)
    init.add_argument("--prompt-sha256")
    init.add_argument("--model", action="append", required=True)
    init.add_argument("--case", action="append")
    init.add_argument("--runtime-revision", required=True)
    init.add_argument("--project-prefix", required=True)
    init.add_argument("--ends-at", default=DEFAULT_END)
    init.add_argument("--holdout", action="store_true")
    init.add_argument("--protocol-frozen", action="store_true")
    run = sub.add_parser(
        "run", help="Submit a bounded batch; may consume account usage"
    )
    run.add_argument("--campaign", type=Path, required=True)
    run.add_argument("--server", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--batch-size", type=int, default=2)
    run.add_argument("--reviewed-interruption", action="append", default=[])
    structures = sub.add_parser(
        "structures", help="Audit up to two eligible downloads; no model calls"
    )
    structures.add_argument("--campaign", type=Path, required=True)
    structures.add_argument("--server", required=True)
    args = parser.parse_args()
    try:
        with campaign_lock():
            result = (
                initialize(args)
                if args.action == "init"
                else (
                    audit_structures(args)
                    if args.action == "structures"
                    else run_batch(args)
                )
            )
        print(json.dumps(result), flush=True)
        if result.get("status") == "paused":
            raise SystemExit(2)
    except Paused as error:
        print(json.dumps({"status": "paused", "reason": str(error)}), flush=True)
        raise SystemExit(2) from None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print(
            json.dumps({"status": "paused", "reason": "invalid_local_state"}),
            flush=True,
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
