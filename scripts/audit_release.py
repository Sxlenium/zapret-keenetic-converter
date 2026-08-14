"""Fail a release build when common personal or secret data is present."""

from __future__ import annotations

import argparse
import ipaddress
import re
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    "",
    ".bat",
    ".cmd",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
PATTERNS = {
    "Windows user profile path": re.compile(
        r"(?i)[a-z]:[\\/](?:users|documents and settings)[\\/][^\\/\s\"']+"
    ),
    "Unix user home path": re.compile(r"(?<![\w/])/home/[a-z_][a-z0-9_-]+", re.IGNORECASE),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "credential-bearing URL": re.compile(r"https?://[^\s/:@]+:[^\s/@]+@", re.IGNORECASE),
}
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
BINARY_HOME_MARKERS = (
    b":\\users\\",
    b":/users/",
    b"/home/",
    ":\\users\\".encode("utf-16le"),
    ":/users/".encode("utf-16le"),
    "/home/".encode("utf-16le"),
)


def release_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def scan(path: Path) -> list[str]:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings = [name for name, pattern in PATTERNS.items() if pattern.search(text)]
    for match in IPV4.finditer(text):
        try:
            address = ipaddress.ip_address(match.group())
        except ValueError:
            continue
        if address.is_global:
            findings.append(f"public IPv4 address: {address}")
    return findings


def scan_artifact_bytes(data: bytes) -> list[str]:
    lowered = data.lower()
    return ["embedded user home path"] if any(marker in lowered for marker in BINARY_HOME_MARKERS) else []


def scan_artifacts(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        for finding in scan_artifact_bytes(path.read_bytes()):
            findings.append(f"{path.relative_to(root)}: {finding}")
        if path.suffix.lower() != ".zip":
            continue
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                member = Path(name)
                if member.is_absolute() or ".." in member.parts:
                    findings.append(f"{path.name}: unsafe archive path: {name}")
                    continue
                if name.endswith("/"):
                    continue
                for finding in scan_artifact_bytes(archive.read(name)):
                    findings.append(f"{path.name}/{name}: {finding}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    findings: list[str] = []
    for path in release_files():
        relative = path.relative_to(ROOT)
        for finding in scan(path):
            findings.append(f"{relative}: {finding}")
    if args.artifacts:
        findings.extend(scan_artifacts(args.artifacts.resolve()))
    if findings:
        print("Release privacy audit failed:")
        print("\n".join(f"- {finding}" for finding in findings))
        return 1
    print("Release privacy audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
