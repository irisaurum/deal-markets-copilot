# CIS-SOURCES-01B — Wave 1 exchange adapters

Implementation checkpoint: **17 July 2026 (Europe/Moscow)**.

Base commit: `b6c4b0bbaba7310268b9497ebf5c850655e7710b`.

This document records the implementation and activation boundary for KASE, AMX and BVM. It does not replace the verified research in [`CIS_SOURCE_RESEARCH.md`](CIS_SOURCE_RESEARCH.md), [`CIS_SOURCE_MATRIX.csv`](CIS_SOURCE_MATRIX.csv), [`CIS_SOURCE_SAMPLES.csv`](CIS_SOURCE_SAMPLES.csv) or [`CIS_EVENT_TAXONOMY.md`](CIS_EVENT_TAXONOMY.md).

## Production activation decision

No Wave 1 source is enabled in production in this implementation.

| Source | Implementation | Production | Access / reuse conclusion |
|---|---|---|---|
| KASE Market and Company News | Implemented and fixture-tested | `implemented_disabled` | Index and numeric detail pages are public and repeatable without authentication. Current pages state that copying materials requires written permission. Production polling is disabled pending written permission or an operator-approved factual-use basis. |
| AMX listing and allocation news | Implemented and fixture-tested | `blocked` | Search engines can reopen official details, and `robots.txt` allows ordinary paths, but repeated direct unattended requests currently return a Cloudflare anti-bot challenge shell without news content. No bypass is attempted. Reuse terms also remain unresolved. |
| Moldova Stock Exchange / BVM news | Implemented and fixture-tested | `implemented_disabled` | Index, pagination, numeric details and prospectus links are public and repeatable without authentication. No explicit unattended factual-reuse terms were located, and the robots path returns the site's 404 representation. Production polling is disabled pending an exact terms conclusion. |

Public readability and robots behavior are operational signals, not licences. The adapters retain only factual fields, the short original title, official identifiers, canonical URLs, relevant official document links and provenance. They do not persist copied full article bodies.

## Shared adapter design

`src/deal_markets_copilot/exchange_sources.py` owns one lightweight exchange-news interface with source-specific index identity, detail parsing, allowlists, exclusions and factual extraction. `sources.py` owns conservative requests and returns individual source-health rows.

Each configured source declares:

- source identity, name, country, market and source family;
- officialness tier, supported deal types and languages;
- canonical index and numeric detail pattern;
- implementation, enabled and required state;
- archive window, page/detail limits and polling interval;
- access/reuse status, production status and source-health state.

The three sources are optional. Their failure cannot stop the existing required Russia processing or the connected Uzbekistan adapter. An enabled source still reports its own `ok`, `empty` or `error` state. Empty expected markup, missing detail links, anti-bot/login/error content and parser-shape failures fail closed.

## Event boundary

The adapter starts with corporate economic-event allowlists:

- KASE: corporate bond programme/issue, book opening, guidance, pricing, placement or issue result, and issue-specific listing; explicit corporate share issue or transaction only when the official publication states it.
- AMX: corporate bond issue, completed placement/allocation, issue-specific listing with economic terms, and a new-capital share issue with required terms.
- BVM: corporate bond issue/admission with issue-level terms, explicit placement result, mandatory withdrawal as M&A review, and a clear new-capital share issue.

Government, sovereign, municipal and central-bank paper; REPO-only notices; coupon/redemption; buybacks; ratings; market statistics; reports and meetings; provisional admissions; routine listing maintenance; and generic issuer news do not create economic events or banker tasks.

## Identity and lifecycle

Source identity is retained as `source_id + source_event_id`. Economic events prefer ISIN or state registration number, then exact programme plus series/tranche. One publication containing several ISINs creates separate security events with the shared source lineage; title similarity cannot collapse distinct security identities.

Programme target amount is never assigned to every issue. AMX amount is derived only when `quantity × denomination` is deterministic and currency is unambiguous; quantity, denomination and the derivation flag remain in source provenance.

Lifecycle remains monotonic:

`Announced → Priced → Issued`

- programme/issue registration, offer opening, guidance and listing-only evidence remain `Announced`;
- final price/yield or book closure is `Priced`;
- explicit completed placement or issue-result evidence is `Issued`;
- a later preliminary event cannot downgrade an issued record.

Source sub-stages are retained separately, including `programme_registered`, `issue_registered`, `offer_open`, `bookbuilding`, `priced`, `placement_completed`, `issue_result_registered` and `listed`.

## Quality and output behavior

Official exchange evidence does not bypass the existing quality gate. Approved ECM/DCM still requires issuer, amount, currency, an instrument/security identity, supported lifecycle evidence and a reopenable canonical official URL without blocking quality flags. Incomplete records remain review with the exact missing-field flags.

Country and market metadata are assigned from the configured adapter, never from publisher language or domain:

- Kazakhstan / KASE;
- Armenia / AMX;
- Moldova / BVM.

The dashboard distinguishes `connected`, `implemented_disabled`, `roadmap`, `link_only` and `blocked`. Only enabled sources count as connected coverage. Because all three Wave 1 sources remain disabled, this implementation makes no claim of expanded production CIS coverage and produces no dataset or public-artifact delta.

## Fixtures and verification

`tests/test_cis_exchange_sources.py` contains three positive and three negative publications per source derived from the checked-in research samples and taxonomy. It covers registry fields, index IDs and pagination, detail parsing, original titles, country/market metadata, amount/currency, ISIN and programme/tranche separation, distinct ISIN preservation, lifecycle monotonicity, repeat-fetch idempotence, fail-closed health, exclusions, quality gates and RU/EN coverage rendering.

Live activation requires a new checkpoint showing both stable unattended access and an acceptable factual-reuse basis. Enabling a source then requires a conservative live smoke and the normal data/artifact release gate.

## Release-acceptance follow-up

Scheduled run `#143` failed in `production_refresh` at the `Verify synchronized public artifacts` step. The strict verifier rejected `latest_snapshot.json` because aggregate `health.source_status` was not `ok`. The retained Actions log does not include the per-source `source_runs` rows, HTTP result or parser result, so the affected source and external failure mode cannot be reconstructed exactly. This is classified as **E — retained diagnostics are insufficient to identify the per-source cause**, not as a Wave 1 configuration defect. The same code and configuration passed manual production run `#142` shortly beforehand, while KASE, AMX and BVM were disabled. No source-health production logic or verifier rule was weakened.

The intended health boundary remains unchanged: disabled or blocked sources are not polled, are not connected or active, and retain their honest UI state and reason without failing global health merely because they are inactive. An enabled required source still fails closed on transport errors, challenge/error pages, empty expected content and parser-shape drift. Focused tests now lock both sides of that boundary.

The 390px RU/EN page overflow was independent of source polling. Its root cause was the source-coverage grid's intrinsic minimum sizing: `1fr` columns and a coverage card with an automatic minimum width inherited the min-content width of long access/reuse identifiers. The grid expanded to about 431px inside a 332px content area and produced an approximately 460px document. Coverage tracks now use `minmax(0, 1fr)`, cards may shrink with `min-width: 0`, and unavoidable source identifiers wrap with `overflow-wrap: anywhere`. The responsive regression asserts these shrink-and-wrap rules; browser acceptance separately verifies a 390px document width in both languages.
