"""Package a verified Docker archive and an explicit list of host
install files."""

import argparse
import hashlib
import re
import stat
import tempfile
import tomllib
import zipfile
from pathlib import Path

HOST_FILES = (
    "labcat.sh",
    "Start Labcat.command",
    "labcat.cmd",
    "labcat.ps1",
    "compose.yaml",
    "README.md",
    "LICENSE.rst",
    "docs/architecture.md",
    "docs/design-note.pdf",
    "docs/aws.md",
    "docs/deployment.md",
    "docs/developer-mode.md",
    "docs/evaluation.md",
    "docs/evaluation-results.json",
    "docs/onboarding.md",
    "docs/plan.md",
    "docs/projects.md",
    "docs/providers.md",
    "docs/goose.md",
    "docs/goose-standalone.md",
    "third_party/README.md",
    "third_party/GOOSE-LICENSE",
    "third_party/CODEX-LICENSE",
    "third_party/CODEX-NOTICE",
    "third_party/JSMOL-LICENSE",
    "third_party/JSMOL-NOTICE",
    "docs/scientific-sources.md",
    "docs/ranking.md",
    "docs/research-safeguards.md",
    "docs/structures.md",
    "docs/jsmol-source.md",
    "docs/scaffolding.md",
    "docs/validation.md",
    "docs/ui-layouts.md",
    "desktop/README.md",
)
EXECUTABLE_FILES = {"labcat.sh", "Start Labcat.command"}
DESKTOP_LAUNCHER_FILES = ("labcat.sh", "labcat.ps1", "compose.yaml")
ARCHIVE_NAME = re.compile(
    r"labcat-(?P<version>[A-Za-z0-9][A-Za-z0-9.+_-]*)"
    r"-linux-(?P<arch>amd64|arm64)\.tar"
)
CHUNK_SIZE = 1024 * 1024
DESKTOP_NAMES = {
    "macos": "Labcat.app",
    "windows": "Labcat.exe",
    "linux": "labcat-desktop",
}


class BundleError(ValueError):
    """An input was missing, unsafe, or inconsistent with the selected
    image."""


def require_regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise BundleError(f"Required regular file is missing or is a symlink: {path}")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_expected_digest(archive: Path, checksum: Path) -> str:
    require_regular_file(checksum)
    lines = checksum.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        raise BundleError("Checksum file must contain exactly one SHA-256 entry.")
    match = re.fullmatch(r"([a-fA-F0-9]{64})[ \t]+\*?(.+)", lines[0])
    if match is None or match.group(2) != archive.name:
        raise BundleError("Checksum file must name the selected archive exactly.")
    return match.group(1).lower()


def zip_entry(
    name: str,
    executable: bool = False,
    *,
    mode: int | None = None,
    directory: bool = False,
) -> zipfile.ZipInfo:
    # Stable metadata avoids inheriting host permissions or private path names.
    entry = zipfile.ZipInfo(name + "/" if directory else name)
    entry.create_system = 3
    permissions = mode if mode is not None else (0o755 if executable else 0o644)
    entry.external_attr = (
        (stat.S_IFDIR if directory else stat.S_IFREG) | permissions
    ) << 16
    if directory:
        entry.external_attr |= 0x10
    entry.compress_type = zipfile.ZIP_DEFLATED
    return entry


