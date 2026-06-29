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
    "ev_revenue", "ev_ebitda", "instrument", "rationale", "quality_status",
    "quality_score", "quality_flags", "source_count", "sources", "score",
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
    status = _status(text, item.category, item.evidence_label)
    if status == "Denied":
        value, currency = None, ""
        enterprise_value, ev_currency = None, ""
    source = {
        "name": event.source.strip() or "Unknown source",
        "url": _safe_public_url(event.url),
        "evidence_label": item.evidence_label,
        "source_type": event.source_type,
        "published_at": event.published_at,
    }
    quality_score, quality_status, quality_flags = _quality_gate({
        "deal_type": item.category,
        "status": status,
        "headline": event.title.strip(),
        "summary": event.summary,
        "target_or_issuer": target,
        "acquirer_or_investor": acquirer,
        "transaction_value": value,
        "currency": currency,
        "evidence_label": item.evidence_label,
        "source_url": source["url"],
        "source_count": 1,
    })
    return DealRecord(
        deal_id=f"DL-{event.event_id}",
        announced_date=_iso_date(event.published_at),
        deal_type=item.category,
        status=status,
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
        quality_status=quality_status,
        quality_score=quality_score,
        quality_flags=quality_flags,
        sources=[source],
        source_count=1,
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
    existing = [_migrate_row(row) for row in _load_database(destination)]
    by_id = {row.get("deal_id"): row for row in existing if row.get("deal_id")}
    for record in records:
        row = _migrate_row(record.to_dict())
        old = by_id.get(record.deal_id)
        if old:
            row["first_seen_at"] = old.get("first_seen_at", row["first_seen_at"])
            if "news.google.com/rss/articles/" in str(row.get("source_url") or "") and "news.google.com" not in str(old.get("source_url") or ""):
                row["source_url"] = old["source_url"]
            for field in (
                "enterprise_value", "payment_form", "advisors", "revenue_ltm", "ebitda_ltm",
                "financials_as_of", "financials_currency", "ev_revenue", "ev_ebitda", "notes",
            ):
                if _is_blank(row.get(field)) and not _is_blank(old.get(field)):
                    row[field] = old[field]
            row["sources"] = _merge_sources(old.get("sources", []), row.get("sources", []))
            row["source_count"] = len(row["sources"])
            _apply_primary_source(row)
            _apply_quality(row)
        by_id[record.deal_id] = row
    by_source: dict[tuple[str, str], dict] = {}
    for row in by_id.values():
        key = (row.get("source_url") or row.get("deal_id"), _normalize_headline(row.get("headline", "")))
        old = by_source.get(key)
        if old is None or row.get("last_seen_at", "") >= old.get("last_seen_at", ""):
            by_source[key] = row
    clusters: list[dict] = []
    candidates = sorted(
        (row for row in by_source.values() if not _is_navigation_record(row)),
        key=lambda row: (row.get("announced_date", ""), row.get("score", 0)), reverse=True,
    )
    for row in candidates:
        duplicate_index = next((index for index, current in enumerate(clusters) if _same_transaction(row, current)), None)
        if duplicate_index is None:
            clusters.append(row)
        else:
            clusters[duplicate_index] = _merge_transaction_rows(clusters[duplicate_index], row)
    output = sorted(clusters, key=lambda row: (row.get("announced_date", ""), row.get("score", 0)), reverse=True)
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
            row["quality_flags"] = ", ".join(row.get("quality_flags", []))
            row["sources"] = json.dumps(row.get("sources", []), ensure_ascii=False, separators=(",", ":"))
            writer.writerow(row)
    return destination


def select_key_deals(rows: list[dict], limit: int = 10) -> list[dict]:
    """Return material transaction records, excluding technical exchange notices."""
    selected: list[dict] = []
    for row in rows:
        if row.get("quality_status") == "rejected":
            continue
        category = row.get("deal_type")
        if not _is_material_transaction(row):
            continue
        target = row.get("target_or_issuer")
        acquirer = row.get("acquirer_or_investor")
        disclosed_party = target not in {None, "", "Not disclosed"} or acquirer not in {None, "", "Not disclosed", "Not applicable"}
        if category == "M&A" and disclosed_party:
            selected.append(row)
        elif category in {"ECM", "DCM"} and target not in {None, "", "Not disclosed"} and (
            row.get("transaction_value") or row.get("status") in {"Announced", "Issued", "Closed", "Confirmed"}
        ):
            selected.append(row)
    clusters: list[dict] = []
    for row in selected:
        duplicate_index = next((index for index, current in enumerate(clusters) if _same_transaction(row, current)), None)
        if duplicate_index is None:
            clusters.append(row)
        elif _record_quality(row) > _record_quality(clusters[duplicate_index]):
            clusters[duplicate_index] = row
    clusters.sort(key=lambda row: (
        row.get("announced_date", ""),
        1 if row.get("quality_status") == "approved" else 0,
        row.get("quality_score", 0),
        row.get("score", 0),
    ), reverse=True)
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
        {"approved": 2, "review": 1, "rejected": 0}.get(row.get("quality_status"), 0),
        int(row.get("quality_score") or 0),
        (1 if row.get("evidence_label") == "confirmed" else 0) * 100
        + int(row.get("score") or 0) * 10
        + (1 if row.get("transaction_value") else 0),
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
    common = a & b
    if len(common) >= 2:
        return True
    left_amount, right_amount = left.get("transaction_value"), right.get("transaction_value")
    same_amount = bool(
        left_amount and right_amount
        and abs(float(left_amount) - float(right_amount)) / max(float(left_amount), float(right_amount)) <= 0.02
    )
    left_tokens, right_tokens = _headline_tokens(left.get("headline", "")), _headline_tokens(right.get("headline", ""))
    similarity = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens)) if left_tokens and right_tokens else 0
    same_day_sale = bool(
        common
        and left.get("announced_date") == right.get("announced_date")
        and re.search(r"продал|продаж|sold|divest", str(left.get("headline") or ""), re.I)
        and re.search(r"продал|продаж|sold|divest", str(right.get("headline") or ""), re.I)
    )
    return bool(common and (same_amount or similarity >= 0.6 or same_day_sale))


