from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import ClassifiedEvent
from .classifier import is_technical_exchange_notice


DELIVERABLES = {
    "M&A": "Transaction snapshot + precedent transactions",
    "ECM": "Trading comps + equity issuance screen",
    "DCM": "Debt comps + maturity profile",
    "Earnings": "Updated KPIs + valuation bridge",
    "Regulatory": "Milestone log + open legal questions",
    "Macro": "Market assumptions + valuation sensitivity",
    "Strategic": "Company update + opportunity screen",
}


def load_previous_snapshot(path: str | Path) -> dict:
    snapshot = Path(path)
    if not snapshot.exists():
        return {}
    try:
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def build_morning_workflow(
    items: list[ClassifiedEvent],
    market_snapshot: list[dict],
    config: dict,
    previous_snapshot: dict | None = None,
    deal_records: list[dict] | None = None,
    as_of: datetime | None = None,
) -> dict:
    """Turn public signals into a repeatable junior-banker morning workflow."""
    previous = previous_snapshot or {}
    valid_baseline = previous.get("workflow_version") in {1, 2}
    previous_ids = {
        row.get("event", {}).get("event_id")
        for row in previous.get("events", [])
        if isinstance(row, dict)
    } if valid_baseline else set()

    ranked = sorted(
        (item for item in items if is_actionable_signal(item)),
        key=lambda item: (item.score, item.event.published_at), reverse=True,
    )
    new_ids = {
        item.event.event_id for item in ranked
        if item.event.event_id and item.event.event_id not in previous_ids
    }
    hypotheses = _build_hypotheses(ranked, config.get("deal_hypotheses", []), new_ids)
    hypothesis_by_event: dict[str, list[str]] = {}
    for hypothesis in hypotheses:
        for event_id in hypothesis["signal_ids"]:
            hypothesis_by_event.setdefault(event_id, []).append(hypothesis["id"])

    tasks = _build_tasks(
        ranked, market_snapshot, hypothesis_by_event, new_ids, config, deal_records or [], as_of
    )
    move_threshold = float(config.get("workflow", {}).get("market_move_threshold", 2.0))
    market_moves = [
        quote for quote in market_snapshot
        if quote.get("change_percent") is not None
        and abs(float(quote["change_percent"])) >= move_threshold
    ]
    market_moves.sort(key=lambda quote: abs(float(quote["change_percent"])), reverse=True)

    attention = sum(hypothesis["status"] == "attention" for hypothesis in hypotheses)
    readout = _build_readout(ranked, tasks, market_moves, new_ids)
    baseline_label = "baseline_created" if not valid_baseline else "compared_with_previous_run"
    if new_ids:
        summary = (
            f"{len(new_ids)} новых сигналов с прошлого запуска; "
            f"{len(tasks)} действий в очереди; {attention} гипотез требуют внимания."
        )
    else:
        summary = (
            f"Новых сигналов с прошлого запуска нет; "
            f"в очереди остаётся {len(tasks)} действий по текущему покрытию."
        )

    return {
        "baseline_status": baseline_label,
        "new_event_ids": sorted(new_ids),
        "new_signals": len(new_ids),
        "market_moves": market_moves,
        "hypotheses": hypotheses,
        "tasks": tasks,
        "attention_hypotheses": attention,
        "summary": summary,
        "readout": readout,
    }


def is_actionable_signal(item: ClassifiedEvent) -> bool:
    """Exclude exchange plumbing and market-roundup stories from banker actions."""
    text = f"{item.event.title}. {item.event.summary}".lower()
    if is_technical_exchange_notice(text):
        return False
    non_actionable = (
        r"(?:price target|target price|analyst recommendation|целева\w*\s+цен|таргет\w*\s+цен|рекомендаци\w*\s+аналитик)",
        r"(?:опроверг|не подтвердил|denied|denies|no agreement)",
        r"(?:купонн\w*\s+выплат|выплат\w*\s+купон|coupon payment)",
        r"(?:погашени\w*\s+облигац|погасил\w*.{0,40}облигац|redemption amount|bond redemption)",
        r"(?:выкуп\w*\s+акци|\bbuyback\b)",
        r"объем (?:ipo|рынка ipo|продаж акций).+(?:полугоди|квартал|год)",
        r"рынок (?:ipo|облигаций).+(?:обзор|итоги|рекорд)",
        r"опасени[яй] инвесторов",
    )
    return not any(re.search(pattern, text, re.I) for pattern in non_actionable)


