# CIS-ORCHESTRATOR-01 — 30-minute production orchestration

Implementation checkpoint: **23 July 2026 (Europe/Moscow)**.

This document records the local implementation contract. It does not activate a source, publish a branch, start `workflow_dispatch`, run a live smoke or close production acceptance.

## Pre-change architecture and root cause

The production workflow had three weekday cron expressions that together targeted 08:30–18:30 Moscow time at 30-minute intervals. Pull requests and ordinary pushes already ran offline validation only; `schedule` and `workflow_dispatch` owned live refresh. Bot-generated data/output paths were excluded from the push trigger.

Production used the workflow-level `deal-desk-pages` concurrency group with `cancel-in-progress: true`. A newer slot could therefore cancel a valid running refresh. The job ran tests and `run.py --live` before installing `requirements-ci.txt`. Bot publication fetched `origin/main`, required the remote to equal `GITHUB_SHA` and then used a normal main-only push.

The no-op defect had four connected causes:

1. `extract_deal_record()` assigned a new wall-clock `last_seen_at` on every observation, and merge retained it even when the normalized record and official evidence were unchanged.
2. live runs rebuilt HTML, snapshot and CSV with new generation/source-health timestamps.
3. the workflow staged and committed those generated changes, then always prepared and uploaded Pages.
4. CNPF validators/fingerprints were stored in tracked `latest_snapshot.json`; cross-run throttling therefore depended on creating a bot commit.

As a result, operational polling time could create a repository/public delta without a new or changed economic event.

## Final workflow design

`.github/workflows/deal-desk.yml` contains exactly one production cron:

```text
*/30 * * * *
```

GitHub may delay scheduled starts. Thirty minutes is the target evaluation cadence, not a real-time SLA. `workflow_dispatch` remains available but is not invoked by this implementation. Pull-request and push validation remain offline and contain no live request. Generated paths and documentation-only paths retain the existing loop/side-effect guards.

The production job installs pinned `requirements-ci.txt` dependencies before tests and before live discovery. One production concurrency group remains, but `cancel-in-progress: false` lets a valid writer finish and queues the next slot. No concurrent discovery or push can occur.

The live step emits `publish_delta`. Replay, workbook/manifest rebuild, site preparation, bot commit, Pages upload and the deploy job require `publish_delta=true`. Strict checked-in artifact verification and a fresh read-only parent check still run on a successful no-op. The bot-push command repeats the fetch/parent comparison immediately before a normal fast-forward push. If `origin/main` moved, publication fails without merge, rebase or force push.

## Source interval table

The global workflow evaluates every 30 minutes. Eligibility is source-specific and explicit.

| source_id | enabled | required | type | prior effective cadence | explicit cadence | request cap (index/detail) | production change |
|---|---:|---:|---|---|---:|---:|---|
| `issuer_news` | true | true | official HTML/feed group | every production schedule | 120 min | 5 / 15 | fewer stable HTML requests |
| `ru-moex` | true | true | official API | every production schedule | 30 min | 1 / 100 | 24/7 evaluation cadence |
| `configured_rss` | true | true | official RSS | every production schedule | 30 min | 1 / 0 | 24/7 evaluation cadence |
| `deal_news` | true | true | discovery RSS | every production schedule | 30 min | 2 / 0 | 24/7 evaluation cadence |
| `company_news` | true | true | discovery RSS | every production schedule | 30 min | 3 / 0 | 24/7 evaluation cadence |
| `deal_archive` | true | false | archive discovery RSS | every production schedule | 360 min | 5 / 10 | less frequent heavy archive polling |
| `gdelt` | false | false | discovery API | zero requests | 120 min | 3 / 0 | none; disabled |
| `sec_filings` | false | false | regulator API | zero requests | 360 min | 8 / 0 | none; disabled |
| `moex_quotes` | true | false | market API | every production schedule | 30 min | 3 / 0 | 24/7 evaluation cadence |
| `kz-kase` | false | false | exchange HTML | zero requests; 360 configured | 360 min | 1 / 10 | none; implemented-disabled |
| `kz-aix` | false | false | research HTML | zero requests | 360 min | 1 / 0 | none; research |
| `am-amx` | false | false | blocked HTML | zero requests; 720 configured | 720 min | 1 / 8 | none; blocked |
| `md-bvm` | false | false | exchange HTML | zero requests; 720 configured | 720 min | 1 / 8 | none; implemented-disabled |
| `cnpf_moldova` | false | false | official Atom/detail | zero requests; 30 configured | 30 min | 1 / 8 | none; implemented-disabled |
| `uz-uzse` | true | false | exchange HTML/detail | every production schedule | 120 min | 3 / 10 | fewer stable HTML requests |
| `uz-openinfo` | false | false | research portal | zero requests | 360 min | 1 / 0 | none; research |
| `kg-kse` | false | false | research HTML | zero requests | 360 min | 1 / 0 | none; research |
| `by-bcse-csd` | false | false | research infrastructure | zero requests | 360 min | 1 / 0 | none; research |

