# Regressions

Registry reviewed against current code and test definitions: **2026-07-04**. The 61 tests were executed for the AUD-01 MOEX market-data health fix. Test names below are exact. Where no dedicated unit test exists, the protecting release check is named honestly.

## Health and source handling

### REG-01 — False-green health when sources fail or return nothing

- **Failure mode:** dashboard says healthy after transport failure, malformed/empty feed or zero usable rows from required discovery.
- **Why it mattered:** analysts could trust stale data as current.
- **Root mechanism:** source functions returned empty lists and health treated absence as success.
- **Current protection:** required empty runs are `empty`; fetch errors are recorded; discovery must be nonzero; required runs must be fresh and usable.
- **Tests/checks:** `test_rss_transport_failure_is_not_silently_successful`, `test_empty_required_source_is_not_success`, `test_structurally_empty_feed_is_an_error`, `test_health_cannot_be_green_when_all_discovery_feeds_are_empty`; strict verifier checks required runs.
- **Files:** `run.py`, `sources.py`, `scripts/verify_public_artifacts.py`, `tests/test_core.py`.

### REG-23 — False-green market tape from partial MOEX rows

- **Failure mode:** a successful MOEX response with `LAST=null` and zero-valued metadata rendered `— ₽ +0.00%` while system health stayed fully green.
- **Why it mattered:** missing market data looked like a real unchanged quote and overstated market-tape availability.
- **Root mechanism:** quote rows were counted by presence, not usable price data; rendering treated the independent change field as valid even when no last price existed.
- **Current protection:** quotes are classified as `valid`, `partial`, `unavailable` or `error`; missing price clears the displayed change; market-data availability is reported separately from the core deal pipeline.
- **Tests/checks:** `test_moex_quotes_distinguish_valid_partial_and_unavailable_rows`, `test_market_health_reports_partial_or_unavailable_without_breaking_core_pipeline`, `test_market_tape_renders_missing_values_without_false_zeroes`.
- **Files:** `sources.py`, `run.py`, `report.py`, `tests/test_core.py`.

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

### REG-24 — Global XLSX text search hiding sheet-specific omissions

- **Failure mode:** a deal ID removed from `Deals` still passed strict verification when the same ID remained in `Sources & QA`; `Summary` could also contain the wrong current transaction set.
- **Why it mattered:** a logically incomplete workbook could be published as synchronized even though its package still contained every ID somewhere.
- **Root mechanism:** the verifier searched all XLSX XML as one text blob instead of validating each sheet against its own dataset contract.
- **Current protection:** `Deals` requires the exact canonical ID set with no missing, phantom or duplicate rows; `Summary` maps its visible transaction fields back to unique dataset IDs and requires exact parity with `select_key_deals()`; `Financials`, eligible `Multiples`, and `Sources & QA` use their own production semantics.
- **Tests/checks:** `test_strict_verifier_rejects_missing_deals_row_when_id_exists_on_other_sheet`, `test_strict_verifier_rejects_duplicate_deals_id`, `test_strict_verifier_rejects_extra_phantom_deals_id`, `test_strict_verifier_rejects_wrong_summary_current_deal_set`, `test_strict_verifier_rejects_technical_filing_in_summary`, `test_strict_verifier_rejects_missing_financials_row`, `test_strict_verifier_rejects_missing_eligible_multiples_row`, `test_strict_verifier_rejects_missing_source_register_row`; strict verifier is exercised against both workbook builders.
- **Files:** `scripts/verify_public_artifacts.py`, `tests/test_xlsx_verifier.py`.

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
- **Current protection:** classifier and workflow suppress shared technical patterns, including routine central-bank Lombard/collateral eligibility notices; records remain traceable as `technical_filing`.
- **Tests/checks:** `test_workflow_suppresses_technical_exchange_notices`, `test_repo_trading_notice_is_not_a_deal_or_task`, `test_cbr_lombard_list_notices_are_non_actionable_technical_filings`, `test_bond_buyback_is_dcm_not_ma`.
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

