from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import release_diagnostics
from scripts import verify_public_artifacts as verifier


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _seed_remote(root: Path) -> Path:
    remote = root / "remote.git"
    seed = root / "seed"
    _git(root, "init", "--bare", "--initial-branch=main", str(remote))
    _git(root, "init", "--initial-branch=main", str(seed))
    _git(seed, "config", "user.name", "Test Bot")
    _git(seed, "config", "user.email", "test@example.com")
    (seed / "state.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "state.txt")
    _git(seed, "commit", "-m", "base")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    return remote


class ReleaseDiagnosticsTests(unittest.TestCase):
    def test_orchestration_state_validator_requires_present_valid_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(release_diagnostics.verify_orchestration_state(path), 1)
            path.write_text("{broken", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(release_diagnostics.verify_orchestration_state(path), 1)
            path.write_text(
                json.dumps({"schema_version": 1, "sources": {"feed": {"etag": "v1"}}}),
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(release_diagnostics.verify_orchestration_state(path), 0)

    def test_verifier_summary_extracts_csv_expected_actual(self) -> None:
        rows = release_diagnostics._verifier_summary(
            "CSV mismatch at row 7, deal_id DL-example, field quality_score: expected='100', actual='90'"
        )
        summary = dict(rows)
        self.assertEqual(summary["failed stage"], "strict verifier")
        self.assertEqual(summary["invariant"], "CSV field equals canonical JSON dataset field")
        self.assertEqual(summary["artifact/file"], "output/precedent_transactions.csv")
        self.assertEqual(summary["Deal ID / row / field"], "Deal ID DL-example, row 7, field quality_score")
        self.assertEqual(summary["expected"], "'100'")
        self.assertEqual(summary["actual"], "'90'")
        self.assertIn("rerun production refresh", summary["recommended next action"])

    def test_verifier_summary_preserves_unparsed_failure_context(self) -> None:
        summary = dict(release_diagnostics._verifier_summary("Workbook contains a formula error"))
        self.assertEqual(summary["actual"], "Workbook contains a formula error")
        self.assertEqual(summary["raw failure context"], "Workbook contains a formula error")
        self.assertEqual(summary["artifact/file"], "unavailable from assertion")

    def test_verifier_wrapper_preserves_failure_and_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary_path = Path(directory) / "summary.md"
            stderr = io.StringIO()
            with (
                patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary_path)}),
                patch.object(verifier, "main", side_effect=AssertionError("unparsed verifier failure")),
                contextlib.redirect_stderr(stderr),
            ):
                result = release_diagnostics.verify_public_artifacts()

            self.assertEqual(result, 1)
            self.assertIn("Traceback", stderr.getvalue())
            self.assertIn("AssertionError: unparsed verifier failure", stderr.getvalue())
            self.assertIn("unparsed verifier failure", summary_path.read_text(encoding="utf-8"))

    def test_bot_push_refuses_stale_origin_main_and_writes_summary(self) -> None:
        calls: list[list[str]] = []

        def fake_git(args: list[str], check: bool = True):
            calls.append(args)
            class Result:
                stdout = "actual-sha\n" if args == ["rev-parse", release_diagnostics.MAIN_REMOTE_REF] else ""
                stderr = ""
                returncode = 0
            return Result()

        with tempfile.TemporaryDirectory() as directory:
            summary_path = Path(directory) / "summary.md"
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary_path)}), patch.object(release_diagnostics, "_run_git", side_effect=fake_git):
                result = release_diagnostics.bot_push("expected-sha")

            self.assertEqual(result, 1)
            self.assertIn(["fetch", "--no-tags", "origin", release_diagnostics.MAIN_FETCH_REFSPEC], calls)
            self.assertNotIn(["push", "origin", release_diagnostics.MAIN_PUSH_REFSPEC], calls)
            summary = summary_path.read_text(encoding="utf-8")
            self.assertIn("bot push stale-main safety", summary)
            self.assertIn("expected-sha", summary)
            self.assertIn("actual-sha", summary)
            self.assertIn("Start a new production refresh run", summary)

    def test_bot_push_allows_normal_fast_forward_push(self) -> None:
        calls: list[list[str]] = []

        def fake_git(args: list[str], check: bool = True):
            calls.append(args)
            class Result:
                stdout = "expected-sha\n" if args == ["rev-parse", release_diagnostics.MAIN_REMOTE_REF] else ""
                stderr = ""
                returncode = 0
            return Result()

        with patch.object(release_diagnostics, "_run_git", side_effect=fake_git):
            result = release_diagnostics.bot_push("expected-sha")

        self.assertEqual(result, 0)
        self.assertIn(["push", "origin", release_diagnostics.MAIN_PUSH_REFSPEC], calls)

    def test_bot_push_summarizes_push_failure(self) -> None:
        def fake_git(args: list[str], check: bool = True):
            class Result:
                stdout = "expected-sha\n" if args == ["rev-parse", release_diagnostics.MAIN_REMOTE_REF] else ""
                stderr = "non-fast-forward"
                returncode = 1 if args == ["push", "origin", release_diagnostics.MAIN_PUSH_REFSPEC] else 0
            return Result()

        with tempfile.TemporaryDirectory() as directory:
            summary_path = Path(directory) / "summary.md"
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary_path)}), patch.object(release_diagnostics, "_run_git", side_effect=fake_git):
                result = release_diagnostics.bot_push("expected-sha")

            self.assertEqual(result, 1)
            summary = summary_path.read_text(encoding="utf-8")
            self.assertIn("bot push", summary)
            self.assertIn("bot commit must fast-forward origin/main without force push", summary)
            self.assertIn("non-fast-forward", summary)

    def test_bot_push_summarizes_fresh_fetch_failure(self) -> None:
        failure = subprocess.CalledProcessError(128, ["git", "fetch"], stderr="network unavailable")

        with tempfile.TemporaryDirectory() as directory:
            summary_path = Path(directory) / "summary.md"
            with (
                patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary_path)}),
                patch.object(release_diagnostics, "_run_git", side_effect=failure),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = release_diagnostics.bot_push("expected-sha")

            self.assertEqual(result, 128)
            summary = summary_path.read_text(encoding="utf-8")
            self.assertIn("bot push safety check", summary)
            self.assertIn("network unavailable", summary)

    def test_real_git_normal_fast_forward_push_targets_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = _seed_remote(root)
            runner = root / "runner"
            _git(root, "clone", str(remote), str(runner))
            _git(runner, "config", "user.name", "Test Bot")
            _git(runner, "config", "user.email", "test@example.com")
            expected_base = _git(runner, "rev-parse", "HEAD").stdout.strip()
            (runner / "state.txt").write_text("candidate\n", encoding="utf-8")
            _git(runner, "add", "state.txt")
            _git(runner, "commit", "-m", "candidate")
            candidate = _git(runner, "rev-parse", "HEAD").stdout.strip()

            with patch.object(release_diagnostics, "ROOT", runner):
                result = release_diagnostics.bot_push(expected_base)

            self.assertEqual(result, 0)
            self.assertEqual(_git(remote, "rev-parse", "refs/heads/main").stdout.strip(), candidate)

    def test_real_git_no_change_push_is_a_safe_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = _seed_remote(root)
            runner = root / "runner"
            _git(root, "clone", str(remote), str(runner))
            expected_base = _git(runner, "rev-parse", "HEAD").stdout.strip()

            with patch.object(release_diagnostics, "ROOT", runner):
                result = release_diagnostics.bot_push(expected_base)

            self.assertEqual(result, 0)
            self.assertEqual(_git(remote, "rev-parse", "refs/heads/main").stdout.strip(), expected_base)

    def test_real_git_stale_candidate_cannot_overwrite_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = _seed_remote(root)
            runner = root / "runner"
            writer = root / "writer"
            _git(root, "clone", str(remote), str(runner))
            _git(root, "clone", str(remote), str(writer))
            for clone in (runner, writer):
                _git(clone, "config", "user.name", "Test Bot")
                _git(clone, "config", "user.email", "test@example.com")

            expected_base = _git(runner, "rev-parse", "HEAD").stdout.strip()
            (writer / "state.txt").write_text("new main\n", encoding="utf-8")
            _git(writer, "add", "state.txt")
            _git(writer, "commit", "-m", "advance main")
            _git(writer, "push", "origin", "main")
            actual_main = _git(writer, "rev-parse", "HEAD").stdout.strip()

            (runner / "candidate.txt").write_text("stale candidate\n", encoding="utf-8")
            _git(runner, "add", "candidate.txt")
            _git(runner, "commit", "-m", "stale candidate")
            with tempfile.TemporaryDirectory() as summary_directory:
                summary_path = Path(summary_directory) / "summary.md"
                with (
                    patch.object(release_diagnostics, "ROOT", runner),
                    patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary_path)}),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    result = release_diagnostics.bot_push(expected_base)

                summary = summary_path.read_text(encoding="utf-8")

            self.assertEqual(result, 1)
            self.assertEqual(_git(remote, "rev-parse", "refs/heads/main").stdout.strip(), actual_main)
            self.assertIn(expected_base, summary)
            self.assertIn(actual_main, summary)


if __name__ == "__main__":
    unittest.main()