def _build_hypotheses(
    items: list[ClassifiedEvent], hypotheses: list[dict], new_ids: set[str]
) -> list[dict]:
    output: list[dict] = []
    for raw in hypotheses:
        tickers = set(raw.get("tickers", []))
        categories = set(raw.get("monitor_categories", []))
        matched = [
            item for item in items
            if tickers.intersection(item.matched_coverage)
            and (not categories or item.category in categories)
        ]
        new_matched = [item for item in matched if item.event.event_id in new_ids]
        high_new = [item for item in new_matched if item.score >= 6]
        status = "attention" if high_new or len(new_matched) >= 2 else "active"
        output.append({
            "id": raw.get("id", f"H-{len(output)+1:02d}"),
            "title": raw.get("title", "Untitled hypothesis"),
            "stage": raw.get("stage", "Screening"),
            "status": status,
            "tickers": sorted(tickers),
            "thesis": raw.get("thesis", ""),
            "decision_question": raw.get("decision_question", ""),
            "deliverable": raw.get("deliverable", "Opportunity screen"),
            "signal_count": len(matched),
            "new_signal_count": len(new_matched),
            "signal_ids": [item.event.event_id for item in matched],
            "latest_signal": matched[0].event.title if matched else "Новых подтверждающих сигналов нет",
        })
    return output


def _build_tasks(
    items: list[ClassifiedEvent],
    market_snapshot: list[dict],
    hypothesis_by_event: dict[str, list[str]],
    new_ids: set[str],
    config: dict,
    deal_records: list[dict],
    as_of: datetime | None,
) -> list[dict]:
    limit = int(config.get("workflow", {}).get("max_actions", 8))
    tasks: list[dict] = []
    deal_index = _index_deal_records(deal_records)
    for item in items:
        event_id = item.event.event_id
        deal = _deal_for_item(item, deal_index)
        task_spec = _deal_task_spec(deal) if deal else None
        if deal and task_spec is None:
            continue
        title = task_spec["title"] if task_spec else item.next_action
        action_type = task_spec["action_type"] if task_spec else item.next_action
        tasks.append({
            "id": _stable_task_id(str(deal.get("deal_id") if deal else event_id), action_type),
            "priority": task_spec["priority"] if task_spec else ("P1" if item.score >= 6 else "P2"),
            "state": "new" if event_id in new_ids else "open",
            "title": title,
            "deliverable": task_spec["deliverable"] if task_spec else DELIVERABLES.get(item.category, "Analyst update"),
            "coverage": ", ".join(item.matched_coverage) or "MARKET",
            "category": item.category,
            "source_url": item.event.url,
            "source_title": item.event.title,
            "hypothesis_ids": hypothesis_by_event.get(event_id, []),
            "deal_id": deal.get("deal_id", "") if deal else "",
            "quality_status": deal.get("quality_status", "") if deal else "",
            "quality_flags": list(deal.get("quality_flags", [])) if deal else [],
            "reason": task_spec.get("reason", "") if task_spec else "",
            "required_source": task_spec.get("required_source", "") if task_spec else "",
        })

    threshold = float(config.get("workflow", {}).get("market_move_threshold", 2.0))
    market_task_date = (as_of or datetime.now(ZoneInfo("Europe/Moscow"))).astimezone(
        ZoneInfo("Europe/Moscow")
    ).date().isoformat()
    for quote in market_snapshot:
        change = quote.get("change_percent")
        if change is None or abs(float(change)) < threshold:
            continue
        ticker = quote.get("ticker", "SECURITY")
        title = f"Проверить драйвер движения {ticker} ({float(change):+.2f}%) и обновить trading comps."
        tasks.append({
            "id": _stable_task_id(ticker, f"market-move|{market_task_date}"),
            "priority": "P1" if abs(float(change)) >= 5 else "P2",
            "state": "market",
            "title": title,
            "deliverable": "Trading comps + market movement note",
            "coverage": ticker,
            "category": "Market",
            "source_url": quote.get("source_url", ""),
            "source_title": f"MOEX quote for {ticker}",
            "hypothesis_ids": [],
        })

    priority_order = {"P1": 0, "P2": 1, "P3": 2}
    tasks.sort(key=lambda task: (priority_order.get(task["priority"], 9), task["state"] != "new"))
    unique: dict[str, dict] = {}
    for task in tasks:
        unique.setdefault(task["id"], task)
    return list(unique.values())[:limit]


