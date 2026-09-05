from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/propose_release.sh"


class ProposalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.repo = self.root / "work"
        self.repo.mkdir()
        self.git("init", "--bare", str(self.remote), cwd=self.root)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Channel tests")
        self.git("config", "user.email", "channel@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        (self.repo / "baseline").write_text("original\n")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-u", "origin", "main")
        self.main = self.git("rev-parse", "HEAD").strip()
        binary = self.root / "bin"
        binary.mkdir()
        fake_gh = binary / "gh"
        fake_gh.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DISPATCH_LOG"\n')
        fake_gh.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=f"{binary}:{os.environ['PATH']}",
            EXPECTED_PACKAGE="mojo-kumihan",
            EXPECTED_VERSION="0.1.0",
            EXPECTED_SHA="a" * 40,
            GH_TOKEN="synthetic-unused-local-remote-token",
            GITHUB_OUTPUT=str(self.root / "output"),
            GITHUB_STEP_SUMMARY=str(self.root / "summary"),
            DISPATCH_LOG=str(self.root / "dispatch"),
        )
        self.branch = "release/mojo-kumihan-0.1.0-" + "a" * 40

    def git(self, *args: str, cwd: Path | None = None) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def stage(self, contents: str = "immutable candidate\n") -> None:
        (self.repo / "artifact.conda").write_text(contents)
        self.git("add", "artifact.conda")

    def propose(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def test_proposal_dispatches_exact_branch_without_updating_main(self) -> None:
        self.stage()
        result = self.propose()
        self.assertEqual(result.returncode, 0, result.stderr)
        sha = self.git("rev-parse", "HEAD").strip()
        self.assertEqual(
            self.git("rev-parse", "refs/heads/main", cwd=self.remote).strip(), self.main
        )
        self.assertEqual(
            self.git("rev-parse", f"refs/heads/{self.branch}", cwd=self.remote).strip(),
            sha,
        )
        self.assertIn(f"sha={sha}", (self.root / "output").read_text())
        self.assertEqual(
            (self.root / "dispatch").read_text(),
            f"workflow run ci.yml --ref {self.branch}\n",
        )

    def test_identical_retry_reuses_original_commit(self) -> None:
        self.stage()
        self.assertEqual(self.propose().returncode, 0)
        first = self.git("rev-parse", "HEAD").strip()
        self.git("reset", "--hard", self.main)
        self.stage()
        result = self.propose()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.git("rev-parse", f"refs/heads/{self.branch}", cwd=self.remote).strip(),
            first,
        )
        self.assertEqual((self.root / "output").read_text().count(f"sha={first}"), 2)

    def test_conflicting_retry_never_overwrites_branch(self) -> None:
        self.stage()
        self.assertEqual(self.propose().returncode, 0)
        first = self.git("rev-parse", "HEAD").strip()
        self.git("reset", "--hard", self.main)
        self.stage("changed candidate\n")
        result = self.propose()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("different bytes or base", result.stderr)
        self.assertEqual(
            self.git("rev-parse", f"refs/heads/{self.branch}", cwd=self.remote).strip(),
            first,
        )
        self.assertEqual(len((self.root / "dispatch").read_text().splitlines()), 1)

    def test_already_published_tree_makes_no_branch_or_dispatch(self) -> None:
        result = self.propose()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already_published=true", (self.root / "output").read_text())
        self.assertFalse((self.root / "dispatch").exists())
        self.assertEqual(
            self.git("ls-remote", "--heads", "origin", f"refs/heads/{self.branch}"), ""
        )


if __name__ == "__main__":
    unittest.main()
