from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from test_validate_conda_runtime import make_conda_artifact

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_transferred_packages import SUBDIRS, ValidationError, validate_transfer  # noqa: E402


class TransferTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.package = "mojo-kumihan"
        self.version = "0.1.0"
        for subdir in SUBDIRS:
            self.build(subdir)

    def build(self, platform_subdir: str, **overrides: object) -> None:
        index = {
            "name": self.package,
            "version": self.version,
            "subdir": platform_subdir,
            "build": "test_0",
            "depends": ["mojo-compiler ==1.0.0"],
        }
        index.update(overrides)
        relative = (
            f"output/{platform_subdir}/{self.package}-{self.version}-test_0.conda"
        )
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        make_conda_artifact(path, index_bytes=json.dumps(index).encode())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.root / f"package-{platform_subdir}.sha256").write_text(
            f"{digest}  {relative}\n"
        )

    def test_three_native_transfers_are_read_only(self) -> None:
        original = {
            path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        }
        result = validate_transfer(self.root, self.package, self.version)
        self.assertEqual([row["subdir"] for row in result], list(SUBDIRS))
        self.assertEqual(original, {path: path.read_bytes() for path in original})

    def test_missing_platform_manifest(self) -> None:
        (self.root / "package-linux-aarch64.sha256").unlink()
        with self.assertRaisesRegex(ValidationError, "checksum manifest"):
            validate_transfer(self.root, self.package, self.version)

    def test_missing_archive(self) -> None:
        next((self.root / "output/osx-arm64").glob("*.conda")).unlink()
        with self.assertRaisesRegex(ValidationError, "transferred archive"):
            validate_transfer(self.root, self.package, self.version)

    def test_changed_archive_bytes(self) -> None:
        archive = next((self.root / "output/linux-64").glob("*.conda"))
        with archive.open("ab") as file:
            file.write(b"changed")
        with self.assertRaisesRegex(ValidationError, "SHA-256 mismatch"):
            validate_transfer(self.root, self.package, self.version)

    def test_duplicate_checksum_record(self) -> None:
        manifest = self.root / "package-linux-64.sha256"
        manifest.write_text(manifest.read_text() * 2)
        with self.assertRaisesRegex(ValidationError, "exactly one"):
            validate_transfer(self.root, self.package, self.version)

    def test_unsafe_checksum_path(self) -> None:
        manifest = self.root / "package-linux-64.sha256"
        manifest.write_text(
            manifest.read_text().replace("output/linux-64/", "../linux-64/")
        )
        with self.assertRaisesRegex(ValidationError, "canonical"):
            validate_transfer(self.root, self.package, self.version)

    def test_metadata_identity_and_runtime_mismatches(self) -> None:
        for override in (
            {"name": "other"},
            {"version": "0.2.0"},
            {"subdir": "noarch"},
            {"build": "other"},
            {"depends": ["mojo-compiler >=1.0.0"]},
        ):
            with self.subTest(override=override):
                self.build("linux-64", **override)
                with self.assertRaises(ValidationError):
                    validate_transfer(self.root, self.package, self.version)

    def test_extra_downloaded_file(self) -> None:
        (self.root / "unexpected.conda").write_bytes(b"extra")
        with self.assertRaisesRegex(ValidationError, "unexpected downloaded"):
            validate_transfer(self.root, self.package, self.version)

    def test_symlinked_archive(self) -> None:
        archive = next((self.root / "output/linux-64").glob("*.conda"))
        target = self.root / "target"
        archive.rename(target)
        archive.symlink_to(target)
        with self.assertRaisesRegex(ValidationError, "symlinks"):
            validate_transfer(self.root, self.package, self.version)


if __name__ == "__main__":
    unittest.main()
