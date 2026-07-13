from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deal_markets_copilot.classifier import classify_event
from deal_markets_copilot.models import Event
from deal_markets_copilot.report import _task_rows
from deal_markets_copilot.workflow import build_morning_workflow


def _item(event_id: str, title: str, source_type: str = "issuer_ir"):
    event = Event(
        event_id, "2026-07-10T10:00:00+03:00", title, "", "Source",
        f"https://example.com/{event_id}", source_type=source_type, confidence="confirmed",
    )
    return classify_event(event, [])


def _row(event_id: str, **updates) -> dict:
    row = {
        "deal_id": f"DL-{event_id}", "deal_type": "DCM", "record_kind": "deal",
        "status": "Issued", "target_or_issuer": "Issuer",
        "acquirer_or_investor": "Not applicable", "transaction_value": 5_000_000_000,
        "currency": "RUB", "quality_status": "approved", "quality_score": 100,
        "quality_flags": [], "evidence_label": "confirmed",
        "source_url": f"https://example.com/{event_id}",
    }
    row.update(updates)
    return row


def _task(item, row):
    workflow = build_morning_workflow(
        [item], [], {"deal_hypotheses": []}, deal_records=[row]
    )
    return workflow["tasks"]


class BankerTaskTests(unittest.TestCase):
    def test_dcm_review_missing_amount_currency_names_exact_terms(self) -> None:
        item = _item("dcm-missing", "Issuer announces bond placement")
        tasks = _task(item, _row(
            "dcm-missing", status="Confirmed", transaction_value=None,
            currency="Not disclosed", quality_status="review", quality_score=80,
            quality_flags=["missing_transaction_value", "missing_currency"],
        ))
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["priority"], "P1")
        self.assertIn("placement size, currency", tasks[0]["title"])
        self.assertIn("issuer, MOEX, NSD, or arranger", tasks[0]["title"])

    def test_approved_dcm_generates_market_update_not_missing_terms(self) -> None:
        tasks = _task(
            _item("dcm-approved", "Issuer placed bonds for RUB 5 billion"),
            _row("dcm-approved"),
        )
        self.assertIn("Add to DCM market update", tasks[0]["title"])
        self.assertIn("comparable transaction note", tasks[0]["title"])
        self.assertNotIn("confirm placement size", tasks[0]["title"])

    def test_weak_secondary_source_requires_official_confirmation(self) -> None:
        tasks = _task(
            _item("weak", "Issuer placed bonds for RUB 5 billion", "public_web"),
            _row(
                "weak", quality_status="review", quality_score=90,
                quality_flags=["single_secondary_source"], evidence_label="confirmed",
            ),
        )
        self.assertIn("Verify official source", tasks[0]["title"])
        self.assertEqual(tasks[0]["quality_status"], "review")
        self.assertNotIn("Add to DCM market update", tasks[0]["title"])

    def test_ma_template_identifies_missing_parties_and_economics(self) -> None:
        item = _item("ma-review", "Buyer considers acquisition of Target")
        tasks = _task(item, _row(
            "ma-review", deal_type="M&A", status="Reported",
            target_or_issuer="Not disclosed", acquirer_or_investor="Not disclosed",
            transaction_value=None, currency="Not disclosed", stake_percent=None,
            payment_form="Not disclosed", quality_status="review", quality_score=65,
            quality_flags=["missing_both_parties"],
        ))
        for field in ("target", "acquirer", "transaction value", "stake", "payment form"):
            self.assertIn(field, tasks[0]["title"])

    def test_ecm_template_identifies_missing_market_terms(self) -> None:
        item = _item("ecm-review", "Issuer announces equity offering")
        tasks = _task(item, _row(
            "ecm-review", deal_type="ECM", status="Announced",
            transaction_value=None, currency="Not disclosed", price_per_share=None,
            quality_status="review", quality_score=80,
            quality_flags=["missing_transaction_value", "missing_currency"],
        ))
        for field in ("offering amount", "currency", "offer price / share count"):
            self.assertIn(field, tasks[0]["title"])

    def test_approved_ma_generates_precedent_and_buyer_landscape_task(self) -> None:
        item = _item("ma-approved", "Buyer completed acquisition of Target for RUB 10 billion")
        tasks = _task(item, _row(
            "ma-approved", deal_type="M&A", status="Closed", target_or_issuer="Target",
            acquirer_or_investor="Buyer", transaction_value=10_000_000_000,
            stake_percent=None, payment_form="Not disclosed",
        ))
        self.assertIn("comparable transaction", tasks[0]["title"])
        self.assertIn("buyer-landscape", tasks[0]["title"])
        self.assertNotIn("confirm stake", tasks[0]["title"])

    def test_task_dashboard_shows_reason_and_required_source(self) -> None:
        item = _item("render", "Issuer announces bond placement")
        tasks = _task(item, _row(
            "render", status="Confirmed", transaction_value=None,
            currency="Not disclosed", quality_status="review", quality_score=80,
            quality_flags=["missing_transaction_value", "missing_currency"],
        ))
        rendered = _task_rows(tasks)
        self.assertIn("Blocking or decision-useful fields are missing", rendered)
        self.assertIn("issuer, MOEX, NSD, or arranger disclosure", rendered)

    def test_final_ecm_without_price_requests_missing_pricing_terms(self) -> None:
        item = _item("ecm-priced", "Issuer priced equity offering")
        tasks = _task(item, _row(
            "ecm-priced", deal_type="ECM", status="Priced", price_per_share=None,
        ))
        self.assertIn("offer price / share count", tasks[0]["title"])

    def test_technical_filing_generates_zero_tasks(self) -> None:
        item = _item("technical", "Issuer placed bonds for RUB 5 billion")
        tasks = _task(item, _row(
            "technical", record_kind="technical_filing", quality_status="review",
            quality_score=40, quality_flags=["technical_filing"],
        ))
        self.assertEqual(tasks, [])

    def test_cbr_lombard_and_moex_technical_notices_generate_zero_tasks(self) -> None:
        cases = (
            ("cbr-lombard", "Eligible securities added to the Bank of Russia collateral list"),
            ("moex-filing", "MOEX registered amendments to bond issue documents"),
        )
        for event_id, title in cases:
            with self.subTest(event_id=event_id):
                tasks = _task(_item(event_id, title), _row(
                    event_id, record_kind="technical_filing", quality_status="review",
                    quality_score=40, quality_flags=["technical_filing"],
                ))
                self.assertEqual(tasks, [])

    def test_production_whoosh_selectel_norilsk_yandex_regressions(self) -> None:
        rows = json.loads((ROOT / "data" / "precedent_transactions.json").read_text(encoding="utf-8"))
        by_id = {row["deal_id"]: row for row in rows}

        whoosh = by_id["DL-6871f1274c313bd9"]
        whoosh_tasks = _task(
            _item("6871f1274c313bd9", whoosh["headline"]), whoosh
        )
        self.assertEqual(whoosh["quality_status"], "review")
        self.assertIn("placement size, currency", whoosh_tasks[0]["title"])

        selectel = by_id["DL-af6397599d020a5f"]
        selectel_tasks = _task(
            _item("af6397599d020a5f", selectel["headline"]), selectel
        )
        self.assertEqual((selectel["transaction_value"], selectel["currency"]), (7_500_000_000.0, "RUB"))
        self.assertIn("7.5bn RUB", selectel_tasks[0]["title"])

        norilsk = next(
            row for row in rows
            if row.get("deal_type") == "DCM" and row.get("transaction_value") == 3_000_000_000
            and row.get("currency") == "CNY" and row.get("status") == "Issued"
        )
        norilsk_tasks = _task(
            _item(norilsk["deal_id"].removeprefix("DL-"), norilsk["headline"]), norilsk
        )
        self.assertEqual((norilsk["transaction_value"], norilsk["currency"]), (3_000_000_000, "CNY"))
        self.assertEqual(norilsk["status"], "Issued")
        self.assertIn("Verify official source", norilsk_tasks[0]["title"])

        yandex = by_id["DL-7a721642a53e0f1d"]
        yandex_tasks = _task(
            _item("7a721642a53e0f1d", yandex["headline"]), yandex
        )
        self.assertEqual(yandex["transaction_value"], 60_000_000_000)
        self.assertEqual(yandex["security_code"], "001Р-04; 001Р-05")
        self.assertEqual(yandex["status"], "Issued")
        self.assertIn("60bn RUB", yandex_tasks[0]["title"])
        self.assertNotIn("DL-f71ff729dc9f5af4", by_id)
        self.assertNotIn("DL-0da418122f0432fc", by_id)


if __name__ == "__main__":
    unittest.main()
