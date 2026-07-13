from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deal_markets_copilot.classifier import classify_event
from deal_markets_copilot.deals import extract_deal_record
from deal_markets_copilot.report import build_html_report
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
            })
            document = path.read_text(encoding="utf-8")
        self.assertIn('<html lang="ru">', document)
        self.assertIn('data-lang="en"', document)
        self.assertIn("Монитор сделок и рынков капитала СНГ", document)
        self.assertIn("CIS deal intelligence for M&amp;A, ECM and DCM", document)
        self.assertNotIn("Рабочий стол младшего банкира", document)
        self.assertNotIn("CIS junior banker deal desk", document)
        self.assertIn('id="deal-country-filter"', document)
        self.assertIn('id="deal-quality-filter"', document)
        self.assertIn('id="deal-source-filter"', document)
        self.assertIn("Источники и покрытие рынков СНГ", document)
        self.assertIn("новая UZSE запись была найдена, но не добавлена в базу из-за архивного окна", document)
        self.assertIn("How to read deal stages", document)
        self.assertIn("Выгрузки для аналитика", document)
        self.assertIn("Как формируется база", document)
        self.assertIn("Fact 25 only", document)
        self.assertIn('data-en="Current deals"', document)
        self.assertIn('data-en="Country / market"', document)
        self.assertIn('data-en="Technical disclosures"', document)
        self.assertIn('data-en="Methodology"', document)
        self.assertIn('data-en="No actions above the configured threshold."', document)
