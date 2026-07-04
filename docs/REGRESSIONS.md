# Regressions

Registry reviewed against current code and test definitions: **2026-07-04**. The 58 tests were last executed in the production-hardening verification cycle and were not rerun for the documentation-only review. Test names below are exact. Where no dedicated unit test exists, the protecting release check is named honestly.

## Health and source handling

### REG-01 — False-green health when sources fail or return nothing

- **Failure mode:** dashboard says healthy after transport failure, malformed/empty feed or zero usable rows from required discovery.
- **Why it mattered:** analysts could trust stale data as current.
- **Root mechanism:** source functions returned empty lists and health treated absence as success.
- **Current protection:** required empty runs are `empty`; fetch errors are recorded; discovery must be nonzero; required runs must be fresh and usable.
- **Tests/checks:** `test_rss_transport_failure_is_not_silently_successful`, `test_empty_required_source_is_not_success`, `test_structurally_empty_feed_is_an_error`, `test_health_cannot_be_green_when_all_discovery_feeds_are_empty`; strict verifier checks required runs.
- **Files:** `run.py`, `sources.py`, `scripts/verify_public_artifacts.py`, `tests/test_core.py`.

## Build and artifact integrity

### REG-02 — Build ID based on incomplete selected fields

- **Failure mode:** material row changes could retain the same Build ID.
- **Why it mattered:** mixed or stale artifacts could appear synchronized.
- **Root mechanism:** identity did not cover complete database bytes.
- **Current protection:** SHA-256 of the exact database file; first 12 characters are Build ID.
- **Tests/checks:** `test_build_id_changes_when_any_dataset_field_changes`; strict verifier recomputes the digest.
- **Files:** `run.py`, both workbook builders, `scripts/verify_public_artifacts.py`.

### REG-03 — JSON/CSV/XLSX desynchronization

- **Failure mode:** artifacts showed different rows or builds while counts alone appeared valid.
- **Why it mattered:** dashboard and downloadable model could disagree.
- **Root mechanism:** shallow checks covered package validity/count, not exact CSV fields or workbook IDs.
- **Current protection:** field-by-field CSV verification; manifest/SHA/Build ID checks; exact workbook ID set; formula-error scan.
- **Tests/checks:** strict `scripts/verify_public_artifacts.py`. No dedicated unit test identified for the whole cross-artifact contract.
- **Files:** verifier, workbook builders, `run.py`, public artifacts.

### REG-04 — Replay mutating the persistent database

- **Failure mode:** `run.py --replay` changed database bytes after XLSX build.
- **Why it mattered:** the artifacts immediately became stale against their source dataset.
- **Root mechanism:** replay previously followed write/enrichment paths intended for live mode.
- **Current protection:** replay loads the version-controlled dataset and skips live merge/enrichment/database writes.
- **Tests/checks:** release runbook requires byte-for-byte hash before/after replay. No dedicated regression test identified.
- **Files:** `run.py`, `docs/TESTING_AND_RELEASE.md`.

### REG-05 — Hardcoded current-table row label

- **Failure mode:** UI said “10 rows” while fewer deals were shown.
- **Why it mattered:** visible internal inconsistency.
- **Root mechanism:** static display label.
- **Current protection:** label is derived from `select_key_deals()` count.
- **Tests/checks:** strict verifier checks the dynamic `N строк` label. No dedicated unit test identified.
- **Files:** `report.py`, `scripts/verify_public_artifacts.py`.

### REG-06 — Excel counts formatted as multiples

- **Failure mode:** observation counts rendered as values such as `6.0x`.
- **Why it mattered:** sample size looked like a valuation multiple.
- **Root mechanism:** count cells reused multiple formatting.
- **Current protection:** separate count and multiple formats in both builders.
- **Tests/checks:** workbook visual QA and sheet inspection. No dedicated regression test identified.
- **Files:** both workbook builders.

### REG-07 — Dashboard and Excel used different current-deal selection

- **Failure mode:** Summary listed a different latest transaction set than HTML.
- **Why it mattered:** two public outputs gave different market views.
- **Root mechanism:** duplicated selection logic in builders.
- **Current protection:** CI builder imports `select_key_deals()`; local builder mirrors its curated/recent/materiality rules.
- **Tests/checks:** `test_key_deals_never_mix_historical_curated_precedents_into_live_flow`, strict verifier; visual QA. No single parity unit test identified.
- **Files:** `deals.py`, both workbook builders.