def _index_deal_records(rows: list[dict]) -> dict[str, dict[str, dict]]:
    by_event_id: dict[str, dict] = {}
    by_url: dict[str, dict] = {}
    for row in rows:
        deal_id = str(row.get("deal_id") or "")
        if deal_id.startswith("DL-"):
            by_event_id.setdefault(deal_id[3:], row)
        urls = {str(row.get("source_url") or "")}
        for source in row.get("sources", []):
            if not isinstance(source, dict):
                continue
            urls.add(str(source.get("url") or ""))
            for representation in source.get("representations", []):
                if isinstance(representation, dict):
                    urls.add(str(representation.get("url") or ""))
        for url in urls - {""}:
            existing = by_url.get(url)
            if existing is None or _deal_task_rank(row) > _deal_task_rank(existing):
                by_url[url] = row
    return {"by_event_id": by_event_id, "by_url": by_url}


def _deal_task_rank(row: dict) -> tuple[int, int, int]:
    return (
        {"approved": 2, "review": 1, "rejected": 0}.get(str(row.get("quality_status")), 0),
        1 if row.get("record_kind") == "deal" else 0,
        int(row.get("quality_score") or 0),
    )


def _deal_for_item(item: ClassifiedEvent, index: dict[str, dict[str, dict]]) -> dict | None:
    return (
        index["by_event_id"].get(item.event.event_id)
        or index["by_url"].get(item.event.url)
    )


def _is_missing(value: object) -> bool:
    return value in {None, "", "Not disclosed", "Not applicable"}


def _display_amount(row: dict) -> str:
    value = row.get("transaction_value")
    currency = str(row.get("currency") or "")
    if not isinstance(value, (int, float)) or _is_missing(currency):
        return "disclosed-size"
    if value >= 1_000_000_000:
        amount = f"{value / 1_000_000_000:g}bn"
    elif value >= 1_000_000:
        amount = f"{value / 1_000_000:g}m"
    else:
        amount = f"{value:g}"
    return f"{amount} {currency}"


