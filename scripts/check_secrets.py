"""Reject credential files and recognizable secrets without printing
values.

By default inspect tracked and unignored working files. --staged
inspects all index blobs so a clean working copy cannot conceal a staged
secret. Pattern checks cannot identify every secret; keep credentials
outside the source checkout and use generated, visibly synthetic test
fixtures.
"""

import argparse
import math
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath

PRIVATE_NAMES = {
    "local_brief.md",
    ".local",
    ".repo-snapshots",
    ".git",
    ".venv",
    ".secrets",
    ".ssh",
    ".aws",
    ".codex",
    "runs",
    "site.local.toml",
    "compose.local.yaml",
    ".labcat-launch-mode",
    ".labcat-project-directory",
    ".labcat-install-source",
    "auth.json",
    "tokens.json",
    "credentials.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "vault-key",
    "vault.key",
    "deployment-secret",
}
PRIVATE_SUFFIXES = (
    ".connections.json",
    ".setup.json",
    ".credentials.enc.json",
    ".credentials.json",
    ".agent-usage.json",
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".sqlite",
    ".sqlite3",
    ".sqlite-journal",
    ".sqlite3-journal",
    ".sqlite-wal",
    ".sqlite3-wal",
    ".sqlite-shm",
    ".sqlite3-shm",
)
PATTERNS = {
    "provider API token": re.compile(
        rb"(?<![\w-])(?:sk-(?:proj-|svcacct-|ant-api\d{2}-)?"
        rb"[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}|"
        rb"xai-[A-Za-z0-9_-]{30,})(?![\w-])"
    ),
    "repository access token": re.compile(
        rb"(?<![\w-])(?:gh[pousr]_[A-Za-z0-9]{30,}|"
        rb"github_pat_[A-Za-z0-9_]{50,})(?![\w-])"
    ),
    "cloud access key": re.compile(
        rb"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"
    ),
    "private key": re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    "signed token": re.compile(
        rb"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    ),
    "messaging access token": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}"),
}
# A key with no branded prefix (including a Materials Project key) is checked
# when stored as a credential literal. Public checksums are not credentials.
LITERAL = re.compile(
    rb"(?ix)(?<![\w])(?:[\"']?(?:[a-z_]{0,64}(?:api[_-]?key|"
    rb"access[_-]?token|refresh[_-]?token|id[_-]?token|secret[_-]?key|"
    rb"secret[_-]?access[_-]?key|client[_-]?secret|vault[_-]?key|password|"
    rb"passphrase)|materials_project)[\"']?)\s*[:=]\s*"
    rb"([\"'])([A-Za-z0-9_+/=-]{20,512})\1"
)
CHUNK_BYTES = 1024 * 1024
OVERLAP_BYTES = 4096


def private_path(name: str) -> bool:
    parts = tuple(part.casefold() for part in PurePosixPath(name).parts)
    return any(
        part in PRIVATE_NAMES
        or part.endswith(PRIVATE_SUFFIXES)
        or (part.startswith(".env") and part != ".env.example")
        for part in parts
    )


def credential_literal(value: bytes) -> bool:
    counts = Counter(value)
    entropy = -sum(
        (count / len(value)) * math.log2(count / len(value))
        for count in counts.values()
    )
    if re.fullmatch(rb"[0-9a-fA-F]{24,128}", value):
        return entropy >= 3.0
    classes = sum(
        bool(re.search(pattern, value)) for pattern in (rb"[a-z]", rb"[A-Z]", rb"[0-9]")
    )
    return classes >= 2 and entropy >= 3.7


def content_findings(content: bytes) -> set[str]:
    findings = {name for name, pattern in PATTERNS.items() if pattern.search(content)}
    if any(credential_literal(match[2]) for match in LITERAL.finditer(content)):
        findings.add("credential literal")
    return findings


def stream_findings(stream) -> set[str]:
    findings = set()
    previous = b""
    while chunk := stream.read(CHUNK_BYTES):
        content = previous + chunk
        findings.update(content_findings(content))
        previous = content[-OVERLAP_BYTES:]
    return findings


def git_output(*arguments: str) -> bytes:
    result = subprocess.run(["git", *arguments], capture_output=True, check=False)
    if result.returncode:
        raise SystemExit("Cannot inspect repository files; no credential data printed.")
    return result.stdout


def check_repository(*, staged: bool = False) -> list[tuple[str, set[str]]]:
    findings = []
    if staged:
        entries = git_output("ls-files", "--stage", "-z").split(b"\x00")
    else:
        entries = git_output(
            "ls-files", "--cached", "--others", "--exclude-standard", "-z"
        ).split(b"\x00")
    for entry in entries:
        if not entry:
            continue
        if staged:
            metadata, raw_name = entry.split(b"\t", 1)
            mode, object_id, stage = metadata.split()
            if stage != b"0":
                raise SystemExit("Resolve index conflicts before checking publication.")
        else:
            raw_name = entry
        name = raw_name.decode("utf-8", errors="replace")
        reasons = set()
        if private_path(name):
            reasons.add("private credential/runtime path")
        if staged:
            if mode not in {b"100644", b"100755"}:
                reasons.add("unsupported index file type")
            else:
                reasons.update(
                    content_findings(git_output("cat-file", "blob", object_id.decode()))
                )
        else:
            path = Path(name)
            if path.is_symlink():
                reasons.add("symbolic link requires publication review")
            elif path.is_file():
                try:
                    with path.open("rb") as stream:
                        reasons.update(stream_findings(stream))
                except OSError:
                    reasons.add("file could not be inspected")
        if reasons:
            findings.append((name, reasons))
    return findings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--worktree", action="store_true")
    args = parser.parse_args(argv)
    findings = check_repository(staged=args.staged)
    if args.staged and args.worktree:
        findings.extend(check_repository())
    if findings:
        for name, reasons in findings:
            print(f"{name}: {', '.join(sorted(reasons))} (contents redacted)")
        raise SystemExit(1)
    print("Credential publication guard passed; recognizable patterns only.")


if __name__ == "__main__":
    main()