def _deal_entities(value: str) -> set[str]:
    aliases = {
        "авто.ру": "auto.ru", "auto.ru": "auto.ru", "яндекс": "yandex", "yandex": "yandex",
        "т-технолог": "t-tech", "технологиям": "t-tech", "ozon": "ozon", "озон": "ozon",
        "сбер": "sber", "афк": "afk-system", "система": "afk-system", "остров": "ostrovok",
        "норникел": "nornickel", "selectel": "selectel", "втб": "vtb", "vk": "vk",
        "nebius": "nebius", "eigen": "eigen", "мтс": "mts", "mts": "mts",
        "точка": "tochka", "авито": "avito", "flamboyan": "flamboyan",
    }
    lowered = value.lower()
    return {canonical for token, canonical in aliases.items() if token in lowered}


def _headline_tokens(value: str) -> set[str]:
    stop = {
        "the", "and", "for", "with", "from", "что", "для", "при", "или", "как", "это",
        "сделка", "сделку", "сделки", "сообщил", "сообщила", "компания", "группа", "group",
    }
    return {token for token in re.findall(r"[a-zа-яё0-9]+", str(value).lower()) if len(token) >= 3 and token not in stop}


def _normalize_headline(value: str) -> str:
    return " ".join(sorted(_headline_tokens(value)))


def _amount_has_transaction_context(context: str) -> bool:
    return bool(re.search(
        r"стоимост\w*\s+сделк|цена\s+сделк|сумм\w*\s+сделк|deal value|transaction value|consideration|"
        r"купил\w*\s+за|покупк\w*\s+за|приобр[её]л\w*\s+за|продал\w*\s+за|acqui\w*\s+for|bought\s+for",
        context, re.I,
    ))