### REG-28 — Confirmed label approved incomplete or single-source records

- **Failure mode:** a record could become `approved` from one confirmed secondary publication, or while a DCM/ECM amount and currency remained missing despite being required for analyst readiness.
- **Why it mattered:** evidence confidence and transaction completeness were conflated, so discovered records could look analyst-ready without primary evidence or usable terms.
- **Root mechanism:** the quality gate checked only the row-level `evidence_label` and party fields; it did not inspect canonical source types or DCM/ECM amount/currency completeness. Long-form Russian units such as `миллиардов` were not parsed.
- **Current protection:** approval requires a confirmed official/issuer source or at least two canonical publications, while material DCM/ECM records receive blocking flags for missing amount or currency. Long-form billion/million units are extracted by the normal parser. Technical filings remain governed by technical/noise rules.
- **Tests/checks:** `test_quality_approval_requires_primary_evidence_or_corroboration`, `test_quality_gate_flags_missing_critical_dcm_fields`, `test_dcm_long_form_amount_is_extracted_instead_of_not_disclosed`, `test_official_whoosh_feed_discovers_real_dcm_without_redemption_noise`, `test_dcm_yuan_currency_is_not_converted_to_rubles`, `test_noise01_production_records_remain_canonical`.
- **Files:** `deals.py`, `report.py`, `tests/test_core.py`, canonical dataset and dependent public artifacts.

### REG-27 — One publication counted twice through direct and discovery URLs

- **Failure mode:** a direct publisher URL and a Google News representation of the same article were stored as two independent sources.
- **Why it mattered:** `source_count` and analyst perception of corroboration were overstated even when the quality decision itself did not depend on the count.
- **Root mechanism:** source identity used literal URL equality; discovery/access representation identity was treated as publication identity.
- **Current protection:** canonical publication sources retain multiple raw URL `representations`; exact normalized URLs merge, and legacy direct + Google rows use only an unambiguous exact publisher/date one-to-one fallback. Tracking parameters/fragments do not create publications; missing metadata, different publishers, different dates and ambiguous groups do not merge. Source count and quality fields are recomputed on migration and merge.
- **Tests/checks:** `test_same_publication_direct_and_google_counts_once_and_preserves_representations`, `test_tracking_query_and_fragment_variants_count_as_one_publication`, `test_same_transaction_different_publishers_remain_independent_publications`, `test_same_publisher_different_articles_remain_separate_publications`, `test_attributed_or_syndicated_articles_are_not_merged_without_strong_identity`, `test_incomplete_publication_metadata_does_not_trigger_direct_google_merge`, `test_publication_canonicalization_is_idempotent`, `test_source_count_and_quality_are_recomputed_after_publication_canonicalization`; strict verifier checks canonical source counts and XLSX representation lineage.
- **Files:** `deals.py`, `models.py`, `sources.py`, `run.py`, both workbook builders, strict verifier, canonical dataset and dependent public artifacts.

### REG-26 — Preliminary and final DCM lifecycle split into separate transactions

