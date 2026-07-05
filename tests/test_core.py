from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deal_markets_copilot.classifier import classify_event, deduplicate, stable_event_id
from deal_markets_copilot.deals import _migrate_row, enrich_precedent_financials, extract_deal_record, median_multiples, merge_curated_precedents, select_deal_buckets, select_key_deals, update_precedent_database, write_precedents_csv
from deal_markets_copilot.models import Event
from deal_markets_copilot.report import _distinct_summary, _safe_url, build_html_report, build_telegram_digest
from deal_markets_copilot.sources import _date_from_title, effective_news_lookback, fetch_configured_sources, fetch_feed, fetch_moex_disclosures, fetch_moex_quotes, fetch_official_issuer_news, fetch_sec_deal_filings, filter_recent_events, load_demo_events, resolve_google_news_events, resolve_google_news_rows
from deal_markets_copilot.workflow import build_morning_workflow, is_actionable_signal
from run import _build_health, _source_run_status


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

    def test_deduplicate_keeps_distinct_bond_issues_for_same_issuer(self) -> None:
        first = Event("a", "", "«МТС» разместила облигации 003Р-03 на 20 млрд рублей", "", "IR", "https://example.com/a")
        second = Event("b", "", "«МТС» разместила облигации 003Р-04 на 20 млрд рублей", "", "IR", "https://example.com/b")
        self.assertEqual(len(deduplicate([first, second])), 2)

    def test_near_duplicate_prefers_stronger_source(self) -> None:
        weak = Event("a", "", "Яндекс продал Авто.ру за 35 млрд рублей", "", "Blog", "https://a")
        strong = Event("b", "", "Т-Технологии закрыли сделку по покупке Авто.ру у Яндекса за 35 млрд рублей", "", "Интерфакс", "https://b")
        result = deduplicate([weak, strong])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "Интерфакс")

    def test_stable_id(self) -> None:
        self.assertEqual(stable_event_id("A", "B"), stable_event_id("A", "B"))

    def test_build_id_changes_when_any_dataset_field_changes(self) -> None:
        original = json.dumps([{"deal_id": "one", "notes": "before"}], ensure_ascii=False, indent=2).encode()
        changed = json.dumps([{"deal_id": "one", "notes": "after"}], ensure_ascii=False, indent=2).encode()
        original_hash = hashlib.sha256(original).hexdigest()
        changed_hash = hashlib.sha256(changed).hexdigest()
        self.assertNotEqual(original_hash, changed_hash)
        self.assertNotEqual(original_hash[:12], changed_hash[:12])

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

    def test_repo_trading_notice_is_not_a_deal_or_task(self) -> None:
        event = Event(
            event_id="moex-repo", published_at="2026-07-03T17:12:32+03:00",
            title="Операции РЕПО с ЦК / с КСУ и сделки купли-продажи облигаций с расчётами в Специализированной валюте",
            summary="Инфраструктурное уведомление", source="MOEX disclosure",
            url="https://www.moex.com/n101768", source_type="official_exchange", confidence="confirmed",
        )
        item = classify_event(event, [])
        self.assertEqual(item.score, 0)
        self.assertFalse(is_actionable_signal(item))
        record = extract_deal_record(item, [])
        self.assertIsNotNone(record)
        self.assertEqual(record.record_kind, "technical_filing")
        self.assertEqual(select_key_deals([record.to_dict()]), [])

    def test_rss_transport_failure_is_not_silently_successful(self) -> None:
        config = {"sources": [{"name": "Test RSS", "url": "https://example.com/rss", "enabled": True}]}
        with patch("deal_markets_copilot.sources.fetch_feed", side_effect=OSError("offline")):
            with self.assertRaises(RuntimeError):
                fetch_configured_sources(config)

    def test_empty_required_source_is_not_success(self) -> None:
        self.assertEqual(_source_run_status([], required=True), "empty")
        self.assertEqual(_source_run_status([], required=False), "ok")

    def test_structurally_empty_feed_is_an_error(self) -> None:
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b"<rss><channel></channel></rss>"
        with patch("deal_markets_copilot.sources.urllib.request.urlopen", return_value=Response()):
            with self.assertRaisesRegex(RuntimeError, "no RSS items"):
                fetch_feed("https://example.com/rss", "Example")

    def test_workflow_suppresses_non_transaction_finance_news(self) -> None:
        headlines = [
            "Аналитик повысил target price Ozon до 5 000 рублей",
            "Ozon выплатил купон по облигациям",
            "Ozon погасил выпуск облигаций на 5 млрд рублей",
            "Yandex объявил buyback акций",
            "Yandex опроверг покупку Ozon",
        ]
        for index, headline in enumerate(headlines):
            event = Event(str(index), "2026-07-04T09:00:00+03:00", headline, "", "News", f"https://example.com/{index}")
            self.assertFalse(is_actionable_signal(classify_event(event, self.coverage)), headline)

    def test_health_cannot_be_green_when_all_discovery_feeds_are_empty(self) -> None:
        rows = [{
            "deal_id": "one", "record_kind": "deal", "quality_status": "approved",
            "deal_type": "M&A", "stake_percent": None, "source_count": 1,
            "sources": [{"name": "Issuer", "url": "https://example.com", "source_type": "official_issuer"}],
        }]
        required = {"issuer_news", "moex_disclosures", "configured_rss", "deal_news", "company_news", "moex_quotes"}
        source_runs = [{"name": name, "status": "ok", "records": 0, "required": True, "checked_at": "2026-07-03T12:00:00+03:00"} for name in required]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "rows.json"
            dataset.write_text(json.dumps(rows), encoding="utf-8")
            digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"build_id": digest[:12], "dataset_sha256": digest, "record_count": 1}), encoding="utf-8")
            health = _build_health(rows, manifest, dataset, source_runs)
        self.assertEqual(health["discovery_status"], "empty")
        self.assertEqual(health["source_status"], "error")
        self.assertEqual(health["system_status"], "warning")

    def test_moex_quotes_distinguish_valid_partial_and_unavailable_rows(self) -> None:
        class Response:
            def __init__(self, payload: dict) -> None:
                self.payload = payload

            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(self.payload).encode()

        def payload(last, change, turnover):
            return {
                "marketdata": {
                    "columns": ["SECID", "LAST", "LASTTOPREVPRICE", "VALTODAY", "UPDATETIME"],
                    "data": [["TICKER", last, change, turnover, "10:30:00"]],
                },
                "securities": {
                    "columns": ["SECID", "SHORTNAME", "PREVPRICE"],
                    "data": [["TICKER", "Company", 100]],
                },
            }

        config = {"coverage": [
            {"moex_secid": "YDEX", "company": "Yandex"},
            {"moex_secid": "OZON", "company": "Ozon"},
            {"moex_secid": "VKCO", "company": "VK"},
        ]}
        responses = [
            Response(payload(123.4, 1.25, 1_000_000)),
            Response(payload(50.0, None, 500_000)),
            Response(payload(None, 0, 0)),
        ]
        with patch("deal_markets_copilot.sources.urllib.request.urlopen", side_effect=responses):
            quotes = fetch_moex_quotes(config)

        self.assertEqual([row["quote_status"] for row in quotes], ["valid", "partial", "unavailable"])
        self.assertEqual([row["quote_usable"] for row in quotes], [True, True, False])
        self.assertEqual(quotes[0]["price"], 123.4)
        self.assertEqual(quotes[0]["change_percent"], 1.25)
        self.assertEqual(quotes[1]["price"], 50.0)
        self.assertIsNone(quotes[1]["change_percent"])
        self.assertIsNone(quotes[2]["price"])
        self.assertIsNone(quotes[2]["change_percent"])

    def test_market_health_reports_partial_or_unavailable_without_breaking_core_pipeline(self) -> None:
        rows = [{
            "deal_id": "one", "record_kind": "deal", "quality_status": "approved",
            "deal_type": "M&A", "stake_percent": None,
            "sources": [{"name": "Issuer", "url": "https://example.com", "source_type": "official_issuer"}],
        }]
        core_names = {"issuer_news", "moex_disclosures", "configured_rss", "deal_news", "company_news"}
        source_runs = [
            {"name": name, "status": "ok", "records": 1, "required": True, "checked_at": "2099-01-01T10:00:00+03:00"}
            for name in core_names
        ] + [{
            "name": "moex_quotes", "status": "ok", "records": 3, "required": False,
            "checked_at": "2099-01-01T10:00:00+03:00",
        }]
        mixed = [
            {"ticker": "YDEX", "price": 100.0, "change_percent": 1.0, "quote_status": "valid", "quote_usable": True},
            {"ticker": "OZON", "price": None, "change_percent": None, "quote_status": "unavailable", "quote_usable": False},
            {"ticker": "VKCO", "price": None, "change_percent": None, "quote_status": "unavailable", "quote_usable": False},
        ]
        unavailable = [dict(row, price=None, change_percent=None, quote_status="unavailable", quote_usable=False) for row in mixed]
        source_error = [{
            "ticker": "YDEX", "price": None, "change_percent": None, "quote_status": "error",
            "quote_usable": False, "error": "transport unavailable",
        }]
        error_runs = [dict(run) for run in source_runs]
        error_runs[-1].update({"status": "error", "records": 0, "error": "1 item unavailable"})
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "rows.json"
            dataset.write_text(json.dumps(rows), encoding="utf-8")
            digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"build_id": digest[:12], "dataset_sha256": digest, "record_count": 1}), encoding="utf-8")
            mixed_health = _build_health(rows, manifest, dataset, source_runs, mixed)
            unavailable_health = _build_health(rows, manifest, dataset, source_runs, unavailable)
            error_health = _build_health(rows, manifest, dataset, error_runs, source_error)

        self.assertEqual(mixed_health["market_data_status"], "partial")
        self.assertEqual(mixed_health["market_quote_count"], 1)
        self.assertEqual(mixed_health["market_quote_total"], 3)
        self.assertEqual(mixed_health["system_status"], "ok")
        self.assertEqual(unavailable_health["market_data_status"], "unavailable")
        self.assertEqual(unavailable_health["market_quote_count"], 0)
        self.assertEqual(unavailable_health["system_status"], "ok")
        self.assertEqual(error_health["market_data_status"], "error")
        self.assertEqual(error_health["system_status"], "ok")

    def test_market_tape_renders_missing_values_without_false_zeroes(self) -> None:
        quotes = [
            {"ticker": "YDEX", "company": "Yandex", "price": 123.4, "change_percent": 1.25, "turnover": 1_000_000, "quote_status": "valid", "quote_usable": True, "source_url": "https://moex.com/YDEX"},
            {"ticker": "OZON", "company": "Ozon", "price": 50.0, "change_percent": None, "turnover": 500_000, "quote_status": "partial", "quote_usable": True, "source_url": "https://moex.com/OZON"},
            {"ticker": "VKCO", "company": "VK", "price": None, "change_percent": None, "turnover": 0, "quote_status": "unavailable", "quote_usable": False, "source_url": "https://moex.com/VKCO"},
        ]
        health = {
            "system_status": "ok", "source_status": "ok", "freshness_status": "ok",
            "xlsx_synced": True, "build_id": "test", "record_count": 0, "approved_count": 0,
            "critical_qa_issues": 0, "market_data_status": "partial", "market_quote_count": 2,
            "market_quote_total": 3,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = build_html_report([], {}, Path(directory) / "report.html", "live", market_snapshot=quotes, health=health)
            text = path.read_text(encoding="utf-8")
            unavailable_quotes = [
                dict(row, price=None, change_percent=None, quote_status="unavailable", quote_usable=False)
                for row in quotes
            ]
            unavailable_health = dict(health, market_data_status="unavailable", market_quote_count=0)
            unavailable_path = build_html_report(
                [], {}, Path(directory) / "unavailable.html", "live",
                market_snapshot=unavailable_quotes, health=unavailable_health,
            )
            unavailable_text = unavailable_path.read_text(encoding="utf-8")

        self.assertIn("123.40 ₽", text)
        self.assertIn("+1.25%", text)
        self.assertIn("50.00 ₽", text)
        self.assertIn("изменение недоступно", text)
        self.assertIn("Котировка недоступна", text)
        self.assertIn("Market tape", text)
        self.assertIn("частично · 2/3", text)
        self.assertNotIn("— ₽", text)
        self.assertNotIn("Котировка недоступна</span><span class=\"quote-change flat\">+0.00%", text)
        self.assertIn("недоступен · 0/3", unavailable_text)
        self.assertNotIn("+0.00%", unavailable_text)
        self.assertNotIn("— ₽", unavailable_text)

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

    def test_dcm_completion_never_uses_ma_closed_status(self) -> None:
        row = _migrate_row({
            "deal_id": "dcm-completed", "announced_date": "2026-07-01", "deal_type": "DCM",
            "record_kind": "deal", "status": "Closed", "target_or_issuer": "Issuer",
            "acquirer_or_investor": "Not applicable", "headline": "Issuer completed bond placement",
            "evidence_label": "confirmed", "source_name": "IR", "source_url": "https://example.com/dcm",
        })
        self.assertEqual(row["status"], "Issued")

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

    def test_dcm_lifecycle_merges_preliminary_aggregate_into_official_final(self) -> None:
        preliminary = Event(
            "preliminary", "2026-06-04T08:00:00+03:00",
            "Альфа разместит облигации 001Р-04 и 001Р-05 минимум на 30 млрд рублей", "",
            "Newswire", "https://example.com/preliminary",
        )
        final = Event(
            "final", "2026-06-19T08:00:00+03:00",
            "Альфа разместила облигации серий 001Р-04 и 001Р-05 на 60 млрд рублей", "",
            "Issuer IR", "https://example.com/final", source_type="issuer_ir", confidence="confirmed",
        )
        records = [extract_deal_record(classify_event(event, []), []) for event in (preliminary, final)]
        with tempfile.TemporaryDirectory() as directory:
            rows = update_precedent_database(records, Path(directory) / "precedents.json")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["deal_id"], "DL-final")
        self.assertEqual(rows[0]["transaction_value"], 60_000_000_000)
        self.assertEqual(rows[0]["status"], "Issued")
        self.assertEqual(set(rows[0]["security_code"].split("; ")), {"001Р-04", "001Р-05"})
        self.assertEqual({source["url"] for source in rows[0]["sources"]}, {
            "https://example.com/preliminary", "https://example.com/final",
        })

    def test_dcm_lifecycle_allows_amount_growth_with_shared_issue_identity(self) -> None:
        events = [
            Event("early", "2026-06-04", "Альфа разместит облигации 001Р-04 минимум на 30 млрд рублей", "", "Press", "https://example.com/early"),
            Event("issued", "2026-06-19", "Альфа разместила облигации 001Р-04 на 60 млрд рублей", "", "Issuer IR", "https://example.com/issued", source_type="issuer_ir", confidence="confirmed"),
        ]
        records = [extract_deal_record(classify_event(event, []), []) for event in events]
        with tempfile.TemporaryDirectory() as directory:
            rows = update_precedent_database(records, Path(directory) / "precedents.json")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["transaction_value"], 60_000_000_000)

    def test_dcm_lifecycle_final_terms_override_preliminary_source_rank(self) -> None:
        events = [
            Event("preliminary-official", "2026-06-04", "Альфа разместит облигации 001Р-04 на 30 млрд рублей", "", "Issuer IR", "https://example.com/preliminary-official", source_type="issuer_ir", confidence="confirmed"),
            Event("final-secondary", "2026-06-19", "Альфа разместила облигации 001Р-04 на 60 млрд рублей", "", "Newswire", "https://example.com/final-secondary", confidence="confirmed"),
        ]
        records = [extract_deal_record(classify_event(event, []), []) for event in events]
        with tempfile.TemporaryDirectory() as directory:
            rows = update_precedent_database(records, Path(directory) / "precedents.json")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "Issued")
        self.assertEqual(rows[0]["transaction_value"], 60_000_000_000)
        self.assertEqual(rows[0]["currency"], "RUB")

    def test_dcm_lifecycle_does_not_merge_distinct_issue_series(self) -> None:
        events = [
            Event("series-a", "2026-06-04", "Альфа разместила облигации 001Р-04 на 20 млрд рублей", "", "IR", "https://example.com/a", confidence="confirmed"),
            Event("series-b", "2026-06-05", "Альфа разместила облигации 001Р-06 на 20 млрд рублей", "", "IR", "https://example.com/b", confidence="confirmed"),
        ]
        records = [extract_deal_record(classify_event(event, []), []) for event in events]
        with tempfile.TemporaryDirectory() as directory:
            rows = update_precedent_database(records, Path(directory) / "precedents.json")
        self.assertEqual(len(rows), 2)

    def test_dcm_lifecycle_does_not_merge_on_same_issuer_and_weak_signals_alone(self) -> None:
        events = [
            Event("weak-a", "2026-06-04", "Сбер разместил облигации на 10 млрд рублей", "", "IR", "https://example.com/weak-a", confidence="confirmed"),
            Event("weak-b", "2026-06-05", "Сбер разместил облигации на 20 млрд рублей", "", "IR", "https://example.com/weak-b", confidence="confirmed"),
        ]
        records = [extract_deal_record(classify_event(event, []), []) for event in events]
        with tempfile.TemporaryDirectory() as directory:
            rows = update_precedent_database(records, Path(directory) / "precedents.json")
        self.assertEqual(len(rows), 2)

    def test_dcm_lifecycle_repeat_processing_is_idempotent(self) -> None:
        events = [
            Event("early", "2026-06-04", "Альфа разместит облигации 001Р-04 и 001Р-05 на 30 млрд рублей", "", "Press", "https://example.com/early"),
            Event("final", "2026-06-19", "Альфа разместила облигации 001Р-04 и 001Р-05 на 60 млрд рублей", "", "Issuer IR", "https://example.com/final", source_type="issuer_ir", confidence="confirmed"),
        ]
        records = [extract_deal_record(classify_event(event, []), []) for event in events]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "precedents.json"
            update_precedent_database(records, database)
            rows = update_precedent_database(records, database)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "Issued")
        self.assertEqual(rows[0]["transaction_value"], 60_000_000_000)
        self.assertEqual(rows[0]["source_count"], 2)

    def test_dcm_refresh_preserves_populated_strong_identity_when_incoming_missing(self) -> None:
        canonical = {
            "deal_id": "DL-final", "announced_date": "2026-06-19", "deal_type": "DCM",
            "record_kind": "deal", "status": "Issued", "target_or_issuer": "Альфа",
            "acquirer_or_investor": "Not applicable", "headline": "Альфа разместила облигации на 60 млрд рублей",
            "transaction_value": 60_000_000_000, "currency": "RUB", "security_code": "001Р-04; 001Р-05",
            "isin": "RU000A123456", "evidence_label": "confirmed", "source_name": "Issuer IR",
            "source_url": "https://example.com/final",
        }
        refresh = Event(
            "final", "2026-06-19", "Альфа разместила облигации на 60 млрд рублей", "",
            "Issuer IR", "https://example.com/final", source_type="issuer_ir", confidence="confirmed",
        )
        record = extract_deal_record(classify_event(refresh, []), [])
        self.assertEqual(record.security_code, "Not disclosed")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "precedents.json"
            database.write_text(json.dumps([canonical]), encoding="utf-8")
            rows = update_precedent_database([record], database)
        self.assertEqual(rows[0]["security_code"], "001Р-04; 001Р-05")
        self.assertEqual(rows[0]["isin"], "RU000A123456")

    def test_dcm_refresh_adds_strong_identity_when_existing_missing(self) -> None:
        existing = {
            "deal_id": "DL-final", "announced_date": "2026-06-19", "deal_type": "DCM",
            "record_kind": "deal", "status": "Issued", "target_or_issuer": "Альфа",
            "acquirer_or_investor": "Not applicable", "headline": "Альфа разместила облигации",
            "security_code": "Not disclosed", "isin": "Not disclosed",
        }
        incoming = Event("final", "2026-06-19", "Альфа разместила облигации 001Р-04 и 001Р-05", "", "IR", "https://example.com/final")
        record = extract_deal_record(classify_event(incoming, []), [])
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "precedents.json"
            database.write_text(json.dumps([existing]), encoding="utf-8")
            rows = update_precedent_database([record], database)
        self.assertEqual(rows[0]["security_code"], "001Р-04; 001Р-05")

    def test_dcm_refresh_unions_partial_and_expanded_issue_identity(self) -> None:
        existing = {
            "deal_id": "DL-final", "announced_date": "2026-06-19", "deal_type": "DCM",
            "record_kind": "deal", "status": "Issued", "target_or_issuer": "Альфа",
            "acquirer_or_investor": "Not applicable", "headline": "Альфа разместила облигации",
            "security_code": "001Р-04",
        }
        incoming = Event("final", "2026-06-19", "Альфа разместила облигации 001Р-04 и 001Р-05", "", "IR", "https://example.com/final")
        record = extract_deal_record(classify_event(incoming, []), [])
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "precedents.json"
            database.write_text(json.dumps([existing]), encoding="utf-8")
            rows = update_precedent_database([record], database)
        self.assertEqual(rows[0]["security_code"], "001Р-04; 001Р-05")

    def test_dcm_refresh_repeat_is_identity_idempotent(self) -> None:
        canonical = {
            "deal_id": "DL-final", "announced_date": "2026-06-19", "deal_type": "DCM",
            "record_kind": "deal", "status": "Issued", "target_or_issuer": "Альфа",
            "acquirer_or_investor": "Not applicable", "headline": "Альфа разместила облигации на 60 млрд рублей",
            "transaction_value": 60_000_000_000, "currency": "RUB", "security_code": "001Р-04; 001Р-05",
            "source_url": "https://example.com/final", "source_name": "Issuer IR",
        }
        refresh = Event("final", "2026-06-19", "Альфа разместила облигации на 60 млрд рублей", "", "Issuer IR", "https://example.com/final")
        record = extract_deal_record(classify_event(refresh, []), [])
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "precedents.json"
            database.write_text(json.dumps([canonical]), encoding="utf-8")
            update_precedent_database([record], database)
            rows = update_precedent_database([record], database)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["security_code"], "001Р-04; 001Р-05")
        self.assertEqual(rows[0]["transaction_value"], 60_000_000_000)
        self.assertEqual(rows[0]["status"], "Issued")
        self.assertEqual(rows[0]["source_count"], 1)

    def test_dcm_lifecycle_archive_signal_cannot_recreate_final_transaction(self) -> None:
        final = Event("final", "2026-06-19", "Альфа разместила облигации 001Р-04 и 001Р-05 на 60 млрд рублей", "", "Issuer IR", "https://example.com/final", source_type="issuer_ir", confidence="confirmed")
        archive = Event("archive", "2026-06-04", "Альфа разместит облигации 001Р-04 и 001Р-05 минимум на 30 млрд рублей", "", "Archive", "https://example.com/archive")
        final_record = extract_deal_record(classify_event(final, []), [])
        archive_record = extract_deal_record(classify_event(archive, []), [])
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "precedents.json"
            update_precedent_database([final_record], database)
            rows = update_precedent_database([archive_record], database)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["deal_id"], "DL-final")
        self.assertEqual(rows[0]["status"], "Issued")
        self.assertEqual(rows[0]["transaction_value"], 60_000_000_000)

    def test_dcm_lifecycle_known_source_lineage_prevents_recreation_without_identifiers(self) -> None:
        canonical = {
            "deal_id": "DL-final", "announced_date": "2026-06-19", "deal_type": "DCM",
            "record_kind": "deal", "status": "Issued", "target_or_issuer": "Альфа",
            "acquirer_or_investor": "Not applicable", "headline": "Альфа разместила два выпуска облигаций на 60 млрд рублей",
            "transaction_value": 60_000_000_000, "currency": "RUB", "security_code": "001Р-04; 001Р-05",
            "evidence_label": "confirmed", "source_name": "Issuer IR", "source_url": "https://example.com/final",
            "sources": [
                {"name": "Issuer IR", "url": "https://example.com/final", "evidence_label": "confirmed", "source_type": "issuer_ir"},
                {"name": "Archive", "url": "https://example.com/archive", "evidence_label": "unverified", "source_type": "archive_discovery"},
            ],
        }
        archive = Event("archive", "2026-06-04", "Альфа разместит облигации минимум на 30 млрд рублей", "", "Archive", "https://example.com/archive")
        archive_record = extract_deal_record(classify_event(archive, []), [])
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "precedents.json"
            database.write_text(json.dumps([canonical]), encoding="utf-8")
            rows = update_precedent_database([archive_record], database)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["deal_id"], "DL-final")
        self.assertEqual(rows[0]["transaction_value"], 60_000_000_000)
        self.assertEqual(rows[0]["status"], "Issued")

    def test_same_url_counts_as_one_source_even_with_two_labels(self) -> None:
        row = _migrate_row({
            "deal_id": "same-url", "announced_date": "2026-07-01", "deal_type": "M&A",
            "record_kind": "deal", "status": "Closed", "target_or_issuer": "Target",
            "acquirer_or_investor": "Buyer", "headline": "Buyer acquired Target",
            "evidence_label": "confirmed", "source_name": "Publisher alias",
            "source_url": "https://example.com/deal", "sources": [
                {"name": "Publisher", "url": "https://example.com/deal", "evidence_label": "confirmed"},
            ],
        })
        self.assertEqual(row["source_count"], 1)

    def test_same_publication_direct_and_google_counts_once_and_preserves_representations(self) -> None:
        row = _migrate_row({
            "deal_id": "same-publication", "announced_date": "2026-06-04", "deal_type": "DCM",
            "record_kind": "deal", "status": "Announced", "target_or_issuer": "Issuer",
            "acquirer_or_investor": "Not applicable", "headline": "Issuer announced bonds",
            "evidence_label": "unverified", "source_name": "Publisher",
            "source_url": "https://publisher.example/articles/bonds", "sources": [
                {"name": "Publisher", "url": "https://publisher.example/articles/bonds", "published_at": "2026-06-04", "source_type": "public_web"},
                {"name": "Publisher", "url": "https://news.google.com/rss/articles/token?oc=5", "published_at": "Thu, 04 Jun 2026 07:00:00 GMT", "source_type": "archive_discovery"},
            ],
        })
        self.assertEqual(row["source_count"], 1)
        self.assertEqual(len(row["sources"]), 1)
        self.assertEqual(row["sources"][0]["url"], "https://publisher.example/articles/bonds")
        self.assertEqual({item["url"] for item in row["sources"][0]["representations"]}, {
            "https://publisher.example/articles/bonds",
            "https://news.google.com/rss/articles/token?oc=5",
        })

    def test_tracking_query_and_fragment_variants_count_as_one_publication(self) -> None:
        row = _migrate_row({
            "deal_id": "url-variants", "announced_date": "2026-06-04", "deal_type": "DCM",
            "record_kind": "deal", "status": "Announced", "target_or_issuer": "Issuer",
            "acquirer_or_investor": "Not applicable", "headline": "Issuer announced bonds",
            "source_name": "Publisher", "source_url": "https://Example.com/article/?utm_source=rss#top",
            "sources": [
                {"name": "Publisher", "url": "https://Example.com/article/?utm_source=rss#top", "published_at": "2026-06-04"},
                {"name": "Publisher", "url": "https://example.com/article?fbclid=abc", "published_at": "2026-06-04"},
            ],
        })
        self.assertEqual(row["source_count"], 1)
        self.assertEqual(len(row["sources"][0]["representations"]), 2)

    def test_same_transaction_different_publishers_remain_independent_publications(self) -> None:
        row = _migrate_row({
            "deal_id": "two-publishers", "announced_date": "2026-06-04", "deal_type": "DCM",
            "record_kind": "deal", "status": "Announced", "target_or_issuer": "Issuer",
            "acquirer_or_investor": "Not applicable", "headline": "Issuer announced bonds",
            "source_name": "Publisher A", "source_url": "https://a.example/article",
            "sources": [
                {"name": "Publisher A", "url": "https://a.example/article", "published_at": "2026-06-04"},
                {"name": "Publisher B", "url": "https://b.example/article", "published_at": "2026-06-04"},
            ],
        })
        self.assertEqual(row["source_count"], 2)

    def test_same_publisher_different_articles_remain_separate_publications(self) -> None:
        row = _migrate_row({
            "deal_id": "two-articles", "announced_date": "2026-06-04", "deal_type": "DCM",
            "record_kind": "deal", "status": "Issued", "target_or_issuer": "Issuer",
            "acquirer_or_investor": "Not applicable", "headline": "Issuer placed bonds",
            "source_name": "Publisher", "source_url": "https://publisher.example/preliminary",
            "sources": [
                {"name": "Publisher", "url": "https://publisher.example/preliminary", "published_at": "2026-06-04"},
                {"name": "Publisher", "url": "https://publisher.example/result", "published_at": "2026-06-19"},
            ],
        })
        self.assertEqual(row["source_count"], 2)

    def test_attributed_or_syndicated_articles_are_not_merged_without_strong_identity(self) -> None:
        row = _migrate_row({
            "deal_id": "syndicated", "announced_date": "2026-06-04", "deal_type": "DCM",
            "record_kind": "deal", "status": "Announced", "target_or_issuer": "Issuer",
            "acquirer_or_investor": "Not applicable", "headline": "Issuer announced bonds",
            "source_name": "Original Wire", "source_url": "https://wire.example/story",
            "sources": [
                {"name": "Original Wire", "url": "https://wire.example/story", "published_at": "2026-06-04"},
                {"name": "Republisher", "url": "https://republisher.example/story", "published_at": "2026-06-04"},
            ],
        })
        self.assertEqual(row["source_count"], 2)

    def test_incomplete_publication_metadata_does_not_trigger_direct_google_merge(self) -> None:
        row = _migrate_row({
            "deal_id": "missing-metadata", "announced_date": "2026-06-04", "deal_type": "DCM",
            "record_kind": "deal", "status": "Announced", "target_or_issuer": "Issuer",
            "acquirer_or_investor": "Not applicable", "headline": "Issuer announced bonds",
            "source_name": "Publisher", "source_url": "https://publisher.example/article",
            "sources": [
                {"name": "Publisher", "url": "https://publisher.example/article", "published_at": ""},
                {"name": "Publisher", "url": "https://news.google.com/rss/articles/token?oc=5", "published_at": "", "source_type": "archive_discovery"},
            ],
        })
        self.assertEqual(row["source_count"], 2)

    def test_publication_canonicalization_is_idempotent(self) -> None:
        source = {
            "deal_id": "idempotent-publication", "announced_date": "2026-06-04", "deal_type": "DCM",
            "record_kind": "deal", "status": "Announced", "target_or_issuer": "Issuer",
            "acquirer_or_investor": "Not applicable", "headline": "Issuer announced bonds",
            "source_name": "Publisher", "source_url": "https://publisher.example/article",
            "sources": [
                {"name": "Publisher", "url": "https://publisher.example/article", "published_at": "2026-06-04"},
                {"name": "Publisher", "url": "https://news.google.com/rss/articles/token?oc=5", "published_at": "2026-06-04", "source_type": "archive_discovery"},
            ],
        }
        first = _migrate_row(source)
        second = _migrate_row(first)
        self.assertEqual(second["sources"], first["sources"])
        self.assertEqual(second["source_count"], 1)

    def test_source_count_and_quality_are_recomputed_after_publication_canonicalization(self) -> None:
        row = _migrate_row({
            "deal_id": "quality-recompute", "announced_date": "2026-06-04", "deal_type": "DCM",
            "record_kind": "deal", "status": "Issued", "target_or_issuer": "Issuer",
            "acquirer_or_investor": "Not applicable", "headline": "Issuer completed bond placement",
            "evidence_label": "confirmed", "quality_score": 1, "quality_status": "rejected",
            "source_name": "Publisher", "source_url": "https://publisher.example/article",
            "sources": [
                {"name": "Publisher", "url": "https://publisher.example/article", "published_at": "2026-06-04", "evidence_label": "confirmed"},
                {"name": "Publisher", "url": "https://news.google.com/rss/articles/token?oc=5", "published_at": "2026-06-04", "source_type": "archive_discovery"},
            ],
        })
        self.assertEqual(row["source_count"], 1)
        self.assertEqual(row["quality_score"], 100)
        self.assertEqual(row["quality_status"], "approved")
        self.assertEqual(row["quality_flags"], [])

    def test_medians_use_valid_ma_multiples(self) -> None:
        eligible = {"record_kind": "deal", "quality_status": "approved", "status": "Closed", "announced_date": "2024-01-01", "financials_available_at": "2023-12-01", "enterprise_value": 100, "currency": "USD", "financials_currency": "USD", "revenue_ltm": 50}
        stats = median_multiples([
            {**eligible, "deal_type": "M&A", "ev_revenue": 2.0, "ev_ebitda": 8.0, "ebitda_ltm": 12.5},
            {**eligible, "deal_type": "M&A", "ev_revenue": 4.0, "ev_ebitda": 12.0, "ebitda_ltm": 8.3},
            {**eligible, "deal_type": "M&A", "quality_status": "review", "ev_revenue": 99.0, "ev_ebitda": 99.0},
        ])
        self.assertIsNone(stats["ev_revenue"])
        self.assertIsNone(stats["ev_ebitda"])
        self.assertEqual(stats["ev_revenue_count"], 2)
        self.assertEqual(stats["ev_ebitda_count"], 2)

    def test_median_is_published_at_three_observations(self) -> None:
        base = {"deal_type": "M&A", "record_kind": "deal", "quality_status": "approved", "status": "Closed", "announced_date": "2024-01-01", "financials_available_at": "2023-12-01", "enterprise_value": 100, "currency": "USD", "financials_currency": "USD", "revenue_ltm": 50}
        rows = [{**base, "deal_id": str(i), "ev_revenue": value} for i, value in enumerate((2.0, 4.0, 8.0))]
        stats = median_multiples(rows)
        self.assertEqual(stats["ev_revenue"], 4.0)
        self.assertEqual(stats["ev_revenue_count"], 3)

    def test_medians_exclude_financials_published_after_announcement(self) -> None:
        base = {"deal_type": "M&A", "record_kind": "deal", "quality_status": "approved", "status": "Closed", "announced_date": "2024-01-01", "enterprise_value": 100, "currency": "USD", "financials_currency": "USD", "revenue_ltm": 50, "ev_revenue": 2.0}
        stats = median_multiples([
            {**base, "financials_available_at": "2023-12-15"},
            {**base, "deal_id": "late", "financials_available_at": "2024-02-01", "ev_revenue": 20.0},
        ])
        self.assertIsNone(stats["ev_revenue"])
        self.assertEqual(stats["ev_revenue_count"], 1)
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
        rows = [{"source_url": "https://news.google.com/rss/articles/token", "sources": [
            {"name": "Publisher", "url": "https://news.google.com/rss/articles/token"},
        ]}]
        with patch("deal_markets_copilot.sources.resolve_google_news_url", return_value="https://publisher.example/deal"):
            upgraded = resolve_google_news_rows(rows, workers=1)
        self.assertEqual(upgraded, 1)
        self.assertEqual(rows[0]["source_url"], "https://publisher.example/deal")
        self.assertEqual(rows[0]["sources"][0]["url"], "https://publisher.example/deal")
        self.assertEqual({item["url"] for item in rows[0]["sources"][0]["representations"]}, {
            "https://news.google.com/rss/articles/token", "https://publisher.example/deal",
        })

    def test_google_event_resolution_preserves_discovery_lineage_in_publication(self) -> None:
        event = Event(
            "google-event", "2026-06-04T07:00:00Z", "Issuer announced bonds", "",
            "Publisher", "https://news.google.com/rss/articles/token", source_type="archive_discovery",
        )
        with patch("deal_markets_copilot.sources.resolve_google_news_url", return_value="https://publisher.example/deal"):
            self.assertEqual(resolve_google_news_events([event], workers=1), 1)
        self.assertEqual(event.url, "https://publisher.example/deal")
        self.assertEqual(event.discovery_url, "https://news.google.com/rss/articles/token")
        record = extract_deal_record(classify_event(event, []), [])
        self.assertEqual(record.source_count, 1)
        self.assertEqual(len(record.sources[0]["representations"]), 2)

    def test_health_separates_publication_count_from_representation_count(self) -> None:
        rows = [{
            "deal_id": "one", "record_kind": "deal", "quality_status": "review", "deal_type": "DCM",
            "sources": [{
                "name": "Publisher", "url": "https://publisher.example/deal", "source_type": "public_web",
                "representations": [
                    {"url": "https://publisher.example/deal", "source_type": "public_web"},
                    {"url": "https://news.google.com/rss/articles/token", "source_type": "archive_discovery"},
                ],
            }],
        }]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "rows.json"
            dataset.write_text(json.dumps(rows), encoding="utf-8")
            health = _build_health(rows, Path(directory) / "missing-manifest.json", dataset)
        self.assertEqual(health["source_count"], 1)
        self.assertEqual(health["source_representation_count"], 2)
        self.assertEqual(health["direct_source_count"], 1)
        self.assertEqual(health["aggregator_source_count"], 1)

    def test_key_deals_exclude_technical_exchange_notices(self) -> None:
        rows = [
            {"deal_id": "technical", "announced_date": "2026-06-28", "deal_type": "DCM", "status": "Reported", "target_or_issuer": "Not disclosed", "acquirer_or_investor": "Not applicable", "transaction_value": None, "score": 8, "headline": "О регистрации изменений в эмиссионные документы"},
            {"deal_id": "ma", "announced_date": "2026-06-27", "deal_type": "M&A", "status": "Completed", "target_or_issuer": "Auto.ru", "acquirer_or_investor": "T-Technologies", "transaction_value": 35_000_000_000, "score": 7, "headline": "Т-Технологии купили Auto.ru у Яндекса"},
            {"deal_id": "dcm", "announced_date": "2026-06-26", "deal_type": "DCM", "status": "Announced", "target_or_issuer": "Selectel", "acquirer_or_investor": "Not applicable", "transaction_value": 5_000_000_000, "score": 5, "headline": "Selectel анонсировал размещение облигаций"},
        ]
        self.assertEqual([row["deal_id"] for row in select_key_deals(rows)], ["ma", "dcm"])

    def test_priced_dcm_is_a_key_deal_without_ma_closed_status(self) -> None:
        rows = [{
            "deal_id": "priced", "announced_date": "2026-07-03", "deal_type": "DCM",
            "record_kind": "deal", "quality_status": "approved", "status": "Priced",
            "target_or_issuer": "Issuer", "acquirer_or_investor": "Not applicable",
            "transaction_value": None, "headline": "Issuer закрыл книгу заявок на облигации", "score": 8,
        }]
        selected = select_key_deals(rows)
        self.assertEqual([row["deal_id"] for row in selected], ["priced"])
        self.assertEqual(selected[0]["status"], "Priced")

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
            "Купонная ставка 18,5%. Дата погашения 30.06.2029. Срок обращения 3 года. ISIN RU000A10TES1.",
            "Issuer IR", "https://example.com/bond", source_type="issuer_ir", confidence="confirmed",
        )
        record = extract_deal_record(classify_event(event, []), [])
        self.assertEqual(record.coupon_rate, 18.5)
        self.assertEqual(record.maturity_date, "2029-06-30")
        self.assertEqual(record.tenor, "3 года")
        self.assertEqual(record.isin, "RU000A10TES1")

    def test_isin_requires_numeric_check_digit(self) -> None:
        event = Event(
            "false-isin", "2026-06-29T10:00:00+03:00", "Yandex разместил облигации на 5 млрд рублей",
            "Материал подготовлен INVESTFUTURE", "InvestFuture", "https://example.com/bond",
            confidence="confirmed",
        )
        record = extract_deal_record(classify_event(event, []), [])
        self.assertEqual(record.isin, "Not disclosed")

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
