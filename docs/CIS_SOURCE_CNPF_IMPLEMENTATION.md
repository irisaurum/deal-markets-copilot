# CIS-SOURCES-01C-B — CNPF Moldova official Atom feed

Implementation checkpoint: **22 July 2026 (Europe/Moscow)**.

Base commit: `b824a65a5c571b3af20d88c7240584c6cb3f5d8d`.

This document records the implementation and activation boundary for the CNPF Moldova official Atom feed. It does not activate or change KASE, AMX, BVM, Openinfo, ARDFM, CBA, ESID or NBG, and it does not start CIS-DIAGNOSTICS-01. The verified merged research documents remain the research source of truth.

## Activation decision

Decision: **`BLOCKED`**.

The first checkpoint failed because the CNPF server presented its leaf certificate without the Sectigo intermediate. Python/OpenSSL could not build that incomplete chain even with the current certifi bundle, while macOS `curl` verified it through the platform Security framework. The application now has a maintained `truststore` platform context for CNPF only, with `CERT_REQUIRED` and hostname checking unchanged. After focused transport tests passed, the one additionally authorized macOS project-client checkpoint succeeded without retry: HTTP 200, `application/atom+xml`, 30 feed entries, 20 entries in the 90-day archive window, three whitelisted candidates and three detail requests. The parser had zero failures and found zero page-specific restrictions. All three details were conservatively rejected by the final event allowlist, producing zero events, records and tasks.

Activation is nevertheless blocked: the production refresh runs on Ubuntu and begins live discovery before `requirements-ci.txt` is installed, while the server's omitted intermediate is not verifiable by the standard Python/OpenSSL or certifi paths tested here. A macOS Security-framework success is not evidence that the deployed Linux transport can build the incomplete chain. The task forbids a workflow change and forbids source-specific certificate workarounds, so CNPF remains disabled and fail-closed.

The registry state is:

- `implemented=true`;
- `enabled=false`;
- `required=false`;
- `production_status=implemented_disabled`;
- `health_state=disabled_server_chain_blocker`.

Disabled CNPF is not polled, does not count as connected coverage and produces no production dataset or public-artifact delta. The successful local checkpoint does not change that production boundary.

## Permission and attribution boundary

Official terms: <https://www.cnpf.md/ro/termeni-si-conditii-6436.html>.

The page authorizes reproduction of site materials with source attribution within applicable copyright and related-rights law. It also says that a page-specific requirement for prior agreement overrides that general authorization and that a reproduction restriction will be indicated where applicable.

The adapter therefore:

- retains only factual fields, a short original title, official identifiers, canonical links, relevant official document links and provenance;
- never persists a full feed summary or article body;
- writes exact per-event attribution as `Source: CNPF Moldova — [canonical official link]`;
- stops on a page-specific restriction rather than retaining content;
- must be disabled on conflicting terms or an operator objection.

Public readability alone is not treated as unrestricted bulk-reuse permission.

## Adapter boundary

`src/deal_markets_copilot/cnpf_source.py` owns safe Atom parsing, the CNPF-specific event allowlist/exclusions, canonical URL handling, factual detail extraction, source identity and lifecycle mapping. `src/deal_markets_copilot/sources.py` owns conditional request validators, entry fingerprints, request caps, transport/content validation and source-health diagnostics. The production orchestrator owns eligibility and persists CNPF operational state in the schema-versioned external GitHub Actions cache; replay neither reads nor writes that state.

The source is optional and isolated from required Russia processing and the existing connected UZSE source. Its failure cannot corrupt records from other sources.

## Event allowlist and exclusions

The feed is broad. Only explicit official corporate securities events are candidates:

- corporate bond issue or placement results;
- corporate share issue results;
- bond or equity prospectus approvals;
- bond programme approvals;
- takeover or mandatory-offer approvals;
- squeeze-out or mandatory-withdrawal approvals.

The source-level filter excludes insurance supervision, consumer notices, sanctions, licensing, liquidation/insolvency, governance appointments, reports/statistics, consultations, coupon/redemption/buyback notices, sovereign/government/municipal paper, training/conferences, public procurement, vacancies and institutional press releases. An excluded feed entry causes no detail request, event, record or banker task.

