from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

from .models import ClassifiedEvent, DealRecord


DEAL_CATEGORIES = {"M&A", "ECM", "DCM"}
CSV_FIELDS = [
    "deal_id", "announced_date", "deal_type", "status", "target_or_issuer",
    "acquirer_or_investor", "sector", "geography", "transaction_value",
    "enterprise_value", "currency", "stake_percent", "payment_form", "advisors",
    "revenue_ltm", "ebitda_ltm", "financials_as_of", "financials_currency",
    "ev_revenue", "ev_ebitda", "instrument", "rationale", "score",
    "evidence_label", "matched_coverage", "source_name", "source_url",
    "headline", "first_seen_at", "last_seen_at", "notes",
]


def extract_deal_record(item: ClassifiedEvent, coverage: list[dict]) -> DealRecord | None:
    if item.category not in DEAL_CATEGORIES:
        return None
    event = item.event
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    text = f"{event.title}. {event.summary}".strip()
    covered_company = _covered_company(item, coverage)
    enterprise_value, ev_currency = _extract_labeled_amount(text, ("enterprise value", "ev", "стоимость предприятия"))
    value, currency = (event.amount, event.currency or "") if event.amount else _extract_amount(text)
    if item.category == "M&A" and enterprise_value == value and not _has_explicit_transaction_value(text):
        value, currency = None, ""
    revenue, revenue_currency = _extract_labeled_amount(text, ("revenue", "выручка"))
    ebitda, ebitda_currency = _extract_labeled_amount(text, ("ebitda", "ебитда"))
    financials_currency = revenue_currency or ebitda_currency or ""
    aligned_currency = bool(enterprise_value and financials_currency and ev_currency == financials_currency)
    target, acquirer = _extract_parties(item.category, event.title, covered_company)
    return DealRecord(
        deal_id=f"DL-{event.event_id}",
        announced_date=_iso_date(event.published_at),
        deal_type=item.category,
        status=_status(text, item.category),
        target_or_issuer=target,
        acquirer_or_investor=acquirer,
        sector=_sector(text),
        geography="Russia" if re.search(r"\b(руб|росси|москва|moex)\w*", text, re.I) else "Not disclosed",
        headline=event.title.strip(),
        transaction_value=float(value) if value is not None else None,
        enterprise_value=enterprise_value,
        currency=(currency or "Not disclosed").upper(),
        stake_percent=_extract_stake(text),
        payment_form=_payment_form(text) if item.category == "M&A" else "Not applicable",
        advisors=_advisors(text),
        revenue_ltm=revenue,
        ebitda_ltm=ebitda,
        financials_as_of=_financials_as_of(text),
        financials_currency=financials_currency or "Not disclosed",
        ev_revenue=(enterprise_value / revenue) if aligned_currency and revenue and revenue > 0 else None,
        ev_ebitda=(enterprise_value / ebitda) if aligned_currency and ebitda and ebitda > 0 else None,
        instrument=_instrument(text, item.category),
        rationale=_rationale(text),
        matched_coverage=list(item.matched_coverage),
        source_name=event.source.strip() or "Unknown source",
        source_url=_safe_public_url(event.url),
        evidence_label=item.evidence_label,
        score=item.score,
        source_event_id=event.event_id,
        first_seen_at=now,
        last_seen_at=now,
        notes="Screening record; verify against primary transaction documents.",
    )


