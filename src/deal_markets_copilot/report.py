from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

from .deals import median_multiples, select_deal_buckets
from .models import ClassifiedEvent
from .sources import quote_is_usable, quote_status


def build_html_report(
    items: list[ClassifiedEvent],
    config: dict,
    output_path: str | Path,
    mode: str,
    market_snapshot: list[dict] | None = None,
    workflow: dict | None = None,
    precedent_transactions: list[dict] | None = None,
    health: dict | None = None,
) -> Path:
    """Build a daily IB workflow desk rather than a generic news dashboard."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    ranked = sorted(items, key=lambda item: (item.score, item.event.published_at), reverse=True)
    quotes = market_snapshot or []
    flow = workflow or _empty_workflow()
    precedents = precedent_transactions or []
    health = health or {}
    healthy = health.get("system_status") == "ok"
    deal_buckets = select_deal_buckets(precedents, 10)
    key_deals = deal_buckets["deal"]
    multiple_deals = sorted(
        (row for row in precedents if row.get("deal_type") == "M&A" and row.get("quality_status") == "approved" and row.get("multiple_eligible") and (row.get("ev_revenue") or row.get("ev_ebitda"))),
        key=lambda row: row.get("announced_date", ""), reverse=True,
    )
    precedent_stats = median_multiples(precedents)
    sectors = sorted({str(row.get("sector")) for rows in deal_buckets.values() for row in rows if row.get("sector") not in {None, "", "Not classified"}})
    sector_options = "".join(f'<option value="{html.escape(value, quote=True)}">{html.escape(value)}</option>' for value in sectors)
    counts = Counter(item.category for item in ranked)
    generated = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y · %H:%M")
    news_window = "72H CATCH-UP" if datetime.now(ZoneInfo("Europe/Moscow")).weekday() in {0, 5, 6} else "24H"
    live = mode == "live"
    new_ids = set(flow.get("new_event_ids", []))
    scope = " · ".join(row.get("ticker", "") for row in config.get("coverage", []) if row.get("ticker")) or "CUSTOM"

    event_payload = [_event_payload(item, item.event.event_id in new_ids) for item in ranked]
    payload_json = json.dumps(event_payload, ensure_ascii=False).replace("</", "<\\/")
    brief_text = _brief_text(flow, generated)
    brief_json = json.dumps(brief_text, ensure_ascii=False).replace("</", "<\\/")

    document = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Deal Market Monitor</title><style>{_CSS}</style></head>
<body>
<header class="site-header"><div class="nav-wrap">
  <a class="brand" href="#brief"><span class="brand-mark">DM</span><span><strong>Deal Market Monitor</strong><small>M&amp;A · ECM · DCM</small></span></a>
  <nav><a href="#deals">Сделки</a><a href="#signals">Свежие события</a><a href="#analytics">Аналитика</a></nav>
  <div class="status" id="global-health"><span class="dot {'live' if live and healthy else 'demo'}"></span><span><strong>{'Данные и источники проверены' if live and healthy else ('Требуется проверка данных' if live else 'Демо-режим')}</strong><small>{generated} МСК</small></span></div>
</div></header>

<main class="page">
  <section class="overview" id="brief">
    <div class="overview-copy"><span class="eyebrow">ЕЖЕДНЕВНЫЙ МОНИТОРИНГ СДЕЛОК</span><h1>Что происходит на рынке сделок</h1>
    <p>{html.escape(flow.get('summary', 'Запусти сборку, чтобы сформировать утреннюю сводку.'))} Последние подтверждённые сделки сохраняются в архиве и не исчезают после обновления.</p>
    <div class="overview-actions"><a class="button primary" href="#deals">Смотреть сделки</a><button class="button ghost" id="copy-brief">Скопировать сводку</button></div></div>
    <div class="overview-side"><div class="freshness"><span class="dot {'live' if live and healthy else 'demo'}"></span><div><strong>{f'Свежие данные · {news_window}' if live and healthy else ('Источники или артефакты требуют проверки' if live else 'Демонстрационные данные')}</strong><small>Автообновление каждые 30 минут в рабочее время</small></div></div>
    <div class="metric-grid">
      {_metric("Свежих событий", len(ranked), news_window.lower())}
      {_metric("Сделок в фокусе", len(key_deals), "последние ключевые")}
      {_metric("M&A", sum(1 for row in key_deals if row.get('deal_type') == 'M&A'), "в текущей выборке")}
      {_metric("База данных", len(precedents), "live + precedents")}
    </div></div>
  </section>

  <section class="market-strip" aria-label="Котировки покрытия">{_quote_cards(quotes, live)}</section>

  {_health_panel(health)}

  <section class="section" id="deals">
    <div class="section-head"><div><span class="eyebrow">КЛЮЧЕВЫЕ СДЕЛКИ</span><h2>Последние сделки рынка</h2><p>Самое важное — стороны, сумма, статус и ссылка на подтверждение. Без технических сообщений биржи.</p></div>
    <div class="export-actions"><a class="button primary" href="precedent_transactions.xlsx" download>Скачать Excel</a><a class="button ghost" href="precedent_transactions.csv" download>CSV</a></div></div>
    <div class="deal-toolbar"><div class="deal-filters"><button class="deal-filter active" data-deal-filter="deal">Актуальные сделки <span>{len(deal_buckets['deal'])}</span></button><button class="deal-filter" data-deal-filter="watchlist">Требует проверки <span>{len(deal_buckets['watchlist'])}</span></button><button class="deal-filter" data-deal-filter="denial">Опровержения <span>{len(deal_buckets['denial'])}</span></button><button class="deal-filter" data-deal-filter="technical_filing">Technical filings <span>{len(deal_buckets['technical_filing'])}</span></button></div>
    <label class="search"><span>⌕</span><input id="deal-search" placeholder="Найти компанию или сделку"></label></div>
    <div class="deal-advanced-filters" aria-label="Фильтры сделок">
      <label>Тип<select id="deal-type-filter"><option value="all">Все типы</option><option value="M&A">M&A</option><option value="DCM">DCM</option><option value="ECM">ECM</option></select></label>
      <label>Период<select id="deal-period-filter"><option value="all">Весь период</option><option value="30">30 дней</option><option value="90">90 дней</option><option value="365">12 месяцев</option></select></label>
      <label>Сектор<select id="deal-sector-filter"><option value="all">Все секторы</option>{sector_options}</select></label>
      <label>Статус<select id="deal-status-filter"><option value="all">Все статусы</option><option value="Closed">Закрыто</option><option value="Priced">Книга закрыта</option><option value="Issued">Размещено</option><option value="Announced">Объявлено</option><option value="Confirmed">Подтверждено</option><option value="In talks">Переговоры</option><option value="Rumor">Слух</option><option value="Denied">Опровергнуто</option></select></label>
      <label>Размер<select id="deal-size-filter"><option value="all">Любой</option><option value="disclosed">Сумма раскрыта</option><option value="undisclosed">Не раскрыта</option><option value="large">≥ 10 млрд в исходной валюте</option></select></label>
      <label>Сортировка<select id="deal-sort"><option value="date-desc">Сначала новые</option><option value="date-asc">Сначала старые</option><option value="amount-desc">По сумме внутри валюты</option><option value="score-desc">По качеству ↓</option></select></label>
      <button class="reset-filters" id="deal-filter-reset" type="button">Сбросить</button>
    </div>
    <div class="deal-stats"><span><b>{len(key_deals)}</b> актуальных сделок за 12 месяцев</span><span><b>{sum(1 for row in key_deals if row.get('quality_status') == 'approved')}</b> прошли quality gate</span><span>Историческая медиана EV/Revenue <b>{_multiple(precedent_stats.get('ev_revenue'))}</b> · n={precedent_stats.get('ev_revenue_count', 0)}</span><span>Историческая медиана EV/EBITDA <b>{_multiple(precedent_stats.get('ev_ebitda')) if precedent_stats.get('ev_ebitda_count', 0) >= 3 else 'N/M'}</b> · n={precedent_stats.get('ev_ebitda_count', 0)}{' · недостаточная выборка' if precedent_stats.get('ev_ebitda_count', 0) < 3 else ''}</span></div>
    <div class="deal-panels">{_deal_bucket_panels(deal_buckets)}</div>
    <details class="data-drawer"><summary>Открыть полную сравнительную таблицу <span>{len(key_deals)} строк · все параметры</span></summary>{_precedent_table(key_deals)}</details>
    <details class="data-drawer"><summary>Precedent multiples <span>{len(multiple_deals)} сделок · только проверяемые расчёты</span></summary>{_precedent_table(multiple_deals[:10])}</details>
  </section>

  <section class="section" id="signals">
    <div class="section-head"><div><span class="eyebrow">СЕГОДНЯ НА РЫНКЕ</span><h2>Свежие события</h2><p>Оперативная лента за {news_window.lower()}. Выберите событие, чтобы увидеть значение для банкира и источник.</p></div>
    <div class="filters"><button class="filter active" data-filter="all">Все</button><button class="filter" data-filter="new">Новые</button>{_filter_buttons(counts)}</div></div>
    <label class="search event-search"><span>⌕</span><input id="event-search" placeholder="Компания, событие или источник"></label>
    <div class="signal-layout"><div class="event-list">{_event_cards(ranked, new_ids)}</div><aside class="detail">{_detail_panel(ranked[0] if ranked else None, ranked[0].event.event_id in new_ids if ranked else False)}</aside></div>
  </section>

  <section class="section analytics" id="analytics">
    <div class="section-head"><div><span class="eyebrow">АНАЛИТИКА</span><h2>Вывод и следующие действия</h2><p>Рабочая зона вынесена отдельно от ленты сделок.</p></div><button class="button ghost" onclick="window.print()">Печать / PDF</button></div>
    <div class="analytics-grid"><div class="readout"><h3>Короткий вывод</h3>{_readout(flow.get('readout', []))}</div>
    <div class="action-panel"><div class="subhead"><h3>Что проверить сегодня</h3><span><b id="open-count">{len(flow.get('tasks', []))}</b> открыто</span></div><div class="task-list">{_task_rows(flow.get('tasks', []))}</div></div></div>
    <details class="data-drawer"><summary>Сценарии и гипотезы <span>внутренняя аналитика, не факты</span></summary><div class="hypothesis-grid">{_hypothesis_cards(flow.get('hypotheses', []))}</div></details>
  </section>

  <section class="utility-grid">
    <details class="data-drawer"><summary>Котировки покрытия <span>MOEX ISS</span></summary>{_quote_table(quotes)}</details>
    <details class="data-drawer" id="sources"><summary>Источники и подтверждения <span>{len(ranked)} свежих записей</span></summary>{_source_table(ranked)}</details>
  </section>
  <footer><strong>Deal Market Monitor</strong><span>Публичные данные · выводы требуют проверки аналитиком · не является инвестиционной рекомендацией</span><small>{html.escape(scope)}</small></footer>
</main>
<script>window.EVENTS={payload_json};window.BRIEF_TEXT={brief_json};{_JS}</script></body></html>"""
    # Keep generated public artifacts clean for review and reproducible diffs.
    document = re.sub(r"^[ \t]+$", "", document, flags=re.MULTILINE)
    output.write_text(document, encoding="utf-8")
    return output


