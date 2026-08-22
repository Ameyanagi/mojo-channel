from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_conda_runtime", ROOT / "scripts" / "validate_conda_runtime.py"
)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def make_conda_artifact(
    path: Path,
    dependencies: object = None,
    *,
    index_bytes: bytes | None = None,
    index_name: str = "info/index.json",
    index_type: bytes = tarfile.REGTYPE,
    link_name: str = "",
    extra_members: tuple[tarfile.TarInfo, ...] = (),
) -> None:
    if index_bytes is None:
        index_bytes = json.dumps({"depends": dependencies}).encode()
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w") as archive:
        member = tarfile.TarInfo(index_name)
        member.type = index_type
        member.linkname = link_name
        if member.isfile():
            member.size = len(index_bytes)
            archive.addfile(member, io.BytesIO(index_bytes))
        else:
            archive.addfile(member)
        for extra_member in extra_members:
            archive.addfile(extra_member)
    compressed = subprocess.run(
        ["zstd", "--compress", "--quiet", "--stdout"],
        input=tar_bytes.getvalue(),
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    with zipfile.ZipFile(path, mode="w") as package:
        package.writestr("metadata.json", '{"conda_pkg_format_version": 2}')
        package.writestr("info-test-0.1.0-0.tar.zst", compressed)


class RuntimeMatchSpecTests(unittest.TestCase):
    def test_accepts_only_explicit_exact_version(self) -> None:
        validator.validate_runtime_dependency(
            {"depends": ["libc >=2.17", "mojo-compiler ==1.0.0"]}
        )

    def test_rejects_non_exact_version_forms(self) -> None:
        invalid_specs = [
            "mojo-compiler 1.0.0.*",
            "mojo-compiler 1.0.0",
            "mojo-compiler =1.0.0",
            "mojo-compiler >=1.0.0,<2.0a0",
            "mojo-compiler >=1.0.0",
            "mojo-compiler ==1.0.*",
            "mojo-compiler ==1.0.0 build_0",
        ]
        for match_spec in invalid_specs:
            with self.subTest(match_spec=match_spec):
                with self.assertRaisesRegex(
                    validator.ValidationError, "exact MatchSpec"
                ):
                    validator.validate_runtime_dependency({"depends": [match_spec]})

    def test_rejects_missing_and_duplicate_runtime_dependencies(self) -> None:
        for dependencies in (
            [],
            ["python >=3.14"],
            ["mojo-compiler ==1.0.0", "mojo-compiler ==1.0.0"],
        ):
            with self.subTest(dependencies=dependencies):
                with self.assertRaisesRegex(validator.ValidationError, "exactly one"):
                    validator.validate_runtime_dependency({"depends": dependencies})

    def test_rejects_malformed_dependencies(self) -> None:
        for dependencies in (None, "mojo-compiler ==1.0.0", [1]):
            with self.subTest(dependencies=dependencies):
                with self.assertRaisesRegex(
                    validator.ValidationError, "list of strings"
                ):
                    validator.validate_runtime_dependency({"depends": dependencies})

    def test_ignores_empty_non_runtime_dependency(self) -> None:
        validator.validate_runtime_dependency(
            {"depends": ["", "mojo-compiler ==1.0.0"]}
        )


class ArtifactTests(unittest.TestCase):
    def test_reads_info_index_from_conda_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact = Path(temporary_directory) / "valid.conda"
            make_conda_artifact(artifact, ["mojo-compiler ==1.0.0"])
            validator.validate_artifact(artifact)

    def test_rejects_wildcard_from_conda_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact = Path(temporary_directory) / "wildcard.conda"
            make_conda_artifact(artifact, ["mojo-compiler 1.0.0.*"])
            with self.assertRaisesRegex(validator.ValidationError, "exact MatchSpec"):
                validator.validate_artifact(artifact)

    def test_rejects_decompressed_info_over_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact = Path(temporary_directory) / "large.conda"
            make_conda_artifact(artifact, ["mojo-compiler ==1.0.0"])
            with mock.patch.object(validator, "MAX_ARCHIVE_MEMBER_BYTES", 1024):
                with self.assertRaisesRegex(
                    validator.ValidationError, "decompressed info archive"
                ):
                    validator.validate_artifact(artifact)

    def test_rejects_noncanonical_index_paths(self) -> None:
        invalid_names = (
            "./info/index.json",
            "../info/index.json",
            "/info/index.json",
            "info/../info/index.json",
            "info\\index.json",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            for index, invalid_name in enumerate(invalid_names):
                with self.subTest(invalid_name=invalid_name):
                    artifact = Path(temporary_directory) / f"unsafe-{index}.conda"
                    make_conda_artifact(
                        artifact,
                        ["mojo-compiler ==1.0.0"],
                        index_name=invalid_name,
                    )
                    with self.assertRaises(validator.ValidationError):
                        validator.validate_artifact(artifact)

    def test_rejects_index_link_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            for index_type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                with self.subTest(index_type=index_type):
                    artifact = Path(temporary_directory) / f"link-{index_type!r}.conda"
                    make_conda_artifact(
                        artifact,
                        index_name="info/index.json",
                        index_type=index_type,
                        link_name="info/other.json",
                    )
                    with self.assertRaisesRegex(
                        validator.ValidationError, "must not be a link"
                    ):
                        validator.validate_artifact(artifact)

    def test_rejects_link_alias_to_canonical_index(self) -> None:
        alias = tarfile.TarInfo("info/index-alias.json")
        alias.type = tarfile.SYMTYPE
        alias.linkname = "info/index.json"
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact = Path(temporary_directory) / "link-alias.conda"
            make_conda_artifact(
                artifact,
                ["mojo-compiler ==1.0.0"],
                extra_members=(alias,),
            )
            with self.assertRaisesRegex(
                validator.ValidationError, "must not be a link"
            ):
                validator.validate_artifact(artifact)

    def test_rejects_duplicate_json_keys(self) -> None:
        duplicate_depends = b'{"depends": [], "depends": ["mojo-compiler ==1.0.0"]}'
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact = Path(temporary_directory) / "duplicate-json-key.conda"
            make_conda_artifact(artifact, index_bytes=duplicate_depends)
            with self.assertRaisesRegex(validator.ValidationError, "duplicate key"):
                validator.validate_artifact(artifact)


if __name__ == "__main__":
    unittest.main()
