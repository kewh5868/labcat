"""Publication checks catch secrets in index and archive inputs without
disclosure."""

import hashlib
import importlib.util
import io
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "publication_privacy", ROOT / "scripts/check_secrets.py"
)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def generated_token():
    return hashlib.sha256(b"inert publication regression, never issued").hexdigest()


@pytest.mark.parametrize(
    "make_content",
    [
        lambda key: "sk-" + key,
        lambda key: "ghp_" + key,
        lambda key: 'API_KEY = "' + key[:32] + '"',
        lambda key: '{"materials_project": "' + key[:32] + '"}',
        lambda key: '{"refresh_token": "' + key + '"}',
        lambda key: "-----BEGIN " + "PRIVATE KEY-----\n" + key,
    ],
)
def test_detects_provider_and_unbranded_credential_literals(make_content):
    content = make_content(generated_token()).encode()
    assert checker.content_findings(content)


def test_public_hashes_and_visibly_inert_fixtures_remain_allowed():
    content = (
        'sha256 = "' + generated_token() + '"\n'
        'MD5 = "' + generated_token()[:32] + '"\n'
        'api_key = "synthetic-not-a-provider-key"\n'
        'current_passphrase = "SYNTHETIC_TEST_VALUE_ONLY"\n'
        'refresh_token = "invalid-refresh-token-for-offline-test"\n'
    ).encode()
    assert not checker.content_findings(content)


def test_chunk_boundary_does_not_hide_token():
    prefix = b"x" * (checker.CHUNK_BYTES - 2) + b"\n"
    assert checker.stream_findings(
        io.BytesIO(prefix + ("sk-" + generated_token()).encode())
    )


@pytest.mark.parametrize(
    "name",
    [
        "nested/credentials.json",
        "nested/secrets.yaml",
        "secrets.yml",
        "config/provider.key",
        "nested/vault-key",
        "nested/.secrets/key",
        "nested/.codex/auth.json",
        "nested/.local/archived-code.tar",
        "nested/WORKSPACE.CREDENTIALS.ENC.JSON",
        "nested/keys.p12",
        ".labcat-launch-mode",
        ".labcat-project-directory",
        ".labcat-install-source",
        "nested/deployment/.LABCAT-LAUNCH-MODE",
        "nested/deployment/.LABCAT-PROJECT-DIRECTORY",
        "nested/deployment/.LABCAT-INSTALL-SOURCE",
    ],
)
def test_private_paths_are_rejected_at_any_depth(name):
    assert checker.private_path(name)


def git(repo, *arguments):
    subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
    )


def test_index_scan_catches_staged_secret_when_worktree_is_clean(tmp_path, monkeypatch):
    git(tmp_path, "init")
    path = tmp_path / "fixture.py"
    token = "sk-" + generated_token()
    path.write_text('api_key = "' + token + '"\n')
    git(tmp_path, "add", path.name)
    path.write_text(
        'api_key = "synthetic-not-a-provider-key"\n'
        'current_passphrase = "SYNTHETIC_TEST_VALUE_ONLY"\n'
    )
    monkeypatch.chdir(tmp_path)
    assert not checker.check_repository()
    findings = checker.check_repository(staged=True)
    assert findings == [(path.name, {"provider API token", "credential literal"})]


def test_worktree_scan_includes_untracked_tests_and_redacts_output(
    tmp_path, monkeypatch, capsys
):
    git(tmp_path, "init")
    folder = tmp_path / "tests"
    folder.mkdir()
    path = folder / "test_sample.py"
    token = "sk-" + generated_token()
    path.write_text('api_key = "' + token + '"\n')
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        checker.main([])
    output = capsys.readouterr().out
    assert "tests/test_sample.py" in output
    assert "contents redacted" in output
    assert token not in output
    assert generated_token() not in output


def test_ignored_private_directory_is_absent_from_uploadable_scan(
    tmp_path, monkeypatch
):
    git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text(".local/\n")
    folder = tmp_path / ".local"
    folder.mkdir()
    (folder / "review.txt").write_text("sk-" + generated_token())
    monkeypatch.chdir(tmp_path)
    assert not checker.check_repository()


@pytest.mark.parametrize("name", ["secrets.yaml", "credentials.json", "private.key"])
def test_git_excludes_credential_files_without_requiring_existing_files(name):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "nested/" + name],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