def build_telegram_digest(items: list[ClassifiedEvent], max_items: int = 5) -> str:
    ranked = sorted(items, key=lambda item: item.score, reverse=True)[:max_items]
    lines = ["🏦 <b>Deal &amp; Markets Brief</b>", ""]
    for item in ranked:
        coverage = ", ".join(item.matched_coverage) or "market"
        lines.extend([
            f"<b>{item.score}/10 · {html.escape(item.category)} · {html.escape(coverage)}</b>",
            html.escape(item.event.title),
            f"<i>{html.escape(item.next_action)}</i>",
            "",
        ])
    lines.append("Source-backed monitoring · not investment advice")
    return "\n".join(lines)


def _empty_workflow() -> dict:
    return {"tasks": [], "hypotheses": [], "readout": [], "new_event_ids": [], "summary": "Workflow ещё не сформирован."}


def _brief_text(flow: dict, generated: str) -> str:
    lines = [f"BANKER MORNING BRIEF · {generated}", flow.get("summary", "")]
    for row in flow.get("readout", []):
        lines.append(f"{row.get('label')}: {row.get('text')}")
    lines.append("Actions:")
    for task in flow.get("tasks", [])[:5]:
        lines.append(f"- {task.get('priority')} · {task.get('coverage')} · {task.get('title')}")
    return "\n".join(lines)


def _metric(label: str, value: int, note: str) -> str:
    return f'<article><span>{html.escape(label)}</span><strong>{value}</strong><small>{html.escape(note)}</small></article>'


def _health_panel(health: dict) -> str:
    if not health:
        return ""
    synced = bool(health.get("xlsx_synced"))
    status = "Система готова" if health.get("system_status") == "ok" else "Требуется проверка"
    css = "ok" if status == "Система готова" else "warn"
    updated = html.escape(str(health.get("source_checked_at") or health.get("last_success_at") or "—"))
    build_id = html.escape(str(health.get("build_id") or "—"))
    records = int(health.get("record_count") or 0)
    approved = int(health.get("approved_count") or 0)
    issues = int(health.get("critical_qa_issues") or 0)
    source_status = "OK" if health.get("source_status") == "ok" else "ошибка"
    freshness = "свежие" if health.get("freshness_status") == "ok" else "устарели"
    age = health.get("source_age_minutes")
    age_label = f"{float(age):.0f} мин" if isinstance(age, (int, float)) else "—"
    market_status = health.get("market_data_status", "unavailable")
    market_count = int(health.get("market_quote_count") or 0)
    market_total = int(health.get("market_quote_total") or 0)
    market_label = {
        "ok": f"OK · {market_count}/{market_total}",
        "partial": f"частично · {market_count}/{market_total}",
        "error": "ошибка источника",
        "unavailable": f"недоступен · {market_count}/{market_total}",
    }.get(str(market_status), "не проверен")
    return f'''<section class="health-panel {css}" id="data-health" data-last-success="{updated}" aria-label="Состояние системы">
      <div><span class="health-dot"></span><strong id="data-health-label">{status}</strong><small>Источники проверены: {updated}</small></div>
      <dl><div><dt>Build ID</dt><dd>{build_id}</dd></div><div><dt>Записей</dt><dd>{records}</dd></div><div><dt>Approved</dt><dd>{approved}</dd></div><div><dt>Источники</dt><dd>{source_status}</dd></div><div><dt>Market tape</dt><dd>{market_label}</dd></div><div><dt>Свежесть</dt><dd>{freshness} · {age_label}</dd></div><div><dt>QA issues</dt><dd>{issues}</dd></div><div><dt>Excel</dt><dd>{'синхронизирован' if synced else 'ожидает сборки'}</dd></div></dl>
    </section>'''


def _deal_bucket_panels(buckets: dict[str, list[dict]]) -> str:
    metadata = {
        "deal": ("Актуальные сделки", "Сделки и размещения; уровень проверки явно указан на каждой карточке."),
        "watchlist": ("Требует проверки", "Материальные сообщения, которые ещё нельзя использовать как подтверждённый факт."),
        "denial": ("Опровержения", "Отдельный журнал опровергнутых или спорных сообщений."),
        "technical_filing": ("Technical filings", "Официальные документы биржи: параметры выпуска без смешивания со сделками."),
    }
    panels = []
    for kind, rows in buckets.items():
        title, description = metadata[kind]
        hidden = "" if kind == "deal" else " hidden"
        cards = _deal_tiles(rows, kind) if rows else '<div class="empty">В этом потоке пока нет записей.</div>'
        panels.append(f'<section class="bucket-panel" data-bucket-panel="{kind}"{hidden}><div class="bucket-head"><div><h3>{title}</h3><p>{description}</p></div><span>{len(rows)}</span></div><div class="deal-grid">{cards}</div><div class="filter-empty" hidden>По выбранным фильтрам записей нет. Сбросьте фильтры или выберите другой поток.</div></section>')
    return "".join(panels)


def _deal_tiles(rows: list[dict], bucket: str = "deal") -> str:
    cards = []
    for row in rows:
        deal_type = row.get("deal_type", "Other")
        search = " ".join(str(row.get(key, "")) for key in (
            "headline", "target_or_issuer", "acquirer_or_investor", "seller", "source_name",
            "security_code", "isin",
        )).lower()
        type_class = {"M&A": "ma", "DCM": "dcm", "ECM": "ecm"}.get(deal_type, "other")
        cards.append(f"""<article class="deal-tile" data-deal-bucket="{html.escape(bucket, quote=True)}" data-deal-type="{html.escape(deal_type, quote=True)}" data-deal-sector="{html.escape(str(row.get('sector') or 'Not classified'), quote=True)}" data-deal-status="{html.escape(str(row.get('status') or ''), quote=True)}" data-deal-date="{html.escape(str(row.get('announced_date') or ''), quote=True)}" data-deal-amount="{html.escape(str(row.get('transaction_value') or ''), quote=True)}" data-deal-currency="{html.escape(str(row.get('currency') or 'Not disclosed'), quote=True)}" data-deal-score="{int(row.get('quality_score') or 0)}" data-deal-search="{html.escape(search, quote=True)}">
          <div class="deal-tile-top"><span class="type-badge type-{type_class}">{html.escape(deal_type)}</span><span class="deal-status">{html.escape(_status_label(row.get('status','Rumor')))}</span><span class="quality-badge {html.escape(row.get('quality_status','review'))}">{html.escape(_quality_label(row.get('quality_status','review')))}</span><time>{html.escape(row.get('announced_date','—') or '—')}</time></div>
          <h3>{html.escape(row.get('headline','Сделка без заголовка'))}</h3>
          {_typed_deal_body(row)}
          {_quality_note(row)}
          <details class="card-more"><summary>Все параметры</summary>{_typed_deal_details(row)}</details>
          <div class="deal-tile-foot"><span>Источники · {int(row.get('source_count') or len(row.get('sources', [])) or 1)}</span><div class="source-list">{_deal_source_links(row)}</div></div>
        </article>""")
    return "".join(cards)