def _quality_gate(row: dict) -> tuple[int, str, list[str]]:
    text = f"{row.get('headline','')}. {row.get('summary','')}".lower()
    category = row.get("deal_type")
    score = 100
    flags: list[str] = []

    material_probe = dict(row)
    material_probe["headline"] = row.get("headline", "")
    if not _is_material_transaction(material_probe):
        score -= 60
        flags.append("non_transaction_or_technical_notice")
    if row.get("evidence_label") != "confirmed":
        score -= 25
        flags.append("unverified_source")
    if "news.google.com" in str(row.get("source_url") or ""):
        score -= 8
        flags.append("aggregator_link")

    target = row.get("target_or_issuer")
    acquirer = row.get("acquirer_or_investor")
    if category == "M&A":
        missing_target = _is_blank(target)
        missing_acquirer = _is_blank(acquirer) or acquirer == "Not applicable"
        if missing_target and missing_acquirer:
            score -= 35
            flags.append("missing_both_parties")
        else:
            if missing_target:
                score -= 15
                flags.append("missing_target")
            if missing_acquirer:
                score -= 15
                flags.append("missing_acquirer")
    elif _is_blank(target):
        score -= 25
        flags.append("missing_issuer")

    if re.search(r"price target|target price|stock price|share price|целева\w*\s+цен|таргет|цена акци", text):
        score -= 40
        flags.append("price_target_context")
    value = row.get("transaction_value")
    if category == "M&A" and isinstance(value, (int, float)) and value < 1_000_000:
        score -= 45
        flags.append("suspicious_small_transaction_value")
    if row.get("status") == "Rumor":
        score -= 8
        flags.append("rumor_only")
    if row.get("status") == "Denied":
        score -= 10
        flags.append("denied_or_disputed")

    score = max(0, min(100, score))
    status = "rejected" if score < 40 else "review" if score < 75 else "approved"
    if row.get("evidence_label") != "confirmed" and status == "approved":
        status = "review"
    return score, status, flags


def _migrate_row(source: dict) -> dict:
    row = dict(source)
    legacy_status = row.get("status")
    if legacy_status == "Completed":
        row["status"] = "Closed"
    elif legacy_status == "Potential":
        row["status"] = "In talks"
    elif legacy_status == "Reported":
        row["status"] = "Confirmed" if row.get("evidence_label") == "confirmed" else "Reported"

    headline = str(row.get("headline") or "")
    inferred_status = _status(headline, row.get("deal_type", ""), row.get("evidence_label", "unverified"))
    if inferred_status in {"Denied", "Closed", "Issued", "In talks", "Announced"} or row.get("status") not in {"Denied", "Closed", "Issued", "In talks", "Announced", "Confirmed", "Reported", "Rumor"} or (row.get("status") == "Rumor" and inferred_status == "Reported"):
        row["status"] = inferred_status
    if row.get("status") == "Denied":
        row["transaction_value"] = None
        row["enterprise_value"] = None
        row["currency"] = "Not disclosed"
    if row.get("deal_type") == "M&A" and re.search(
        r"price target|target price|stock price|share price|целева\w*\s+цен|таргет|цена акци", headline, re.I,
    ):
        if isinstance(row.get("transaction_value"), (int, float)) and row["transaction_value"] < 1_000_000:
            row["transaction_value"] = None
            row["currency"] = "Not disclosed"
        if str(row.get("acquirer_or_investor") or "").isupper() and str(row.get("acquirer_or_investor")) not in headline:
            row["acquirer_or_investor"] = "Not disclosed"
        if str(row.get("rationale") or "").startswith(("$", "€", "₽")):
            row["rationale"] = "Not disclosed"
    if row.get("deal_type") == "M&A":
        parsed_target, parsed_acquirer = _extract_parties("M&A", headline, "Not disclosed")
        if not _is_blank(parsed_target):
            row["target_or_issuer"] = parsed_target
        if not _is_blank(parsed_acquirer):
            row["acquirer_or_investor"] = parsed_acquirer
        elif re.search(r"продал|продаж|sold|divest", headline, re.I):
            row["acquirer_or_investor"] = "Not disclosed"
    if _is_generic_party(row.get("target_or_issuer")):
        row["target_or_issuer"] = "Not disclosed"

    row["sources"] = _merge_sources(row.get("sources", []), [{
        "name": row.get("source_name", "Unknown source"),
        "url": row.get("source_url", ""),
        "evidence_label": row.get("evidence_label", "unverified"),
        "source_type": row.get("source_type", "public_web"),
        "published_at": row.get("announced_date", ""),
    }])
    row["source_count"] = len(row["sources"])
    row.setdefault("quality_flags", [])
    _apply_primary_source(row)
    _apply_quality(row)
    return row


