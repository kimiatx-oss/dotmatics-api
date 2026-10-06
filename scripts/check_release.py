"""Scan an export tree or wheel/sdist for private references and high-confidence secrets."""

import argparse
import re
import sys
import tarfile
import zipfile
from pathlib import Path

IGNORE = {
    ".git",
    ".venv",
    "build",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}
REFERENCES = re.compile(
    r"https?://[A-Za-z0-9.-]+\.dotmatics\.net|"
    r"python\.pkg\.dev|inventory_openapi\.json",
    re.IGNORECASE,
)
SECRETS = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b|"
    r"\bgithub_pat_[A-Za-z0-9_]{40,}\b|"
    r'"type"\s*:\s*"service_account"|'
    r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b"
)
ALLOW = {
    "LICENSE": {"Copyright (c) 2026, Kimia Therapeutics"},
    "README.md": {
        "Shared by Kimia Therapeutics as a community reference and starter-code release."
    },
}


def files(target):
    if target.is_dir():
        for path in sorted(target.rglob("*")):
            relative = path.relative_to(target)
            if any(
                part in IGNORE or part.endswith(".egg-info") for part in relative.parts
            ):
                continue
            if path.is_symlink():
                raise ValueError(f"Symlinks are not permitted in exports: {relative}")
            if path.is_file():
                yield str(relative), path.read_bytes()
    elif zipfile.is_zipfile(target):
        with zipfile.ZipFile(target) as archive:
            for name in archive.namelist():
                if not name.endswith("/"):
                    yield name, archive.read(name)
    elif tarfile.is_tarfile(target):
        with tarfile.open(target) as archive:
            for member in archive.getmembers():
                if member.isfile():
                    with archive.extractfile(member) as handle:
                        yield member.name, handle.read()
                elif member.issym() or member.islnk():
                    raise ValueError("Archive symlinks are not permitted")
    else:
        yield target.name, target.read_bytes()


def approved(name, line):
    if line in ALLOW.get(name, set()):
        return True
    # SPDX package metadata and archive LICENSE paths reproduce approved attribution.
    if name.endswith(("/licenses/LICENSE", "/LICENSE")) and line in ALLOW["LICENSE"]:
        return True
    if name.endswith(("METADATA", "PKG-INFO")):
        return (
            line in ALLOW["README.md"]
            or line == "License: Copyright (c) 2026, Kimia Therapeutics"
        )
    if name.endswith("/README.md") and line in ALLOW["README.md"]:
        return True
    return False


def scan(target):
    failures = []
    for name, content in files(target):
        scanner = name == "scripts/check_release.py" or name.endswith(
            "/scripts/check_release.py"
        )
        if any(
            part.endswith((".db", ".sqlite", ".sqlite3", ".pem"))
            for part in Path(name).parts
        ):
            failures.append(f"{name}: prohibited artifact type")
        try:
            body = content.decode("utf-8")
        except UnicodeDecodeError:
            failures.append(
                f"{name}: binary asset requires an explicit review/allowlist"
            )
            continue
        for number, line in enumerate(body.splitlines(), 1):
            if (
                SECRETS.search(line)
                or REFERENCES.search(line)
                and not scanner
                and not approved(name, line)
            ):
                # Print locations only; never echo possible secrets or private data.
                failures.append(
                    f"{name}:{number}: prohibited reference or secret pattern"
                )
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="*", type=Path)
    args = parser.parse_args()
    targets = args.targets or [Path(__file__).resolve().parents[1]]
    failures = [
        f"{target}: {failure}" for target in targets for failure in scan(target)
    ]
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        raise SystemExit(1)
    print(f"Disclosure and secret-pattern checks passed for {len(targets)} target(s)")


if __name__ == "__main__":
    main()