def _typed_deal_body(row: dict) -> str:
    deal_type = row.get("deal_type")
    amount = _display_amount(row)
    if deal_type == "M&A":
        entities = _entity_grid([
            ("Покупатель", row.get("acquirer_or_investor")),
            ("Target", row.get("target_or_issuer")),
            ("Продавец", row.get("seller")),
        ])
        facts = [
            ("Стоимость", amount), ("Доля", _display_percent(row.get("stake_percent"))),
            ("Форма оплаты", _display_value(row.get("payment_form"))),
            ("EV/EBITDA", _multiple(row.get("ev_ebitda"))),
        ]
    elif deal_type == "DCM":
        entities = _entity_grid([("Эмитент", row.get("target_or_issuer")), ("Инструмент", row.get("instrument"))])
        coupon = _display_percent(row.get("coupon_rate"))
        if row.get("coupon_type") not in {None, "", "Not disclosed"}:
            coupon = f"{coupon} · {_display_value(row.get('coupon_type'))}" if coupon != "Не раскрыт" else _display_value(row.get("coupon_type"))
        facts = [
            ("Объём", amount), ("Купон", coupon),
            ("Погашение / срок", _display_value(row.get("maturity_date") if row.get("maturity_date") not in {None, "", "Not disclosed"} else row.get("tenor"))),
            ("ISIN / номер", _display_value(row.get("isin") if row.get("isin") not in {None, "", "Not disclosed"} else row.get("security_code"))),
        ]
    else:
        entities = _entity_grid([("Эмитент", row.get("target_or_issuer")), ("Инструмент", row.get("instrument"))])
        facts = [
            ("Объём", amount), ("Цена / акция", _display_number(row.get("price_per_share"), row.get("currency"))),
            ("Дисконт", _display_percent(row.get("discount_percent"))),
            ("Free float", _display_percent(row.get("free_float_percent"))),
        ]
    return entities + '<div class="deal-facts typed-facts">' + "".join(_fact(label, value) for label, value in facts) + "</div>"


def _typed_deal_details(row: dict) -> str:
    deal_type = row.get("deal_type")
    if deal_type == "M&A":
        fields = [
            ("Advisors", row.get("advisors")), ("Rationale", row.get("rationale")),
            ("EV", _deal_amount(row.get("enterprise_value"), row.get("currency", ""))),
            ("Revenue LTM", _deal_amount(row.get("revenue_ltm"), row.get("financials_currency", ""))),
            ("EBITDA LTM", _deal_amount(row.get("ebitda_ltm"), row.get("financials_currency", ""))),
            ("Financials as of", row.get("financials_as_of")),
            ("Financial source", row.get("financials_source_name")),
            ("Multiple note", row.get("multiple_notes")),
        ]
    elif deal_type == "DCM":
        fields = [("Валюта", row.get("currency")), ("Доходность", _display_percent(row.get("yield_rate"))), ("Срок", row.get("tenor")), ("Цена размещения", row.get("issue_price"))]
    else:
        fields = [("Bookrunners", row.get("bookrunners")), ("Rationale", row.get("rationale")), ("Валюта", row.get("currency"))]
    return '<div class="card-detail-grid">' + "".join(_fact(label, _display_value(value)) for label, value in fields) + "</div>"


def _entity_grid(items: list[tuple[str, object]]) -> str:
    return '<div class="entity-grid">' + "".join(f'<div><span>{html.escape(label)}</span><strong>{html.escape(_display_value(value))}</strong></div>' for label, value in items) + "</div>"


def _fact(label: str, value: object) -> str:
    return f'<div><span>{html.escape(label)}</span><strong>{html.escape(_display_value(value))}</strong></div>'


def _display_value(value: object) -> str:
    labels = {"Floating": "Плавающий", "Fixed": "Фиксированный", "Discount": "Дисконтный"}
    return "Не раскрыто" if value in {None, "", "Not disclosed", "NOT DISCLOSED"} else "Не применимо" if value == "Not applicable" else labels.get(str(value), str(value))


def _display_amount(row: dict) -> str:
    value = _deal_amount(row.get("transaction_value"), row.get("currency", ""))
    if value == "Not disclosed":
        return "Не раскрыт"
    result = value.replace("bn", "млрд").replace("mm", "млн").strip()
    if row.get("currency") in {None, "", "Not disclosed", "NOT DISCLOSED"}:
        result += " · валюта не раскрыта"
    return result


def _display_percent(value) -> str:
    return "Не раскрыт" if value in {None, ""} else f"{float(value):.1f}%"


def _display_number(value, currency: str) -> str:
    if value in {None, ""}:
        return "Не раскрыта"
    symbol = {"RUB": "₽", "USD": "$", "EUR": "€", "CNY": "¥"}.get(str(currency).upper(), str(currency or ""))
    return f"{float(value):,.2f} {symbol}".replace(",", " ").strip()


def _status_label(value: str) -> str:
    return {
        "Closed": "Закрыто",
        "Completed": "Закрыто",
        "Issued": "Размещено",
        "Priced": "Книга закрыта",
        "Announced": "Объявлено",
        "In talks": "Переговоры",
        "Potential": "Переговоры",
        "Confirmed": "Подтверждено",
        "Reported": "Сообщается",
        "Rumor": "Слух",
        "Denied": "Опровергнуто",
    }.get(str(value), str(value))


def _quality_label(value: str) -> str:
    return {"approved": "Проверено", "review": "Требует проверки", "rejected": "Отклонено"}.get(str(value), "Требует проверки")


