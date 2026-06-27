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
    "currency", "stake_percent", "instrument", "rationale", "score",
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
    value, currency = (event.amount, event.currency or "") if event.amount else _extract_amount(text)
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
        currency=(currency or "Not disclosed").upper(),
        stake_percent=_extract_stake(text),
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
        by_id[record.deal_id] = row
    output = sorted(by_id.values(), key=lambda row: (row.get("announced_date", ""), row.get("score", 0)), reverse=True)
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
