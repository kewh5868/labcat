"""Offline runner mechanics only; fake responses never become scientific
evidence."""

import importlib.util
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/research_campaign.py"
spec = importlib.util.spec_from_file_location("research_campaign", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def args(tmp_path, **updates):
    value = SimpleNamespace(
        campaign=tmp_path / "campaign",
        prompt_set=tmp_path / "prompts.json",
        model=["test-model"],
        case=None,
        runtime_revision="TEST-ONLY-image",
        project_prefix="TEST ONLY",
        prompt_sha256=None,
        holdout=False,
        protocol_frozen=False,
        ends_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
    )
    for key, item in updates.items():
        setattr(value, key, item)
    return value


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "PENDING_ROOT", tmp_path / "pending")
    monkeypatch.setattr(runner, "fingerprint", lambda: "frozen")
    monkeypatch.setattr(
        runner.shutil,
        "disk_usage",
        lambda _: shutil._ntuple_diskusage(100 * runner.GIB, 0, 100 * runner.GIB),
    )
    definitions = {
        name: {
            "prompt": "TEST ONLY ordinary material request",
            "class": "polymers",
            "expectation": "TEST ONLY evaluate sources",
            "candidates_expected": True,
        }
        for name in ("first", "second", "third")
    }
    setup = args(tmp_path)
    setup.prompt_set.write_text(json.dumps({"cases": definitions}))
    result = runner.initialize(setup)
    assert result["status"] == "initialized_no_requests"
    evaluator = {
        "assess": lambda detail, _: {
            "passed": True,
            "model": "test-model",
            "provider": "chatgpt",
            "checks": {},
        }
    }
    monkeypatch.setattr(runner, "run_path", lambda _: evaluator)
    return SimpleNamespace(
        campaign=setup.campaign,
        server="http://127.0.0.1:8000",
        model="test-model",
        batch_size=2,
    )


class API:
    def __init__(
        self,
        *,
        research_error=None,
        detail=None,
        progress=None,
        quota=50,
        state="ready",
    ):
        self.base = "http://127.0.0.1:8000"
        self.calls = []
        self.research_error = research_error
        self.detail = detail or {"reports": [{"id": "TEST ONLY"}]}
        self.progress = progress or {"status": "running"}
        self.quota, self.state = quota, state
        self.chat_count = 0

    def call(self, path, body=None, **_):
        self.calls.append((path, body))
        if path.startswith("/api/connections/setup"):
            return {
                "can_research": self.state == "ready",
                "model": {
                    "status": self.state,
                    "provider": "chatgpt",
                    "model": "test-model",
                },
            }
        if path == "/api/connections/usage":
            return {"rate_limits": [{"primary": {"remaining_percent": self.quota}}]}
        if path == "/api/source-settings":
            return {"enabled": ["TEST ONLY public source"]}
        if path == "/api/projects":
            return {"id": "test-project"}
        if path.endswith("/draft-chat"):
            self.chat_count += 1
            return {"id": "test-chat-" + str(self.chat_count)}
        if path.endswith("/messages"):
            # Prove the journal exists before any potentially billable call.
            if self.research_error:
                raise self.research_error
            return self.detail
        if "/research-status" in path:
            return self.progress
        if path.startswith("/api/chats/"):
            return self.detail
        raise AssertionError(path)


def submissions(api):
    return [item for item in api.calls if item[0].endswith("/messages")]


def test_successful_batch_resumes_without_replaying(campaign):
    first = API()
    assert runner.run_batch(campaign, api=first)["submitted"] == 2
    assert len(submissions(first)) == 2
    second = API()
    assert runner.run_batch(campaign, api=second)["submitted"] == 1
    third = API()
    assert runner.run_batch(campaign, api=third)["submitted"] == 0
    assert submissions(third) == []
    assert len(list(campaign.campaign.glob("model-*/case-*/outcome.json"))) == 3


def test_timeout_intent_is_durable_and_failed_attempt_is_never_overwritten(campaign):
    api = API(research_error=runner.RequestFailed("request_deadline"))
    event = runner.run_batch(campaign, api=api)
    assert event["status"] == "paused" and len(submissions(api)) == 1
    folder = campaign.campaign / "model-1/case-001"
    original = (folder / "outcome.json").read_bytes()
    assert runner.load(folder / "intent.json")["run_id"]
    api2 = API(detail={"reports": [], "messages": []})
    event = runner.run_batch(campaign, api=api2)
    assert event["reason"] == "prior_submission_unresolved_no_resubmission"
    assert not submissions(api2)
    assert (folder / "outcome.json").read_bytes() == original
    api3 = API(progress={"status": "completed"})
    event = runner.run_batch(campaign, api=api3)
    assert event["reconciled"] == 1 and event["submitted"] == 2
    assert (folder / "reconciliation.json").exists()
    assert (folder / "outcome.json").read_bytes() == original