def _deal_source_links(row: dict, limit: int = 3) -> str:
    sources = row.get("sources") or [{
        "name": row.get("source_name", "Источник"),
        "url": row.get("source_url", ""),
        "evidence_label": row.get("evidence_label", "unverified"),
    }]
    links = []
    for source in sources[:limit]:
        url = _safe_url(source.get("url", ""))
        name = html.escape(str(source.get("name") or "Источник"))
        marker = "✓" if source.get("evidence_label") == "confirmed" else "↗"
        links.append(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">{name} {marker}</a>')
    remaining = len(sources) - len(links)
    if remaining > 0:
        links.append(f'<span>+{remaining}</span>')
    return "".join(links)


def _quality_note(row: dict) -> str:
    if row.get("quality_status") == "approved":
        return ""
    labels = {
        "unverified_source": "источник не подтверждён",
        "aggregator_link": "ссылка через агрегатор",
        "missing_both_parties": "стороны не определены",
        "missing_target": "не определён target",
        "missing_acquirer": "не определён покупатель",
        "missing_issuer": "не определён эмитент",
        "price_target_context": "обнаружен контекст target price",
        "suspicious_small_transaction_value": "подозрительная сумма",
        "non_transaction_or_technical_notice": "возможное техническое сообщение",
        "technical_filing": "официальный filing, не сделка",
        "rumor_only": "только рыночный слух",
        "talks_only": "переговоры без закрытия",
        "denied_or_disputed": "сделка опровергнута",
        "invalid_currency": "валюта не нормализована",
    }
    notes = [labels.get(flag, flag) for flag in row.get("quality_flags", [])][:3]
    return f'<div class="quality-note"><b>Проверить:</b> {html.escape(", ".join(notes))}</div>' if notes else ""


def _deal_card(deal: dict | None) -> str:
    if not deal:
        return '<article class="panel deal-card"><span class="kicker">DEAL CARD</span><div class="empty">Новая сделка появится здесь после следующего запуска.</div></article>'
    amount = _deal_amount(deal.get("transaction_value"), deal.get("currency", ""))
    source_url = _safe_url(deal.get("source_url", ""))
    return f"""<article class="panel deal-card">
      <div class="deal-card-top"><span class="kicker">LATEST DEAL CARD</span><b>{html.escape(deal.get('status','Reported'))}</b></div>
      <div class="deal-type">{html.escape(deal.get('deal_type',''))} · SCORE {html.escape(str(deal.get('score','—')))}/10</div>
      <h2>{html.escape(deal.get('headline',''))}</h2>
      <div class="deal-kpis"><div><span>TARGET / ISSUER</span><strong>{html.escape(deal.get('target_or_issuer','Not disclosed'))}</strong></div>
      <div><span>ACQUIRER / INVESTOR</span><strong>{html.escape(deal.get('acquirer_or_investor','Not disclosed'))}</strong></div>
      <div><span>TRANSACTION VALUE</span><strong>{html.escape(amount)}</strong></div>
      <div><span>ANNOUNCED</span><strong>{html.escape(deal.get('announced_date','—') or '—')}</strong></div>
      <div><span>STAKE</span><strong>{html.escape(_percent(deal.get('stake_percent')))}</strong></div>
      <div><span>PAYMENT</span><strong>{html.escape(deal.get('payment_form','Not disclosed'))}</strong></div>
      <div><span>EV / REVENUE</span><strong>{html.escape(_multiple(deal.get('ev_revenue')))}</strong></div>
      <div><span>EV / EBITDA</span><strong>{html.escape(_multiple(deal.get('ev_ebitda')))}</strong></div></div>
      <div class="deal-note"><span>RATIONALE / USE OF PROCEEDS</span><p>{html.escape(deal.get('rationale','Not disclosed'))}</p></div>
      <div class="deal-note"><span>ADVISORS</span><p>{html.escape(deal.get('advisors','Not disclosed'))}</p></div>
      <div class="deal-foot"><span>{html.escape(deal.get('instrument',''))} · {html.escape(deal.get('evidence_label','unverified'))}</span><a href="{html.escape(source_url, quote=True)}" target="_blank" rel="noopener">{_proof_label(source_url)}</a></div>
    </article>"""


def _precedent_table(rows: list[dict]) -> str:
    if not rows:
        return '<div class="empty">База пока пуста.</div>'
    output = []
    for row in rows:
        output.append(f"""<tr><td>{html.escape(row.get('announced_date','—') or '—')}</td><td><b>{html.escape(row.get('deal_type',''))}</b><small>{html.escape(_status_label(row.get('status','Rumor')))}</small></td>
        <td class="deal-headline"><b>{html.escape(row.get('headline','Not disclosed'))}</b></td>
        <td>{html.escape(row.get('target_or_issuer','Not disclosed'))}</td><td>{html.escape(row.get('acquirer_or_investor','Not disclosed'))}</td>
        <td>{html.escape(_deal_amount(row.get('transaction_value'), row.get('currency','')))}</td><td>{html.escape(_percent(row.get('stake_percent')))}</td>
        <td>{html.escape(_multiple(row.get('ev_revenue')))}</td><td>{html.escape(_multiple(row.get('ev_ebitda')))}</td><td>{html.escape(row.get('payment_form','Not disclosed'))}</td>
        <td><span class="quality-badge {html.escape(row.get('quality_status','review'))}">{html.escape(_quality_label(row.get('quality_status','review')))}</span><small>{int(row.get('quality_score') or 0)}/100</small>{_quality_note(row)}</td>
        <td><div class="source-list table-sources">{_deal_source_links(row)}</div></td></tr>""")
    return f'<div class="table-wrap"><table><thead><tr><th>Date</th><th>Type</th><th>Сделка / событие</th><th>Target / Issuer</th><th>Acquirer</th><th>Value</th><th>Stake</th><th>EV/Revenue</th><th>EV/EBITDA</th><th>Payment</th><th>Quality</th><th>Sources</th></tr></thead><tbody>{"".join(output)}</tbody></table></div>'


def _deal_amount(value, currency: str) -> str:
    if value in {None, ""}:
        return "Not disclosed"
    number = float(value)
    normalized = str(currency or "").upper()
    symbol = {"RUB": "₽", "USD": "$", "EUR": "€", "CNY": "¥", "GBP": "£"}.get(normalized, "")
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:,.1f} bn {symbol}".replace(",", " ")
    if number >= 1_000_000:
        return f"{number / 1_000_000:,.1f} mm {symbol}".replace(",", " ")
    return f"{number:,.0f} {symbol}".replace(",", " ")


def _multiple(value) -> str:
    return "N/M" if value in {None, ""} else f"{float(value):.1f}x"


def _percent(value) -> str:
    return "Not disclosed" if value in {None, ""} else f"{float(value):.1f}%"


def _quote_cards(quotes: list[dict], live: bool) -> str:
    if not quotes:
        state = "Ожидает live-запуска" if not live else "Данные временно недоступны"
        return f'<div class="tape-empty">MOEX MARKET TAPE · {state}</div>'
    cards = []
    for quote in quotes:
        usable = quote_is_usable(quote)
        if not usable:
            cards.append(f'''<a class="quote-card quote-card-unavailable" href="{html.escape(_safe_url(quote.get('source_url','')), quote=True)}" target="_blank" rel="noopener">
        <div><strong>{html.escape(quote.get('ticker',''))}</strong><small>{html.escape(quote.get('company',''))}</small></div>
        <span class="quote-unavailable">Котировка недоступна</span></a>''')
            continue
        price = _number(quote.get("price"), 2)
        change = quote.get("change_percent")
        change_text = "изменение недоступно" if change is None else f"{change:+.2f}%"
        direction = "up" if (change or 0) > 0 else "down" if (change or 0) < 0 else "flat"
        cards.append(f"""<a class="quote-card" href="{html.escape(_safe_url(quote.get('source_url','')), quote=True)}" target="_blank" rel="noopener">
        <div><strong>{html.escape(quote.get('ticker',''))}</strong><small>{html.escape(quote.get('company',''))}</small></div>
        <span class="quote-price">{price} ₽</span><span class="quote-change {direction}">{change_text}</span></a>""")
    return "".join(cards)


def _task_rows(tasks: list[dict]) -> str:
    if not tasks:
        return '<div class="empty">Нет действий выше заданного порога.</div>'
    rows = []
    for task in tasks:
        hypotheses = " · ".join(task.get("hypothesis_ids", [])) or task.get("category", "")
        state = task.get("state", "open")
        rows.append(f"""<label class="task" data-task-id="{html.escape(task.get('id',''), quote=True)}">
        <input class="task-check" type="checkbox"><span class="checkmark">✓</span>
        <span class="priority {task.get('priority','P2').lower()}">{html.escape(task.get('priority','P2'))}</span>
        <span class="task-body"><strong>{html.escape(task.get('title',''))}</strong>
        <small>{html.escape(task.get('coverage',''))} · {html.escape(hypotheses)} · DELIVERABLE: {html.escape(task.get('deliverable',''))}</small></span>
        <span class="state {html.escape(state)}">{html.escape(state.upper())}</span>
        <a href="{html.escape(_safe_url(task.get('source_url','')), quote=True)}" target="_blank" rel="noopener" title="Источник">↗</a></label>""")
    return "".join(rows)


def _readout(rows: list[dict]) -> str:
    return "".join(f'<div class="readout-row"><span>{html.escape(row.get("label",""))}</span><p>{html.escape(row.get("text",""))}</p></div>' for row in rows)


def _hypothesis_cards(hypotheses: list[dict]) -> str:
    if not hypotheses:
        return '<div class="empty">Добавь deal_hypotheses в config.json.</div>'
    cards = []
    for hypothesis in hypotheses:
        status = hypothesis.get("status", "active")
        cards.append(f"""<article class="hypothesis-card {html.escape(status)}">
        <div class="hypothesis-top"><span>{html.escape(hypothesis.get('id',''))} · {html.escape(hypothesis.get('stage',''))}</span><b>{'REVIEW' if status == 'attention' else 'ACTIVE'}</b></div>
        <h3>{html.escape(hypothesis.get('title',''))}</h3><p>{html.escape(hypothesis.get('thesis',''))}</p>
        <dl><div><dt>Decision question</dt><dd>{html.escape(hypothesis.get('decision_question',''))}</dd></div>
        <div><dt>Next deliverable</dt><dd>{html.escape(hypothesis.get('deliverable',''))}</dd></div></dl>
        <div class="hypothesis-foot"><span>{hypothesis.get('signal_count',0)} signals · <b>{hypothesis.get('new_signal_count',0)} new</b></span><span>{html.escape(' · '.join(hypothesis.get('tickers',[])))}</span></div></article>""")
    return "".join(cards)


def _filter_buttons(counts: Counter) -> str:
    return "".join(f'<button class="filter" data-filter="{html.escape(category, quote=True)}">{html.escape(category)} <small>{count}</small></button>' for category, count in counts.most_common())


