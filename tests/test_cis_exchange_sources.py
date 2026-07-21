from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deal_markets_copilot.classifier import classify_event, deduplicate
from deal_markets_copilot.deals import extract_deal_record, update_precedent_database
from deal_markets_copilot.exchange_sources import SourceHealthError, parse_exchange_detail, parse_exchange_index
from deal_markets_copilot.report import build_html_report
from deal_markets_copilot.sources import fetch_cis_disclosures_with_health


def _registry() -> dict[str, dict]:
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    return {row["id"]: row for row in config["cis_source_registry"]}


def _kase(event_id: str, title: str, body: str) -> tuple[str, str]:
    payload = {"b": {
        "id": int(event_id), "create_datetime": "2026-05-25T12:27:00",
        "language": "en", "subject": title, "body": body,
    }}
    page = f"<html><script>{json.dumps(payload, separators=(',', ':'))}</script></html>"
    return page, f"https://kase.kz/en/information/news/show/{event_id}"


def _amx(event_id: str, title: str, body: str) -> tuple[str, str]:
    return (
        f"<html><main><h1>{title}</h1><time>2026-06-17</time>{body}</main></html>",
        f"https://amx.am/en/news/sample/{event_id}",
    )


def _bvm(event_id: str, title: str, body: str) -> tuple[str, str]:
    return (
        f'<html><section class="contentBox"><h2 class="title1">{title}</h2><time>2026-06-23</time>{body}</section></html>',
        f"https://www.bvm.md/en/news/{event_id}/",
    )


KASE_POSITIVE = (
    _kase("1567249", "Three issues of KMF Bank bonds are included in KASE official list", """
        KZ2C00018034 (MFKMb10; KZT 1,000, KZT 10.0 bn; 2 years);
        KZ2C00018125 (MFKMb11; KZT 1,000, KZT 10.0 bn; 2 years);
        KZ2C00018257 (MFKMb12; KZT 1,000, KZT 10.0 bn; 3 years).
        These are the first, second and third issues under the third bond program of KMF Bank JSC.
    """),
    _kase("1566344", "Qazaqstan Investment Corporation bonds included in private placement market", """
        Bonds of Qazaqstan Investment Corporation JSC KZ2C00018182 (QICb1; USD 1,000, USD 500 mln; 5 years)
        are included in KASE official list. Coupon rate 6.5%.
    """),
    _kase("1564001", "International bonds of Kazakhstan Temir Zholy included in KASE official list", """
        Bonds of NC Kazakhstan Temir Zholy JSC XS3353982112 (KZT 1,000, USD 500 mln; 5 years)
        and XS3353982385 (KZT 1,000, USD 500 mln; 10 years) are included in KASE official list.
    """),
)

KASE_NEGATIVE = (
    _kase("1570001", "Government bonds included in KASE official list", "Government bonds KZK100000001 were listed."),
    _kase("1570002", "A-cars LLP paid fourth coupon on bonds KZ2P00011364", "Coupon payment amounted to KZT 292,500,000."),
    _kase("1570003", "ForteBank JSC reported confirmation of ratings", "Fitch Ratings affirmed the bank ratings."),
)

AMX_POSITIVE = (
    _amx("2574", '"Ameriabank" CJSC’s bonds will be listed on Armenia Stock Exchange', """
        <table><tr><td>Name of the issuer</td><td>"Ameriabank" CJSC</td></tr>
        <tr><td>Type of security</td><td>nominal, coupon bond</td></tr>
        <tr><td>Issuance date</td><td>5/19/2026</td></tr>
        <tr><td>Placement period - start/end</td><td>5/19/2026–6/12/2026</td></tr>
        <tr><td>ISIN</td><td>AMAMRBBNQER5</td></tr><tr><td>Nominal Value</td><td>10,000 USD</td></tr>
        <tr><td>Number of securities</td><td>5,000</td></tr><tr><td>Maturity Date</td><td>perpetual</td></tr>
        <tr><td>Coupon Rate</td><td>8.5%</td></tr></table><p>Placement was carried out in the stated period.</p>
    """),
    _amx("2364", "Globbing LLC bonds will be listed on Armenia Stock Exchange", """
        <p>Name of the issuer Global Shipping LLC Type of security nominal coupon bonds ISIN AMGBLSB2DER1
        Aggregate nominal amount 1,500,000,000 AMD Nominal Value 50,000 AMD Number of securities 30,000
        Coupon Rate 12% Placement was carried out from 12/12/2025 to 1/5/2026.</p>
    """),
    _amx("2400", "Armenian Economic Development Bank OJSC bonds will be listed", """
        <p>Name of the issuer Armenian Economic Development Bank OJSC Type of security nominal coupon bond
        ISIN AMHEZBB2QER5 Nominal Value 10,000 AMD Number of securities 400,000 Coupon Rate 10.25%
        Placement was carried out from 2/23/2026 to 2/24/2026.</p>
    """),
)