def test_interrupted_intent_before_response_does_not_duplicate(campaign):
    folder = campaign.campaign / "model-1/case-001"
    runner.save_new(
        folder / "intent.json",
        {
            "case": "first",
            "model": "test-model",
            "chat_id": "existing",
            "run_id": "run-1",
        },
    )
    api = API(detail={"reports": [], "messages": []}, progress={"status": "idle"})
    assert runner.run_batch(campaign, api=api)["status"] == "paused"
    assert not submissions(api)


@pytest.mark.parametrize(
    "state,quota,reason",
    [
        ("not_connected", 50, "sign_in_or_connection_action_required"),
        ("ready", 0, "provider_allowance_exhausted"),
    ],
)
def test_auth_and_quota_pause_before_project_or_inference(
    campaign, state, quota, reason
):
    api = API(state=state, quota=quota)
    assert runner.run_batch(campaign, api=api)["reason"] == reason
    assert not submissions(api)
    assert not any(path == "/api/projects" for path, _ in api.calls)


def test_unknown_allowance_is_not_invented():
    assert runner.allowance_remaining({"rate_limits": None}) is None
    assert (
        runner.allowance_remaining(
            {"rate_limits": [{"primary": {"remaining_percent": float("nan")}}]}
        )
        is None
    )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("low_disk", "low_disk_space"),
        ("changed", "implementation_changed_create_new_campaign"),
        ("large", "artifact_budget_reached"),
    ],
)
def test_resource_guards_make_no_calls(campaign, monkeypatch, mutation, reason):
    if mutation == "low_disk":
        monkeypatch.setattr(
            runner.shutil, "disk_usage", lambda _: SimpleNamespace(free=runner.GIB)
        )
    elif mutation == "changed":
        monkeypatch.setattr(runner, "fingerprint", lambda: "modified")
    else:
        monkeypatch.setattr(runner, "artifact_bytes", lambda _: 2 * runner.GIB)
    api = API()
    with pytest.raises(runner.Paused, match=reason):
        runner.run_batch(campaign, api=api)
    assert not api.calls


def test_frozen_prompts_detect_tampering(campaign):
    with (campaign.campaign / "prompts.json").open("a") as handle:
        handle.write(" ")
    with pytest.raises(runner.Paused, match="prompt_set_changed"):
        runner.run_batch(campaign, api=API())


def assert_private_permissions(path):
    if os.name == "nt":
        # Verify the actual Windows security descriptor, not DOS stat mode bits.
        script = (
            "$acl = Get-Acl -LiteralPath $env:LABCAT_TEST_ARTIFACT; "
            "$rules = @($acl.Access); "
            "@{ protected = $acl.AreAccessRulesProtected; "
            "count = $rules.Count; "
            "sid = $rules[0].IdentityReference.Translate("
            "[System.Security.Principal.SecurityIdentifier]).Value; "
            "rights = [int]$rules[0].FileSystemRights; "
            "type = [string]$rules[0].AccessControlType } | ConvertTo-Json"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env={**os.environ, "LABCAT_TEST_ARTIFACT": str(path)},
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        acl = json.loads(completed.stdout)
        assert acl == {
            "protected": True,
            "count": 1,
            "sid": "S-1-3-4",
            "rights": 2032127,
            "type": "Allow",
        }
    else:
        assert path.stat().st_mode & 0o777 == 0o600


def test_immutable_private_artifacts_redact_secrets(tmp_path):
    path = tmp_path / "result.json"
    runner.save_new(
        path,
        {
            "access_token": "secret",
            "text": "Bearer secret-value",
            "usage": {"total_tokens": 4},
        },
    )
    assert "secret-value" not in path.read_text()
    assert runner.load(path)["usage"]["total_tokens"] == 4
    assert_private_permissions(path)
    with pytest.raises(FileExistsError):
        runner.save_new(path, {"overwritten": True})


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8000",
        "http://example.com:8000",
        "http://127.0.0.1:8000/?key=secret",
        "http://user@127.0.0.1:8000",
        "http://127.0.0.1:8000/path",
        "http://localhost:8000",
    ],
)
def test_only_explicit_loopback_address_is_accepted(url):
    with pytest.raises(runner.Paused, match="invalid_local_address"):
        runner.local_base(url)


