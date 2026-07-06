from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deal_markets_copilot.deals import select_key_deals


def _row(deal_id: str, days_ago: int = 0, **overrides) -> dict:
    row = {
        "deal_id": deal_id,
        "announced_date": (date.today() - timedelta(days=days_ago)).isoformat(),
        "deal_type": "DCM",
        "record_kind": "deal",
        "status": "Announced",
        "target_or_issuer": f"Issuer {deal_id}",
        "acquirer_or_investor": "Not applicable",
        "transaction_value": 1_000_000_000,
        "quality_status": "review",
        "quality_score": 70,
        "evidence_label": "confirmed",
        "score": 7,
        "headline": f"Issuer {deal_id} анонсировал размещение облигаций",
        "security_code": f"001P-{deal_id}",
    }
    row.update(overrides)
    return row


def _js_ids(rows: list[dict], limit: int = 10) -> list[str]:
    program = """
import { selectSummaryDeals } from './scripts/summary_selector.mjs';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const payload = JSON.parse(input);
process.stdout.write(JSON.stringify(selectSummaryDeals(payload.rows, payload.limit).map(row => row.deal_id)));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        cwd=ROOT,
        input=json.dumps({"rows": rows, "limit": limit}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def _python_ids(rows: list[dict], limit: int = 10) -> list[str]:
    return [row["deal_id"] for row in select_key_deals(rows, limit)]


class SummarySelectorParityTests(unittest.TestCase):
    def assert_selector_parity(self, rows: list[dict], limit: int = 10) -> None:
        self.assertEqual(_js_ids(rows, limit), _python_ids(rows, limit))

    def test_parity_excludes_non_key_and_watchlist_records_near_boundary(self) -> None:
        rows = [_row(f"eligible-{index}", days_ago=index + 1) for index in range(9)]
        rows.extend([
            _row(
                "missing-issuer-filing",
                status="Confirmed",
                target_or_issuer="Not disclosed",
                transaction_value=None,
                headline="О внесении изменений в решение о выпуске облигаций в части представителя владельцев",
            ),
            _row("watchlist", record_kind="watchlist", quality_status="review"),
            _row("technical", record_kind="technical_filing", quality_status="review"),
        ])
        self.assert_selector_parity(rows)

    def test_parity_keeps_approved_and_review_current_deals(self) -> None:
        rows = [
            _row("approved", quality_status="approved", quality_score=95),
            _row("review", days_ago=1, quality_status="review", quality_score=65),
        ]
        self.assert_selector_parity(rows)

    def test_parity_preserves_equal_rank_input_order(self) -> None:
        rows = [_row("tie-first"), _row("tie-second")]
        self.assert_selector_parity(rows)

    def test_parity_when_fewer_than_summary_limit(self) -> None:
        rows = [_row(f"few-{index}", days_ago=index) for index in range(4)]
        self.assert_selector_parity(rows, 10)

    def test_parity_when_more_than_summary_limit(self) -> None:
        rows = [_row(f"many-{index}", days_ago=index) for index in range(14)]
        self.assert_selector_parity(rows, 10)

    def test_parity_matches_exact_ids_and_order_at_limit(self) -> None:
        rows = [_row(f"rank-{index}", days_ago=index // 2, quality_score=80 - index) for index in range(12)]
        rows[1]["quality_status"] = "approved"
        rows.append(_row("technical-boundary", record_kind="technical_filing"))
        self.assert_selector_parity(rows, 10)


if __name__ == "__main__":
    unittest.main()
