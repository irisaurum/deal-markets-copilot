from __future__ import annotations

import hashlib
import json
import html
import math
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from .classifier import stable_event_id
from .cnpf_source import CnpfFeedEntry, cnpf_candidate_type, parse_cnpf_atom, parse_cnpf_detail
from .exchange_sources import (
    SourceHealthError,
    is_candidate_title,
    parse_exchange_detail,
    parse_exchange_index,
)
from .models import Event

try:
    import truststore
except ImportError:  # The disabled connector must not break pre-install CI phases.
    truststore = None


USER_AGENT = "DealMarketsCopilot/0.2"
_SYSTEM_CA = Path("/etc/ssl/cert.pem")
SSL_CONTEXT = ssl.create_default_context(cafile=str(_SYSTEM_CA)) if _SYSTEM_CA.exists() else ssl.create_default_context()
CNPF_SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT) if truststore else None


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    content_type: str
    text: str
    etag: str = ""
    last_modified: str = ""


class CnpfFetchError(SourceHealthError):
    def __init__(self, reason: str, diagnostics: dict):
        super().__init__(f"cnpf_moldova: {reason}")
        self.reason = reason
        self.diagnostics = diagnostics


def quote_status(quote: dict) -> str:
    """Classify quote availability without treating missing market data as zero."""
    if quote.get("error"):
        return "error"
    price = quote.get("price")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or not math.isfinite(float(price)) or float(price) <= 0:
        return "unavailable"
    change = quote.get("change_percent")
    if not isinstance(change, (int, float)) or isinstance(change, bool) or not math.isfinite(float(change)):
        return "partial"
    return "valid"


def quote_is_usable(quote: dict) -> bool:
    """A positive last price is usable even when the daily change is unavailable."""
    return quote_status(quote) in {"valid", "partial"}


def load_demo_events(path: str | Path) -> list[Event]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [_event_from_mapping(item) for item in raw]


def fetch_configured_sources(config: dict, timeout: int = 15) -> list[Event]:
    events: list[Event] = []
    failures: list[str] = []
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
        except Exception as exc:
            failures.append(f"{source.get('name', source.get('url', 'RSS'))}: {type(exc).__name__}")
    if failures:
        raise RuntimeError("RSS source failure: " + "; ".join(failures))
    return events


def fetch_cis_disclosures(config: dict, timeout: int = 15) -> list[Event]:
    """Fetch narrowly scoped official CIS disclosures.

    Connectors are opt-in and isolated from the required Russia source groups.
    Each adapter applies its own narrow deal-event allowlist and preserves a
    primary disclosure link. Routine notices such as coupons, redemptions and
    exchange plumbing are intentionally ignored.
    """
    events, runs = fetch_cis_disclosures_with_health(config, timeout)
    failures = [run for run in runs if run.get("required") and run.get("status") != "ok"]
    if failures:
        raise RuntimeError("CIS source failure: " + "; ".join(
            f"{run.get('name')}: {run.get('error') or run.get('status')}" for run in failures
        ))
    return events


def fetch_cis_disclosures_with_health(
    config: dict,
    timeout: int = 15,
    *,
    operational_state: dict | None = None,
    now: datetime | None = None,
) -> tuple[list[Event], list[dict]]:
    """Fetch each enabled CIS source independently and return per-source health.

    Optional exchange failures remain isolated from the existing Russia and
    Uzbekistan processing, while their own health state stays explicit.
    """
    events: list[Event] = []
    runs: list[dict] = []
    poll_state = operational_state if operational_state is not None else {}
    checked_now = now or datetime.now(timezone.utc)
    if checked_now.tzinfo is None:
        raise ValueError("CIS source clock must be timezone-aware")
    for source in config.get("cis_source_registry", []):
        if not source.get("enabled") or not source.get("implemented"):
            continue
        source_id = str(source.get("id") or "unknown")
        required = bool(source.get("required", False))
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            connector = source.get("connector")
            if connector == "uzse_material_facts":
                result = _fetch_uzse_material_facts(source, timeout)
                request_counts = {}
            elif connector == "exchange_news":
                result, request_counts = _fetch_exchange_news(source, timeout)
            elif connector == "cnpf_atom":
                result, request_counts = _fetch_cnpf_atom(
                    source, timeout, poll_state, checked_now.astimezone(timezone.utc)
                )
            else:
                raise SourceHealthError(f"unsupported connector: {connector or 'missing'}")
            events.extend(result)
            run_status = str(request_counts.pop("_status", "ok" if result else "empty"))
            run_error = str(request_counts.pop("_error", "" if result else "Active source returned zero allowed events"))
            runs.append({
                "name": f"cis:{source_id}",
                "source_id": source_id,
                "enabled": True,
                "status": run_status,
                "records": len(result),
                "required": required,
                "checked_at": checked_at,
                "error": run_error,
                **request_counts,
            })
        except CnpfFetchError as exc:
            runs.append({
                "name": f"cis:{source_id}",
                "source_id": source_id,
                "enabled": True,
                "status": "error",
                "records": 0,
                "required": required,
                "checked_at": checked_at,
                "error": f"CnpfFetchError: {exc.reason}",
                **exc.diagnostics,
            })
        except Exception as exc:
            runs.append({
                "name": f"cis:{source_id}",
                "source_id": source_id,
                "status": "error",
                "records": 0,
                "required": required,
                "checked_at": checked_at,
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            })
    return events, runs