def test_holdout_not_opened_before_protocol_frozen(tmp_path):
    setup = args(tmp_path, holdout=True)
    with pytest.raises(runner.Paused, match="freeze_protocol_before_opening_holdout"):
        runner.initialize(setup)
    assert not setup.campaign.exists()


def test_wrong_selected_model_stops(campaign):
    campaign.model = "different-model"
    with pytest.raises(runner.Paused, match="model_not_in_frozen_campaign"):
        runner.run_batch(campaign, api=API())


def test_normal_submission_has_no_expectations_or_material_answers(campaign):
    api = API()
    runner.run_batch(campaign, api=api)
    for _, body in submissions(api):
        assert set(body) == {"content", "ranking_profile_id", "run_id"}
        assert body["ranking_profile_id"] == "infer"


def test_interruption_retains_report_and_pauses_until_explicit_review(campaign):
    detail = {"reports": [{"result": {"execution": {"model_interrupted": True}}}]}
    first = runner.run_batch(campaign, api=API(detail=detail))
    assert first["reason"] == "model_interrupted_review_required"
    assert first["submitted"] == 1
    later = API()
    assert (
        runner.run_batch(campaign, api=later)["reason"]
        == "model_interrupted_review_required"
    )
    assert not submissions(later)
    intent = runner.load(campaign.campaign / "model-1/case-001/intent.json")
    campaign.reviewed_interruption = [intent["run_id"]]
    assert runner.run_batch(campaign, api=API())["submitted"] == 2


def test_global_pending_blocks_a_new_campaign(campaign):
    runner.run_batch(
        campaign, api=API(research_error=runner.RequestFailed("request_deadline"))
    )
    api = API()
    with pytest.raises(runner.Paused, match="prior_submission_unresolved"):
        runner.global_pending_guard(api)
    assert not submissions(api)


def test_saved_report_does_not_allow_overlap_while_server_running(campaign):
    runner.run_batch(
        campaign, api=API(research_error=runner.RequestFailed("request_deadline"))
    )
    api = API()  # has a saved report, but progress is still running
    assert (
        runner.run_batch(campaign, api=api)["reason"]
        == "prior_submission_unresolved_no_resubmission"
    )
    assert not submissions(api)


def test_missing_report_model_is_an_unverified_comparison():
    evaluator = {"assess": lambda *_: {"passed": True, "model": None, "checks": {}}}
    value = runner.outcome({"reports": [{}]}, {}, "test-model", evaluator)
    assert value["assessment"]["passed"] is False
    assert value["assessment"]["checks"]["expected_model"] is False
    intake = runner.outcome({"reports": []}, {}, "test-model", evaluator)
    assert intake["assessment"]["passed"] is True


def test_report_validation_failure_is_not_a_model_mismatch():
    evaluator = {
        "assess": lambda *_: {
            "passed": False,
            "model": None,
            "checks": {"response_schema": False},
        }
    }
    value = runner.outcome({"reports": [{}]}, {}, "test-model", evaluator)
    assert value["assessment"]["passed"] is False
    assert value["assessment"]["checks"] == {"response_schema": False}


def test_failed_report_replay_pauses_before_another_submission(campaign, monkeypatch):
    monkeypatch.setattr(
        runner,
        "run_path",
        lambda _: {
            "assess": lambda *_: {
                "passed": False,
                "checks": {"response_schema": False},
            }
        },
    )
    api = API()
    result = runner.run_batch(campaign, api=api)
    assert result["reason"] == "report_validation_failed"
    assert result["status"] == "paused"
    assert len(submissions(api)) == 1
    saved = runner.load(campaign.campaign / "model-1/case-001/outcome.json")
    assert saved["assessment"]["passed"] is False
    assert saved["assessment"]["checks"] == {"response_schema": False}


