from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

from .models import ClassifiedEvent


def build_html_report(
    items: list[ClassifiedEvent],
    config: dict,
    output_path: str | Path,
    mode: str,
    market_snapshot: list[dict] | None = None,
    workflow: dict | None = None,
    precedent_transactions: list[dict] | None = None,
) -> Path:
    """Build a daily IB workflow desk rather than a generic news dashboard."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    ranked = sorted(items, key=lambda item: (item.score, item.event.published_at), reverse=True)
    quotes = market_snapshot or []
    flow = workflow or _empty_workflow()
    precedents = precedent_transactions or []
    counts = Counter(item.category for item in ranked)
    generated = datetime.now().astimezone().strftime("%d.%m.%Y · %H:%M")
    news_window = "72H CATCH-UP" if datetime.now().astimezone().weekday() in {0, 5, 6} else "24H"
    live = mode == "live"
    new_ids = set(flow.get("new_event_ids", []))
    scope = " · ".join(row.get("ticker", "") for row in config.get("coverage", []) if row.get("ticker")) or "CUSTOM"

    event_payload = [_event_payload(item, item.event.event_id in new_ids) for item in ranked]
    payload_json = json.dumps(event_payload, ensure_ascii=False).replace("</", "<\\/")
    brief_text = _brief_text(flow, generated)
    brief_json = json.dumps(brief_text, ensure_ascii=False).replace("</", "<\\/")

    document = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Banker Morning Desk</title><style>{_CSS}{_DEAL_CSS}</style></head>
<body><div class="shell">
<aside class="sidebar">
  <div class="brand"><span class="brand-mark">D</span><div><strong>DEAL DESK</strong><small>JUNIOR BANKER COPILOT</small></div></div>
  <nav><a class="active" href="#brief"><span>01</span>Morning brief</a><a href="#deal-card"><span>02</span>Deal card</a>
  <a href="#actions"><span>03</span>Действия</a><a href="#hypotheses"><span>04</span>Deal hypotheses</a>
  <a href="#signals"><span>05</span>Сигналы</a><a href="#sources"><span>06</span>Источники</a></nav>
  <div class="scope"><span>WATCHLIST</span><strong>TMT · RUSSIA</strong><small>{html.escape(scope)}</small></div>
  <div class="sidebar-note">Focused IB workflow<br>Не является Bloomberg Terminal</div>
</aside>
<main class="workspace">
  <header class="topbar"><div><span class="crumb">WORKSPACE / MORNING RUN</span><h1>Banker Morning Desk</h1></div>
  <div class="status"><span class="dot {'live' if live else 'demo'}"></span><div><strong>{f'LIVE PUBLIC DATA · {news_window}' if live else 'DEMO DATA'}</strong><small>{generated}</small></div></div></header>

  <section class="hero panel" id="brief">
    <div><span class="kicker">DAILY DEAL FLOW · {news_window} · M&A / ECM / DCM</span><h2>Что изменилось. Что обновить. Что отдать.</h2>
    <p>{html.escape(flow.get('summary', 'Запусти сборку, чтобы сформировать morning workflow.'))}</p></div>
    <div class="hero-actions"><button id="copy-brief">Скопировать brief</button><button class="secondary" onclick="window.print()">Печать / PDF</button></div>
  </section>

  <section class="market-tape">{_quote_cards(quotes, live)}</section>
  <section class="metrics">
    {_metric("Новых сигналов", flow.get("new_signals", 0), "с прошлого запуска")}
    {_metric("Analyst actions", len(flow.get("tasks", [])), "чекбоксы сохраняются")}
    {_metric("Hypotheses at risk", flow.get("attention_hypotheses", 0), "нужен review")}
    {_metric("Покрытие", len(config.get("coverage", [])), "компаний в watchlist")}
  </section>

  <section class="deal-module" id="deal-card">
    {_deal_card(precedents[0] if precedents else None)}
    <div class="panel precedent-panel">
      <div class="panel-head"><div><span class="kicker">PRECEDENT TRANSACTIONS</span><h2>Накопительная база сделок</h2></div>
      <div class="export-actions"><a href="precedent_transactions.xlsx" download>Excel .xlsx ↓</a><a class="secondary-export" href="precedent_transactions.csv" download>CSV ↓</a></div></div>
      <div class="precedent-summary"><span><b>{len(precedents)}</b> сделок в базе</span><span>Source-backed · screening-grade</span></div>
      {_precedent_table(precedents[:8])}
    </div>
  </section>

  <section class="workflow-grid" id="actions">
    <div class="panel action-panel">
      <div class="panel-head"><div><span class="kicker">BANKER ACTION QUEUE</span><h2>Что сделать сегодня</h2></div>
      <span class="provider"><b id="open-count">{len(flow.get('tasks', []))}</b> OPEN · LOCAL STATE</span></div>
      <div class="task-list">{_task_rows(flow.get('tasks', []))}</div>
    </div>
    <aside class="panel readout">
      <span class="kicker">60-SECOND READOUT</span><h2>Утренний вывод</h2>{_readout(flow.get('readout', []))}
      <div class="baseline"><span>CHANGE DETECTION</span><strong>{'Baseline создан' if flow.get('baseline_status') == 'baseline_created' else 'Сравнено с прошлым запуском'}</strong></div>
    </aside>
  </section>

  <section class="panel hypotheses" id="hypotheses">
    <div class="panel-head"><div><span class="kicker">ACTIVE DEAL HYPOTHESES</span><h2>За какими сценариями мы следим</h2></div>
    <span class="provider">INTERNAL HYPOTHESES · NOT TRANSACTION FACTS</span></div>
    <div class="hypothesis-grid">{_hypothesis_cards(flow.get('hypotheses', []))}</div>
  </section>

  <section class="terminal-grid" id="signals">
    <div class="radar panel">
      <div class="panel-head"><div><span class="kicker">SOURCE-BACKED SIGNAL RADAR</span><h2>События и изменения</h2></div>
      <div class="filters"><button class="filter active" data-filter="all">Все</button><button class="filter" data-filter="new">Только новые</button>{_filter_buttons(counts)}</div></div>
      <div class="search"><span>⌕</span><input id="event-search" placeholder="Компания, событие или источник"></div>
      <div class="event-list">{_event_cards(ranked, new_ids)}</div>
    </div>
    <aside class="detail panel">{_detail_panel(ranked[0] if ranked else None, ranked[0].event.event_id in new_ids if ranked else False)}</aside>
  </section>

  <section class="panel market-table">
    <div class="panel-head"><div><span class="kicker">MARKET MONITOR</span><h2>Котировки покрытия</h2></div><span class="provider">MOEX ISS · VS PREVIOUS CLOSE</span></div>
    {_quote_table(quotes)}
  </section>

  <section class="panel sources" id="sources">
    <div class="panel-head"><div><span class="kicker">EVIDENCE LEDGER</span><h2>На чём основан brief</h2></div>
    <span class="provider">ФАКТ ≠ HYPOTHESIS ≠ BANKER ACTION</span></div>{_source_table(ranked)}
  </section>
  <footer>Screen-grade public-data workflow · Material conclusions require analyst review · Not investment advice</footer>
</main></div>
<script>window.EVENTS={payload_json};window.BRIEF_TEXT={brief_json};{_JS}</script></body></html>"""
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
      <div><span>ANNOUNCED</span><strong>{html.escape(deal.get('announced_date','—') or '—')}</strong></div></div>
      <div class="deal-note"><span>RATIONALE / USE OF PROCEEDS</span><p>{html.escape(deal.get('rationale','Not disclosed'))}</p></div>
      <div class="deal-foot"><span>{html.escape(deal.get('instrument',''))} · {html.escape(deal.get('evidence_label','unverified'))}</span><a href="{html.escape(source_url, quote=True)}" target="_blank" rel="noopener">Source ↗</a></div>
    </article>"""


def _precedent_table(rows: list[dict]) -> str:
    if not rows:
        return '<div class="empty">База пока пуста.</div>'
    output = []
    for row in rows:
        output.append(f"""<tr><td>{html.escape(row.get('announced_date','—') or '—')}</td><td><b>{html.escape(row.get('deal_type',''))}</b><small>{html.escape(row.get('status',''))}</small></td>
        <td>{html.escape(row.get('target_or_issuer','Not disclosed'))}</td><td>{html.escape(row.get('acquirer_or_investor','Not disclosed'))}</td>
        <td>{html.escape(_deal_amount(row.get('transaction_value'), row.get('currency','')))}</td><td>{html.escape(row.get('instrument',''))}</td>
        <td><a href="{html.escape(_safe_url(row.get('source_url','')), quote=True)}" target="_blank" rel="noopener">{html.escape(row.get('source_name','Source'))} ↗</a></td></tr>""")
    return f'<div class="table-wrap"><table><thead><tr><th>Date</th><th>Type</th><th>Target / Issuer</th><th>Acquirer</th><th>Value</th><th>Instrument</th><th>Source</th></tr></thead><tbody>{"".join(output)}</tbody></table></div>'


def _deal_amount(value, currency: str) -> str:
    if value in {None, ""}:
        return "Not disclosed"
    number = float(value)
    symbol = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(str(currency).upper(), str(currency))
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:,.1f} bn {symbol}".replace(",", " ")
    if number >= 1_000_000:
        return f"{number / 1_000_000:,.1f} mm {symbol}".replace(",", " ")
    return f"{number:,.0f} {symbol}".replace(",", " ")


def _quote_cards(quotes: list[dict], live: bool) -> str:
    if not quotes:
        state = "Ожидает live-запуска" if not live else "Данные временно недоступны"
        return f'<div class="tape-empty">MOEX MARKET TAPE · {state}</div>'
    cards = []
    for quote in quotes:
        price = _number(quote.get("price"), 2)
        change = quote.get("change_percent")
        change_text = "—" if change is None else f"{change:+.2f}%"
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
    <a id="detail-link" class="primary-link" href="{html.escape(payload['url'], quote=True)}" target="_blank" rel="noopener">Открыть материал ↗</a>"""


