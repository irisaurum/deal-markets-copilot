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
from deal_markets_copilot.deals import enrich_precedent_financials, extract_deal_record, median_multiples, merge_curated_precedents, select_deal_buckets, select_key_deals, update_precedent_database, write_precedents_csv
from deal_markets_copilot.models import Event
from deal_markets_copilot.report import _distinct_summary, _safe_url, build_html_report, build_telegram_digest
from deal_markets_copilot.sources import _date_from_title, effective_news_lookback, fetch_configured_sources, fetch_moex_disclosures, fetch_official_issuer_news, fetch_sec_deal_filings, filter_recent_events, load_demo_events, resolve_google_news_rows
from deal_markets_copilot.workflow import build_morning_workflow, is_actionable_signal


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
        version_two = build_morning_workflow([item], [], config, {"workflow_version": 2, "events": [item.to_dict()]})
        self.assertEqual(version_two["new_signals"], 0)

    def test_workflow_suppresses_technical_exchange_notices(self) -> None:
        event = Event(
            event_id="moex-buyback", published_at="2026-07-03T14:33:00+03:00",
            title="О проведении выкупа облигаций с 06 по 10 июля 2026 года",
            summary="Техническое уведомление Московской биржи", source="MOEX",
            url="https://www.moex.com/n101755", confidence="confirmed",
        )
        item = classify_event(event, [])
        self.assertFalse(is_actionable_signal(item))
        workflow = build_morning_workflow([item], [], {"deal_hypotheses": []})
        self.assertEqual(workflow["new_signals"], 0)
        self.assertEqual(workflow["tasks"], [])

    def test_rss_transport_failure_is_not_silently_successful(self) -> None:
        config = {"sources": [{"name": "Test RSS", "url": "https://example.com/rss", "enabled": True}]}
        with patch("deal_markets_copilot.sources.fetch_feed", side_effect=OSError("offline")):
            with self.assertRaises(RuntimeError):
                fetch_configured_sources(config)

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
        priced = Event(
            event_id="priced", published_at="2026-06-27T08:00:00+03:00",
            title="МТС закрыла книгу заявок на облигации объемом 20 млрд рублей", summary="",
            source="Company", url="https://example.com/priced", confidence="confirmed",
        )
        issued = Event(
            event_id="issued", published_at="2026-06-30T08:00:00+03:00",
            title="ВУШ завершил первый этап размещения облигаций", summary="",
            source="Press", url="https://example.com/issued", confidence="unverified",
        )
        talks_record = extract_deal_record(classify_event(talks, self.coverage), self.coverage)
        closed_record = extract_deal_record(classify_event(closed, self.coverage), self.coverage)
        denied_record = extract_deal_record(classify_event(denied, self.coverage), self.coverage)
        priced_record = extract_deal_record(classify_event(priced, self.coverage), self.coverage)
        issued_record = extract_deal_record(classify_event(issued, self.coverage), self.coverage)
        self.assertEqual(talks_record.status, "In talks")
        self.assertEqual(closed_record.status, "Closed")
        self.assertEqual(denied_record.status, "Denied")
        self.assertEqual(priced_record.status, "Priced")
        self.assertEqual(issued_record.status, "Issued")
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
        eligible = {"record_kind": "deal", "quality_status": "approved", "status": "Closed", "announced_date": "2024-01-01", "financials_available_at": "2023-12-01", "enterprise_value": 100, "currency": "USD", "financials_currency": "USD", "revenue_ltm": 50}
        stats = median_multiples([
            {**eligible, "deal_type": "M&A", "ev_revenue": 2.0, "ev_ebitda": 8.0, "ebitda_ltm": 12.5},
            {**eligible, "deal_type": "M&A", "ev_revenue": 4.0, "ev_ebitda": 12.0, "ebitda_ltm": 8.3},
            {**eligible, "deal_type": "M&A", "quality_status": "review", "ev_revenue": 99.0, "ev_ebitda": 99.0},
        ])
        self.assertEqual(stats["ev_revenue"], 3.0)
        self.assertEqual(stats["ev_ebitda"], 10.0)
        self.assertEqual(stats["ev_revenue_count"], 2)
        self.assertEqual(stats["ev_ebitda_count"], 2)

    def test_medians_exclude_financials_published_after_announcement(self) -> None:
        base = {"deal_type": "M&A", "record_kind": "deal", "quality_status": "approved", "status": "Closed", "announced_date": "2024-01-01", "enterprise_value": 100, "currency": "USD", "financials_currency": "USD", "revenue_ltm": 50, "ev_revenue": 2.0}
        stats = median_multiples([
            {**base, "financials_available_at": "2023-12-15"},
            {**base, "deal_id": "late", "financials_available_at": "2024-02-01", "ev_revenue": 20.0},
        ])
        self.assertEqual(stats["ev_revenue"], 2.0)
        self.assertEqual(stats["coverage"], 1)

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
        self.assertEqual(classify_event(event, []).score, 0)

    def test_classifier_routes_funds_ofz_and_registration_notices_out_of_deals(self) -> None:
        titles = (
            "Московская биржа начала торги паями активно управляемого БПИФ",
            "Итоги аукциона ОФЗ Минфина",
            "О регистрации программы и проспекта биржевых облигаций",
            "ВТБ получил в залог крупный пакет акций Ozon",
        )
        for index, title in enumerate(titles):
            item = classify_event(Event(str(index), "2026-07-03", title, "", "MOEX", "https://example.com"), self.coverage)
            self.assertEqual(item.score, 0)

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

    def test_key_deals_exclude_funds_units_and_ofz_auctions(self) -> None:
        rows = [
            {"deal_id": "fund", "announced_date": "2026-07-01", "deal_type": "ECM", "record_kind": "deal", "quality_status": "approved", "headline": "Московская биржа начала торги паями БПИФ", "score": 9},
            {"deal_id": "ofz", "announced_date": "2026-07-01", "deal_type": "DCM", "record_kind": "deal", "quality_status": "approved", "headline": "Итоги аукциона ОФЗ Минфина", "score": 9},
            {"deal_id": "real", "announced_date": "2026-07-01", "deal_type": "M&A", "record_kind": "deal", "quality_status": "approved", "headline": "Buyer acquired Target", "target_or_issuer": "Target", "acquirer_or_investor": "Buyer", "score": 7},
        ]
        self.assertEqual([row["deal_id"] for row in select_key_deals(rows)], ["real"])

    def test_key_deals_never_mix_historical_curated_precedents_into_live_flow(self) -> None:
        rows = [
            {"deal_id": "CURATED-MA-OLD-2022", "announced_date": "2022-01-01", "deal_type": "M&A", "record_kind": "deal", "quality_status": "approved", "headline": "Buyer acquired Old Target", "target_or_issuer": "Old Target", "acquirer_or_investor": "Buyer", "score": 10},
            {"deal_id": "LIVE-2026", "announced_date": "2026-06-01", "deal_type": "M&A", "record_kind": "deal", "quality_status": "approved", "headline": "Buyer acquired Current Target", "target_or_issuer": "Current Target", "acquirer_or_investor": "Buyer", "score": 8},
        ]
        self.assertEqual([row["deal_id"] for row in select_key_deals(rows)], ["LIVE-2026"])

    def test_database_clears_fields_that_do_not_belong_to_deal_type(self) -> None:
        event = Event("typed-dcm", "2026-07-01T10:00:00+03:00", "Selectel разместил облигации на 5 млрд рублей", "ISIN RU000A10TEST", "Issuer IR", "https://example.com/dcm", source_type="issuer_ir", confidence="confirmed")
        record = extract_deal_record(classify_event(event, []), [])
        with tempfile.TemporaryDirectory() as directory:
            row = update_precedent_database([record], Path(directory) / "precedents.json")[0]
        self.assertEqual(row["deal_type"], "DCM")
        self.assertIsNone(row["stake_percent"])
        self.assertEqual(row["payment_form"], "Not applicable")
        self.assertEqual(row["seller"], "Not applicable")
        self.assertIsNone(row["enterprise_value"])

    def test_moex_results_are_structured_filing_not_top_deal(self) -> None:
        event = Event(
            "moex-results", "2026-06-29T12:19:22+03:00", "Итоги выпуска биржевых облигаций",
            'Извещаем об итогах размещения следующих эмитентов: "Газпромбанк" (Акционерное общество). '
            'Регистрационный номер выпуска биржевых облигаций: 4B02-05-00354-B-006P. '
            'Объем размещенных биржевых облигаций по номинальной стоимости: 3 930 247 000 руб. '
            'Доля размещенных облигаций: 78,6%.',
            "MOEX disclosure", "https://www.moex.com/n1", source_type="official_exchange", confidence="confirmed",
        )
        record = extract_deal_record(classify_event(event, []), [])
        self.assertEqual(record.record_kind, "technical_filing")
        self.assertEqual(record.target_or_issuer, "Газпромбанк")
        self.assertEqual(record.transaction_value, 3_930_247_000)
        self.assertEqual(record.currency, "RUB")
        self.assertIsNone(record.stake_percent)
        self.assertEqual(record.quality_status, "review")
        self.assertEqual(select_key_deals([record.to_dict()]), [])

    def test_dcm_yuan_currency_is_not_converted_to_rubles(self) -> None:
        event = Event(
            "yuan-bond", "2026-06-10T10:00:00+03:00",
            '"Норникель" зафиксировал объем размещения облигаций на уровне 3 млрд юаней', "",
            "Интерфакс", "https://example.com/yuan",
        )
        record = extract_deal_record(classify_event(event, []), [])
        self.assertEqual(record.transaction_value, 3_000_000_000)
        self.assertEqual(record.currency, "CNY")

    def test_dcm_card_extracts_coupon_maturity_and_isin(self) -> None:
        event = Event(
            "bond-terms", "2026-06-29T10:00:00+03:00",
            "Selectel разместил облигации объемом 3 млрд рублей",
            "Купонная ставка 18,5%. Дата погашения 30.06.2029. Срок обращения 3 года. ISIN RU000A10TEST.",
            "Issuer IR", "https://example.com/bond", source_type="issuer_ir", confidence="confirmed",
        )
        record = extract_deal_record(classify_event(event, []), [])
        self.assertEqual(record.coupon_rate, 18.5)
        self.assertEqual(record.maturity_date, "2029-06-30")
        self.assertEqual(record.tenor, "3 года")
        self.assertEqual(record.isin, "RU000A10TEST")

    def test_ma_card_separates_buyer_target_and_seller(self) -> None:
        event = Event(
            "sale-parties", "2026-06-29T10:00:00+03:00",
            "Yandex продал 25% акций Auto.ru компании T-Tech за 35 млрд рублей", "",
            "Company release", "https://example.com/sale", confidence="confirmed",
        )
        record = extract_deal_record(classify_event(event, []), [])
        self.assertEqual(record.target_or_issuer, "Auto.ru")
        self.assertEqual(record.acquirer_or_investor, "T-Tech")
        self.assertEqual(record.seller, "Yandex")
        self.assertEqual(record.stake_percent, 25)
        self.assertEqual(record.payment_form, "Not disclosed")

    def test_ecm_card_extracts_transaction_terms(self) -> None:
        event = Event(
            "ecm-terms", "2026-06-29T10:00:00+03:00", "Ozon объявил SPO объемом 20 млрд рублей",
            "Offering price 3200 RUB per share; discount 5.5%; free float 18%; Bookrunners: VTB Capital and Alfa Bank.",
            "Issuer IR", "https://example.com/spo", source_type="issuer_ir", confidence="confirmed",
        )
        record = extract_deal_record(classify_event(event, self.coverage), self.coverage)
        self.assertEqual(record.price_per_share, 3200)
        self.assertEqual(record.discount_percent, 5.5)
        self.assertEqual(record.free_float_percent, 18)
        self.assertEqual(record.bookrunners, "VTB Capital and Alfa Bank")

    def test_report_separates_deal_monitoring_streams(self) -> None:
        events = [
            Event("deal", "2026-06-29T10:00:00+03:00", "Ozon разместил облигации на 5 млрд рублей", "", "IR", "https://example.com/deal", confidence="confirmed"),
            Event("rumor", "2026-06-29T09:00:00+03:00", "Yandex может купить Ozon", "", "Press", "https://example.com/rumor"),
            Event("denial", "2026-06-29T08:00:00+03:00", "Yandex опроверг покупку Ozon", "", "Press", "https://example.com/denial"),
            Event("filing", "2026-06-29T07:00:00+03:00", "О регистрации выпуска биржевых облигаций", "Наименование Эмитента Ozon Наименование ценной бумаги облигации", "MOEX", "https://example.com/filing", source_type="official_exchange", confidence="confirmed"),
            Event("routine-dcm", "2026-06-29T06:00:00+03:00", "ВУШ завершил первый этап размещения облигаций", "", "Press", "https://example.com/routine-dcm"),
        ]
        records = [extract_deal_record(classify_event(event, self.coverage), self.coverage) for event in events]
        buckets = select_deal_buckets([record.to_dict() for record in records])
        self.assertEqual({key: len(value) for key, value in buckets.items()}, {"deal": 1, "watchlist": 1, "denial": 1, "technical_filing": 1})
        with tempfile.TemporaryDirectory() as directory:
            items = [classify_event(event, self.coverage) for event in events]
            path = build_html_report(items, {}, Path(directory) / "report.html", "live", precedent_transactions=[record.to_dict() for record in records])
            text = path.read_text(encoding="utf-8")
            self.assertIn("Актуальные сделки", text)
            self.assertIn("Требует проверки", text)
            self.assertIn("Опровержения", text)
            self.assertIn("Technical filings", text)
            self.assertIn("Купон", text)

    def test_financial_enrichment_calculates_only_aligned_currency_multiples(self) -> None:
        deals = [{
            "deal_id": "curated-1", "announced_date": "2022-05-26", "deal_type": "M&A",
            "record_kind": "deal", "status": "Closed", "target_or_issuer": "Target",
            "acquirer_or_investor": "Buyer", "seller": "Shareholders", "headline": "Buyer acquired Target",
            "enterprise_value": 1200, "transaction_value": 1000, "currency": "USD",
            "evidence_label": "confirmed", "source_name": "Deal release", "source_url": "https://example.com/deal",
            "sources": [{"name": "Deal release", "url": "https://example.com/deal", "evidence_label": "confirmed", "source_type": "issuer_ir"}],
        }]
        financials = [{
            "deal_id": "curated-1", "period_end": "2021-12-31", "available_at": "2022-03-01",
            "currency": "USD", "revenue": 400, "ebitda": 100, "metric_basis": "Audited GAAP",
            "source_name": "10-K", "source_url": "https://www.sec.gov/example",
        }]
        row = enrich_precedent_financials(deals, financials)[0]
        self.assertEqual(row["ev_revenue"], 3.0)
        self.assertEqual(row["ev_ebitda"], 12.0)
        self.assertEqual(row["financials_as_of"], "2021-12-31")
        self.assertEqual(row["source_count"], 2)
        financials[0]["currency"] = "EUR"
        mismatch = enrich_precedent_financials(deals, financials)[0]
        self.assertIsNone(mismatch["ev_revenue"])
        self.assertIsNone(mismatch["ev_ebitda"])

    def test_curated_precedents_merge_by_stable_id(self) -> None:
        existing = [{"deal_id": "same", "headline": "Buyer acquired Target", "deal_type": "M&A", "status": "Closed", "target_or_issuer": "Target", "acquirer_or_investor": "Buyer", "evidence_label": "confirmed", "source_url": "https://example.com/a", "source_name": "A"}]
        curated = [{"deal_id": "same", "headline": "Buyer acquired Target", "deal_type": "M&A", "status": "Closed", "target_or_issuer": "Target", "acquirer_or_investor": "Buyer", "enterprise_value": 100, "currency": "USD", "evidence_label": "confirmed", "source_url": "https://example.com/b", "source_name": "B"}]
        merged = merge_curated_precedents(existing, curated)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["enterprise_value"], 100)

    def test_report_contains_advanced_deal_filters_and_sorting(self) -> None:
        event = Event("filters", "2026-06-29T10:00:00+03:00", "Ozon разместил облигации на 5 млрд рублей", "", "IR", "https://example.com/deal", confidence="confirmed")
        record = extract_deal_record(classify_event(event, self.coverage), self.coverage)
        with tempfile.TemporaryDirectory() as directory:
            path = build_html_report([classify_event(event, self.coverage)], {}, Path(directory) / "report.html", "live", precedent_transactions=[record.to_dict()])
            text = path.read_text(encoding="utf-8")
            for control in ("deal-type-filter", "deal-period-filter", "deal-sector-filter", "deal-status-filter", "deal-size-filter", "deal-sort"):
                self.assertIn(f'id="{control}"', text)
            self.assertIn("По сумме внутри валюты", text)
            self.assertIn("filter-empty", text)

    def test_report_exposes_data_health_and_build_id(self) -> None:
        health = {"build_id": "abc123def456", "last_success_at": "2026-07-03T09:00+03:00", "record_count": 10, "key_deal_count": 10, "approved_count": 8, "review_count": 2, "rejected_count": 0, "source_count": 15, "direct_source_count": 12, "aggregator_source_count": 3, "critical_qa_issues": 0, "xlsx_synced": True, "xlsx_generated_at": "2026-07-03T09:01+03:00"}
        with tempfile.TemporaryDirectory() as directory:
            path = build_html_report([], {}, Path(directory) / "report.html", "live", precedent_transactions=[], health=health)
            text = path.read_text(encoding="utf-8")
        self.assertIn("abc123def456", text)
        self.assertIn("синхронизирован", text)

    def test_curated_technology_benchmark_has_ten_transactions(self) -> None:
        curated = json.loads((ROOT / "data" / "curated_precedents.json").read_text(encoding="utf-8"))
        technology = [row for row in curated if row.get("sector") == "Technology"]
        self.assertGreaterEqual(len(technology), 10)
        self.assertTrue(all(str(row.get("source_url", "")).startswith("https://") for row in technology))


if __name__ == "__main__":
    unittest.main()