AMX_NEGATIVE = (
    _amx("2467", "Auction for placement of government bonds held", "<p>Government bonds AMGB1129A357 were allocated.</p>"),
    _amx("2501", "Branch opening. Ameriabank CJSC", "<p>A new branch opened.</p>"),
    _amx("2502", "Admission of securities for REPO trading", "<p>Routine REPO admission without a current issuance.</p>"),
)

BVM_POSITIVE = (
    _bvm("1655", "Admission of the 25th issue of corporate bonds of Commercial Bank MOLDOVA-AGROINDBANK JSC (MD1004000250)", """
        <p>ISIN: MD1004000250</p><p>Value, MDL 172 880 000</p><p>Number of issued bonds, un. 8 644</p>
        <p>Nominal value, MDL 20 000</p><p>Issue date 17.06.2026</p><p>Admission date 24.06.2026</p>
        <a href="/files/issue-25-prospect.pdf">Prospectus</a>
        <p>This issue is within the bond Offer Program with a target of 2,000,000,000 MDL.</p>
    """),
    _bvm("1644", "Admission of the 24th issue of corporate bonds of Commercial Bank MOLDOVA-AGROINDBANK JSC (MD1004000243)", """
        <p>ISIN: MD1004000243</p><p>Value, MDL 160 000 000</p><p>Number of issued bonds, un. 8 000</p>
        <p>Nominal value, MDL 20 000</p><p>Issue date 05.05.2026</p><p>Admission date 12.05.2026</p>
    """),
    _bvm("1635", "Admission of the 23rd issue of corporate bonds of Commercial Bank MOLDOVA-AGROINDBANK JSC (MD1004000235)", """
        <p>ISIN: MD1004000235</p><p>Value, MDL 163 820 000</p><p>Number of issued bonds, un. 8 191</p>
        <p>Nominal value, MDL 20 000</p><p>Issue date 27.03.2026</p><p>Admission date 02.04.2026</p>
    """),
)

BVM_NEGATIVE = (
    _bvm("1661", "Admission of two issues of Government Bonds", "<p>Government bonds were admitted.</p>"),
    _bvm("1649", "Provisional admission within the ATS of shares issued by JSC Test", "<p>Temporary technical admission MD14TEST1001.</p>"),
    _bvm("1648", "Daily trade statistics", "<p>Trading volume and number of transactions.</p>"),
)