- **Failure mode:** a preliminary coordinated bond-placement signal and the later official result remained separate economic transactions when event IDs, dates, amounts and headlines differed.
- **Why it mattered:** the archive overstated deal count, leaked a preliminary amount into review surfaces and lost the relationship between one coordinated deal and its distinct issue series.
- **Root mechanism:** database identity used a 10-day window plus weak amount/title/entity similarity; issue series were not extracted into `security_code`, canonical source lineage was not considered on replayed archive events, and a same-ID refresh could overwrite a populated strong identity with `Not disclosed` before lifecycle clustering.
- **Current protection:** DCM identity uses overlapping ISIN/security-code/series/registration identifiers or exact stored source lineage together with the same issuer. Source lineage includes canonical publication URLs and nested raw/discovery URL representations; explicitly disjoint strong issue identities still block a lineage merge. Issuer-only weak signals remain separate. Canonical selection prioritizes source quality, lifecycle maturity and completeness; merge precedence keeps status and final terms monotonic while unioning issue identities and sources. Same-ID DCM refreshes preserve populated strong identities, accept newly discovered identities and monotonically union expanded issue-code sets.
- **Tests/checks:** `test_dcm_lifecycle_merges_preliminary_aggregate_into_official_final`, `test_dcm_lifecycle_allows_amount_growth_with_shared_issue_identity`, `test_dcm_lifecycle_final_terms_override_preliminary_source_rank`, `test_dcm_lifecycle_does_not_merge_distinct_issue_series`, `test_dcm_lifecycle_does_not_merge_on_same_issuer_and_weak_signals_alone`, `test_dcm_lifecycle_repeat_processing_is_idempotent`, `test_dcm_lifecycle_archive_signal_cannot_recreate_final_transaction`, `test_dcm_lifecycle_known_source_lineage_prevents_recreation_without_identifiers`, `test_dcm_lifecycle_rediscovered_google_representation_after_source_canonicalization`, `test_dcm_lifecycle_representation_processing_orders_converge_to_canonical_final`, `test_dcm_lifecycle_representation_refresh_is_stable_across_three_runs`, `test_dcm_lifecycle_representation_does_not_overmerge_different_issue`, `test_dcm_refresh_preserves_populated_strong_identity_when_incoming_missing`, `test_dcm_refresh_adds_strong_identity_when_existing_missing`, `test_dcm_refresh_unions_partial_and_expanded_issue_identity`, `test_dcm_refresh_repeat_is_identity_idempotent`.
- **Files:** `deals.py`, `tests/test_core.py`, canonical dataset and dependent public artifacts.

### REG-29 — CIS exchange expansion creates permission, noise or issue-identity drift

- **Failure mode:** a publicly readable exchange is labelled connected before unattended access/reuse is resolved; government/technical notices create deals or tasks; one programme amount is copied to every issue; or several ISINs collapse into one event.
- **Why it mattered:** production coverage could overstate legal/operational readiness and corrupt DCM counts, economics and analyst workflow.
- **Root mechanism:** treating public access as reuse permission, broad keyword scraping, publisher-level identity and programme-level amount extraction.
- **Current protection:** KASE, AMX and BVM have separate access/reuse and production states; all remain disabled after the Wave 1 checkpoint. One shared adapter applies source-specific allowlists/exclusions, fail-closed health, factual-field-only retention, `source_id + source_event_id` lineage, distinct ISIN events and issue-level amount extraction. AMX multiplication is allowed only for deterministic quantity × denomination.
- **Tests/checks:** `test_wave1_registry_is_implemented_but_not_enabled`, `test_three_positive_publications_per_source`, `test_three_negative_publications_per_source_are_suppressed`, `test_programme_tranche_and_distinct_isin_identity`, `test_amx_amount_is_deterministically_derived`, `test_bvm_issue_amount_does_not_use_programme_target`, `test_lifecycle_is_monotonic_and_repeat_fetch_is_idempotent`, `test_health_fails_closed_on_empty_markup_and_antibot`.
- **Files:** `exchange_sources.py`, `sources.py`, `models.py`, `deals.py`, `classifier.py`, `config.json`, `report.py`, `tests/test_cis_exchange_sources.py`.

### REG-30 — Broad regulator feed creates false deals or unsafe activation

