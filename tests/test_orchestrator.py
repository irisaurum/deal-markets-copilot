from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deal_markets_copilot.orchestrator import (
    MAX_BACKOFF_MINUTES,
    OperationalStateError,
    OperationalStateStore,
    SourceOrchestrator,
    SourcePolicy,
    content_changed,
    empty_state,
    execute_source,
    format_diagnostic,
)


UTC = timezone.utc
AT = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def policy(
    source_id: str,
    *,
    enabled: bool = True,
    required: bool = False,
    state: str = "connected",
    interval: int = 30,
    detail_cap: int = 8,
) -> SourcePolicy:
    return SourcePolicy.from_mapping(source_id, {
        "enabled": enabled,
        "required": required,
        "implementation_state": state,
        "source_type": "fixture",
        "poll_interval_minutes": interval,
        "max_feed_requests": 1,
        "max_detail_requests": detail_cap,
    })


def next_due(source_policy: SourcePolicy, start: datetime = AT) -> datetime:
    for offset in range(0, 24 * 60, 30):
        candidate = start + timedelta(minutes=offset)
        if SourceOrchestrator(empty_state(), candidate).decide(source_policy).eligible:
            return candidate
    raise AssertionError("No deterministic due slot found")


class SourceEligibilityTests(unittest.TestCase):
    def test_enabled_due_source_is_eligible(self) -> None:
        source = policy("feed-30", interval=30)
        self.assertEqual(SourceOrchestrator(empty_state(), AT).decide(source).decision, "eligible")

    def test_not_due_source_makes_zero_requests(self) -> None:
        source = policy("html-120", interval=120)
        due = next_due(source)
        not_due = due + timedelta(minutes=30)
        fetcher = Mock(return_value=[1])
        value, decision, _ = execute_source(SourceOrchestrator(empty_state(), not_due), source, fetcher)
        self.assertIsNone(value)
        self.assertEqual(decision.decision, "skipped_not_due")
        fetcher.assert_not_called()

    def test_disabled_blocked_and_research_sources_make_zero_requests(self) -> None:
        cases = (
            (policy("disabled", enabled=False, state="implemented_disabled"), "skipped_disabled"),
            (policy("blocked", enabled=False, state="blocked"), "skipped_blocked"),
            (policy("research", enabled=False, state="roadmap"), "skipped_research"),
        )
        for source, expected in cases:
            with self.subTest(source=source.source_id):
                fetcher = Mock(return_value=[1])
                _, decision, _ = execute_source(SourceOrchestrator(empty_state(), AT), source, fetcher)
                self.assertEqual(decision.decision, expected)
                fetcher.assert_not_called()

    def test_confirmed_disabled_cis_sources_make_zero_requests(self) -> None:
        sources = (
            policy("cnpf_moldova", enabled=False, state="implemented_disabled", interval=30),
            policy("kz-kase", enabled=False, state="implemented_disabled", interval=360),
            policy("md-bvm", enabled=False, state="implemented_disabled", interval=720),
            policy("am-amx", enabled=False, state="blocked", interval=720),
        )
        for source in sources:
            fetcher = Mock()
            execute_source(SourceOrchestrator(empty_state(), AT), source, fetcher)
            fetcher.assert_not_called()

    def test_implemented_disabled_state_fails_closed_even_if_enabled_flag_drifts(self) -> None:
        source = policy("disabled-drift", enabled=True, state="implemented_disabled")
        fetcher = Mock(return_value=[1])
        _, decision, _ = execute_source(SourceOrchestrator(empty_state(), AT), source, fetcher)
        self.assertEqual(decision.decision, "skipped_disabled")
        fetcher.assert_not_called()

    def test_independent_intervals_and_utc_boundaries_are_deterministic(self) -> None:
        policies = [policy("feed", interval=30), policy("html", interval=120), policy("heavy", interval=360)]
        decisions_a = [SourceOrchestrator(empty_state(), AT).decide(item).decision for item in policies]
        decisions_b = [SourceOrchestrator(empty_state(), AT).decide(item).decision for item in policies]
        self.assertEqual(decisions_a, decisions_b)
        self.assertEqual(decisions_a[0], "eligible")
        self.assertIn("skipped_not_due", decisions_a)

    def test_same_slot_cannot_be_consumed_twice_after_state_reload(self) -> None:
        source = policy("feed", interval=30)
        state = empty_state()
        first = SourceOrchestrator(state, AT)
        decision = first.decide(source)
        first.begin(source, decision)
        reloaded = json.loads(json.dumps(state))
        self.assertEqual(SourceOrchestrator(reloaded, AT).decide(source).decision, "skipped_not_due")

    def test_content_fingerprint_distinguishes_changed_from_unchanged(self) -> None:
        source = policy("feed")
        state = empty_state()
        orchestrator = SourceOrchestrator(state, AT)
        self.assertTrue(content_changed(orchestrator, source, [{"id": "one"}]))
        self.assertFalse(content_changed(orchestrator, source, [{"id": "one"}]))
        self.assertTrue(content_changed(orchestrator, source, [{"id": "two"}]))