def add_file(
    bundle: zipfile.ZipFile,
    path: Path,
    name: str,
    *,
    executable: bool = False,
    mode: int | None = None,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        with bundle.open(
            zip_entry(name, executable, mode=mode), "w", force_zip64=True
        ) as target:
            for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
                target.write(chunk)
                digest.update(chunk)
    return digest.hexdigest()


def require_no_symlink_path(path: Path) -> None:
    if ".." in path.parts:
        raise BundleError("Desktop input must not contain parent traversal ('..').")
    for component in (path.absolute(), *path.absolute().parents):
        if component.is_symlink():
            raise BundleError(f"Desktop input must not use symlinks: {component}")


def desktop_entries(
    desktop_app: Path | None, host: str | None
) -> list[tuple[str, Path, int, bool]]:
    """Collect only the explicitly selected native file or safe macOS
    app tree."""
    if desktop_app is None and host is None:
        return []
    if desktop_app is None or host is None:
        raise BundleError("--desktop-app and --host must be supplied together.")
    if host not in DESKTOP_NAMES:
        raise BundleError("Desktop host must be macos, windows, or linux.")
    if desktop_app.name != DESKTOP_NAMES[host]:
        raise BundleError(f"Expected desktop input named {DESKTOP_NAMES[host]}.")
    require_no_symlink_path(desktop_app)
    if host == "macos":
        if not desktop_app.is_dir():
            raise BundleError("macos desktop input must be an .app directory.")
    else:
        require_regular_file(desktop_app)

    entries = []
    source_root = desktop_app.resolve()

    def collect(path: Path) -> None:
        require_no_symlink_path(path)
        if path.name == "compose.local.yaml":
            raise BundleError(
                "Build a clean desktop app without private deployment overrides."
            )
        if not path.resolve().is_relative_to(source_root):
            raise BundleError("Desktop input resolves outside the selected app.")
        # Backslashes can become path separators on a different extraction host.
        if any(char in path.name for char in "\\:") or any(
            ord(char) < 32 or ord(char) == 127 for char in path.name
        ):
            raise BundleError("Desktop input contains an unsafe archive filename.")
        details = path.lstat()
        directory = stat.S_ISDIR(details.st_mode)
        if not directory and not stat.S_ISREG(details.st_mode):
            raise BundleError(
                "Desktop input may contain only regular files/directories."
            )
        relative = path.relative_to(desktop_app.parent).as_posix()
        entries.append((relative, path, details.st_mode & 0o777, directory))
        if directory:
            for child in sorted(path.iterdir()):
                collect(child)

    collect(desktop_app)
    return entries


def build_install_bundle(
    archive: Path,
    output_dir: Path | None = None,
    *,
    project_root: Path | None = None,
    desktop_app: Path | None = None,
    host: str | None = None,
) -> tuple[Path, Path]:
    """Verify inputs, create the ZIP atomically, and write its SHA-256
    sidecar."""
    root = (project_root or Path(__file__).resolve().parents[1]).resolve()
    require_regular_file(archive)
    match = ARCHIVE_NAME.fullmatch(archive.name)
    if match is None:
        raise BundleError("Expected labcat-VERSION-linux-{amd64,arm64}.tar.")
    project_version = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    if match.group("version") != project_version:
        raise BundleError("Image archive version does not match pyproject.toml.")
    native_files = desktop_entries(desktop_app, host)

    source_files = []
    for name in HOST_FILES:
        path = root / name
        require_regular_file(path)
        if not path.resolve().is_relative_to(root):
            raise BundleError(f"Bundle input resolves outside the project: {name}")
        source_files.append((name, path))

    checksum = archive.with_suffix(".tar.sha256")
    expected = read_expected_digest(archive, checksum)
    if file_digest(archive) != expected:
        raise BundleError("Image archive SHA-256 does not match its checksum file.")

    destination = output_dir if output_dir is not None else archive.parent
    if desktop_app is not None and desktop_app.is_dir():
        if destination.resolve().is_relative_to(desktop_app.resolve()):
            raise BundleError("Bundle output must be outside the selected desktop app.")
    destination.mkdir(parents=True, exist_ok=True)
    prefix = (
        f"labcat-{project_version}-{host}-{match.group('arch')}"
        if native_files
        else archive.stem
    )
    output = destination / f"{prefix}.zip"
    with tempfile.NamedTemporaryFile(
        prefix=f".{prefix}-", suffix=".tmp", dir=destination, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w", allowZip64=True) as bundle:
            copied_digest = add_file(bundle, archive, f"{prefix}/{archive.name}")
            if copied_digest != expected:
                raise BundleError("Image archive changed while the bundle was built.")
            bundle.writestr(
                zip_entry(f"{prefix}/{checksum.name}"),
                f"{expected}  {archive.name}\n",
            )
            for name, path in source_files:
                add_file(
                    bundle,
                    path,
                    f"{prefix}/{name}",
                    executable=name in EXECUTABLE_FILES,
                )
            if host in {"windows", "linux"}:
                # Standalone binaries need the same fixed resources bundled
                # inside a macOS .app; never copy adjacent build directories.
                sources = dict(source_files)
                for name in DESKTOP_LAUNCHER_FILES:
                    add_file(
                        bundle,
                        sources[name],
                        f"{prefix}/desktop-bin/launcher/{name}",
                        executable=name in EXECUTABLE_FILES,
                    )
            for name, path, mode, directory in native_files:
                require_no_symlink_path(path)
                target = f"{prefix}/desktop-bin/{name}"
                if directory:
                    if not path.is_dir():
                        raise BundleError("Desktop directory changed during packaging.")
                    bundle.writestr(zip_entry(target, mode=mode, directory=True), b"")
                else:
                    require_regular_file(path)
                    add_file(bundle, path, target, mode=mode)
        temporary_path.replace(output)
    finally:
        temporary_path.unlink(missing_ok=True)

    output_checksum = output.with_suffix(".zip.sha256")
    output_checksum.write_text(
        f"{file_digest(output)}  {output.name}\n", encoding="utf-8"
    )
    return output, output_checksum


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bundle a verified image archive with host launchers."
    )
    parser.add_argument("archive", type=Path, help="Existing Docker .tar archive")
    parser.add_argument(
        "--output-dir", type=Path, help="Defaults to the archive folder"
    )
    parser.add_argument(
        "--desktop-app",
        type=Path,
        help="Optional native binary or macOS .app directory",
    )
    parser.add_argument(
        "--host", choices=tuple(DESKTOP_NAMES), help="Required with --desktop-app"
    )
    args = parser.parse_args(argv)
    try:
        output, checksum = build_install_bundle(
            args.archive, args.output_dir, desktop_app=args.desktop_app, host=args.host
        )
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(f"Install bundle: {output}")
    print(f"Bundle checksum: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
