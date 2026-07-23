from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from deal_markets_copilot.orchestrator import (
    OperationalStateStore,
    STATE_SCHEMA_VERSION,
    SourceOrchestrator,
    SourcePolicy,
    content_changed,
    empty_state,
)
from scripts import release_diagnostics


UTC = timezone.utc
AT = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
ARTIFACTS = (
    ROOT / "data" / "precedent_transactions.json",
    ROOT / "output" / "build_manifest.json",
    ROOT / "output" / "deal_markets_brief.html",
    ROOT / "output" / "latest_snapshot.json",
    ROOT / "output" / "precedent_transactions.csv",
    ROOT / "output" / "precedent_transactions.xlsx",
)


def policy(source_id: str, *, required: bool = False) -> SourcePolicy:
    return SourcePolicy.from_mapping(
        source_id,
        {
            "enabled": True,
            "required": required,
            "implementation_state": "connected",
            "poll_interval_minutes": 30,
            "max_feed_requests": 1,
            "max_detail_requests": 8,
        },
    )


def seeded_state() -> dict:
    state = empty_state()
    state["committed"]["sources"]["source-a"] = {
        "etag": '"old"',
        "last_modified": "Wed, 23 Jul 2026 10:00:00 GMT",
        "entry_fingerprints": {"old-id": "old-fingerprint"},
        "processed_entry_ids": ["old-id"],
        "last_success_at": (AT - timedelta(minutes=30)).isoformat(),
    }
    return state


def artifact_hashes() -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ARTIFACTS
    }


