from __future__ import annotations

import json
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]

from run import _build_health, classification_as_of
from deal_markets_copilot.classifier import _recency_bonus, classify_event, deduplicate
from deal_markets_copilot.cnpf_source import (
    CnpfFeedEntry,
    cnpf_candidate_type,
    parse_cnpf_atom,
    parse_cnpf_detail,
)
from deal_markets_copilot.deals import extract_deal_record, update_precedent_database
from deal_markets_copilot.exchange_sources import SourceHealthError
from deal_markets_copilot.models import Event
from deal_markets_copilot.report import build_html_report
from deal_markets_copilot.sources import CNPF_SSL_CONTEXT, HttpResponse, fetch_cis_disclosures_with_health
from deal_markets_copilot.workflow import build_morning_workflow


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


def _registry() -> dict[str, dict]:
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    return {row["id"]: row for row in config["cis_source_registry"]}


def _entry(
    entry_id: str,
    title: str,
    summary: str,
    *,
    published: str = "2026-07-21T09:00:00+03:00",
    link: str | None = None,
) -> str:
    canonical = link or f"https://www.cnpf.md/ro/eveniment-{entry_id}-7000.html"
    return f"""
      <entry>
        <id>tag:cnpf.md,2026:{entry_id}</id>
        <title>{title}</title>
        <published>{published}</published><updated>{published}</updated>
        <link rel="alternate" type="text/html" href="{canonical}" />
        <summary type="html">{summary}</summary><category term="Decizii" />
      </entry>
    """


