from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_validate_conda_runtime import make_conda_artifact

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_channel import ValidationError, read_ledger, validate_channel  # noqa: E402


class ChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = "linux-64/mojo-kumihan-0.1.0-test_0.conda"
        self.index = {
            "name": "mojo-kumihan",
            "version": "0.1.0",
            "subdir": "linux-64",
            "build": "test_0",
            "build_number": 0,
            "depends": ["mojo-compiler ==1.0.0"],
        }
        for subdir in ("linux-64", "linux-aarch64", "osx-arm64", "noarch"):
            (self.root / subdir).mkdir()
            self.write_json(
                f"{subdir}/repodata.json",
                {"info": {"subdir": subdir}, "packages": {}, "packages.conda": {}},
            )
        self.write_json("legacy-artifacts.json", {})
        self.rebuild()

    def write_json(self, path: str, value: object) -> None:
        (self.root / path).write_text(json.dumps(value))

    def rebuild(self) -> None:
        archive = self.root / self.path
        make_conda_artifact(archive, index_bytes=json.dumps(self.index).encode())
        raw = archive.read_bytes()
        self.digest = hashlib.sha256(raw).hexdigest()
        self.row = f"{self.path}\t{self.digest}\tkumihan\tv0.1.0\t{'a' * 40}\n"
        (self.root / "artifacts.tsv").write_text(self.row)
        self.metadata = dict(
            self.index,
            sha256=self.digest,
            md5=hashlib.md5(raw, usedforsecurity=False).hexdigest(),
            size=len(raw),
        )
        self.write_repodata()

    def write_repodata(self) -> None:
        self.write_json(
            "linux-64/repodata.json",
            {
                "info": {"subdir": "linux-64"},
                "packages": {},
                "packages.conda": {Path(self.path).name: self.metadata},
            },
        )

    def test_complete_channel_is_read_only(self) -> None:
        files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(
            validate_channel(self.root),
            {"current": 1, "unsupported_legacy": 0, "total": 1},
        )
        self.assertEqual(files, {p: p.read_bytes() for p in files})

    def test_changed_bytes(self) -> None:
        with (self.root / self.path).open("ab") as file:
            file.write(b"changed")
        with self.assertRaisesRegex(ValidationError, "SHA-256 mismatch"):
            validate_channel(self.root)

    def test_missing_archive(self) -> None:
        (self.root / self.path).unlink()
        with self.assertRaisesRegex(ValidationError, "missing="):
            validate_channel(self.root)

    def test_unrecorded_archive(self) -> None:
        (self.root / "linux-64/extra.conda").write_bytes(b"unrecorded")
        with self.assertRaisesRegex(ValidationError, "unrecorded="):
            validate_channel(self.root)

    def test_duplicate_and_conflicting_rows(self) -> None:
        for row in (self.row, self.row.replace(self.digest, "b" * 64)):
            with self.subTest(row=row):
                (self.root / "artifacts.tsv").write_text(self.row + row)
                with self.assertRaisesRegex(ValidationError, "duplicate/conflicting"):
                    validate_channel(self.root)

    def test_row_structure_and_unsafe_paths(self) -> None:
        for row in (
            "\n",
            "a\tb\n",
            self.row.replace("linux-64/", "../"),
            self.row.replace(self.digest, "INVALID"),
            self.row.replace("v0.1.0", "main"),
            self.row.replace("a" * 40, "x" * 40),
            self.row.replace("\tkumihan\t", "\tunknown\t"),
        ):
            with self.subTest(row=row):
                with self.assertRaises(ValidationError):
                    read_ledger(row)

    def test_same_tag_has_one_source_commit_across_platforms(self) -> None:
        second = self.row.replace("linux-64/", "linux-aarch64/").replace(
            "a" * 40, "b" * 40
        )
        with self.assertRaisesRegex(ValidationError, "conflicting source"):
            read_ledger(self.row + second)

    def test_repodata_mismatches(self) -> None:
        original = self.metadata.copy()
        for key, invalid in {
            "name": "other",
            "version": "0.2.0",
            "subdir": "osx-arm64",
            "build": "other",
            "build_number": 2,
            "depends": [],
            "sha256": "b" * 64,
            "md5": "b" * 32,
            "size": 0,
        }.items():
            with self.subTest(field=key):
                self.metadata = dict(original, **{key: invalid})
                self.write_repodata()
                with self.assertRaisesRegex(ValidationError, "repodata"):
                    validate_channel(self.root)

    def test_missing_or_extra_repodata_record(self) -> None:
        for records in ({}, {"extra.conda": self.metadata}):
            self.write_json(
                "linux-64/repodata.json",
                {"info": {"subdir": "linux-64"}, "packages.conda": records},
            )
            with self.assertRaisesRegex(ValidationError, "repodata archive inventory"):
                validate_channel(self.root)

    def test_archive_identity_does_not_follow_rewritten_repodata(self) -> None:
        self.index["name"] = "mojo-other"
        self.rebuild()
        with self.assertRaisesRegex(ValidationError, "identity mismatch"):
            validate_channel(self.root)

    def test_current_archive_requires_exact_runtime(self) -> None:
        self.index["depends"] = ["mojo-compiler >=1.0.0,<2.0a0"]
        self.rebuild()
        with self.assertRaisesRegex(ValidationError, "exact MatchSpec"):
            validate_channel(self.root)

    def make_legacy(self) -> None:
        self.index["depends"] = ["mojo-compiler >=1.0.0,<2.0a0"]
        self.rebuild()
        (self.root / "artifacts.tsv").write_text("")
        self.legacy = {
            self.path: {
                "sha256": self.digest,
                "index": self.index.copy(),
                "reason": "Unsupported, retained pre-ledger archive",
            }
        }
        self.write_json("legacy-artifacts.json", self.legacy)

    def test_explicit_legacy_is_classified_without_installing(self) -> None:
        self.make_legacy()
        self.assertEqual(validate_channel(self.root)["unsupported_legacy"], 1)

    def test_legacy_metadata_must_match_frozen_inventory(self) -> None:
        self.make_legacy()
        self.legacy[self.path]["index"]["depends"] = []
        self.write_json("legacy-artifacts.json", self.legacy)
        with self.assertRaisesRegex(ValidationError, "legacy metadata changed"):
            validate_channel(self.root)

    def test_current_and_legacy_cannot_overlap(self) -> None:
        self.make_legacy()
        (self.root / "artifacts.tsv").write_text(self.row)
        with self.assertRaisesRegex(ValidationError, "both current and legacy"):
            validate_channel(self.root)

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def commit_baseline(self) -> None:
        self.git("init", "-q")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Channel test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "baseline",
        )

    def test_baseline_ledger_cannot_be_rewritten_or_removed(self) -> None:
        self.commit_baseline()
        validate_channel(self.root, "HEAD")
        for text in ("", self.row.replace("a" * 40, "b" * 40)):
            (self.root / "artifacts.tsv").write_text(text)
            with self.assertRaisesRegex(ValidationError, "immutable ledger"):
                validate_channel(self.root, "HEAD")

    def test_baseline_legacy_cannot_expand(self) -> None:
        self.commit_baseline()
        self.write_json(
            "legacy-artifacts.json",
            {
                "osx-arm64/other.conda": {
                    "sha256": "b" * 64,
                    "index": {},
                    "reason": "Pretend legacy",
                }
            },
        )
        with self.assertRaisesRegex(ValidationError, "frozen legacy"):
            validate_channel(self.root, "HEAD")

    def test_repodata_duplicate_keys_rejected(self) -> None:
        (self.root / "linux-64/repodata.json").write_text(
            '{"packages.conda": {}, "packages.conda": {}}'
        )
        with self.assertRaisesRegex(ValidationError, "duplicate key"):
            validate_channel(self.root)

    def test_archive_symlink_rejected(self) -> None:
        archive = self.root / self.path
        target = self.root / "original"
        archive.rename(target)
        archive.symlink_to(target)
        with self.assertRaisesRegex(ValidationError, "regular file"):
            validate_channel(self.root)


if __name__ == "__main__":
    unittest.main()