class StateTransactionTests(unittest.TestCase):
    def test_config_and_runtime_use_the_same_transactional_schema(self) -> None:
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["orchestration"]["state_schema_version"], STATE_SCHEMA_VERSION)
        self.assertEqual(STATE_SCHEMA_VERSION, 2)

    def _candidate_with_new_evidence(
        self,
        path: Path,
        *,
        fail_source: str | None = None,
        fail_required: bool = False,
    ) -> None:
        store = OperationalStateStore(path)
        store.save(seeded_state())
        transaction = store.begin()
        orchestrator = SourceOrchestrator(transaction, AT)
        source_a = policy("source-a")
        decision = orchestrator.decide(source_a)
        orchestrator.begin(source_a, decision)
        source_state = orchestrator.source_state("source-a")
        source_state.update(
            {
                "etag": '"new"',
                "last_modified": "Wed, 23 Jul 2026 11:30:00 GMT",
                "entry_fingerprints": {"new-id": "new-fingerprint"},
                "processed_entry_ids": ["old-id", "new-id"],
                "last_successful_poll_at": AT.isoformat(),
            }
        )
        orchestrator.succeed(source_a, changed=True)
        if fail_source:
            failed = policy(fail_source, required=fail_required)
            failed_decision = orchestrator.decide(failed)
            orchestrator.begin(failed, failed_decision)
            orchestrator.source_state(fail_source).update(
                {
                    "etag": '"partial-unaccepted"',
                    "entry_fingerprints": {"partial": "unsafe"},
                }
            )
            orchestrator.fail(
                failed,
                "http_429",
                result="failed_http",
                retry_after=3600,
            )
        store.save(transaction)

    def _finalize(
        self,
        path: Path,
        *,
        publish_delta: str,
        refresh: str,
        verifier: str,
        parent: str,
        publication: str,
    ) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return release_diagnostics.finalize_orchestration_state(
                path,
                publish_delta=publish_delta,
                refresh_outcome=refresh,
                verifier_outcome=verifier,
                parent_outcome=parent,
                publication_outcome=publication,
            )

    def test_verifier_stale_parent_commit_and_push_failures_keep_old_evidence(self) -> None:
        cases = {
            "strict-verifier": ("true", "success", "failure", "skipped", "skipped"),
            "stale-parent": ("true", "success", "success", "failure", "skipped"),
            "bot-commit": ("true", "success", "success", "success", "failure"),
            "bot-push": ("true", "success", "success", "success", "failure"),
        }
        for name, outcomes in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "state.json"
                self._candidate_with_new_evidence(path)
                self.assertEqual(
                    self._finalize(
                        path,
                        publish_delta=outcomes[0],
                        refresh=outcomes[1],
                        verifier=outcomes[2],
                        parent=outcomes[3],
                        publication=outcomes[4],
                    ),
                    0,
                )
                restored = OperationalStateStore(path).load()
                source = restored["committed"]["sources"]["source-a"]
                self.assertEqual(source["etag"], '"old"')
                self.assertEqual(source["entry_fingerprints"], {"old-id": "old-fingerprint"})
                self.assertEqual(source["processed_entry_ids"], ["old-id"])
                self.assertNotIn("last_successful_poll_at", source)

    def test_required_source_failure_preserves_backoff_and_rolls_back_other_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self._candidate_with_new_evidence(
                path,
                fail_source="source-b",
                fail_required=True,
            )
            self.assertEqual(
                self._finalize(
                    path,
                    publish_delta="false",
                    refresh="failure",
                    verifier="skipped",
                    parent="skipped",
                    publication="skipped",
                ),
                0,
            )
            restored = OperationalStateStore(path).load()
        self.assertEqual(restored["committed"]["sources"]["source-a"]["etag"], '"old"')
        failed = restored["committed"]["sources"]["source-b"]
        self.assertEqual(failed["consecutive_failures"], 1)
        self.assertEqual(failed["last_error_code"], "http_429")
        self.assertIn("next_eligible_at", failed)
        self.assertNotIn("etag", failed)
        self.assertNotIn("entry_fingerprints", failed)

    def test_optional_failure_patch_neither_wipes_old_state_nor_promotes_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self._candidate_with_new_evidence(path, fail_source="optional")
            self.assertEqual(
                self._finalize(
                    path,
                    publish_delta="true",
                    refresh="success",
                    verifier="failure",
                    parent="skipped",
                    publication="skipped",
                ),
                0,
            )
            restored = OperationalStateStore(path).load()
        self.assertEqual(restored["committed"]["sources"]["source-a"]["etag"], '"old"')
        self.assertEqual(
            restored["committed"]["sources"]["optional"]["last_error_code"],
            "http_429",
        )
        self.assertNotIn("entry_fingerprints", restored["committed"]["sources"]["optional"])

    def test_successful_noop_with_optional_failure_accepts_only_its_safe_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self._candidate_with_new_evidence(path, fail_source="optional")
            self.assertEqual(
                self._finalize(
                    path,
                    publish_delta="false",
                    refresh="success",
                    verifier="success",
                    parent="success",
                    publication="skipped",
                ),
                0,
            )
            restored = OperationalStateStore(path).load()
        self.assertEqual(restored["committed"]["sources"]["source-a"]["etag"], '"new"')
        optional = restored["committed"]["sources"]["optional"]
        self.assertEqual(optional["last_error_code"], "http_429")
        self.assertEqual(optional["consecutive_failures"], 1)
        self.assertNotIn("etag", optional)
        self.assertNotIn("entry_fingerprints", optional)

    def test_successful_noop_promotes_candidate_without_artifact_delta(self) -> None:
        before = artifact_hashes()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self._candidate_with_new_evidence(path)
            self.assertEqual(
                self._finalize(
                    path,
                    publish_delta="false",
                    refresh="success",
                    verifier="success",
                    parent="success",
                    publication="skipped",
                ),
                0,
            )
            restored = OperationalStateStore(path).load()
        self.assertEqual(restored["accepted_generation"], 1)
        self.assertEqual(restored["committed"]["sources"]["source-a"]["etag"], '"new"')
        self.assertEqual(artifact_hashes(), before)

    def test_successful_publication_promotes_before_deployment_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self._candidate_with_new_evidence(path)
            self.assertEqual(
                self._finalize(
                    path,
                    publish_delta="true",
                    refresh="success",
                    verifier="success",
                    parent="success",
                    publication="success",
                ),
                0,
            )
            accepted = OperationalStateStore(path).load()
            simulated_deployment_outcome = "failure"
            self.assertEqual(simulated_deployment_outcome, "failure")
            restored = OperationalStateStore(path).load()
        self.assertEqual(restored, accepted)
        self.assertEqual(restored["committed"]["sources"]["source-a"]["etag"], '"new"')

    def test_missing_or_malformed_publish_delta_fails_closed(self) -> None:
        for value in ("", "TRUE", "unexpected"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "state.json"
                self._candidate_with_new_evidence(path)
                self.assertEqual(
                    self._finalize(
                        path,
                        publish_delta=value,
                        refresh="success",
                        verifier="success",
                        parent="success",
                        publication="success",
                    ),
                    0,
                )
                source = OperationalStateStore(path).load()["committed"]["sources"]["source-a"]
                self.assertEqual(source["etag"], '"old"')

    def test_hard_cancellation_prefers_bounded_refetch_over_silent_skip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prior_path = Path(directory) / "prior.json"
            candidate_path = Path(directory) / "candidate.json"
            prior_store = OperationalStateStore(prior_path)
            prior_store.save(seeded_state())
            candidate_path.write_bytes(prior_path.read_bytes())
            self._candidate_with_new_evidence(candidate_path)
            restored = OperationalStateStore(prior_path).load()
            decision = SourceOrchestrator(restored, AT).decide(policy("source-a"))
        self.assertTrue(decision.eligible)
        self.assertEqual(restored["committed"]["sources"]["source-a"]["etag"], '"old"')


class TwoProcessTransactionTests(unittest.TestCase):
    def _run(self, program: str, path: Path) -> dict:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")
        completed = subprocess.run(
            [sys.executable, "-c", program, str(path)],
            check=True,
            env=environment,
            text=True,
            capture_output=True,
        )
        return json.loads(completed.stdout)

    def test_two_process_unpublished_change_is_reprocessed(self) -> None:
        process_a = """
import json, sys
from datetime import datetime, timezone
from deal_markets_copilot.orchestrator import OperationalStateStore, SourceOrchestrator, SourcePolicy, empty_state
path = sys.argv[1]
state = empty_state()
state["committed"]["sources"]["source-a"] = {"etag": '"old"', "entry_fingerprints": {"old": "1"}}
store = OperationalStateStore(path); store.save(state)
tx = store.begin(); o = SourceOrchestrator(tx, datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc))
p = SourcePolicy.from_mapping("source-a", {"enabled": True, "implementation_state": "connected", "poll_interval_minutes": 30})
d = o.decide(p); o.begin(p, d); o.source_state("source-a").update({"etag": '"new"', "entry_fingerprints": {"new": "2"}}); o.succeed(p, changed=True)
store.save(tx); store.finalize(accept_candidate=False)
print(json.dumps({"done": True}))
"""
        process_b = """
import json, sys
from datetime import datetime, timezone
from deal_markets_copilot.orchestrator import OperationalStateStore, SourceOrchestrator, SourcePolicy
state = OperationalStateStore(sys.argv[1]).load()
p = SourcePolicy.from_mapping("source-a", {"enabled": True, "implementation_state": "connected", "poll_interval_minutes": 30})
d = SourceOrchestrator(state, datetime(2026, 7, 23, 12, 30, tzinfo=timezone.utc)).decide(p)
s = state["committed"]["sources"]["source-a"]
print(json.dumps({"etag": s["etag"], "fingerprints": s["entry_fingerprints"], "eligible": d.eligible}, sort_keys=True))
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self._run(process_a, path)
            result = self._run(process_b, path)
        self.assertEqual(result, {"eligible": True, "etag": '"old"', "fingerprints": {"old": "1"}})

    def test_two_process_accepted_noop_restores_validators_and_eligibility(self) -> None:
        before = artifact_hashes()
        process_a = """
import json, sys
from datetime import datetime, timezone
from deal_markets_copilot.orchestrator import OperationalStateStore, SourceOrchestrator, SourcePolicy, empty_state
path = sys.argv[1]; store = OperationalStateStore(path); store.save(empty_state()); tx = store.begin()
o = SourceOrchestrator(tx, datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc))
p = SourcePolicy.from_mapping("source-a", {"enabled": True, "implementation_state": "connected", "poll_interval_minutes": 30})
d = o.decide(p); o.begin(p, d); o.source_state("source-a").update({"etag": '"accepted"', "last_modified": "Wed, 23 Jul 2026 11:30:00 GMT"}); o.succeed(p, changed=False)
store.save(tx); store.finalize(accept_candidate=True); print(json.dumps({"done": True}))
"""
        process_b = """