def _event_cards(items: list[ClassifiedEvent], new_ids: set[str]) -> str:
    if not items:
        return '<div class="empty">Нет событий выше заданного порога.</div>'
    cards = []
    for index, item in enumerate(items):
        event = item.event
        coverage = ", ".join(item.matched_coverage) or "MARKET"
        is_new = event.event_id in new_ids
        summary = _distinct_summary(event.title, event.summary)
        summary_html = f'<p>{html.escape(summary[:190])}</p>' if summary else ""
        cards.append(f"""<article class="event-card{' selected' if index == 0 else ''}" data-index="{index}" data-category="{html.escape(item.category, quote=True)}" data-new="{'true' if is_new else 'false'}" data-search="{html.escape((event.title+' '+event.source+' '+coverage).lower(), quote=True)}">
          <div class="score {item.severity}">{item.score}</div><div class="event-main">
          <div class="event-meta"><span>{html.escape(item.category)}</span><span>{html.escape(coverage)}</span><span>{html.escape(_short_date(event.published_at))}</span>{'<b>NEW</b>' if is_new else ''}</div>
          <h3>{html.escape(event.title)}</h3>{summary_html}
          <div class="event-source">{html.escape(event.source)} · {html.escape(item.evidence_label)}</div></div>
          <a class="source-link" href="{html.escape(_safe_url(event.url), quote=True)}" target="_blank" rel="noopener" title="Открыть источник">↗</a></article>""")
    return "".join(cards)


def _distinct_summary(title: str, summary: str) -> str:
    """Hide RSS descriptions that merely repeat the headline."""
    clean_title = _normalize_text(title)
    clean_summary = _normalize_text(summary)
    if not clean_summary or clean_summary in clean_title or clean_title in clean_summary:
        return ""
    title_tokens = set(clean_title.split())
    summary_tokens = set(clean_summary.split())
    if title_tokens and summary_tokens:
        overlap = len(title_tokens & summary_tokens) / min(len(title_tokens), len(summary_tokens))
        if overlap >= 0.75:
            return ""
    return summary.strip()


def _normalize_text(value: str) -> str:
    return " ".join(re.findall(r"[a-zа-яё0-9]+", value.lower()))


def _detail_panel(item: ClassifiedEvent | None, is_new: bool) -> str:
    if item is None:
        return '<div class="empty">Выберите событие.</div>'
    payload = _event_payload(item, is_new)
    return f"""<span class="kicker">BANKER BRIEF</span><div class="detail-score"><span id="detail-score">{item.score}/10</span><small id="detail-state">{'NEW SIGNAL' if is_new else item.severity.upper()}</small></div>
    <h2 id="detail-title">{html.escape(payload['title'])}</h2>
    <div class="detail-section"><span>ПОЧЕМУ ЭТО ВАЖНО</span><p id="detail-angle">{html.escape(payload['banker_angle'])}</p></div>
    <div class="detail-section"><span>СЛЕДУЮЩЕЕ ДЕЙСТВИЕ</span><p id="detail-action">{html.escape(payload['next_action'])}</p></div>
    <div class="detail-grid"><div><span>TYPE</span><strong id="detail-category">{html.escape(payload['category'])}</strong></div>
    <div><span>COVERAGE</span><strong id="detail-coverage">{html.escape(payload['coverage'])}</strong></div>
    <div><span>EVIDENCE</span><strong id="detail-evidence">{html.escape(payload['evidence'])}</strong></div>
    <div><span>SOURCE</span><strong id="detail-source">{html.escape(payload['source'])}</strong></div></div>
    <a id="detail-link" class="primary-link" href="{html.escape(payload['url'], quote=True)}" target="_blank" rel="noopener">{html.escape(payload['proof_label'])}</a>"""


def _quote_table(quotes: list[dict]) -> str:
    if not quotes:
        return '<div class="empty">Запусти <code>python3 run.py --live</code>, чтобы получить реальные котировки.</div>'
    rows = []
    for quote in quotes:
        usable = quote_is_usable(quote)
        change = quote.get("change_percent")
        price_text = f"{_number(quote.get('price'),2)} ₽" if usable else "Котировка недоступна"
        change_text = "изменение недоступно" if usable and change is None else "—" if not usable else f"{change:+.2f}%"
        rows.append(f"""<tr><td><strong>{html.escape(quote.get('ticker',''))}</strong><small>{html.escape(quote.get('company',''))}</small></td>
        <td>{price_text}</td><td class="{'positive' if (change or 0)>0 else 'negative' if (change or 0)<0 else ''}">{change_text}</td>
        <td>{_compact(quote.get('turnover'))}</td><td>{html.escape(str(quote.get('updated','—')))}</td><td><a href="{html.escape(_safe_url(quote.get('source_url','')), quote=True)}" target="_blank" rel="noopener">MOEX ISS ↗</a></td></tr>""")
    return f'<div class="table-wrap"><table><thead><tr><th>Security</th><th>Last</th><th>Change</th><th>Turnover</th><th>Updated</th><th>Source</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _source_table(items: list[ClassifiedEvent]) -> str:
    rows = []
    for index, item in enumerate(items, 1):
        event = item.event
        rows.append(f"""<tr><td>SRC-{index:03d}</td><td>{html.escape(event.source)}</td><td>{html.escape(_short_date(event.published_at))}</td>
        <td>{html.escape(item.evidence_label)}</td><td>{html.escape(item.category)}</td><td>{html.escape(event.title[:90])}</td><td><a href="{html.escape(_safe_url(event.url), quote=True)}" target="_blank" rel="noopener">{_proof_label(event.url)}</a></td></tr>""")
    return f'<div class="table-wrap"><table><thead><tr><th>ID</th><th>Источник</th><th>Дата</th><th>Статус</th><th>Тип</th><th>Claim</th><th>Ссылка</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _event_payload(item: ClassifiedEvent, is_new: bool) -> dict:
    return {
        "title": item.event.title, "category": item.category,
        "coverage": ", ".join(item.matched_coverage) or "MARKET",
        "evidence": item.evidence_label, "source": item.event.source,
        "url": _safe_url(item.event.url), "banker_angle": item.banker_angle,
        "next_action": item.next_action, "score": item.score,
        "severity": item.severity, "is_new": is_new,
        "proof_label": _proof_label(item.event.url),
    }


def _number(value, digits: int) -> str:
    return "—" if value is None else f"{float(value):,.{digits}f}".replace(",", " ")


def _safe_url(value: str) -> str:
    try:
        parsed = urlparse(str(value).strip())
        return str(value).strip() if parsed.scheme in {"http", "https"} and parsed.netloc else "#"
    except (TypeError, ValueError):
        return "#"


def _proof_label(value: str) -> str:
    return "Открыть через Google News ↗" if "news.google.com" in str(value) else "Подтверждение ↗"


def _compact(value) -> str:
    if value is None:
        return "—"
    value = float(value)
    if value >= 1_000_000_000:
        return f"{value/1_000_000_000:.2f} млрд ₽"
    if value >= 1_000_000:
        return f"{value/1_000_000:.1f} млн ₽"
    return f"{value:,.0f} ₽".replace(",", " ")


def _short_date(value: str) -> str:
    if not value:
        return "—"
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}T", value):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y")
        return parsedate_to_datetime(value).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return value[:18]


