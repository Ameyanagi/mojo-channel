#!/usr/bin/env python3
"""Validate that .conda artifacts pin the stable Mojo runtime exactly."""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any


MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024


class ValidationError(ValueError):
    """Raised when an artifact violates the publication contract."""


def _matchspec_name(match_spec: str) -> str | None:
    fields = match_spec.split(maxsplit=1)
    return fields[0] if fields else None


def validate_runtime_dependency(
    index: dict[str, Any], expected_version: str = "1.0.0"
) -> None:
    """Require one unambiguous, exact mojo-compiler version MatchSpec."""
    dependencies = index.get("depends")
    if not isinstance(dependencies, list) or not all(
        isinstance(dependency, str) for dependency in dependencies
    ):
        raise ValidationError("info/index.json 'depends' must be a list of strings")

    runtime_specs = [
        dependency
        for dependency in dependencies
        if _matchspec_name(dependency) == "mojo-compiler"
    ]
    if len(runtime_specs) != 1:
        raise ValidationError(
            "info/index.json must contain exactly one mojo-compiler dependency; "
            f"found {len(runtime_specs)}"
        )

    actual_fields = runtime_specs[0].split()
    expected_fields = ["mojo-compiler", f"=={expected_version}"]
    if actual_fields != expected_fields:
        raise ValidationError(
            "mojo-compiler must use the exact MatchSpec "
            f"'mojo-compiler =={expected_version}'; found {runtime_specs[0]!r}"
        )


def _read_index(artifact: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(artifact) as package:
            info_archives = [
                member
                for member in package.infolist()
                if not member.is_dir()
                and member.filename.startswith("info-")
                and member.filename.endswith(".tar.zst")
                and "/" not in member.filename
            ]
            if len(info_archives) != 1:
                raise ValidationError(
                    f"{artifact} must contain exactly one info-*.tar.zst member; "
                    f"found {len(info_archives)}"
                )
            if info_archives[0].file_size > MAX_ARCHIVE_MEMBER_BYTES:
                raise ValidationError(f"{artifact} info archive is unexpectedly large")
            compressed_info = package.read(info_archives[0])
    except (OSError, zipfile.BadZipFile) as error:
        raise ValidationError(
            f"cannot read {artifact} as a .conda archive: {error}"
        ) from error

    zstd = shutil.which("zstd")
    if zstd is None:
        raise ValidationError("zstd is required to inspect .conda artifacts")
    try:
        decompressed_info = subprocess.run(
            [zstd, "--decompress", "--quiet", "--stdout"],
            input=compressed_info,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise ValidationError(
            f"cannot decompress {artifact} info archive: {detail}"
        ) from error
    if len(decompressed_info) > MAX_ARCHIVE_MEMBER_BYTES:
        raise ValidationError(
            f"{artifact} decompressed info archive is unexpectedly large"
        )

    try:
        with tarfile.open(fileobj=io.BytesIO(decompressed_info), mode="r:") as info_tar:
            index_members = [
                member
                for member in info_tar.getmembers()
                if member.isfile() and member.name.lstrip("./") == "info/index.json"
            ]
            if len(index_members) != 1:
                raise ValidationError(
                    f"{artifact} must contain exactly one info/index.json; "
                    f"found {len(index_members)}"
                )
            index_file = info_tar.extractfile(index_members[0])
            if index_file is None:
                raise ValidationError(f"cannot read {artifact} info/index.json")
            parsed = json.load(index_file)
    except (
        OSError,
        tarfile.TarError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise ValidationError(
            f"cannot parse {artifact} info/index.json: {error}"
        ) from error

    if not isinstance(parsed, dict):
        raise ValidationError(f"{artifact} info/index.json must be a JSON object")
    return parsed


def validate_artifact(artifact: Path, expected_version: str = "1.0.0") -> None:
    if artifact.suffix != ".conda" or not artifact.is_file():
        raise ValidationError(f"artifact is not a readable .conda file: {artifact}")
    validate_runtime_dependency(_read_index(artifact), expected_version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path, nargs="+")
    parser.add_argument("--expected-version", default="1.0.0")
    arguments = parser.parse_args(argv)

    try:
        for artifact in arguments.artifacts:
            validate_artifact(artifact, arguments.expected_version)
            print(
                f"Validated exact mojo-compiler =={arguments.expected_version}: "
                f"{artifact}"
            )
    except ValidationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
