#!/usr/bin/env python3
"""Validate that .conda artifacts pin the stable Mojo runtime exactly."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, BinaryIO


MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024
DECOMPRESSION_TIMEOUT_SECONDS = 30
STREAM_CHUNK_BYTES = 64 * 1024


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


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _decompress_info(compressed_info: bytes, artifact: Path) -> BinaryIO:
    """Stream zstd output into a temporary file with hard size and time bounds."""
    zstd = shutil.which("zstd")
    if zstd is None:
        raise ValidationError("zstd is required to inspect .conda artifacts")

    output_file = tempfile.TemporaryFile()
    with tempfile.TemporaryFile() as input_file, tempfile.TemporaryFile() as error_file:
        input_file.write(compressed_info)
        input_file.seek(0)
        process = subprocess.Popen(
            [zstd, "--decompress", "--quiet", "--stdout"],
            stdin=input_file,
            stdout=subprocess.PIPE,
            stderr=error_file,
        )
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + DECOMPRESSION_TIMEOUT_SECONDS
        output_size = 0

        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValidationError(
                        f"decompressing {artifact} info archive timed out after "
                        f"{DECOMPRESSION_TIMEOUT_SECONDS} seconds"
                    )
                for key, _events in selector.select(timeout=min(remaining, 0.5)):
                    chunk = os.read(key.fd, STREAM_CHUNK_BYTES)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output_size += len(chunk)
                    if output_size > MAX_ARCHIVE_MEMBER_BYTES:
                        raise ValidationError(
                            f"{artifact} decompressed info archive is unexpectedly large"
                        )
                    output_file.write(chunk)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValidationError(
                    f"decompressing {artifact} info archive timed out after "
                    f"{DECOMPRESSION_TIMEOUT_SECONDS} seconds"
                )
            try:
                return_code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as error:
                raise ValidationError(
                    f"decompressing {artifact} info archive timed out after "
                    f"{DECOMPRESSION_TIMEOUT_SECONDS} seconds"
                ) from error
            if return_code != 0:
                error_file.seek(0)
                detail = error_file.read(8192).decode("utf-8", errors="replace").strip()
                raise ValidationError(
                    f"cannot decompress {artifact} info archive: {detail}"
                )
        except BaseException:
            _stop_process(process)
            output_file.close()
            raise
        finally:
            selector.close()
            process.stdout.close()

    output_file.seek(0)
    return output_file


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValidationError(f"info/index.json contains duplicate key {key!r}")
        parsed[key] = value
    return parsed


def _validate_tar_path(path: str, description: str, artifact: Path) -> None:
    if (
        path.startswith("/")
        or "\\" in path
        or any(component in {".", ".."} for component in path.split("/"))
    ):
        raise ValidationError(f"{artifact} contains unsafe {description} path {path!r}")


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

    try:
        with _decompress_info(compressed_info, artifact) as decompressed_info:
            with tarfile.open(fileobj=decompressed_info, mode="r:") as info_tar:
                members = info_tar.getmembers()
                for member in members:
                    _validate_tar_path(member.name, "tar member", artifact)
                    if member.issym() or member.islnk():
                        _validate_tar_path(member.linkname, "tar link target", artifact)
                        if (
                            member.name == "info/index.json"
                            or member.linkname == "info/index.json"
                        ):
                            raise ValidationError(
                                f"{artifact} info/index.json must not be a link"
                            )

                index_members = [
                    member for member in members if member.name == "info/index.json"
                ]
                if len(index_members) != 1 or not index_members[0].isfile():
                    raise ValidationError(
                        f"{artifact} must contain exactly one regular "
                        "info/index.json member"
                    )
                index_file = info_tar.extractfile(index_members[0])
                if index_file is None:
                    raise ValidationError(f"cannot read {artifact} info/index.json")
                parsed = json.load(index_file, object_pairs_hook=_reject_duplicate_keys)
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