_JS = r"""
const AUTO_REFRESH_MS=5*60*1000;
const cards=[...document.querySelectorAll('.event-card')],filters=[...document.querySelectorAll('.filter')],search=document.getElementById('event-search');let active='all';
function applyFilters(){const q=search.value.trim().toLowerCase();cards.forEach(c=>{const categoryOk=active==='all'||(active==='new'?c.dataset.new==='true':c.dataset.category===active);const searchOk=!q||c.dataset.search.includes(q);c.hidden=!(categoryOk&&searchOk);});}
filters.forEach(button=>button.addEventListener('click',()=>{filters.forEach(x=>x.classList.remove('active'));button.classList.add('active');active=button.dataset.filter;applyFilters();}));search.addEventListener('input',applyFilters);
const dealCards=[...document.querySelectorAll('.deal-tile')],dealPanels=[...document.querySelectorAll('.bucket-panel')],dealFilters=[...document.querySelectorAll('.deal-filter')],dealSearch=document.getElementById('deal-search'),dealType=document.getElementById('deal-type-filter'),dealPeriod=document.getElementById('deal-period-filter'),dealSector=document.getElementById('deal-sector-filter'),dealStatus=document.getElementById('deal-status-filter'),dealSize=document.getElementById('deal-size-filter'),dealSort=document.getElementById('deal-sort');let activeDeal='deal';
function applyDealFilters(){const q=dealSearch.value.trim().toLowerCase(),days=Number(dealPeriod.value)||0,cutoff=days?Date.now()-days*86400000:0;dealPanels.forEach(panel=>panel.hidden=panel.dataset.bucketPanel!==activeDeal);dealCards.forEach(card=>{const amount=Number(card.dataset.dealAmount)||0,date=Date.parse(card.dataset.dealDate)||0;const ok=card.dataset.dealBucket===activeDeal&&(!q||card.dataset.dealSearch.includes(q))&&(dealType.value==='all'||card.dataset.dealType===dealType.value)&&(dealSector.value==='all'||card.dataset.dealSector===dealSector.value)&&(dealStatus.value==='all'||card.dataset.dealStatus===dealStatus.value)&&(!cutoff||date>=cutoff)&&(dealSize.value==='all'||(dealSize.value==='disclosed'&&amount>0)||(dealSize.value==='undisclosed'&&!amount)||(dealSize.value==='large'&&amount>=1e10));card.hidden=!ok;});dealPanels.forEach(panel=>{const grid=panel.querySelector('.deal-grid');if(!grid)return;[...grid.querySelectorAll('.deal-tile')].sort((a,b)=>{if(dealSort.value==='date-asc')return a.dataset.dealDate.localeCompare(b.dataset.dealDate);if(dealSort.value==='amount-desc'){const currencyOrder={RUB:0,USD:1,EUR:2,CNY:3,GBP:4,CHF:5};const ac=currencyOrder[a.dataset.dealCurrency]??99,bc=currencyOrder[b.dataset.dealCurrency]??99;return ac!==bc?ac-bc:(Number(b.dataset.dealAmount)||0)-(Number(a.dataset.dealAmount)||0);}if(dealSort.value==='score-desc')return (Number(b.dataset.dealScore)||0)-(Number(a.dataset.dealScore)||0);return b.dataset.dealDate.localeCompare(a.dataset.dealDate);}).forEach(card=>grid.appendChild(card));const visible=[...grid.querySelectorAll('.deal-tile')].some(card=>!card.hidden);const empty=panel.querySelector('.filter-empty');if(empty)empty.hidden=visible;});}
dealFilters.forEach(button=>button.addEventListener('click',()=>{dealFilters.forEach(x=>x.classList.remove('active'));button.classList.add('active');activeDeal=button.dataset.dealFilter;applyDealFilters();}));dealSearch.addEventListener('input',applyDealFilters);applyDealFilters();
[dealType,dealPeriod,dealSector,dealStatus,dealSize,dealSort].forEach(control=>control.addEventListener('change',applyDealFilters));document.getElementById('deal-filter-reset').addEventListener('click',()=>{dealSearch.value='';[dealType,dealPeriod,dealSector,dealStatus,dealSize].forEach(control=>control.value='all');dealSort.value='date-desc';applyDealFilters();});
cards.forEach(card=>card.addEventListener('click',event=>{if(event.target.closest('a'))return;cards.forEach(x=>x.classList.remove('selected'));card.classList.add('selected');const d=window.EVENTS[Number(card.dataset.index)];
document.getElementById('detail-title').textContent=d.title;document.getElementById('detail-angle').textContent=d.banker_angle;document.getElementById('detail-action').textContent=d.next_action;document.getElementById('detail-category').textContent=d.category;document.getElementById('detail-coverage').textContent=d.coverage;document.getElementById('detail-evidence').textContent=d.evidence;document.getElementById('detail-source').textContent=d.source;document.getElementById('detail-score').textContent=d.score+'/10';document.getElementById('detail-state').textContent=d.is_new?'NEW SIGNAL':d.severity.toUpperCase();document.getElementById('detail-link').href=d.url;document.getElementById('detail-link').textContent=d.proof_label;}));
const completed=JSON.parse(localStorage.getItem('dealDeskCompleted')||'{}');
function refreshTasks(){document.querySelectorAll('.task').forEach(row=>{const check=row.querySelector('.task-check');check.checked=!!completed[row.dataset.taskId];row.classList.toggle('done',check.checked);});document.getElementById('open-count').textContent=document.querySelectorAll('.task:not(.done)').length;localStorage.setItem('dealDeskCompleted',JSON.stringify(completed));}
document.querySelectorAll('.task-check').forEach(check=>check.addEventListener('change',()=>{const row=check.closest('.task');completed[row.dataset.taskId]=check.checked;if(!check.checked)delete completed[row.dataset.taskId];refreshTasks();}));refreshTasks();
document.getElementById('copy-brief').addEventListener('click',async event=>{await navigator.clipboard.writeText(window.BRIEF_TEXT);const old=event.currentTarget.textContent;event.currentTarget.textContent='Скопировано ✓';setTimeout(()=>event.currentTarget.textContent=old,1300);});
const healthPanel=document.getElementById('data-health');if(healthPanel){const last=Date.parse(healthPanel.dataset.lastSuccess),now=new Date(),hour=Number(new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Moscow',hour:'2-digit',hour12:false}).format(now)),weekday=new Intl.DateTimeFormat('en-US',{timeZone:'Europe/Moscow',weekday:'short'}).format(now),working=!['Sat','Sun'].includes(weekday)&&hour>=8&&hour<20,maxAge=working?90*60000:72*3600000;if(!last||now-last>maxAge){healthPanel.classList.remove('ok');healthPanel.classList.add('warn');document.getElementById('data-health-label').textContent='Данные устарели';const global=document.getElementById('global-health');if(global){global.querySelector('strong').textContent='Данные устарели';global.querySelector('.dot').className='dot demo';}}}
setInterval(()=>{if(document.visibilityState==='visible')window.location.reload();},AUTO_REFRESH_MS);
"""


