from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deal_markets_copilot.classifier import classify_event
from deal_markets_copilot.deals import extract_deal_record
from deal_markets_copilot.report import _freshness_labels, build_html_report
from deal_markets_copilot.sources import fetch_cis_disclosures


class CisProductTests(TestCase):
    def test_uzse_connector_accepts_only_fact_25_and_preserves_market_metadata(self):
        listing = """
        <table><tr><td>2025-01-27</td><td>XKBK</td><td>UZ7055620007</td>
        <td>Xalq Banki</td><td>25</td><td><a href="/reports/13754/material_fact">View</a></td></tr>
        <tr><td>2025-01-26</td><td>TEST</td><td>UZ0000</td><td>Noise Issuer</td>
        <td>21</td><td><a href="/reports/13710/material_fact">View</a></td></tr></table>
        """
        detail = "Security type Ordinary shares  Total issue amount 700 000 000 000 UZS"
        config = {"cis_source_registry": [{
            "name": "UZSE material facts", "url": "https://uzse.uz/reports/material_facts?locale=en&page=1",
            "country": "Uzbekistan", "market": "UZSE", "implemented": True, "enabled": True,
            "connector": "uzse_material_facts", "fact_numbers": ["25"], "max_pages": 1,
        }]}
        with patch("deal_markets_copilot.sources._get_text", side_effect=[listing, detail]):
            events = fetch_cis_disclosures(config)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].country, "Uzbekistan")
        self.assertEqual(events[0].market, "UZSE")
        self.assertEqual(events[0].currency, "UZS")
        self.assertEqual(events[0].amount, 700_000_000_000)
        item = classify_event(events[0], [])
        self.assertEqual(item.category, "ECM")
        record = extract_deal_record(item, [])
        self.assertEqual(record.geography, "Uzbekistan")
        self.assertEqual(record.sources[0]["market"], "UZSE")

    def test_report_is_russian_first_with_english_toggle_and_cis_controls(self):
        config = {"cis_source_registry": [{
            "country": "Uzbekistan", "market": "UZSE", "name": "UZSE material facts",
            "url": "https://uzse.uz/reports/material_facts", "deal_types": ["ECM", "DCM"],
            "expected_value": "Official securities issues", "noise_risk": "low",
            "limitations": "Fact 25 only", "implemented": True, "enabled": True,
        }]}
        with TemporaryDirectory() as directory:
            path = build_html_report([], config, Path(directory) / "report.html", "live", health={
                "build_id": "abc123", "dataset_sha256": "f" * 64,
                "system_status": "ok", "source_status": "ok", "freshness_status": "ok",
                "source_age_minutes": 472, "freshness_limit_minutes": 72 * 60,
            })
            document = path.read_text(encoding="utf-8")
        self.assertIn('<html lang="ru">', document)
        self.assertIn('data-lang="en"', document)
        self.assertIn("Монитор сделок и рынков капитала СНГ", document)
        self.assertIn("CIS deal intelligence for M&amp;A, ECM and DCM", document)
        self.assertIn('data-ru="Открыть скринер сделок" data-en="Open deal screener"', document)
        self.assertIn('data-ru="Скринер сделок: Россия и СНГ" data-en="Deal screener: Russia and CIS"', document)
        self.assertIn("качество источников и подтверждений", document)
        self.assertNotIn('data-ru="Открыть deal screener"', document)
        self.assertNotIn('data-ru="Deal screener: Россия и СНГ"', document)
        self.assertNotIn("качество evidence", document)
        self.assertNotIn('<h1>Deal Markets Copilot</h1>', document)
        self.assertNotIn("Рабочий стол младшего банкира", document)
        self.assertNotIn("CIS junior banker deal desk", document)
        self.assertIn('data-ru="Подтверждено" data-en="Approved">Подтверждено</dt>', document)
        self.assertIn('data-ru="Рыночный контекст" data-en="Market tape">Рыночный контекст</dt>', document)
        self.assertIn('data-ru="Ошибки проверки" data-en="QA issues">Ошибки проверки</dt>', document)
        self.assertNotIn("<dt>Approved</dt>", document)
        self.assertNotIn("<dt>Market tape</dt>", document)
        self.assertNotIn("<dt>QA issues</dt>", document)
        self.assertIn('data-en="Approved"', document)
        self.assertIn('data-en="Market tape"', document)
        self.assertIn('data-en="QA issues"', document)
        self.assertIn('data-ru="Последняя проверка: 7 ч 52 мин назад"', document)
        self.assertIn('data-en="Last checked 7h 52m ago"', document)
        self.assertNotIn('data-ru="свежие · 472 мин"', document)
        self.assertIn('id="deal-country-filter"', document)
        self.assertIn('id="deal-quality-filter"', document)
        self.assertIn('id="deal-source-filter"', document)
        self.assertIn("Источники и покрытие рынков СНГ", document)
        self.assertIn("новая запись UZSE была найдена, но не добавлена в базу из-за архивного окна", document)
        self.assertIn("How to read deal stages", document)
        self.assertIn("Выгрузки для аналитика", document)
        self.assertIn("Как формируется база", document)
        self.assertIn("Fact 25 only", document)
        self.assertIn('data-en="Current deals"', document)
        self.assertIn('data-en="Country / market"', document)
        self.assertIn('data-en="Technical disclosures"', document)
        self.assertIn('data-en="Methodology"', document)
        self.assertIn('data-en="No actions above the configured threshold."', document)
        self.assertIn('class="mobile-section-nav"', document)
        self.assertIn('data-ru-aria-label="Разделы" data-en-aria-label="Sections"', document)
        for anchor in ("overview", "deals", "review", "tasks", "coverage", "downloads", "methodology"):
            self.assertIn(f'href="#{anchor}"', document)
            self.assertIn(f'id="{anchor}"', document)
        self.assertNotIn("/Users/", document)
        self.assertNotIn("file://", document)

        ru_labels = "\n".join(re.findall(r'data-ru="([^"]*)"', document))
        for untranslated in (
            "ANALYST WORKFLOW", "SOURCE COVERAGE", "METHODOLOGY &amp; INTEGRITY",
            "Открыть deal screener", "Deal screener: Россия и СНГ", "quality evidence",
        ):
            self.assertNotIn(untranslated, ru_labels)

    def test_freshness_presentation_distinguishes_fresh_overnight_and_stale(self):
        fresh = _freshness_labels({
            "source_age_minutes": 45, "freshness_limit_minutes": 90, "freshness_status": "ok",
        })
        overnight = _freshness_labels({
            "source_age_minutes": 472, "freshness_limit_minutes": 72 * 60, "freshness_status": "ok",
        })
        stale = _freshness_labels({
            "source_age_minutes": 72 * 60 + 1, "freshness_limit_minutes": 72 * 60,
            "freshness_status": "stale",
        })

        self.assertEqual(fresh, ("свежие данные", "fresh data", "fresh"))
        self.assertEqual(overnight, ("Последняя проверка: 7 ч 52 мин назад", "Last checked 7h 52m ago", "checked"))
        self.assertNotIn("свеж", overnight[0])
        self.assertNotIn("fresh", overnight[1].lower())
        self.assertEqual(stale, ("требуется обновление", "refresh required", "stale"))