## Safe Atom and detail parsing

The Atom parser is namespace-aware and fail-closed. It rejects DTD/entity declarations, malformed XML, a missing Atom root, missing feed metadata, missing immutable entry ID, invalid timestamps and missing or unsafe canonical links. Duplicate entries are suppressed by immutable Atom entry ID and processing order is deterministic.

Detail requests accept only canonical HTTPS links on `cnpf.md`. The parser reads visible article/main text, strips navigation/footer/script/style content, checks for page-specific reuse restrictions and extracts only supported factual fields:

- issuer, target and offeror/acquirer;
- amount and currency;
- ISIN or state/decision registration number;
- programme and series/tranche;
- stake percentage and official event date;
- relevant official PDF/document links.

No NLP inference fills an undisclosed field.

## Identity, lifecycle and quality

Source lineage is `cnpf_moldova + immutable Atom entry ID`. One entry with several ISINs produces distinct economic events under the same source lineage. The stable Atom ID is never replaced by title/date/issuer fallback identity.

Lifecycle remains monotonic:

- prospectus, programme or issue registration stays `Announced`;
- takeover/mandatory-offer approval stays `Announced`, never `Closed`;
- `Issued` requires explicit issue/placement-result evidence plus issuer, amount, currency and ISIN/registration identity;
- a preliminary disclosure cannot downgrade a stronger existing stage.

Official-regulator status does not bypass the quality gate. Missing issuer, security identity, amount, currency or supported lifecycle evidence produces an exact blocking/review flag. Technical or excluded items create zero tasks.

## Polling and health

CNPF is configured for 30-minute deterministic UTC-slot eligibility but remains disabled, so production makes zero requests. If separately activated in the future, an eligible poll is capped at exactly one conditional Atom feed request and at most eight new or changed whitelisted canonical detail requests; there is no pagination or site crawl. The adapter compatibility contract also retains +29/+30-minute last-success gating when invoked outside the production orchestrator. ETag and Last-Modified validators are retained when available, and HTTP 304 is healthy with zero detail requests. Deterministic Atom-entry fingerprints prevent repeated detail fetches for unchanged entries.

Per-source diagnostics include eligibility, request counts, feed HTTP status/class, content type, parser status, entries discovered/in archive, whitelisted/excluded counts, detail requests, accepted/review counts, duplicate suppression and a sanitized health reason. Transport exceptions retain attempted-request counters and fail as `transport_error` without storing response content.

403, 429, challenge/login HTML, wrong content type, empty response, malformed/unexpected feed, unsafe timestamp, unresolved canonical link, parser drift or a page-specific restriction fail closed. A failed poll does not advance the successful-poll timestamp. A valid non-empty feed with zero allowlisted entries is `healthy_zero_whitelisted`; an unchanged valid feed is `healthy_unchanged`; a structurally empty or malformed feed is unhealthy.

## Fixtures and verification boundary

`tests/test_cnpf_source.py` uses compact synthetic excerpts, not copied articles. It includes six positive fixtures, eight negative fixtures and explicit malformed/empty/identity/link/restriction/HTTP/content/transport failures. It covers namespace parsing, canonicalization, Romanian preservation, field mapping, lifecycle, distinct ISINs, deduplication, fixed-point merge, replay/poll independence, +29/+30-minute gating, conditional 304 handling, unchanged-entry suppression, request caps, platform TLS verification, health reasons, quality/review flags, zero-task exclusions, RU/EN coverage, Moldova filtering, attribution and the 390px CSS contract.

The local implementation gate includes the verified CNPF-only macOS checkpoint, full offline regression suite, canonical replay fixed-point checks and strict artifact verification. No branch workflow was started. After merge, exactly one normal production refresh is required for the code/replay changes and synchronized public artifacts, but it will not poll disabled CNPF. Activation requires a separate change that first proves the deployed Ubuntu transport can verify the server chain without weakening TLS.