KASE, BVM and CNPF remain `implemented_disabled`; AMX remains `blocked`. CNPF remains configured for 30-minute eligibility but `enabled=false`, so its transport and trust-store dependency are not initialized.

## Deterministic eligibility state machine

One timezone-aware UTC `ORCHESTRATION_AT` is captured once per workflow run and injected into `run.py`. The 30-minute base-slot index is:

```text
floor(ORCHESTRATION_AT unix seconds / 1800)
```

For a source interval, the number of base slots is `ceil(interval_minutes / 30)`. A stable SHA-256-derived source phase distributes intervals longer than 30 minutes. The source is due only when the current slot matches its phase and the same slot has not already been attempted. Therefore the same policy, operational state and orchestration time always produce the same decision across process restarts.

Decision order is:

```text
disabled / blocked / research
→ active bounded backoff
→ deterministic UTC slot and same-slot guard
→ eligible
→ completed_changed / completed_unchanged
   or failed_transport / failed_http / failed_parser
```

Disabled, blocked, research-only, not-due and backoff sources perform zero transport initialization and zero requests.

## Operational-state persistence

Polling state uses transactional schema version `2` and lives under `${{ runner.temp }}/deal-markets-orchestration/state.json` in production. It is restored/saved with `actions/cache/restore@v4` and `actions/cache/save@v4`. The stable restore prefix is `deal-markets-orchestration-v2-${{ runner.os }}-main-`; every save key adds `${{ github.run_id }}-${{ github.run_attempt }}`, so immutable GitHub caches can advance on every production run without a key collision. Version 1 caches are intentionally incompatible and cannot be restored under the v2 prefix. The production job is explicitly limited to `refs/heads/main`. Every state transition uses a same-directory temporary file, `fsync` and atomic replace.

The persisted document makes its acceptance boundary explicit:

- `committed` is the only authoritative generation restored by a later runner;
- `candidate` starts as a deep copy of committed state and receives this runner's discovery mutations;
- `failure_patch` contains only `last_attempt_at`, `last_attempt_slot`, `consecutive_failures`, sanitized `last_error_code`, bounded `next_eligible_at` and failure `last_result`;
- `accepted_generation` increments only when candidate state is promoted;
- `state_status` is `candidate` during discovery and must be `committed` before cache save.

ETag, Last-Modified, entry/content fingerprints, processed IDs, source success timestamps and other evidence-consumption fields never enter `failure_patch`. They are accepted only with the whole candidate generation. State is never staged by Git, never enters the economic dataset and is not read or written by replay.

On a missing/evicted cache, the schema starts empty but deterministic UTC slot phasing still prevents every 120/360-minute source from firing together. Conditional validators may be lost and one due source may perform its capped unconditional index request. GitHub cache retention/eviction is therefore a bounded efficiency limitation, not an economic-data or request-storm mechanism.

Corrupted, unfinalized or wrong-version state fails the current live run closed before any source request. The runtime may atomically replace the runner-local file with a clean v2 document for diagnostics, but that replacement has no accepted transaction and cannot supersede the last compatible cache. The failure is not treated as healthy and does not create a public delta.

Discovery atomically writes the candidate transaction but does not save it to a cross-run cache. One `always()` finalization step evaluates canonical step outcomes:

- successful `publish_delta=false` + strict verifier + parent check promotes candidate state;
- successful `publish_delta=true` + strict verifier + parent check + allowlisted commit/fast-forward push promotes candidate state;
- every other outcome rolls back candidate evidence and merges only `failure_patch` into the prior committed generation.

A second validator requires a finalized committed document. Cache save requires both canonical finalization and validation outputs. Missing/malformed `publish_delta`, missing step outcomes, a candidate document or a failed finalizer cannot become the newest cache.

Deployment starts only after a delta's candidate state was accepted and cached following the successful push. A later Pages failure does not invalidate the economic commit already present on `main`. Hard cancellation can lose the current candidate/failure patch, causing a bounded re-fetch, but the previous immutable committed cache remains authoritative and unpublished evidence is never silently skipped.

