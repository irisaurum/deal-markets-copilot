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
- **Status:** superseded by "Replay reaches a canonical fixed point" below.
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
- **Status:** superseded by "Public Pages contract excludes internal snapshot" below.
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
- **Status:** superseded by "Validation and production refresh are separate workflow paths" below.
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

## Publication identity is separate from URL representation

- **Date:** 2026-07-06.
- **Decision:** store one canonical source object per publication and retain alternate direct/discovery/tracking URLs as nested representations; count publications rather than raw URLs.
- **Context:** the same InvestFuture and Finam articles appeared once through publisher URLs and once through Google News, inflating source counts without adding independent corroboration.
- **Rationale:** a flat raw-representation count overstates evidence, while deleting discovery URLs destroys useful lineage. The existing source object can carry alternate representations without introducing a separate provenance subsystem.
- **Consequences:** canonical URL normalization is conservative; ambiguous or incomplete metadata does not trigger merging; same-publisher and syndicated articles remain separate unless publication identity is established. CSV serializes the nested lineage and XLSX `Sources & QA` shows canonical publication rows plus representation counts/URLs.
- **Related:** `deals.py`, `sources.py`, `DATA_RULES.md`, `REGRESSIONS.md` REG-27, workbook builders and strict verifier.

## Replay reaches a canonical fixed point

- **Date:** 2026-07-08 CI-01-T1.
- **Decision:** replay is not ingestion and must not create new economic events, change economic deal semantics or create lifecycle duplicates. Replay may persist deterministic schema migration, source canonicalization and quality recomputation when required to bring the dataset to the canonical fixed point. After the first canonicalization replay, a repeated replay must be byte-stable for the dataset.
- **Context:** the older "replay must not mutate the database" wording was too broad after deterministic canonicalization/persistence became part of the release path.
- **Rationale:** deterministic canonicalization is necessary before dependent artifacts can share one identity, but replay must still be prohibited from adding or changing economic transactions.
- **Consequences:** dependent artifacts are generated only after the final persisted dataset state; release verification checks the second replay for byte-stability against that final dataset.
- **Related:** `run.py`, `ARCHITECTURE.md`, `TESTING_AND_RELEASE.md`.

## Public Pages contract excludes internal snapshot

- **Date:** 2026-07-08 CI-01-T1.
- **Decision:** the public GitHub Pages release contract is dashboard HTML, `build_manifest.json`, `precedent_transactions.csv` and `precedent_transactions.xlsx`. `latest_snapshot.json` is internal-only and public 404 is expected until the architecture deliberately changes.
- **Context:** historical documentation used "HTML/JSON/CSV/XLSX" and sometimes treated snapshot as public, creating ambiguity during public verification.
- **Rationale:** public consumers should verify the artifacts intentionally published by Pages, while internal health/snapshot state may remain generated but unpublished.
- **Consequences:** public release checks use manifest, HTML, CSV and XLSX; `latest_snapshot.json` public 404 is not a release failure.
- **Related:** `ARCHITECTURE.md`, `TESTING_AND_RELEASE.md`, `CURRENT_STATE.md`.

## Release workflow uses two replay steps

- **Date:** 2026-07-08 CI-01-T1.
- **Decision:** current production order is tests -> live refresh -> first replay canonicalization/persistence -> workbook + manifest generation -> second replay health synchronization -> strict verifier -> bot commit -> Pages deploy.
- **Context:** one replay before artifacts may persist the final canonical dataset, while a later replay is still required to synchronize health after workbook/manifest generation.
- **Rationale:** artifacts must be built from the final persisted dataset and then verified after health/presentation state is synchronized to those artifacts.
- **Consequences:** a failed strict verifier blocks both the bot commit and Pages deployment.
- **Related:** `.github/workflows/deal-desk.yml`, `ARCHITECTURE.md`, `TESTING_AND_RELEASE.md`.

