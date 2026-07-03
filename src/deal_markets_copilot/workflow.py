from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import ClassifiedEvent


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

    tasks = _build_tasks(ranked, market_snapshot, hypothesis_by_event, new_ids, config)
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
    non_actionable = (
        r"^о проведении выкупа облигаций",
        r"^о регистрации (?:выпуска|проспекта|программы|изменений)",
        r"^о признании (?:выпуска|программы).+несостоявш",
        r"^о порядке (?:сбора заявок|приобретения облигаций|заключения сделок)",
        r"^дополнительные условия проведения торгов",
        r"^информация о кодах расчетов",
        r"^московская биржа начала торги",
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
) -> list[dict]:
    limit = int(config.get("workflow", {}).get("max_actions", 8))
    tasks: list[dict] = []
    for item in items:
        event_id = item.event.event_id
        tasks.append({
            "id": _stable_task_id(event_id, item.next_action),
            "priority": "P1" if item.score >= 6 else "P2",
            "state": "new" if event_id in new_ids else "open",
            "title": item.next_action,
            "deliverable": DELIVERABLES.get(item.category, "Analyst update"),
            "coverage": ", ".join(item.matched_coverage) or "MARKET",
            "category": item.category,
            "source_url": item.event.url,
            "source_title": item.event.title,
            "hypothesis_ids": hypothesis_by_event.get(event_id, []),
        })

    threshold = float(config.get("workflow", {}).get("market_move_threshold", 2.0))
    for quote in market_snapshot:
        change = quote.get("change_percent")
        if change is None or abs(float(change)) < threshold:
            continue
        ticker = quote.get("ticker", "SECURITY")
        title = f"Проверить драйвер движения {ticker} ({float(change):+.2f}%) и обновить trading comps."
        tasks.append({
            "id": _stable_task_id(ticker, f"market-move|{datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat()}"),
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
