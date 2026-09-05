#!/usr/bin/env python3
"""Verify three downloaded native package artifacts without installing them."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from validate_conda_runtime import (
    ValidationError,
    _read_index,
    validate_runtime_dependency,
)

SUBDIRS = ("linux-64", "linux-aarch64", "osx-arm64")


def validate_transfer(root: Path, package: str, version: str) -> list[dict[str, str]]:
    if not re.fullmatch(r"(?:mojo-[a-z]+|yuragi)", package):
        raise ValidationError(f"invalid package name {package!r}")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValidationError(f"invalid package version {version!r}; expected X.Y.Z")
    if root.is_symlink() or not root.is_dir():
        raise ValidationError(f"download root must be a regular directory: {root}")
    actual_files: set[Path] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValidationError(
                f"downloaded artifacts must not contain symlinks: {path}"
            )
        if path.is_file():
            actual_files.add(path)
    expected_files: set[Path] = set()
    results = []
    for subdir in SUBDIRS:
        manifest = root / f"package-{subdir}.sha256"
        if not manifest.is_file() or manifest.is_symlink():
            raise ValidationError(f"missing regular checksum manifest: {manifest}")
        lines = manifest.read_text().splitlines()
        if len(lines) != 1:
            raise ValidationError(f"{manifest}: expected exactly one checksum record")
        match = re.fullmatch(
            r"([0-9a-f]{64})  (output/"
            + re.escape(subdir)
            + "/"
            + re.escape(package)
            + "-"
            + re.escape(version)
            + r"-[a-zA-Z0-9_]+\.conda)",
            lines[0],
        )
        if match is None:
            raise ValidationError(
                f"{manifest}: expected SHA-256 and canonical output/{subdir}/{package}-{version}-BUILD.conda path"
            )
        expected_digest, relative = match.groups()
        archive = root / relative
        if not archive.is_file() or archive.is_symlink():
            raise ValidationError(f"missing regular transferred archive: {relative}")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != expected_digest:
            raise ValidationError(f"transferred archive SHA-256 mismatch: {relative}")
        index = _read_index(archive)
        for key, expected in (
            ("name", package),
            ("version", version),
            ("subdir", subdir),
        ):
            if index.get(key) != expected:
                raise ValidationError(
                    f"transferred archive {key} mismatch: {relative}; expected {expected!r}, found {index.get(key)!r}"
                )
        if archive.name != f"{package}-{version}-{index.get('build')}.conda":
            raise ValidationError(
                f"transferred archive filename/build mismatch: {relative}"
            )
        validate_runtime_dependency(index)
        expected_files.update((manifest, archive))
        results.append({"path": relative, "sha256": digest, "subdir": subdir})
    if actual_files != expected_files:
        raise ValidationError(
            f"unexpected downloaded files: {sorted(str(p.relative_to(root)) for p in actual_files - expected_files)}"
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--package", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        results = validate_transfer(args.root, args.package, args.version)
    except (OSError, UnicodeError, ValidationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"verified_transfers": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