class OperationalStateTests(unittest.TestCase):
    def test_atomic_state_survives_process_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = OperationalStateStore(path)
            state = empty_state()
            state["committed"]["sources"]["feed"] = {"etag": '"v1"', "last_attempt_slot": 123}
            store.save(state)
            self.assertEqual(OperationalStateStore(path).load(), state)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*")), [])

    def test_missing_state_is_valid_and_slot_gating_prevents_all_source_storm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = OperationalStateStore(Path(directory) / "missing.json").load()
        policies = [policy("feed", interval=30), policy("html", interval=120), policy("heavy", interval=360)]
        decisions = [SourceOrchestrator(state, AT).decide(item).decision for item in policies]
        self.assertEqual(decisions.count("eligible"), 1)

    def test_corrupted_and_wrong_schema_state_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(OperationalStateError, "corrupted"):
                OperationalStateStore(path).load()
            path.write_text('{"schema_version":99,"sources":{}}', encoding="utf-8")
            with self.assertRaisesRegex(OperationalStateError, "schema"):
                OperationalStateStore(path).load()

    def test_state_and_public_artifacts_survive_a_second_python_process(self) -> None:
        artifact_paths = [
            ROOT / "data" / "precedent_transactions.json",
            ROOT / "output" / "build_manifest.json",
            ROOT / "output" / "deal_markets_brief.html",
            ROOT / "output" / "latest_snapshot.json",
            ROOT / "output" / "precedent_transactions.csv",
            ROOT / "output" / "precedent_transactions.xlsx",
        ]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifact_paths}
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(ROOT / "src")
            process_a = """
import sys
from datetime import datetime, timezone
from deal_markets_copilot.orchestrator import OperationalStateStore, SourceOrchestrator, SourcePolicy, empty_state
path = sys.argv[1]
policy = SourcePolicy.from_mapping("feed", {"enabled": True, "required": True, "implementation_state": "connected", "poll_interval_minutes": 30})
state = empty_state()
state["committed"]["sources"]["feed"] = {
    "etag": '"v1"',
    "last_modified": "Wed, 23 Jul 2026 11:00:00 GMT",
}
store = OperationalStateStore(path)
store.save(state)
transaction = store.begin()
orchestrator = SourceOrchestrator(transaction, datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc))
decision = orchestrator.decide(policy)
orchestrator.begin(policy, decision)
orchestrator.fail(policy, "http_429", retry_after=3600)
store.save(transaction)
store.finalize(accept_candidate=False)
"""
            subprocess.run(
                [sys.executable, "-c", process_a, str(state_path)],
                check=True,
                env=environment,
                capture_output=True,
                text=True,
            )
            process_b = """
import json, sys
from datetime import datetime, timezone
from deal_markets_copilot.orchestrator import OperationalStateStore, SourceOrchestrator, SourcePolicy
state = OperationalStateStore(sys.argv[1]).load()
policy = SourcePolicy.from_mapping("feed", {"enabled": True, "required": True, "implementation_state": "connected", "poll_interval_minutes": 30})
decision = SourceOrchestrator(state, datetime(2026, 7, 23, 12, 30, tzinfo=timezone.utc)).decide(policy)
source = state["committed"]["sources"]["feed"]
print(json.dumps({"decision": decision.decision, "etag": source["etag"], "last_modified": source["last_modified"], "failures": source["consecutive_failures"]}, sort_keys=True))
"""
            completed = subprocess.run(
                [sys.executable, "-c", process_b, str(state_path)],
                check=True,
                env=environment,
                capture_output=True,
                text=True,
            )
            restored = json.loads(completed.stdout)
        self.assertEqual(restored["decision"], "skipped_backoff")
        self.assertEqual(restored["etag"], '"v1"')
        self.assertEqual(restored["failures"], 1)
        after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifact_paths}
        self.assertEqual(after, before)


class BackoffTests(unittest.TestCase):
    def test_failure_increments_and_repeated_failures_increase_bounded_delay(self) -> None:
        source = policy("required", required=True, interval=30)
        state = empty_state()
        first = SourceOrchestrator(state, AT)
        first_next = first.fail(source, "failed_transport")
        self.assertEqual(state["committed"]["sources"]["required"]["consecutive_failures"], 1)
        second_at = AT + timedelta(minutes=30)
        second = SourceOrchestrator(state, second_at)
        second_next = second.fail(source, "failed_transport")
        self.assertGreater(
            datetime.fromisoformat(second_next),
            datetime.fromisoformat(first_next),
        )
        for index in range(12):
            SourceOrchestrator(state, AT + timedelta(hours=index + 2)).fail(source, "failed_http_429")
        capped = datetime.fromisoformat(state["committed"]["sources"]["required"]["next_eligible_at"]) - (AT + timedelta(hours=13))
        self.assertLessEqual(capped.total_seconds() / 60, MAX_BACKOFF_MINUTES)

    def test_retry_after_is_respected_within_cap_and_success_clears_backoff(self) -> None:
        source = policy("feed", interval=30)
        state = empty_state()
        orchestrator = SourceOrchestrator(state, AT)
        next_at = orchestrator.fail(source, "failed_http_429", retry_after=3600)
        self.assertGreaterEqual(datetime.fromisoformat(next_at), AT + timedelta(minutes=60))
        orchestrator.succeed(source, changed=False)
        self.assertEqual(state["committed"]["sources"]["feed"]["consecutive_failures"], 0)
        self.assertEqual(state["committed"]["sources"]["feed"]["next_eligible_at"], "")

    def test_disabled_source_ignores_stale_backoff(self) -> None:
        state = empty_state()
        state["committed"]["sources"]["disabled"] = {
            "next_eligible_at": (AT + timedelta(days=1)).isoformat(),
            "consecutive_failures": 5,
        }
        decision = SourceOrchestrator(state, AT).decide(
            policy("disabled", enabled=False, state="implemented_disabled")
        )
        self.assertEqual(decision.decision, "skipped_disabled")

    def test_one_execution_attempt_has_no_retry_loop(self) -> None:
        source = policy("feed", interval=30)
        fetcher = Mock(side_effect=OSError("TLS"))
        _, decision, _ = execute_source(SourceOrchestrator(empty_state(), AT), source, fetcher)
        self.assertEqual(decision.decision, "failed_transport")
        fetcher.assert_called_once()