def test_valid_structure_bytes_and_wrong_atom_count():
    import base64

    cif = (
        b"data_test\n_cell_length_a 4\n_cell_length_b 4\n_cell_length_c 4\n"
        b"_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\n"
        b"loop_\n_atom_site_label\n_atom_site_type_symbol\n_atom_site_fract_x\n"
        b"_atom_site_fract_y\n_atom_site_fract_z\nSi1 Si 0 0 0\n"
    )
    sha = runner.digest(cif)
    download = {
        "base64": base64.b64encode(cif).decode(),
        "sha256": sha,
        "content_type": "chemical/x-cif",
    }
    metadata = {"sha256": sha, "n_sites": 1, "derived": True}
    assert runner.validate_structure_download(download, metadata)["sites"] == 1
    with pytest.raises(runner.Paused, match="atom_count"):
        runner.validate_structure_download(download, {**metadata, "n_sites": 2})
    with pytest.raises(runner.Paused, match="bytes_or_hash"):
        runner.validate_structure_download(
            {**download, "content_type": "text/html"}, metadata
        )


def test_request_worker_uses_ephemeral_csrf_and_disables_proxies(monkeypatch, capsys):
    from io import BytesIO

    seen = []

    class Response(BytesIO):
        headers = {}

    class Opener:
        def open(self, request, **_):
            seen.append(request)
            if isinstance(request, str):
                assert request.endswith("/api/session")
                return Response(b'{"csrf_token":"TEST_ONLY_CSRF_VALUE"}')
            assert request.get_header("X-csrf-token") == "TEST_ONLY_CSRF_VALUE"
            return Response(b'{"can_research":true}')

    def opener(*handlers):
        assert any(
            isinstance(h, runner.ProxyHandler) and h.proxies == {} for h in handlers
        )
        assert any(isinstance(h, runner.HTTPCookieProcessor) for h in handlers)
        assert any(isinstance(h, runner.NoRedirects) for h in handlers)
        return Opener()

    supplied = {
        "base": "http://127.0.0.1:8000",
        "path": "/api/connections/setup/verify",
        "body": {},
    }
    monkeypatch.setattr(runner, "build_opener", opener)
    monkeypatch.setattr(
        runner.sys,
        "stdin",
        SimpleNamespace(buffer=BytesIO(json.dumps(supplied).encode())),
    )
    runner.request_worker()
    output = capsys.readouterr().out
    assert json.loads(output)["ok"] is True
    assert "TEST_ONLY_CSRF_VALUE" not in output
    assert len(seen) == 2


def test_malformed_research_payload_pauses_without_false_completion(campaign):
    class InvalidAPI(API):
        def call(self, path, body=None, **kwargs):
            if path.endswith("/messages"):
                return {"reports": ["not a report"]}
            return super().call(path, body, **kwargs)

    result = runner.run_batch(campaign, api=InvalidAPI())
    assert result["status"] == "paused"
    assert result["reason"] == "invalid_response_schema"
    assert result["submitted"] == 1


@pytest.mark.parametrize(
    "relative",
    [
        "src/labcat/default.toml",
        "src/labcat/science/data/mp_dielectric_snapshot.json",
        "src/labcat/science/data/nested/future_records.json",
    ],
)
def test_fingerprint_covers_bundled_configuration_and_scientific_data(
    tmp_path, monkeypatch, relative
):
    for name in (
        "scripts/evaluate_live_prompts.py",
        "scripts/research_campaign.py",
        "docs/materials-evaluation-rubric.md",
        "src/labcat/core.py",
        relative,
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("TEST ONLY initial content")
    monkeypatch.setattr(runner, "REPO", tmp_path)
    before = runner.fingerprint()
    (tmp_path / relative).write_text("TEST ONLY changed content")
    assert runner.fingerprint() != before


def test_permission_failure_leaves_no_artifact(tmp_path, monkeypatch):
    path = tmp_path / "result.json"

    def reject_permissions(_):
        raise OSError("TEST ONLY unsupported private permissions")

    monkeypatch.setattr(runner, "restrict_private_file", reject_permissions)
    with pytest.raises(runner.Paused, match="private_artifact_permissions_unavailable"):
        runner.save_new(path, {"private": "MUST NOT BE WRITTEN"})
    assert not path.exists()


def test_permissions_are_private_at_creation_before_content_open(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    original_fdopen = runner.os.fdopen
    observed = []

    def inspect_creation(descriptor, *args, **kwargs):
        assert_private_permissions(path)
        assert path.stat().st_size == 0
        observed.append(True)
        return original_fdopen(descriptor, *args, **kwargs)

    monkeypatch.setattr(runner.os, "fdopen", inspect_creation)
    runner.save_new(path, {"private": "TEST ONLY content"})
    assert observed == [True]
    assert runner.load(path)["private"] == "TEST ONLY content"