def _is_generic_party(value) -> bool:
    return bool(re.match(
        r"^(?:о регистрации|о порядке|о проведении|дополнительные условия|информация|сообщение|уведомление)",
        str(value or "").strip(), re.I,
    ))


def _merge_sources(*source_groups: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for source in (item for group in source_groups for item in (group or [])):
        if not isinstance(source, dict):
            continue
        url = _safe_public_url(source.get("url", ""))
        name = str(source.get("name") or "Unknown source").strip()
        key = (url, name.lower())
        candidate = {
            "name": name,
            "url": url,
            "evidence_label": source.get("evidence_label", "unverified"),
            "source_type": source.get("source_type", "public_web"),
            "published_at": source.get("published_at", ""),
        }
        current = merged.get(key)
        if current is None or _source_quality(candidate) > _source_quality(current):
            merged[key] = candidate
    return sorted(merged.values(), key=_source_quality, reverse=True)


def _source_quality(source: dict) -> tuple[int, int, int]:
    source_type = str(source.get("source_type") or "")
    return (
        1 if source.get("evidence_label") == "confirmed" else 0,
        1 if source_type in {"issuer_ir", "official_ir", "regulator", "exchange", "official_exchange", "sec_filing", "official"} else 0,
        1 if "news.google.com" not in str(source.get("url") or "") else 0,
    )


def _apply_primary_source(row: dict) -> None:
    sources = row.get("sources", [])
    if not sources:
        return
    primary = max(sources, key=_source_quality)
    row["source_name"] = primary.get("name", "Unknown source")
    row["source_url"] = primary.get("url", "")
    row["evidence_label"] = "confirmed" if any(source.get("evidence_label") == "confirmed" for source in sources) else "unverified"


def _apply_quality(row: dict) -> None:
    score, status, flags = _quality_gate(row)
    row["quality_score"] = score
    row["quality_status"] = status
    row["quality_flags"] = flags


def _merge_transaction_rows(left: dict, right: dict) -> dict:
    winner, other = (left, right) if _record_quality(left) >= _record_quality(right) else (right, left)
    merged = dict(winner)
    for field in (
        "target_or_issuer", "acquirer_or_investor", "transaction_value", "enterprise_value", "currency",
        "stake_percent", "payment_form", "advisors", "rationale", "revenue_ltm", "ebitda_ltm",
        "financials_as_of", "financials_currency", "ev_revenue", "ev_ebitda", "sector", "geography",
    ):
        if _is_blank(merged.get(field)) or merged.get(field) == "Not applicable":
            if not _is_blank(other.get(field)):
                merged[field] = other[field]
    merged["sources"] = _merge_sources(left.get("sources", []), right.get("sources", []))
    merged["source_count"] = len(merged["sources"])
    merged["matched_coverage"] = sorted(set(left.get("matched_coverage", [])) | set(right.get("matched_coverage", [])))
    merged["first_seen_at"] = min(value for value in (left.get("first_seen_at"), right.get("first_seen_at")) if value)
    merged["last_seen_at"] = max(left.get("last_seen_at", ""), right.get("last_seen_at", ""))
    status_rank = {"Rumor": 0, "Reported": 1, "In talks": 2, "Confirmed": 3, "Announced": 4, "Issued": 5, "Closed": 6, "Denied": 7}
    merged["status"] = max((left.get("status", "Rumor"), right.get("status", "Rumor")), key=lambda value: status_rank.get(value, 0))
    if merged["status"] == "Denied":
        merged["transaction_value"] = None
        merged["enterprise_value"] = None
        merged["currency"] = "Not disclosed"
    _apply_primary_source(merged)
    _apply_quality(merged)
    return merged


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
    disposal_patterns = [
        r"^(.+?)\s+закрыл\w*\s+сделк\w*\s+по\s+продаж\w*\s+(.+?)(?:\s+за\s+|:|$)",
        r"^(.+?)\s+(?:продал\w*|sold|divested)\s+(?:свою\s+)?(?:\d+(?:[.,]\d+)?%\s+)?(?:акци\w*|дол\w*|stake\s+in|shares?\s+of)?\s*(?:в\s+)?(.+?)(?:\s+за\s+|:|$)",
    ]
    for pattern in disposal_patterns:
        match = re.search(pattern, clean, re.I)
        if match:
            return _clean_party(match.group(2)), "Not disclosed"
    contextual_patterns = [
        r"договоренност\w*\s+(.+?)\s+о\s+покупк\w*\s+(?:дол\w*\s+в\s+)?(.+?)(?:\s+[—-]\s+|$)",
        r"^(.+?)\s+(?:стал\w*\s+)?(?:основн\w*\s+)?претендент\w*\s+на\s+покупк\w*\s+(.+?)(?:\s+[—-]\s+|$)",
    ]
    for pattern in contextual_patterns:
        match = re.search(pattern, clean, re.I)
        if match:
            return _clean_party(match.group(2)), _clean_party(match.group(1))
    patterns = [
        r"^(.+?)\s+(?:закрыл\w*\s+сделк\w*\s+по\s+покупке|приобр[её]л\w*|купил\w*)\s+(.+?)(?:\s+у\s+|\s+за\s+|$)",
        r"^(.+?)\s+(?:announces|evaluates|considers)?\s*acquisition of\s+(.+?)(?:\s+for\s+|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean, re.I)
        if match:
            return _clean_party(match.group(2)), _clean_party(match.group(1))
    return "Not disclosed", "Not disclosed"


def _leading_entity(title: str) -> str:
    if _is_generic_party(title):
        return "Not disclosed"
    quoted = re.match(r"^[«\"]([^»\"]+)[»\"]", title)
    if quoted:
        return quoted.group(1).strip()
    words = re.split(r"\s+(?:размест|выпуст|планир|рассматрива|considers|explores|announces)\w*", title, maxsplit=1, flags=re.I)
    return _clean_party(words[0]) if words and len(words[0]) <= 80 else "Not disclosed"


def _clean_party(value: str) -> str:
    cleaned = value.strip(" \"'«».,:;")[:100]
    aliases = [
        (r"^сбер\w*$", "Sber"), (r"^озон\w*$", "Ozon"), (r"^яндекс\w*$", "Yandex"),
        (r"^авто\.ру$", "Авто.ру"), (r"^остров\w*$", "Островок"),
    ]
    for pattern, canonical in aliases:
        if re.match(pattern, cleaned, re.I):
            return canonical
    return cleaned or "Not disclosed"


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
        context = text[max(0, match.start() - 45):min(len(text), match.end() + 45)].lower()
        if re.search(r"price target|target price|stock price|share price|целева\w*\s+цен|таргет|цена акци", context):
            continue
        number = float(match.group(2).replace(",", "."))
        multiplier = 1_000_000_000_000 if unit in {"трлн", "trillion"} else 1_000_000_000 if unit in {"млрд", "billion"} else 1_000_000 if unit in {"млн", "million"} else 1
        if multiplier == 1 and number < 1_000_000 and not _amount_has_transaction_context(context):
            continue
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


def _is_navigation_record(row: dict) -> bool:
    headline = str(row.get("headline") or "").strip().lower()
    return row.get("source_name") in {"MTS Investor Relations"} and headline in {"облигации", "еврооблигации 2023"}


def _extract_stake(text: str) -> float | None:
    match = re.search(r"(?:пакет\s+|stake\s+of\s+|покупк\w*\s+)?(\d+(?:[.,]\d+)?)\s*%", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def _status(text: str, category: str, evidence_label: str = "unverified") -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("опроверг", "не подтверди", "denied", "denies", "no agreement")):
        return "Denied"
    if any(word in lowered for word in ("закрыл", "закрыла", "завершил", "завершила", "completed", "closed")):
        return "Closed"
    if category in {"ECM", "DCM"} and any(word in lowered for word in ("разместил", "выпустил", "priced", "issued")):
        return "Issued"
    if any(word in lowered for word in ("переговор", "договарива", "negotiat", "in talks", "ведет обсужден")):
        return "In talks"
    if any(word in lowered for word in ("слух", "сообщил о возмож", "может купить", "может приобрести", "rumor", "reportedly", "potential bidder", "претендент")):
        return "Rumor"
    if any(word in lowered for word in ("объявил", "анонсировал", "announced", "планирует", "разместит")):
        return "Announced"
    return "Confirmed" if evidence_label == "confirmed" else "Reported"


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
