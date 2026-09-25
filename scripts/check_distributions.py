"""Check the exact wheel/sdist pair without extracting archive contents.

Pass two explicit archive paths and --built-after a file created before
the build when freshness is required. With no paths, check the
wheel/sdist files in dist/.
"""

import argparse
import re
import stat
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

METADATA_LIMIT = 1024 * 1024
REQUIRED_SOURCE_SUPPORT = (
    "scripts/materials_prompt_matrix.json",
    "scripts/holdout_prompts.json",
    "frontend/tests/reportLayoutChecks.js",
)


def normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def check_names(names: list[str]) -> None:
    forbidden = {
        "LOCAL_BRIEF.md",
        ".DS_Store",
        ".local",
        ".repo-snapshots",
        ".git",
        ".venv",
        "runs",
        "site.local.toml",
        "compose.local.yaml",
    }
    seen = set()
    for name in names:
        parts = name.removesuffix("/").split("/")
        if (
            not name
            or "\\" in name
            or "\x00" in name
            or re.match(r"^[A-Za-z]:", name)
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise SystemExit(f"Unsafe distribution member path: {name!r}")
        canonical = "/".join(parts)
        if canonical in seen:
            raise SystemExit(f"Duplicate distribution member: {name}")
        seen.add(canonical)
        if (
            forbidden.intersection(parts)
            or any(part.startswith(".env") for part in parts)
            or any(
                part.endswith(
                    (
                        ".sqlite",
                        ".sqlite3",
                        ".connections.json",
                        ".setup.json",
                        ".credentials.enc.json",
                        ".agent-usage.json",
                    )
                )
                or any(suffix in part for suffix in (".sqlite-", ".sqlite3-"))
                for part in parts
            )
        ):
            raise SystemExit(f"Private file included in distribution: {name}")
        if PurePosixPath(name).name in {"auth.json", "tokens.json"}:
            raise SystemExit(f"Authentication cache included in distribution: {name}")


def check_metadata(content: bytes, name: str, version: str) -> None:
    if len(content) > METADATA_LIMIT:
        raise SystemExit("Distribution metadata exceeds the inspection size limit.")
    metadata = BytesParser().parsebytes(content, headersonly=True)
    names = metadata.get_all("Name", [])
    versions = metadata.get_all("Version", [])
    if (
        len(names) != 1
        or normalized_name(names[0]) != normalized_name(name)
        or versions != [version]
    ):
        raise SystemExit("Distribution metadata does not match project name/version.")


def check_wheel(archive: Path, name: str, version: str) -> None:
    fields = archive.name.removesuffix(".whl").split("-")
    if (
        len(fields) not in {5, 6}
        or fields[:2] != [normalized_name(name), version]
        or not all(fields)
    ):
        raise SystemExit(
            f"Wheel filename does not match project name/version: {archive}"
        )
    metadata_path = f"{normalized_name(name)}-{version}.dist-info/METADATA"
    with zipfile.ZipFile(archive) as wheel:
        members = wheel.infolist()
        check_names([member.filename for member in members])
        for member in members:
            mode = stat.S_IFMT(member.external_attr >> 16)
            if (
                mode not in {0, stat.S_IFREG, stat.S_IFDIR}
                or (mode == stat.S_IFDIR and not member.is_dir())
                or (mode == stat.S_IFREG and member.is_dir())
            ):
                raise SystemExit(f"Unsupported wheel member type: {member.filename}")
        files = {member.filename: member for member in members if not member.is_dir()}
        if "labcat/static/index.html" not in files:
            raise SystemExit("Wheel is missing the built React interface.")
        metadata_names = {
            path for path in files if path.endswith(".dist-info/METADATA")
        }
        if metadata_names != {metadata_path}:
            raise SystemExit("Wheel is missing the expected, unique project metadata.")
        if files[metadata_path].file_size > METADATA_LIMIT:
            raise SystemExit("Distribution metadata exceeds the inspection size limit.")
        with wheel.open(metadata_path) as stream:
            check_metadata(stream.read(METADATA_LIMIT + 1), name, version)


def check_sdist(archive: Path, name: str, version: str) -> None:
    root = archive.name.removesuffix(".tar.gz")
    if root != f"{normalized_name(name)}-{version}":
        raise SystemExit(
            f"Source filename does not match project name/version: {archive}"
        )
    with tarfile.open(archive, mode="r:gz") as source:
        members = source.getmembers()
        check_names([member.name for member in members])
        for member in members:
            if not (member.isfile() or member.isdir()):
                raise SystemExit(f"Unsupported source member type: {member.name}")
            if member.name.split("/", 1)[0] != root:
                raise SystemExit(
                    f"Source member is outside the project root: {member.name}"
                )
        metadata_path = f"{root}/PKG-INFO"
        files = {member.name: member for member in members if member.isfile()}
        if metadata_path not in files:
            raise SystemExit("Source archive is missing the project metadata.")
        missing_data = [
            path for path in REQUIRED_SOURCE_SUPPORT if f"{root}/{path}" not in files
        ]
        if missing_data:
            raise SystemExit(
                "Source archive is missing required test/evaluation support: "
                + ", ".join(missing_data)
            )
        if files[metadata_path].size > METADATA_LIMIT:
            raise SystemExit("Distribution metadata exceeds the inspection size limit.")
        stream = source.extractfile(files[metadata_path])
        if stream is None:
            raise SystemExit("Source archive metadata is not a regular file.")
        with stream:
            check_metadata(stream.read(METADATA_LIMIT + 1), name, version)


def check_distributions(
    archives: list[Path], project_file: Path, built_after: Path | None = None
) -> None:
    wheels = [path for path in archives if path.name.endswith(".whl")]
    sources = [path for path in archives if path.name.endswith(".tar.gz")]
    if len(archives) != 2 or len(wheels) != 1 or len(sources) != 1:
        raise SystemExit("Provide exactly one wheel and one source distribution.")
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))["project"]
    name, version = project.get("name"), project.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise SystemExit("Project must declare a static name and version.")
    earliest = built_after.stat().st_mtime_ns if built_after is not None else None
    for archive in archives:
        if archive.is_symlink() or not archive.is_file():
            raise SystemExit(f"Distribution must be a regular file: {archive}")
        if earliest is not None and archive.stat().st_mtime_ns < earliest:
            raise SystemExit(f"Distribution predates the build marker: {archive}")
    try:
        check_wheel(wheels[0], name, version)
        check_sdist(sources[0], name, version)
    except (OSError, EOFError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise SystemExit(f"Cannot inspect distribution: {error}") from error


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="*", type=Path)
    parser.add_argument(
        "--built-after", type=Path, help="File created immediately before this build"
    )
    args = parser.parse_args(argv)
    archives = args.archives or [
        *Path("dist").glob("*.whl"),
        *Path("dist").glob("*.tar.gz"),
    ]
    check_distributions(archives, Path("pyproject.toml"), args.built_after)
    print(
        "Distribution pair checked: project identity and private-file exclusions pass."
    )


if __name__ == "__main__":
    main()
