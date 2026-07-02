from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from deal_markets_copilot.classifier import classify_event, deduplicate
from deal_markets_copilot.deals import (
    enrich_precedent_financials,
    extract_deal_record,
    load_public_dataset,
    merge_curated_precedents,
    select_key_deals,
    update_precedent_database,
    write_precedent_database,
    write_precedents_csv,
)
from deal_markets_copilot.models import Event
from deal_markets_copilot.report import build_html_report, build_telegram_digest
from deal_markets_copilot.sources import (
    fetch_company_news,
    fetch_configured_sources,
    fetch_deal_archive_news,
    fetch_deal_news,
    fetch_gdelt_deal_news,
    fetch_moex_disclosures,
    fetch_moex_quotes,
    fetch_official_issuer_news,
    fetch_sec_deal_filings,
    effective_news_lookback,
    filter_recent_events,
    load_demo_events,
    resolve_google_news_events,
    resolve_google_news_rows,
)
from deal_markets_copilot.telegram import load_dotenv, send_telegram
from deal_markets_copilot.workflow import build_morning_workflow, load_previous_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Deal & Markets Intelligence Copilot")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="Use illustrative offline events")
    mode.add_argument("--live", action="store_true", help="Fetch enabled RSS/Atom feeds")
    mode.add_argument("--replay", action="store_true", help="Rebuild from the latest saved live snapshot without network access")
    parser.add_argument("--telegram", action="store_true", help="Send digest to Telegram")
    parser.add_argument("--serve", action="store_true", help="Generate demo and serve output on localhost:8765")
    args = parser.parse_args()

    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    selected_mode = "live" if args.live or args.replay else "demo"
    snapshot_path = ROOT / "output" / "latest_snapshot.json"
    previous_snapshot = load_previous_snapshot(snapshot_path)
    if args.replay:
        events = [Event(**row["event"]) for row in previous_snapshot.get("events", []) if row.get("event")]
        archive_events = []
        market_snapshot = previous_snapshot.get("market", [])
    elif selected_mode == "live":
        official_events = fetch_official_issuer_news(config)
        lookback = effective_news_lookback(config.get("live_data", {}))
        gdelt_events = fetch_gdelt_deal_news(config)
        events = (
            fetch_moex_disclosures(config)
            + filter_recent_events(official_events, lookback)
            + fetch_configured_sources(config)
            + fetch_deal_news(config)
            + fetch_company_news(config)
            + filter_recent_events(gdelt_events, lookback)
        )
        archive_events = fetch_deal_archive_news(config) + fetch_sec_deal_filings(config) + official_events + gdelt_events
        market_snapshot = fetch_moex_quotes(config)
    else:
        events = load_demo_events(ROOT / "data" / "sample_events.json")
        archive_events = []
        market_snapshot = []
    events = deduplicate(events)
    classified = [classify_event(event, config.get("coverage", [])) for event in events]
    if config.get("workflow", {}).get("deals_only"):
        deal_categories = set(config.get("workflow", {}).get("deal_categories", ["M&A", "ECM", "DCM"]))
        classified = [item for item in classified if item.category in deal_categories]
    min_score = config.get("thresholds", {}).get("dashboard_min_score", 3)
    classified = [item for item in classified if item.score >= min_score]
    if args.live:
        resolve_google_news_events(
            [item.event for item in classified],
            limit=int(config.get("live_data", {}).get("max_live_link_resolutions", 12)),
        )
    workflow = build_morning_workflow(
        classified,
        market_snapshot,
        config,
        previous_snapshot=previous_snapshot,
    )
    current_deals = [
        record for item in classified
        if (record := extract_deal_record(item, config.get("coverage", []))) is not None
    ]
    if archive_events:
        archive_classified = [classify_event(event, config.get("coverage", [])) for event in deduplicate(archive_events)]
        archive_deals = [
            record for item in archive_classified
            if item.category in {"M&A", "ECM", "DCM"}
            and item.score >= config.get("thresholds", {}).get("archive_min_score", 3)
            and (record := extract_deal_record(item, config.get("coverage", []))) is not None
        ]
        current_deals.extend(archive_deals)
    precedent_path = ROOT / "data" / "precedent_transactions.json"
    precedents = (
        update_precedent_database(current_deals, precedent_path)
        if selected_mode == "live"
        else [record.to_dict() for record in current_deals]
    )
    if selected_mode == "live":
        curated = load_public_dataset(ROOT / "data" / "curated_precedents.json")
        financials = json.loads((ROOT / "data" / "financials.json").read_text(encoding="utf-8"))
        precedents = enrich_precedent_financials(merge_curated_precedents(precedents, curated), financials)
        write_precedent_database(precedents, precedent_path)
    upgraded_links = resolve_google_news_rows(
        precedents,
        limit=int(config.get("live_data", {}).get("max_archive_link_resolutions", 30)),
    ) if args.live else 0
    if upgraded_links:
        write_precedent_database(precedents, precedent_path)
    csv_path = write_precedents_csv(precedents, ROOT / "output" / "precedent_transactions.csv")
    health = _build_health(precedents, ROOT / "output" / "build_manifest.json")

    report_path = build_html_report(
        classified,
        config,
        ROOT / "output" / "deal_markets_brief.html",
        selected_mode,
        market_snapshot=market_snapshot,
        workflow=workflow,
        precedent_transactions=precedents,
        health=health,
    )
    snapshot_path.write_text(json.dumps({
        "workflow_version": 2,
        "generated_at": health["last_success_at"],
        "health": health,
        "mode": selected_mode,
        "market": market_snapshot,
        "events": [item.to_dict() for item in classified],
        "workflow": workflow,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report created: {report_path}")
    print(f"Data snapshot: {snapshot_path}")
    print(f"Events included: {len(classified)}")
    print(f"Precedent transactions: {len(precedents)}")
    print(f"Direct source links upgraded: {upgraded_links}")
    print(f"Excel-compatible export: {csv_path}")
    print(f"Build ID: {health['build_id']} | XLSX synced: {health['xlsx_synced']}")

    if args.telegram:
        load_dotenv(ROOT / ".env")
        threshold = config.get("thresholds", {}).get("telegram_min_score", 6)
        digest_items = [item for item in classified if item.score >= threshold]
        send_telegram(build_telegram_digest(digest_items, config.get("telegram", {}).get("max_items", 5)))
        print("Telegram digest sent")

    if args.serve:
        class OutputHandler(SimpleHTTPRequestHandler):
            def __init__(self, *handler_args, **handler_kwargs):
                super().__init__(*handler_args, directory=str(ROOT / "output"), **handler_kwargs)

        server = ThreadingHTTPServer(("127.0.0.1", 8765), OutputHandler)
        print("Open http://127.0.0.1:8765/deal_markets_brief.html")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def _build_health(rows: list[dict], manifest_path: Path) -> dict:
    payload = "\n".join(
        "|".join(str(row.get(field) or "") for field in (
            "deal_id", "record_kind", "quality_status", "source_count", "headline",
        ))
        for row in sorted(rows, key=lambda item: str(item.get("deal_id") or ""))
    )
    build_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    sources = [source for row in rows for source in row.get("sources", []) if isinstance(source, dict)]
    direct_sources = [source for source in sources if source.get("url") and "news.google.com" not in str(source.get("url"))]
    critical = 0
    for row in rows:
        if row.get("quality_status") == "approved" and row.get("record_kind") != "deal":
            critical += 1
        if row.get("deal_type") != "M&A" and row.get("stake_percent") not in {None, "", 0}:
            critical += 1
        if row.get("deal_type") == "DCM" and row.get("acquirer_or_investor") not in {None, "", "Not applicable", "Not disclosed"}:
            critical += 1
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
    return {
        "last_success_at": datetime.now().astimezone().isoformat(timespec="minutes"),
        "build_id": build_id,
        "record_count": len(rows),
        "key_deal_count": len(select_key_deals(rows, 10)),
        "approved_count": sum(row.get("quality_status") == "approved" for row in rows),
        "review_count": sum(row.get("quality_status") == "review" for row in rows),
        "rejected_count": sum(row.get("quality_status") == "rejected" for row in rows),
        "source_count": len(sources),
        "direct_source_count": len(direct_sources),
        "aggregator_source_count": len(sources) - len(direct_sources),
        "critical_qa_issues": critical,
        "xlsx_synced": manifest.get("build_id") == build_id and manifest.get("record_count") == len(rows),
        "xlsx_generated_at": manifest.get("generated_at"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
