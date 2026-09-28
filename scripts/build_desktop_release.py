"""Package a clean native shell for installation without host build
tools."""

import argparse
import tarfile
import tempfile
import zipfile
from pathlib import Path

from build_install_bundle import add_file, desktop_entries, file_digest

TARGETS = {
    "aarch64-apple-darwin": "macos",
    "x86_64-apple-darwin": "macos",
    "x86_64-pc-windows-msvc": "windows",
    "x86_64-unknown-linux-gnu": "linux",
}


def package_native(target: str, app: Path, output: Path) -> Path:
    """Use the existing allowlisted native tree validator before
    archiving."""
    host = TARGETS[target]
    entries = desktop_entries(app, host)
    output.mkdir(parents=True, exist_ok=True)
    suffix = ".zip" if host == "windows" else ".tar.gz"
    destination = output / f"Labcat-{target}{suffix}"
    with tempfile.NamedTemporaryFile(dir=output, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        if host == "windows":
            with zipfile.ZipFile(temporary, "w") as archive:
                for name, path, mode, _ in entries:
                    add_file(archive, path, name, mode=mode)
        else:
            with tarfile.open(temporary, "w:gz") as archive:
                for name, path, mode, directory in entries:
                    info = tarfile.TarInfo(name)
                    info.mode = mode
                    info.mtime = 0
                    info.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
                    if directory:
                        archive.addfile(info)
                    else:
                        info.size = path.stat().st_size
                        with path.open("rb") as stream:
                            archive.addfile(info, stream)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    destination.with_name(destination.name + ".sha256").write_text(
        f"{file_digest(destination)}  {destination.name}\n", encoding="utf-8"
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(package_native(args.target, args.app, args.output))


if __name__ == "__main__":
    main()
