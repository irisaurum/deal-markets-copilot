# Decisions log

Append-only log of durable architectural/product decisions. It is not a commit changelog. If a decision is superseded, append a new entry; do not silently rewrite the old rationale.

## Live flow and historical precedents are separate

- **Date:** documented before current context system.
- **Decision:** historical/curated precedents never populate live or current deal flow.
- **Context:** useful valuation history made old transactions visible as if current.
- **Rationale:** monitoring recency and valuation comparability are different products.
- **Consequences:** `CURATED-` rows remain available to archive/Excel/analytics but are excluded by current selection.
- **Related:** `deals.py`, `DATA_RULES.md`.

## Current lists are not padded

- **Date:** documented before current context system.
- **Decision:** return fewer than 10 transactions when fewer pass recency, materiality and quality.
- **Context:** fixed-length presentation encouraged old or weak records.
- **Rationale:** an honest empty/short list is more useful than false coverage.
- **Consequences:** counts and labels are dynamic.
- **Related:** `deals.py`, `report.py`.

## DCM owns its status semantics

- **Date:** documented before current context system.
- **Decision:** book closure is `Priced`, placement is `Issued`, and `Closed` is M&A-only.
- **Context:** shared completion keywords produced misleading DCM stages.
- **Rationale:** deal types have different execution milestones.
- **Consequences:** extraction, migration, UI and tests enforce type-aware statuses.
- **Related:** `deals.py`, `DATA_RULES.md`, `REGRESSIONS.md`.

## Technical events do not create banker tasks

- **Date:** documented before current context system.
- **Decision:** filings, REPO, redemptions, coupon payments, routine registrations and technical buybacks are suppressed before task generation.
- **Context:** exchange plumbing produced high-priority debt-comps tasks.
- **Rationale:** traceability is useful; analyst-action noise is not.
- **Consequences:** technical records may remain in their own stream.
- **Related:** `classifier.py`, `workflow.py`, `deals.py`.

## Replay is database-immutable

- **Date:** documented before current context system.
- **Decision:** replay rebuilds dependent views from saved inputs without writing the persistent database.
- **Context:** post-XLSX database mutation invalidated build synchronization.
- **Rationale:** replay is a deterministic synchronization step, not ingestion.
- **Consequences:** releases verify byte-for-byte database stability.
- **Related:** `run.py`, `TESTING_AND_RELEASE.md`.

## Full database bytes define Build ID

- **Date:** 2026-07-04 hardening milestone.
- **Decision:** Build ID derives from SHA-256 of exact database bytes.
- **Context:** selected-field hashes missed material changes.
- **Rationale:** one canonical identity is required across public artifacts.
- **Consequences:** formatting/order changes to the canonical database also change build identity.
- **Related:** `run.py`, workbook builders, verifier.

## Public medians expose sample size

- **Date:** documented before current context system; threshold hardened 2026-07-04.
- **Decision:** show `n` for each multiple and show `N/M` when `n < 3`.
- **Context:** a two-observation median looked authoritative.
- **Rationale:** thin or ineligible samples must remain visible as uncertainty.
- **Consequences:** Python, HTML and both Excel builders share the threshold.
- **Related:** `deals.py`, workbook builders, `DATA_RULES.md`.

## Empty required source is unhealthy

- **Date:** 2026-07-04 hardening milestone.
- **Decision:** a required source returning zero usable records is not silently `ok`.
- **Context:** total discovery failure could resemble a quiet news day.
- **Rationale:** absence of evidence is not proof of successful ingestion.
- **Consequences:** health distinguishes source/discovery/freshness states.
- **Related:** `run.py`, `sources.py`, verifier.

## Public artifacts form one atomic build

- **Date:** documented before current context system.
- **Decision:** HTML, snapshot, CSV, XLSX and manifest must all describe one database build.
- **Context:** separate generation paths allowed stale downloads.
- **Rationale:** analysts must be able to reproduce every public view from one dataset.
- **Consequences:** strict verifier and CI order gate publication.
- **Related:** `ARCHITECTURE.md`, `TESTING_AND_RELEASE.md`.

## Newer scheduled run supersedes stale work

- **Date:** 2026-07-03.
- **Decision:** use one workflow concurrency group and cancel older in-progress runs.
- **Context:** frequent schedules can overlap network, build and deploy phases.
- **Rationale:** an old successful run must not overwrite fresher data.
- **Consequences:** interrupted stale runs are expected behavior.
- **Related:** `.github/workflows/deal-desk.yml`.

## Documentation context is modular

- **Date:** 2026-07-04.
- **Decision:** use short `AGENTS.md` rules plus task-routed documents instead of one giant handoff.
- **Context:** a long thread and monolithic context became stale, expensive and hard to verify.
- **Rationale:** future sessions should load only durable rules and task-relevant context.
- **Consequences:** update `CURRENT_STATE.md` after milestones and route through `START_HERE.md`.
- **Related:** `AGENTS.md`, all `docs/*.md` context files.

## Documentation-only pushes do not refresh production

- **Date:** 2026-07-05.
- **Decision:** exclude proven documentation-only and bot-generated paths from the production push trigger; keep schedule, manual dispatch and all other tracked paths production-relevant by default.
- **Context:** a documentation commit ran live ingestion, changed public artifacts, created a bot commit and redeployed Pages.
- **Rationale:** a conservative ignore-list prevents non-production side effects without risking a missed refresh when a new code, config, verifier, builder, test or data path is added.
- **Consequences:** docs-only pushes receive no production refresh; mixed docs/code pushes do; scheduled and manual autonomous refreshes are unchanged; table-driven workflow-policy tests protect the boundary and loop guard.
- **Related:** `.github/workflows/deal-desk.yml`, `tests/test_workflow_policy.py`, `TESTING_AND_RELEASE.md`.

## Coordinated DCM placements use one deal lifecycle with distinct issue identities

- **Date:** 2026-07-05.
- **Decision:** represent a coordinated multi-series placement as one canonical deal-level lifecycle while retaining the complete set of distinct issue series in `security_code` and every relevant source as lineage.
- **Context:** a preliminary aggregate signal and the official final placement were stored as separate economic transactions because event-level identity and weak proximity heuristics overrode deal-level continuity.
- **Rationale:** the existing flat deal schema already supports one economic record, multiple sources and a displayable identifier field; linked event records or a new parent/child schema would add counting and downstream complexity without improving this case.
- **Consequences:** DCM lifecycle matching relies on shared strong issue identifiers or exact stored source lineage plus issuer equality; weak signals alone do not merge. Official final evidence, lifecycle maturity and completeness determine the canonical record, and status/terms cannot regress during consolidation.
- **Related:** `deals.py`, `DATA_RULES.md`, `REGRESSIONS.md` REG-26.
