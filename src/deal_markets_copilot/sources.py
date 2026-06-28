from __future__ import annotations

import json
import html
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from .classifier import stable_event_id
from .models import Event


USER_AGENT = "DealMarketsCopilot/0.2"
_SYSTEM_CA = Path("/etc/ssl/cert.pem")
SSL_CONTEXT = ssl.create_default_context(cafile=str(_SYSTEM_CA)) if _SYSTEM_CA.exists() else ssl.create_default_context()


def load_demo_events(path: str | Path) -> list[Event]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [_event_from_mapping(item) for item in raw]


def fetch_configured_sources(config: dict, timeout: int = 15) -> list[Event]:
    events: list[Event] = []
    for source in config.get("sources", []):
        if not source.get("enabled"):
            continue
        events.extend(fetch_feed(
            source["url"],
            source_name=source.get("name", source["url"]),
            source_type=source.get("source_type", "public_web"),
            timeout=timeout,
            include_terms=source.get("include_terms", []),
            exclude_terms=source.get("exclude_terms", []),
        ))
    return events


def fetch_moex_disclosures(config: dict, timeout: int = 15) -> list[Event]:
    """Fetch direct MOEX disclosure/news records from the official ISS API."""
    settings = config.get("primary_sources", {}).get("moex", {})
    if not settings.get("enabled", True):
        return []
    limit = int(settings.get("max_items", 80))
    terms = [term.lower() for term in settings.get("include_terms", _deal_terms())]
    params = urllib.parse.urlencode({
        "iss.meta": "off",
        "sitenews.columns": "id,title,published_at,tag",
        "start": 0,
    })
    endpoint = f"https://iss.moex.com/iss/sitenews.json?{params}"
    payload = _get_json(endpoint, timeout)
    events: list[Event] = []
    for row in _rows(payload.get("sitenews", {}))[:limit]:
        title = html.unescape(str(row.get("title") or "").strip())
        if not title or not any(term in title.lower() for term in terms):
            continue
        news_id = row.get("id")
        detail_url = f"https://iss.moex.com/iss/sitenews/{news_id}.json?iss.meta=off"
        detail = _get_json(detail_url, timeout)
        detail_rows = _rows(detail.get("content", {})) or _rows(detail.get("sitenews", {}))
        body = " ".join(str(value) for item in detail_rows for value in item.values() if isinstance(value, str))
        public_url = f"https://www.moex.com/n{news_id}"
        events.append(Event(
            event_id=f"moex-{news_id}",
            published_at=str(row.get("published_at") or ""),
            title=title,
            summary=_strip_html(body)[:1500],
            source="MOEX disclosure",
            url=public_url,
            source_type="official_exchange",
            confidence="confirmed",
        ))
    return events


def fetch_official_issuer_news(config: dict, timeout: int = 15) -> list[Event]:
    """Collect transaction-related links directly from configured issuer IR pages."""
    events: list[Event] = []
    for source in config.get("primary_sources", {}).get("issuers", []):
        if not source.get("enabled", True):
            continue
        url = source.get("url", "")
        try:
            page = _get_text(url, timeout)
        except Exception:
            continue
        parser = _LinkParser()
        parser.feed(page)
        allowed_host = urllib.parse.urlparse(url).netloc.lower()
        terms = [term.lower() for term in source.get("include_terms", _deal_terms())]
        seen: set[str] = set()
        for href, label in parser.links:
            title = re.sub(r"\s+", " ", html.unescape(label)).strip()
            absolute = urllib.parse.urljoin(url, href)
            parsed = urllib.parse.urlparse(absolute)
            if not title or not any(term in title.lower() for term in terms):
                continue
            if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != allowed_host or absolute in seen:
                continue
            seen.add(absolute)
            published, summary = _page_metadata(absolute, timeout)
            title_date, clean_title = _date_from_title(title)
            events.append(Event(
                event_id=stable_event_id("official-issuer", absolute),
                published_at=published or title_date or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                title=clean_title,
                summary=summary,
                source=source.get("name", "Issuer IR"),
                url=absolute,
                companies=[source.get("ticker", "")],
                source_type="official_issuer",
                confidence="confirmed",
            ))
            if len(events) >= int(source.get("max_items", 20)):
                break
    return events


def fetch_company_news(config: dict, timeout: int = 15) -> list[Event]:
    """Fetch recent company news from Google News RSS without an API key."""
    live = config.get("live_data", {})
    lookback = effective_news_lookback(live)
    max_items = int(live.get("max_news_per_company", 8))
    events: list[Event] = []
    for company in config.get("coverage", []):
        query = company.get("news_query") or company.get("company")
        if not query:
            continue
        events.extend(_fetch_google_news(
            query=query,
            lookback=lookback,
            max_items=max_items,
            timeout=timeout,
            companies=[company.get("ticker", "")],
            exclude_terms=company.get("exclude_terms", []),
        ))
    return events