def _fetch_cnpf_atom(
    source: dict,
    timeout: int,
    operational_state: dict,
    now: datetime,
) -> tuple[list[Event], dict]:
    source_id = str(source.get("id") or "cnpf_moldova")
    feed_url = str(source.get("feed_url") or source.get("url") or "")
    diagnostics = {
        "poll_eligible": True,
        "request_count": 0,
        "feed_requests": 0,
        "feed_http_status": None,
        "http_status_class": "not_requested",
        "content_type": "",
        "parser_status": "not_started",
        "entries_discovered": 0,
        "entries_in_archive": 0,
        "whitelisted": 0,
        "detail_requests": 0,
        "accepted": 0,
        "review": 0,
        "excluded": 0,
        "duplicates_suppressed": 0,
        "health_reason": "not_started",
    }
    if not _safe_http_url(feed_url):
        raise CnpfFetchError("unsafe_feed_url", diagnostics)

    interval = max(30, int(source.get("poll_interval_minutes", 30)))
    previous = operational_state.get(source_id, {}) if isinstance(operational_state.get(source_id, {}), dict) else {}
    last_successful = _state_timestamp(previous.get("last_successful_poll_at"))
    if last_successful and now < last_successful + timedelta(minutes=interval):
        diagnostics.update({
            "poll_eligible": False,
            "health_reason": "poll_interval_not_elapsed",
            "last_successful_poll_at": last_successful.isoformat(),
            "next_eligible_at": (last_successful + timedelta(minutes=interval)).isoformat(),
        })
        return [], {"_status": "skipped", "_error": "poll_interval_not_elapsed", **diagnostics}

    conditional_headers = {}
    if previous.get("etag"):
        conditional_headers["If-None-Match"] = str(previous["etag"])
    if previous.get("last_modified"):
        conditional_headers["If-Modified-Since"] = str(previous["last_modified"])
    diagnostics.update({"request_count": 1, "feed_requests": 1})
    try:
        response = _get_http_response(
            feed_url,
            timeout,
            accept="application/atom+xml, application/xml, text/xml",
            extra_headers=conditional_headers,
        )
    except Exception as exc:
        diagnostics.update({
            "http_status_class": "transport_error",
            "transport_error": type(exc).__name__,
            "health_reason": "transport_error",
        })
        raise CnpfFetchError("transport_error", diagnostics) from exc
    diagnostics.update({
        "feed_http_status": response.status,
        "http_status_class": _http_status_class(response.status),
        "content_type": response.content_type,
    })
    if response.status == 304:
        if not last_successful or not conditional_headers:
            diagnostics["health_reason"] = "unexpected_not_modified"
            raise CnpfFetchError("unexpected_not_modified", diagnostics)
        diagnostics.update({
            "parser_status": "not_modified",
            "health_reason": "not_modified",
        })
        operational_state[source_id] = {
            **previous,
            "last_successful_poll_at": now.isoformat(),
            "feed_url": feed_url,
        }
        return [], {"_status": "ok", "_error": "", **diagnostics}
    _validate_cnpf_response(response, diagnostics, feed=True)
    try:
        feed = parse_cnpf_atom(response.text, feed_url)
    except SourceHealthError as exc:
        diagnostics.update({"parser_status": "error", "health_reason": _sanitized_health_reason(exc)})
        raise CnpfFetchError(diagnostics["health_reason"], diagnostics) from exc
    diagnostics.update({
        "parser_status": "ok",
        "entries_discovered": len(feed.entries),
        "duplicates_suppressed": feed.duplicates_suppressed,
    })

    archive_days = max(1, min(int(source.get("archive_days", 90)), 730))
    cutoff = now.date() - timedelta(days=archive_days)
    try:
        in_archive = [entry for entry in feed.entries if _entry_date(entry) >= cutoff]
    except SourceHealthError as exc:
        diagnostics.update({"parser_status": "error", "health_reason": _sanitized_health_reason(exc)})
        raise CnpfFetchError(diagnostics["health_reason"], diagnostics) from exc
    candidates = [entry for entry in in_archive if cnpf_candidate_type(entry)]
    previous_fingerprints = (
        previous.get("entry_fingerprints", {})
        if isinstance(previous.get("entry_fingerprints", {}), dict)
        else {}
    )
    fingerprints = {entry.entry_id: _cnpf_entry_fingerprint(entry) for entry in in_archive}
    changed_candidates = [
        entry for entry in candidates
        if previous_fingerprints.get(entry.entry_id) != fingerprints[entry.entry_id]
    ]
    unchanged_candidates = len(candidates) - len(changed_candidates)
    max_details = max(1, min(int(source.get("max_detail_requests", 8)), 8))
    details_to_fetch = changed_candidates[:max_details]
    diagnostics.update({
        "entries_in_archive": len(in_archive),
        "whitelisted": len(candidates),
        "changed_candidates": len(changed_candidates),
        "unchanged_candidates": unchanged_candidates,
        "excluded": len(in_archive) - len(candidates),
    })

    events: list[Event] = []
    completed_changed_ids: set[str] = set()
    for entry in details_to_fetch:
        diagnostics["request_count"] += 1
        diagnostics["detail_requests"] += 1
        try:
            detail = _get_http_response(entry.url, timeout, accept="text/html, application/xhtml+xml")
        except Exception as exc:
            diagnostics.update({
                "http_status_class": "transport_error",
                "transport_error": type(exc).__name__,
                "health_reason": "transport_error",
            })
            raise CnpfFetchError("transport_error", diagnostics) from exc
        diagnostics["http_status_class"] = _http_status_class(detail.status)
        _validate_cnpf_response(detail, diagnostics, feed=False)
        try:
            parsed = parse_cnpf_detail(source, detail.text, entry)
        except SourceHealthError as exc:
            diagnostics.update({"parser_status": "error", "health_reason": _sanitized_health_reason(exc)})
            raise CnpfFetchError(diagnostics["health_reason"], diagnostics) from exc
        if not parsed:
            diagnostics["excluded"] += 1
        events.extend(parsed)
        completed_changed_ids.add(entry.entry_id)

    diagnostics["accepted"] = len(events)
    diagnostics["review"] = sum(not _cnpf_event_complete(event) for event in events)
    diagnostics["health_reason"] = (
        "healthy_zero_whitelisted" if not candidates
        else "healthy_unchanged" if not details_to_fetch
        else "ok"
    )
    next_fingerprints = {
        entry.entry_id: fingerprints[entry.entry_id]
        for entry in in_archive
        if (
            not cnpf_candidate_type(entry)
            or previous_fingerprints.get(entry.entry_id) == fingerprints[entry.entry_id]
            or entry.entry_id in completed_changed_ids
        )
    }
    operational_state[source_id] = {
        "last_successful_poll_at": now.isoformat(),
        "feed_url": feed_url,
        "etag": response.etag,
        "last_modified": response.last_modified,
        "entry_fingerprints": next_fingerprints,
    }
    return events, {"_status": "ok", "_error": "", **diagnostics}


