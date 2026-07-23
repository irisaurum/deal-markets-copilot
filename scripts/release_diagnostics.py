from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deal_markets_copilot.orchestrator import OperationalStateError, OperationalStateStore


MAIN_REMOTE_REF = "refs/remotes/origin/main"
MAIN_FETCH_REFSPEC = "+refs/heads/main:refs/remotes/origin/main"
MAIN_PUSH_REFSPEC = "HEAD:refs/heads/main"


def _summary_path() -> Path | None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    return Path(path) if path else None


def _append_summary(title: str, rows: list[tuple[str, str]]) -> None:
    path = _summary_path()
    if path is None:
        return
    lines = [f"## {title}", "", "| Field | Value |", "|---|---|"]
    for key, value in rows:
        rendered = str(value).replace("|", "\\|").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
        lines.append(f"| {key} | {rendered} |")
    lines.append("")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _verifier_summary(message: str) -> list[tuple[str, str]]:
    context = message.strip() or "Verifier failed without an exception message."
    rows = [
        ("failed stage", "strict verifier"),
        ("invariant", "public artifacts describe one final dataset build"),
        ("artifact/file", "unavailable from assertion"),
        ("Deal ID / row / field", "unavailable from assertion"),
        ("expected", "strict verifier completes successfully"),
        ("actual", context),
        ("raw failure context", context),
        ("recommended next action", "Fix the upstream data/artifact mismatch, rerun production refresh, and keep the verifier strict."),
    ]

    csv_match = re.search(
        r"CSV mismatch at row (?P<row>\d+)(?:, deal_id (?P<deal_id>[^,]+))?, field (?P<field>[^:]+): expected=(?P<expected>.*), actual=(?P<actual>.*)",
        message,
    )
    if csv_match:
        rows[1] = ("invariant", "CSV field equals canonical JSON dataset field")
        rows[2] = ("artifact/file", "output/precedent_transactions.csv")
        location = f"row {csv_match.group('row')}, field {csv_match.group('field')}"
        if csv_match.group("deal_id"):
            location = f"Deal ID {csv_match.group('deal_id')}, {location}"
        rows[3] = ("Deal ID / row / field", location)
        rows[4] = ("expected", csv_match.group("expected"))
        rows[5] = ("actual", csv_match.group("actual"))
        return rows

    missing_ids = re.search(r"(?P<sheet>.+) is missing deal IDs: (?P<ids>\[.*\])", message)
    if missing_ids:
        rows[1] = ("invariant", "XLSX sheet contains every required deal ID")
        rows[2] = ("artifact/file", "output/precedent_transactions.xlsx")
        rows[3] = ("Deal ID / row / field", missing_ids.group("ids"))
        rows[4] = ("expected", f"{missing_ids.group('sheet')} contains the listed IDs")
        rows[5] = ("actual", "listed IDs absent")
        return rows

    manifest_hash = re.search(
        r"XLSX manifest dataset hash is stale: expected=(?P<expected>.*), actual=(?P<actual>.*)",
        message,
    )
    if manifest_hash:
        rows[1] = ("invariant", "manifest dataset_sha256 equals final dataset SHA")
        rows[2] = ("artifact/file", "output/build_manifest.json")
        rows[4] = ("expected", manifest_hash.group("expected"))
        rows[5] = ("actual", manifest_hash.group("actual"))
        return rows

    deal_id_match = re.search(r": (?P<deal_id>(?:DL|CURATED)-[A-Za-z0-9._-]+)$", context)
    if deal_id_match:
        rows[2] = ("artifact/file", "data/precedent_transactions.json")
        rows[3] = ("Deal ID / row / field", f"Deal ID {deal_id_match.group('deal_id')}")

    return rows


def verify_public_artifacts() -> int:
    sys.path.insert(0, str(ROOT))
    from scripts import verify_public_artifacts as verifier

    try:
        verifier.main()
    except Exception as exc:  # Preserve traceback while adding a compact summary.
        traceback.print_exc()
        _append_summary("Production failure diagnostics", _verifier_summary(str(exc)))
        return 1
    return 0


def _run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _git_failure_text(error: subprocess.CalledProcessError) -> str:
    return (error.stderr or error.stdout or str(error)).strip()


