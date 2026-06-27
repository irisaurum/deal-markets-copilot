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