def _atom(*entries: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <id>https://www.cnpf.md/ro/feed</id><title>CNPF Moldova</title>
      <updated>2026-07-22T10:00:00+03:00</updated>{''.join(entries)}
    </feed>"""


def _detail(body: str, *, document: str = "/files/decizia-1.pdf") -> str:
    return f"""<html><body><article><h1>Decizia CNPF</h1><p>{body}</p>
    <a href="{document}">Decizia oficială PDF</a></article>
    <footer>Reproducerea informației generale a site-ului se face conform termenilor CNPF.</footer>
    </body></html>"""


POSITIVE = (
    (
        _entry("bond-result", "Rezultatele emisiunii de obligațiuni corporative Victoriabank", "Obligațiunile au fost emise și plasate."),
        _detail("Emitent: Victoriabank S.A. Rezultatele emisiunii confirmă că obligațiunile au fost emise și plasate. ISIN MD1004000300. Valoarea emisiunii: 120 000 000 MDL. Data deciziei 21.07.2026."),
    ),
    (
        _entry("share-result", "Rezultatele emisiunii suplimentare de acțiuni FinComBank", "Acțiunile au fost emise."),
        _detail("Emitent: FinComBank S.A. Rezultatele emisiunii de acțiuni confirmă că valorile mobiliare au fost emise. Numărul de înregistrare: MD14FCB10009. Suma emisiunii: 80 000 000 lei. Data 20.07.2026."),
    ),
    (
        _entry("prospectus", "Aprobarea prospectului ofertei publice de obligațiuni MAIB", "Prospect de obligațiuni aprobat."),
        _detail("Emitent: BC MAIB S.A. Aprobarea prospectului ofertei publice de obligațiuni. ISIN MD1004000318. Valoarea ofertei: 150 milioane MDL. Data 19.07.2026."),
    ),
    (
        _entry("takeover", "Aprobarea ofertei de preluare a Societății Alfa", "Oferta de preluare a fost aprobată."),
        _detail("Ofertant: Beta Holding S.A. Societatea vizată: Societatea Alfa S.A. Aprobarea ofertei de preluare pentru 62,5% din acțiuni. Decizia nr. 33/4 din 18.07.2026."),
    ),
    (
        _entry("mandatory", "Aprobarea ofertei obligatorii și retragerii obligatorii", "Ofertă obligatorie și squeeze-out."),
        _detail("Ofertant: Gamma Capital S.A. Societatea vizată: Delta S.A. Aprobarea ofertei obligatorii și retragerii obligatorii pentru 95% din acțiuni. Decizia nr. 32/2 din 17.07.2026."),
    ),
    (
        _entry("review", "Rezultatele emisiunii de obligațiuni Test Leasing", "Rezultatul emisiunii este publicat."),
        _detail("Emitent: Test Leasing S.A. Rezultatele emisiunii de obligațiuni. Numărul de înregistrare: MD-TL-2026-01. Data 16.07.2026. Suma și moneda nu sunt divulgate."),
    ),
)


NEGATIVE = (
    _entry("insurance", "Supravegherea sectorului de asigurare", "Indicatori de solvabilitate ai asigurătorilor."),
    _entry("consumer", "Informare pentru consumatorii financiari", "Gestionarea petițiilor și reclamațiilor."),
    _entry("sanction", "Sancțiune administrativă aplicată", "Amendă pentru încălcarea raportării."),
    _entry("liquidation", "Inițierea procedurii de lichidare", "Insolvabilitatea participantului."),
    _entry("licence", "Retragerea licenței unui participant", "Decizie privind licența."),
    _entry("coupon", "Plata cuponului și rambursarea obligațiunilor", "Achitarea dobânzii."),
    _entry("government", "Emisiune de valori mobiliare de stat", "Titluri de stat și obligațiuni municipale."),
    _entry("press", "Comunicat de presă privind conferința CNPF", "Eveniment instituțional și instruire."),
)


class CnpfSourceTests(TestCase):
    def setUp(self) -> None:
        self.registry = _registry()
        self.source = self.registry["cnpf_moldova"]

    def test_registry_configuration_and_other_wave1_states(self):
        source = self.source
        self.assertTrue(source["implemented"])
        self.assertFalse(source["enabled"])
        self.assertFalse(source["required"])
        self.assertEqual(source["connector"], "cnpf_atom")
        self.assertEqual(source["country"], "Moldova")
        self.assertEqual(source["market"], "CNPF Moldova")
        self.assertEqual(source["source_family"], "securities_regulator")
        self.assertEqual(source["poll_interval_minutes"], 30)
        self.assertEqual(source["max_feed_requests"], 1)
        self.assertEqual(source["max_detail_requests"], 8)
        self.assertEqual(source["attribution"], "Source: CNPF Moldova — [canonical official link]")
        self.assertEqual((self.registry["kz-kase"]["enabled"], self.registry["kz-kase"]["production_status"]), (False, "implemented_disabled"))
        self.assertEqual((self.registry["am-amx"]["enabled"], self.registry["am-amx"]["production_status"]), (False, "blocked"))
        self.assertEqual((self.registry["md-bvm"]["enabled"], self.registry["md-bvm"]["production_status"]), (False, "implemented_disabled"))

    def test_atom_is_namespace_aware_deterministic_and_preserves_romanian(self):
        feed = parse_cnpf_atom(_atom(POSITIVE[0][0], POSITIVE[1][0]), self.source["feed_url"])
        self.assertEqual(feed.feed_id, "https://www.cnpf.md/ro/feed")
        self.assertEqual(len(feed.entries), 2)
        self.assertIn("obligațiuni", feed.entries[1].title)
        self.assertTrue(all(entry.published_at.endswith("+03:00") for entry in feed.entries))
        self.assertTrue(all(entry.url.startswith("https://www.cnpf.md/ro/") for entry in feed.entries))

    def test_safe_xml_and_required_structure_fail_closed(self):
        fixtures = (
            "<feed",
            "",
            "<!DOCTYPE feed [<!ENTITY x 'boom'>]><feed xmlns='http://www.w3.org/2005/Atom'></feed>",
            _atom(_entry("missing-url", "Rezultatele emisiunii de obligațiuni", "Obligațiuni emise.", link="https://evil.example/item")),
            _atom("<entry><title>Rezultatele emisiunii</title><updated>2026-07-20T10:00:00Z</updated><link rel='alternate' href='https://www.cnpf.md/ro/item-1.html'/></entry>"),
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture[:30]):
                with self.assertRaises(SourceHealthError):
                    parse_cnpf_atom(fixture, self.source["feed_url"])

    def test_duplicate_atom_entry_is_suppressed_by_immutable_id(self):
        item = POSITIVE[0][0]
        feed = parse_cnpf_atom(_atom(item, item), self.source["feed_url"])
        self.assertEqual(len(feed.entries), 1)
        self.assertEqual(feed.duplicates_suppressed, 1)

    def test_six_positive_fixtures_map_fields_lifecycle_and_attribution(self):
        for index, (entry_xml, detail) in enumerate(POSITIVE):
            with self.subTest(index=index):
                entry = parse_cnpf_atom(_atom(entry_xml), self.source["feed_url"]).entries[0]
                events = parse_cnpf_detail(self.source, detail, entry)
                self.assertGreaterEqual(len(events), 1)
                for event in events:
                    self.assertEqual(event.country, "Moldova")
                    self.assertEqual(event.market, "CNPF Moldova")
                    self.assertEqual(event.source_operator, "CNPF Moldova")
                    self.assertEqual(event.source_attribution, f"Source: CNPF Moldova — {event.url}")
                    self.assertEqual(event.original_title, event.title)
                    self.assertEqual(event.source_event_id, entry.entry_id)
                    self.assertNotIn("Suma și moneda", event.summary)
                    self.assertIn(event.lifecycle_stage, {"Announced", "Issued"})
        bond = parse_cnpf_detail(self.source, POSITIVE[0][1], parse_cnpf_atom(_atom(POSITIVE[0][0]), self.source["feed_url"]).entries[0])[0]
        self.assertEqual((bond.amount, bond.currency, bond.isin, bond.lifecycle_stage), (120_000_000, "MDL", "MD1004000300", "Issued"))
        prospectus = parse_cnpf_detail(self.source, POSITIVE[2][1], parse_cnpf_atom(_atom(POSITIVE[2][0]), self.source["feed_url"]).entries[0])[0]
        self.assertEqual((prospectus.lifecycle_stage, prospectus.event_sub_stage), ("Announced", "prospectus_approved"))
        takeover = parse_cnpf_detail(self.source, POSITIVE[3][1], parse_cnpf_atom(_atom(POSITIVE[3][0]), self.source["feed_url"]).entries[0])[0]
        self.assertEqual((takeover.target, takeover.acquirer, takeover.lifecycle_stage), ("Societatea Alfa S.A", "Beta Holding S.A", "Announced"))

    def test_eight_negative_fixtures_are_excluded_before_detail_requests(self):
        feed = parse_cnpf_atom(_atom(*NEGATIVE), self.source["feed_url"])
        self.assertEqual(len(feed.entries), 8)
        self.assertEqual([cnpf_candidate_type(entry) for entry in feed.entries], [""] * 8)

    def test_issue_registration_is_not_issued_and_explicit_complete_result_is_issued(self):
        entry = CnpfFeedEntry(
            "tag:cnpf.md,2026:registration", "Aprobarea prospectului de obligațiuni",
            "2026-07-20T10:00:00+03:00", "2026-07-20T10:00:00+03:00",
            "https://www.cnpf.md/ro/registration-7000.html", "Aprobarea prospectului de obligațiuni.",
        )
        page = _detail("Emitent: Issuer S.A. Înregistrarea emisiunii de obligațiuni. ISIN MD1004000334. Valoarea emisiunii: 50 000 000 MDL. Data 20.07.2026.")
        event = parse_cnpf_detail(self.source, page, entry)[0]
        self.assertEqual(event.lifecycle_stage, "Announced")
        self.assertNotEqual(event.lifecycle_stage, "Issued")

    def test_distinct_isins_and_source_identity_remain_distinct_and_repeatable(self):
        entry = CnpfFeedEntry(
            "tag:cnpf.md,2026:multi", "Rezultatele emisiunii de obligațiuni Multi S.A.",
            "2026-07-20T10:00:00+03:00", "2026-07-20T10:00:00+03:00",
            "https://www.cnpf.md/ro/multi-7000.html", "Obligațiunile au fost emise și plasate.",
        )
        page = _detail("Emitent: Multi S.A. Rezultatele emisiunii: obligațiunile au fost emise și plasate. ISIN MD1004000342 și MD1004000359. Valoarea emisiunii: 60 000 000 MDL. Programul nr. P-2026, tranșa T1. Data 20.07.2026.")
        events = parse_cnpf_detail(self.source, page, entry)
        self.assertEqual(len(events), 2)
        self.assertEqual(len({event.event_id for event in events}), 2)
        self.assertEqual({event.isin for event in events}, {"MD1004000342", "MD1004000359"})
        self.assertEqual(len(deduplicate(events + events)), 2)

    def test_quality_gate_and_review_reason_accuracy(self):
        complete_entry = parse_cnpf_atom(_atom(POSITIVE[0][0]), self.source["feed_url"]).entries[0]
        complete_event = parse_cnpf_detail(self.source, POSITIVE[0][1], complete_entry)[0]
        complete = extract_deal_record(classify_event(complete_event, []), [])
        self.assertEqual(complete.quality_status, "approved")
        self.assertEqual(complete.sources[0]["source_operator"], "CNPF Moldova")
        review_entry = parse_cnpf_atom(_atom(POSITIVE[5][0]), self.source["feed_url"]).entries[0]
        review_event = parse_cnpf_detail(self.source, POSITIVE[5][1], review_entry)[0]
        review = extract_deal_record(classify_event(review_event, []), [])
        self.assertEqual(review.quality_status, "review")
        self.assertIn("missing_transaction_value", review.quality_flags)
        self.assertIn("missing_currency", review.quality_flags)

    def test_excluded_items_create_zero_events_records_and_tasks(self):
        feed = parse_cnpf_atom(_atom(*NEGATIVE), self.source["feed_url"])
        events = [event for entry in feed.entries for event in ([] if not cnpf_candidate_type(entry) else [object()])]
        self.assertEqual(events, [])
        workflow = build_morning_workflow([], [], {"workflow": {"max_actions": 8}}, deal_records=[])
        self.assertEqual(workflow["tasks"], [])

    def test_page_specific_restriction_stops_without_persisting_content(self):
        entry = parse_cnpf_atom(_atom(POSITIVE[0][0]), self.source["feed_url"]).entries[0]
        restricted = "<html><article>Reproducerea este interzisă fără acordul prealabil al autorului. Emitent: Victoriabank S.A.</article></html>"
        with self.assertRaisesRegex(SourceHealthError, "page_specific_restriction"):
            parse_cnpf_detail(self.source, restricted, entry)

    def test_eligible_poll_once_updates_operational_state_and_reports_health(self):
        source = dict(self.source, enabled=True)
        atom = _atom(POSITIVE[0][0])
        responses = [
            HttpResponse(200, "application/atom+xml", atom, '"feed-v1"', "Wed, 22 Jul 2026 09:00:00 GMT"),
            HttpResponse(200, "text/html", POSITIVE[0][1]),
        ]
        state: dict = {}
        with patch("deal_markets_copilot.sources._get_http_response", side_effect=responses) as get:
            events, runs = fetch_cis_disclosures_with_health(
                {"cis_source_registry": [source]}, operational_state=state, now=NOW
            )
        self.assertEqual(get.call_count, 2)
        self.assertEqual(len(events), 1)
        self.assertEqual(runs[0]["feed_requests"], 1)
        self.assertEqual(runs[0]["detail_requests"], 1)
        self.assertEqual(runs[0]["parser_status"], "ok")
        self.assertEqual(runs[0]["health_reason"], "ok")
        self.assertEqual(state["cnpf_moldova"]["last_successful_poll_at"], NOW.isoformat())
        self.assertEqual(state["cnpf_moldova"]["etag"], '"feed-v1"')
        self.assertEqual(len(state["cnpf_moldova"]["entry_fingerprints"]), 1)

    def test_poll_at_plus_29_minutes_makes_zero_requests(self):
        source = dict(self.source, enabled=True)
        state = {"cnpf_moldova": {"last_successful_poll_at": (NOW - timedelta(minutes=29)).isoformat()}}
        with patch("deal_markets_copilot.sources._get_http_response") as get:
            events, runs = fetch_cis_disclosures_with_health(
                {"cis_source_registry": [source]}, operational_state=state, now=NOW
            )
        get.assert_not_called()
        self.assertEqual(events, [])
        self.assertEqual(runs[0]["status"], "skipped")
        self.assertFalse(runs[0]["poll_eligible"])
        self.assertEqual(runs[0]["request_count"], 0)

    def test_poll_at_plus_30_minutes_is_eligible_and_sends_validators(self):
        source = dict(self.source, enabled=True)
        state = {"cnpf_moldova": {
            "last_successful_poll_at": (NOW - timedelta(minutes=30)).isoformat(),
            "etag": '"feed-v1"',
            "last_modified": "Wed, 22 Jul 2026 09:00:00 GMT",
        }}
        with patch(
            "deal_markets_copilot.sources._get_http_response",
            return_value=HttpResponse(200, "application/atom+xml", _atom(*NEGATIVE)),
        ) as get:
            _, runs = fetch_cis_disclosures_with_health(
                {"cis_source_registry": [source]}, operational_state=state, now=NOW
            )
        self.assertEqual(get.call_count, 1)
        self.assertTrue(runs[0]["poll_eligible"])
        self.assertEqual(get.call_args.kwargs["extra_headers"], {
            "If-None-Match": '"feed-v1"',
            "If-Modified-Since": "Wed, 22 Jul 2026 09:00:00 GMT",
        })

    def test_not_modified_is_healthy_and_makes_zero_detail_requests(self):
        source = dict(self.source, enabled=True)
        prior = (NOW - timedelta(minutes=30)).isoformat()
        state = {"cnpf_moldova": {
            "last_successful_poll_at": prior,
            "etag": '"feed-v1"',
            "entry_fingerprints": {"tag:cnpf.md,2026:old": "f" * 64},
        }}
        with patch(
            "deal_markets_copilot.sources._get_http_response",
            return_value=HttpResponse(304, "", ""),
        ) as get:
            events, runs = fetch_cis_disclosures_with_health(
                {"cis_source_registry": [source]}, operational_state=state, now=NOW
            )
        self.assertEqual(get.call_count, 1)
        self.assertEqual(events, [])
        self.assertEqual(runs[0]["status"], "ok")
        self.assertEqual(runs[0]["health_reason"], "not_modified")
        self.assertEqual(runs[0]["detail_requests"], 0)
        self.assertEqual(state["cnpf_moldova"]["last_successful_poll_at"], NOW.isoformat())
        self.assertEqual(state["cnpf_moldova"]["entry_fingerprints"], {"tag:cnpf.md,2026:old": "f" * 64})

    def test_unchanged_whitelisted_entry_makes_zero_detail_requests(self):
        source = dict(self.source, enabled=True)
        state: dict = {}
        first = [
            HttpResponse(200, "application/atom+xml", _atom(POSITIVE[0][0])),
            HttpResponse(200, "text/html", POSITIVE[0][1]),
        ]
        with patch("deal_markets_copilot.sources._get_http_response", side_effect=first):
            fetch_cis_disclosures_with_health(
                {"cis_source_registry": [source]}, operational_state=state, now=NOW
            )
        with patch(
            "deal_markets_copilot.sources._get_http_response",
            return_value=HttpResponse(200, "application/atom+xml", _atom(POSITIVE[0][0])),
        ) as get:
            events, runs = fetch_cis_disclosures_with_health(
                {"cis_source_registry": [source]}, operational_state=state,
                now=NOW + timedelta(minutes=30),
            )
        self.assertEqual(get.call_count, 1)
        self.assertEqual(events, [])
        self.assertEqual(runs[0]["health_reason"], "healthy_unchanged")
        self.assertEqual(runs[0]["unchanged_candidates"], 1)
        self.assertEqual(runs[0]["detail_requests"], 0)

    def test_eight_detail_cap_and_one_feed_cap_are_hard(self):
        source = dict(self.source, enabled=True, max_detail_requests=99, max_feed_requests=99)
        entries = [
            _entry(str(index), f"Rezultatele emisiunii de obligațiuni Issuer {index}", "Obligațiunile au fost emise și plasate.")
            for index in range(9)
        ]
        detail = _detail("Emitent: Issuer S.A. Rezultatele emisiunii: obligațiunile au fost emise și plasate. ISIN MD1004000300. Valoarea emisiunii: 10 000 000 MDL. Data 21.07.2026.")
        responses = [HttpResponse(200, "application/atom+xml", _atom(*entries))] + [HttpResponse(200, "text/html", detail)] * 8
        with patch("deal_markets_copilot.sources._get_http_response", side_effect=responses) as get:
            _, runs = fetch_cis_disclosures_with_health(
                {"cis_source_registry": [source]}, operational_state={}, now=NOW
            )
        self.assertEqual(get.call_count, 9)
        self.assertEqual(runs[0]["feed_requests"], 1)
        self.assertEqual(runs[0]["detail_requests"], 8)
        self.assertEqual(runs[0]["whitelisted"], 9)

    def test_transport_content_type_challenge_and_parser_failures_are_explicit(self):
        source = dict(self.source, enabled=True)
        failures = (
            (HttpResponse(403, "text/html", "forbidden"), "http_403"),
            (HttpResponse(429, "text/html", "rate limited"), "http_429"),
            (HttpResponse(200, "text/html", "<html>challenge</html>"), "unexpected_content_type"),
            (HttpResponse(200, "application/atom+xml", "<feed"), "malformed_feed"),
        )
        for response, reason in failures:
            with self.subTest(reason=reason):
                state: dict = {}
                with patch("deal_markets_copilot.sources._get_http_response", return_value=response):
                    events, runs = fetch_cis_disclosures_with_health(
                        {"cis_source_registry": [source]}, operational_state=state, now=NOW
                    )
                self.assertEqual(events, [])
                self.assertEqual(runs[0]["status"], "error")
                self.assertIn(reason, runs[0]["error"])
                self.assertNotIn("cnpf_moldova", state)

    def test_transport_exception_keeps_request_diagnostics_and_fails_closed(self):
        source = dict(self.source, enabled=True)
        previous = (NOW - timedelta(minutes=30)).isoformat()
        state = {"cnpf_moldova": {"last_successful_poll_at": previous}}
        with patch("deal_markets_copilot.sources._get_http_response", side_effect=OSError("TLS trust failure")):
            events, runs = fetch_cis_disclosures_with_health(
                {"cis_source_registry": [source]}, operational_state=state, now=NOW
            )
        self.assertEqual(events, [])
        self.assertEqual(runs[0]["status"], "error")
        self.assertEqual(runs[0]["health_reason"], "transport_error")
        self.assertEqual(runs[0]["transport_error"], "OSError")
        self.assertEqual((runs[0]["feed_requests"], runs[0]["detail_requests"]), (1, 0))
        self.assertEqual(runs[0]["request_count"], 1)
        self.assertEqual(state["cnpf_moldova"]["last_successful_poll_at"], previous)

    @skipUnless(CNPF_SSL_CONTEXT is not None, "truststore dependency not installed in this CI phase")
    def test_transport_uses_platform_trust_with_required_verification(self):
        self.assertEqual(type(CNPF_SSL_CONTEXT).__module__.split(".")[0], "truststore")
        self.assertEqual(CNPF_SSL_CONTEXT.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(CNPF_SSL_CONTEXT.check_hostname)

    def test_replay_recency_uses_snapshot_clock_not_current_wall_clock(self):
        anchor = classification_as_of(
            {"generated_at": "2026-07-22T15:59:00+03:00"}, replay=True
        )
        self.assertEqual(anchor.isoformat(), "2026-07-22T12:59:00+00:00")
        self.assertEqual(_recency_bonus("2026-07-22 14:59:08", as_of=anchor), 0)
        first_replay_clock = datetime(2026, 7, 22, 14, 11, tzinfo=timezone.utc)
        self.assertEqual(_recency_bonus("2026-07-22 14:59:08", as_of=first_replay_clock), 1)

    def test_healthy_zero_whitelist_is_not_unhealthy_empty(self):
        source = dict(self.source, enabled=True)
        with patch("deal_markets_copilot.sources._get_http_response", return_value=HttpResponse(200, "application/atom+xml", _atom(*NEGATIVE))):
            events, runs = fetch_cis_disclosures_with_health(
                {"cis_source_registry": [source]}, operational_state={}, now=NOW
            )
        self.assertEqual(events, [])
        self.assertEqual(runs[0]["status"], "ok")
        self.assertEqual(runs[0]["health_reason"], "healthy_zero_whitelisted")
        self.assertEqual(runs[0]["excluded"], 8)

    def test_repeat_fetch_and_lifecycle_merge_reach_fixed_point(self):
        entry = parse_cnpf_atom(_atom(POSITIVE[0][0]), self.source["feed_url"]).entries[0]
        event = parse_cnpf_detail(self.source, POSITIVE[0][1], entry)[0]
        record = extract_deal_record(classify_event(event, []), [])
        with TemporaryDirectory() as directory:
            path = Path(directory) / "rows.json"
            first = update_precedent_database([record], path)
            first_bytes = path.read_bytes()
            second = update_precedent_database([record], path)
            second_bytes = path.read_bytes()
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0]["status"], "Issued")
        self.assertEqual(first_bytes, second_bytes)

    def test_disabled_fixture_and_replay_paths_do_not_consume_poll_state(self):
        state = {"cnpf_moldova": {"last_successful_poll_at": "2026-07-20T10:00:00+00:00"}}
        before = json.loads(json.dumps(state))
        disabled_source = dict(self.source, enabled=False)
        with patch("deal_markets_copilot.sources._get_http_response") as get:
            events, runs = fetch_cis_disclosures_with_health(
                {"cis_source_registry": [disabled_source]}, operational_state=state, now=NOW
            )
        get.assert_not_called()
        self.assertEqual((events, runs), ([], []))
        self.assertEqual(state, before)
        ordinary = Event("ordinary", NOW.isoformat(), "Title", "Summary", "Source", "https://example.com")
        self.assertFalse({"target", "acquirer", "source_operator", "source_attribution", "source_quality_flags"} & ordinary.to_dict().keys())

    def test_ru_en_coverage_moldova_filter_attribution_and_mobile_contract(self):
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        with TemporaryDirectory() as directory:
            path = build_html_report([], config, Path(directory) / "report.html", "live", health={
                "build_id": "fixture", "dataset_sha256": "f" * 64,
                "system_status": "warning", "source_status": "ok", "freshness_status": "ok",
                "source_age_minutes": 1, "freshness_limit_minutes": 90,
            })
            document = path.read_text(encoding="utf-8")
        self.assertIn('value="Moldova"', document)
        self.assertIn("Избранные официальные регуляторные события", document)
        self.assertIn("Selected official Moldova regulatory securities events", document)
        self.assertIn("Source: CNPF Moldova — [canonical official link]", document)
        self.assertIn("Ubuntu production transport не подтверждён", document)
        self.assertIn('data-ru="Реализован, отключён" data-en="Implemented, disabled"', document)
        self.assertIn(".coverage-grid{grid-template-columns:minmax(0,1fr)}", document)
        self.assertIn("overflow-wrap:anywhere", document)

    def test_optional_cnpf_failure_does_not_corrupt_other_required_source_health(self):
        required_names = ("issuer_news", "moex_disclosures", "configured_rss", "deal_news", "company_news")
        baseline = [
            {"name": name, "status": "ok", "records": 1, "required": True, "checked_at": "2099-01-01T10:00:00+03:00"}
            for name in required_names
        ]
        cnpf = {
            "name": "cis:cnpf_moldova", "source_id": "cnpf_moldova", "status": "error",
            "records": 0, "required": False, "checked_at": "2099-01-01T10:00:00+03:00",
            "error": "CnpfFetchError: malformed_feed",
        }
        with TemporaryDirectory() as directory:
            health = _build_health([], Path(directory) / "missing.json", source_runs=baseline + [cnpf])
        self.assertEqual(health["source_status"], "ok")


if __name__ == "__main__":
    import unittest
    unittest.main()
