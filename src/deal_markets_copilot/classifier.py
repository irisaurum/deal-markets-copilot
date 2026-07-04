from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .models import ClassifiedEvent, Event


CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "M&A": (
        "acquisition", "acquire", "merger", "takeover", "buyout", "divest",
        "strategic review", "приобрет", "слиян", "поглощ", "продаж бизнеса",
        "сделк", "покупк", "закрыл сделку", "может купить", "продал",
    ),
    "ECM": (
        "ipo", "follow-on", "secondary offering", "rights issue", "share placement",
        "размещен акций", "размещение акций", "публичн размещен", "допэмисс", "spo", "spо",
        "offering price", "free float", "buyback",
        "выкуп акций", "дивиденд",
    ),
    "DCM": (
        "bond", "notes offering", "refinancing", "credit facility", "debt issuance",
        "облигац", "кредитн лини", "рефинансир", "заем",
    ),
    "Earnings": (
        "earnings", "results", "revenue", "ebitda", "guidance", "financial results",
        "отчетност", "выручк", "прибыл", "ebitda", "прогноз",
    ),
    "Regulatory": (
        "antitrust", "regulator", "investigation", "sanction", "approval", "filing",
        "регулятор", "расследован", "согласован", "антимонопол", "санкц",
    ),
    "Macro": (
        "central bank", "interest rate", "inflation", "gdp", "cpi", "currency",
        "ключевая ставка", "инфляц", "ввп", "центробанк", "курс валют",
    ),
}


BANKER_ANGLES = {
    "M&A": "Проверить стратегическую логику, потенциальных покупателей, valuation и precedent transactions.",
    "ECM": "Оценить equity story, размер размещения, dilution, окно рынка и trading comps.",
    "DCM": "Проверить размер долга, купон/доходность, maturity profile, leverage и use of proceeds.",
    "Earnings": "Обновить financials, прогнозы, KPI, консенсус и valuation multiples.",
    "Regulatory": "Оценить влияние на certainty, сроки сделки, доступ к капиталу и disclosure.",
    "Macro": "Проверить влияние на стоимость капитала, FX, секторные мультипликаторы и окно рынка.",
    "Strategic": "Определить влияние на позиционирование компании и потенциальные транзакционные сценарии.",
}


NEXT_ACTIONS = {
    "M&A": "Добавить событие в deal log и подготовить one-page transaction snapshot.",
    "ECM": "Обновить market window и таблицу comparable issuances.",
    "DCM": "Обновить debt comps и проверить ближайшие погашения.",
    "Earnings": "Занести новые KPI в модель и пересчитать trading comps.",
    "Regulatory": "Зафиксировать milestone, source и вопрос для legal/human review.",
    "Macro": "Обновить market assumptions и чувствительность valuation.",
    "Strategic": "Добавить в watchlist и проверить первичный источник.",
}


def stable_event_id(title: str, url: str) -> str:
    raw = f"{title.strip().lower()}|{url.strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def classify_event(event: Event, coverage: list[dict]) -> ClassifiedEvent:
    text = f"{event.title} {event.summary}".lower()
    category = "Strategic"
    keyword_hits = 0

    for candidate, keywords in CATEGORY_KEYWORDS.items():
        hits = len({keyword for keyword in keywords if keyword in text})
        if hits > keyword_hits:
            category = candidate
            keyword_hits = hits

    non_transaction_notice = _is_non_transaction_notice(text)
    if non_transaction_notice:
        keyword_hits = 0

    if re.search(r"\b(bond|notes)\b|облигац", text, re.I) and not re.search(r"acquisition\s+of\s+(?:a\s+)?company|покупк\w*\s+(?:компани|бизнес)", text, re.I):
        category = "DCM"

    matched: list[str] = []
    for company in coverage:
        aliases = [company.get("company", ""), company.get("ticker", "")]
        aliases.extend(company.get("aliases", []))
        if any(alias and _alias_matches(alias, text) for alias in aliases):
            ticker = company.get("ticker") or company.get("company", "Unknown")
            if ticker not in matched:
                matched.append(ticker)

    score = 0
    score += min(keyword_hits, 3) * 2
    if matched:
        score += 2
    if event.amount:
        score += 1
    if event.confidence == "confirmed":
        score += 1
    if event.source_type in {"official_exchange", "official_regulator", "official_issuer"}:
        score += 2
    source_name = event.source.lower()
    if any(low_quality in source_name for low_quality in ("форум", "smart-lab", "forum")):
        score -= 2
    if any(high_quality in source_name for high_quality in ("reuters", "интерфакс", "moex", "банк россии", "company release")):
        score += 1
    score += _recency_bonus(event.published_at)
    score = max(0, min(score, 10))
    if non_transaction_notice:
        score = 0

    severity = "critical" if score >= 8 else "high" if score >= 6 else "medium" if score >= 3 else "low"
    evidence = event.confidence if event.confidence in {"confirmed", "inferred", "unverified", "conflicting"} else "unverified"

    return ClassifiedEvent(
        event=event,
        category=category,
        score=score,
        severity=severity,
        banker_angle=BANKER_ANGLES[category],
        next_action=NEXT_ACTIONS[category],
        matched_coverage=matched,
        evidence_label=evidence,
    )