def bot_push(expected_base: str) -> int:
    fetch_args = ["fetch", "--no-tags", "origin", MAIN_FETCH_REFSPEC]
    try:
        _run_git(fetch_args)
        actual = _run_git(["rev-parse", MAIN_REMOTE_REF]).stdout.strip()
    except subprocess.CalledProcessError as error:
        failure = _git_failure_text(error)
        _append_summary(
            "Production failure diagnostics",
            [
                ("failed stage", "bot push safety check"),
                ("invariant", "origin/main must be freshly resolved before publication"),
                ("artifact/file", "origin/main"),
                ("Deal ID / row / field", "n/a"),
                ("expected", expected_base),
                ("actual", failure),
                ("recommended next action", "Restore GitHub connectivity, then start a new production refresh on current main."),
            ],
        )
        if error.stdout:
            sys.stdout.write(error.stdout)
        if error.stderr:
            sys.stderr.write(error.stderr)
        return error.returncode or 1

    if actual != expected_base:
        _append_summary(
            "Production failure diagnostics",
            [
                ("failed stage", "bot push stale-main safety"),
                ("invariant", "bot commit may push only when origin/main still equals the run base SHA"),
                ("artifact/file", "origin/main"),
                ("Deal ID / row / field", "n/a"),
                ("expected", expected_base),
                ("actual", actual),
                ("recommended next action", "Start a new production refresh run on the current origin/main; do not rebase, merge or force-push this stale run."),
            ],
        )
        print("Refusing bot push because origin/main changed during this run.", file=sys.stderr)
        print(f"Expected base SHA: {expected_base}", file=sys.stderr)
        print(f"Actual origin/main SHA: {actual}", file=sys.stderr)
        print("Start a new run on the current main; this run will not rebase, merge or force-push.", file=sys.stderr)
        return 1

    push = _run_git(["push", "origin", MAIN_PUSH_REFSPEC], check=False)
    if push.returncode != 0:
        _append_summary(
            "Production failure diagnostics",
            [
                ("failed stage", "bot push"),
                ("invariant", "bot commit must fast-forward origin/main without force push"),
                ("artifact/file", "origin/main"),
                ("Deal ID / row / field", "n/a"),
                ("expected", "normal fast-forward or no-op push to origin/main from run base"),
                ("actual", (push.stderr or push.stdout).strip() or "git push failed"),
                ("recommended next action", "Inspect remote history and start a new production refresh run on current main."),
            ],
        )
    sys.stdout.write(push.stdout)
    sys.stderr.write(push.stderr)
    return push.returncode


def verify_parent(expected_base: str) -> int:
    """Read-only stale-main guard used on both delta and no-op production runs."""
    try:
        _run_git(["fetch", "--no-tags", "origin", MAIN_FETCH_REFSPEC])
        actual = _run_git(["rev-parse", MAIN_REMOTE_REF]).stdout.strip()
    except subprocess.CalledProcessError as error:
        failure = _git_failure_text(error)
        _append_summary(
            "Production failure diagnostics",
            [
                ("failed stage", "production parent verification"),
                ("invariant", "origin/main must be freshly resolved before publication decision"),
                ("artifact/file", "origin/main"),
                ("Deal ID / row / field", "n/a"),
                ("expected", expected_base),
                ("actual", failure),
                ("recommended next action", "Restore GitHub connectivity and let the next scheduled run retry."),
            ],
        )
        return error.returncode or 1
    if actual == expected_base:
        return 0
    _append_summary(
        "Production failure diagnostics",
        [
            ("failed stage", "production parent verification"),
            ("invariant", "origin/main must still equal the workflow run parent"),
            ("artifact/file", "origin/main"),
            ("Deal ID / row / field", "n/a"),
            ("expected", expected_base),
            ("actual", actual),
            ("recommended next action", "Let the next scheduled run start from current main; do not merge, rebase or force-push."),
        ],
    )
    print("Refusing publication because origin/main changed during this run.", file=sys.stderr)
    return 1


def verify_orchestration_state(path: str | Path) -> int:
    """Allow cache save only for a present, complete, schema-valid state file."""
    state_path = Path(path)
    if not state_path.is_file():
        print("ORCHESTRATION_STATE_NOT_SAVED missing_state_file", file=sys.stderr)
        return 1
    try:
        state = OperationalStateStore(state_path).load()
    except OperationalStateError as exc:
        print(f"ORCHESTRATION_STATE_NOT_SAVED {exc}", file=sys.stderr)
        return 1
    print(
        "ORCHESTRATION_STATE_VALID "
        f"schema={state['schema_version']} sources={len(state['sources'])}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify-public-artifacts")
    verify_parent_parser = subparsers.add_parser("verify-parent")
    verify_parent_parser.add_argument("--expected-base", required=True)
    verify_state_parser = subparsers.add_parser("verify-orchestration-state")
    verify_state_parser.add_argument("--path", required=True)
    bot_push_parser = subparsers.add_parser("bot-push")
    bot_push_parser.add_argument("--expected-base", required=True)
    args = parser.parse_args(argv)

    if args.command == "verify-public-artifacts":
        return verify_public_artifacts()
    if args.command == "bot-push":
        return bot_push(args.expected_base)
    if args.command == "verify-parent":
        return verify_parent(args.expected_base)
    if args.command == "verify-orchestration-state":
        return verify_orchestration_state(args.path)
    raise AssertionError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
