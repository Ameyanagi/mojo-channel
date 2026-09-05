#!/usr/bin/env python3
"""Read-only audit of every channel archive, index entry and provenance record."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from validate_conda_runtime import (
    ValidationError,
    _read_index,
    _reject_duplicate_keys,
    validate_runtime_dependency,
)

SUBDIRS = ("linux-64", "linux-aarch64", "osx-arm64", "noarch")
REPOSITORIES = frozenset(
    "akari hibana kagerou kumihan moji mojotui nagare nami nerai sen shuhafft yomi yuragi".split()
)


def read_json(text: str, description: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, ValidationError) as error:
        raise ValidationError(f"{description}: {error}") from error


def validate_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        len(path.parts) != 2
        or path.parts[0] not in SUBDIRS
        or path.suffix != ".conda"
        or str(path) != value
        or "\\" in value
    ):
        raise ValidationError(
            f"invalid archive path {value!r}; expected SUBDIR/FILE.conda"
        )


def read_ledger(text: str) -> dict[str, tuple[str, ...]]:
    entries: dict[str, tuple[str, ...]] = {}
    sources: dict[tuple[str, str], str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        fields = tuple(line.split("\t"))
        if len(fields) != 5 or any(not field for field in fields):
            raise ValidationError(
                f"ledger line {number}: expected five nonempty TSV fields"
            )
        path, digest, repository, tag, source = fields
        validate_path(path)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValidationError(f"ledger line {number}: invalid SHA-256 {digest!r}")
        if repository not in REPOSITORIES:
            raise ValidationError(
                f"ledger line {number}: unknown repository {repository!r}"
            )
        if (
            not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag)
            or tag == "v0.0.0"
        ):
            raise ValidationError(f"ledger line {number}: invalid release tag {tag!r}")
        if not re.fullmatch(r"[0-9a-f]{40}", source):
            raise ValidationError(
                f"ledger line {number}: invalid source commit {source!r}"
            )
        if path in entries:
            raise ValidationError(
                f"ledger line {number}: duplicate/conflicting path {path!r}"
            )
        key = (repository, tag)
        if key in sources and sources[key] != source:
            raise ValidationError(
                f"ledger line {number}: conflicting source for {repository} {tag}"
            )
        sources[key] = source
        entries[path] = fields
    return entries


def read_legacy(text: str) -> dict[str, dict[str, Any]]:
    data = read_json(text, "legacy-artifacts.json")
    if not isinstance(data, dict):
        raise ValidationError("legacy-artifacts.json must be an object")
    for path, record in data.items():
        validate_path(path)
        if not isinstance(record, dict) or set(record) != {"sha256", "index", "reason"}:
            raise ValidationError(f"legacy {path}: expected sha256, index and reason")
        if not isinstance(record["sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", record["sha256"]
        ):
            raise ValidationError(f"legacy {path}: invalid SHA-256")
        if (
            not isinstance(record["index"], dict)
            or not isinstance(record["reason"], str)
            or not record["reason"]
        ):
            raise ValidationError(
                f"legacy {path}: missing metadata or unsupported reason"
            )
    return data


def baseline_file(root: Path, revision: str, name: str) -> str | None:
    # An initial adoption baseline legitimately lacks the explicit legacy inventory.
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{revision}:{name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        probe = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{revision}^{{commit}}"],
            capture_output=True,
            check=False,
        )
        if probe.returncode:
            raise ValidationError(f"unknown baseline commit {revision!r}")
        if name == "legacy-artifacts.json":
            return None
        raise ValidationError(f"cannot read baseline {name}: {result.stderr.strip()}")
    return result.stdout


def validate_channel(root: Path, baseline_ref: str | None = None) -> dict[str, int]:
    ledger = read_ledger((root / "artifacts.tsv").read_text())
    legacy = read_legacy((root / "legacy-artifacts.json").read_text())
    if ledger.keys() & legacy.keys():
        raise ValidationError(
            "an archive cannot have both current and legacy provenance"
        )
    if baseline_ref:
        previous = read_ledger(baseline_file(root, baseline_ref, "artifacts.tsv") or "")
        for path, fields in previous.items():
            if ledger.get(path) != fields:
                raise ValidationError(
                    f"immutable ledger record changed or removed: {path}"
                )
        previous_legacy = baseline_file(root, baseline_ref, "legacy-artifacts.json")
        if previous_legacy is not None and legacy != read_legacy(previous_legacy):
            raise ValidationError("the frozen legacy inventory changed")
        if previous_legacy is None:
            # First adoption must freeze exactly the pre-ledger archive inventory.
            tree = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "ls-tree",
                    "-r",
                    "--name-only",
                    baseline_ref,
                    "--",
                    *SUBDIRS,
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.splitlines()
            expected_legacy = {
                path for path in tree if path.endswith(".conda")
            } - previous.keys()
            if legacy.keys() != expected_legacy:
                raise ValidationError(
                    "initial legacy inventory differs from baseline archives"
                )
            for path in expected_legacy:
                raw = subprocess.run(
                    ["git", "-C", str(root), "show", f"{baseline_ref}:{path}"],
                    capture_output=True,
                    check=True,
                ).stdout
                if hashlib.sha256(raw).hexdigest() != legacy[path]["sha256"]:
                    raise ValidationError(
                        f"initial legacy bytes differ from baseline: {path}"
                    )

    recorded = ledger.keys() | legacy.keys()
    actual = {
        str(p.relative_to(root))
        for subdir in SUBDIRS
        for p in (root / subdir).glob("*.conda")
    }
    if recorded != actual:
        raise ValidationError(
            f"archive inventory mismatch: missing={sorted(recorded - actual)}, "
            f"unrecorded={sorted(actual - recorded)}"
        )
    indexes: dict[str, dict[str, Any]] = {}
    for subdir in SUBDIRS:
        metadata = read_json(
            (root / subdir / "repodata.json").read_text(), f"{subdir}/repodata.json"
        )
        if not isinstance(metadata, dict) or not isinstance(
            metadata.get("packages.conda"), dict
        ):
            raise ValidationError(f"{subdir}: missing packages.conda mapping")
        if metadata.get("info", {}).get("subdir") != subdir:
            raise ValidationError(f"{subdir}: repodata info.subdir mismatch")
        if metadata.get("packages", {}):
            raise ValidationError(
                f"{subdir}: unsupported unrecorded .tar.bz2 artifacts"
            )
        indexes[subdir] = metadata["packages.conda"]
        expected = {
            PurePosixPath(p).name for p in recorded if p.startswith(subdir + "/")
        }
        if set(indexes[subdir]) != expected:
            raise ValidationError(f"{subdir}: repodata archive inventory mismatch")

    for path in sorted(recorded):
        artifact = root / path
        if artifact.is_symlink() or not artifact.is_file():
            raise ValidationError(f"archive must be a regular file: {path}")
        raw = artifact.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        expected_digest = ledger[path][1] if path in ledger else legacy[path]["sha256"]
        if digest != expected_digest:
            raise ValidationError(f"SHA-256 mismatch: {path}")
        index = _read_index(artifact)
        if path in ledger:
            _, _, repository, tag, _ = ledger[path]
            name = "yuragi" if repository == "yuragi" else f"mojo-{repository}"
            if index.get("name") != name or index.get("version") != tag[1:]:
                raise ValidationError(f"ledger/package identity mismatch: {path}")
            validate_runtime_dependency(index)
        elif index != legacy[path]["index"]:
            raise ValidationError(f"legacy metadata changed: {path}")
        subdir, filename = PurePosixPath(path).parts
        if index.get("subdir") != subdir:
            raise ValidationError(f"archive subdir mismatch: {path}")
        if (
            filename
            != f"{index.get('name')}-{index.get('version')}-{index.get('build')}.conda"
        ):
            raise ValidationError(f"archive filename/identity mismatch: {path}")
        repodata = indexes[subdir][filename]
        if not isinstance(repodata, dict):
            raise ValidationError(f"repodata entry must be an object: {path}")
        for key in ("name", "version", "subdir", "build", "build_number", "depends"):
            if repodata.get(key) != index.get(key):
                raise ValidationError(f"repodata {key} mismatch: {path}")
        if repodata.get("sha256") != digest or repodata.get("size") != len(raw):
            raise ValidationError(f"repodata hash/size mismatch: {path}")
        if repodata.get("md5") != hashlib.md5(raw, usedforsecurity=False).hexdigest():
            raise ValidationError(f"repodata md5 mismatch: {path}")
    return {
        "current": len(ledger),
        "unsupported_legacy": len(legacy),
        "total": len(recorded),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--baseline-ref")
    args = parser.parse_args()
    try:
        result = validate_channel(args.root, args.baseline_ref)
    except (OSError, UnicodeError, ValidationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
