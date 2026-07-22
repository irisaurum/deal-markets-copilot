from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser

from .exchange_sources import SourceHealthError, validate_public_page
from .models import Event


ATOM_NS = "http://www.w3.org/2005/Atom"
SOURCE_ID = "cnpf_moldova"
SOURCE_OPERATOR = "CNPF Moldova"


@dataclass(frozen=True, slots=True)
class CnpfFeedEntry:
    entry_id: str
    title: str
    published_at: str
    updated_at: str
    url: str
    summary: str = ""
    category: str = ""
    document_urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CnpfFeed:
    feed_id: str
    title: str
    updated_at: str
    entries: tuple[CnpfFeedEntry, ...]
    duplicates_suppressed: int = 0


_EXCLUSIONS = (
    r"\basigur(?:are|ări|ator)",
    r"\bsolvabilitat",
    r"\bconsumator|\bpeti(?:ție|ţii|ții)|\breclama",
    r"\bsanc(?:ți|ţi)un|\bamend[ăa]",
    r"\blicen(?:ță|ţă|ței|ţei)|retragerea licen",
    r"\blichidare|\binsolvabil|\bfaliment",
    r"\bnumir(?:e|ea)|\bguvernan",
    r"raport(?:ul)? anual|\bconsultare public",
    r"\bstatistic|mentenan(?:ță|ţă)|actualizarea registrului|corectare tehnic",
    r"plata cuponului|plata dob(?:â|a)nzii|achitarea dob(?:â|a)nzii|\brambursare|\brăscumpărare|\brascumparare",
    r"valori mobiliare de stat|titluri de stat|obliga(?:ți|ţi)uni municipale|\bsuveran",
    r"\binstruire|\bseminar|\bconferin|\bachizi(?:ție|ţie) public|\bvacan(?:ță|ţă)|\bconcurs pentru",
    r"comunicat de pres[ăa]|nout(?:ăț|ăţ)i institu(?:ț|ţ)ionale|programul de activitate",
)

_DCM_ALLOW = (
    r"(?:rezultat(?:ele|ul)?|totalurile).{0,100}(?:emisiun|plas(?:ament|ării)).{0,80}obliga",
    r"obliga(?:ți|ţi)un.{0,100}(?:emise|plasate|emisiunii|plasamentului)",
    r"(?:aprobarea|autorizarea).{0,120}prospect.{0,100}obliga",
    r"(?:aprobarea|autorizarea).{0,120}program.{0,80}obliga",
    r"confirmarea.{0,100}(?:rezultat|emisiun).{0,80}obliga",
)

_ECM_ALLOW = (
    r"(?:rezultat(?:ele|ul)?|totalurile).{0,100}emisiun.{0,80}ac(?:ț|ţ)iuni",
    r"emisiun(?:e|ii) suplimentar.{0,80}ac(?:ț|ţ)iuni",
    r"majorarea capitalului.{0,120}emisiun.{0,80}ac(?:ț|ţ)iuni",
    r"(?:aprobarea|autorizarea).{0,120}(?:ofert|prospect).{0,100}ac(?:ț|ţ)iuni",
)

_MA_ALLOW = (
    r"(?:aprobarea|autorizarea).{0,120}ofert.{0,80}(?:preluare|obligator)",
    r"ofert.{0,80}(?:preluare|obligator).{0,120}(?:aprobat|autorizat)",
    r"(?:squeeze[- ]?out|retragere obligatorie|achizi(?:ț|ţ)ionare obligatorie)",
    r"(?:achizi(?:ț|ţ)ie|concentrare).{0,120}(?:ofertant|dob(?:â|a)nditor|societate.{0,20}vizat)",
)

_RESTRICTION_PATTERNS = (
    r"reproducerea.{0,100}(?:interzis|numai|doar).{0,80}(?:acord|consim(?:ț|ţ)(?:ă|a)m(?:â|a)nt|permisiun)",
    r"acordul prealabil.{0,100}(?:cnpf|autor)",
    r"consim(?:ț|ţ)(?:ă|a)m(?:â|a)ntul prealabil",
)