def _is_non_transaction_notice(text: str) -> bool:
    """Keep exchange administration and fund trading out of deal workflows."""
    patterns = (
        r"московская биржа начала торги (?:паями|акциями|облигациями)",
        r"\b(?:бпиф|ипиф|пиф)\b",
        r"инвестиционн\w*\s+па[йё]",
        r"(?:итоги|проведени\w*)\s+аукцион\w*.+\bофз\b",
        r"\bофз\b.+аукцион",
        r"^о регистрации (?:выпуска|проспекта|программы|изменений)",
        r"^о признании выпуск\w* облигац\w* несостоявш",
        r"^итоги выпуска биржевых облигаций",
        r"^о порядке (?:сбора заявок|приобретения облигаций|заключения сделок)",
        r"^операции репо .+сделки купли-продажи облигаций",
        r"получил\w*\s+в\s+залог.+(?:акци|дол)",
    )
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def deduplicate(events: list[Event]) -> list[Event]:
    unique: list[Event] = []
    exact_ids: set[str] = set()
    for event in events:
        key = event.event_id or stable_event_id(event.title, event.url)
        if key in exact_ids:
            continue
        event.event_id = key
        exact_ids.add(key)
        duplicate_index = next((i for i, current in enumerate(unique) if _title_similarity(event.title, current.title) >= 0.30), None)
        if duplicate_index is None:
            unique.append(event)
        elif _source_rank(event.source, event.source_type) > _source_rank(unique[duplicate_index].source, unique[duplicate_index].source_type):
            unique[duplicate_index] = event
    return unique


def _title_similarity(left: str, right: str) -> float:
    left_codes = _security_identifiers(left)
    right_codes = _security_identifiers(right)
    if left_codes and right_codes and left_codes.isdisjoint(right_codes):
        return 0.0
    left_entities = _quoted_entities(left)
    right_entities = _quoted_entities(right)
    if left_entities and left_entities == right_entities and len(left_entities) > 1:
        return 1.0
    stop = {"яндекс", "яндекса", "ozon", "озон", "сделка", "сделку", "сделки", "рублей", "компания", "company"}
    def tokens(value: str) -> set[str]:
        return {token for token in re.findall(r"[a-zа-яё0-9.]+", value.lower()) if len(token) >= 3 and token not in stop}
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _security_identifiers(value: str) -> set[str]:
    """Keep distinct bond/equity issues from collapsing into one issuer story."""
    return {
        token.upper()
        for token in re.findall(r"\b(?:RU[A-Z0-9]{10}|\d{3,4}[РP]-\d{1,3}|[A-ZА-Я0-9]{2,12}-\d{1,3})\b", value, re.I)
    }


def _quoted_entities(value: str) -> set[str]:
    entities = set()
    for chunk in re.findall(r"[«\"]([^»\"]+)[»\"]", value.lower()):
        normalized = re.sub(r"[^a-zа-яё0-9.]+", " ", chunk).strip()
        if normalized and normalized not in {"яндекс", "яндекса", "коммерсантъ", "т технологии"}:
            entities.add(normalized)
    return entities


def _alias_matches(alias: str, text: str) -> bool:
    alias = alias.lower().strip()
    if len(alias) >= 4:
        return alias in text
    return bool(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text))


def _source_rank(source: str, source_type: str = "") -> int:
    if source_type in {"official_exchange", "official_regulator", "official_issuer"}:
        return 5
    name = source.lower()
    if any(value in name for value in ("интерфакс", "reuters", "company release", "moex", "банк россии")):
        return 3
    if any(value in name for value in ("ведомости", "коммерсант", "рбк", "finam", "финам", "бкс")):
        return 2
    if any(value in name for value in ("smart-lab", "форум", "forum")):
        return 0
    return 1


def _recency_bonus(value: str) -> int:
    try:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600
        return 1 if -1 <= age_hours <= 48 else 0
    except (TypeError, ValueError):
        return 0
