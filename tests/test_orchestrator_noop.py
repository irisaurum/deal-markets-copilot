from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from deal_markets_copilot.deals import extract_deal_record, update_precedent_database
from deal_markets_copilot.models import ClassifiedEvent, Event
from run import _presentation_fingerprint, _stable_source_transition


class NoopDeterminismTests(unittest.TestCase):
    def _record(self, observed_at: datetime):
        event = Event(
            event_id="fixture-issued-bond",
            published_at="2026-07-23T09:00:00+00:00",
            title="Fixture Bank issued bonds for 10 million USD",
            summary="The bonds were issued. ISIN US0000000001.",
            source="Fixture official feed",
            url="https://example.com/bond",
            source_type="official_issuer",
            confidence="confirmed",
            amount=10_000_000,
            currency="USD",
            issuer="Fixture Bank",
            instrument="Corporate bonds",
            isin="US0000000001",
            lifecycle_stage="Issued",
        )
        item = ClassifiedEvent(
            event=event,
            category="DCM",
            score=8,
            severity="high",
            banker_angle="DCM",
            next_action="Review",
            evidence_label="confirmed",
        )
        return extract_deal_record(item, [], observed_at=observed_at)

    def test_identical_observation_preserves_last_seen_dataset_sha_and_build_id(self) -> None:
        first_at = datetime(2026, 7, 23, 9, 30, tzinfo=timezone.utc)
        second_at = first_at + timedelta(hours=6)
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "precedents.json"
            first_rows = update_precedent_database([self._record(first_at)], dataset)
            first_bytes = dataset.read_bytes()
            first_hash = hashlib.sha256(first_bytes).hexdigest()
            second_rows = update_precedent_database([self._record(second_at)], dataset)
            second_bytes = dataset.read_bytes()
        self.assertEqual(first_rows[0]["last_seen_at"], first_at.isoformat(timespec="seconds"))
        self.assertEqual(second_rows[0]["last_seen_at"], first_rows[0]["last_seen_at"])
        self.assertEqual(second_bytes, first_bytes)
        self.assertEqual(hashlib.sha256(second_bytes).hexdigest(), first_hash)
        self.assertEqual(hashlib.sha256(second_bytes).hexdigest()[:12], first_hash[:12])

    def test_operational_health_timestamp_alone_is_not_publishable(self) -> None:
        previous = [{
            "name": "configured_rss",
            "status": "ok",
            "records": 3,
            "required": True,
            "checked_at": "2026-07-23T09:00:00+00:00",
        }]
        current = [{
            **previous[0],
            "status": "completed_unchanged",
            "checked_at": "2026-07-23T09:30:00+00:00",
        }]
        self.assertFalse(_stable_source_transition(current, previous))

    def test_stable_health_transition_is_publishable_once(self) -> None:
        ok = [{"name": "optional", "status": "ok", "required": False}]
        failed = [{"name": "optional", "status": "failed_transport", "required": False}]
        self.assertTrue(_stable_source_transition(failed, ok))
        self.assertFalse(_stable_source_transition(failed, [{"name": "optional", "status": "error"}]))

    def test_presentation_fingerprint_is_stable_and_excludes_operational_state(self) -> None:
        first = _presentation_fingerprint()
        second = _presentation_fingerprint()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)


if __name__ == "__main__":
    unittest.main()