import json, sys
from datetime import datetime, timezone
from deal_markets_copilot.orchestrator import OperationalStateStore, SourceOrchestrator, SourcePolicy
state = OperationalStateStore(sys.argv[1]).load()
p = SourcePolicy.from_mapping("source-a", {"enabled": True, "implementation_state": "connected", "poll_interval_minutes": 30})
d = SourceOrchestrator(state, datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)).decide(p)
s = state["committed"]["sources"]["source-a"]
print(json.dumps({"etag": s["etag"], "generation": state["accepted_generation"], "decision": d.decision}, sort_keys=True))
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self._run(process_a, path)
            result = self._run(process_b, path)
        self.assertEqual(
            result,
            {"decision": "skipped_not_due", "etag": '"accepted"', "generation": 1},
        )
        self.assertEqual(artifact_hashes(), before)

    def test_two_process_publication_does_not_duplicate_accepted_event(self) -> None:
        process_a = """
import json, sys
from datetime import datetime, timezone
from deal_markets_copilot.orchestrator import OperationalStateStore, SourceOrchestrator, SourcePolicy, content_changed, empty_state
path = sys.argv[1]; store = OperationalStateStore(path); store.save(empty_state()); tx = store.begin()
o = SourceOrchestrator(tx, datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc))
p = SourcePolicy.from_mapping("source-a", {"enabled": True, "implementation_state": "connected", "poll_interval_minutes": 30})
d = o.decide(p); o.begin(p, d); changed = content_changed(o, p, [{"event_id": "new"}]); o.source_state("source-a")["processed_entry_ids"] = ["new"]; o.succeed(p, changed=changed)
store.save(tx); store.finalize(accept_candidate=True); print(json.dumps({"changed": changed}))
"""
        process_b = """
import json, sys
from datetime import datetime, timezone
from deal_markets_copilot.orchestrator import OperationalStateStore, SourceOrchestrator, SourcePolicy, content_changed
state = OperationalStateStore(sys.argv[1]).load(); o = SourceOrchestrator(state, datetime(2026, 7, 23, 12, 30, tzinfo=timezone.utc))
p = SourcePolicy.from_mapping("source-a", {"enabled": True, "implementation_state": "connected", "poll_interval_minutes": 30})
duplicate = content_changed(o, p, [{"event_id": "new"}])
print(json.dumps({"duplicate": duplicate, "processed": o.source_state("source-a")["processed_entry_ids"], "generation": state["accepted_generation"]}, sort_keys=True))
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            first = self._run(process_a, path)
            second = self._run(process_b, path)
        self.assertTrue(first["changed"])
        self.assertEqual(second, {"duplicate": False, "generation": 1, "processed": ["new"]})


if __name__ == "__main__":
    unittest.main()