## Conditional requests and backoff

CNPF retains `If-None-Match`, `If-Modified-Since`, HTTP 304 health, zero 304 detail requests, entry fingerprints and the one-feed/eight-detail caps. Validators and fingerprints now belong to external operational state when the production orchestrator is used. Other adapters do not receive unsupported conditional headers.

A source has at most one orchestration execution attempt per eligible run. There is no orchestrator retry loop or random jitter. Consecutive failures increase delay exponentially from at least the configured interval, capped at **1,440 minutes**. A valid `Retry-After` seconds/date value is respected up to that cap. Success clears failures and backoff. Disabled state takes precedence over stale backoff.

Required-source transport/HTTP/parser/empty failure fails the live step closed after sanitized diagnostics. Optional failure remains explicit and never becomes healthy merely because the pipeline continues.

## No-op publication contract

An unchanged observation preserves both the existing canonical row and `last_seen_at`. `first_seen_at` is assigned only when the record is first created. A changed normalized record or official evidence may advance `last_seen_at`.

After discovery, canonicalization, enrichment and supported link upgrades, `run.py` compares exact dataset bytes and stable source-health state:

- `publish_delta=false` when dataset bytes, stable health state and the versioned presentation fingerprint are unchanged;
- `publish_delta=true` for a new/changed canonical record, stable lifecycle/quality/provenance correction, a stable health transition that must be disclosed, or a changed versioned artifact-generator/config fingerprint.

Scheduler time, last attempt/success refresh, request counters, unchanged observation, workflow run ID and validator-only changes are not publishable. A no-op writes candidate operational state, prints `NO_PUBLISH_DELTA`, preserves dataset SHA/Build ID and exits before HTML/snapshot/CSV generation. The workflow verifies the existing synchronized artifacts and current parent, then promotes candidate state, validates it and saves a new immutable cache. It skips bot commit, push, Pages upload and deployment.

For a real delta, local dataset/artifact generation does not accept operational evidence. Promotion occurs only after strict verification, stale-parent protection, allowlisted bot commit and successful fast-forward push. If verifier, parent, commit or push fails, the next runner restores the prior validators/fingerprints/processed IDs and can rediscover the same unpublished evidence. Required-source failure after another source found a delta follows the same rollback; only the failed required source's bounded backoff patch may persist.

The stable presentation fingerprint covers `config.json`, `run.py`, `report.py` and `workflow.py`; it is stored in the snapshot, not in the economic dataset or operational cache. This makes a deliberate merged generator/config change publish exactly once even when canonical economic rows are unchanged, without changing the dataset-derived Build ID.

## Sanitized diagnostics

Before any strict required-source failure, stdout receives one compact `ORCHESTRATION` JSON row per orchestrated source. Fields cover identity/configuration, decision/reason, backoff, request counts/caps, HTTP class, parser status, discovery/archive/whitelist/accept/review/exclude counts, sanitized error code and next eligibility.

The formatter omits response bodies, headers, authorization, cookies and stack traces. Reasons are reduced to bounded lowercase codes. This is the minimum orchestration evidence required by CIS-ORCHESTRATOR-01; it does not add a diagnostics dashboard, public history or CIS-DIAGNOSTICS-01.

## Production acceptance still required

This local branch requires publication, merge and a multi-run acceptance sequence:

1. Post-merge push validation must pass with production refresh and deploy skipped.
2. The first qualifying natural `schedule/main` run must use the merged orchestrator, install dependencies before discovery, report a legitimate v2 cache miss after the schema transition, call only due sources, finalize state at the correct no-op/push boundary and save a new uniquely keyed committed v2 cache. A real public delta may produce one verified six-artifact bot commit and deploy; a no-op must produce neither.
3. A later natural `schedule/main` run on a separate runner must restore the committed v2 cache saved by the first run, prove that no candidate document was authoritative, apply source intervals, keep disabled/blocked/research sources at zero requests and, when evidence is unchanged, log `NO_PUBLISH_DELTA` with no bot commit or deploy and unchanged Build ID/dataset SHA.

If the second run contains a legitimate public delta, it is not no-op evidence; wait for a later natural unchanged schedule rather than triggering an artificial run. CIS-ORCHESTRATOR-01 closes only after both separate-run cache restoration and a genuine scheduled no-op are proven. Production evidence must also retain strict verification, workbook parity, public artifact identity and safety-state checks. CNPF Ubuntu TLS remains unverified and no source activation is part of this task.