def _validate_cnpf_response(response: HttpResponse, diagnostics: dict, *, feed: bool) -> None:
    if response.status in {403, 429}:
        diagnostics["health_reason"] = f"http_{response.status}"
        raise CnpfFetchError(diagnostics["health_reason"], diagnostics)
    if not 200 <= response.status < 300:
        diagnostics["health_reason"] = f"http_{_http_status_class(response.status)}"
        raise CnpfFetchError(diagnostics["health_reason"], diagnostics)
    content_type = response.content_type.split(";", 1)[0].strip().lower()
    allowed = (
        {"application/atom+xml", "application/xml", "text/xml"}
        if feed else {"text/html", "application/xhtml+xml"}
    )
    if content_type not in allowed:
        diagnostics["health_reason"] = "unexpected_content_type"
        raise CnpfFetchError("unexpected_content_type", diagnostics)
    if not response.text.strip():
        diagnostics["health_reason"] = "empty_response"
        raise CnpfFetchError("empty_response", diagnostics)
    if "<html" in response.text[:500].lower() and feed:
        diagnostics["health_reason"] = "html_challenge_or_error"
        raise CnpfFetchError("html_challenge_or_error", diagnostics)


def _entry_date(entry: CnpfFeedEntry):
    try:
        return datetime.fromisoformat(entry.published_at.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise SourceHealthError("cnpf_moldova: unsafe_entry_timestamp") from exc


def _cnpf_entry_fingerprint(entry: CnpfFeedEntry) -> str:
    payload = json.dumps({
        "entry_id": entry.entry_id,
        "title": entry.title,
        "published_at": entry.published_at,
        "updated_at": entry.updated_at,
        "url": entry.url,
        "summary": entry.summary,
        "category": entry.category,
        "document_urls": list(entry.document_urls),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _state_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _http_status_class(status: int) -> str:
    return f"{status // 100}xx" if 100 <= status <= 599 else "unknown"


def _sanitized_health_reason(exc: Exception) -> str:
    reason = str(exc).split(":", 1)[-1].strip()
    return re.sub(r"[^a-z0-9_:-]+", "_", reason.lower())[:120] or type(exc).__name__.lower()


def _cnpf_event_complete(event: Event) -> bool:
    if event.instrument in {"Corporate bonds", "Share issue"}:
        return bool(
            event.issuer and event.instrument and event.amount is not None and event.currency
            and (event.isin or event.registration_number) and event.lifecycle_stage
        )
    return bool(event.target and event.acquirer and event.lifecycle_stage)


def _fetch_exchange_news(source: dict, timeout: int) -> tuple[list[Event], dict]:
    index_url = str(source.get("index_url") or source.get("url") or "")
    if not _safe_http_url(index_url):
        raise SourceHealthError("Exchange index URL must be HTTP(S)")
    max_pages = max(1, min(int(source.get("max_pages", 1)), 5))
    max_details = max(1, min(int(source.get("max_detail_requests", 12)), 30))
    pages_to_fetch = [index_url]
    entries = []
    index_requests = 0
    for page_url in pages_to_fetch:
        page = _get_text(page_url, timeout)
        index_requests += 1
        parsed, archive_pages = parse_exchange_index(source, page)
        entries.extend(parsed)
        if len(pages_to_fetch) < max_pages:
            for archive_url in archive_pages:
                if archive_url not in pages_to_fetch:
                    pages_to_fetch.append(archive_url)
                    if len(pages_to_fetch) >= max_pages:
                        break
    unique_entries = {entry.source_event_id: entry for entry in entries}
    archive_days = max(1, min(int(source.get("archive_days", 90)), 730))
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=archive_days)
    def inside_archive(entry) -> bool:
        if not entry.published_at:
            return True
        try:
            return datetime.fromisoformat(entry.published_at.replace("Z", "+00:00")).date() >= cutoff
        except ValueError:
            raise SourceHealthError(f"Unsafe publication timestamp for source event {entry.source_event_id}")
    candidates = [
        entry for entry in unique_entries.values()
        if inside_archive(entry) and is_candidate_title(str(source.get("id") or ""), entry.title)
    ][:max_details]
    detail_requests = 0
    events: list[Event] = []
    for entry in candidates:
        detail = _get_text(entry.url, timeout)
        detail_requests += 1
        events.extend(parse_exchange_detail(source, detail, entry.url, entry.title))
    return events, {
        "index_requests": index_requests,
        "detail_requests": detail_requests,
        "candidate_publications": len(candidates),
    }


def _fetch_uzse_material_facts(source: dict, timeout: int) -> list[Event]:
    base_url = str(source.get("url") or "https://uzse.uz/reports/material_facts?locale=en&page=1")
    allowed_facts = {str(value) for value in source.get("fact_numbers", ["25"])}
    max_pages = max(1, min(int(source.get("max_pages", 3)), 10))
    max_items = max(1, min(int(source.get("max_items", 10)), 50))
    events: list[Event] = []
    seen: set[str] = set()
    for page_number in range(1, max_pages + 1):
        page_url = re.sub(r"([?&])page=\d+", rf"\g<1>page={page_number}", base_url)
        page = _get_text(page_url, timeout)
        for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, re.I | re.S):
            cells = [_strip_html(value) for value in re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, re.I | re.S)]
            link_match = re.search(r'href=["\']([^"\']*/reports/\d+/material_fact(?:\?[^"\']*)?)["\']', row_html, re.I)
            if len(cells) < 5 or not link_match:
                continue
            fact_number = next((cell for cell in reversed(cells) if cell.strip().isdigit()), "")
            if fact_number not in allowed_facts:
                continue
            detail_url = urllib.parse.urljoin(base_url, html.unescape(link_match.group(1)))
            if detail_url in seen:
                continue
            seen.add(detail_url)
            published = next((cell for cell in cells if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cell.strip())), "")
            issuer = cells[3].strip() if len(cells) > 3 else ""
            detail = _strip_html(_get_text(detail_url, timeout))
            security_type = _label_value(detail, ("Security type", "Вид ценной бумаги", "Qimmatli qog'oz turi"))
            amount_text = _label_value(detail, ("Total issue amount", "Общая сумма выпуска", "Chiqarilishning umumiy summasi"))
            amount = _uzs_amount(amount_text)
            if not issuer or not published or not security_type:
                continue
            is_bond = bool(re.search(r"bond|облигац", security_type, re.I))
            instrument = "облигаций" if is_bond else "акций"
            amount_label = f" на {amount:,.0f} UZS".replace(",", " ") if amount else ""
            title = f"{issuer} объявил выпуск {instrument}{amount_label}"
            events.append(Event(
                event_id=stable_event_id("uzse-fact-25", detail_url),
                published_at=f"{published}T00:00:00+05:00",
                title=title,
                summary=f"Официальное раскрытие UZSE: {security_type}. {amount_text}"[:1500],
                source=source.get("name", "UZSE material facts"),
                url=detail_url,
                source_type="official_exchange",
                confidence="confirmed",
                amount=amount,
                currency="UZS" if amount else None,
                country=source.get("country", "Uzbekistan"),
                market=source.get("market", "UZSE"),
            ))
            if len(events) >= max_items:
                return events
    return events


