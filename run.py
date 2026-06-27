from __future__ import annotations

import argparse
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from deal_markets_copilot.classifier import classify_event, deduplicate
from deal_markets_copilot.deals import extract_deal_record, update_precedent_database, write_precedents_csv
from deal_markets_copilot.report import build_html_report, build_telegram_digest
from deal_markets_copilot.sources import (
    fetch_company_news,
    fetch_configured_sources,
    fetch_deal_news,
    fetch_moex_quotes,
    load_demo_events,
)
from deal_markets_copilot.telegram import load_dotenv, send_telegram
from deal_markets_copilot.workflow import build_morning_workflow, load_previous_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Deal & Markets Intelligence Copilot")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="Use illustrative offline events")
    mode.add_argument("--live", action="store_true", help="Fetch enabled RSS/Atom feeds")
    parser.add_argument("--telegram", action="store_true", help="Send digest to Telegram")
    parser.add_argument("--serve", action="store_true", help="Generate demo and serve output on localhost:8765")
    args = parser.parse_args()

    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    selected_mode = "live" if args.live else "demo"
    snapshot_path = ROOT / "output" / "latest_snapshot.json"
    previous_snapshot = load_previous_snapshot(snapshot_path)
    if selected_mode == "live":
        events = fetch_deal_news(config) + fetch_company_news(config) + fetch_configured_sources(config)
        market_snapshot = fetch_moex_quotes(config)
    else:
        events = load_demo_events(ROOT / "data" / "sample_events.json")
        market_snapshot = []
    events = deduplicate(events)
    classified = [classify_event(event, config.get("coverage", [])) for event in events]
    if config.get("workflow", {}).get("deals_only"):
        deal_categories = set(config.get("workflow", {}).get("deal_categories", ["M&A", "ECM", "DCM"]))
        classified = [item for item in classified if item.category in deal_categories]
    min_score = config.get("thresholds", {}).get("dashboard_min_score", 3)
    classified = [item for item in classified if item.score >= min_score]
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
    precedent_path = ROOT / "data" / "precedent_transactions.json"
    precedents = (
        update_precedent_database(current_deals, precedent_path)
        if selected_mode == "live"
        else [record.to_dict() for record in current_deals]
    )
    csv_path = write_precedents_csv(precedents, ROOT / "output" / "precedent_transactions.csv")

    report_path = build_html_report(
        classified,
        config,
        ROOT / "output" / "deal_markets_brief.html",
        selected_mode,
        market_snapshot=market_snapshot,
        workflow=workflow,
        precedent_transactions=precedents,
    )
    snapshot_path.write_text(json.dumps({
        "workflow_version": 1,
        "mode": selected_mode,
        "market": market_snapshot,
        "events": [item.to_dict() for item in classified],
        "workflow": workflow,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report created: {report_path}")
    print(f"Data snapshot: {snapshot_path}")
    print(f"Events included: {len(classified)}")
    print(f"Precedent transactions: {len(precedents)}")
    print(f"Excel-compatible export: {csv_path}")

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


if __name__ == "__main__":
    raise SystemExit(main())