def parse_cnpf_atom(payload: str, feed_url: str) -> CnpfFeed:
    if not payload.strip():
        raise SourceHealthError("cnpf_moldova: missing_feed")
    lowered = payload[:4096].lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise SourceHealthError("cnpf_moldova: unsafe_xml_declaration")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise SourceHealthError("cnpf_moldova: malformed_feed") from exc
    if root.tag != f"{{{ATOM_NS}}}feed":
        raise SourceHealthError("cnpf_moldova: missing_atom_feed_root")

    feed_id = _xml_text(root, "id")
    title = _xml_text(root, "title")
    updated = _xml_text(root, "updated")
    if not feed_id or not title or not _iso_timestamp(updated):
        raise SourceHealthError("cnpf_moldova: feed_metadata_drift")

    entries: list[CnpfFeedEntry] = []
    seen: set[str] = set()
    duplicates = 0
    for node in root.findall(f"{{{ATOM_NS}}}entry"):
        entry_id = _xml_text(node, "id")
        entry_title = _clean_text(_xml_text(node, "title"))
        published = _xml_text(node, "published")
        entry_updated = _xml_text(node, "updated")
        if not entry_id:
            raise SourceHealthError("cnpf_moldova: missing_entry_id")
        if entry_id in seen:
            duplicates += 1
            continue
        seen.add(entry_id)
        timestamp = published or entry_updated
        if not entry_title or not _iso_timestamp(timestamp):
            raise SourceHealthError(f"cnpf_moldova: entry_structure_drift:{_safe_reason(entry_id)}")
        canonical, documents = _entry_links(node, feed_url)
        if not canonical:
            raise SourceHealthError(f"cnpf_moldova: missing_canonical_link:{_safe_reason(entry_id)}")
        summary = _clean_text(_xml_text(node, "summary") or _xml_text(node, "content"))[:2000]
        category_node = node.find(f"{{{ATOM_NS}}}category")
        category = _clean_text(
            str(category_node.get("label") or category_node.get("term") or "")
            if category_node is not None else ""
        )
        entries.append(CnpfFeedEntry(
            entry_id=entry_id,
            title=entry_title,
            published_at=published or entry_updated,
            updated_at=entry_updated or published,
            url=canonical,
            summary=summary,
            category=category,
            document_urls=tuple(documents),
        ))
    if not entries:
        raise SourceHealthError("cnpf_moldova: unexpected_empty_feed")
    entries.sort(key=lambda item: (item.published_at, item.entry_id), reverse=True)
    return CnpfFeed(feed_id, title, updated, tuple(entries), duplicates)


def cnpf_candidate_type(entry: CnpfFeedEntry) -> str:
    text = _fold(f"{entry.title} {entry.summary} {entry.category}")
    if any(re.search(pattern, text, re.I | re.S) for pattern in _EXCLUSIONS):
        return ""
    if any(re.search(pattern, text, re.I | re.S) for pattern in _DCM_ALLOW):
        return "DCM"
    if any(re.search(pattern, text, re.I | re.S) for pattern in _ECM_ALLOW):
        return "ECM"
    if any(re.search(pattern, text, re.I | re.S) for pattern in _MA_ALLOW):
        return "M&A"
    return ""