def _quote_table(quotes: list[dict]) -> str:
    if not quotes:
        return '<div class="empty">Запусти <code>python3 run.py --live</code>, чтобы получить реальные котировки.</div>'
    rows = []
    for quote in quotes:
        change = quote.get("change_percent")
        rows.append(f"""<tr><td><strong>{html.escape(quote.get('ticker',''))}</strong><small>{html.escape(quote.get('company',''))}</small></td>
        <td>{_number(quote.get('price'),2)} ₽</td><td class="{'positive' if (change or 0)>0 else 'negative' if (change or 0)<0 else ''}">{'—' if change is None else f'{change:+.2f}%'}</td>
        <td>{_compact(quote.get('turnover'))}</td><td>{html.escape(str(quote.get('updated','—')))}</td><td><a href="{html.escape(_safe_url(quote.get('source_url','')), quote=True)}" target="_blank" rel="noopener">MOEX ISS ↗</a></td></tr>""")
    return f'<div class="table-wrap"><table><thead><tr><th>Security</th><th>Last</th><th>Change</th><th>Turnover</th><th>Updated</th><th>Source</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _source_table(items: list[ClassifiedEvent]) -> str:
    rows = []
    for index, item in enumerate(items, 1):
        event = item.event
        rows.append(f"""<tr><td>SRC-{index:03d}</td><td>{html.escape(event.source)}</td><td>{html.escape(_short_date(event.published_at))}</td>
        <td>{html.escape(item.evidence_label)}</td><td>{html.escape(item.category)}</td><td>{html.escape(event.title[:90])}</td><td><a href="{html.escape(_safe_url(event.url), quote=True)}" target="_blank" rel="noopener">Открыть ↗</a></td></tr>""")
    return f'<div class="table-wrap"><table><thead><tr><th>ID</th><th>Источник</th><th>Дата</th><th>Статус</th><th>Тип</th><th>Claim</th><th>Ссылка</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _event_payload(item: ClassifiedEvent, is_new: bool) -> dict:
    return {
        "title": item.event.title, "category": item.category,
        "coverage": ", ".join(item.matched_coverage) or "MARKET",
        "evidence": item.evidence_label, "source": item.event.source,
        "url": _safe_url(item.event.url), "banker_angle": item.banker_angle,
        "next_action": item.next_action, "score": item.score,
        "severity": item.severity, "is_new": is_new,
    }


