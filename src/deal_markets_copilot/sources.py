from __future__ import annotations

import json
import html
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
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
        try:
            events.extend(fetch_feed(
                source["url"],
                source_name=source.get("name", source["url"]),
                source_type=source.get("source_type", "public_web"),
                timeout=timeout,
                include_terms=source.get("include_terms", []),
                exclude_terms=source.get("exclude_terms", []),
            ))
        except Exception:
            continue
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
    primary = config.get("primary_sources", {})
    sources = [source for source in primary.get("issuers", []) + primary.get("regulators", []) if source.get("enabled", True)]
    events: list[Event] = []
    with ThreadPoolExecutor(max_workers=min(6, len(sources) or 1)) as pool:
        futures = [pool.submit(_fetch_official_page, source, timeout) for source in sources]
        for future in as_completed(futures):
            try:
                events.extend(future.result())
            except Exception:
                continue
    return events


def _fetch_official_page(source: dict, timeout: int) -> list[Event]:
    url = source.get("url", "")
    page = _get_text(url, timeout)
    parser = _LinkParser()
    parser.feed(page)
    allowed_host = urllib.parse.urlparse(url).netloc.lower()
    terms = [term.lower() for term in source.get("include_terms", _deal_terms())]
    seen: set[str] = set()
    events: list[Event] = []
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
        if clean_title.strip().lower() in {"облигации", "еврооблигации 2023", "bond", "bonds"}:
            continue
        event_date = title_date or published
        if not event_date:
            continue
        events.append(Event(
            event_id=stable_event_id("official-page", absolute),
            published_at=event_date,
            title=clean_title,
            summary=summary,
            source=source.get("name", "Official source"),
            url=absolute,
            companies=[source.get("ticker", "")],
            source_type=source.get("source_type", "official_issuer"),
            confidence="confirmed",
        ))
        if len(events) >= int(source.get("max_items", 20)):
            break
    return events


def fetch_sec_deal_filings(config: dict, timeout: int = 20) -> list[Event]:
    """Fetch transaction filings from the official free SEC submissions API."""
    settings = config.get("primary_sources", {}).get("sec_edgar", {})
    if not settings.get("enabled", False):
        return []
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=int(settings.get("archive_days", 540)))
    max_per_company = int(settings.get("max_per_company", 5))
    user_agent = settings.get("user_agent", "DealMarketsCopilot irisaurum@users.noreply.github.com")
    events: list[Event] = []
    for company in settings.get("companies", []):
        cik = str(company.get("cik", "")).lstrip("0")
        if not cik:
            continue
        endpoint = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
        payload = _get_json(endpoint, timeout, user_agent=user_agent)
        recent = payload.get("filings", {}).get("recent", {})
        columns = list(recent)
        rows = [dict(zip(columns, values, strict=False)) for values in zip(*(recent.get(column, []) for column in columns))] if columns else []
        accepted = 0
        for row in rows:
            form = str(row.get("form") or "")
            filing_date = str(row.get("filingDate") or "")
            try:
                if datetime.fromisoformat(filing_date).date() < cutoff:
                    continue
            except ValueError:
                continue
            items = str(row.get("items") or "")
            transaction_form = form in {"S-4", "S-4/A", "PREM14A", "DEFM14A", "SC 14D9", "SC TO-T", "SC TO-T/A"}
            completed_deal = form in {"8-K", "8-K/A"} and "2.01" in items
            if not (transaction_form or completed_deal):
                continue
            accession = str(row.get("accessionNumber") or "")
            document = str(row.get("primaryDocument") or "")
            if not accession or not document:
                continue
            company_name = str(payload.get("name") or company.get("company") or cik)
            direct_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{document}"
            description = str(row.get("primaryDocDescription") or "").strip()
            events.append(Event(
                event_id=f"sec-{accession.lower()}",
                published_at=f"{filing_date}T00:00:00-04:00",
                title=f"{company_name}: SEC {form} transaction filing",
                summary=f"Official transaction filing. {description}. Items: {items}. Merger, acquisition or disposition disclosure.",
                source="SEC EDGAR",
                url=direct_url,
                companies=[company.get("ticker", "")],
                source_type="official_regulator",
                confidence="confirmed",
            ))
            accepted += 1
            if accepted >= max_per_company:
                break
    return events