## Classification, streams and workflow

### REG-08 — DCM using M&A status `Closed`

- **Failure mode:** book closure or completed placement became `Closed`.
- **Why it mattered:** transaction stage was semantically wrong.
- **Root mechanism:** generic completion keywords were shared across deal types.
- **Current protection:** DCM/ECM book closure = `Priced`; completed placement = `Issued`; migration repairs old DCM `Closed`.
- **Tests/checks:** `test_normalized_deal_statuses`, `test_dcm_completion_never_uses_ma_closed_status`, `test_priced_dcm_is_a_key_deal_without_ma_closed_status`; strict verifier.
- **Files:** `deals.py`, `tests/test_core.py`, verifier.

### REG-09 — Technical buybacks/REPO becoming P1 debt-comps tasks

- **Failure mode:** exchange plumbing generated banker actions.
- **Why it mattered:** task queue prioritized non-deal noise.
- **Root mechanism:** category keywords were treated as sufficient actionability.
- **Current protection:** classifier and workflow suppress technical patterns; records remain traceable as `technical_filing`.
- **Tests/checks:** `test_workflow_suppresses_technical_exchange_notices`, `test_repo_trading_notice_is_not_a_deal_or_task`, `test_bond_buyback_is_dcm_not_ma`.
- **Files:** `classifier.py`, `workflow.py`, `deals.py`.

### REG-10 — Market roundups/routine content entering transaction streams

- **Failure mode:** ordinary placements, market reviews, target prices or funding commentary appeared as rumors/current deals.
- **Why it mattered:** signal/noise separation broke.
- **Root mechanism:** broad keywords without materiality and stream-specific filters.
- **Current protection:** actionability suppression, materiality rules, mutually separated deal/watchlist/denial/technical buckets.
- **Tests/checks:** `test_workflow_suppresses_non_transaction_finance_news`, `test_report_separates_deal_monitoring_streams`, `test_key_deals_exclude_funds_units_and_ofz_auctions`.
- **Files:** `workflow.py`, `deals.py`, `report.py`.

### REG-11 — Obsolete stream names

- **Failure mode:** labels implied all items were confirmed or that routine DCM belonged to rumors/negotiations.
- **Why it mattered:** UI semantics contradicted record kinds and quality.
- **Root mechanism:** presentation labels predated the bucket model.
- **Current protection:** current streams are `Актуальные сделки`, `Требует проверки`, `Опровержения`, `Technical filings`.
- **Tests/checks:** `test_report_separates_deal_monitoring_streams`; strict verifier rejects obsolete labels.
- **Files:** `report.py`, verifier.

### REG-12 — Non-date-aware market-task ID

- **Failure mode:** marking yesterday’s ticker task complete could hide today’s new move.
- **Why it mattered:** daily workflow state leaked across dates.
- **Root mechanism:** market task ID used ticker without date.
- **Current protection:** market task hash includes the current Moscow date; event-driven task IDs remain stable for the same event.
- **Tests/checks:** `test_workflow_detects_new_events_and_keeps_stable_tasks` covers event-task stability. No dedicated date-rollover test identified.
- **Files:** `workflow.py`.

## Deal data and analytics

### REG-13 — Auto.ru missing buyer T-Technologies

- **Failure mode:** a known buyer remained `Not disclosed` despite source evidence.
- **Why it mattered:** core M&A party extraction was incomplete.
- **Root mechanism:** buyer was present in evidence URL/context but not parsed from the headline.
- **Current protection:** migration recognizes the source evidence and assigns `T-Technologies`; current verifier checks matching rows.
- **Tests/checks:** strict verifier. No dedicated regression test identified for this exact transaction.
- **Files:** `deals.py`, verifier, dataset.

### REG-14 — Publishing EV/EBITDA median with `n=2`

- **Failure mode:** a thin sample appeared as a meaningful public median.
- **Why it mattered:** precedent analysis overstated evidence.
- **Root mechanism:** no minimum sample threshold.
- **Current protection:** medians require at least three eligible observations and always expose counts.
- **Tests/checks:** `test_medians_use_valid_ma_multiples`, `test_median_is_published_at_three_observations`, `test_medians_exclude_financials_published_after_announcement`.
- **Files:** `deals.py`, both workbook builders, `report.py`.