def _number(value, digits: int) -> str:
    return "—" if value is None else f"{float(value):,.{digits}f}".replace(",", " ")


def _safe_url(value: str) -> str:
    try:
        parsed = urlparse(str(value).strip())
        return str(value).strip() if parsed.scheme in {"http", "https"} and parsed.netloc else "#"
    except (TypeError, ValueError):
        return "#"


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
cards.forEach(card=>card.addEventListener('click',event=>{if(event.target.closest('a'))return;cards.forEach(x=>x.classList.remove('selected'));card.classList.add('selected');const d=window.EVENTS[Number(card.dataset.index)];
document.getElementById('detail-title').textContent=d.title;document.getElementById('detail-angle').textContent=d.banker_angle;document.getElementById('detail-action').textContent=d.next_action;document.getElementById('detail-category').textContent=d.category;document.getElementById('detail-coverage').textContent=d.coverage;document.getElementById('detail-evidence').textContent=d.evidence;document.getElementById('detail-source').textContent=d.source;document.getElementById('detail-score').textContent=d.score+'/10';document.getElementById('detail-state').textContent=d.is_new?'NEW SIGNAL':d.severity.toUpperCase();document.getElementById('detail-link').href=d.url;}));
const completed=JSON.parse(localStorage.getItem('dealDeskCompleted')||'{}');
function refreshTasks(){document.querySelectorAll('.task').forEach(row=>{const check=row.querySelector('.task-check');check.checked=!!completed[row.dataset.taskId];row.classList.toggle('done',check.checked);});document.getElementById('open-count').textContent=document.querySelectorAll('.task:not(.done)').length;localStorage.setItem('dealDeskCompleted',JSON.stringify(completed));}
document.querySelectorAll('.task-check').forEach(check=>check.addEventListener('change',()=>{const row=check.closest('.task');completed[row.dataset.taskId]=check.checked;if(!check.checked)delete completed[row.dataset.taskId];refreshTasks();}));refreshTasks();
document.getElementById('copy-brief').addEventListener('click',async event=>{await navigator.clipboard.writeText(window.BRIEF_TEXT);const old=event.currentTarget.textContent;event.currentTarget.textContent='Скопировано ✓';setTimeout(()=>event.currentTarget.textContent=old,1300);});
setInterval(()=>{if(document.visibilityState==='visible')window.location.reload();},AUTO_REFRESH_MS);
"""


_CSS = r"""
:root{--bg:#070a0f;--surface:#10151d;--surface2:#151c26;--line:#253040;--text:#eef2f7;--muted:#8b98aa;--cyan:#34d1bb;--blue:#6aa7ff;--amber:#ffbd5b;--red:#ff6b6b;--green:#51d88a}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font:13px/1.45 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.shell{display:grid;grid-template-columns:230px minmax(0,1fr);min-height:100vh}.panel{border:1px solid var(--line);background:var(--surface);padding:18px}
.sidebar{position:sticky;top:0;height:100vh;border-right:1px solid var(--line);background:#0a0e14;padding:24px 18px;display:flex;flex-direction:column}.brand{display:flex;gap:12px;align-items:center;margin-bottom:40px}.brand-mark{display:grid;place-items:center;width:36px;height:36px;background:var(--cyan);color:#06100e;font-size:20px;font-weight:900}.brand strong{display:block;font-size:13px;letter-spacing:1.5px}.brand small{display:block;color:var(--muted);font-size:8px;letter-spacing:1.2px}nav{display:grid;gap:4px}nav a{display:flex;gap:12px;padding:11px 12px;color:var(--muted);text-decoration:none;border-left:2px solid transparent}nav a span{font-family:monospace;color:#526070}nav a:hover,nav a.active{color:var(--text);background:var(--surface);border-left-color:var(--cyan)}.scope{margin-top:38px;padding:14px;border:1px solid var(--line);display:grid;gap:5px}.scope span,.kicker,.detail-section span,.detail-grid span,.baseline span{color:var(--cyan);font-size:9px;font-weight:800;letter-spacing:1.3px}.scope small{color:var(--muted)}.sidebar-note{margin-top:auto;color:#596575;font-size:10px;line-height:1.6}
.workspace{min-width:0;padding:24px 28px 44px;max-width:1680px;width:100%;margin:auto}.topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}.crumb{font:10px monospace;color:var(--muted)}h1{font-size:28px;margin:5px 0 0;letter-spacing:-.5px}h2{font-size:18px;margin:4px 0}.status{display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid var(--line);background:var(--surface)}.status strong{display:block;font-size:10px;letter-spacing:.8px}.status small{display:block;color:var(--muted);font-size:9px}.dot{width:8px;height:8px;border-radius:50%}.dot.live{background:var(--green);box-shadow:0 0 12px var(--green)}.dot.demo{background:var(--amber)}
.hero{display:flex;align-items:center;justify-content:space-between;gap:30px;background:linear-gradient(100deg,#111923,#0d131b);border-left:3px solid var(--cyan);padding:24px;margin-bottom:12px}.hero h2{font-size:25px;margin:8px 0 5px}.hero p{color:#b8c2cf;margin:0}.hero-actions{display:flex;gap:8px;flex:none}.hero button{border:1px solid var(--cyan);background:var(--cyan);color:#06100e;padding:10px 13px;font:700 11px inherit;cursor:pointer}.hero button.secondary{background:transparent;color:var(--text);border-color:var(--line)}
.market-tape{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line);background:var(--surface);margin-bottom:12px}.quote-card{display:grid;grid-template-columns:1fr auto auto;gap:14px;align-items:center;padding:12px 15px;border-right:1px solid var(--line);color:var(--text);text-decoration:none}.quote-card:last-child{border:0}.quote-card strong,.quote-card small{display:block}.quote-card small{font-size:9px;color:var(--muted)}.quote-price{font:700 14px monospace}.quote-change{font:700 12px monospace}.up,.positive{color:var(--green)}.down,.negative{color:var(--red)}.flat{color:var(--muted)}.tape-empty{padding:12px;color:var(--muted);font:10px monospace;grid-column:1/-1}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}.metrics article{border:1px solid var(--line);background:var(--surface);padding:15px}.metrics span,.metrics small{display:block;color:var(--muted)}.metrics strong{display:block;font:700 27px monospace;color:var(--text);margin:5px 0}.metrics small{font-size:9px}.workflow-grid{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(300px,.7fr);gap:12px;align-items:start}.panel-head{display:flex;justify-content:space-between;gap:15px;align-items:flex-end;margin-bottom:14px}.provider{font:9px monospace;color:var(--muted)}
.task-list{display:grid}.task{position:relative;display:grid;grid-template-columns:22px 36px minmax(0,1fr) 54px 18px;gap:10px;align-items:center;padding:13px 6px;border-bottom:1px solid var(--line);cursor:pointer}.task:hover{background:var(--surface2)}.task input{position:absolute;opacity:0}.checkmark{display:grid;place-items:center;width:18px;height:18px;border:1px solid #3a4656;color:transparent}.task input:checked+.checkmark{background:var(--cyan);border-color:var(--cyan);color:#06100e}.task.done .task-body{text-decoration:line-through;opacity:.45}.priority{font:800 10px monospace}.priority.p1{color:var(--amber)}.priority.p2{color:var(--green)}.task-body strong,.task-body small{display:block}.task-body strong{font-size:12px}.task-body small{color:var(--muted);font-size:9px;margin-top:4px}.task .state{font:800 8px monospace;color:var(--muted)}.task .state.new{color:var(--cyan)}.task .state.market{color:var(--blue)}.task a{color:var(--blue);text-decoration:none}.readout{background:linear-gradient(145deg,#121923,#0d131b)}.readout-row{padding:15px 0;border-bottom:1px solid var(--line)}.readout-row span{font:800 9px monospace;color:var(--muted);text-transform:uppercase}.readout-row p{margin:5px 0 0;color:#d0d7e1}.baseline{display:grid;gap:4px;margin-top:17px;padding:12px;border:1px solid var(--line)}
.hypotheses,.market-table,.sources{margin-top:12px}.hypothesis-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.hypothesis-card{border:1px solid var(--line);background:#0d1219;padding:17px}.hypothesis-card.attention{border-top:2px solid var(--amber)}.hypothesis-card.active{border-top:2px solid var(--green)}.hypothesis-top,.hypothesis-foot{display:flex;justify-content:space-between;gap:10px;font:9px monospace;color:var(--muted)}.hypothesis-top b{color:var(--green)}.hypothesis-card.attention .hypothesis-top b{color:var(--amber)}.hypothesis-card h3{font-size:15px;margin:10px 0 6px}.hypothesis-card>p{color:var(--muted);font-size:11px;min-height:32px}.hypothesis-card dl{margin:14px 0}.hypothesis-card dl div{border-top:1px solid var(--line);padding:9px 0}.hypothesis-card dt{font:8px monospace;color:var(--cyan);text-transform:uppercase}.hypothesis-card dd{margin:3px 0 0;font-size:11px}.hypothesis-foot{border-top:1px solid var(--line);padding-top:10px}.hypothesis-foot b{color:var(--cyan)}
.terminal-grid{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(300px,.75fr);gap:12px;align-items:start;margin-top:12px}.filters{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:5px}.filter{border:1px solid var(--line);background:var(--bg);color:var(--muted);padding:6px 9px;cursor:pointer;font:10px inherit}.filter:hover,.filter.active{color:#06100e;background:var(--cyan);border-color:var(--cyan)}.filter small{opacity:.7}.search{display:flex;gap:8px;align-items:center;background:#090d12;border:1px solid var(--line);padding:9px 12px;margin-bottom:10px}.search span{color:var(--cyan)}.search input{width:100%;background:transparent;border:0;outline:0;color:var(--text);font:12px inherit}.search input::placeholder{color:#556170}.event-list{display:grid;max-height:650px;overflow:auto}.event-card{position:relative;display:grid;grid-template-columns:42px minmax(0,1fr) 28px;gap:12px;padding:14px 10px;border-bottom:1px solid var(--line);cursor:pointer}.event-card:hover,.event-card.selected{background:var(--surface2)}.event-card.selected:before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--cyan)}.score{display:grid;place-items:center;width:34px;height:34px;border:1px solid var(--line);font:800 14px monospace}.score.critical{color:var(--red)}.score.high{color:var(--amber)}.score.medium{color:var(--green)}.event-meta{display:flex;flex-wrap:wrap;gap:9px;color:var(--muted);font:9px monospace;text-transform:uppercase}.event-meta span:first-child{color:var(--cyan)}.event-meta b{background:var(--cyan);color:#06100e;padding:1px 4px}.event-card h3{font-size:14px;margin:6px 0 3px}.event-card p{color:var(--muted);font-size:11px;margin:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.event-source{color:#566375;font-size:9px;margin-top:7px}.source-link{color:var(--blue);text-decoration:none;font-size:16px}.event-card[hidden]{display:none}
.detail{position:sticky;top:18px;background:linear-gradient(145deg,#121923,#0e131b)}.detail-score{display:flex;align-items:end;gap:8px;margin:18px 0 12px}.detail-score span{font:800 30px monospace;color:var(--cyan)}.detail-score small{color:var(--muted);font-size:9px}.detail h2{font-size:20px;line-height:1.25;margin-bottom:22px}.detail-section{border-top:1px solid var(--line);padding:14px 0}.detail-section p{margin:6px 0 0;color:#c7d0dc}.detail-grid{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid var(--line);margin:4px 0 18px}.detail-grid div{padding:10px 0;border-bottom:1px solid var(--line)}.detail-grid strong{display:block;margin-top:4px;font-size:11px}.primary-link{display:block;background:var(--cyan);color:#06100e;padding:11px;text-align:center;text-decoration:none;font-weight:800}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:760px}th{text-align:left;color:#687587;font:9px monospace;text-transform:uppercase;padding:9px;border-bottom:1px solid var(--line)}td{padding:11px 9px;border-bottom:1px solid var(--line);font-size:11px}td small{display:block;color:var(--muted);font-size:9px}td a{color:var(--blue);text-decoration:none}.empty{padding:25px;color:var(--muted);text-align:center}footer{text-align:center;color:#515c6b;font-size:9px;padding:30px 0 0}
@media(max-width:1100px){.shell{grid-template-columns:1fr}.sidebar{position:static;height:auto;display:block;border-right:0;border-bottom:1px solid var(--line)}.brand{margin-bottom:16px}.sidebar nav{display:flex;overflow:auto}.scope,.sidebar-note{display:none}.workflow-grid,.terminal-grid{grid-template-columns:1fr}.detail{position:static}.workspace{padding:18px}.market-tape{grid-template-columns:1fr}.quote-card{border-right:0;border-bottom:1px solid var(--line)}}
@media(max-width:700px){.topbar,.panel-head,.hero{align-items:flex-start;flex-direction:column}.metrics,.hypothesis-grid{grid-template-columns:1fr 1fr}.filters{justify-content:flex-start}.task{grid-template-columns:22px 30px minmax(0,1fr) 18px}.task .state{display:none}.hero-actions{width:100%}.hero button{flex:1}.event-card{grid-template-columns:38px minmax(0,1fr) 20px}h1{font-size:22px}}
@media print{.sidebar,.hero-actions,.filters,.search{display:none}.shell{display:block}.workspace{max-width:none;padding:0}.panel{break-inside:avoid;background:#fff;color:#111;border-color:#bbb}.task,.event-card{break-inside:avoid}body{background:#fff;color:#111}.muted{color:#555}}
"""

_DEAL_CSS = r"""
.deal-module{display:grid;grid-template-columns:minmax(320px,.9fr) minmax(520px,1.5fr);gap:14px;margin-bottom:14px;align-items:start}.deal-card{padding:22px}.deal-card-top{display:flex;justify-content:space-between;gap:12px}.deal-card-top b{font:700 10px monospace;color:var(--cyan);border:1px solid #24524f;padding:5px 8px}.deal-type{margin:22px 0 8px;color:var(--cyan);font:700 11px monospace;letter-spacing:.08em}.deal-card h2{font-size:21px;line-height:1.3;margin:0 0 20px}.deal-kpis{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line)}.deal-kpis div{padding:13px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.deal-kpis div:nth-child(2n){border-right:0}.deal-kpis div:nth-last-child(-n+2){border-bottom:0}.deal-kpis span,.deal-note span{display:block;color:var(--muted);font:700 9px monospace;letter-spacing:.08em;margin-bottom:6px}.deal-kpis strong{font-size:12px}.deal-note{margin-top:16px;padding:13px;background:#0c1219;border-left:2px solid var(--cyan)}.deal-note p{margin:0;font-size:12px;line-height:1.5}.deal-foot{display:flex;justify-content:space-between;gap:12px;margin-top:16px;color:var(--muted);font:10px monospace}.deal-foot a,.export-actions a{color:#071014;background:var(--cyan);padding:8px 11px;text-decoration:none;font-weight:800}.precedent-panel{overflow:hidden}.precedent-panel .panel-head{padding:20px 20px 14px}.precedent-summary{display:flex;justify-content:space-between;padding:0 20px 14px;color:var(--muted);font:10px monospace}.precedent-summary b{color:var(--text);font-size:15px}.export-actions{display:flex;gap:7px}.export-actions .secondary-export{background:transparent;color:var(--text);border:1px solid var(--line)}.precedent-panel .table-wrap{border-top:1px solid var(--line)}.precedent-panel td{vertical-align:top}.precedent-panel td:nth-child(3),.precedent-panel td:nth-child(4){max-width:150px}@media(max-width:1150px){.deal-module{grid-template-columns:1fr}}@media(max-width:700px){.deal-kpis{grid-template-columns:1fr}.deal-kpis div{border-right:0}.deal-kpis div:nth-last-child(2){border-bottom:1px solid var(--line)}.precedent-summary{align-items:flex-start;gap:8px;flex-direction:column}.export-actions{width:100%}.export-actions a{flex:1;text-align:center}}
"""
