from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
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
    fetch_cis_disclosures,
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
    quote_is_usable,
    quote_status,
    resolve_google_news_events,
    resolve_google_news_rows,
)
from deal_markets_copilot.telegram import load_dotenv, send_telegram
from deal_markets_copilot.workflow import build_morning_workflow, is_actionable_signal, load_previous_snapshot


def load_replay_precedents(precedent_path: Path) -> list[dict]:
    """Load replay data and persist any canonical migrations before exports.

    ``load_public_dataset`` applies the same row migration, source
    canonicalization and quality recomputation used by live updates.  Replay
    then exports CSV/HTML from those in-memory rows, so the JSON source of truth
    must be rewritten first; otherwise strict artifact verification can compare
    stale JSON fields against freshly migrated CSV fields.
    """
    precedents = load_public_dataset(precedent_path)
    write_precedent_database(precedents, precedent_path)
    return precedents


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
    source_runs: list[dict] = []
    def collect_source(name, fetcher, required=True):
        checked_at = datetime.now(ZoneInfo("Europe/Moscow")).isoformat(timespec="seconds")
        try:
            result = fetcher(config)
            row_errors = [row for row in result if isinstance(row, dict) and row.get("error")]
            status = _source_run_status(result, required=required)
            if row_errors:
                status = "error"
            source_runs.append({
                "name": name, "status": status, "records": len(result) - len(row_errors),
                "required": required, "checked_at": checked_at,
                "error": (
                    f"{len(row_errors)} item(s) unavailable" if row_errors
                    else "Required source returned zero records" if status == "empty" else ""
                ),
            })
            return result
        except Exception as exc:
            source_runs.append({
                "name": name, "status": "error", "records": 0, "required": required,
                "checked_at": checked_at, "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            })
            return []
    if args.replay:
        source_runs = list(previous_snapshot.get("health", {}).get("source_runs", []))
        events = [Event(**row["event"]) for row in previous_snapshot.get("events", []) if row.get("event")]
        archive_events = []
        market_snapshot = previous_snapshot.get("market", [])
    elif selected_mode == "live":
        official_events = collect_source("issuer_news", fetch_official_issuer_news)
        cis_events = collect_source("cis_disclosures", fetch_cis_disclosures, required=False)
        lookback = effective_news_lookback(config.get("live_data", {}))
        gdelt_events = collect_source("gdelt", fetch_gdelt_deal_news, required=False)
        events = (
            collect_source("moex_disclosures", fetch_moex_disclosures)
            + filter_recent_events(official_events, lookback)
            + collect_source("configured_rss", fetch_configured_sources)
            + collect_source("deal_news", fetch_deal_news)
            + collect_source("company_news", fetch_company_news)
            + filter_recent_events(gdelt_events, lookback)
            + filter_recent_events(cis_events, lookback)
        )
        archive_events = collect_source("deal_archive", fetch_deal_archive_news, required=False) + collect_source("sec_filings", fetch_sec_deal_filings, required=False) + official_events + gdelt_events + filter_recent_events(cis_events, config.get("live_data", {}).get("archive_lookback", "90d"))
        market_snapshot = collect_source("moex_quotes", fetch_moex_quotes, required=False)
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
    actionable = [item for item in classified if is_actionable_signal(item)]
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
    if args.replay:
        precedents = load_replay_precedents(precedent_path)
    elif selected_mode == "live":
        precedents = update_precedent_database(current_deals, precedent_path)
    else:
        precedents = [record.to_dict() for record in current_deals]
    if selected_mode == "live" and not args.replay:
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
    workflow = build_morning_workflow(
        actionable,
        market_snapshot,
        config,
        previous_snapshot=previous_snapshot,
        deal_records=precedents,
    )
    csv_path = write_precedents_csv(precedents, ROOT / "output" / "precedent_transactions.csv")
    health = _build_health(precedents, ROOT / "output" / "build_manifest.json", precedent_path, source_runs, market_snapshot)

    report_path = build_html_report(
        actionable,
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
        "events": [item.to_dict() for item in actionable],
        "workflow": workflow,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report created: {report_path}")
    print(f"Data snapshot: {snapshot_path}")
    print(f"Events included: {len(actionable)} ({len(classified) - len(actionable)} technical/context items suppressed)")
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


def _source_run_status(result: list, required: bool = True) -> str:
    """An empty required source is degraded, not a successful fetch."""
    if required and not result:
        return "empty"
    return "ok"


def _build_health(
    rows: list[dict],
    manifest_path: Path,
    dataset_path: Path | None = None,
    source_runs: list[dict] | None = None,
    market_snapshot: list[dict] | None = None,
) -> dict:
    dataset_bytes = dataset_path.read_bytes() if dataset_path and dataset_path.exists() else json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    build_id = dataset_sha256[:12]
    sources = [source for row in rows for source in row.get("sources", []) if isinstance(source, dict)]
    source_representations = [
        representation
        for source in sources
        for representation in (
            source.get("representations")
            if isinstance(source.get("representations"), list) and source.get("representations")
            else [source]
        )
        if isinstance(representation, dict) and representation.get("url")
    ]
    direct_sources = [source for source in source_representations if "news.google.com" not in str(source.get("url"))]
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
    source_groups = {str(source.get("source_type") or source.get("name") or "unknown") for source in sources if source.get("url")}
    runs = source_runs or []
    failed_runs = [run for run in runs if run.get("name") != "moex_quotes" and run.get("status") != "ok"]
    required_names = {"issuer_news", "moex_disclosures", "configured_rss", "deal_news", "company_news"}
    present_names = {str(run.get("name")) for run in runs}
    missing_required = sorted(required_names - present_names)
    discovery_names = {"configured_rss", "deal_news", "company_news", "issuer_news", "gdelt", "cis_disclosures"}
    discovery_records = sum(int(run.get("records") or 0) for run in runs if run.get("name") in discovery_names)
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    freshness_limit_minutes = 90 if now.weekday() < 5 and 8 <= now.hour < 20 else 72 * 60
    source_ages: list[float] = []
    source_checked_times: list[datetime] = []
    stale_sources: list[str] = []
    for run in runs:
        if run.get("name") == "moex_quotes":
            continue
        raw = str(run.get("checked_at") or "")
        try:
            checked = datetime.fromisoformat(raw).astimezone(ZoneInfo("Europe/Moscow"))
            age = max(0.0, (now - checked).total_seconds() / 60)
            run["age_minutes"] = round(age, 1)
            source_ages.append(age)
            source_checked_times.append(checked)
            if age > freshness_limit_minutes:
                stale_sources.append(str(run.get("name") or "unknown"))
        except ValueError:
            stale_sources.append(str(run.get("name") or "unknown"))
    discovery_ok = discovery_records > 0
    live_sources_ok = bool(runs) and not failed_runs and not missing_required and discovery_ok
    freshness_ok = bool(runs) and not stale_sources
    quotes = market_snapshot or []
    market_run = next((run for run in runs if run.get("name") == "moex_quotes"), None)
    market_quote_total = len(quotes)
    market_quote_count = sum(quote_is_usable(quote) for quote in quotes)
    market_complete_count = sum(quote_status(quote) == "valid" for quote in quotes)
    if market_quote_total and market_complete_count == market_quote_total:
        market_data_status = "ok"
    elif market_quote_count:
        market_data_status = "partial"
    elif market_run and market_run.get("status") == "error":
        market_data_status = "error"
    else:
        market_data_status = "unavailable"
    xlsx_synced = manifest.get("dataset_sha256") == dataset_sha256 and manifest.get("build_id") == build_id and manifest.get("record_count") == len(rows)
    return {
        "last_success_at": datetime.now(ZoneInfo("Europe/Moscow")).isoformat(timespec="minutes"),
        "build_id": build_id,
        "dataset_sha256": dataset_sha256,
        "record_count": len(rows),
        "key_deal_count": len(select_key_deals(rows, 10)),
        "approved_count": sum(row.get("quality_status") == "approved" for row in rows),
        "review_count": sum(row.get("quality_status") == "review" for row in rows),
        "rejected_count": sum(row.get("quality_status") == "rejected" for row in rows),
        "source_count": len(sources),
        "source_representation_count": len(source_representations),
        "direct_source_count": len(direct_sources),
        "aggregator_source_count": len(source_representations) - len(direct_sources),
        "critical_qa_issues": critical,
        "source_group_count": len(source_groups),
        "source_runs": runs,
        "discovery_record_count": discovery_records,
        "discovery_status": "ok" if discovery_ok else "empty",
        "missing_required_sources": missing_required,
        "stale_sources": sorted(set(stale_sources)),
        "source_age_minutes": round(max(source_ages), 1) if source_ages else None,
        "source_checked_at": min(source_checked_times).isoformat(timespec="minutes") if source_checked_times else None,
        "freshness_limit_minutes": freshness_limit_minutes,
        "source_status": "ok" if live_sources_ok else ("unknown" if not runs else "error"),
        "freshness_status": "ok" if freshness_ok else "stale",
        "market_data_status": market_data_status,
        "market_quote_count": market_quote_count,
        "market_quote_total": market_quote_total,
        "system_status": "ok" if not critical and xlsx_synced and source_groups and live_sources_ok and freshness_ok else "warning",
        "xlsx_synced": xlsx_synced,
        "xlsx_generated_at": manifest.get("generated_at"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
