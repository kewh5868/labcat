"""Credential tests use synthetic secrets and isolated files only."""

import json
import os

import pytest
from cryptography.fernet import Fernet

from labcat.connections import DEFAULT_PROFILE, validate_profile
from labcat.credentials import ConnectionError, CredentialVault, read_private_file

SECRET = "synthetic-only-credential"
PASSPHRASE = "synthetic vault passphrase"


@pytest.fixture(autouse=True)
def isolated_keys(monkeypatch):
    monkeypatch.delenv("LABCAT_VAULT_KEY", raising=False)
    monkeypatch.delenv("LABCAT_VAULT_KEY_FILE", raising=False)


def test_session_credentials_do_not_persist(tmp_path):
    path = tmp_path / "vault.json"
    vault = CredentialVault(path)
    vault.update({"openai": SECRET}, [], "session")
    assert vault.get("openai") == SECRET
    assert not path.exists()
    assert CredentialVault(path).get("openai") is None


def test_passphrase_ciphertext_restart_lock_and_forget(tmp_path):
    path = tmp_path / "vault.json"
    vault = CredentialVault(path)
    vault.create(PASSPHRASE)
    vault.update({"openai": SECRET}, [], "encrypted")
    raw = path.read_bytes()
    assert SECRET.encode() not in raw and PASSPHRASE.encode() not in raw
    if os.name == "posix":
        assert path.stat().st_mode & 0o077 == 0
    reopened = CredentialVault(path)
    assert reopened.status()["locked"]
    assert reopened.get("openai") is None
    with pytest.raises(ConnectionError):
        reopened.unlock("wrong synthetic passphrase")
    assert reopened.get("openai") is None
    reopened.unlock(PASSPHRASE)
    assert reopened.get("openai") == SECRET
    reopened.update({"kimi": SECRET}, [], "session")
    reopened.lock()
    assert reopened.get("openai") is None and reopened.get("kimi") is None
    reopened.unlock(PASSPHRASE)
    reopened.update({}, ["openai"], "encrypted")
    reopened.lock()
    reopened.unlock(PASSPHRASE)
    assert reopened.get("openai") is None


def test_tampered_ciphertext_stays_locked_without_overwriting(tmp_path):
    path = tmp_path / "vault.json"
    vault = CredentialVault(path)
    vault.create(PASSPHRASE)
    vault.update({"openai": SECRET}, [], "encrypted")
    document = json.loads(path.read_text())
    document["token"] = "tampered"
    path.write_text(json.dumps(document))
    before = path.read_bytes()
    reopened = CredentialVault(path)
    with pytest.raises(ConnectionError):
        reopened.unlock(PASSPHRASE)
    assert reopened.get("openai") is None
    assert path.read_bytes() == before


def test_external_key_is_separate_from_saved_ciphertext(tmp_path, monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setenv("LABCAT_VAULT_KEY", key.decode())
    path = tmp_path / "vault.json"
    vault = CredentialVault(path)
    vault.update({"openai": SECRET}, [], "encrypted")
    assert key not in path.read_bytes() and SECRET.encode() not in path.read_bytes()
    assert CredentialVault(path).get("openai") == SECRET
    monkeypatch.setenv("LABCAT_VAULT_KEY", Fernet.generate_key().decode())
    assert CredentialVault(path).get("openai") is None


def test_symlinked_storage_is_rejected(tmp_path):
    target = tmp_path / "target"
    target.write_text("private fixture")
    linked = tmp_path / "linked"
    linked.symlink_to(target)
    with pytest.raises(ConnectionError):
        read_private_file(linked)
    vault = CredentialVault(linked)
    with pytest.raises(ConnectionError):
        vault.reset()
    assert target.read_text() == "private fixture"


@pytest.mark.parametrize(
    "change",
    [
        {"allow_paid_inference": "yes"},
        {"provider": "unapproved"},
        {"ollama_url": "http://169.254.169.254:11434"},
        {"provider": "ollama", "model": "cloud-model"},
        {"allow_paid_inference": True},
        {"model": "has spaces"},
    ],
)
def test_profiles_reject_unapproved_routes_and_implicit_consent(change):
    with pytest.raises(ConnectionError):
        validate_profile({**DEFAULT_PROFILE, **change})


def test_encrypted_write_requires_unlocked_vault(tmp_path):
    path = tmp_path / "vault.json"
    vault = CredentialVault(path)
    with pytest.raises(ConnectionError):
        vault.update({"openai": SECRET}, [], "encrypted")
    assert not path.exists()