class CisExchangeSourceTests(TestCase):
    def setUp(self) -> None:
        self.sources = _registry()

    def test_wave1_registry_is_implemented_but_not_enabled(self):
        expected = {
            "kz-kase": ("Kazakhstan", "KASE", "IMPLEMENTED_DISABLED_PENDING_TERMS"),
            "am-amx": ("Armenia", "AMX", "BLOCKED"),
            "md-bvm": ("Moldova", "BVM", "IMPLEMENTED_DISABLED_PENDING_TERMS"),
        }
        for source_id, (country, market, access_status) in expected.items():
            with self.subTest(source=source_id):
                source = self.sources[source_id]
                self.assertTrue(source["implemented"])
                self.assertFalse(source["enabled"])
                self.assertFalse(source["required"])
                self.assertEqual(source["connector"], "exchange_news")
                self.assertEqual(source["country"], country)
                self.assertEqual(source["market"], market)
                self.assertEqual(source["access_reuse_status"], access_status)
                for field in (
                    "source_family", "officialness_tier", "languages", "index_url", "detail_pattern",
                    "archive_days", "poll_interval_minutes", "production_status", "health_state",
                ):
                    self.assertIn(field, source)

    def test_indexes_preserve_numeric_ids_and_archive_pagination(self):
        fixtures = {
            "kz-kase": '<a href="/en/information/news/show/1567249">KMF Bank bonds included</a>',
            "am-amx": '<a href="/en/news/sample/2574">Ameriabank bonds will be listed</a>',
            "md-bvm": '<a href="/en/news/1655/">23.06.2026 - MAIB corporate bonds</a><a href="/en/news/page/50">2</a>',
        }
        for source_id, page in fixtures.items():
            entries, pages = parse_exchange_index(self.sources[source_id], page)
            self.assertEqual(len(entries), 1, source_id)
            self.assertTrue(entries[0].source_event_id.isdigit(), source_id)
            self.assertTrue(entries[0].url.startswith("https://"), source_id)
            if source_id == "md-bvm":
                self.assertEqual(pages, ["https://www.bvm.md/en/news/page/50"])

    def test_three_positive_publications_per_source(self):
        for source_id, fixtures in (
            ("kz-kase", KASE_POSITIVE), ("am-amx", AMX_POSITIVE), ("md-bvm", BVM_POSITIVE),
        ):
            for index, (page, url) in enumerate(fixtures):
                with self.subTest(source=source_id, fixture=index):
                    events = parse_exchange_detail(self.sources[source_id], page, url)
                    self.assertGreaterEqual(len(events), 1)
                    for event in events:
                        self.assertEqual(event.country, self.sources[source_id]["country"])
                        self.assertEqual(event.market, self.sources[source_id]["market"])
                        self.assertEqual(event.source_event_id, url.rstrip("/").split("/")[-1])
                        self.assertEqual(event.original_title, event.title)
                        self.assertEqual(event.instrument, "Corporate bonds")
                        self.assertIn(event.lifecycle_stage, {"Announced", "Issued"})

    def test_three_negative_publications_per_source_are_suppressed(self):
        for source_id, fixtures in (
            ("kz-kase", KASE_NEGATIVE), ("am-amx", AMX_NEGATIVE), ("md-bvm", BVM_NEGATIVE),
        ):
            for index, (page, url) in enumerate(fixtures):
                with self.subTest(source=source_id, fixture=index):
                    self.assertEqual(parse_exchange_detail(self.sources[source_id], page, url), [])

    def test_programme_tranche_and_distinct_isin_identity(self):
        events = parse_exchange_detail(self.sources["kz-kase"], *KASE_POSITIVE[0])
        self.assertEqual(len(events), 3)
        self.assertEqual(len({event.event_id for event in events}), 3)
        self.assertEqual(len({event.isin for event in events}), 3)
        self.assertEqual({event.amount for event in events}, {10_000_000_000})
        self.assertEqual({event.programme for event in events}, {"third bond program"})
        self.assertEqual({event.series for event in events}, {"MFKMb10", "MFKMb11", "MFKMb12"})
        self.assertEqual(len(deduplicate(events)), 3)

    def test_amx_amount_is_deterministically_derived(self):
        event = parse_exchange_detail(self.sources["am-amx"], *AMX_POSITIVE[0])[0]
        self.assertEqual(event.quantity, 5_000)
        self.assertEqual(event.denomination, 10_000)
        self.assertEqual(event.amount, 50_000_000)
        self.assertEqual(event.currency, "USD")
        self.assertTrue(event.amount_is_derived)
        self.assertEqual(event.maturity_date, "Perpetual")

    def test_bvm_issue_amount_does_not_use_programme_target(self):
        event = parse_exchange_detail(self.sources["md-bvm"], *BVM_POSITIVE[0])[0]
        self.assertEqual(event.isin, "MD1004000250")
        self.assertEqual(event.amount, 172_880_000)
        self.assertNotEqual(event.amount, 2_000_000_000)
        self.assertEqual(event.lifecycle_stage, "Issued")
        self.assertEqual(event.event_sub_stage, "placement_completed")
        self.assertEqual(event.document_urls, ["https://www.bvm.md/files/issue-25-prospect.pdf"])

    def test_lifecycle_is_monotonic_and_repeat_fetch_is_idempotent(self):
        announced = parse_exchange_detail(self.sources["kz-kase"], *KASE_POSITIVE[1])[0]
        issued_page, issued_url = _kase(
            "1567000", "Qazaqstan Investment Corporation completed placement of bonds KZ2C00018182",
            "Qazaqstan Investment Corporation JSC completed placement of bonds KZ2C00018182 (QICb1; KZT 1,000, USD 500 mln).",
        )
        issued = parse_exchange_detail(self.sources["kz-kase"], issued_page, issued_url)[0]
        self.assertEqual(announced.lifecycle_stage, "Announced")
        self.assertEqual(issued.lifecycle_stage, "Issued")
        records = [extract_deal_record(classify_event(event, []), []) for event in (announced, issued)]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "deals.json"
            first = update_precedent_database([record for record in records if record], path)
            second = update_precedent_database([record for record in records if record], path)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0]["status"], "Issued")
        self.assertEqual(second[0]["status"], "Issued")
        self.assertEqual(first[0]["isin"], "KZ2C00018182")

    def test_health_fails_closed_on_empty_markup_and_antibot(self):
        with self.assertRaises(SourceHealthError):
            parse_exchange_index(self.sources["kz-kase"], "<html><h1>News</h1></html>")
        with self.assertRaises(SourceHealthError):
            parse_exchange_index(self.sources["am-amx"], '<script src="/cdn-cgi/challenge-platform/main.js"></script>')

        source = dict(self.sources["am-amx"], enabled=True)
        with patch("deal_markets_copilot.sources._get_text", return_value='<script src="/cdn-cgi/challenge-platform/main.js"></script>'):
            events, runs = fetch_cis_disclosures_with_health({"cis_source_registry": [source]})
        self.assertEqual(events, [])
        self.assertEqual(runs[0]["status"], "error")
        self.assertFalse(runs[0]["required"])
        self.assertIn("anti-bot", runs[0]["error"])

    def test_fetch_respects_configured_archive_window(self):
        recent_page, _ = BVM_POSITIVE[0]
        index = (
            '<a href="/en/news/1655/">23.06.2026 - Admission of corporate bonds MD1004000250</a>'
            '<a href="/en/news/1400/">01.01.2025 - Admission of corporate bonds MD1004000100</a>'
        )
        source = dict(self.sources["md-bvm"], enabled=True, archive_days=90, max_pages=1, max_detail_requests=8)
        with patch("deal_markets_copilot.sources._get_text", side_effect=[index, recent_page]):
            events, runs = fetch_cis_disclosures_with_health({"cis_source_registry": [source]})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].isin, "MD1004000250")
        self.assertEqual(runs[0]["detail_requests"], 1)
        self.assertEqual(runs[0]["candidate_publications"], 1)

    def test_quality_gate_requires_complete_economics_even_for_official_source(self):
        complete = parse_exchange_detail(self.sources["am-amx"], *AMX_POSITIVE[0])[0]
        complete_record = extract_deal_record(classify_event(complete, []), [])
        self.assertIsNotNone(complete_record)
        self.assertEqual(complete_record.quality_status, "approved")
        self.assertEqual(complete_record.geography, "Armenia")
        self.assertEqual(complete_record.sources[0]["market"], "AMX")
        self.assertTrue(complete_record.sources[0]["amount_is_derived"])

        page, url = _amx("2600", "Test Issuer CJSC bonds will be listed", """
            <p>Name of the issuer Test Issuer CJSC Type of security nominal coupon bond ISIN AMTESTB2QER5</p>
        """)
        incomplete = parse_exchange_detail(self.sources["am-amx"], page, url)[0]
        incomplete_record = extract_deal_record(classify_event(incomplete, []), [])
        self.assertEqual(incomplete_record.quality_status, "review")
        self.assertIn("missing_transaction_value", incomplete_record.quality_flags)
        self.assertIn("missing_currency", incomplete_record.quality_flags)

    def test_disabled_coverage_states_render_in_ru_and_en_filters(self):
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        with TemporaryDirectory() as directory:
            path = build_html_report([], config, Path(directory) / "report.html", "live", health={
                "build_id": "fixture", "dataset_sha256": "f" * 64,
                "system_status": "warning", "source_status": "ok", "freshness_status": "ok",
                "source_age_minutes": 1, "freshness_limit_minutes": 90,
            })
            document = path.read_text(encoding="utf-8")
        self.assertIn('value="Armenia"', document)
        self.assertIn('value="Moldova"', document)
        self.assertIn('data-ru="Реализован, отключён" data-en="Implemented, disabled"', document)
        self.assertIn('data-ru="Заблокирован" data-en="Blocked"', document)
        self.assertIn("IMPLEMENTED_DISABLED_PENDING_TERMS", document)
        self.assertIn("blocked_anti_bot", document)


if __name__ == "__main__":
    import unittest
    unittest.main()