def fetch_deal_news(config: dict, timeout: int = 15) -> list[Event]:
    """Fetch market-wide transaction news so the radar is not limited to three issuers."""
    live = config.get("live_data", {})
    lookback = effective_news_lookback(live)
    max_items = int(live.get("max_deal_news_per_query", 15))
    events: list[Event] = []
    for query in config.get("deal_queries", []):
        if not query.get("enabled", True) or not query.get("query"):
            continue
        events.extend(_fetch_google_news(
            query=query["query"],
            lookback=lookback,
            max_items=max_items,
            timeout=timeout,
            source_type="public_deal_news",
            exclude_terms=query.get("exclude_terms", []),
        ))
    return events


def fetch_deal_archive_news(config: dict, timeout: int = 15) -> list[Event]:
    """Fetch a rolling discovery window for the persistent deal archive.

    These events feed the precedent database only; they never inflate the 24h live radar.
    """
    live = config.get("live_data", {})
    lookback = live.get("archive_lookback", "90d")
    max_items = int(live.get("max_archive_items_per_query", 40))
    events: list[Event] = []
    for query in config.get("deal_queries", []):
        if query.get("enabled", True) and query.get("query"):
            events.extend(_fetch_google_news(
                query=query["query"], lookback=lookback, max_items=max_items,
                timeout=timeout, source_type="archive_discovery",
                exclude_terms=query.get("exclude_terms", []),
            ))
    for company in config.get("coverage", []):
        query = company.get("news_query") or company.get("company")
        if query:
            events.extend(_fetch_google_news(
                query=query, lookback=lookback, max_items=max_items,
                timeout=timeout, companies=[company.get("ticker", "")],
                source_type="archive_discovery", exclude_terms=company.get("exclude_terms", []),
            ))
    return events


def effective_news_lookback(live_config: dict, now: datetime | None = None) -> str:
    """Use 24h normally and a short 72h catch-up window around weekends."""
    current = now or datetime.now().astimezone()
    if current.weekday() in {0, 5, 6}:
        return live_config.get("catchup_lookback", "3d")
    return live_config.get("news_lookback", "1d")


def _fetch_google_news(
    query: str,
    lookback: str,
    max_items: int,
    timeout: int,
    companies: list[str] | None = None,
    source_type: str = "public_news",
    exclude_terms: list[str] | None = None,
) -> list[Event]:
    full_query = f"({query}) when:{lookback}"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": full_query,
        "hl": "ru",
        "gl": "RU",
        "ceid": "RU:ru",
    })
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
            root = ET.fromstring(response.read())
    except Exception:
        return []

    events: list[Event] = []
    excluded = [term.lower() for term in (exclude_terms or [])]
    for row in root.findall(".//item")[:max_items]:
        title = _text(row, "title")
        link = _text(row, "link")
        published = _text(row, "pubDate")
        source_node = row.find("source")
        source_name = (source_node.text or "Google News").strip() if source_node is not None else "Google News"
        description = _strip_html(_text(row, "description"))
        if not title:
            continue
        combined = f"{title} {description}".lower()
        if any(term in combined for term in excluded):
            continue
        events.append(Event(
            event_id=stable_event_id(title, link),
            published_at=published,
            title=title,
            summary=description,
            source=source_name,
            url=link,
            companies=companies or [],
            source_type=source_type,
            confidence="unverified",
        ))
    return events