def _label_value(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*[:\-]?\s*(.+?)(?=\s{{2,}}[A-ZА-ЯЁOQ]|$)", text, re.I)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" .:;-")[:300]
    return ""


def _uzs_amount(value: str) -> float | None:
    match = re.search(r"(\d[\d\s.,]*)", value or "")
    if not match:
        return None
    compact = re.sub(r"[\s,]", "", match.group(1))
    try:
        return float(compact)
    except ValueError:
        return None


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
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=min(6, len(sources) or 1)) as pool:
        futures = {pool.submit(_fetch_official_page, source, timeout): source for source in sources}
        for future in as_completed(futures):
            try:
                events.extend(future.result())
            except Exception as exc:
                source = futures[future]
                failures.append(f"{source.get('name', source.get('url', 'issuer'))}: {type(exc).__name__}")
    if failures:
        raise RuntimeError("Official source failure: " + "; ".join(failures))
    return events


def _fetch_official_page(source: dict, timeout: int) -> list[Event]:
    if source.get("feed_uid"):
        return _fetch_tilda_feed(source, timeout)
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


def _fetch_tilda_feed(source: dict, timeout: int) -> list[Event]:
    """Read a public Tilda feed used by an official issuer press page."""
    feed_url = str(source.get("feed_url") or "https://feeds.tildaapi.com/api/getfeed/")
    if not _safe_http_url(feed_url):
        raise ValueError("Official feed URL must be HTTP(S)")
    params = urllib.parse.urlencode({
        "feeduid": str(source["feed_uid"]),
        "recid": str(source.get("feed_rec_id") or ""),
        "size": int(source.get("max_items", 20)),
        "slice": 1,
        "sort[date]": "desc",
        "filters[date]": "",
        "getparts": "true",
    })
    payload = _get_json(f"{feed_url}?{params}", timeout)
    terms = [str(term).lower() for term in source.get("include_terms", _deal_terms())]
    excluded = [str(term).lower() for term in source.get("exclude_terms", [])]
    allowed_hosts = {str(host).lower() for host in source.get("allowed_hosts", []) if host}
    events: list[Event] = []
    for row in payload.get("posts", []):
        title = _strip_html(str(row.get("title") or ""))
        summary = _strip_html(str(row.get("descr") or row.get("text") or ""))[:1500]
        combined = f"{title} {summary}".lower()
        direct_url = str(row.get("directlink") or row.get("url") or "").strip()
        host = urllib.parse.urlparse(direct_url).netloc.lower()
        if not title or not _safe_http_url(direct_url):
            continue
        if allowed_hosts and host not in allowed_hosts:
            continue
        if terms and not any(term in combined for term in terms):
            continue
        if excluded and any(term in combined for term in excluded):
            continue
        published = _official_feed_date(str(row.get("date") or row.get("published") or ""), source)
        if not published:
            continue
        events.append(Event(
            event_id=stable_event_id("official-feed", direct_url),
            published_at=published,
            title=title,
            summary=summary,
            source=source.get("name", "Official issuer feed"),
            url=direct_url,
            companies=[source.get("ticker", "")],
            source_type=source.get("source_type", "official_issuer"),
            confidence="confirmed",
        ))
    return events