def fetch_gdelt_deal_news(config: dict, timeout: int = 20) -> list[Event]:
    """Use free GDELT only as direct-link discovery; all claims remain unverified."""
    settings = config.get("discovery_sources", {}).get("gdelt", {})
    if not settings.get("enabled", False):
        return []
    events: list[Event] = []
    for company in config.get("coverage", []):
        name = company.get("company")
        if not name:
            continue
        query = f'"{name}" (acquisition OR merger OR IPO OR bond OR "share placement")'
        params = urllib.parse.urlencode({
            "query": query, "mode": "ArtList", "maxrecords": int(settings.get("max_items_per_company", 10)),
            "format": "json", "timespan": settings.get("timespan", "7d"), "sort": "HybridRel",
        })
        payload = _get_json(f"https://api.gdeltproject.org/api/v2/doc/doc?{params}", timeout)
        for row in payload.get("articles", []):
            title = str(row.get("title") or "").strip()
            url = str(row.get("url") or "").strip()
            if not title or not _safe_http_url(url):
                continue
            events.append(Event(
                event_id=stable_event_id(title, url),
                published_at=_gdelt_date(str(row.get("seendate") or "")),
                title=title,
                summary="GDELT discovery result; verify against a primary company or regulatory source.",
                source=str(row.get("domain") or "GDELT"),
                url=url,
                companies=[company.get("ticker", "")],
                source_type="public_discovery",
                confidence="unverified",
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


def filter_recent_events(events: list[Event], lookback: str, now: datetime | None = None) -> list[Event]:
    match = re.match(r"(\d+)d", str(lookback).lower())
    days = int(match.group(1)) if match else 1
    cutoff = (now or datetime.now(timezone.utc)).astimezone(timezone.utc) - timedelta(days=days)
    recent: list[Event] = []
    for event in events:
        try:
            try:
                published = datetime.fromisoformat(event.published_at.replace("Z", "+00:00"))
            except ValueError:
                from email.utils import parsedate_to_datetime
                published = parsedate_to_datetime(event.published_at)
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if published.astimezone(timezone.utc) >= cutoff:
                recent.append(event)
        except (TypeError, ValueError):
            continue
    return recent


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


def _get_json(url: str, timeout: int, user_agent: str = USER_AGENT) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
            return json.loads(response.read())
    except Exception:
        return {}


def resolve_google_news_url(url: str, timeout: int = 20) -> str:
    """Resolve a Google News RSS article token to the publisher's direct URL."""
    if "news.google.com/rss/articles/" not in url:
        return url
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
            page = response.read().decode("utf-8", errors="replace")
        signature = re.search(r'data-n-a-sg="([^"]+)"', page)
        timestamp = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not signature or not timestamp:
            return url
        token = url.split("/articles/", 1)[1].split("?", 1)[0]
        request_payload = [
            "garturlreq",
            [["X", "X", ["FINANCE_TOP_INDICES", "WEB_TEST_1_0_0"], None, None, 1, 1, "US:en", None, 180, None, None, None, None, None, 0, None, None, [1608992183, 723341000]], "X", "X", 1, [2, 3, 4, 8], 1, 0, "655000234", 0, 0, None, 0],
            token,
            int(timestamp.group(1)),
            signature.group(1),
        ]
        inner = json.dumps(request_payload, separators=(",", ":"))
        outer = json.dumps([[["Fbv4je", inner, None, "generic"]]], separators=(",", ":"))
        data = urllib.parse.urlencode({"f.req": outer}).encode()
        batch_request = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je",
            data=data,
            headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        with urllib.request.urlopen(batch_request, timeout=timeout, context=SSL_CONTEXT) as response:
            result = response.read().decode("utf-8", errors="replace")
        match = re.search(r'\[\\"garturlres\\",\\"(https?://.+?)\\",\d+\]', result)
        direct = match.group(1).replace(r"\u003d", "=").replace(r"\u0026", "&") if match else ""
        return direct if _safe_http_url(direct) and "news.google.com" not in direct else url
    except Exception:
        return url


def resolve_google_news_rows(rows: list[dict], limit: int = 30, workers: int = 6) -> int:
    """Upgrade stored Google redirect URLs in parallel without dropping failed rows."""
    candidates = [row for row in rows if "news.google.com/rss/articles/" in str(row.get("source_url") or "")][:limit]
    if not candidates:
        return 0
    upgraded = 0
    with ThreadPoolExecutor(max_workers=min(workers, len(candidates))) as pool:
        futures = {pool.submit(resolve_google_news_url, row["source_url"]): row for row in candidates}
        for future in as_completed(futures):
            row = futures[future]
            try:
                direct = future.result()
            except Exception:
                continue
            if direct != row.get("source_url"):
                row["source_url"] = direct
                upgraded += 1
    return upgraded


def resolve_google_news_events(events: list[Event], limit: int = 12, workers: int = 6) -> int:
    rows = [{"source_url": event.url, "event": event} for event in events if "news.google.com/rss/articles/" in event.url][:limit]
    upgraded = resolve_google_news_rows(rows, limit=limit, workers=workers)
    for row in rows:
        row["event"].url = row["source_url"]
    return upgraded


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


def _gdelt_date(value: str) -> str:
    try:
        return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return ""


def _safe_http_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


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
    if match and match.group(2).lower() in months:
        date = f"{int(match.group(3)):04d}-{months[match.group(2).lower()]:02d}-{int(match.group(1)):02d}T00:00:00+03:00"
        return date, match.group(4).strip()
    numeric = re.match(r"^(\d{1,2})/(\d{1,2})/(20\d{2})\s+(.+)$", value)
    if numeric:
        date = f"{int(numeric.group(3)):04d}-{int(numeric.group(1)):02d}-{int(numeric.group(2)):02d}T00:00:00+03:00"
        return date, numeric.group(4).strip()
    return "", value


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