def fetch_moex_quotes(config: dict, timeout: int = 15) -> list[dict]:
    """Fetch current/delayed MOEX market data for the configured coverage."""
    quotes: list[dict] = []
    for company in config.get("coverage", []):
        secid = company.get("moex_secid")
        if not secid:
            continue
        params = urllib.parse.urlencode({
            "iss.meta": "off",
            "iss.only": "marketdata,securities",
            "marketdata.columns": "SECID,LAST,LASTTOPREVPRICE,VALTODAY,UPDATETIME",
            "securities.columns": "SECID,SHORTNAME,PREVPRICE",
        })
        endpoint = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{urllib.parse.quote(secid)}.json?{params}"
        request = urllib.request.Request(endpoint, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
                payload = json.loads(response.read())
            market_rows = _rows(payload.get("marketdata", {}))
            security_rows = _rows(payload.get("securities", {}))
            market = next((row for row in market_rows if row.get("LAST") is not None), market_rows[-1] if market_rows else {})
            security = next((row for row in security_rows if row.get("PREVPRICE") is not None), security_rows[-1] if security_rows else {})
            quotes.append({
                "ticker": secid,
                "company": company.get("company", security.get("SHORTNAME", secid)),
                "price": market.get("LAST"),
                "change_percent": market.get("LASTTOPREVPRICE"),
                "turnover": market.get("VALTODAY"),
                "updated": market.get("UPDATETIME") or "market close",
                "currency": "RUB",
                "source": "MOEX ISS",
                "source_url": f"https://www.moex.com/ru/issue.aspx?board=TQBR&code={urllib.parse.quote(secid)}",
                "api_url": endpoint,
            })
        except Exception as exc:
            quotes.append({
                "ticker": secid,
                "company": company.get("company", secid),
                "price": None,
                "change_percent": None,
                "turnover": None,
                "updated": "unavailable",
                "currency": "RUB",
                "source": "MOEX ISS",
                "source_url": f"https://www.moex.com/ru/issue.aspx?board=TQBR&code={urllib.parse.quote(secid)}",
                "api_url": endpoint,
                "error": str(exc),
            })
    return quotes


def fetch_feed(
    url: str,
    source_name: str,
    source_type: str = "public_web",
    timeout: int = 15,
    include_terms: list[str] | None = None,
    exclude_terms: list[str] | None = None,
) -> list[Event]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
        root = ET.fromstring(response.read())

    rows = root.findall(".//item")
    atom = False
    if not rows:
        rows = root.findall("{http://www.w3.org/2005/Atom}entry")
        atom = True

    events: list[Event] = []
    for row in rows[:50]:
        if atom:
            title = _text(row, "{http://www.w3.org/2005/Atom}title")
            summary = _text(row, "{http://www.w3.org/2005/Atom}summary") or _text(row, "{http://www.w3.org/2005/Atom}content")
            published = _text(row, "{http://www.w3.org/2005/Atom}updated") or _text(row, "{http://www.w3.org/2005/Atom}published")
            link_node = row.find("{http://www.w3.org/2005/Atom}link")
            link = link_node.attrib.get("href", "") if link_node is not None else ""
        else:
            title = _text(row, "title")
            summary = _text(row, "description")
            published = _text(row, "pubDate")
            link = _text(row, "link")
        if not title:
            continue
        combined = f"{title} {_strip_html(summary)}".lower()
        if include_terms and not any(term.lower() in combined for term in include_terms):
            continue
        if exclude_terms and any(term.lower() in combined for term in exclude_terms):
            continue
        events.append(Event(
            event_id=stable_event_id(title, link),
            published_at=published,
            title=title,
            summary=summary,
            source=source_name,
            url=link,
            source_type=source_type,
            confidence="confirmed" if link else "unverified",
        ))
    return events


def _event_from_mapping(item: dict) -> Event:
    data = dict(item)
    data.setdefault("event_id", stable_event_id(data.get("title", ""), data.get("url", "")))
    return Event(**data)


def _text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return "" if child is None or child.text is None else child.text.strip()


def _rows(block: dict) -> list[dict]:
    columns = block.get("columns", [])
    return [dict(zip(columns, values, strict=False)) for values in block.get("data", [])]


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _get_json(url: str, timeout: int) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
            return json.loads(response.read())
    except Exception:
        return {}


def _get_text(url: str, timeout: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def _page_metadata(url: str, timeout: int) -> tuple[str, str]:
    try:
        page = _get_text(url, timeout)
    except Exception:
        return "", ""
    date_patterns = [
        r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|datePublished)["\'][^>]+content=["\']([^"\']+)',
        r'<time[^>]+datetime=["\']([^"\']+)',
    ]
    description_patterns = [
        r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\'][^>]+content=["\']([^"\']+)',
    ]
    published = next((match.group(1) for pattern in date_patterns if (match := re.search(pattern, page, re.I))), "")
    summary = next((_strip_html(match.group(1)) for pattern in description_patterns if (match := re.search(pattern, page, re.I))), "")
    return published, summary[:1500]


def _deal_terms() -> list[str]:
    return [
        "слиян", "поглощ", "приобрет", "сделк", "ipo", "spo", "размещ",
        "облигац", "выпуск", "эмисси", "bond", "acquisition", "offering",
    ]


def _date_from_title(value: str) -> tuple[str, str]:
    months = {
        "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
        "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    }
    match = re.match(r"^(\d{1,2})\s+([а-яё]+)\s+(20\d{2})\s+(.+)$", value, re.I)
    if not match or match.group(2).lower() not in months:
        return "", value
    date = f"{int(match.group(3)):04d}-{months[match.group(2).lower()]:02d}-{int(match.group(1)):02d}T00:00:00+03:00"
    return date, match.group(4).strip()


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
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
