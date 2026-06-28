from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class Event:
    event_id: str
    published_at: str
    title: str
    summary: str
    source: str
    url: str
    companies: list[str] = field(default_factory=list)
    source_type: str = "public_web"
    confidence: str = "unverified"
    amount: float | None = None
    currency: str | None = None
    demo: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ClassifiedEvent:
    event: Event
    category: str
    score: int
    severity: str
    banker_angle: str
    next_action: str
    matched_coverage: list[str] = field(default_factory=list)
    evidence_label: str = "unverified"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["event"] = self.event.to_dict()
        return data


@dataclass(slots=True)
class DealRecord:
    deal_id: str
    announced_date: str
    deal_type: str
    status: str
    target_or_issuer: str
    acquirer_or_investor: str
    sector: str
    geography: str
    headline: str
    transaction_value: float | None
    enterprise_value: float | None
    currency: str
    stake_percent: float | None
    payment_form: str
    advisors: str
    revenue_ltm: float | None
    ebitda_ltm: float | None
    financials_as_of: str
    financials_currency: str
    ev_revenue: float | None
    ev_ebitda: float | None
    instrument: str
    rationale: str
    matched_coverage: list[str]
    source_name: str
    source_url: str
    evidence_label: str
    score: int
    source_event_id: str
    first_seen_at: str
    last_seen_at: str
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
