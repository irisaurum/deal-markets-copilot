from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser

from .models import Event


class SourceHealthError(RuntimeError):
    """Raised when an exchange page cannot be treated as a healthy source."""


@dataclass(frozen=True, slots=True)
class ExchangeIndexEntry:
    source_event_id: str
    url: str
    title: str
    published_at: str = ""


_BLOCKED_PAGE_PATTERNS = (
    r"cdn-cgi/challenge-platform",
    r"cf-chl-",
    r"captcha",
    r"access denied",
    r"sign in to continue",
    r"<title>\s*(?:error|login|authorization)\b",
)

_COMMON_EXCLUSIONS = (
    r"\bgovernment bond",
    r"\bsovereign\b",
    r"\bmunicipal bond",
    r"\bcentral bank\b",
    r"\bnational bank (?:note|bond|paper)",
    r"(?:paid\s+\w*\s+coupon|coupon\s+(?:paid|payment\b(?!\s+dates)))",
    r"\bredemption\b|\bmaturity payment\b",
    r"\bbuyback\b",
    r"\brating(?:s)?\b.{0,50}\b(?:affirm|confirm|upgrade|downgrade)",
    r"trading (?:conditions|results|statistics)",
    r"market (?:summary|statistics|data)",
)

_SOURCE_EXCLUSIONS = {
    "kz-kase": _COMMON_EXCLUSIONS + (
        r"information on shares and shareholders",
        r"depository balance",
        r"futures? on .+ exchange rate",
        r"routine listing maintenance",
    ),
    "am-amx": _COMMON_EXCLUSIONS + (
        r"shareholders?.{0,30}(?:meeting|general meeting)",
        r"branch opening",
        r"interim reports?|annual reports?",
        r"dividend",
        r"essential facts and information",
    ),
    "md-bvm": _COMMON_EXCLUSIONS + (
        r"provisional (?:admission|registration)",
        r"temporary (?:admission|registration)",
        r"daily statistics|annual statistics|trade statistics",
        r"withdrawal from (?:the )?(?:ats|regulated market)",
    ),
}


def validate_public_page(page: str, source_name: str) -> None:
    lowered = page.lower()
    if not page.strip():
        raise SourceHealthError(f"{source_name}: empty response")
    if any(re.search(pattern, lowered, re.I) for pattern in _BLOCKED_PAGE_PATTERNS):
        raise SourceHealthError(f"{source_name}: anti-bot, login or error page")


def parse_exchange_index(source: dict, page: str) -> tuple[list[ExchangeIndexEntry], list[str]]:
    source_name = str(source.get("name") or source.get("id") or "Exchange source")
    validate_public_page(page, source_name)
    source_id = str(source.get("id") or "")
    base_url = str(source.get("index_url") or source.get("url") or "")
    parser = _LinkParser()
    parser.feed(page)
    entries: list[ExchangeIndexEntry] = []
    pages: list[str] = []
    seen_entries: set[str] = set()
    seen_pages: set[str] = set()
    for href, label in parser.links:
        absolute = urllib.parse.urljoin(base_url, html.unescape(href))
        event_id = _detail_id(source_id, absolute)
        if event_id:
            if event_id in seen_entries:
                continue
            seen_entries.add(event_id)
            clean_label = _clean_text(label)
            published, title = _leading_date(clean_label)
            entries.append(ExchangeIndexEntry(event_id, absolute, title or clean_label, published))
            continue
        if _is_archive_page(source_id, absolute, base_url) and absolute not in seen_pages:
            seen_pages.add(absolute)
            pages.append(absolute)
    if not entries:
        raise SourceHealthError(f"{source_name}: expected detail links were not found")
    return entries, pages