## LaunchAgent is an interim manual fallback

- **Date:** 2026-07-08 CI-01-T1.
- **Status:** superseded by "Local LaunchAgent remains disabled by default" below.
- **Decision:** LaunchAgent remains unloaded and is not a production automation path. At CI-01-T1 it was retained only as an emergency/manual fallback until CI-01-T5 finalized the policy, and it was not allowed to run during development or integration work.
- **Context:** production automation is currently the GitHub Actions path.
- **Rationale:** local scheduled execution can create side effects outside the controlled CI release contract.
- **Consequences:** development and integration tasks must leave LaunchAgent unloaded unless a future decision changes this policy.
- **Related:** `TESTING_AND_RELEASE.md`, `CURRENT_STATE.md`.

## Validation and production refresh are separate workflow paths

- **Date:** 2026-07-08 CI-01-T2.
- **Decision:** pull requests and production-relevant pushes to `main` run deterministic validation only. Schedule and `workflow_dispatch` own live discovery, replay canonicalization, workbook/manifest generation, second replay synchronization, strict verification, bot commit and Pages deploy.
- **Context:** one workflow previously served PR/code validation, push-to-main refresh, scheduled refresh, manual refresh, publication and deployment.
- **Rationale:** code validation must be deterministic and side-effect-free, while production refresh must remain the single controlled writer/publisher path.
- **Consequences:** docs-only and bot-generated paths remain excluded from push-triggered validation loops; pushes to `main` no longer run live discovery or deploy Pages; the current scheduled cadence and manual production refresh remain unchanged.
- **Related:** `.github/workflows/deal-desk.yml`, `tests/test_workflow_policy.py`, `ARCHITECTURE.md`, `TESTING_AND_RELEASE.md`.

## Production failures fail closed with actionable diagnostics

- **Date:** 2026-07-08 CI-01-T3/T4.
- **Decision:** strict verifier failures and bot-push stale-main failures write compact GitHub Actions step summaries while preserving traceback/assertion output. Every production candidate, including a no-change run, must compare `origin/main` with the run base SHA before an explicit main-only push or deploy and refuse publication if main moved.
- **Context:** production failures were safe but not always immediately actionable, and bot push relied on the final `git push` to discover non-fast-forward races.
- **Rationale:** publication must fail before remote overwrite risk, and operators need the failed stage, invariant, artifact/file, expected/actual values and recommended next action in one place.
- **Consequences:** stale production runs do not rebase, merge, force-push or overwrite remote main; a new production refresh must run on the current main. Verifier assertions remain strict.
- **Related:** `.github/workflows/deal-desk.yml`, `scripts/release_diagnostics.py`, `scripts/verify_public_artifacts.py`, `tests/test_release_diagnostics.py`.

## Local LaunchAgent remains disabled by default

- **Date:** 2026-07-11 CI-01-T5.
- **Decision:** GitHub Actions scheduled production refresh is the only official production automation path. The local LaunchAgent remains unloaded by default, is not part of the production release contract and is retained only as an explicit emergency/manual local fallback.
- **Context:** CI-01 T1-T4 moved release semantics, production refresh, bot publication safety and failure diagnostics into the controlled GitHub Actions path. The local LaunchAgent was verified as unloaded / service not found at CI-01 closure.
- **Rationale:** a local scheduled writer can run outside the CI concurrency, stale-main, verifier and Pages publication contract. Keeping it disabled preserves one authoritative production path while retaining a manual escape hatch.
- **Consequences:** tasks must not restore LaunchAgent automatically. It must not run during development, integration, branch work, PR work or while a GitHub Actions production refresh may run. Any manual restore requires an intentional local-only decision and a clean working tree; production publication still goes through GitHub Actions.
- **Related:** `TESTING_AND_RELEASE.md`, `CURRENT_STATE.md`, `ARCHITECTURE.md`, `scripts/scheduled_update.py`.
