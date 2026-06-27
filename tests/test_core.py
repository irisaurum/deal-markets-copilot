from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deal_markets_copilot.classifier import classify_event, deduplicate, stable_event_id
from deal_markets_copilot.deals import extract_deal_record, update_precedent_database, write_precedents_csv
from deal_markets_copilot.models import Event
from deal_markets_copilot.report import _distinct_summary, _safe_url, build_html_report, build_telegram_digest
from deal_markets_copilot.sources import effective_news_lookback, load_demo_events
from deal_markets_copilot.workflow import build_morning_workflow


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.coverage = [{"ticker": "OZON", "company": "Ozon", "aliases": ["Ozon", "Озон"]}]

    def test_ma_classification_and_coverage(self) -> None:
        event = Event(
            event_id="1", published_at="2026-06-27T08:00:00+03:00",
            title="Ozon announces acquisition", summary="Strategic buyout",
            source="Company", url="https://example.com", confidence="confirmed",
        )
        result = classify_event(event, self.coverage)
        self.assertEqual(result.category, "M&A")
        self.assertIn("OZON", result.matched_coverage)
        self.assertGreaterEqual(result.score, 6)

    def test_deduplicate(self) -> None:
        event = Event("x", "", "Title", "", "Source", "https://example.com")
        self.assertEqual(len(deduplicate([event, event])), 1)

    def test_near_duplicate_prefers_stronger_source(self) -> None:
        weak = Event("a", "", "Яндекс продал Авто.ру за 35 млрд рублей", "", "Blog", "https://a")
        strong = Event("b", "", "Т-Технологии закрыли сделку по покупке Авто.ру у Яндекса за 35 млрд рублей", "", "Интерфакс", "https://b")
        result = deduplicate([weak, strong])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "Интерфакс")

    def test_stable_id(self) -> None:
        self.assertEqual(stable_event_id("A", "B"), stable_event_id("A", "B"))

    def test_demo_load_and_report(self) -> None:
        events = load_demo_events(ROOT / "data" / "sample_events.json")
        self.assertEqual(len(deduplicate(events)), 5)
        items = [classify_event(event, self.coverage) for event in deduplicate(events)]
        with tempfile.TemporaryDirectory() as directory:
            workflow = build_morning_workflow(items, [], {"deal_hypotheses": []})
            path = build_html_report(
                items, {"report_title": "Test"}, Path(directory) / "report.html", "demo", workflow=workflow
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("EVIDENCE LEDGER", text)
            self.assertIn("DEMO DATA", text)
            self.assertIn("Не является Bloomberg Terminal", text)
            self.assertIn("BANKER ACTION QUEUE", text)
            self.assertIn("Что изменилось", text)
            self.assertIn("AUTO_REFRESH_MS", text)
            self.assertIn("DAILY DEAL FLOW", text)

    def test_workflow_detects_new_events_and_keeps_stable_tasks(self) -> None:
        event = Event(
            event_id="event-1", published_at="2026-06-27T08:00:00+03:00",
            title="Ozon announces acquisition", summary="Strategic buyout",
            source="Company", url="https://example.com", confidence="confirmed",
        )
        item = classify_event(event, self.coverage)
        config = {"deal_hypotheses": [{
            "id": "H-01", "title": "Ozon scenario", "tickers": ["OZON"],
            "monitor_categories": ["M&A"],
        }]}
        first = build_morning_workflow([item], [], config, {})
        self.assertEqual(first["new_signals"], 1)
        self.assertEqual(first["hypotheses"][0]["status"], "attention")
        previous = {"workflow_version": 1, "events": [item.to_dict()]}
        second = build_morning_workflow([item], [], config, previous)
        self.assertEqual(second["new_signals"], 0)
        self.assertEqual(first["tasks"][0]["id"], second["tasks"][0]["id"])

    def test_telegram_digest_escapes_html(self) -> None:
        event = Event("1", "", "A < B", "", "Source", "")
        digest = build_telegram_digest([classify_event(event, [])])
        self.assertIn("A &lt; B", digest)

    def test_repeated_rss_summary_is_hidden(self) -> None:
        title = "Ozon выплатил дивиденды за 2025 год — AKM.RU"
        summary = "Ozon выплатил дивиденды за 2025 год. AKM.RU"
        self.assertEqual(_distinct_summary(title, summary), "")
        self.assertEqual(
            _distinct_summary(title, "Совет директоров также утвердил новую дивидендную политику."),
            "Совет директоров также утвердил новую дивидендную политику.",
        )

    def test_daily_news_window_and_weekend_catchup(self) -> None:
        from datetime import datetime

        config = {"news_lookback": "1d", "catchup_lookback": "3d"}
        self.assertEqual(effective_news_lookback(config, datetime(2026, 6, 23, 9, 0)), "1d")
        self.assertEqual(effective_news_lookback(config, datetime(2026, 6, 27, 9, 0)), "3d")
        self.assertEqual(effective_news_lookback(config, datetime(2026, 6, 29, 9, 0)), "3d")

    def test_external_links_allow_only_http_and_https(self) -> None:
        self.assertEqual(_safe_url("https://example.com/story"), "https://example.com/story")
        self.assertEqual(_safe_url("javascript:alert(1)"), "#")
        self.assertEqual(_safe_url("file:///Users/example/private.txt"), "#")

    def test_extracts_dcm_deal_card_without_inventing_fields(self) -> None:
        event = Event(
            event_id="selectel-1", published_at="Wed, 24 Jun 2026 10:00:00 GMT",
            title="Selectel разместит облигации на 5 млрд руб. для рефинансирования и инвестиций - ComNews.ru",
            summary="", source="ComNews.ru", url="https://example.com/selectel",
        )
        record = extract_deal_record(classify_event(event, []), [])
        self.assertIsNotNone(record)
        self.assertEqual(record.target_or_issuer, "Selectel")
        self.assertEqual(record.transaction_value, 5_000_000_000)
        self.assertEqual(record.currency, "RUB")
        self.assertEqual(record.instrument, "Bonds")
        self.assertEqual(record.rationale, "рефинансирования и инвестиций")
        self.assertEqual(record.sector, "Not classified")

    def test_precedent_database_deduplicates_and_exports_csv(self) -> None:
        event = Event(
            event_id="deal-1", published_at="2026-06-27T08:00:00+03:00",
            title="Ozon considers a new bond", summary="RUB 5 billion refinancing",
            source="Company release", url="https://example.com/deal", confidence="confirmed",
        )
        record = extract_deal_record(classify_event(event, self.coverage), self.coverage)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "precedents.json"
            rows = update_precedent_database([record, record], database)
            self.assertEqual(len(rows), 1)
            csv_path = write_precedents_csv(rows, Path(directory) / "precedents.csv")
            self.assertIn("deal_id,announced_date,deal_type", csv_path.read_text(encoding="utf-8-sig"))

    def test_report_contains_deal_card_and_excel_export(self) -> None:
        event = Event(
            event_id="deal-2", published_at="2026-06-27T08:00:00+03:00",
            title="Ozon considers a new bond", summary="RUB 5 billion refinancing",
            source="Company release", url="https://example.com/deal", confidence="confirmed",
        )
        item = classify_event(event, self.coverage)
        record = extract_deal_record(item, self.coverage)
        with tempfile.TemporaryDirectory() as directory:
            path = build_html_report(
                [item], {}, Path(directory) / "report.html", "live",
                precedent_transactions=[record.to_dict()],
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("LATEST DEAL CARD", text)
            self.assertIn("PRECEDENT TRANSACTIONS", text)
            self.assertIn("precedent_transactions.xlsx", text)


if __name__ == "__main__":
    unittest.main()
