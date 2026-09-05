#!/usr/bin/env python3
"""Install one exact hosted package on its native platform and run its smoke test."""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

CHANNEL = "https://ameyanagi.github.io/mojo-channel"
PACKAGES = ("mojo-kumihan", "mojo-sen", "mojo-mojotui", "mojo-yomi")
NATIVE = {
    ("Linux", "x86_64"): "linux-64",
    ("Linux", "aarch64"): "linux-aarch64",
    ("Darwin", "arm64"): "osx-arm64",
}


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]} {args[1]} failed: {result.stderr.strip()}")
    return result.stdout


def validate_resolved_package(
    packages: list[dict],
    expected: dict[str, dict],
    package: str,
    version: str,
    subdir: str,
) -> dict:
    """Require one exact installed package and a known native archive with its digest."""
    matches = [record for record in packages if record.get("name") == package]
    if len(matches) != 1 or matches[0].get("version") != version:
        raise ValueError(f"exact consumer package mismatch: {matches}")
    resolved = matches[0]
    expected_urls = {
        f"{CHANNEL}/{subdir}/{filename}": record.get("sha256")
        for filename, record in expected.items()
    }
    url = resolved.get("url")
    digest = resolved.get("sha256")
    if (
        not isinstance(url, str)
        or url not in expected_urls
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or expected_urls[url] != digest
    ):
        raise ValueError(
            f"consumer archive URL/hash does not match hosted index: {resolved}"
        )
    return resolved


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", choices=PACKAGES)
    parser.add_argument("version")
    parser.add_argument("subdir", choices=tuple(NATIVE.values()))
    parser.add_argument("smoke", type=Path)
    return parser


def main() -> None:
    parser = argument_parser()
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version):
        parser.error("version must be X.Y.Z")
    if NATIVE.get((platform.system(), platform.machine())) != args.subdir:
        parser.error(f"refusing foreign-platform installation: {args.subdir}")
    if run("pixi", "--version").strip() != "pixi 0.76.2":
        parser.error("consumer verification requires pixi 0.76.2")
    with urllib.request.urlopen(
        f"{CHANNEL}/{args.subdir}/repodata.json", timeout=30
    ) as response:
        records = json.load(response)["packages.conda"]
    expected = {
        name: record
        for name, record in records.items()
        if record["name"] == args.package and record["version"] == args.version
    }
    if not expected:
        raise ValueError(
            f"hosted package absent: {args.package}=={args.version} ({args.subdir})"
        )
    with tempfile.TemporaryDirectory(prefix="mojo-published-consumer-") as directory:
        consumer = Path(directory)
        shutil.copyfile(args.smoke, consumer / "smoke.mojo")
        print(
            run(
                "pixi",
                "init",
                str(consumer),
                "--platform",
                args.subdir,
                "--channel",
                CHANNEL,
                "--channel",
                "https://conda.modular.com/max",
                "--channel",
                "conda-forge",
            )
        )
        print(
            run(
                "pixi",
                "add",
                "--manifest-path",
                str(consumer),
                f"{args.package}=={args.version}",
            )
        )
        packages = json.loads(
            run(
                "pixi",
                "list",
                "--manifest-path",
                str(consumer),
                "--json",
                "--frozen",
            )
        )
        resolved = validate_resolved_package(
            packages, expected, args.package, args.version, args.subdir
        )
        print(run("pixi", "run", "--locked", "mojo", "run", "smoke.mojo", cwd=consumer))
        print(
            json.dumps(
                {
                    "package": args.package,
                    "version": args.version,
                    "subdir": args.subdir,
                    "url": resolved["url"],
                    "sha256": resolved["sha256"],
                    "installed_smoke": "passed",
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