def _deal_task_spec(row: dict) -> dict | None:
    """Return one analyst-ready action for a normalized deal record."""
    flags = set(row.get("quality_flags") or [])
    if (
        row.get("record_kind") == "technical_filing"
        or row.get("quality_status") == "rejected"
        or "technical_filing" in flags
        or "non_transaction_or_technical_notice" in flags
    ):
        return None

    deal_type = str(row.get("deal_type") or "")
    status = str(row.get("status") or "Reported")
    issuer = str(row.get("target_or_issuer") or "the issuer")
    weak_evidence = bool(flags.intersection({"unverified_source", "aggregator_link", "single_secondary_source"}))
    source_map = {
        "DCM": "issuer, MOEX, NSD, or arranger disclosure",
        "ECM": "issuer, exchange, prospectus, or bookrunner disclosure",
        "M&A": "company, FAS, exchange, or transaction-party disclosure",
    }
    required_source = source_map.get(deal_type, "official primary disclosure")
    missing: list[str] = []

    if deal_type == "DCM":
        if "missing_issuer" in flags or _is_missing(row.get("target_or_issuer")):
            missing.append("issuer")
        if "missing_transaction_value" in flags or not isinstance(row.get("transaction_value"), (int, float)):
            missing.append("placement size")
        if "missing_currency" in flags or _is_missing(row.get("currency")):
            missing.append("currency")
    elif deal_type == "ECM":
        if "missing_issuer" in flags or _is_missing(row.get("target_or_issuer")):
            missing.append("issuer")
        if "missing_transaction_value" in flags or not isinstance(row.get("transaction_value"), (int, float)):
            missing.append("offering amount")
        if "missing_currency" in flags or _is_missing(row.get("currency")):
            missing.append("currency")
        if (
            row.get("quality_status") != "approved" or status in {"Priced", "Issued"}
        ) and _is_missing(row.get("price_per_share")):
            missing.append("offer price / share count")
    elif deal_type == "M&A":
        if "missing_target" in flags or "missing_both_parties" in flags or _is_missing(row.get("target_or_issuer")):
            missing.append("target")
        if "missing_acquirer" in flags or "missing_both_parties" in flags or _is_missing(row.get("acquirer_or_investor")):
            missing.append("acquirer")
        if row.get("quality_status") != "approved":
            if not isinstance(row.get("transaction_value"), (int, float)):
                missing.append("transaction value")
            if not isinstance(row.get("stake_percent"), (int, float)):
                missing.append("stake")
            if _is_missing(row.get("payment_form")):
                missing.append("payment form")

    if weak_evidence or missing:
        fields = ", ".join(dict.fromkeys(missing)) or "transaction terms"
        evidence_lead = "Verify official source and confirm" if weak_evidence else "Confirm"
        return {
            "action_type": f"verify-{deal_type.lower()}-{'evidence' if weak_evidence else 'fields'}-{'-'.join(dict.fromkeys(missing))}",
            "priority": "P1",
            "title": f"{evidence_lead} {fields}: use {required_source} before upgrading this {deal_type} record.",
            "deliverable": f"Verified {deal_type} terms + evidence note",
            "reason": "Official evidence is insufficient for approval." if weak_evidence else f"Blocking or decision-useful fields are missing: {fields}.",
            "required_source": required_source,
        }

    if deal_type in {"DCM", "ECM"} and status not in {"Priced", "Issued"}:
        milestone = "bookbuilding, pricing, settlement, and final placement" if deal_type == "ECM" else "pricing, final placement, and settlement"
        return {
            "action_type": f"monitor-{deal_type.lower()}-placement",
            "priority": "P2",
            "title": f"Monitor {milestone}: check {required_source} and update the record when final terms are disclosed.",
            "deliverable": f"{deal_type} execution-status update",
            "reason": f"The transaction is {status}, not yet at a final Priced/Issued stage.",
            "required_source": required_source,
        }

    if deal_type == "DCM":
        return {
            "action_type": "dcm-market-update",
            "priority": "P2",
            "title": f"Add to DCM market update: summarize {issuer}'s {_display_amount(row)} {status} issuance and prepare a comparable transaction note.",
            "deliverable": "DCM market update + comparable transaction note",
            "reason": "Approved issuance has disclosed size and currency and is ready for analyst use.",
            "required_source": required_source,
        }
    if deal_type == "ECM":
        return {
            "action_type": "ecm-market-update",
            "priority": "P2",
            "title": f"Add to ECM market update: capture {issuer}'s final terms and add the transaction to the precedent table.",
            "deliverable": "ECM market update + precedent table entry",
            "reason": "Approved offering terms are ready for analyst use.",
            "required_source": required_source,
        }
    if deal_type == "M&A":
        return {
            "action_type": "ma-precedent-note",
            "priority": "P2",
            "title": "Prepare a comparable transaction and buyer-landscape note using the confirmed parties and disclosed economics.",
            "deliverable": "M&A precedent transaction + buyer landscape note",
            "reason": "Approved parties and transaction economics are ready for precedent analysis.",
            "required_source": required_source,
        }
    return None


def _build_readout(
    items: list[ClassifiedEvent], tasks: list[dict], market_moves: list[dict], new_ids: set[str]
) -> list[dict]:
    top_new = next((item for item in items if item.event.event_id in new_ids), None)
    signal_text = top_new.event.title if top_new else "Новых событий после предыдущего запуска не обнаружено."
    if market_moves:
        move = market_moves[0]
        market_text = f"{move.get('ticker', 'Security')}: {float(move['change_percent']):+.2f}% к предыдущему закрытию."
    else:
        market_text = "Движений выше установленного порога нет."
    action_text = tasks[0]["title"] if tasks else "Очередь действий пуста."
    return [
        {"label": "Главный сигнал", "text": signal_text},
        {"label": "Рынок", "text": market_text},
        {"label": "Первое действие", "text": action_text},
    ]


def _stable_task_id(left: str, right: str) -> str:
    digest = hashlib.sha256(f"{left}|{right}".encode("utf-8")).hexdigest()[:12]
    return f"TASK-{digest}"