def parse_cnpf_detail(source: dict, page: str, entry: CnpfFeedEntry) -> list[Event]:
    validate_public_page(page, SOURCE_OPERATOR)
    canonical_url = canonical_cnpf_url(entry.url, str(source.get("feed_url") or source.get("url") or ""))
    if not canonical_url:
        raise SourceHealthError("cnpf_moldova: unresolved_canonical_link")
    article_html = _article_fragment(page)
    article_text = _visible_text(article_html)
    if not article_text:
        raise SourceHealthError("cnpf_moldova: empty_detail_content")
    if any(re.search(pattern, _fold(article_text), re.I | re.S) for pattern in _RESTRICTION_PATTERNS):
        raise SourceHealthError("cnpf_moldova: page_specific_restriction")

    combined = _clean_text(f"{entry.title} {entry.summary} {article_text}")
    deal_type = cnpf_candidate_type(CnpfFeedEntry(
        entry.entry_id, entry.title, entry.published_at, entry.updated_at,
        entry.url, combined, entry.category, entry.document_urls,
    ))
    if not deal_type:
        return []

    issuer = _labeled_entity(combined, ("emitent", "emitentul", "emitentului"))
    target = _labeled_entity(combined, ("societatea vizată", "societatea vizata", "ținta", "tinta"))
    acquirer = _labeled_entity(combined, ("ofertant", "achizitor", "dobânditor", "dobanditor"))
    identities = _isins(combined) or _registration_numbers(combined) or [""]
    amount, currency = _amount_currency(combined)
    event_date = _event_date(combined) or entry.published_at[:10]
    lifecycle, sub_stage = _lifecycle(deal_type, combined, issuer, identities[0], amount, currency)
    document_urls = sorted(set(entry.document_urls) | set(_document_urls(article_html, canonical_url)))
    programme = _capture(combined, r"(?:program(?:ul|ului)?)[^.;]{0,20}(?:nr\.?\s*)?([A-Z0-9./-]{2,40})")
    series = _capture(combined, r"(?:seria|tran(?:ș|s)a)\s*[:#-]?\s*([A-Z0-9./-]{1,40})")
    stake = _stake(combined)
    events: list[Event] = []
    for position, identity in enumerate(identities):
        isin = identity if identity in _isins(combined) else ""
        registration = identity if identity and not isin else ""
        safe_identity = re.sub(r"[^a-z0-9]+", "-", identity.lower()).strip("-")
        identity_suffix = safe_identity or str(position + 1)
        entry_hash = hashlib.sha256(entry.entry_id.encode("utf-8")).hexdigest()[:16]
        instrument = "Corporate bonds" if deal_type == "DCM" else "Share issue" if deal_type == "ECM" else "Takeover offer"
        flags: list[str] = []
        if deal_type in {"DCM", "ECM"} and not identity:
            flags.append("missing_security_identity")
        summary = _factual_summary(
            deal_type=deal_type, issuer=issuer, target=target, acquirer=acquirer,
            instrument=instrument, identity=identity, amount=amount, currency=currency,
            stage=lifecycle, event_date=event_date, stake=stake,
        )
        events.append(Event(
            event_id=f"{SOURCE_ID}-{entry_hash}-{identity_suffix}",
            published_at=entry.published_at,
            title=entry.title,
            summary=summary,
            source=SOURCE_OPERATOR,
            url=canonical_url,
            source_type="official_regulator",
            confidence="confirmed",
            amount=amount,
            currency=currency or None,
            country=str(source.get("country") or "Moldova"),
            market=str(source.get("market") or "CNPF Moldova"),
            source_id=SOURCE_ID,
            source_event_id=entry.entry_id,
            original_title=entry.title,
            issuer=issuer,
            target=target,
            acquirer=acquirer,
            instrument=instrument,
            programme=programme,
            series=series,
            isin=isin,
            registration_number=registration,
            event_date=event_date,
            lifecycle_stage=lifecycle,
            event_sub_stage=sub_stage,
            document_urls=document_urls,
            source_operator=SOURCE_OPERATOR,
            source_attribution=f"Source: CNPF Moldova — {canonical_url}",
            source_quality_flags=flags,
        ))
    return events


def canonical_cnpf_url(value: str, base_url: str) -> str:
    absolute = urllib.parse.urljoin(base_url, html.unescape(str(value or "").strip()))
    try:
        parsed = urllib.parse.urlsplit(absolute)
    except ValueError:
        return ""
    if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() not in {"cnpf.md", "www.cnpf.md"}:
        return ""
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urllib.parse.urlencode(sorted(
        (key, item) for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"gclid", "fbclid", "yclid"}
    ))
    return urllib.parse.urlunsplit(("https", "www.cnpf.md", path, query, ""))


def _xml_text(node: ET.Element, name: str) -> str:
    child = node.find(f"{{{ATOM_NS}}}{name}")
    return "" if child is None else "".join(child.itertext()).strip()