def _official_feed_date(value: str, source: dict) -> str:
    if not value:
        return ""
    normalized = value.strip().replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        return f"{parsed.isoformat()}{source.get('timezone_offset', '+03:00')}"
    return parsed.isoformat()


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
    except Exception as exc:
        raise RuntimeError(f"Google News RSS unavailable for query: {query}") from exc

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
            quote = {
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
            }
            quote["quote_status"] = quote_status(quote)
            quote["quote_usable"] = quote_is_usable(quote)
            if not quote["quote_usable"]:
                quote["change_percent"] = None
            quotes.append(quote)
        except Exception as exc:
            quote = {
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
            }
            quote["quote_status"] = quote_status(quote)
            quote["quote_usable"] = False
            quotes.append(quote)
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
    if not rows:
        raise RuntimeError(f"Feed returned no RSS items or Atom entries: {url}")

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
    with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
        return json.loads(response.read())


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
                previous = row.get("source_url")
                row["source_url"] = direct
                for source in row.get("sources", []):
                    if isinstance(source, dict) and source.get("url") == previous:
                        source["url"] = direct
                        source["representations"] = _merge_url_representations(source, previous, direct)
                upgraded += 1
    return upgraded


def resolve_google_news_events(events: list[Event], limit: int = 12, workers: int = 6) -> int:
    rows = [{"source_url": event.url, "event": event} for event in events if "news.google.com/rss/articles/" in event.url][:limit]
    upgraded = resolve_google_news_rows(rows, limit=limit, workers=workers)
    for row in rows:
        if row["event"].url != row["source_url"]:
            row["event"].discovery_url = row["event"].url
        row["event"].url = row["source_url"]
    return upgraded


