from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, TypeVar


STATE_SCHEMA_VERSION = 2
BASE_SLOT_MINUTES = 30
MAX_BACKOFF_MINUTES = 24 * 60
_SAFE_CODE = re.compile(r"[^a-z0-9_:-]+")
_SAFE_FAILURE_FIELDS = frozenset(
    {
        "last_attempt_at",
        "last_attempt_slot",
        "consecutive_failures",
        "last_error_code",
        "next_eligible_at",
        "last_result",
    }
)
_FORBIDDEN_STATE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "headers",
        "password",
        "private_key",
        "response_body",
        "stack_trace",
        "token",
    }
)
T = TypeVar("T")


class OperationalStateError(RuntimeError):
    """Operational state is unavailable and polling must fail closed."""


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    source_id: str
    enabled: bool
    required: bool
    implementation_state: str
    source_type: str
    poll_interval_minutes: int
    index_request_cap: int
    detail_request_cap: int

    @classmethod
    def from_mapping(cls, source_id: str, value: dict) -> "SourcePolicy":
        interval = max(BASE_SLOT_MINUTES, int(value.get("poll_interval_minutes", BASE_SLOT_MINUTES)))
        return cls(
            source_id=source_id,
            enabled=bool(value.get("enabled", False)),
            required=bool(value.get("required", False)),
            implementation_state=str(
                value.get("implementation_state")
                or value.get("production_status")
                or ("implemented" if value.get("implemented", True) else "research")
            ),
            source_type=str(value.get("source_type") or value.get("source_family") or value.get("connector") or "public_web"),
            poll_interval_minutes=interval,
            index_request_cap=max(
                0,
                int(
                    value.get("max_feed_requests")
                    or value.get("max_pages")
                    or value.get("index_request_cap")
                    or 1
                ),
            ),
            detail_request_cap=max(
                0,
                int(
                    value.get("max_detail_requests")
                    or value.get("max_items")
                    or value.get("detail_request_cap")
                    or 0
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    source_id: str
    decision: str
    reason: str
    next_eligible_at: str | None
    consecutive_failures: int

    @property
    def eligible(self) -> bool:
        return self.decision == "eligible"


def parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Orchestration time must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def empty_generation() -> dict:
    return {"sources": {}}


def empty_failure_patch() -> dict:
    return {"sources": {}}


def empty_state() -> dict:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "state_status": "committed",
        "accepted_generation": 0,
        "committed": empty_generation(),
        "candidate": None,
        "failure_patch": empty_failure_patch(),
    }


def _validate_generation(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"sources"} or not isinstance(value.get("sources"), dict):
        return False
    for source_id, source_state in value["sources"].items():
        if not isinstance(source_id, str) or not isinstance(source_state, dict):
            return False
        if any(str(key).lower() in _FORBIDDEN_STATE_KEYS for key in source_state):
            return False
    return True


def _validate_failure_patch(value: object) -> bool:
    if not _validate_generation(value):
        return False
    return all(
        set(source_state).issubset(_SAFE_FAILURE_FIELDS)
        for source_state in value["sources"].values()
    )


def validate_state_document(value: object, *, require_committed: bool = False) -> dict:
    expected_keys = {
        "schema_version",
        "state_status",
        "accepted_generation",
        "committed",
        "candidate",
        "failure_patch",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected_keys
        or value.get("schema_version") != STATE_SCHEMA_VERSION
    ):
        raise OperationalStateError("operational_state_schema_invalid")
    status = value.get("state_status")
    generation = value.get("accepted_generation")
    committed = value.get("committed")
    candidate = value.get("candidate")
    failure_patch = value.get("failure_patch")
    if status not in {"committed", "candidate"} or not isinstance(generation, int) or generation < 0:
        raise OperationalStateError("operational_state_schema_invalid")
    if not _validate_generation(committed) or not _validate_failure_patch(failure_patch):
        raise OperationalStateError("operational_state_schema_invalid")
    if status == "committed":
        if candidate is not None or failure_patch["sources"]:
            raise OperationalStateError("operational_state_not_finalized")
    elif not _validate_generation(candidate):
        raise OperationalStateError("operational_state_schema_invalid")
    if require_committed and status != "committed":
        raise OperationalStateError("operational_state_not_finalized")
    return value


def begin_transaction(state: dict) -> dict:
    validate_state_document(state, require_committed=True)
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "state_status": "candidate",
        "accepted_generation": state["accepted_generation"],
        "committed": copy.deepcopy(state["committed"]),
        "candidate": copy.deepcopy(state["committed"]),
        "failure_patch": empty_failure_patch(),
    }


def finalize_transaction(state: dict, *, accept_candidate: bool) -> tuple[dict, str]:
    validate_state_document(state)
    if state["state_status"] != "candidate":
        raise OperationalStateError("operational_state_transaction_missing")
    if accept_candidate:
        committed = copy.deepcopy(state["candidate"])
        generation = state["accepted_generation"] + 1
        outcome = "accepted"
    else:
        committed = copy.deepcopy(state["committed"])
        for source_id, patch in state["failure_patch"]["sources"].items():
            committed["sources"].setdefault(source_id, {}).update(copy.deepcopy(patch))
        generation = state["accepted_generation"]
        outcome = "failure_only"
    finalized = {
        "schema_version": STATE_SCHEMA_VERSION,
        "state_status": "committed",
        "accepted_generation": generation,
        "committed": committed,
        "candidate": None,
        "failure_patch": empty_failure_patch(),
    }
    validate_state_document(finalized, require_committed=True)
    return finalized, outcome


class OperationalStateStore:
    """Atomic committed/candidate state outside tracked economic artifacts."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return empty_state()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OperationalStateError("operational_state_corrupted") from exc
        return validate_state_document(value)

    def save(self, state: dict) -> None:
        validate_state_document(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def begin(self) -> dict:
        transaction = begin_transaction(self.load())
        self.save(transaction)
        return transaction

    def finalize(self, *, accept_candidate: bool) -> str:
        finalized, outcome = finalize_transaction(
            self.load(),
            accept_candidate=accept_candidate,
        )
        self.save(finalized)
        return outcome


class SourceOrchestrator:
    """One deterministic eligibility/backoff layer for a production run."""

    def __init__(self, state: dict, as_of: str | datetime):
        validate_state_document(state)
        self.transaction = state
        self.state = (
            state["candidate"]
            if state["state_status"] == "candidate"
            else state["committed"]
        )
        self.as_of = parse_utc(as_of)
        self.diagnostics: list[dict] = []

    @property
    def sources(self) -> dict:
        return self.state["sources"]

    def source_state(self, source_id: str) -> dict:
        value = self.sources.setdefault(source_id, {})
        if not isinstance(value, dict):
            raise OperationalStateError(f"operational_source_state_invalid:{sanitize_code(source_id)}")
        return value

    def decide(self, policy: SourcePolicy) -> EligibilityDecision:
        state = self.source_state(policy.source_id)
        failures = max(0, int(state.get("consecutive_failures") or 0))
        implementation = policy.implementation_state.lower()
        if not policy.enabled:
            if "blocked" in implementation:
                return EligibilityDecision(policy.source_id, "skipped_blocked", "source_blocked", None, failures)
            if "research" in implementation or "roadmap" in implementation or "not_implemented" in implementation:
                return EligibilityDecision(policy.source_id, "skipped_research", "source_research_only", None, failures)
            return EligibilityDecision(policy.source_id, "skipped_disabled", "source_disabled", None, failures)
        if "disabled" in implementation:
            return EligibilityDecision(policy.source_id, "skipped_disabled", "implementation_not_activated", None, failures)
        if "blocked" in implementation:
            return EligibilityDecision(policy.source_id, "skipped_blocked", "source_blocked", None, failures)
        if "research" in implementation or "roadmap" in implementation or "not_implemented" in implementation:
            return EligibilityDecision(policy.source_id, "skipped_research", "source_research_only", None, failures)

        backoff_until = _state_time(state.get("next_eligible_at"))
        if backoff_until and self.as_of < backoff_until:
            return EligibilityDecision(
                policy.source_id,
                "skipped_backoff",
                "bounded_backoff_active",
                backoff_until.isoformat(),
                failures,
            )

        slot = int(self.as_of.timestamp() // (BASE_SLOT_MINUTES * 60))
        interval_slots = max(1, (policy.poll_interval_minutes + BASE_SLOT_MINUTES - 1) // BASE_SLOT_MINUTES)
        phase = int(hashlib.sha256(policy.source_id.encode("utf-8")).hexdigest()[:8], 16) % interval_slots
        last_attempt_slot = state.get("last_attempt_slot")
        if slot % interval_slots != phase or last_attempt_slot == slot:
            next_slot = slot + 1
            while next_slot % interval_slots != phase:
                next_slot += 1
            return EligibilityDecision(
                policy.source_id,
                "skipped_not_due",
                "deterministic_utc_slot_not_due",
                datetime.fromtimestamp(next_slot * BASE_SLOT_MINUTES * 60, timezone.utc).isoformat(),
                failures,
            )
        return EligibilityDecision(policy.source_id, "eligible", "deterministic_utc_slot_due", None, failures)

    def begin(self, policy: SourcePolicy, decision: EligibilityDecision) -> None:
        if not decision.eligible:
            return
        state = self.source_state(policy.source_id)
        state["last_attempt_at"] = self.as_of.isoformat()
        state["last_attempt_slot"] = int(self.as_of.timestamp() // (BASE_SLOT_MINUTES * 60))

    def succeed(self, policy: SourcePolicy, *, changed: bool) -> None:
        state = self.source_state(policy.source_id)
        state.update(
            {
                "last_success_at": self.as_of.isoformat(),
                "consecutive_failures": 0,
                "last_error_code": "",
                "next_eligible_at": "",
                "last_result": "completed_changed" if changed else "completed_unchanged",
            }
        )

    def fail(
        self,
        policy: SourcePolicy,
        error_code: str,
        *,
        result: str | None = None,
        retry_after: str | int | None = None,
    ) -> str:
        state = self.source_state(policy.source_id)
        failures = max(0, int(state.get("consecutive_failures") or 0)) + 1
        exponential = min(
            MAX_BACKOFF_MINUTES,
            max(policy.poll_interval_minutes, BASE_SLOT_MINUTES) * (2 ** (failures - 1)),
        )
        retry_minutes = _retry_after_minutes(retry_after, self.as_of)
        delay = min(MAX_BACKOFF_MINUTES, max(exponential, retry_minutes or 0))
        next_eligible = self.as_of + timedelta(minutes=delay)
        code = sanitize_code(error_code)
        state.update(
            {
                "consecutive_failures": failures,
                "last_error_code": code,
                "next_eligible_at": next_eligible.isoformat(),
                "last_result": result or code,
            }
        )
        if self.transaction["state_status"] == "candidate":
            patch = {
                key: copy.deepcopy(state[key])
                for key in _SAFE_FAILURE_FIELDS
                if key in state
            }
            self.transaction["failure_patch"]["sources"][policy.source_id] = patch
            committed_source = copy.deepcopy(
                self.transaction["committed"]["sources"].get(policy.source_id, {})
            )
            committed_source.update(copy.deepcopy(patch))
            self.transaction["candidate"]["sources"][policy.source_id] = committed_source
        return next_eligible.isoformat()

    def diagnostic(
        self,
        policy: SourcePolicy,
        decision: EligibilityDecision,
        *,
        result: str | None = None,
        reason: str | None = None,
        **counts: object,
    ) -> dict:
        state = self.source_state(policy.source_id)
        row = {
            "source_id": policy.source_id,
            "enabled": policy.enabled,
            "required": policy.required,
            "implementation_state": policy.implementation_state,
            "source_type": policy.source_type,
            "configured_interval_minutes": policy.poll_interval_minutes,
            "eligibility_decision": result or decision.decision,
            "eligibility_reason": sanitize_code(reason or decision.reason),
            "backoff_state": "active" if decision.decision == "skipped_backoff" else "clear",
            "consecutive_failures": int(state.get("consecutive_failures") or 0),
            "index_feed_request_count": int(counts.get("index_feed_request_count") or 0),
            "detail_request_count": int(counts.get("detail_request_count") or 0),
            "http_status_class": sanitize_code(str(counts.get("http_status_class") or "not_requested")),
            "parser_status": sanitize_code(str(counts.get("parser_status") or "not_started")),
            "items_discovered": int(counts.get("items_discovered") or 0),
            "items_in_archive": int(counts.get("items_in_archive") or 0),
            "items_whitelisted": int(counts.get("items_whitelisted") or 0),
            "accepted": int(counts.get("accepted") or 0),
            "review": int(counts.get("review") or 0),
            "excluded": int(counts.get("excluded") or 0),
            "sanitized_error_code": sanitize_code(str(counts.get("sanitized_error_code") or "")),
            "next_eligibility": decision.next_eligible_at or str(state.get("next_eligible_at") or ""),
            "index_request_cap": policy.index_request_cap,
            "detail_request_cap": policy.detail_request_cap,
        }
        self.diagnostics.append(row)
        return row


def execute_source(
    orchestrator: SourceOrchestrator,
    policy: SourcePolicy,
    fetcher: Callable[[], T],
    *,
    changed: Callable[[T], bool] | None = None,
) -> tuple[T | None, EligibilityDecision, dict]:
    decision = orchestrator.decide(policy)
    if not decision.eligible:
        return None, decision, orchestrator.diagnostic(policy, decision)
    orchestrator.begin(policy, decision)
    try:
        value = fetcher()
    except Exception as exc:
        decision_code = classify_error(exc)
        error_code = specific_error_code(exc)
        next_eligible = orchestrator.fail(
            policy,
            error_code,
            result=decision_code,
            retry_after=getattr(exc, "retry_after", None),
        )
        failed = EligibilityDecision(
            policy.source_id,
            decision_code,
            error_code,
            next_eligible,
            int(orchestrator.source_state(policy.source_id).get("consecutive_failures") or 0),
        )
        return None, failed, orchestrator.diagnostic(
            policy,
            failed,
            sanitized_error_code=error_code,
        )
    is_changed = changed(value) if changed else bool(value)
    orchestrator.succeed(policy, changed=is_changed)
    result = "completed_changed" if is_changed else "completed_unchanged"
    completed = EligibilityDecision(policy.source_id, result, result, None, 0)
    return value, completed, orchestrator.diagnostic(policy, completed, result=result)


def content_changed(
    orchestrator: SourceOrchestrator,
    policy: SourcePolicy,
    value: object,
) -> bool:
    def normalized(item: object) -> object:
        if hasattr(item, "to_dict"):
            return normalized(item.to_dict())
        if isinstance(item, dict):
            return {str(key): normalized(item[key]) for key in sorted(item)}
        if isinstance(item, (list, tuple)):
            return [normalized(child) for child in item]
        return item

    payload = json.dumps(
        normalized(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    state = orchestrator.source_state(policy.source_id)
    previous = state.get("content_fingerprint")
    state["content_fingerprint"] = fingerprint
    return previous != fingerprint


def classify_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "parser" in text or "malformed" in text or "unexpected_content" in text:
        return "failed_parser"
    if "http" in text or "403" in text or "429" in text or "challenge" in text or "login" in text:
        return "failed_http"
    return "failed_transport"


def specific_error_code(exc: Exception) -> str:
    text = str(exc).lower()
    if "429" in text:
        return "http_429"
    if "403" in text:
        return "http_403"
    if "challenge" in text or "login" in text:
        return "challenge_or_login"
    if "tls" in text or "ssl" in text or "certificate" in text:
        return "tls_transport"
    if "parser" in text or "malformed" in text or "unexpected_content" in text:
        return "parser_error"
    if "http" in text:
        return "http_error"
    return "transport_error"


def sanitize_code(value: str) -> str:
    return _SAFE_CODE.sub("_", value.lower()).strip("_")[:120]


def format_diagnostic(row: dict) -> str:
    safe = {
        key: value
        for key, value in row.items()
        if key not in {"response_body", "headers", "authorization", "cookie", "stack_trace"}
    }
    return "ORCHESTRATION " + json.dumps(safe, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _state_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return parse_utc(str(value))
    except (TypeError, ValueError):
        return None


def _retry_after_minutes(value: str | int | None, now: datetime) -> int | None:
    if value in (None, ""):
        return None
    try:
        return max(0, int(value) // 60 + (1 if int(value) % 60 else 0))
    except (TypeError, ValueError):
        try:
            parsed = parsedate_to_datetime(str(value)).astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None
        return max(0, int((parsed - now).total_seconds() // 60) + 1)
