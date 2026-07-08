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
        self.assertEqual(trigger_block.count("- cron:"), 3)
        production_gate = "if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
        self.assertIn(production_gate, self.production_job)
        self.assertIn(production_gate, self.deploy_job)

    def test_validation_path_is_deterministic(self) -> None:
        self.assertIn("contents: read", self.validate_job)
        self.assertIn("python -m unittest discover -s tests -v", self.validate_job)
        self.assertIn("python scripts/verify_public_artifacts.py", self.validate_job)
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
            "python scripts/verify_public_artifacts.py",
        ])
        self.assertLess(first_replay, workbook)
        self.assertLess(workbook, second_replay)
        self.assertLess(second_replay, verifier)
        self.assertEqual(self.production_job.count("run: python run.py --replay"), 2)

    def test_production_concurrency_group_is_preserved(self) -> None:
        self.assertIn("'deal-desk-pages'", self.workflow)
        self.assertIn("github.event_name == 'schedule'", self.workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", self.workflow)


if __name__ == "__main__":
    unittest.main()