def _merge_url_representations(source: dict, previous: str, direct: str) -> list[dict]:
    raw = list(source.get("representations", [])) if isinstance(source.get("representations"), list) else []
    raw.extend((
        {"name": source.get("name", "Unknown source"), "url": previous, "source_type": source.get("source_type", "public_web"), "published_at": source.get("published_at", "")},
        {"name": source.get("name", "Unknown source"), "url": direct, "source_type": source.get("source_type", "public_web"), "published_at": source.get("published_at", "")},
    ))
    return list({item.get("url"): item for item in raw if isinstance(item, dict) and _safe_http_url(str(item.get("url") or ""))}.values())


def _get_text(url: str, timeout: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def _get_http_response(
    url: str,
    timeout: int,
    accept: str = "*/*",
    *,
    extra_headers: dict[str, str] | None = None,
) -> HttpResponse:
    if CNPF_SSL_CONTEXT is None:
        raise RuntimeError("CNPF platform trust store dependency is unavailable")
    headers = {"User-Agent": USER_AGENT, "Accept": accept, **(extra_headers or {})}
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=timeout, context=CNPF_SSL_CONTEXT)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(exc.headers.get_content_charset() or "utf-8", errors="replace")
        return HttpResponse(
            int(exc.code),
            str(exc.headers.get_content_type() or ""),
            body,
            str(exc.headers.get("ETag") or ""),
            str(exc.headers.get("Last-Modified") or ""),
        )
    with response:
        body = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        return HttpResponse(
            int(getattr(response, "status", 200)),
            str(response.headers.get_content_type() or ""),
            body,
            str(response.headers.get("ETag") or ""),
            str(response.headers.get("Last-Modified") or ""),
        )


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
