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


def _production_refresh_expected(paths: list[str], ignored: list[str]) -> bool:
    return any(not any(fnmatch.fnmatch(path, pattern) for pattern in ignored) for path in paths)


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

    def test_push_path_matrix(self) -> None:
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
                self.assertEqual(_production_refresh_expected(list(paths), self.ignored), expected)

    def test_non_push_production_triggers_are_preserved(self) -> None:
        trigger_block = self.workflow.split("permissions:", 1)[0]
        self.assertRegex(trigger_block, r"(?m)^  workflow_dispatch:$")
        self.assertRegex(trigger_block, r"(?m)^  schedule:$")
        self.assertEqual(trigger_block.count("- cron:"), 3)

    def test_generated_artifacts_remain_a_loop_guard(self) -> None:
        self.assertIn("output/**", self.ignored)
        self.assertIn("site/**", self.ignored)
        self.assertIn("data/precedent_transactions.json", self.ignored)

    def test_replay_canonicalization_precedes_manifest_generation(self) -> None:
        first_replay, workbook, second_replay, verifier = _step_positions(self.workflow, [
            "Persist replay canonicalization before Excel",
            "python scripts/build_precedents_workbook_ci.py",
            "Synchronize dashboard health with Excel",
            "python scripts/verify_public_artifacts.py",
        ])
        self.assertLess(first_replay, workbook)
        self.assertLess(workbook, second_replay)
        self.assertLess(second_replay, verifier)
        self.assertEqual(self.workflow.count("run: python run.py --replay"), 2)


if __name__ == "__main__":
    unittest.main()