def parse_exchange_detail(source: dict, page: str, url: str, index_title: str = "") -> list[Event]:
    source_name = str(source.get("name") or source.get("id") or "Exchange source")
    validate_public_page(page, source_name)
    source_id = str(source.get("id") or "")
    source_event_id = _detail_id(source_id, url)
    if not source_event_id:
        raise SourceHealthError(f"{source_name}: unsafe or non-canonical detail URL")

    if source_id == "kz-kase":
        published_at, title, body = _kase_payload(page, source_event_id)
        text = _clean_text(body)
    else:
        fragment = _detail_fragment(source_id, page)
        title = _first_heading(fragment) or index_title
        text = _visible_text(fragment)
        published_at = _publication_date(text)
    title = _clean_text(title or index_title)
    if not title or not text:
        raise SourceHealthError(f"{source_name}: title or detail body is empty")

    combined = f"{title} {text}"
    if _is_excluded(source_id, combined):
        return []
    deal_type = _allowed_deal_type(source_id, combined)
    if not deal_type:
        return []

    issuer = _issuer(source_id, title, text)
    isins = _isins(combined)
    registrations = _registration_numbers(combined)
    identities = isins or registrations or [""]
    if deal_type in {"DCM", "ECM"} and not issuer:
        return []

    stage, sub_stage = _lifecycle(source_id, combined)
    document_urls = _document_urls(page, url)
    events: list[Event] = []
    for position, identity in enumerate(identities):
        isin = identity if identity in isins else ""
        registration = identity if identity in registrations else ""
        context = _identity_context(text, identity)
        amount, currency, quantity, denomination, derived = _economics(source_id, context, text, len(identities))
        series = _series(context or combined, identity)
        programme = _programme(combined)
        coupon = _coupon_rate(context or combined)
        maturity = _maturity_date(context or combined)
        event_date = _event_date(combined)
        suffix = identity or series or str(position + 1)
        safe_suffix = re.sub(r"[^a-z0-9]+", "-", suffix.lower()).strip("-") or "event"
        factual_summary = _factual_summary(
            issuer=issuer,
            instrument="Corporate bonds" if deal_type == "DCM" else "Share issue" if deal_type == "ECM" else "Mandatory withdrawal",
            isin=isin,
            registration=registration,
            amount=amount,
            currency=currency,
            coupon=coupon,
            maturity=maturity,
            programme=programme,
            series=series,
            stage=stage,
        )
        events.append(Event(
            event_id=f"{source_id}-{source_event_id}-{safe_suffix}",
            published_at=published_at or event_date,
            title=title,
            summary=factual_summary,
            source=source_name,
            url=url,
            source_type="official_exchange",
            confidence="confirmed",
            amount=amount,
            currency=currency or None,
            country=str(source.get("country") or "Not disclosed"),
            market=str(source.get("market") or "Not disclosed"),
            source_id=source_id,
            source_event_id=source_event_id,
            original_title=title,
            issuer=issuer,
            instrument="Corporate bonds" if deal_type == "DCM" else "Share issue" if deal_type == "ECM" else "Mandatory withdrawal",
            programme=programme,
            series=series,
            isin=isin,
            registration_number=registration,
            coupon_rate=coupon,
            maturity_date=maturity,
            event_date=event_date,
            lifecycle_stage=stage,
            event_sub_stage=sub_stage,
            document_urls=document_urls,
            quantity=quantity,
            denomination=denomination,
            amount_is_derived=derived,
        ))
    return events


def is_candidate_title(source_id: str, title: str) -> bool:
    text = title.lower()
    if _is_excluded(source_id, text):
        return False
    if source_id == "md-bvm" and "mandatory withdrawal" in text:
        return True
    return bool(re.search(
        r"\b(?:bond|bonds|issue|issuance|placement|bookbuilding|guidance|priced|listing|listed|allocation|share issue|acquisition|disposal|takeover|tender)\b",
        text,
        re.I,
    ))


def _detail_id(source_id: str, url: str) -> str:
    path = urllib.parse.urlparse(url).path
    patterns = {
        "kz-kase": r"/(?:en|ru|kz)/information/news/show/(\d+)/?$",
        "am-amx": r"/(?:en|am)/news/[^/]+/(\d+)/?$",
        "md-bvm": r"/(?:en|ro|ru)/news/(\d+)/?$",
    }
    match = re.search(patterns.get(source_id, r"$^"), path, re.I)
    return match.group(1) if match else ""


