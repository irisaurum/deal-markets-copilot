from __future__ import annotations

import fnmatch
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deal-desk.yml"


def _ignored_push_paths(workflow: str) -> list[str]:
    match = re.search(
        r"(?ms)^  push:\n.*?^    paths-ignore:\n(?P<body>(?:^      .*\n)+)",
        workflow,
    )
    if match is None:
        raise AssertionError("push.paths-ignore is missing")
    return re.findall(r'^      - "([^"]+)"$', match.group("body"), re.MULTILINE)


def _push_validation_expected(paths: list[str], ignored: list[str]) -> bool:
    return any(not any(fnmatch.fnmatch(path, pattern) for pattern in ignored) for path in paths)


def _job_block(workflow: str, job_name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        workflow,
    )
    if match is None:
        raise AssertionError(f"workflow job is missing: {job_name}")
    return match.group("body")


def _step_positions(workflow: str, commands: list[str]) -> list[int]:
    positions: list[int] = []
    for command in commands:
        position = workflow.find(command)
        if position == -1:
            raise AssertionError(f"workflow command is missing: {command}")
        positions.append(position)
    return positions


class WorkflowPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.ignored = _ignored_push_paths(cls.workflow)
        cls.validate_job = _job_block(cls.workflow, "validate")
        cls.production_job = _job_block(cls.workflow, "production_refresh")
        cls.deploy_job = _job_block(cls.workflow, "deploy")

    def test_push_validation_path_matrix(self) -> None:
        cases = {
            ("docs/ARCHITECTURE.md",): False,
            ("AGENTS.md",): False,
            ("docs/REGRESSIONS.md",): False,
            ("README.md",): False,
            ("SECURITY.md",): False,
            ("LICENSE",): False,
            ("output/build_manifest.json",): False,
            ("data/precedent_transactions.json",): False,
            ("src/deal_markets_copilot/deals.py",): True,
            ("run.py",): True,
            ("config.json",): True,
            ("scripts/verify_public_artifacts.py",): True,
            ("scripts/build_precedents_workbook_ci.py",): True,
            ("tests/test_core.py",): True,
            (".github/workflows/deal-desk.yml",): True,
            ("requirements-ci.txt",): True,
            ("data/financials.json",): True,
            ("docs/ARCHITECTURE.md", "src/deal_markets_copilot/deals.py"): True,
        }
        for paths, expected in cases.items():
            with self.subTest(paths=paths):
                self.assertEqual(_push_validation_expected(list(paths), self.ignored), expected)

    def test_validation_triggers_are_pull_request_and_push(self) -> None:
        trigger_block = self.workflow.split("permissions:", 1)[0]
        self.assertRegex(trigger_block, r"(?m)^  pull_request:$")
        self.assertRegex(trigger_block, r"(?m)^  push:$")
        self.assertIn("if: github.event_name == 'pull_request' || github.event_name == 'push'", self.validate_job)

    def test_non_push_production_triggers_are_preserved(self) -> None:
        trigger_block = self.workflow.split("permissions:", 1)[0]
        self.assertRegex(trigger_block, r"(?m)^  workflow_dispatch:$")
        self.assertRegex(trigger_block, r"(?m)^  schedule:$")
        self.assertEqual(trigger_block.count("- cron:"), 1)
        self.assertIn('- cron: "*/30 * * * *"', trigger_block)
        production_gate = "if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
        self.assertIn(production_gate, self.production_job)
        self.assertIn("needs.production_refresh.outputs.publish_delta == 'true'", self.deploy_job)

    def test_validation_path_is_deterministic(self) -> None:
        self.assertIn("contents: read", self.validate_job)
        self.assertIn("python -m unittest discover -s tests -v", self.validate_job)
        self.assertIn("python scripts/release_diagnostics.py verify-public-artifacts", self.validate_job)
        forbidden = [
            "python run.py --live",
            "python run.py --replay",
            "git push",
            "actions/deploy-pages",
            "actions/upload-pages-artifact",
        ]
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, self.validate_job)

    def test_push_does_not_run_production_refresh(self) -> None:
        self.assertNotIn("github.event_name == 'push'", self.production_job)
        self.assertNotIn("github.event_name == 'pull_request'", self.production_job)
        self.assertNotIn("github.event_name == 'push'", self.deploy_job)
        self.assertNotIn("github.event_name == 'pull_request'", self.deploy_job)

    def test_generated_artifacts_remain_a_loop_guard(self) -> None:
        self.assertIn("output/**", self.ignored)
        self.assertIn("site/**", self.ignored)
        self.assertIn("data/precedent_transactions.json", self.ignored)

    def test_replay_canonicalization_precedes_manifest_generation(self) -> None:
        first_replay, workbook, second_replay, verifier = _step_positions(self.production_job, [
            "Persist replay canonicalization before Excel",
            "python scripts/build_precedents_workbook_ci.py",
            "Synchronize dashboard health with Excel",
            "python scripts/release_diagnostics.py verify-public-artifacts",
        ])
        self.assertLess(first_replay, workbook)
        self.assertLess(workbook, second_replay)
        self.assertLess(second_replay, verifier)
        self.assertEqual(self.production_job.count("run: python run.py --replay"), 2)

    def test_bot_push_uses_stale_main_safety_without_force(self) -> None:
        self.assertIn('python scripts/release_diagnostics.py bot-push --expected-base "$GITHUB_SHA"', self.production_job)
        self.assertNotIn("git push", self.production_job)
        self.assertNotIn("--force", self.production_job)
        self.assertRegex(
            self.production_job,
            r'(?ms)if ! git diff --cached --quiet; then\n\s+git commit -m "chore: refresh deal desk"\n\s+fi\n\s+python scripts/release_diagnostics.py bot-push --expected-base "\$GITHUB_SHA"',
        )
        self.assertIn(
            'python scripts/release_diagnostics.py verify-parent --expected-base "$GITHUB_SHA"',
            self.production_job,
        )

    def test_bot_commit_is_limited_to_public_data_and_output_files(self) -> None:
        match = re.search(r"(?m)^\s+git add (?P<paths>.+)$", self.production_job)
        self.assertIsNotNone(match)
        self.assertEqual(
            set(match.group("paths").split()),
            {
                "data/precedent_transactions.json",
                "output/build_manifest.json",
                "output/deal_markets_brief.html",
                "output/latest_snapshot.json",
                "output/precedent_transactions.csv",
                "output/precedent_transactions.xlsx",
            },
        )

    def test_verifier_and_stale_guard_gate_publication_and_deploy(self) -> None:
        verifier, site, bot_push, upload = _step_positions(
            self.production_job,
            [
                "python scripts/release_diagnostics.py verify-public-artifacts",
                "Prepare site",
                'python scripts/release_diagnostics.py bot-push --expected-base "$GITHUB_SHA"',
                "actions/upload-pages-artifact",
            ],
        )
        self.assertLess(verifier, site)
        self.assertLess(site, bot_push)
        self.assertLess(bot_push, upload)
        self.assertIn("needs: production_refresh", self.deploy_job)
        self.assertIn("needs.production_refresh.outputs.publish_delta == 'true'", self.deploy_job)

    def test_post_refresh_verifier_emits_diagnostics_before_regression_tests(self) -> None:
        step = self.production_job.split("- name: Verify synchronized public artifacts", 1)[1].split("- name:", 1)[0]
        verifier = step.find("python scripts/release_diagnostics.py verify-public-artifacts")
        tests = step.find("python -m unittest discover -s tests -v")
        self.assertNotEqual(verifier, -1)
        self.assertNotEqual(tests, -1)
        self.assertLess(verifier, tests)

    def test_production_concurrency_group_is_preserved(self) -> None:
        self.assertIn("'deal-desk-pages'", self.workflow)
        self.assertIn("github.event_name == 'schedule'", self.workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_production_dependencies_precede_live_discovery(self) -> None:
        install = self.production_job.find("Install pinned production dependencies")
        live = self.production_job.find("python run.py --live")
        self.assertNotEqual(install, -1)
        self.assertNotEqual(live, -1)
        self.assertLess(install, live)

    def test_noop_skips_commit_upload_and_deploy(self) -> None:
        self.assertIn("steps.refresh.outputs.publish_delta == 'true'", self.production_job)
        for step in (
            "Persist replay canonicalization before Excel",
            "Rebuild Excel workbook",
            "Prepare site",
            "Commit and push verified publishable delta",
            "Upload Pages artifact",
        ):
            block = self.production_job.split(f"- name: {step}", 1)[1].split("- name:", 1)[0]
            self.assertIn("if: steps.refresh.outputs.publish_delta == 'true'", block)

    def test_cross_run_operational_state_uses_cache_not_git(self) -> None:
        self.assertIn("actions/cache/restore@v4", self.production_job)
        self.assertIn("actions/cache/save@v4", self.production_job)
        self.assertIn("runner.temp", self.production_job)
        git_add = re.search(r"(?m)^\s+git add (?P<paths>.+)$", self.production_job)
        self.assertIsNotNone(git_add)
        self.assertNotIn("orchestration", git_add.group("paths"))


if __name__ == "__main__":
    unittest.main()
