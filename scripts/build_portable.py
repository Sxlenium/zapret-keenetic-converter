"""Create release assets without embedding host filesystem paths."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_tree(archive: zipfile.ZipFile, source: Path, archive_root: str) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_file():
            relative = path.relative_to(source).as_posix()
            archive.write(path, f"{archive_root}/{relative}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    executable = args.exe.resolve()
    if not executable.is_file():
        parser.error(f"executable not found: {executable}")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    release_exe = output / "ZapretKeeneticConverter.exe"
    shutil.copy2(executable, release_exe)

    archive_name = f"ZapretKeeneticConverter-v{args.version}-windows-x64.zip"
    archive_path = output / archive_name
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary) / "ZapretKeeneticConverter"
        staging.mkdir()
        shutil.copy2(release_exe, staging / release_exe.name)
        shutil.copy2(ROOT / "README.md", staging / "README.md")
        shutil.copy2(ROOT / "LICENSE", staging / "LICENSE")
        shutil.copytree(ROOT / "docs", staging / "docs")
        (staging / "ИНСТРУКЦИЯ.txt").write_text(
            (ROOT / "ИНСТРУКЦИЯ.txt").read_text(encoding="utf-8"),
            encoding="utf-8-sig",
            newline="\r\n",
        )
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            add_tree(archive, staging, staging.name)

    checksums = output / "SHA256SUMS.txt"
    checksums.write_text(
        f"{sha256(release_exe)}  {release_exe.name}\n"
        f"{sha256(archive_path)}  {archive_path.name}\n",
        encoding="ascii",
        newline="\n",
    )
    print(archive_path)
    print(checksums)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