- **Failure mode:** broad CNPF notices create transactions/tasks, preliminary registration is labelled `Issued`, several ISINs collapse, polling exceeds the agreed cap, or the source is labelled connected without a successful current live check.
- **Why it mattered:** this would overstate Moldova coverage, corrupt lifecycle/economics and ignore the source's page-specific permission boundary.
- **Root mechanism:** broad keyword ingestion, title-based fallback identity, official-source quality bypass, unbounded polling and treating a generic terms page as sufficient activation evidence.
- **Current protection:** a separate namespace-aware Atom adapter applies strict allowlists/exclusions, immutable entry lineage, distinct-ISIN events, complete-economics lifecycle/quality rules, exact attribution, page-specific restriction stops, 30-minute state gating, conditional feed requests, entry fingerprints, one-feed/eight-new-or-changed-detail hard caps and fail-closed per-source diagnostics. The CNPF transport can use the maintained platform trust store through `truststore` with certificate and hostname verification required. Its macOS checkpoint passed, but the source remains `implemented_disabled` because the server omits its intermediate certificate and the deployed Ubuntu transport is not verified.
- **Tests/checks:** `tests.test_cnpf_source` covers six positive and eight negative fixtures, XML/HTTP/transport/restriction failures, identity/lifecycle/dedup/fixed-point behavior, polling caps/state, quality/task behavior and coverage/mobile contracts; full regression and strict artifact checks remain required before any future activation.
- **Files:** `cnpf_source.py`, `sources.py`, `run.py`, `models.py`, `deals.py`, `config.json`, `report.py`, `tests/test_cnpf_source.py`, `CIS_SOURCE_CNPF_IMPLEMENTATION.md`.

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

### REG-25 — Documentation-only push triggering a production refresh

- **Failure mode:** a change limited to project documentation ran live collection, rebuilt public artifacts, created a bot data commit and redeployed Pages.
- **Why it mattered:** non-production edits mutated remote data and public state while consuming the full release pipeline.
- **Root mechanism:** the `push` trigger ignored generated artifacts but matched every documentation path.
- **Current protection:** `push.paths-ignore` excludes documentation-only candidates that are not runtime or Pages inputs; production code, config, builders, verifier, tests, workflows and non-generated data remain production-relevant by default. Schedule and manual dispatch remain unconditional, while generated output/archive paths remain excluded to prevent a bot loop.
- **Tests/checks:** `test_push_path_matrix`, `test_non_push_production_triggers_are_preserved`, `test_generated_artifacts_remain_a_loop_guard`.
- **Files:** `.github/workflows/deal-desk.yml`, `tests/test_workflow_policy.py`.

### REG-31 — No-op scheduled run creates a bot commit and deployment

- **Failure mode:** unchanged evidence rewrites generated timestamps, creates `chore: refresh deal desk` and redeploys identical Pages content.
- **Root mechanism:** publication was gated only by staged file differences after unconditional generation.
- **Current protection:** exact dataset/stable-health/versioned-presentation `publish_delta`; replay/build/commit/upload/deploy require `true`; no-op prints `NO_PUBLISH_DELTA`.
- **Tests/checks:** `test_noop_skips_commit_upload_and_deploy`, `test_operational_health_timestamp_alone_is_not_publishable`; workflow contract review.
- **Files:** `run.py`, `.github/workflows/deal-desk.yml`, orchestrator tests.

### REG-32 — Unchanged observation advances `last_seen_at`

- **Failure mode:** the same normalized event changes database bytes, dataset SHA and Build ID on every poll.
- **Root mechanism:** extraction used the wall clock and merge retained the incoming observation time without comparing meaning.
- **Current protection:** one injected observation time plus canonical comparison excluding seen timestamps; unchanged meaning preserves the stored `last_seen_at`.
- **Tests/checks:** `test_identical_observation_preserves_last_seen_dataset_sha_and_build_id`.
- **Files:** `deals.py`, `run.py`, `tests/test_orchestrator_noop.py`.

### REG-33 — Duplicate scheduled production runs overlap or cancel valid work

