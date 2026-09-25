"""Smoke argument/branch checks use no Docker, OAuth or network."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "smoke_container_auth_test",
    Path(__file__).parents[1] / "scripts" / "smoke_container.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize("argv", [[], ["--workspace"], ["--platform", "linux/arm64"]])
def test_existing_smoke_options_keep_real_auth_default(argv):
    assert MODULE.parse_args(argv).skip_real_auth is False


def test_unattended_option_preserves_all_other_selected_checks():
    args = MODULE.parse_args(
        [
            "--image",
            "example:test",
            "--platform",
            "linux/arm64",
            "--workspace",
            "--skip-real-auth",
        ]
    )
    assert args.skip_real_auth is True
    assert args.workspace is True
    assert args.image == "example:test" and args.platform == "linux/arm64"


def test_skipped_real_auth_never_executes_probe(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Skipped auth must not call Docker or a provider.")

    monkeypatch.setattr(MODULE, "command", forbidden)
    monkeypatch.setattr(MODULE, "urlopen", forbidden)
    MODULE.check_real_browser_auth("test-owned-container", skip_real_auth=True)
    output = capsys.readouterr().out
    assert "SKIPPED" in output and "--skip-real-auth" in output
    assert "start/poll/cancel" in output
    assert "no provider sign-in flow initiated by this check" in output


def test_default_probe_still_exercises_start_poll_and_cancel(monkeypatch, capsys):
    calls = []

    def fake_command(*args):
        calls.append(args)
        return "Synthetic auth probe result; no actual execution."

    monkeypatch.setattr(MODULE, "command", fake_command)
    MODULE.check_real_browser_auth("test-owned-container")
    assert len(calls) == 1
    assert calls[0][:4] == ("exec", "test-owned-container", "python", "-c")
    code = calls[0][4]
    assert "'/auth/start'" in code and "'/auth/poll'" in code
    assert "finally:" in code and "'/auth/cancel'" in code
    assert "if not (ready and cancelled)" in code
    assert "Synthetic auth probe result" in capsys.readouterr().out


def test_default_auth_failure_is_not_silently_skipped(monkeypatch):
    def failed(*args):
        raise RuntimeError("Synthetic probe failure")

    monkeypatch.setattr(MODULE, "command", failed)
    with pytest.raises(RuntimeError, match="Synthetic probe failure"):
        MODULE.check_real_browser_auth("test-owned-container")
