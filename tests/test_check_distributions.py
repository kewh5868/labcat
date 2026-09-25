"""Distribution checks reject wrong, stale and unsafe archive pairs."""

import importlib.util
import io
import os
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_distributions.py"
SPEC = importlib.util.spec_from_file_location("check_distributions", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

NAME = "labcat"
VERSION = "0.1.0.dev0"
ROOT = f"{NAME}-{VERSION}"
METADATA = f"Metadata-Version: 2.4\nName: {NAME}\nVersion: {VERSION}\n\n".encode()


def write_wheel(path, *, metadata=METADATA, extra=None, index=True):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{ROOT}.dist-info/METADATA", metadata)
        if index:
            archive.writestr("labcat/static/index.html", "<html></html>")
        for name, content in extra or []:
            archive.writestr(name, content)


def write_source(path, *, metadata=METADATA, extra=None, omit_data=None):
    data = [
        (f"{ROOT}/{name}", b"[]\n")
        for name in (
            "scripts/materials_prompt_matrix.json",
            "scripts/holdout_prompts.json",
            "frontend/tests/reportLayoutChecks.js",
        )
        if name != omit_data
    ]
    with tarfile.open(path, "w:gz") as archive:
        for name, content in [(f"{ROOT}/PKG-INFO", metadata), *data, *(extra or [])]:
            info = name if isinstance(name, tarfile.TarInfo) else tarfile.TarInfo(name)
            if info.isfile():
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
            else:
                archive.addfile(info)


@pytest.fixture
def pair(tmp_path):
    project = tmp_path / "pyproject.toml"
    project.write_text(f'[project]\nname = "{NAME}"\nversion = "{VERSION}"\n')
    wheel = tmp_path / f"{ROOT}-py3-none-any.whl"
    source = tmp_path / f"{ROOT}.tar.gz"
    write_wheel(wheel)
    write_source(source)
    return project, wheel, source


def test_accepts_matching_pair_without_extracting(pair):
    project, wheel, source = pair
    checker.check_distributions([wheel, source], project)
    assert sorted(path.name for path in project.parent.iterdir()) == sorted(
        [project.name, wheel.name, source.name]
    )


@pytest.mark.parametrize("choice", ["empty", "wheel", "two_wheels", "extra_source"])
def test_requires_exactly_one_of_each_archive_type(pair, choice):
    project, wheel, source = pair
    archives = {
        "empty": [],
        "wheel": [wheel],
        "two_wheels": [wheel, wheel],
        "extra_source": [wheel, source, source],
    }[choice]
    with pytest.raises(SystemExit, match="exactly one wheel"):
        checker.check_distributions(archives, project)


@pytest.mark.parametrize("which", ["wheel", "source"])
@pytest.mark.parametrize("replacement", ["other-0.1.0.dev0", "labcat-0.0.9"])
def test_rejects_wrong_archive_identity(pair, which, replacement):
    project, wheel, source = pair
    original = wheel if which == "wheel" else source
    renamed = original.with_name(original.name.replace(ROOT, replacement))
    original.rename(renamed)
    archives = [renamed, source] if which == "wheel" else [wheel, renamed]
    with pytest.raises(SystemExit, match="filename does not match"):
        checker.check_distributions(archives, project)


@pytest.mark.parametrize("which", ["wheel", "source"])
@pytest.mark.parametrize(
    "metadata",
    [
        b"Name: other\nVersion: 0.1.0.dev0\n\n",
        b"Name: labcat\nVersion: 0.0.9\n\n",
        METADATA.replace(b"\n\n", b"\nName: labcat\n\n"),
        b"Metadata-Version: 2.4\n\n",
    ],
)
def test_rejects_wrong_or_ambiguous_metadata(pair, which, metadata):
    project, wheel, source = pair
    if which == "wheel":
        write_wheel(wheel, metadata=metadata)
    else:
        write_source(source, metadata=metadata)
    with pytest.raises(SystemExit, match="metadata does not match"):
        checker.check_distributions([wheel, source], project)


@pytest.mark.parametrize("which", ["wheel", "source"])
def test_rejects_oversized_metadata(pair, which):
    project, wheel, source = pair
    metadata = METADATA + b"x" * checker.METADATA_LIMIT
    if which == "wheel":
        write_wheel(wheel, metadata=metadata)
    else:
        write_source(source, metadata=metadata)
    with pytest.raises(SystemExit, match="size limit"):
        checker.check_distributions([wheel, source], project)


def test_rejects_missing_built_interface(pair):
    project, wheel, source = pair
    write_wheel(wheel, index=False)
    with pytest.raises(SystemExit, match="built React interface"):
        checker.check_distributions([wheel, source], project)


@pytest.mark.parametrize(
    "missing",
    [
        "scripts/materials_prompt_matrix.json",
        "scripts/holdout_prompts.json",
        "frontend/tests/reportLayoutChecks.js",
    ],
)
def test_rejects_missing_test_and_evaluation_support(pair, missing):
    project, wheel, source = pair
    write_source(source, omit_data=missing)
    with pytest.raises(
        SystemExit, match="missing required test/evaluation support"
    ) as error:
        checker.check_distributions([wheel, source], project)
    assert missing in str(error.value)


@pytest.mark.parametrize(
    "missing",
    [
        "scripts/materials_prompt_matrix.json",
        "scripts/holdout_prompts.json",
        "frontend/tests/reportLayoutChecks.js",
    ],
)
def test_directory_cannot_satisfy_required_test_and_evaluation_support(pair, missing):
    project, wheel, source = pair
    member = tarfile.TarInfo(f"{ROOT}/{missing}")
    member.type = tarfile.DIRTYPE
    write_source(source, omit_data=missing, extra=[(member, b"")])
    with pytest.raises(SystemExit, match="missing required test/evaluation support"):
        checker.check_distributions([wheel, source], project)


@pytest.mark.parametrize("which", ["wheel", "source"])
def test_checks_freshness_of_both_archives(pair, which):
    project, wheel, source = pair
    marker = project.parent / "build-start"
    marker.touch()
    cutoff = marker.stat().st_mtime_ns
    for archive in [wheel, source]:
        os.utime(archive, ns=(cutoff + 1_000_000_000, cutoff + 1_000_000_000))
    stale = wheel if which == "wheel" else source
    os.utime(stale, ns=(cutoff - 1_000_000_000, cutoff - 1_000_000_000))
    with pytest.raises(SystemExit, match="predates the build marker"):
        checker.check_distributions([wheel, source], project, marker)
    os.utime(stale, ns=(cutoff + 1_000_000_000, cutoff + 1_000_000_000))
    checker.check_distributions([wheel, source], project, marker)


@pytest.mark.parametrize("which", ["wheel", "source"])
@pytest.mark.parametrize(
    "member",
    [
        "nested/LOCAL_BRIEF.md",
        "nested/.DS_Store",
        "nested/.local/cache",
        "nested/.env.production",
        "nested/auth.json",
        "nested/private.sqlite3-wal",
        "../escape",
        "/absolute",
        "C:/absolute",
        "nested\\LOCAL_BRIEF.md",
        "nested//file",
    ],
)
def test_rejects_private_and_unsafe_members(pair, which, member):
    project, wheel, source = pair
    if which == "wheel":
        write_wheel(wheel, extra=[(member, b"private")])
    else:
        write_source(source, extra=[(member, b"private")])
    with pytest.raises(SystemExit, match="Private file|Authentication cache|Unsafe"):
        checker.check_distributions([wheel, source], project)


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_rejects_source_links_and_special_members(pair, kind):
    project, wheel, source = pair
    member = tarfile.TarInfo(f"{ROOT}/linked-file")
    member.type = kind
    member.linkname = "../../private"
    write_source(source, extra=[(member, b"")])
    with pytest.raises(SystemExit, match="Unsupported source member type"):
        checker.check_distributions([wheel, source], project)


def test_rejects_wheel_symlinks(pair):
    project, wheel, source = pair
    member = zipfile.ZipInfo("labcat/linked-file")
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    write_wheel(wheel, extra=[(member, b"../../private")])
    with pytest.raises(SystemExit, match="Unsupported wheel member type"):
        checker.check_distributions([wheel, source], project)


def test_rejects_duplicate_members(pair):
    project, wheel, source = pair
    write_source(source, extra=[(f"{ROOT}/PKG-INFO", METADATA)])
    with pytest.raises(SystemExit, match="Duplicate distribution member"):
        checker.check_distributions([wheel, source], project)


def test_rejects_source_members_outside_expected_root(pair):
    project, wheel, source = pair
    write_source(source, extra=[("unrelated/file", b"content")])
    with pytest.raises(SystemExit, match="outside the project root"):
        checker.check_distributions([wheel, source], project)


@pytest.mark.parametrize("which", ["wheel", "source"])
def test_corrupt_archive_fails_with_inspection_error(pair, which):
    project, wheel, source = pair
    (wheel if which == "wheel" else source).write_bytes(b"not an archive")
    with pytest.raises(SystemExit, match="Cannot inspect distribution"):
        checker.check_distributions([wheel, source], project)


def test_cli_accepts_explicit_pair_and_marker(pair, monkeypatch, capsys):
    project, wheel, source = pair
    monkeypatch.chdir(project.parent)
    marker = project.parent / "build-start"
    marker.touch()
    cutoff = min(wheel.stat().st_mtime_ns, source.stat().st_mtime_ns) - 1_000_000_000
    os.utime(marker, ns=(cutoff, cutoff))
    checker.main(["--built-after", str(marker), str(source), str(wheel)])
    assert "Distribution pair checked" in capsys.readouterr().out


def test_legacy_cli_checks_dist_and_rejects_extra_archives(pair, monkeypatch):
    project, wheel, source = pair
    monkeypatch.chdir(project.parent)
    dist = project.parent / "dist"
    dist.mkdir()
    wheel.rename(dist / wheel.name)
    source.rename(dist / source.name)
    checker.main([])
    (dist / "stale-0.0.1.tar.gz").touch()
    with pytest.raises(SystemExit, match="exactly one wheel"):
        checker.main([])
