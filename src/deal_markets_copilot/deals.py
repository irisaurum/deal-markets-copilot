from __future__ import annotations

import csv
import json
import re
from datetime import date, timedelta
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from .models import ClassifiedEvent, DealRecord
from .classifier import is_technical_exchange_notice


DEAL_CATEGORIES = {"M&A", "ECM", "DCM"}
OFFICIAL_SOURCE_TYPES = {
    "issuer_ir", "official_ir", "official_issuer", "regulator", "official_regulator",
    "exchange", "official_exchange", "sec_filing", "official",
}
CSV_FIELDS = [
    "deal_id", "announced_date", "deal_type", "record_kind", "status", "target_or_issuer",
    "acquirer_or_investor", "seller", "sector", "geography", "transaction_value",
    "enterprise_value", "currency", "stake_percent", "payment_form", "advisors",
    "revenue_ltm", "ebitda_ltm", "financials_as_of", "financials_currency",
    "financials_available_at", "operating_income", "depreciation", "amortization",
    "financials_metric_basis", "financials_source_name",
    "financials_source_url", "ev_revenue", "ev_ebitda", "multiple_eligible", "multiple_notes",
    "instrument", "security_code", "isin", "coupon_rate",
    "coupon_type", "yield_rate", "maturity_date", "tenor", "issue_price",
    "price_per_share", "discount_percent", "bookrunners", "free_float_percent",
    "rationale", "quality_status",
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
    headline = _clean_headline(event.title)
    covered_company = _covered_company(item, coverage)
    enterprise_value, ev_currency = _extract_labeled_amount(text, ("enterprise value", "ev", "стоимость предприятия"))
    if event.amount:
        value, currency = event.amount, event.currency or ""
    elif item.category == "DCM":
        value, currency = _extract_dcm_volume(text)
        if value is None:
            value, currency = _extract_amount(text)
    else:
        value, currency = _extract_amount(text)
    if item.category == "M&A" and enterprise_value == value and not _has_explicit_transaction_value(text):
        value, currency = None, ""
    revenue, revenue_currency = _extract_labeled_amount(text, ("revenue", "выручка"))
    ebitda, ebitda_currency = _extract_labeled_amount(text, ("ebitda", "ебитда"))
    financials_currency = revenue_currency or ebitda_currency or ""
    aligned_currency = bool(enterprise_value and financials_currency and ev_currency == financials_currency)
    target, acquirer = _extract_parties(item.category, headline, covered_company)
    if item.category in {"DCM", "ECM"} and _is_blank(target):
        target = _extract_issuer(text)
    seller = _extract_seller(headline) if item.category == "M&A" else "Not applicable"
    status = _status(text, item.category, item.evidence_label)
    record_kind = _record_kind({
        "headline": headline,
        "summary": event.summary,
        "deal_type": item.category,
        "status": status,
        "evidence_label": item.evidence_label,
        "source_type": event.source_type,
    })
    if status == "Denied":
        value, currency = None, ""
        enterprise_value, ev_currency = None, ""
    resolved_discovery = bool(event.discovery_url and event.discovery_url != event.url)
    source = {
        "name": event.source.strip() or "Unknown source",
        "url": _safe_public_url(event.url),
        "evidence_label": item.evidence_label,
        "source_type": "public_web" if resolved_discovery else event.source_type,
        "published_at": event.published_at,
        "title": event.title,
    }
    if resolved_discovery:
        source["representations"] = [
            {
                "name": source["name"], "url": source["url"],
                "source_type": source["source_type"], "published_at": source["published_at"],
            },
            {
                "name": source["name"], "url": _safe_public_url(event.discovery_url),
                "source_type": event.source_type, "published_at": source["published_at"],
            },
        ]
    quality_score, quality_status, quality_flags = _quality_gate({
        "deal_type": item.category,
        "record_kind": record_kind,
        "status": status,
        "headline": headline,
        "summary": event.summary,
        "target_or_issuer": target,
        "acquirer_or_investor": acquirer,
        "transaction_value": value,
        "currency": currency,
        "evidence_label": item.evidence_label,
        "source_url": source["url"],
        "source_count": 1,
        "sources": [source],
    })
    return DealRecord(
        deal_id=f"DL-{event.event_id}",
        announced_date=_iso_date(event.published_at),
        deal_type=item.category,
        record_kind=record_kind,
        status=status,
        target_or_issuer=target,
        acquirer_or_investor=acquirer,
        seller=seller,
        sector=_sector(text),
        geography="Russia" if re.search(r"\b(руб|росси|москва|moex)\w*", text, re.I) else "Not disclosed",
        headline=headline,
        transaction_value=float(value) if value is not None else None,
        enterprise_value=enterprise_value,
        currency=_normalize_currency(currency),
        stake_percent=_extract_stake(text) if item.category == "M&A" else None,
        payment_form=_payment_form(text) if item.category == "M&A" else "Not applicable",
        advisors=_advisors(text),
        revenue_ltm=revenue,
        ebitda_ltm=ebitda,
        financials_as_of=_financials_as_of(text),
        financials_currency=financials_currency or "Not disclosed",
        financials_available_at="Not disclosed",
        financials_metric_basis="Headline extraction" if revenue or ebitda else "Not disclosed",
        financials_source_name=event.source.strip() if revenue or ebitda else "Not disclosed",
        financials_source_url=_safe_public_url(event.url) if revenue or ebitda else "",
        ev_revenue=(enterprise_value / revenue) if aligned_currency and revenue and revenue > 0 else None,
        ev_ebitda=(enterprise_value / ebitda) if aligned_currency and ebitda and ebitda > 0 else None,
        multiple_notes="Calculated from disclosed EV and aligned-currency financials" if aligned_currency else "N/M: EV and aligned-currency financials are required",
        instrument=_instrument(text, item.category),
        security_code=_security_code(text),
        isin=_isin(text),
        coupon_rate=_coupon_rate(text),
        coupon_type=_coupon_type(text),
        yield_rate=_yield_rate(text),
        maturity_date=_maturity_date(text),
        tenor=_tenor(text),
        issue_price=_issue_price(text) if item.category == "DCM" else None,
        price_per_share=_price_per_share(text) if item.category == "ECM" else None,
        discount_percent=_discount_percent(text) if item.category == "ECM" else None,
        bookrunners=_bookrunners(text) if item.category == "ECM" else "Not applicable",
        free_float_percent=_free_float(text) if item.category == "ECM" else None,
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
            if old.get("deal_type") == row.get("deal_type") == "DCM":
                row["security_code"] = _merge_dcm_security_codes(old.get("security_code"), row.get("security_code"))
                row["isin"] = _merge_dcm_scalar_identity(old.get("isin"), row.get("isin"))
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


def load_public_dataset(path: str | Path) -> list[dict]:
    """Load a version-controlled public JSON dataset without accepting other shapes."""
    return [_migrate_row(row) for row in _load_database(Path(path)) if isinstance(row, dict)]


def merge_curated_precedents(rows: list[dict], curated_rows: list[dict]) -> list[dict]:
    """Merge analyst-reviewed precedents by stable deal id and retain their primary sources."""
    merged = {row.get("deal_id"): _migrate_row(row) for row in rows if row.get("deal_id")}
    for source in curated_rows:
        row = _migrate_row(source)
        deal_id = row.get("deal_id")
        if not deal_id:
            continue
        if deal_id in merged:
            row = _merge_transaction_rows(merged[deal_id], row)
        _apply_primary_source(row)
        _apply_quality(row)
        merged[deal_id] = row
    return sorted(merged.values(), key=lambda row: (row.get("announced_date", ""), row.get("score", 0)), reverse=True)


def enrich_precedent_financials(rows: list[dict], financial_rows: list[dict]) -> list[dict]:
    """Attach audited financial inputs and calculate multiples only when units and currencies align."""
    by_deal = {str(item.get("deal_id")): item for item in financial_rows if item.get("deal_id")}
    enriched: list[dict] = []
    for source in rows:
        row = _migrate_row(source)
        financial = by_deal.get(str(row.get("deal_id")))
        if not financial:
            row["ev_revenue"] = _valid_multiple(row.get("enterprise_value"), row.get("revenue_ltm"), row.get("currency"), row.get("financials_currency"))
            row["ev_ebitda"] = _valid_multiple(row.get("enterprise_value"), row.get("ebitda_ltm"), row.get("currency"), row.get("financials_currency"))
            row["multiple_eligible"] = _multiple_is_eligible(row)
            enriched.append(row)
            continue
        revenue = _positive_number(financial.get("revenue"))
        ebitda = _positive_number(financial.get("ebitda"))
        currency = _normalize_currency(financial.get("currency"))
        row.update({
            "revenue_ltm": revenue,
            "ebitda_ltm": ebitda,
            "operating_income": _positive_number(financial.get("operating_income")),
            "depreciation": _positive_number(financial.get("depreciation")),
            "amortization": _positive_number(financial.get("amortization")),
            "financials_as_of": financial.get("period_end") or "Not disclosed",
            "financials_available_at": financial.get("available_at") or "Not disclosed",
            "financials_currency": currency,
            "financials_metric_basis": financial.get("metric_basis") or "Not disclosed",
            "financials_source_name": financial.get("source_name") or "Not disclosed",
            "financials_source_url": _safe_public_url(financial.get("source_url", "")),
        })
        row["ev_revenue"] = _valid_multiple(row.get("enterprise_value"), revenue, row.get("currency"), currency)
        row["ev_ebitda"] = _valid_multiple(row.get("enterprise_value"), ebitda, row.get("currency"), currency)
        available_after_announcement = bool(
            row.get("announced_date") and financial.get("available_at")
            and str(financial["available_at"]) > str(row["announced_date"])
        )
        row["multiple_notes"] = (
            "Calculated from disclosed EV and audited financials; report became available after announcement"
            if available_after_announcement else
            "Calculated from disclosed EV and latest audited financials available at announcement"
        )
        row["multiple_eligible"] = _multiple_is_eligible(row) and not available_after_announcement
        financial_source = {
            "name": row["financials_source_name"],
            "url": row["financials_source_url"],
            "evidence_label": "confirmed",
            "source_type": "sec_filing",
            "published_at": row["financials_available_at"],
        }
        row["sources"] = _merge_sources(row.get("sources", []), [financial_source])
        row["source_count"] = len(row["sources"])
        enriched.append(row)
    return enriched


def write_precedent_database(rows: list[dict], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


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
    """Return recent live deal flow; historical curated precedents stay analytical-only."""
    selected: list[dict] = []
    for row in rows:
        if not _is_recent_live_record(row):
            continue
        if row.get("record_kind") not in {None, "deal"}:
            continue
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
            row.get("transaction_value") or row.get("status") in {"Announced", "Priced", "Issued", "Confirmed"}
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


def _is_recent_live_record(row: dict, max_age_days: int = 365) -> bool:
    if str(row.get("deal_id") or "").startswith("CURATED-"):
        return False
    announced = str(row.get("announced_date") or "")[:10]
    try:
        announced_date = date.fromisoformat(announced)
    except ValueError:
        return False
    from zoneinfo import ZoneInfo
    moscow_today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    return announced_date >= moscow_today - timedelta(days=max_age_days)


def select_deal_buckets(rows: list[dict], limit: int = 10) -> dict[str, list[dict]]:
    """Build mutually exclusive UI streams with transactions separated from monitoring items."""
    migrated = [_migrate_row(row) for row in rows]
    deals = select_key_deals(migrated, limit)
    result = {"deal": deals, "watchlist": [], "denial": [], "technical_filing": []}
    for kind in ("watchlist", "denial", "technical_filing"):
        candidates = [
            row for row in migrated
            if row.get("record_kind") == kind
            and row.get("quality_status") != "rejected"
            and _is_recent_live_record(row)
            and (kind != "watchlist" or _is_watchlist_candidate(row))
        ]
        candidates.sort(key=lambda row: (
            row.get("announced_date", ""),
            row.get("quality_score", 0),
            row.get("score", 0),
        ), reverse=True)
        result[kind] = candidates[:limit]
    return result


def _is_watchlist_candidate(row: dict) -> bool:
    """Keep the review stream focused on transaction claims, not routine issuance news."""
    return row.get("deal_type") == "M&A" and _is_material_transaction(row)


def _is_material_transaction(row: dict) -> bool:
    title = str(row.get("headline") or "").lower()
    category = row.get("deal_type")
    if re.search(r"\b(?:бпиф|ипиф|пиф)\b|инвестиционн\w*\s+па[йё]|аукцион\w*.+\bофз\b|\bофз\b.+аукцион", title):
        return False
    if category == "M&A":
        if "последний день покупки акций" in title:
            return False
        return bool(re.search(r"покуп|куп|приобрет|продал|продаж|слиян|поглощ|acquir|acquisition|merger|buyout", title))
    if category == "DCM":
        if _is_technical_filing(title, str(row.get("source_type") or "")):
            return False
        if re.search(r"погашен|погашения|перечислил.+погаш|заработай", title):
            return False
        if re.search(r"разбор|чего ждать|инвестор\w*.+(?:вложен|вклад)|как заработать", title):
            return False
        if re.search(r"выкуп", title) and not re.search(r"размещ|анонс|план", title):
            return False
        return bool(re.search(r"размещ|выпуск|облигац|bond|notes", title))
    if category == "ECM":
        if re.search(r"объем (?:ipo|продаж акций)|рынок ipo|полугоди|квартал|рекордн|обзор", title):
            return False
        if re.search(r"выкуп акций|buyback", title):
            return False
        return bool(re.search(r"\bipo\b|\bspo\b|размещ|эмисси", title))
    return False


def _record_kind(row: dict) -> str:
    text = f"{row.get('headline','')}. {row.get('summary','')}".lower()
    if row.get("status") == "Denied":
        return "denial"
    if _is_technical_filing(text, row.get("source_type", "")):
        return "technical_filing"
    if row.get("evidence_label") != "confirmed":
        return "watchlist"
    if row.get("status") in {"Rumor", "In talks"}:
        return "watchlist"
    if row.get("status") == "Reported" and row.get("evidence_label") != "confirmed":
        return "watchlist"
    return "deal"


def _is_technical_filing(text: str, source_type: str = "") -> bool:
    return is_technical_exchange_notice(text)


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
    if left.get("deal_type") == "DCM":
        left_identifiers = _dcm_identifiers(left)
        right_identifiers = _dcm_identifiers(right)
        if left_identifiers and right_identifiers and left_identifiers.isdisjoint(right_identifiers):
            return False
        if _source_lineage(left) & _source_lineage(right):
            return _same_issuer(left, right)
        if not left_identifiers or not right_identifiers:
            return False
        return _same_issuer(left, right)
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


def _same_issuer(left: dict, right: dict) -> bool:
    def normalize(value) -> str:
        if _is_blank(value) or value == "Not applicable":
            return ""
        return re.sub(r"[^a-zа-яё0-9]+", "", str(value).lower())

    left_issuer = normalize(left.get("target_or_issuer"))
    right_issuer = normalize(right.get("target_or_issuer"))
    return bool(left_issuer and left_issuer == right_issuer)


def _dcm_identifiers(row: dict) -> set[str]:
    values = " ".join(str(row.get(field) or "") for field in ("security_code", "isin", "headline"))
    identifiers = {_canonical_dcm_identifier(value) for value in _issue_codes(values)}
    identifiers.update(value.upper() for value in re.findall(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", values, re.I))
    return identifiers


def _source_lineage(row: dict) -> set[str]:
    urls: set[str] = set()

    def add_url(value) -> None:
        url = _canonical_publication_url(value)
        if url:
            urls.add(url)

    for field in ("source_url", "url", "canonical_url"):
        add_url(row.get(field))
    sources = row.get("sources", [])
    if not isinstance(sources, list):
        return urls
    for source in sources:
        if not isinstance(source, dict):
            continue
        for field in ("url", "source_url", "canonical_url"):
            add_url(source.get(field))
        representations = source.get("representations", [])
        if not isinstance(representations, list):
            continue
        for representation in representations:
            if not isinstance(representation, dict):
                continue
            for field in ("url", "source_url", "canonical_url"):
                add_url(representation.get(field))
    return urls


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


def _clean_headline(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    lead = re.match(r"^[\"«]?([A-Za-zА-Яа-яЁё0-9.-]{3,30})", text)
    if lead and len(text) > 100:
        repeated = re.search(rf"\s+(?:компания\s+)?{re.escape(lead.group(1))}\s+", text[60:], re.I)
        if repeated:
            text = text[:60 + repeated.start()].strip(" .,:;—-")
    sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    if len(sentence) <= 220:
        return sentence
    clipped = sentence[:217].rsplit(" ", 1)[0]
    return f"{clipped}…"


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
    record_kind = row.get("record_kind") or _record_kind(row)

    material_probe = dict(row)
    material_probe["headline"] = row.get("headline", "")
    material_transaction = _is_material_transaction(material_probe)
    if record_kind == "technical_filing":
        score -= 40
        flags.append("technical_filing")
    elif not material_transaction:
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

    if _is_blank(row.get("status")):
        score -= 25
        flags.append("missing_status")
    if category in {"ECM", "DCM"} and record_kind in {"deal", "watchlist"} and material_transaction:
        if not isinstance(row.get("transaction_value"), (int, float)):
            score -= 10
            flags.append("missing_transaction_value")
        if row.get("currency") in {None, "", "Not disclosed"}:
            score -= 10
            flags.append("missing_currency")

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
    if row.get("status") == "In talks":
        score -= 5
        flags.append("talks_only")
    if row.get("currency") not in {None, "", "Not disclosed", "RUB", "USD", "EUR", "CNY", "GBP", "CHF"}:
        score -= 25
        flags.append("invalid_currency")
    if record_kind == "deal" and row.get("evidence_label") == "confirmed" and not _approval_evidence_is_sufficient(row):
        score -= 10
        flags.append("single_secondary_source")

    score = max(0, min(100, score))
    status = "rejected" if score < 40 else "review" if score < 75 else "approved"
    blocking_flags = {
        "technical_filing", "missing_both_parties", "missing_target", "missing_acquirer",
        "missing_issuer", "price_target_context", "invalid_currency", "denied_or_disputed",
        "missing_status", "missing_transaction_value", "missing_currency", "single_secondary_source",
    }
    if row.get("evidence_label") != "confirmed" and status == "approved":
        status = "review"
    if record_kind != "deal" and status == "approved":
        status = "review"
    if blocking_flags.intersection(flags) and status == "approved":
        status = "review"
    if record_kind == "technical_filing" and row.get("evidence_label") == "confirmed":
        score, status = max(score, 40), "review"
    return score, status, flags


def _migrate_row(source: dict) -> dict:
    row = dict(source)
    row["currency"] = _normalize_currency(row.get("currency"))
    legacy_status = row.get("status")
    if legacy_status == "Completed":
        row["status"] = "Closed"
    elif legacy_status == "Potential":
        row["status"] = "In talks"
    elif legacy_status == "Reported":
        row["status"] = "Confirmed" if row.get("evidence_label") == "confirmed" else "Reported"

    headline = str(row.get("headline") or "")
    inferred_status = _status(headline, row.get("deal_type", ""), row.get("evidence_label", "unverified"))
    if inferred_status in {"Denied", "Closed", "Priced", "Issued", "In talks", "Rumor", "Announced"} or row.get("status") not in {"Denied", "Closed", "Priced", "Issued", "In talks", "Announced", "Confirmed", "Reported", "Rumor"}:
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
        source_urls = " ".join(str(item.get("url") or "") for item in row.get("sources", []) if isinstance(item, dict)).lower()
        if _is_blank(row.get("acquirer_or_investor")) and re.search(r"(?:t-|т-)tekhnolog|t-tekhnolog|т-технолог", source_urls):
            row["acquirer_or_investor"] = "T-Technologies"
        parsed_seller = _extract_seller(headline)
        if not _is_blank(parsed_seller):
            row["seller"] = parsed_seller
        else:
            row.setdefault("seller", "Not disclosed")
        row["stake_percent"] = _extract_stake(headline) if row.get("stake_percent") is None else row.get("stake_percent")
    else:
        row["seller"] = "Not applicable"
        row["stake_percent"] = None
        row["payment_form"] = "Not applicable"
        parsed_issuer, _ = _extract_parties(row.get("deal_type", ""), headline, "Not disclosed")
        current_issuer = row.get("target_or_issuer")
        if not _is_blank(parsed_issuer) and (_is_blank(current_issuer) or _is_generic_party(current_issuer)):
            row["target_or_issuer"] = parsed_issuer
        if row.get("deal_type") == "DCM":
            parsed_value, parsed_currency = _extract_dcm_volume(headline)
            if parsed_value is None:
                parsed_value, parsed_currency = _extract_amount(headline)
            if parsed_value is not None:
                row["transaction_value"] = parsed_value
                row["currency"] = _normalize_currency(parsed_currency)
    if _is_generic_party(row.get("target_or_issuer")):
        row["target_or_issuer"] = "Not disclosed"
    row["headline"] = _clean_headline(headline)

    row["record_kind"] = _record_kind(row)
    if row["record_kind"] == "technical_filing":
        issuer = str(row.get("target_or_issuer") or "")
        if issuer not in {"", "Not disclosed", "Not applicable"} and issuer.lower() not in row["headline"].lower():
            row["target_or_issuer"] = "Not disclosed"
    if row.get("deal_type") != "M&A":
        row["enterprise_value"] = None
        row["ev_revenue"] = None
        row["ev_ebitda"] = None
        row["multiple_eligible"] = False
    if row.get("deal_type") != "DCM":
        for field in ("security_code", "isin", "coupon_rate", "coupon_type", "yield_rate", "maturity_date", "tenor", "issue_price"):
            row[field] = None if field in {"coupon_rate", "yield_rate", "issue_price"} else "Not applicable"
    if row.get("deal_type") != "ECM":
        row["price_per_share"] = None
        row["discount_percent"] = None
        row["bookrunners"] = "Not applicable"
        row["free_float_percent"] = None
    row.setdefault("security_code", _security_code(headline))
    row.setdefault("isin", _isin(headline))
    if row.get("deal_type") == "DCM" and not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", str(row.get("isin") or ""), re.I):
        row["isin"] = _isin(headline)
    row.setdefault("coupon_rate", _coupon_rate(headline))
    row.setdefault("coupon_type", _coupon_type(headline))
    row.setdefault("yield_rate", _yield_rate(headline))
    row.setdefault("maturity_date", _maturity_date(headline))
    row.setdefault("tenor", _tenor(headline))
    row.setdefault("issue_price", _issue_price(headline) if row.get("deal_type") == "DCM" else None)
    row.setdefault("price_per_share", _price_per_share(headline) if row.get("deal_type") == "ECM" else None)
    row.setdefault("discount_percent", _discount_percent(headline) if row.get("deal_type") == "ECM" else None)
    row.setdefault("bookrunners", _bookrunners(headline) if row.get("deal_type") == "ECM" else "Not applicable")
    row.setdefault("free_float_percent", _free_float(headline) if row.get("deal_type") == "ECM" else None)
    row.setdefault("financials_available_at", "Not disclosed")
    row.setdefault("operating_income", None)
    row.setdefault("depreciation", None)
    row.setdefault("amortization", None)
    row.setdefault("financials_metric_basis", "Not disclosed")
    row.setdefault("financials_source_name", "Not disclosed")
    row.setdefault("financials_source_url", "")
    row.setdefault("multiple_notes", "N/M: EV and aligned-currency financials are required")
    row.setdefault("multiple_eligible", False)

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
    text = str(value or "").strip()
    return bool(
        len(text) > 100
        or re.match(
            r"^(?:и\s+привлек|итоги выпуска|о регистрации|о порядке|о проведении|о включении|дополнительные условия|информация|сообщение|уведомление)",
            text, re.I,
        )
        or re.search(r"\s(?:разместил\w*|закрыл\w*\s+книг\w*|привлек\w*)\s", text, re.I)
    )


def _merge_sources(*source_groups: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for source in (item for group in source_groups for item in (group or [])):
        if not isinstance(source, dict):
            continue
        candidate = _canonical_source(source)
        url = candidate["url"]
        name = candidate["name"]
        # Exact canonical URL identity is strong publication evidence. Labels only
        # rank metadata and never create an additional evidence unit.
        key = (_canonical_publication_url(url), "") if url else ("", _normalize_publisher(name))
        current = merged.get(key)
        merged[key] = candidate if current is None else _merge_source_objects(current, candidate)

    publications = list(merged.values())
    by_publisher_date: dict[tuple[str, str], list[dict]] = {}
    for source in publications:
        key = (_normalize_publisher(source.get("name")), _iso_date(source.get("published_at")))
        if all(key):
            by_publisher_date.setdefault(key, []).append(source)

    consumed: set[int] = set()
    canonical: list[dict] = []
    for source in publications:
        if id(source) in consumed:
            continue
        key = (_normalize_publisher(source.get("name")), _iso_date(source.get("published_at")))
        peers = by_publisher_date.get(key, [])
        direct = [peer for peer in peers if _has_direct_representation(peer)]
        discovery_only = [peer for peer in peers if _is_google_only_source(peer)]
        # Legacy rows do not retain per-source titles. A one-to-one publisher/date
        # pair is the narrow safe fallback; ambiguous one-to-many groups stay apart.
        if len(direct) == 1 and len(discovery_only) == 1 and (source is direct[0] or source is discovery_only[0]):
            combined = _merge_source_objects(direct[0], discovery_only[0])
            consumed.update((id(direct[0]), id(discovery_only[0])))
            canonical.append(combined)
        else:
            consumed.add(id(source))
            canonical.append(source)
    return sorted(canonical, key=_source_quality, reverse=True)


def _canonical_source(source: dict) -> dict:
    candidate = {
        "name": str(source.get("name") or "Unknown source").strip(),
        "url": _safe_public_url(source.get("url", "")),
        "evidence_label": source.get("evidence_label", "unverified"),
        "source_type": source.get("source_type", "public_web"),
        "published_at": source.get("published_at", ""),
    }
    if source.get("title"):
        candidate["title"] = str(source["title"]).strip()
    representations = _source_representations(source)
    if len(representations) > 1:
        candidate["representations"] = representations
    return candidate


def _source_representations(source: dict) -> list[dict]:
    raw = list(source.get("representations", [])) if isinstance(source.get("representations"), list) else []
    raw.append({
        "name": source.get("name", "Unknown source"),
        "url": source.get("url", ""),
        "source_type": source.get("source_type", "public_web"),
        "published_at": source.get("published_at", ""),
    })
    representations: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = _safe_public_url(item.get("url", ""))
        if not url:
            continue
        representations[url] = {
            "name": str(item.get("name") or source.get("name") or "Unknown source").strip(),
            "url": url,
            "source_type": item.get("source_type", source.get("source_type", "public_web")),
            "published_at": item.get("published_at", source.get("published_at", "")),
        }
    return sorted(representations.values(), key=lambda item: ("news.google.com" in item["url"], item["url"]))


def _merge_source_objects(left: dict, right: dict) -> dict:
    winner, other = (left, right) if _source_quality(left) >= _source_quality(right) else (right, left)
    merged = dict(winner)
    representations: dict[str, dict] = {}
    for source in (left, right):
        for item in _source_representations(source):
            representations[item["url"]] = item
    if len(representations) > 1:
        merged["representations"] = sorted(
            representations.values(), key=lambda item: ("news.google.com" in item["url"], item["url"])
        )
    else:
        merged.pop("representations", None)
    if other.get("evidence_label") == "confirmed":
        merged["evidence_label"] = "confirmed"
    if not merged.get("title") and other.get("title"):
        merged["title"] = other["title"]
    return merged


def _normalize_publisher(value) -> str:
    text = re.sub(r"^https?://", "", str(value or "").strip().lower())
    return re.sub(r"[^a-zа-яё0-9]+", "", text)


def _canonical_publication_url(value) -> str:
    url = _safe_public_url(value)
    if not url:
        return ""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        return ""
    if port and not ((parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    tracking_parameters = {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
        "gclid", "fbclid", "yclid", "mc_cid", "mc_eid", "oc",
    }
    query = urlencode(sorted(
        (key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in tracking_parameters
    ))
    return urlunsplit((parsed.scheme.lower(), host, path, query, ""))


def _has_direct_representation(source: dict) -> bool:
    return any("news.google.com" not in item["url"] for item in _source_representations(source))


def _is_google_only_source(source: dict) -> bool:
    representations = _source_representations(source)
    return bool(representations) and all("news.google.com" in item["url"] for item in representations)


def _source_quality(source: dict) -> tuple[int, int, int]:
    source_type = str(source.get("source_type") or "")
    return (
        1 if source.get("evidence_label") == "confirmed" else 0,
        1 if source_type in OFFICIAL_SOURCE_TYPES else 0,
        1 if "news.google.com" not in str(source.get("url") or "") else 0,
    )


def _approval_evidence_is_sufficient(row: dict) -> bool:
    sources = [source for source in row.get("sources", []) if isinstance(source, dict)]
    confirmed = [source for source in sources if source.get("evidence_label") == "confirmed"]
    if any(str(source.get("source_type") or "") in OFFICIAL_SOURCE_TYPES for source in confirmed):
        return True
    return bool(confirmed) and len(sources) >= 2


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
    if left.get("deal_type") == right.get("deal_type") == "DCM":
        winner, other = (left, right) if _dcm_canonical_rank(left) >= _dcm_canonical_rank(right) else (right, left)
    else:
        winner, other = (left, right) if _record_quality(left) >= _record_quality(right) else (right, left)
    merged = dict(winner)
    for field in (
        "target_or_issuer", "acquirer_or_investor", "seller", "transaction_value", "enterprise_value", "currency",
        "stake_percent", "payment_form", "advisors", "rationale", "revenue_ltm", "ebitda_ltm",
        "financials_as_of", "financials_currency", "ev_revenue", "ev_ebitda", "sector", "geography",
        "security_code", "isin", "coupon_rate", "coupon_type", "yield_rate", "maturity_date",
        "tenor", "issue_price", "price_per_share", "discount_percent", "bookrunners", "free_float_percent",
    ):
        if _is_blank(merged.get(field)) or merged.get(field) == "Not applicable":
            if not _is_blank(other.get(field)):
                merged[field] = other[field]
    if merged.get("deal_type") == "DCM":
        merged["security_code"] = _merge_dcm_security_codes(left.get("security_code"), right.get("security_code"))
        merged["isin"] = _merge_dcm_scalar_identity(left.get("isin"), right.get("isin"))
        terms_row = max(
            (left, right),
            key=lambda row: (_lifecycle_status_rank(row.get("status")), _dcm_canonical_rank(row)),
        )
        if not _is_blank(terms_row.get("transaction_value")):
            merged["transaction_value"] = terms_row["transaction_value"]
            merged["currency"] = terms_row.get("currency") or merged.get("currency")
    merged["sources"] = _merge_sources(left.get("sources", []), right.get("sources", []))
    merged["source_count"] = len(merged["sources"])
    merged["matched_coverage"] = sorted(set(left.get("matched_coverage", [])) | set(right.get("matched_coverage", [])))
    first_seen = [value for value in (left.get("first_seen_at"), right.get("first_seen_at")) if value]
    merged["first_seen_at"] = min(first_seen) if first_seen else ""
    merged["last_seen_at"] = max(left.get("last_seen_at") or "", right.get("last_seen_at") or "")
    status_rank = {"Rumor": 0, "Reported": 1, "In talks": 2, "Confirmed": 3, "Announced": 4, "Priced": 5, "Issued": 6, "Closed": 6, "Denied": 7}
    merged["status"] = max((left.get("status", "Rumor"), right.get("status", "Rumor")), key=lambda value: status_rank.get(value, 0))
    if merged["status"] == "Denied":
        merged["transaction_value"] = None
        merged["enterprise_value"] = None
        merged["currency"] = "Not disclosed"
    merged["record_kind"] = _record_kind(merged)
    _apply_primary_source(merged)
    _apply_quality(merged)
    return merged


def _dcm_canonical_rank(row: dict) -> tuple:
    sources = [source for source in row.get("sources", []) if isinstance(source, dict)]
    source_rank = max((_source_quality(source) for source in sources), default=(0, 0, 0))
    completeness = sum(
        not _is_blank(row.get(field)) and row.get(field) != "Not applicable"
        for field in ("transaction_value", "currency", "security_code", "isin", "coupon_rate", "yield_rate", "maturity_date", "tenor")
    )
    return source_rank, _lifecycle_status_rank(row.get("status")), completeness, _record_quality(row)


def _lifecycle_status_rank(status) -> int:
    return {"Rumor": 0, "Reported": 1, "In talks": 2, "Confirmed": 3, "Announced": 4, "Priced": 5, "Issued": 6}.get(status, 0)


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
        issuer = covered_company if covered_company != "Not disclosed" else _extract_issuer(clean)
        if _is_blank(issuer):
            issuer = _leading_entity(clean)
        return issuer, "Not applicable"
    sale_to_patterns = [
        r"^(.+?)\s+продал\w*\s+(?:\d+(?:[.,]\d+)?%\s+)?(?:акци\w*|дол\w*|пакет\w*)?\s*(.+?)\s+(?:компании|группе)\s+(.+?)(?:\s+за\s+|$)",
        r"^(.+?)\s+(?:sold|divested)\s+(?:a\s+)?(?:\d+(?:[.,]\d+)?%\s+)?(?:stake\s+in|shares?\s+of)?\s*(.+?)\s+to\s+(.+?)(?:\s+for\s+|$)",
    ]
    for pattern in sale_to_patterns:
        match = re.search(pattern, clean, re.I)
        if match:
            return _clean_party(match.group(2)), _clean_party(match.group(3))
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
        r"^(.+?)\s+(?:может|планирует|намерен\w*)\s+(?:купить|приобрести)\s+(.+?)(?:\s+[—-]\s+|$)",
        r"^(.+?)\s+опроверг\w*\s+(?:покупк\w*|приобретени\w*)\s+(.+?)(?:\s+[—-]\s+|$)",
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
    quoted = re.match(r"^[«\"]([^»\"]+)[»\"]", title)
    if quoted:
        return quoted.group(1).strip()
    words = re.split(
        r"\s+(?:(?:успешно\s+)?закрыл\w*\s+книг\w*|размест\w*|выпуст\w*|планир\w*|рассматрива\w*|considers|explores|announces)",
        title, maxsplit=1, flags=re.I,
    )
    candidate = _clean_party(words[0]) if words and len(words[0]) <= 80 else "Not disclosed"
    return "Not disclosed" if _is_generic_party(candidate) else candidate


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


def _extract_seller(title: str) -> str:
    clean = re.sub(r"\s+[—-]\s+[^—-]+$", "", title).strip()
    patterns = (
        r"^(.+?)\s+закрыл\w*\s+сделк\w*\s+по\s+продаж\w*\s+",
        r"^(.+?)\s+(?:продал\w*|sold|divested)\s+",
        r"\s+у\s+(.+?)(?:\s+за\s+|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, re.I)
        if match:
            return _clean_party(match.group(1))
    return "Not disclosed"


def _extract_issuer(text: str) -> str:
    patterns = (
        r"наименование эмитента\s+(.+?)\s+наименование ценной бумаги",
        r"следующих эмитентов\s*:\s*[\"«]?(.+?)[\"»]?\s*\(",
        r"^\s*выпуск\s+облигаций\s+(.+?)\s+(?:на|объем|объ[её]мом)",
        r"эмитент(?:ом|а)?\s*[:—-]\s*(.+?)(?:[.;]|\s+серии\s+)",
        r"облигаци\w*\s+(.+?)\s+серии\s+[A-ZА-Я0-9-]+",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            value = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;")
            if 2 < len(value) <= 180 and not _is_generic_party(value):
                return value
    return "Not disclosed"


def _parse_number(value: str) -> float:
    compact = re.sub(r"\s+", "", value).replace(",", ".")
    return float(compact)


def _currency_from_token(value: str) -> str:
    token = str(value or "").upper()
    if "CNY" in token or "RMB" in token or "ЮАН" in token:
        return "CNY"
    if "$" in token or "USD" in token or "ДОЛЛАР" in token:
        return "USD"
    if "€" in token or "EUR" in token or "ЕВРО" in token:
        return "EUR"
    if "GBP" in token or "ФУНТ" in token:
        return "GBP"
    return "RUB" if re.search(r"RUB|РУБ|₽", token) else "Not disclosed"


def _normalize_currency(value) -> str:
    token = str(value or "").strip()
    if not token or token.upper() in {"NOT DISCLOSED", "NONE", "N/A"}:
        return "Not disclosed"
    normalized = _currency_from_token(token)
    return normalized if normalized != "Not disclosed" else token.upper()


def _extract_dcm_volume(text: str) -> tuple[float | None, str]:
    match = re.search(
        r"(?:об[ъь]ем\s+(?:размещенн\w+\s+биржев\w+\s+облигац\w+(?:\s+по\s+номинальн\w+\s+стоимост\w+)?|размещени\w*|выпуск\w*)|"
        r"общ(?:ая|ую)\s+сумм\w*|issue\s+size|offering\s+size)"
        r"[^\d$€₽]{0,100}((?:\d[\d\s]*)(?:[.,]\d+)?)\s*"
        r"(трлн|триллион\w*|trillion|млрд|миллиард\w*|billion|млн|миллион\w*|million)?\s*"
        r"(CNY|RMB|USD|EUR|RUB|юан\w*|руб\w*|доллар\w*|евро|₽|\$|€)?",
        text, re.I,
    )
    if not match:
        return None, ""
    number = _parse_number(match.group(1))
    unit = (match.group(2) or "").lower()
    multiplier = _amount_multiplier(unit)
    if multiplier == 1 and number < 1_000_000:
        return None, ""
    currency_token = match.group(3) or text[match.end():match.end() + 180]
    currency = _currency_from_token(currency_token)
    return number * multiplier, currency


def _extract_amount(text: str) -> tuple[float | None, str]:
    pattern = re.compile(
        r"(?:(CNY|RMB|USD|EUR|RUB|\$|€|₽)\s*)?(\d+(?:[.,]\d+)?)\s*(трлн|триллион\w*|trillion|млрд|миллиард\w*|billion|млн|миллион\w*|million)?\s*(юан\w*|cny|rmb|руб(?:лей|ля|\.)?|rub|usd|доллар\w*|eur|евро|₽|\$|€)?",
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
        multiplier = _amount_multiplier(unit)
        if multiplier == 1 and number < 1_000_000 and not _amount_has_transaction_context(context):
            continue
        token = f"{prefix} {suffix}"
        currency = _currency_from_token(token)
        return number * multiplier, currency
    return None, ""


def _amount_multiplier(unit: str) -> int:
    normalized = str(unit or "").lower()
    if normalized in {"трлн", "trillion"} or normalized.startswith("триллион"):
        return 1_000_000_000_000
    if normalized in {"млрд", "billion"} or normalized.startswith("миллиард"):
        return 1_000_000_000
    if normalized in {"млн", "million"} or normalized.startswith("миллион"):
        return 1_000_000
    return 1


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
    cash = bool(re.search(r"(?:consideration|оплат\w*|расчет\w*)[^.;]{0,60}\bcash\b|денежн\w*\s+средств|за\s+наличн", lowered))
    shares = bool(re.search(r"(?:consideration|оплат\w*|расчет\w*)[^.;]{0,60}\b(?:shares?|stock)\b|обмен\w*\s+акци|оплат\w*\s+акци", lowered))
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


def _security_code(text: str) -> str:
    return "; ".join(_issue_codes(text)) or "Not disclosed"


def _issue_codes(text: str) -> list[str]:
    values = re.findall(r"\b\d{3,4}[РP]-\d{1,3}\b", str(text), re.I)
    match = re.search(
        r"(?:регистрационн\w*\s+номер(?:\s+выпуска)?(?:\s+биржев\w*\s+облигац\w*)?|registration\s+number)(?:\s*[:№]\s*|\s+)([0-9][A-Z0-9-]{7,39})",
        text, re.I,
    )
    if match:
        values.append(match.group(1))
    unique: dict[str, str] = {}
    for value in values:
        display = re.sub(r"(?<=\d)P(?=-\d)", "Р", value.upper())
        unique.setdefault(_canonical_dcm_identifier(display), display)
    return sorted(unique.values(), key=_canonical_dcm_identifier)


def _canonical_dcm_identifier(value: str) -> str:
    return re.sub(r"(?<=\d)Р(?=-\d)", "P", str(value).upper())


def _missing_dcm_identity(value) -> bool:
    return _is_blank(value) or value == "Not applicable"


def _merge_dcm_security_codes(existing, incoming) -> str:
    values: dict[str, str] = {}
    for source in (existing, incoming):
        if _missing_dcm_identity(source):
            continue
        for value in re.split(r"\s*;\s*", str(source)):
            display = value.strip()
            if display:
                values.setdefault(_canonical_dcm_identifier(display), display)
    return "; ".join(values.values()) if values else "Not disclosed"


def _merge_dcm_scalar_identity(existing, incoming) -> str:
    if not _missing_dcm_identity(existing):
        return str(existing)
    return "Not disclosed" if _missing_dcm_identity(incoming) else str(incoming)


def _isin(text: str) -> str:
    # ISO 6166: two-letter country prefix, nine alphanumerics, numeric check digit.
    match = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", text, re.I)
    return match.group(1).upper() if match else "Not disclosed"


def _coupon_rate(text: str) -> float | None:
    match = re.search(
        r"(?:ставк\w*\s+(?:первого\s+)?купон\w*|купонн\w*\s+ставк\w*|coupon\s+rate)"
        r"[^\d]{0,45}(\d{1,2}(?:[.,]\d+)?)\s*%",
        text, re.I,
    )
    return float(match.group(1).replace(",", ".")) if match else None


def _coupon_type(text: str) -> str:
    lowered = text.lower()
    if re.search(r"переменн\w*\s+купон|ключев\w*\s+ставк\w*.+преми|floating|float rate", lowered):
        return "Floating"
    if re.search(r"фиксированн\w*\s+купон|fixed[- ]rate", lowered):
        return "Fixed"
    if re.search(r"дисконтн\w*\s+облигац|zero[- ]coupon", lowered):
        return "Discount"
    return "Not disclosed"


def _yield_rate(text: str) -> float | None:
    match = re.search(r"(?:доходност\w*|yield)[^\d]{0,35}(\d{1,2}(?:[.,]\d+)?)\s*%", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def _maturity_date(text: str) -> str:
    match = re.search(
        r"(?:дата\s+погашения|погашени\w*\s+ожидается|maturity(?:\s+date)?)\s*[:—-]?\s*"
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{2}-\d{2})",
        text, re.I,
    )
    if not match:
        return "Not disclosed"
    value = match.group(1)
    if re.match(r"^\d{4}-", value):
        return value
    parts = re.split(r"[./-]", value)
    return f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"


def _tenor(text: str) -> str:
    match = re.search(r"(?:срок\s+обращения|сроком\s+на|tenor)[^\d]{0,30}(\d+(?:[.,]\d+)?)\s*(лет|год\w*|месяц\w*|years?|months?)", text, re.I)
    return f"{match.group(1).replace(',', '.')} {match.group(2)}" if match else "Not disclosed"


def _issue_price(text: str) -> float | None:
    match = re.search(r"(?:цена\s+размещения|фактическ\w*\s+цена\s+размещения|issue\s+price)[^\d]{0,25}(\d+(?:[.,]\d+)?)", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def _price_per_share(text: str) -> float | None:
    match = re.search(r"(?:цена\s+размещения|цена\s+за\s+акци\w*|offering\s+price|price\s+per\s+share)[^\d]{0,30}(\d+(?:[.,]\d+)?)", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def _discount_percent(text: str) -> float | None:
    match = re.search(r"(?:дисконт\w*|discount)[^\d]{0,30}(\d+(?:[.,]\d+)?)\s*%", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def _bookrunners(text: str) -> str:
    match = re.search(r"(?:bookrunners?|букраннер\w*|организатор\w*\s+размещения)\s*(?:выступил[аи]?|were|was|:)?\s*([^.;]+)", text, re.I)
    return re.sub(r"\s+", " ", match.group(1)).strip()[:180] if match else "Not disclosed"


def _free_float(text: str) -> float | None:
    match = re.search(r"(?:free[- ]float|дол\w*\s+акци\w*\s+в\s+свободн\w*\s+обращени\w*)[^\d]{0,30}(\d+(?:[.,]\d+)?)\s*%", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def _financials_as_of(text: str) -> str:
    match = re.search(r"(?:ltm|за\s+12\s+месяцев|за\s+(?:20)?\d{2}\s+год|as\s+of)\s*([^.;,]{0,30})", text, re.I)
    return match.group(0).strip()[:60] if match else "Not disclosed"


def median_multiples(rows: list[dict]) -> dict[str, float | int | None]:
    def values(field: str) -> list[float]:
        result = sorted(
            float(row[field]) for row in rows
            if _multiple_is_eligible(row)
            and isinstance(row.get(field), (int, float))
            and row[field] > 0
        )
        return result
    def median(items: list[float]) -> float | None:
        if len(items) < 3:
            return None
        middle = len(items) // 2
        return items[middle] if len(items) % 2 else (items[middle - 1] + items[middle]) / 2
    revenue = values("ev_revenue")
    ebitda = values("ev_ebitda")
    eligible = [row for row in rows if _multiple_is_eligible(row) and (row.get("ev_revenue") or row.get("ev_ebitda"))]
    return {"ev_revenue": median(revenue), "ev_ebitda": median(ebitda), "coverage": len(eligible), "ev_revenue_count": len(revenue), "ev_ebitda_count": len(ebitda)}


def _is_blank(value) -> bool:
    return value is None or value == "" or value == "Not disclosed"


def _positive_number(value) -> float | None:
    try:
        number = float(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _valid_multiple(enterprise_value, metric, deal_currency, metric_currency) -> float | None:
    ev = _positive_number(enterprise_value)
    denominator = _positive_number(metric)
    if not ev or not denominator:
        return None
    if _normalize_currency(deal_currency) != _normalize_currency(metric_currency):
        return None
    return ev / denominator


def _multiple_is_eligible(row: dict) -> bool:
    """Use only approved, source-backed M&A observations available by announcement."""
    if row.get("deal_type") != "M&A" or row.get("record_kind") not in {None, "deal"}:
        return False
    if row.get("quality_status") != "approved" or row.get("status") == "Denied":
        return False
    announced = str(row.get("announced_date") or "")[:10]
    available_raw = row.get("financials_available_at")
    available = str(available_raw or "")[:10]
    if not announced or _is_blank(available_raw) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", available):
        return False
    if available > announced:
        return False
    return bool(
        _positive_number(row.get("enterprise_value"))
        and _normalize_currency(row.get("currency")) == _normalize_currency(row.get("financials_currency"))
        and (_positive_number(row.get("revenue_ltm")) or _positive_number(row.get("ebitda_ltm")))
    )


def _is_navigation_record(row: dict) -> bool:
    headline = str(row.get("headline") or "").strip().lower()
    return row.get("source_name") in {"MTS Investor Relations"} and headline in {"облигации", "еврооблигации 2023"}


def _extract_stake(text: str) -> float | None:
    match = re.search(
        r"(?:дол\w*|пакет\w*|stake(?:\s+of)?|приобрета\w*|покупк\w*)[^\d%]{0,30}(\d+(?:[.,]\d+)?)\s*%|"
        r"(\d+(?:[.,]\d+)?)\s*%\s*(?:акци\w*|дол\w*|stake|of\s+(?:the\s+)?target)",
        text, re.I,
    )
    value = match.group(1) or match.group(2) if match else None
    return float(value.replace(",", ".")) if value else None


def _status(text: str, category: str, evidence_label: str = "unverified") -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("опроверг", "не подтверди", "denied", "denies", "no agreement")):
        return "Denied"
    if category in {"ECM", "DCM"} and re.search(r"закрыл\w*\s+книг|book\w*\s+clos|priced", lowered):
        return "Priced"
    if category in {"ECM", "DCM"} and re.search(
        r"завершил\w*(?:\s+\w+){0,3}\s+размещени|размещение\s+завершено|"
        r"зафиксировал\w*\s+об[ъь]ем\s+размещени",
        lowered,
    ):
        return "Issued"
    if any(word in lowered for word in ("закрыл", "закрыла", "завершил", "завершила", "completed", "closed")):
        return "Issued" if category in {"ECM", "DCM"} else "Closed"
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
    patterns = (
        r"для\s+(?:целей\s+)?((?:рефинансирования|финансирования|инвестиций|развития).+?)(?:[.;]|$)",
        r"средства\s+(?:будут\s+)?направлены\s+на\s+(.+?)(?:[.;]|$)",
        r"целью\s+(?:сделки|размещения)\s+является\s+(.+?)(?:[.;]|$)",
        r"use\s+of\s+proceeds\s*:?\s*(.+?)(?:[.;]|$)",
        r"to\s+(?:fund|finance|refinance)\s+(.+?)(?:[.;]|$)",
    )
    match = next((candidate for pattern in patterns if (candidate := re.search(pattern, text, re.I))), None)
    if not match:
        return "Not disclosed"
    value = match.group(1).strip()
    value = re.split(r"\s+[—-]\s+", value, maxsplit=1)[0]
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