- **Failure mode:** the next 30-minute slot overlaps discovery/push or cancels a valid writer.
- **Root mechanism:** production used a shared group with `cancel-in-progress: true`.
- **Current protection:** one production group with `cancel-in-progress: false`; queued runs serialize, and parent verification prevents stale publication.
- **Tests/checks:** `test_production_concurrency_group_is_preserved`, bot-push real-Git race tests.
- **Files:** `.github/workflows/deal-desk.yml`, `release_diagnostics.py`.

### REG-34 — Live discovery starts before pinned production dependencies

- **Failure mode:** an adapter may initialize before its pinned runtime dependency is installed.
- **Root mechanism:** `requirements-ci.txt` installation followed `run.py --live`.
- **Current protection:** pinned dependency installation precedes tests and live discovery.
- **Tests/checks:** `test_production_dependencies_precede_live_discovery`.
- **Files:** `.github/workflows/deal-desk.yml`.

### REG-35 — Operational polling timestamps change public artifacts

- **Failure mode:** attempts, successes, counters, validators or health-check time alone regenerate HTML/snapshot/CSV/XLSX.
- **Root mechanism:** polling state lived in tracked snapshot state and generation ran unconditionally.
- **Current protection:** schema-versioned external atomic state, deterministic slots and stable-health transition comparison; replay is state-independent.
- **Tests/checks:** operational-state restart/corruption tests, `test_operational_health_timestamp_alone_is_not_publishable`, replay fixed-point checks.
- **Files:** `orchestrator.py`, `run.py`, workflow, tests.

### REG-36 — Immutable cache key or invalid state freezes/poisons cross-run orchestration

- **Failure mode:** a constant cache key cannot be replaced, a branch/platform-ambiguous prefix restores incompatible state, or `always()` saves a missing/corrupt directory after an earlier failure.
- **Impact:** validators and backoff freeze, disappear or are replaced, so separate runners cannot enforce source cadence safely.
- **Current protection:** schema/runner/main restore prefix; unique run ID/attempt save key; main-only production gate; present/schema-valid state check before cache save; offline two-process persistence regression.
- **Tests/checks:** `test_cross_run_operational_state_uses_cache_not_git`, `test_orchestration_state_validator_requires_present_valid_schema`, `test_state_and_public_artifacts_survive_a_second_python_process`.
- **Files:** `.github/workflows/deal-desk.yml`, `release_diagnostics.py`, orchestrator/workflow tests.

### REG-37 — Unpublished source evidence marked consumed before verification/publication

- **Failure mode:** discovery advances ETag, Last-Modified, fingerprints, processed IDs or successful evidence timestamps, then strict verification, stale-parent checking, bot commit or bot push fails; the next runner restores those fields and silently skips the unpublished evidence.
- **Impact:** a valid economic event can be absent from `main` while operational state says it was already handled.
- **Root mechanism:** the live process mutated one authoritative state object and the workflow saved its cache before the artifact verifier and publication boundary.
- **Current protection:** schema v2 stores explicit `committed`, `candidate` and `failure_patch` namespaces. Candidate evidence is promoted only after a successful verified no-op or successful fast-forward bot push. All other terminal paths roll back candidate evidence and merge only whitelisted attempt/error/backoff fields into the prior committed generation. Cache save occurs only after finalization and committed-state validation; hard cancellation leaves the prior immutable cache authoritative.
- **Tests/checks:** `tests/test_orchestrator_transaction.py` covers verifier/stale-parent/commit/push rollback, required and optional source failures, successful no-op/publication, deployment failure and hard cancellation, including three separate-process scenarios; `test_state_transaction_finalizes_only_after_release_boundary` protects workflow ordering.
- **Files:** `orchestrator.py`, `run.py`, `.github/workflows/deal-desk.yml`, `release_diagnostics.py`, transaction/workflow tests.

## Using this registry

For a change, run the named test/checks for the affected rows first. Update this file only when a failure mode, protection or exact test changes. Do not treat a green historical verification date as proof of the current build; follow [`TESTING_AND_RELEASE.md`](TESTING_AND_RELEASE.md).
