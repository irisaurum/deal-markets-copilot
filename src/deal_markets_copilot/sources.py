from __future__ import annotations

import json
import html
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
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
        ))
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


def fetch_feed(url: str, source_name: str, source_type: str = "public_web", timeout: int = 15) -> list[Event]:
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