_CSS = r"""
:root{--bg:#f4f6f9;--surface:#fff;--surface-soft:#f8f9fc;--ink:#172238;--muted:#6d7788;--line:#dfe4ec;--blue:#3559c7;--blue-dark:#203b91;--blue-soft:#edf1ff;--mint:#0d8b72;--mint-soft:#e8f7f3;--amber:#b57418;--amber-soft:#fff6e7;--red:#c34d58;--shadow:0 12px 34px rgba(31,45,72,.07)}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:84px}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Avenir Next",Avenir,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}button,input{font:inherit}a{color:inherit}.site-header{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.94);border-bottom:1px solid var(--line);backdrop-filter:blur(14px)}.nav-wrap{max-width:1320px;margin:auto;height:70px;padding:0 28px;display:flex;align-items:center;gap:42px}.brand{display:flex;align-items:center;gap:11px;text-decoration:none;min-width:240px}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:11px;background:var(--ink);color:#fff;font-weight:800;font-size:12px;letter-spacing:.04em}.brand strong,.brand small,.status strong,.status small{display:block}.brand strong{font-size:14px;letter-spacing:-.01em}.brand small{font-size:10px;color:var(--muted);letter-spacing:.08em;margin-top:1px}.site-header nav{display:flex;gap:28px}.site-header nav a{text-decoration:none;color:var(--muted);font-weight:600;font-size:13px}.site-header nav a:hover{color:var(--blue)}.status{margin-left:auto;display:flex;align-items:center;gap:9px}.status strong{font-size:11px}.status small{font-size:10px;color:var(--muted)}.dot{width:8px;height:8px;border-radius:50%;flex:none}.dot.live{background:var(--mint);box-shadow:0 0 0 4px var(--mint-soft)}.dot.demo{background:var(--amber);box-shadow:0 0 0 4px var(--amber-soft)}
.page{max-width:1320px;margin:auto;padding:34px 28px 54px}.overview{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(420px,.8fr);gap:46px;padding:45px 48px;border-radius:22px;background:linear-gradient(135deg,#14213a 0%,#1d3156 100%);color:#fff;box-shadow:var(--shadow)}.eyebrow{display:block;color:#7891e8;font-size:10px;font-weight:800;letter-spacing:.13em;margin-bottom:11px}.overview .eyebrow{color:#9eb4ff}.overview h1{font-size:42px;line-height:1.08;letter-spacing:-.04em;margin:0 0 17px;max-width:650px}.overview-copy>p{font-size:15px;color:#d4dced;max-width:720px;margin:0;line-height:1.65}.overview-actions{display:flex;gap:10px;margin-top:26px}.button{display:inline-flex;align-items:center;justify-content:center;min-height:41px;padding:9px 16px;border-radius:10px;border:1px solid var(--line);background:#fff;color:var(--ink);text-decoration:none;font-weight:700;font-size:12px;cursor:pointer}.button.primary{background:var(--blue);border-color:var(--blue);color:#fff}.overview .button.primary{background:#fff;border-color:#fff;color:var(--blue-dark)}.overview .button.ghost{background:transparent;border-color:#536583;color:#fff}.button:hover{transform:translateY(-1px)}.overview-side{display:grid;gap:16px}.freshness{display:flex;align-items:center;gap:12px;padding:14px 16px;border:1px solid rgba(255,255,255,.16);border-radius:13px;background:rgba(255,255,255,.05)}.freshness strong,.freshness small{display:block}.freshness strong{font-size:12px}.freshness small{font-size:10px;color:#aebbd1;margin-top:2px}.metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.metric-grid article{padding:15px;border-radius:13px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.1)}.metric-grid span,.metric-grid small{display:block;color:#aebbd1;font-size:10px}.metric-grid strong{display:block;font-size:27px;line-height:1;margin:8px 0 6px;letter-spacing:-.04em;font-variant-numeric:tabular-nums}
.market-strip{display:grid;grid-template-columns:repeat(3,1fr);margin:18px 0 26px;background:var(--surface);border:1px solid var(--line);border-radius:14px;overflow:hidden}.quote-card{display:grid;grid-template-columns:1fr auto auto;gap:14px;align-items:center;padding:13px 17px;border-right:1px solid var(--line);text-decoration:none}.quote-card:last-child{border:0}.quote-card strong,.quote-card small{display:block}.quote-card small{color:var(--muted);font-size:10px}.quote-price,.quote-change{font-weight:750;font-variant-numeric:tabular-nums}.quote-change{font-size:12px}.quote-card-unavailable{grid-template-columns:1fr auto}.quote-unavailable{color:var(--muted);font-size:11px;font-weight:750}.up,.positive{color:var(--mint)}.down,.negative{color:var(--red)}.flat{color:var(--muted)}.tape-empty{padding:15px;color:var(--muted);grid-column:1/-1}
.health-panel{display:flex;align-items:center;justify-content:space-between;gap:20px;margin:0 0 24px;padding:14px 18px;border:1px solid var(--line);border-radius:13px;background:var(--surface)}.health-panel>div{display:grid;grid-template-columns:10px auto;column-gap:9px;align-items:center}.health-panel>div small{grid-column:2;color:var(--muted);font-size:9px}.health-dot{width:9px;height:9px;border-radius:50%}.health-panel.ok .health-dot{background:var(--mint);box-shadow:0 0 0 4px var(--mint-soft)}.health-panel.warn .health-dot{background:var(--amber);box-shadow:0 0 0 4px var(--amber-soft)}.health-panel dl{display:flex;gap:20px;margin:0}.health-panel dl div{min-width:70px}.health-panel dt{color:var(--muted);font-size:8px;text-transform:uppercase}.health-panel dd{margin:2px 0 0;font-size:10px;font-weight:750;font-variant-numeric:tabular-nums}.filter-empty{padding:28px;border:1px dashed var(--line);border-radius:12px;color:var(--muted);text-align:center}.filter-empty[hidden]{display:none}
.section{margin-top:24px;padding:30px;background:var(--surface);border:1px solid var(--line);border-radius:18px;box-shadow:0 5px 18px rgba(31,45,72,.035)}.section-head{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;margin-bottom:22px}.section-head h2{font-size:27px;line-height:1.15;letter-spacing:-.025em;margin:0}.section-head p{color:var(--muted);margin:8px 0 0;max-width:700px}.export-actions,.filters{display:flex;gap:8px;flex-wrap:wrap}.deal-filters{display:grid;grid-template-columns:repeat(4,max-content);gap:8px}.deal-toolbar{display:flex;justify-content:space-between;align-items:start;gap:14px;margin-bottom:14px}.deal-filter,.filter{border:1px solid var(--line);background:var(--surface);color:var(--muted);border-radius:9px;padding:8px 12px;font-size:12px;font-weight:700;cursor:pointer}.deal-filter:hover,.deal-filter.active,.filter:hover,.filter.active{background:var(--blue-soft);border-color:#aebcf2;color:var(--blue-dark)}.deal-filter span{margin-left:4px;color:var(--blue)}.search{display:flex;align-items:center;gap:8px;border:1px solid var(--line);background:var(--surface-soft);border-radius:10px;padding:8px 12px;min-width:290px}.search span{color:var(--blue);font-size:17px}.search input{width:100%;border:0;outline:0;background:transparent;color:var(--ink);font-size:12px}.search input::placeholder{color:#98a0ae}.deal-advanced-filters{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr)) auto;gap:8px;padding:12px;margin-bottom:4px;border:1px solid var(--line);border-radius:12px;background:var(--surface-soft)}.deal-advanced-filters label{display:grid;gap:4px;color:var(--muted);font-size:9px;font-weight:750}.deal-advanced-filters select{min-width:0;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink);padding:8px;font-size:10px}.reset-filters{align-self:end;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--blue);padding:8px 10px;font-size:10px;font-weight:750;cursor:pointer}.deal-stats{display:flex;gap:24px;flex-wrap:wrap;padding:12px 0 18px;color:var(--muted);font-size:11px}.deal-stats b{color:var(--ink)}
.deal-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.deal-tile{display:flex;flex-direction:column;min-height:300px;border:1px solid var(--line);border-radius:15px;padding:20px;background:var(--surface);transition:.18s ease}.deal-tile:hover{border-color:#b9c4d6;box-shadow:var(--shadow);transform:translateY(-2px)}.deal-tile[hidden]{display:none}.deal-tile-top{display:flex;align-items:center;gap:7px;flex-wrap:wrap;color:var(--muted);font-size:10px}.deal-tile-top time{margin-left:auto;font-variant-numeric:tabular-nums}.type-badge,.deal-status,.quality-badge{padding:4px 8px;border-radius:999px;font-size:9px;font-weight:800;letter-spacing:.04em}.type-badge{background:var(--blue-soft);color:var(--blue-dark)}.type-ma{background:var(--mint-soft);color:var(--mint)}.type-ecm{background:#f2edff;color:#6e45bd}.type-dcm{background:var(--amber-soft);color:var(--amber)}.deal-status{background:var(--surface-soft);border:1px solid var(--line);color:var(--muted)}.quality-badge.approved{background:var(--mint-soft);color:var(--mint)}.quality-badge.review{background:var(--amber-soft);color:var(--amber)}.quality-badge.rejected{background:#fff0f1;color:var(--red)}.deal-tile h3{font-size:17px;line-height:1.35;letter-spacing:-.012em;margin:15px 0 18px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.parties{display:grid;grid-template-columns:1fr 22px 1fr;align-items:center;gap:8px;padding:13px;border-radius:11px;background:var(--surface-soft)}.parties div span,.deal-facts span{display:block;color:var(--muted);font-size:9px;margin-bottom:4px}.parties strong{display:block;font-size:12px}.party-arrow{text-align:center;color:#9aa5b5}.deal-facts{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:15px 0}.deal-facts div+div{border-left:1px solid var(--line);padding-left:12px}.deal-facts strong{font-size:12px;font-variant-numeric:tabular-nums}.quality-note{margin:-3px 0 12px;padding:8px 10px;border-radius:8px;background:var(--amber-soft);color:#805418;font-size:9px}.quality-note b{font-weight:800}.deal-tile-foot{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-top:auto;padding-top:13px;border-top:1px solid var(--line);color:var(--muted);font-size:10px}.source-list{display:flex;justify-content:flex-end;gap:5px;flex-wrap:wrap}.source-list a,.source-list span{padding:4px 7px;border-radius:6px;background:var(--blue-soft);color:var(--blue);text-decoration:none;font-weight:750}.source-list a:hover{text-decoration:underline}.table-sources{min-width:170px;justify-content:flex-start}
.bucket-panel[hidden]{display:none}.bucket-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:13px;padding:12px 14px;border-radius:11px;background:var(--surface-soft);border:1px solid var(--line)}.bucket-head h3{margin:0;font-size:15px}.bucket-head p{margin:3px 0 0;color:var(--muted);font-size:10px}.bucket-head>span{display:grid;place-items:center;min-width:31px;height:31px;border-radius:9px;background:var(--blue-soft);color:var(--blue);font-weight:800}.entity-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:13px;border-radius:11px;background:var(--surface-soft)}.entity-grid div+div{border-left:1px solid var(--line);padding-left:12px}.entity-grid span,.card-detail-grid span{display:block;color:var(--muted);font-size:9px;margin-bottom:4px}.entity-grid strong,.card-detail-grid strong{display:block;font-size:12px}.typed-facts{grid-template-columns:repeat(4,minmax(0,1fr))}.card-more{margin:0 0 12px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.card-more summary{padding:9px 0;cursor:pointer;color:var(--blue);font-size:10px;font-weight:750;list-style:none}.card-more summary::-webkit-details-marker{display:none}.card-more summary:after{content:" +"}.card-more[open] summary:after{content:" −"}.card-detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;padding:0 0 11px}.card-detail-grid div{padding:8px;border-radius:8px;background:var(--surface-soft)}
.data-drawer{margin-top:18px;border:1px solid var(--line);border-radius:12px;background:var(--surface);overflow:hidden}.data-drawer summary{display:flex;justify-content:space-between;gap:16px;padding:15px 17px;cursor:pointer;font-weight:700;list-style:none}.data-drawer summary::-webkit-details-marker{display:none}.data-drawer summary:after{content:"+";margin-left:auto;color:var(--blue);font-size:18px;line-height:1}.data-drawer[open] summary:after{content:"−"}.data-drawer summary span{color:var(--muted);font-size:10px;font-weight:500;margin-right:8px}.table-wrap{overflow:auto;border-top:1px solid var(--line)}table{border-collapse:collapse;width:100%;min-width:820px}th{text-align:left;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.05em;padding:11px;border-bottom:1px solid var(--line);background:var(--surface-soft)}td{padding:12px 11px;border-bottom:1px solid var(--line);font-size:11px;vertical-align:top}td small{display:block;color:var(--muted);font-size:9px;margin-top:3px}td a{color:var(--blue);text-decoration:none}.proof-link{display:inline-block;padding:6px 8px;border-radius:7px;background:var(--blue-soft)}.proof-link b,.proof-link small{display:block}
.event-search{margin-bottom:12px;width:100%}.signal-layout{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(310px,.55fr);gap:16px;align-items:start}.event-list{display:grid;border:1px solid var(--line);border-radius:12px;overflow:hidden;max-height:630px;overflow-y:auto}.event-card{position:relative;display:grid;grid-template-columns:40px minmax(0,1fr) 24px;gap:13px;padding:16px;border-bottom:1px solid var(--line);cursor:pointer;background:var(--surface)}.event-card:last-child{border:0}.event-card:hover,.event-card.selected{background:var(--blue-soft)}.event-card.selected:before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--blue)}.event-card[hidden]{display:none}.score{display:grid;place-items:center;width:35px;height:35px;border-radius:10px;background:var(--surface-soft);font-weight:800}.score.critical{color:var(--red)}.score.high{color:var(--amber)}.score.medium{color:var(--mint)}.event-meta{display:flex;flex-wrap:wrap;gap:8px;color:var(--muted);font-size:9px;text-transform:uppercase}.event-meta span:first-child{color:var(--blue);font-weight:800}.event-meta b{padding:1px 5px;border-radius:4px;background:var(--mint);color:#fff}.event-card h3{font-size:14px;line-height:1.35;margin:6px 0 3px}.event-card p{color:var(--muted);font-size:11px;margin:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.event-source{color:var(--muted);font-size:10px;margin-top:7px}.source-link{color:var(--blue);text-decoration:none;font-size:17px}.detail{position:sticky;top:88px;padding:21px;border:1px solid var(--line);border-radius:13px;background:var(--surface-soft)}.kicker,.detail-section span,.detail-grid span{color:var(--blue);font-size:9px;font-weight:800;letter-spacing:.08em}.detail-score{display:flex;align-items:end;gap:8px;margin:15px 0 12px}.detail-score span{font-size:27px;font-weight:800;color:var(--blue)}.detail-score small{color:var(--muted);font-size:9px}.detail h2{font-size:18px;line-height:1.3;margin:0 0 18px}.detail-section{border-top:1px solid var(--line);padding:13px 0}.detail-section p{margin:5px 0 0;font-size:12px}.detail-grid{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid var(--line);margin-bottom:15px}.detail-grid div{padding:10px 0;border-bottom:1px solid var(--line)}.detail-grid strong{display:block;margin-top:3px;font-size:11px}.primary-link{display:block;padding:10px;border-radius:9px;background:var(--blue);color:#fff;text-align:center;text-decoration:none;font-weight:750;font-size:12px}
.analytics-grid{display:grid;grid-template-columns:minmax(280px,.7fr) minmax(0,1.3fr);gap:16px}.readout,.action-panel{border:1px solid var(--line);border-radius:13px;padding:20px}.readout h3,.subhead h3{margin:0;font-size:16px}.readout-row{padding:13px 0;border-bottom:1px solid var(--line)}.readout-row:last-child{border:0}.readout-row span{font-size:9px;color:var(--blue);font-weight:800;text-transform:uppercase}.readout-row p{margin:4px 0 0;color:var(--muted);font-size:12px}.subhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px}.subhead span{font-size:10px;color:var(--muted)}.task-list{display:grid}.task{position:relative;display:grid;grid-template-columns:22px 32px minmax(0,1fr) 48px 18px;gap:9px;align-items:center;padding:12px 4px;border-bottom:1px solid var(--line);cursor:pointer}.task:last-child{border:0}.task:hover{background:var(--surface-soft)}.task input{position:absolute;opacity:0}.checkmark{display:grid;place-items:center;width:18px;height:18px;border:1px solid #b9c2cf;border-radius:5px;color:transparent}.task input:checked+.checkmark{background:var(--mint);border-color:var(--mint);color:#fff}.task.done .task-body{text-decoration:line-through;opacity:.45}.priority{font-size:10px;font-weight:800}.priority.p1{color:var(--amber)}.priority.p2{color:var(--mint)}.task-body strong,.task-body small{display:block}.task-body strong{font-size:12px}.task-body small{color:var(--muted);font-size:9px;margin-top:3px}.task .state{font-size:8px;font-weight:800;color:var(--muted)}.task a{color:var(--blue);text-decoration:none}.hypothesis-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:15px;border-top:1px solid var(--line)}.hypothesis-card{border:1px solid var(--line);border-radius:12px;padding:16px;background:var(--surface-soft)}.hypothesis-top,.hypothesis-foot{display:flex;justify-content:space-between;gap:10px;font-size:9px;color:var(--muted)}.hypothesis-top b{color:var(--mint)}.hypothesis-card.attention .hypothesis-top b{color:var(--amber)}.hypothesis-card h3{font-size:15px;margin:10px 0 5px}.hypothesis-card>p{color:var(--muted);font-size:11px}.hypothesis-card dl div{border-top:1px solid var(--line);padding:8px 0}.hypothesis-card dt{font-size:8px;color:var(--blue);text-transform:uppercase}.hypothesis-card dd{margin:3px 0 0;font-size:11px}.hypothesis-foot{border-top:1px solid var(--line);padding-top:9px}.utility-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.utility-grid .data-drawer{margin-top:24px}.empty{padding:24px;color:var(--muted);text-align:center}footer{display:grid;grid-template-columns:auto 1fr auto;gap:18px;align-items:center;margin-top:30px;padding:20px 4px;color:var(--muted);font-size:10px}footer span{text-align:center}footer small{font-size:9px}
@media(max-width:980px){.site-header nav{display:none}.overview{grid-template-columns:1fr;padding:36px}.overview-side{grid-template-columns:1fr 1fr;align-items:start}.metric-grid{grid-template-columns:repeat(4,1fr)}.health-panel{align-items:flex-start;flex-direction:column}.health-panel dl{width:100%;flex-wrap:wrap}.deal-toolbar{flex-direction:column}.deal-advanced-filters{grid-template-columns:repeat(3,1fr)}.deal-grid,.analytics-grid,.utility-grid{grid-template-columns:1fr}.signal-layout{grid-template-columns:1fr}.detail{position:static}.market-strip{grid-template-columns:1fr}.quote-card{border-right:0;border-bottom:1px solid var(--line)}.quote-card:last-child{border-bottom:0}}
@media(max-width:680px){.nav-wrap{height:62px;padding:0 16px}.brand{min-width:0}.brand small,.status strong{display:none}.page{padding:18px 12px 38px}.overview{padding:27px 22px;border-radius:16px;gap:26px}.overview h1{font-size:32px}.overview-copy>p{font-size:13px}.overview-actions{flex-direction:column}.overview-actions .button{width:100%}.overview-side{grid-template-columns:1fr}.metric-grid{grid-template-columns:1fr 1fr}.section{padding:20px 16px;border-radius:14px}.section-head,.deal-toolbar{flex-direction:column}.section-head h2{font-size:23px}.export-actions,.export-actions .button,.search{width:100%}.search{min-width:0}.deal-filters,.deal-advanced-filters{grid-template-columns:1fr 1fr;width:100%}.deal-filter{padding:8px 7px;font-size:10px}.deal-grid{grid-template-columns:1fr}.deal-tile{min-height:0;padding:17px}.parties,.entity-grid{grid-template-columns:1fr}.entity-grid div+div{border-left:0;border-top:1px solid var(--line);padding:8px 0 0}.party-arrow{display:none}.deal-facts,.typed-facts{grid-template-columns:1fr 1fr}.deal-facts div:nth-child(3){display:block}.event-card{grid-template-columns:34px minmax(0,1fr) 18px;padding:13px 11px}.score{width:31px;height:31px}.filters{width:100%}.analytics-grid{grid-template-columns:1fr}.task{grid-template-columns:20px 27px minmax(0,1fr) 16px}.task .state{display:none}.hypothesis-grid{grid-template-columns:1fr}.utility-grid{display:block}footer{grid-template-columns:1fr;text-align:center}footer span{text-align:center}}
@media print{.site-header,.overview-actions,.deal-toolbar,.filters,.event-search,.utility-grid{display:none}.page{max-width:none;padding:0}.overview{color:#111;background:#fff;border:1px solid #ccc;box-shadow:none}.overview-copy>p{color:#444}.section{break-inside:avoid;box-shadow:none}.deal-grid{grid-template-columns:1fr 1fr}}
"""
