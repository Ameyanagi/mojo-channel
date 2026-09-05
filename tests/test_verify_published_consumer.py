from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_published_consumer import (  # noqa: E402
    CHANNEL,
    argument_parser,
    validate_resolved_package,
)


class ConsumerValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package = "mojo-mojotui"
        self.version = "0.1.1"
        self.subdir = "linux-64"
        self.filename = "mojo-mojotui-0.1.1-hb0f4dca_0.conda"
        self.digest = "a" * 64
        self.expected = {self.filename: {"sha256": self.digest}}
        self.record = {
            "name": self.package,
            "version": self.version,
            "url": f"{CHANNEL}/{self.subdir}/{self.filename}",
            "sha256": self.digest,
        }

    def validate(self, records: list[dict]) -> dict:
        return validate_resolved_package(
            records, self.expected, self.package, self.version, self.subdir
        )

    def test_supported_consumer_targets(self) -> None:
        for package in ("mojo-kumihan", "mojo-sen", "mojo-mojotui", "mojo-yomi"):
            with self.subTest(package=package):
                args = argument_parser().parse_args(
                    [package, self.version, self.subdir, "smoke.mojo"]
                )
                self.assertEqual(args.package, package)
                self.assertEqual(args.version, self.version)
                filename = f"{package}-{self.version}-hb0f4dca_0.conda"
                expected = {filename: {"sha256": self.digest}}
                record = dict(
                    self.record,
                    name=package,
                    url=f"{CHANNEL}/{self.subdir}/{filename}",
                )
                self.assertEqual(
                    validate_resolved_package(
                        [record], expected, package, self.version, self.subdir
                    ),
                    record,
                )

    def test_accepts_exact_native_identity_on_each_platform(self) -> None:
        for subdir in ("linux-64", "linux-aarch64", "osx-arm64"):
            with self.subTest(subdir=subdir):
                record = dict(self.record, url=f"{CHANNEL}/{subdir}/{self.filename}")
                self.assertEqual(
                    validate_resolved_package(
                        [record], self.expected, self.package, self.version, subdir
                    ),
                    record,
                )

    def test_rejects_missing_duplicate_or_wrong_version(self) -> None:
        for records in (
            [],
            [self.record, self.record],
            [dict(self.record, version="0.1.0")],
        ):
            with self.subTest(records=records):
                with self.assertRaisesRegex(ValueError, "exact consumer package"):
                    self.validate(records)

    def test_rejects_foreign_platform_or_unknown_origin(self) -> None:
        for url in (
            self.record["url"].replace("linux-64", "osx-arm64"),
            self.record["url"].replace(CHANNEL, "https://example.invalid/channel"),
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "URL/hash"):
                    self.validate([dict(self.record, url=url)])

    def test_rejects_corrupt_or_absent_digest(self) -> None:
        for digest in ("b" * 64, None, "", "a" * 63):
            with self.subTest(digest=digest):
                with self.assertRaisesRegex(ValueError, "URL/hash"):
                    self.validate([dict(self.record, sha256=digest)])

    def test_unknown_url_and_missing_hash_cannot_compare_equal(self) -> None:
        record = dict(
            self.record, url="https://example.invalid/unknown.conda", sha256=None
        )
        with self.assertRaisesRegex(ValueError, "URL/hash"):
            self.validate([record])

    def test_validator_preserves_input_records(self) -> None:
        original = copy.deepcopy(self.record)
        expected = copy.deepcopy(self.expected)
        self.validate([self.record])
        self.assertEqual(self.record, original)
        self.assertEqual(self.expected, expected)


if __name__ == "__main__":
    unittest.main()
