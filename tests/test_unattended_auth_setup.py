"""Deployment preparation never replaces an unrelated volume or
configuration."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare_unattended_vault.py"
spec = importlib.util.spec_from_file_location("prepare_unattended_vault", SCRIPT)
prepare_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_module)


@pytest.mark.parametrize("volume", ["labcat_workspace-data", "other", "../key"])
def test_unattended_key_rejects_non_dedicated_volume(volume, tmp_path, monkeypatch):
    monkeypatch.setattr(
        prepare_module, "run", lambda *a, **kw: pytest.fail("Unexpected Docker call")
    )
    with pytest.raises(ValueError, match="dedicated"):
        prepare_module.prepare("test-image", volume, tmp_path / "override.json")


def test_unattended_key_rejects_existing_unowned_volume(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return "labcat-test-vault-key\n" if args[1] == "ls" else "{}"

    monkeypatch.setattr(prepare_module, "run", fake_run)
    with pytest.raises(ValueError, match="not a managed"):
        prepare_module.prepare(
            "test-image", "labcat-test-vault-key", tmp_path / "override.json"
        )
    assert len(calls) == 2
    assert not (tmp_path / "override.json").exists()


@pytest.mark.parametrize("volume", ["labcat-vault-key", "labcat-test-vault-key"])
def test_unattended_key_override_scopes_key_to_parent_and_is_idempotent(
    tmp_path, monkeypatch, volume
):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args[:2] == ["volume", "ls"]:
            return volume + "\n"
        if args[:2] == ["volume", "inspect"]:
            return '{"org.labcat.role":"deployment-vault-key"}'
        return "Deployment key ready; contents were not exported."

    monkeypatch.setattr(prepare_module, "run", fake_run)
    output = tmp_path / "override.json"
    expected = prepare_module.prepare("test-image", volume, output)
    before = output.read_bytes()
    assert prepare_module.prepare("test-image", volume, output) == expected
    assert output.read_bytes() == before
    value = json.loads(before)
    assert set(value["services"]) == {"labcat"}
    assert value["services"]["labcat"]["environment"] == {
        "LABCAT_VAULT_KEY_FILE": "/run/labcat-vault/key"
    }
    assert value["services"]["labcat"]["volumes"] == [f"{volume}:/run/labcat-vault:ro"]
    assert value["volumes"][volume]["external"] is True
    runs = [args for args, _ in calls if args[0] == "run"]
    assert len(runs) == 2
    for args in runs:
        assert args[args.index("--network") + 1] == "none"
        assert "--read-only" in args
        assert "--privileged" not in args
        assert args[args.index("--cap-drop") + 1] == "ALL"