def _is_archive_page(source_id: str, url: str, base_url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    base = urllib.parse.urlparse(base_url)
    if parsed.netloc.lower() != base.netloc.lower():
        return False
    if source_id == "md-bvm":
        return bool(re.search(r"/en/news/page/\d+/?$", parsed.path))
    if source_id == "kz-kase":
        return parsed.path.rstrip("/") == base.path.rstrip("/") and bool(parsed.query)
    if source_id == "am-amx":
        return parsed.path.rstrip("/") == base.path.rstrip("/") and bool(parsed.query)
    return False


def _kase_payload(page: str, source_event_id: str) -> tuple[str, str, str]:
    pattern = (
        rf'"b":\{{"id":{re.escape(source_event_id)},"create_datetime":"((?:\\.|[^"\\])*)",'
        rf'"language":"en","subject":"((?:\\.|[^"\\])*)","body":"((?:\\.|[^"\\])*)"'
    )
    match = re.search(pattern, page)
    if not match:
        title = _first_heading(page)
        text = _visible_text(page)
        if not title or not text:
            raise SourceHealthError("KASE: expected transfer-state payload is missing")
        return _publication_date(text), title, text
    return tuple(_decode_json_string(value) for value in match.groups())  # type: ignore[return-value]


def _decode_json_string(value: str) -> str:
    return json.loads(f'"{value}"')


def _is_excluded(source_id: str, text: str) -> bool:
    return any(re.search(pattern, text, re.I | re.S) for pattern in _SOURCE_EXCLUSIONS.get(source_id, _COMMON_EXCLUSIONS))


def _allowed_deal_type(source_id: str, text: str) -> str:
    if source_id == "md-bvm" and "mandatory withdrawal" in text.lower():
        return "M&A"
    if re.search(r"\b(?:bond|bonds|notes)\b|облигац", text, re.I):
        if re.search(r"\b(?:issue|issuance|placement|placed|book|guidance|priced|allocation|admission|listed|listing|official list)\b", text, re.I):
            return "DCM"
    if re.search(r"\b(?:share issue|issue of shares|share placement|new capital)\b", text, re.I):
        return "ECM"
    if source_id == "kz-kase" and re.search(r"\b(?:acquisition|disposal|takeover|tender offer|completed transaction)\b", text, re.I):
        return "M&A"
    return ""


def _issuer(source_id: str, title: str, text: str) -> str:
    if source_id == "am-amx":
        match = re.search(r'(?:Name of the issuer|Issuer)\s*[:\-]?\s*["“]?(.+?)(?=\s+(?:Type of security|Issuance date|ISIN|Ticker)\b)', text, re.I)
        if match:
            return _clean_entity(match.group(1))
    if source_id == "md-bvm":
        match = re.search(r'(?:bonds? of (?:the )?|issued by )(.+?)(?:\s*\(|\s+Central Office|\s+ISIN)', title + " " + text, re.I)
        if match:
            return _clean_entity(match.group(1))
    if source_id == "kz-kase":
        match = re.search(r'(?:bonds? of|issues? of)\s+(.{2,120}?\b(?:JSC|LLP|Ltd))\b', title + " " + text, re.I)
        if match:
            return _clean_entity(match.group(1))
        match = re.match(r'\s*([A-Z][A-Za-z0-9 ."“”&-]{2,120}?\b(?:JSC|LLP|Ltd))\b', text)
        if match:
            return _clean_entity(match.group(1))
        match = re.search(r'(?:bonds? of|issues? of)\s+(.+?)(?:\s+are\s+included|\s+included|\s+on\s+KASE|\s+JSC\s*\()', title + " " + text, re.I)
        if match:
            value = _clean_entity(match.group(1))
            return value if value.endswith(("JSC", "LLP", "Ltd")) else value
        match = re.search(r'of\s+([A-Z][A-Za-z0-9 ."“”&-]+?(?:JSC|LLP|Ltd))', title)
        if match:
            return _clean_entity(match.group(1))
    match = re.search(r'([A-Z][A-Za-z0-9 ."“”&-]+?(?:JSC|CJSC|OJSC|LLC|LLP|Bank))', title + " " + text)
    return _clean_entity(match.group(1)) if match else ""


def _isins(text: str) -> list[str]:
    values: list[str] = []
    for value in re.findall(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", text, re.I):
        normalized = value.upper()
        if normalized not in values:
            values.append(normalized)
    return values


def _registration_numbers(text: str) -> list[str]:
    values = re.findall(r"(?:registration (?:number|no\.?|№)|state registration number)\s*[:№-]?\s*([A-Z0-9-]{8,40})", text, re.I)
    return list(dict.fromkeys(value.upper() for value in values))


def _identity_context(text: str, identity: str) -> str:
    if not identity:
        return text
    index = text.upper().find(identity.upper())
    if index < 0:
        return text
    return text[max(0, index - 100):index + 500]


def _economics(source_id: str, context: str, full_text: str, identity_count: int) -> tuple[float | None, str, float | None, float | None, bool]:
    if source_id == "am-amx":
        quantity = _labeled_number(full_text, ("Number of securities", "Quantity"))
        denomination, denomination_currency = _labeled_money(full_text, ("Nominal Value", "Nominal value", "Denomination"))
        amount, currency = _labeled_money(full_text, ("Aggregate nominal amount", "Total nominal value", "Issue amount"))
        if amount is not None:
            return amount, currency, quantity, denomination, False
        if identity_count == 1 and quantity is not None and denomination is not None and denomination_currency:
            return quantity * denomination, denomination_currency, quantity, denomination, True
    if source_id == "md-bvm":
        amount, currency = _labeled_money(full_text, ("Value", "Issue value", "Issue amount"))
        quantity = _labeled_number(full_text, ("Number of issued bonds", "Number of bonds"))
        denomination, _ = _labeled_money(full_text, ("Nominal value", "Denomination"))
        return amount, currency, quantity, denomination, False
    if source_id == "kz-kase":
        pair = re.search(
            r"(?:[A-Z]{2}[A-Z0-9]{9}\d[^;]{0,80};\s*)?(KZT|USD|EUR|CNY)\s*\d[\d ,.]*\s*,\s*(KZT|USD|EUR|CNY)\s*(\d[\d ,.]*)\s*(bn|mln|million|billion)?(?:[;.)]|$)",
            context,
            re.I,
        )
        if pair:
            return _scaled_number(pair.group(3), pair.group(4)), pair.group(2).upper(), None, None, False
        amount, currency = _labeled_money(context, ("Declared placement volume", "Issue volume", "Placement volume"))
        if amount is not None:
            return amount, currency, None, None, False
    amount, currency = _labeled_money(context, ("Amount", "Volume", "Value"))
    return amount, currency, None, None, False


def _labeled_money(text: str, labels: tuple[str, ...]) -> tuple[float | None, str]:
    label_pattern = "|".join(re.escape(label) for label in labels)
    patterns = (
        rf"(?:{label_pattern})\s*[,:(-]*\s*(KZT|USD|EUR|CNY|AMD|MDL)\s*(\d[\d ,.]*)\s*(bn|bln|mln|million|billion)?(?=\s+[A-Za-z]|[;.)]|$)",
        rf"(?:{label_pattern})\s*[,:(-]*\s*(\d[\d ,.]*)\s*(bn|bln|mln|million|billion)?\s*(KZT|USD|EUR|CNY|AMD|MDL)",
    )
    first = re.search(patterns[0], text, re.I)
    if first:
        return _scaled_number(first.group(2), first.group(3)), first.group(1).upper()
    second = re.search(patterns[1], text, re.I)
    if second:
        return _scaled_number(second.group(1), second.group(2)), second.group(3).upper()
    return None, ""


def _labeled_number(text: str, labels: tuple[str, ...]) -> float | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})\s*[,:(-]*\s*(?:un\.?\s*)?(\d[\d ,.]*)", text, re.I)
    return _scaled_number(match.group(1), "") if match else None


def _scaled_number(value: str, unit: str | None) -> float:
    compact = re.sub(r"[\s,]", "", value)
    number = float(compact)
    multiplier = 1_000_000_000 if str(unit).lower() in {"bn", "bln", "billion"} else 1_000_000 if str(unit).lower() in {"mln", "million"} else 1
    return number * multiplier


def _series(text: str, identity: str) -> str:
    if identity:
        tied = re.search(rf"{re.escape(identity)}\s*\(\s*([A-Z]{{2,8}}[bB]\d{{1,3}})\b", text, re.I)
        if tied:
            return tied.group(1)
    match = re.search(r"\b([A-Z]{2,8}[bB]\d{1,3})\b", text)
    if match:
        return match.group(1)
    match = re.search(r"\b(\d{1,3})(?:st|nd|rd|th)\s+issue\b", text, re.I)
    return f"Issue {match.group(1)}" if match else ""


def _programme(text: str) -> str:
    match = re.search(r"(?:within (?:the framework of )?|under )(?:the )?(.{0,80}?bond (?:programme|program))", text, re.I)
    return _clean_text(match.group(1)) if match else ""


def _coupon_rate(text: str) -> float | None:
    match = re.search(r"(?:coupon rate|fixed annual coupon rate|annual yield)\s*[:,-]?\s*(\d{1,2}(?:[.,]\d+)?)\s*%", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def _maturity_date(text: str) -> str:
    if re.search(r"(?:Maturity Date|Maturity)\s*[:,-]?\s*perpetual", text, re.I):
        return "Perpetual"
    match = re.search(r"(?:Maturity Date|Due date)\s*[:,-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{2}-\d{2})", text, re.I)
    return _iso_date(match.group(1)) if match else ""


def _lifecycle(source_id: str, text: str) -> tuple[str, str]:
    lowered = text.lower()
    if re.search(r"book\w* clos|final price|final yield|priced", lowered):
        return "Priced", "priced"
    if re.search(r"placement (?:was |has been )?(?:completed|carried out)|completed placement|issuance result|number of issued bonds", lowered):
        return "Issued", "placement_completed"
    if source_id == "md-bvm" and "issue date" in lowered and "number of issued bonds" in lowered:
        return "Issued", "issue_result_registered"
    if re.search(r"book(?:building)? (?:opens?|opening)|offer (?:opens?|opening)|special trading session for placement", lowered):
        return "Announced", "offer_open"
    if "guidance" in lowered:
        return "Announced", "bookbuilding"
    if re.search(r"programme (?:registered|approved)|program (?:registered|approved)", lowered):
        return "Announced", "programme_registered"
    if re.search(r"listed|listing|admission|official list", lowered):
        return "Announced", "listed"
    return "Announced", "issue_registered"


def _event_date(text: str) -> str:
    for label in ("Placement period - start/end", "Issue date", "Issuance date", "Admission date", "Date of Listing/Admission to Trading"):
        match = re.search(rf"{re.escape(label)}\s*[:,-]?\s*(\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})", text, re.I)
        if match:
            return _iso_date(match.group(1))
    return ""


def _publication_date(text: str) -> str:
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if match:
        return f"{match.group(1)}T00:00:00"
    match = re.search(r"\b(\d{1,2}[./-]\d{1,2}[./-]20\d{2})\b", text)
    return f"{_iso_date(match.group(1))}T00:00:00" if match else ""


def _leading_date(value: str) -> tuple[str, str]:
    match = re.match(r"\s*(\d{1,2}[./-]\d{1,2}[./-]20\d{2})\s*[-–—]\s*(.+)", value)
    if not match:
        return "", value
    return f"{_iso_date(match.group(1))}T00:00:00", match.group(2).strip()


def _iso_date(value: str) -> str:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    parts = re.split(r"[./-]", value)
    if len(parts) == 3:
        first, second, year = (int(part) for part in parts)
        if second > 12 and first <= 12:
            month, day = first, second
        else:
            day, month = first, second
        return f"{year:04d}-{month:02d}-{day:02d}"
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return ""


def _document_urls(page: str, base_url: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(page)
    values: list[str] = []
    allowed_host = urllib.parse.urlparse(base_url).netloc.lower()
    for href, label in parser.links:
        absolute = urllib.parse.urljoin(base_url, html.unescape(href))
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != allowed_host:
            continue
        if re.search(r"\.(?:pdf|docx?|xlsx?)(?:$|\?)|prospect", parsed.path + " " + label, re.I) and absolute not in values:
            values.append(absolute)
    return values[:10]


def _factual_summary(**values: object) -> str:
    labels = {
        "issuer": "Issuer", "instrument": "Instrument", "isin": "ISIN", "registration": "Registration number",
        "amount": "Amount", "coupon": "Coupon", "maturity": "Maturity", "programme": "Programme",
        "series": "Series/tranche", "stage": "Lifecycle stage",
    }
    parts: list[str] = []
    currency = str(values.get("currency") or "")
    for key in ("issuer", "instrument", "isin", "registration", "amount", "coupon", "maturity", "programme", "series", "stage"):
        value = values.get(key)
        if value in {None, "", 0}:
            continue
        if key == "amount":
            display = f"{float(value):,.0f} {currency}".replace(",", " ")
        elif key == "coupon":
            display = f"{value}%"
        else:
            display = str(value)
        parts.append(f"{labels[key]}: {display}")
    return ". ".join(parts)[:1500]


def _first_heading(page: str) -> str:
    for tag in ("h1", "h2"):
        match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", page, re.I | re.S)
        if match:
            value = _clean_text(re.sub(r"<[^>]+>", " ", match.group(1)))
            if value and value.lower() not in {"news", "information center"}:
                return value
    match = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)', page, re.I)
    return _clean_text(match.group(1)) if match else ""


def _detail_fragment(source_id: str, page: str) -> str:
    patterns = {
        "md-bvm": r'(<section\s+class=["\']contentBox["\'][\s\S]*?</section>)',
        "am-amx": r'(<(?:main|article)\b[\s\S]*?</(?:main|article)>)',
    }
    match = re.search(patterns.get(source_id, r"$^"), page, re.I)
    return match.group(1) if match else page


def _visible_text(page: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(page)
    return _clean_text(" ".join(parser.parts))


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


def _clean_entity(value: str) -> str:
    cleaned = _clean_text(value).strip(' "“”«».,;:-')
    cleaned = cleaned.translate(str.maketrans('', '', '"“”«»'))
    cleaned = re.sub(r"\s+bonds?$", "", cleaned, flags=re.I)
    return re.sub(r"\s+(?:of|on|starting|will)\s*$", "", cleaned, flags=re.I)[:200]


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._href = dict(attrs).get("href") or ""
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, " ".join(self._text)))
            self._href = ""
            self._text = []


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data)
