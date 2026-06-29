from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deal_markets_copilot.classifier import classify_event, deduplicate, stable_event_id
from deal_markets_copilot.deals import extract_deal_record, median_multiples, select_key_deals, update_precedent_database, write_precedents_csv
from deal_markets_copilot.models import Event
from deal_markets_copilot.report import _distinct_summary, _safe_url, build_html_report, build_telegram_digest
from deal_markets_copilot.sources import _date_from_title, effective_news_lookback, fetch_moex_disclosures, fetch_official_issuer_news, fetch_sec_deal_filings, filter_recent_events, load_demo_events, resolve_google_news_rows
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
            self.assertIn("Источники и подтверждения", text)
            self.assertIn("Демо-режим", text)
            self.assertIn("Что происходит на рынке сделок", text)
            self.assertIn("Что проверить сегодня", text)
            self.assertIn("Последние сделки рынка", text)
            self.assertIn("AUTO_REFRESH_MS", text)
            self.assertIn('class="deal-grid"', text)
            self.assertNotIn('class="sidebar"', text)

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

    def test_database_preserves_resolved_publisher_url(self) -> None:
        event = Event("resolved-1", "2026-06-27T08:00:00+03:00", "Ozon announces acquisition", "", "Publisher", "https://news.google.com/rss/articles/token")
        record = extract_deal_record(classify_event(event, self.coverage), self.coverage)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "precedents.json"
            rows = update_precedent_database([record], database)
            rows[0]["source_url"] = "https://publisher.example/direct-deal"
            database.write_text(json.dumps(rows), encoding="utf-8")
            refreshed = update_precedent_database([record], database)
            self.assertEqual(refreshed[0]["source_url"], "https://publisher.example/direct-deal")

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
            self.assertIn('class="deal-tile"', text)
            self.assertIn("КЛЮЧЕВЫЕ СДЕЛКИ", text)
            self.assertIn("precedent_transactions.xlsx", text)
            self.assertIn("Последние сделки рынка", text)
            self.assertIn("Свежие события", text)
            self.assertIn("Подтверждение ↗", text)

    def test_extracts_explicit_precedent_analytics_only(self) -> None:
        event = Event(
            event_id="analytics-1", published_at="2026-06-27T08:00:00+03:00",
            title="Buyer announces acquisition and merger deal for 75% of Target",
            summary="Enterprise value RUB 120 billion; revenue RUB 40 billion; EBITDA RUB 12 billion. Consideration is cash and shares. Financial advisor: Alpha Bank.",
            source="Target company release", url="https://target.example/deal", confidence="confirmed",
        )
        record = extract_deal_record(classify_event(event, []), [])
        self.assertEqual(record.enterprise_value, 120_000_000_000)
        self.assertIsNone(record.transaction_value)
        self.assertEqual(record.stake_percent, 75)
        self.assertEqual(record.payment_form, "Cash and shares")
        self.assertEqual(record.advisors, "Alpha Bank")
        self.assertEqual(record.ev_revenue, 3)
        self.assertEqual(record.ev_ebitda, 10)

    def test_quality_gate_rejects_price_target_as_deal_value(self) -> None:
        event = Event(
            event_id="nebius-price-target", published_at="2026-06-27T08:00:00+03:00",
            title="Nebius completes Eigen AI acquisition, analyst lifts stock price target to $280",
            summary="Analyst commentary after the acquisition",
            source="Market blog", url="https://example.com/nebius", confidence="unverified",
        )
        record = extract_deal_record(classify_event(event, self.coverage), self.coverage)
        self.assertIsNotNone(record)
        self.assertIsNone(record.transaction_value)
        self.assertEqual(record.acquirer_or_investor, "Not disclosed")
        self.assertEqual(record.quality_status, "rejected")
        self.assertIn("price_target_context", record.quality_flags)

    def test_normalized_deal_statuses(self) -> None:
        talks = Event(
            event_id="talks", published_at="2026-06-27T08:00:00+03:00",
            title="Yandex ведет переговоры о покупке Авто.ру", summary="",
            source="Press", url="https://example.com/talks", confidence="unverified",
        )
        closed = Event(
            event_id="closed", published_at="2026-06-27T08:00:00+03:00",
            title="Yandex завершил приобретение Авто.ру", summary="",
            source="Company", url="https://example.com/closed", confidence="confirmed",
        )
        denied = Event(
            event_id="denied", published_at="2026-06-27T08:00:00+03:00",
            title="Греф опроверг договоренность Сбера о покупке доли в Ozon", summary="Сделку оценивали в 300 млрд руб.",
            source="Press", url="https://example.com/denied", confidence="unverified",
        )
        talks_record = extract_deal_record(classify_event(talks, self.coverage), self.coverage)
        closed_record = extract_deal_record(classify_event(closed, self.coverage), self.coverage)
        denied_record = extract_deal_record(classify_event(denied, self.coverage), self.coverage)
        self.assertEqual(talks_record.status, "In talks")
        self.assertEqual(closed_record.status, "Closed")
        self.assertEqual(denied_record.status, "Denied")
        self.assertIsNone(denied_record.transaction_value)
        self.assertEqual(denied_record.quality_status, "review")

    def test_seller_is_not_mislabeled_as_acquirer(self) -> None:
        event = Event(
            event_id="vk-sale", published_at="2026-04-16T08:00:00+03:00",
            title="VK продал 25% акций Точка Банка: сделку оценили в 21,2 млрд ₽",
            summary="", source="Press", url="https://example.com/vk-sale", confidence="unverified",
        )
        record = extract_deal_record(classify_event(event, []), [])
        self.assertEqual(record.target_or_issuer, "Точка Банка")
        self.assertEqual(record.acquirer_or_investor, "Not disclosed")
        self.assertEqual(record.quality_status, "review")

    def test_same_deal_aggregates_multiple_sources(self) -> None:
        first = Event(
            event_id="source-a", published_at="2026-06-27T08:00:00+03:00",
            title="Яндекс закрыл сделку по покупке Авто.ру", summary="",
            source="Yandex IR", url="https://example.com/primary", confidence="confirmed", source_type="issuer_ir",
        )
        second = Event(
            event_id="source-b", published_at="2026-06-28T08:00:00+03:00",
            title="Яндекс завершил приобретение Авто.ру", summary="",
            source="Newswire", url="https://example.com/secondary", confidence="unverified",
        )
        records = [
            extract_deal_record(classify_event(first, self.coverage), self.coverage),
            extract_deal_record(classify_event(second, self.coverage), self.coverage),
        ]
        with tempfile.TemporaryDirectory() as directory:
            rows = update_precedent_database(records, Path(directory) / "precedents.json")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_count"], 2)
        self.assertEqual(rows[0]["evidence_label"], "confirmed")
        self.assertEqual({source["url"] for source in rows[0]["sources"]}, {
            "https://example.com/primary", "https://example.com/secondary",
        })

    def test_medians_use_valid_ma_multiples(self) -> None:
        stats = median_multiples([
            {"deal_type": "M&A", "ev_revenue": 2.0, "ev_ebitda": 8.0},
            {"deal_type": "M&A", "ev_revenue": 4.0, "ev_ebitda": 12.0},
            {"deal_type": "DCM", "ev_revenue": 99.0, "ev_ebitda": 99.0},
        ])
        self.assertEqual(stats["ev_revenue"], 3.0)
        self.assertEqual(stats["ev_ebitda"], 10.0)

    def test_official_moex_disclosure_uses_direct_url(self) -> None:
        payloads = [
            {"sitenews": {"columns": ["id", "title", "published_at", "tag"], "data": [[123, "О регистрации выпуска облигаций", "2026-06-27T10:00:00+03:00", "listing"]]}},
            {"content": {"columns": ["body"], "data": [["<p>Первичный документ</p>"]]}},
        ]
        with patch("deal_markets_copilot.sources._get_json", side_effect=payloads):
            events = fetch_moex_disclosures({"primary_sources": {"moex": {"enabled": True}}})
        self.assertEqual(events[0].url, "https://www.moex.com/n123")
        self.assertEqual(events[0].source_type, "official_exchange")
        self.assertEqual(events[0].confidence, "confirmed")

    def test_bond_buyback_is_dcm_not_ma(self) -> None:
        event = Event("bond-1", "2026-06-27T08:00:00+03:00", "О порядке приобретения облигаций серии 001P", "", "MOEX disclosure", "https://www.moex.com/n1", source_type="official_exchange", confidence="confirmed")
        self.assertEqual(classify_event(event, []).category, "DCM")

    def test_official_issuer_parser_extracts_date_and_direct_link(self) -> None:
        config = {"primary_sources": {"issuers": [{"name": "Issuer IR", "ticker": "TEST", "url": "https://issuer.example/news", "include_terms": ["сделк"]}]}}
        with patch("deal_markets_copilot.sources._get_text", return_value='<a href="/deal">2 июня 2026 Компания закрыла сделку</a>'), patch("deal_markets_copilot.sources._page_metadata", return_value=("", "Primary release")):
            events = fetch_official_issuer_news(config)
        self.assertEqual(events[0].published_at[:10], "2026-06-02")
        self.assertEqual(events[0].title, "Компания закрыла сделку")
        self.assertEqual(events[0].url, "https://issuer.example/deal")

    def test_russian_date_prefix(self) -> None:
        published, title = _date_from_title("19 июня 2026 Яндекс разместил облигации")
        self.assertEqual(published[:10], "2026-06-19")
        self.assertEqual(title, "Яндекс разместил облигации")
        published, title = _date_from_title("12/16/2024 Selectel приобрел Servers.ru")
        self.assertEqual(published[:10], "2024-12-16")
        self.assertEqual(title, "Selectel приобрел Servers.ru")

    def test_live_feed_excludes_old_official_archive_items(self) -> None:
        from datetime import datetime, timezone
        events = [
            Event("old", "2024-12-16T00:00:00+03:00", "Old acquisition", "", "Issuer IR", "https://example.com/old"),
            Event("new", "2026-06-27T12:00:00+03:00", "New acquisition", "", "Issuer IR", "https://example.com/new"),
        ]
        filtered = filter_recent_events(events, "3d", datetime(2026, 6, 28, 8, 0, tzinfo=timezone.utc))
        self.assertEqual([event.event_id for event in filtered], ["new"])

    def test_sec_transaction_filing_has_direct_archive_url(self) -> None:
        payload = {
            "name": "Example Corp",
            "filings": {"recent": {
                "form": ["8-K"], "filingDate": ["2026-06-20"], "items": ["2.01"],
                "accessionNumber": ["0001234567-26-000001"], "primaryDocument": ["deal.htm"],
                "primaryDocDescription": ["Completion of acquisition"],
            }},
        }
        config = {"primary_sources": {"sec_edgar": {"enabled": True, "archive_days": 900, "companies": [{"ticker": "EX", "cik": "1234567"}]}}}
        with patch("deal_markets_copilot.sources._get_json", return_value=payload):
            events = fetch_sec_deal_filings(config)
        self.assertEqual(events[0].source, "SEC EDGAR")
        self.assertEqual(events[0].source_type, "official_regulator")
        self.assertEqual(events[0].url, "https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/deal.htm")

    def test_google_rows_upgrade_only_when_direct_url_resolves(self) -> None:
        rows = [{"source_url": "https://news.google.com/rss/articles/token"}]
        with patch("deal_markets_copilot.sources.resolve_google_news_url", return_value="https://publisher.example/deal"):
            upgraded = resolve_google_news_rows(rows, workers=1)
        self.assertEqual(upgraded, 1)
        self.assertEqual(rows[0]["source_url"], "https://publisher.example/deal")

    def test_key_deals_exclude_technical_exchange_notices(self) -> None:
        rows = [
            {"deal_id": "technical", "announced_date": "2026-06-28", "deal_type": "DCM", "status": "Reported", "target_or_issuer": "Not disclosed", "acquirer_or_investor": "Not applicable", "transaction_value": None, "score": 8, "headline": "О регистрации изменений в эмиссионные документы"},
            {"deal_id": "ma", "announced_date": "2026-06-27", "deal_type": "M&A", "status": "Completed", "target_or_issuer": "Auto.ru", "acquirer_or_investor": "T-Technologies", "transaction_value": 35_000_000_000, "score": 7, "headline": "Т-Технологии купили Auto.ru у Яндекса"},
            {"deal_id": "dcm", "announced_date": "2026-06-26", "deal_type": "DCM", "status": "Announced", "target_or_issuer": "Selectel", "acquirer_or_investor": "Not applicable", "transaction_value": 5_000_000_000, "score": 5, "headline": "Selectel анонсировал размещение облигаций"},
        ]
        self.assertEqual([row["deal_id"] for row in select_key_deals(rows)], ["ma", "dcm"])


if __name__ == "__main__":
    unittest.main()