def _entry_links(node: ET.Element, feed_url: str) -> tuple[str, list[str]]:
    canonical = ""
    documents: list[str] = []
    for link in node.findall(f"{{{ATOM_NS}}}link"):
        href = str(link.get("href") or "")
        relation = str(link.get("rel") or "alternate").lower()
        mime = str(link.get("type") or "").lower()
        normalized = canonical_cnpf_url(href, feed_url)
        if not normalized:
            continue
        if relation == "alternate" and not canonical:
            canonical = normalized
        elif relation in {"enclosure", "related"} and ("pdf" in mime or normalized.lower().endswith(".pdf")):
            documents.append(normalized)
    return canonical, sorted(set(documents))


def _iso_timestamp(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return parsed.isoformat() if parsed.tzinfo else ""


def _fold(value: str) -> str:
    return (
        str(value or "").lower()
        .replace("ş", "ș").replace("ţ", "ț")
        .replace("ă", "a").replace("â", "a").replace("î", "i")
    )


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()


def _safe_reason(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def _article_fragment(page: str) -> str:
    for tag in ("article", "main"):
        match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", page, re.I | re.S)
        if match:
            return match.group(1)
    cleaned = re.sub(r"<(?:script|style|nav|footer)\b[^>]*>.*?</(?:script|style|nav|footer)>", " ", page, flags=re.I | re.S)
    return cleaned


def _visible_text(fragment: str) -> str:
    parser = _TextParser()
    parser.feed(fragment)
    return _clean_text(" ".join(parser.values))


def _labeled_entity(text: str, labels: tuple[str, ...]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    corporate_match = re.search(
        rf"(?:{label_pattern})\s*[:\-–]?\s*[\"„“]?(.+?\b(?:S\.\s*A\.|S\.\s*R\.\s*L\.|SA|SRL))",
        text, re.I,
    )
    if corporate_match:
        return _clean_text(corporate_match.group(1)).strip(' "„“.,;')[:160]
    match = re.search(
        rf"(?:{label_pattern})\s*[:\-–]?\s*[\"„“]?(.+?)(?=\s+(?:ISIN|num(?:a|ă)r(?:ul)?\s+de\s+[îi]nregistrare|"
        rf"valoarea|suma|moneda|ofertant|societatea\s+vizat|emitent|instrument|data)\b|[.;])",
        text, re.I,
    )
    if not match:
        return ""
    return _clean_text(match.group(1)).strip(' "„“.,;')[:160]


def _isins(text: str) -> list[str]:
    return list(dict.fromkeys(value.upper() for value in re.findall(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", text, re.I)))


def _registration_numbers(text: str) -> list[str]:
    matches = re.findall(
        r"(?:num(?:a|ă)r(?:ul)?\s+de\s+[îi]nregistrare|nr\.\s*de\s+[îi]nregistrare|decizia\s+nr\.)\s*[:#-]?\s*([A-Z0-9./-]{3,40})",
        text, re.I,
    )
    return list(dict.fromkeys(value.upper().strip(".,;") for value in matches))


def _amount_currency(text: str) -> tuple[float | None, str]:
    patterns = (
        r"(?:valoarea|volumul|suma|m(?:ă|a)rimea)\s+(?:total(?:ă|a)\s+)?(?:a\s+)?(?:emisiunii|ofertei|plasamentului)?\s*[:\-]?\s*"
        r"([0-9][0-9\s.,]*)\s*(miliarde|milioane|mii|mlrd\.?|mil\.?)?\s*(MDL|lei|EUR|euro|USD|dolari)",
        r"([0-9][0-9\s.,]*)\s*(miliarde|milioane|mii|mlrd\.?|mil\.?)\s*(MDL|lei|EUR|euro|USD|dolari)",
    )
    for pattern in patterns:
        match = re.search(pattern, _fold(text), re.I)
        if not match:
            continue
        number = _romanian_number(match.group(1))
        scale = _fold(match.group(2) or "")
        if "miliard" in scale or "mlrd" in scale:
            number *= 1_000_000_000
        elif "milio" in scale or scale.startswith("mil"):
            number *= 1_000_000
        elif "mii" in scale:
            number *= 1_000
        token = _fold(match.group(3))
        currency = "MDL" if token in {"mdl", "lei"} else "EUR" if token in {"eur", "euro"} else "USD"
        return number, currency
    return None, ""


def _romanian_number(value: str) -> float:
    compact = re.sub(r"\s+", "", value)
    if "," in compact and "." in compact:
        compact = compact.replace(".", "").replace(",", ".")
    elif "," in compact:
        compact = compact.replace(",", ".")
    elif compact.count(".") > 1 or ("." in compact and len(compact.rsplit(".", 1)[1]) == 3):
        compact = compact.replace(".", "")
    return float(compact)


def _event_date(text: str) -> str:
    match = re.search(r"\b([0-3]?\d)[./-]([01]?\d)[./-](20\d{2})\b", text)
    if not match:
        return ""
    day, month, year = map(int, match.groups())
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return ""


def _lifecycle(
    deal_type: str, text: str, issuer: str, identity: str,
    amount: float | None, currency: str,
) -> tuple[str, str]:
    folded = _fold(text)
    if deal_type == "M&A":
        return "Announced", "offer_approved"
    actual_result = bool(re.search(
        r"(?:rezultat(?:ele|ul)?|totalurile).{0,100}(?:emisiun|plas(?:ament|arii))|"
        r"(?:valori mobiliare|obligatiuni|actiuni).{0,80}(?:au fost emise|au fost plasate)",
        folded, re.I | re.S,
    ))
    if actual_result and issuer and identity and amount is not None and currency:
        return "Issued", "issue_result_registered"
    if "prospect" in folded:
        return "Announced", "prospectus_approved"
    if "program" in folded:
        return "Announced", "programme_registered"
    if "inregistr" in folded:
        return "Announced", "issue_registered"
    return "Announced", "offer_approved"


def _document_urls(fragment: str, base_url: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(fragment)
    output: list[str] = []
    for href, label in parser.links:
        absolute = urllib.parse.urljoin(base_url, html.unescape(href))
        parsed = urllib.parse.urlsplit(absolute)
        if parsed.scheme != "https" or not parsed.hostname:
            continue
        if not (parsed.path.lower().endswith(".pdf") or re.search(r"prospect|decizi|hot(?:ă|a)r", _fold(label))):
            continue
        output.append(urllib.parse.urlunsplit(("https", parsed.netloc.lower(), parsed.path, parsed.query, "")))
    return sorted(set(output))


def _capture(text: str, pattern: str) -> str:
    match = re.search(pattern, _fold(text), re.I)
    return _clean_text(match.group(1)).upper() if match else ""


def _stake(text: str) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", text)
    return float(match.group(1).replace(",", ".")) if match else None


def _factual_summary(**values: object) -> str:
    labels = {
        "DCM": "Official corporate bond event",
        "ECM": "Official corporate share issue event",
        "M&A": "Official takeover or mandatory-offer event",
    }
    parts = [labels.get(str(values["deal_type"]), "Official securities event")]
    for key, label in (
        ("issuer", "Issuer"), ("target", "Target"), ("acquirer", "Offeror/acquirer"),
        ("instrument", "Instrument"), ("identity", "Security/decision identity"),
        ("stage", "Lifecycle"), ("event_date", "Official event date"),
    ):
        if values.get(key):
            parts.append(f"{label}: {values[key]}")
    if values.get("amount") is not None and values.get("currency"):
        parts.append(f"Amount: {float(values['amount']):g} {values['currency']}")
    if values.get("stake") is not None:
        parts.append(f"Stake: {float(values['stake']):g}%")
    return ". ".join(parts) + "."


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            self.values.append(data)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.href = ""
        self.label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.href = dict(attrs).get("href") or ""
            self.label = []

    def handle_data(self, data: str) -> None:
        if self.href:
            self.label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.href:
            self.links.append((self.href, " ".join(self.label)))
            self.href = ""
            self.label = []