### REG-15 — Old/curated deals entering live/latest

- **Failure mode:** 2022–2024 or curated historical transactions appeared as current deal flow.
- **Why it mattered:** dashboard did not represent the current market.
- **Root mechanism:** archive and curated data were used to pad a list to its limit.
- **Current protection:** `CURATED-` exclusion, Moscow-time recent cutoff, quality/materiality selection, no padding.
- **Tests/checks:** `test_key_deals_never_mix_historical_curated_precedents_into_live_flow`, `test_live_feed_excludes_old_official_archive_items`.
- **Files:** `deals.py`, `sources.py`, workbook builders.

### REG-16 — Distinct bond issues deduplicated together

- **Failure mode:** separate securities from one issuer collapsed into one event.
- **Why it mattered:** DCM coverage lost transactions.
- **Root mechanism:** headline similarity over-weighted shared issuer tokens.
- **Current protection:** different detected ISIN/series identifiers block a near-duplicate match.
- **Tests/checks:** `test_deduplicate_keeps_distinct_bond_issues_for_same_issuer`.
- **Files:** `classifier.py`.

### REG-17 — Google redirect normalized only in the primary URL

- **Failure mode:** `source_url` became direct while `sources[]` retained the aggregator URL.
- **Why it mattered:** evidence views disagreed and traceability remained indirect.
- **Root mechanism:** partial in-place update.
- **Current protection:** successful resolution updates both representations.
- **Tests/checks:** `test_google_rows_upgrade_only_when_direct_url_resolves`, `test_database_preserves_resolved_publisher_url`.
- **Files:** `sources.py`, `deals.py`.

### REG-18 — Invalid ISIN accepted from arbitrary uppercase text

- **Failure mode:** non-ISIN tokens were stored as security identifiers.
- **Why it mattered:** DCM cards presented false precision and dedupe could be corrupted.
- **Root mechanism:** permissive extraction without a numeric check digit.
- **Current protection:** ISIN pattern requires the final numeric check digit; migration cleans invalid stored values.
- **Tests/checks:** `test_isin_requires_numeric_check_digit`, `test_dcm_card_extracts_coupon_maturity_and_isin`.
- **Files:** `deals.py`.

### REG-19 — UTC-dependent recent cutoff

- **Failure mode:** around midnight, the same deal could be recent or stale depending on runner timezone.
- **Why it mattered:** Moscow-market current lists changed inconsistently.
- **Root mechanism:** local/UTC date rather than configured market timezone.
- **Current protection:** current selection derives today from `Europe/Moscow`.
- **Tests/checks:** current selection tests exercise date filtering, but no dedicated midnight-boundary test identified.
- **Files:** `deals.py`.

### REG-20 — Duplicate labels inflating source count

- **Failure mode:** one article counted as several sources under different names.
- **Why it mattered:** evidence strength was overstated.
- **Root mechanism:** dedupe key combined URL and label.
- **Current protection:** non-empty URL is the evidence identity; labels only rank metadata quality.
- **Tests/checks:** `test_same_url_counts_as_one_source_even_with_two_labels`.
- **Files:** `deals.py`.

## CI and deployment

### REG-21 — Stale scheduled build publishing after a newer build

- **Failure mode:** an older queued run could overwrite fresher Pages data.
- **Why it mattered:** successful CI could still publish stale market information.
- **Root mechanism:** concurrent scheduled runs had no supersession policy.
- **Current protection:** workflow-level concurrency group with `cancel-in-progress: true`.
- **Tests/checks:** workflow review and live Actions behavior. No dedicated automated regression test identified.
- **Files:** `.github/workflows/deal-desk.yml`.

### REG-22 — Pages deployment without transient-failure retry

- **Failure mode:** a temporary Pages error left an otherwise valid build unpublished.
- **Why it mattered:** repository and public site diverged.
- **Root mechanism:** one deploy attempt only.
- **Current protection:** first deploy may fail without ending the job; workflow waits and retries once.
- **Tests/checks:** workflow review; the latest verified release exercised the retry path successfully. No unit test identified.
- **Files:** `.github/workflows/deal-desk.yml`.

## Using this registry

For a change, run the named test/checks for the affected rows first. Update this file only when a failure mode, protection or exact test changes. Do not treat a green historical verification date as proof of the current build; follow [`TESTING_AND_RELEASE.md`](TESTING_AND_RELEASE.md).