class DiagnosticsAndIntegrationTests(unittest.TestCase):
    def test_diagnostics_are_one_row_per_source_and_sanitized(self) -> None:
        orchestrator = SourceOrchestrator(empty_state(), AT)
        sources = [
            policy("enabled", interval=30),
            policy("disabled", enabled=False, state="implemented_disabled"),
            policy("blocked", enabled=False, state="blocked"),
        ]
        for source in sources:
            execute_source(orchestrator, source, lambda: [])
        self.assertEqual(len(orchestrator.diagnostics), 3)
        rendered = "\n".join(format_diagnostic(row) for row in orchestrator.diagnostics)
        self.assertNotIn("Authorization", rendered)
        self.assertNotIn("Cookie", rendered)
        self.assertNotIn("/Users/", rendered)
        self.assertIn("skipped_disabled", rendered)
        self.assertIn("skipped_blocked", rendered)

    def test_offline_mixed_interval_scenario_only_calls_due_sources(self) -> None:
        feed = policy("feed-30", required=True, interval=30, detail_cap=2)
        html = policy("html-120", interval=120, detail_cap=1)
        heavy = policy("heavy-360", interval=360, detail_cap=1)
        disabled = policy("cnpf_moldova", enabled=False, state="implemented_disabled")
        blocked = policy("am-amx", enabled=False, state="blocked")
        optional = policy("optional-30", interval=30)
        at = next_due(html)
        calls: dict[str, int] = {}
        orchestrator = SourceOrchestrator(empty_state(), at)
        for source in (feed, html, heavy, disabled, blocked, optional):
            fetcher = Mock(return_value=[source.source_id])
            execute_source(orchestrator, source, fetcher)
            calls[source.source_id] = fetcher.call_count
        self.assertEqual(calls["feed-30"], 1)
        self.assertEqual(calls["html-120"], 1)
        self.assertEqual(calls["cnpf_moldova"], 0)
        self.assertEqual(calls["am-amx"], 0)
        self.assertLess(sum(calls.values()), len(calls))

    def test_one_source_failure_does_not_contaminate_another_state(self) -> None:
        state = empty_state()
        bad = policy("required", required=True)
        good = policy("optional")
        execute_source(SourceOrchestrator(state, AT), bad, Mock(side_effect=OSError("down")))
        execute_source(SourceOrchestrator(state, AT), good, Mock(return_value=[]))
        self.assertEqual(state["committed"]["sources"]["required"]["consecutive_failures"], 1)
        self.assertEqual(state["committed"]["sources"]["optional"]["consecutive_failures"], 0)

    def test_registered_long_interval_sources_have_stable_distributed_phases(self) -> None:
        configured = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        policies: list[SourcePolicy] = []
        for name, value in configured["orchestration"]["sources"].items():
            if value["enabled"] and value["poll_interval_minutes"] > 30:
                policies.append(SourcePolicy.from_mapping(value.get("source_id", name), value))
        for value in configured["cis_source_registry"]:
            if (
                value.get("enabled")
                and not value.get("orchestrated_by")
                and value.get("poll_interval_minutes", 30) > 30
            ):
                policies.append(SourcePolicy.from_mapping(value["id"], value))
        due_offsets = {}
        start = datetime(2026, 7, 23, 0, 0, tzinfo=UTC)
        for source in policies:
            due = next_due(source, start)
            interval_slots = source.poll_interval_minutes // 30
            due_offsets[source.source_id] = int(due.timestamp() // 1800) % interval_slots
        self.assertEqual(due_offsets, {
            "issuer_news": 1,
            "deal_archive": 7,
            "uz-uzse": 0,
        })
        expected = {
            source.source_id: int(
                hashlib.sha256(source.source_id.encode("utf-8")).hexdigest()[:8],
                16,
            ) % (source.poll_interval_minutes // 30)
            for source in policies
        }
        self.assertEqual(due_offsets, expected)


if __name__ == "__main__":
    unittest.main()