def update_precedent_database(records: list[DealRecord], path: str | Path) -> list[dict]:
    destination = Path(path)
    existing = _load_database(destination)
    by_id = {row.get("deal_id"): row for row in existing if row.get("deal_id")}
    for record in records:
        row = record.to_dict()
        old = by_id.get(record.deal_id)
        if old:
            row["first_seen_at"] = old.get("first_seen_at", row["first_seen_at"])
            for field in (
                "enterprise_value", "payment_form", "advisors", "revenue_ltm", "ebitda_ltm",
                "financials_as_of", "financials_currency", "ev_revenue", "ev_ebitda", "notes",
            ):
                if _is_blank(row.get(field)) and not _is_blank(old.get(field)):
                    row[field] = old[field]
        by_id[record.deal_id] = row
    by_source: dict[str, dict] = {}
    for row in by_id.values():
        key = row.get("source_url") or row.get("deal_id")
        old = by_source.get(key)
        if old is None or row.get("last_seen_at", "") >= old.get("last_seen_at", ""):
            by_source[key] = row
    output = sorted(by_source.values(), key=lambda row: (row.get("announced_date", ""), row.get("score", 0)), reverse=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def write_precedents_csv(rows: list[dict], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for source in rows:
            row = dict(source)
            row["matched_coverage"] = ", ".join(row.get("matched_coverage", []))
            writer.writerow(row)
    return destination


def select_key_deals(rows: list[dict], limit: int = 10) -> list[dict]:
    """Return material transaction records, excluding technical exchange notices."""
    selected: list[dict] = []
    for row in rows:
        category = row.get("deal_type")
        if not _is_material_transaction(row):
            continue
        target = row.get("target_or_issuer")
        acquirer = row.get("acquirer_or_investor")
        disclosed_party = target not in {None, "", "Not disclosed"} or acquirer not in {None, "", "Not disclosed", "Not applicable"}
        if category == "M&A" and disclosed_party:
            selected.append(row)
        elif category in {"ECM", "DCM"} and target not in {None, "", "Not disclosed"} and (
            row.get("transaction_value") or row.get("status") in {"Announced", "Issued", "Completed"}
        ):
            selected.append(row)
    clusters: list[dict] = []
    for row in selected:
        duplicate_index = next((index for index, current in enumerate(clusters) if _same_transaction(row, current)), None)
        if duplicate_index is None:
            clusters.append(row)
        elif _record_quality(row) > _record_quality(clusters[duplicate_index]):
            clusters[duplicate_index] = row
    clusters.sort(key=lambda row: (row.get("announced_date", ""), row.get("score", 0)), reverse=True)
    return clusters[:limit]


def _is_material_transaction(row: dict) -> bool:
    title = str(row.get("headline") or "").lower()
    category = row.get("deal_type")
    if category == "M&A":
        if "последний день покупки акций" in title:
            return False
        return bool(re.search(r"покуп|куп|приобрет|продал|продаж|слиян|поглощ|acquisition|merger|buyout", title))
    if category == "DCM":
        if re.search(r"погашен|погашения|перечислил.+погаш|заработай", title):
            return False
        if re.search(r"выкуп|разбор", title) and not re.search(r"размещ|анонс|план", title):
            return False
        return bool(re.search(r"размещ|выпуск|облигац|bond|notes", title))
    if category == "ECM":
        return bool(re.search(r"\bipo\b|\bspo\b|размещ|выкуп акций|buyback|эмисси", title))
    return False


def _record_quality(row: dict) -> tuple[int, int, int]:
    return (
        1 if row.get("evidence_label") == "confirmed" else 0,
        int(row.get("score") or 0),
        1 if row.get("transaction_value") else 0,
    )


def _same_transaction(left: dict, right: dict) -> bool:
    if left.get("deal_type") != right.get("deal_type"):
        return False
    try:
        if abs((datetime.fromisoformat(left.get("announced_date", "")) - datetime.fromisoformat(right.get("announced_date", ""))).days) > 10:
            return False
    except ValueError:
        pass
    a, b = _deal_entities(left.get("headline", "")), _deal_entities(right.get("headline", ""))
    return bool(a and b and len(a & b) / min(len(a), len(b)) >= 0.75)


def _deal_entities(value: str) -> set[str]:
    aliases = {
        "авто.ру": "auto.ru", "auto.ru": "auto.ru", "яндекс": "yandex", "yandex": "yandex",
        "т-технолог": "t-tech", "технологиям": "t-tech", "ozon": "ozon", "озон": "ozon",
        "сбер": "sber", "афк": "afk-system", "система": "afk-system", "остров": "ostrovok",
        "норникел": "nornickel", "selectel": "selectel", "втб": "vtb", "vk": "vk",
    }
    lowered = value.lower()
    return {canonical for token, canonical in aliases.items() if token in lowered}


def _load_database(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _covered_company(item: ClassifiedEvent, coverage: list[dict]) -> str:
    for ticker in item.matched_coverage:
        match = next((row for row in coverage if row.get("ticker") == ticker), None)
        if match:
            return str(match.get("company") or ticker)
    return item.event.companies[0] if item.event.companies else "Not disclosed"


def _extract_parties(category: str, title: str, covered_company: str) -> tuple[str, str]:
    clean = re.sub(r"\s+[—-]\s+[^—-]+$", "", title).strip()
    if category in {"ECM", "DCM"}:
        issuer = covered_company if covered_company != "Not disclosed" else _leading_entity(clean)
        return issuer, "Not applicable"
    patterns = [
        r"^(.+?)\s+(?:закрыл\w*\s+сделк\w*\s+по\s+покупке|приобр[её]л\w*|купил\w*)\s+(.+?)(?:\s+у\s+|\s+за\s+|$)",
        r"^(.+?)\s+(?:announces|evaluates|considers)?\s*acquisition of\s+(.+?)(?:\s+for\s+|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean, re.I)
        if match:
            return _clean_party(match.group(2)), _clean_party(match.group(1))
    if covered_company != "Not disclosed":
        return "Not disclosed", covered_company
    return "Not disclosed", "Not disclosed"


def _leading_entity(title: str) -> str:
    quoted = re.match(r"^[«\"]([^»\"]+)[»\"]", title)
    if quoted:
        return quoted.group(1).strip()
    words = re.split(r"\s+(?:размест|выпуст|планир|рассматрива|considers|explores|announces)\w*", title, maxsplit=1, flags=re.I)
    return _clean_party(words[0]) if words and len(words[0]) <= 80 else "Not disclosed"


def _clean_party(value: str) -> str:
    return value.strip(" \"'«».,:;")[:100] or "Not disclosed"


def _extract_amount(text: str) -> tuple[float | None, str]:
    pattern = re.compile(
        r"(?:(USD|EUR|RUB|\$|€|₽)\s*)?(\d+(?:[.,]\d+)?)\s*(трлн|trillion|млрд|billion|млн|million)?\s*(руб(?:лей|ля|\.)?|rub|usd|доллар\w*|eur|евро|₽|\$|€)?",
        re.I,
    )
    for match in pattern.finditer(text):
        unit = (match.group(3) or "").lower()
        suffix = (match.group(4) or "").lower()
        prefix = (match.group(1) or "").upper()
        if not (unit or suffix or prefix in {"USD", "EUR", "RUB", "$", "€", "₽"}):
            continue
        number = float(match.group(2).replace(",", "."))
        multiplier = 1_000_000_000_000 if unit in {"трлн", "trillion"} else 1_000_000_000 if unit in {"млрд", "billion"} else 1_000_000 if unit in {"млн", "million"} else 1
        token = f"{prefix} {suffix}"
        currency = "USD" if "$" in token or "USD" in token or "доллар" in token else "EUR" if "€" in token or "EUR" in token or "евро" in token else "RUB"
        return number * multiplier, currency
    return None, ""


def _extract_labeled_amount(text: str, labels: tuple[str, ...]) -> tuple[float | None, str]:
    label = "|".join(re.escape(value) for value in labels)
    match = re.search(
        rf"(?:{label})\s*(?:ltm|за\s+последние\s+12\s+месяцев)?\s*(?:составил[аио]?|was|of|:|=)?\s*"
        r"(?:(USD|EUR|RUB|\$|€|₽)\s*)?(\d+(?:[.,]\d+)?)\s*"
        r"(трлн|trillion|млрд|billion|млн|million)?\s*"
        r"(руб(?:лей|ля|\.)?|rub|usd|доллар\w*|eur|евро|₽|\$|€)?",
        text,
        re.I,
    )
    if not match:
        return None, ""
    number = float(match.group(2).replace(",", "."))
    unit = (match.group(3) or "").lower()
    multiplier = 1_000_000_000_000 if unit in {"трлн", "trillion"} else 1_000_000_000 if unit in {"млрд", "billion"} else 1_000_000 if unit in {"млн", "million"} else 1
    token = f"{match.group(1) or ''} {match.group(4) or ''}".upper()
    currency = "USD" if "$" in token or "USD" in token or "ДОЛЛАР" in token else "EUR" if "€" in token or "EUR" in token or "ЕВРО" in token else "RUB"
    return number * multiplier, currency


def _has_explicit_transaction_value(text: str) -> bool:
    amount = r"(?:(?:USD|EUR|RUB|\$|€|₽)\s*)?\d+(?:[.,]\d+)?\s*(?:трлн|trillion|млрд|billion|млн|million)?\s*(?:руб\w*|rub|usd|доллар\w*|eur|евро|₽|\$|€)?"
    return bool(re.search(rf"(?:transaction value|deal value|consideration|стоимость сделки|цена сделки)\s*(?:was|is|составил[аио]?|:|=)?\s*{amount}|\sза\s+{amount}", text, re.I))


def _payment_form(text: str) -> str:
    lowered = text.lower()
    cash = bool(re.search(r"\b(cash|денежн\w*\s+средств|за\s+наличн)\b", lowered))
    shares = bool(re.search(r"\b(shares?|stock|акци\w*|обмен\w*\s+акци)\b", lowered))
    if cash and shares:
        return "Cash and shares"
    if cash:
        return "Cash"
    if shares:
        return "Shares"
    return "Not disclosed"


def _advisors(text: str) -> str:
    match = re.search(
        r"(?:financial\s+advisor|legal\s+advisor|advisor|консультант(?:ом|ами)?|советник(?:ом|ами)?)\s*(?:выступил[аи]?|was|is|:)?\s*([^.;]+)",
        text,
        re.I,
    )
    return _clean_party(match.group(1))[:180] if match else "Not disclosed"


def _financials_as_of(text: str) -> str:
    match = re.search(r"(?:ltm|за\s+12\s+месяцев|за\s+(?:20)?\d{2}\s+год|as\s+of)\s*([^.;,]{0,30})", text, re.I)
    return match.group(0).strip()[:60] if match else "Not disclosed"


def median_multiples(rows: list[dict]) -> dict[str, float | int | None]:
    def values(field: str) -> list[float]:
        result = sorted(float(row[field]) for row in rows if row.get("deal_type") == "M&A" and isinstance(row.get(field), (int, float)) and row[field] > 0)
        return result
    def median(items: list[float]) -> float | None:
        if not items:
            return None
        middle = len(items) // 2
        return items[middle] if len(items) % 2 else (items[middle - 1] + items[middle]) / 2
    revenue = values("ev_revenue")
    ebitda = values("ev_ebitda")
    return {"ev_revenue": median(revenue), "ev_ebitda": median(ebitda), "coverage": len(set(id(row) for row in rows if row.get("ev_revenue") or row.get("ev_ebitda")))}


def _is_blank(value) -> bool:
    return value is None or value == "" or value == "Not disclosed"


def _extract_stake(text: str) -> float | None:
    match = re.search(r"(?:пакет\s+|stake\s+of\s+|покупк\w*\s+)?(\d+(?:[.,]\d+)?)\s*%", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def _status(text: str, category: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("закрыл", "завершил", "completed", "closed")):
        return "Completed"
    if category in {"ECM", "DCM"} and any(word in lowered for word in ("разместил", "выпустил", "priced", "issued")):
        return "Issued"
    if any(word in lowered for word in ("рассматрива", "может", "evaluates", "considers", "explores")):
        return "Potential"
    if any(word in lowered for word in ("объявил", "announced", "планирует", "разместит")):
        return "Announced"
    return "Reported"


def _instrument(text: str, category: str) -> str:
    lowered = text.lower()
    if category == "M&A":
        return "Acquisition / disposal"
    if "ipo" in lowered:
        return "IPO"
    if any(word in lowered for word in ("spo", "secondary", "вторичн")):
        return "Secondary share placement"
    if any(word in lowered for word in ("облигац", "bond", "notes")):
        return "Bonds"
    return "Equity issuance" if category == "ECM" else "Debt financing"


def _sector(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("technology", "технолог", "cloud", "облач", "digital", "интернет")):
        return "Technology"
    if any(word in lowered for word in ("банк", "bank", "insurance", "страхов")):
        return "Financials"
    if any(word in lowered for word in ("нефт", "газ", "oil", "energy")):
        return "Energy"
    return "Not classified"


def _rationale(text: str) -> str:
    match = re.search(r"(?:to|для|чтобы)\s+(.+?)(?:[.;]|$)", text, re.I)
    if not match:
        return "Not disclosed"
    value = re.split(r"\s+[—-]\s+", match.group(1).strip(), maxsplit=1)[0]
    if "@" in value or sum(character.isdigit() for character in value) >= 6:
        return "Not disclosed"
    return value[:240]


def _iso_date(value: str) -> str:
    try:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = parsedate_to_datetime(value)
        return parsed.date().isoformat()
    except (TypeError, ValueError):
        return ""


def _safe_public_url(value: str) -> str:
    try:
        parsed = urlparse(str(value).strip())
        return str(value).strip() if parsed.scheme in {"http", "https"} and parsed.netloc else ""
    except (TypeError, ValueError):
        return ""
