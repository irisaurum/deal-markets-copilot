from __future__ import annotations

import json
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
            state["sources"]["feed"] = {"etag": '"v1"', "last_attempt_slot": 123}
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


class BackoffTests(unittest.TestCase):
    def test_failure_increments_and_repeated_failures_increase_bounded_delay(self) -> None:
        source = policy("required", required=True, interval=30)
        state = empty_state()
        first = SourceOrchestrator(state, AT)
        first_next = first.fail(source, "failed_transport")
        self.assertEqual(state["sources"]["required"]["consecutive_failures"], 1)
        second_at = AT + timedelta(minutes=30)
        second = SourceOrchestrator(state, second_at)
        second_next = second.fail(source, "failed_transport")
        self.assertGreater(
            datetime.fromisoformat(second_next),
            datetime.fromisoformat(first_next),
        )
        for index in range(12):
            SourceOrchestrator(state, AT + timedelta(hours=index + 2)).fail(source, "failed_http_429")
        capped = datetime.fromisoformat(state["sources"]["required"]["next_eligible_at"]) - (AT + timedelta(hours=13))
        self.assertLessEqual(capped.total_seconds() / 60, MAX_BACKOFF_MINUTES)

    def test_retry_after_is_respected_within_cap_and_success_clears_backoff(self) -> None:
        source = policy("feed", interval=30)
        state = empty_state()
        orchestrator = SourceOrchestrator(state, AT)
        next_at = orchestrator.fail(source, "failed_http_429", retry_after=3600)
        self.assertGreaterEqual(datetime.fromisoformat(next_at), AT + timedelta(minutes=60))
        orchestrator.succeed(source, changed=False)
        self.assertEqual(state["sources"]["feed"]["consecutive_failures"], 0)
        self.assertEqual(state["sources"]["feed"]["next_eligible_at"], "")

    def test_disabled_source_ignores_stale_backoff(self) -> None:
        state = empty_state()
        state["sources"]["disabled"] = {
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
        self.assertEqual(state["sources"]["required"]["consecutive_failures"], 1)
        self.assertEqual(state["sources"]["optional"]["consecutive_failures"], 0)


if __name__ == "__main__":
    unittest.main()
