# Current state

Last verified: **2026-07-11 MSK (Europe/Moscow)**.

| Field | Verified value |
|---|---|
| Branch | `main` |
| Last verified production release commit | `65be8638edbc86aebd4bb515364ed2fa326200a4` |
| Last production workflow commit | `65be8638edbc86aebd4bb515364ed2fa326200a4` |
| Last bot/data commit | `3070d5433155fa1af040660320c212763920274e` |
| Last verified production Build ID | `607838a99475` |
| Dataset SHA-256 | `607838a9947569ce070b1d321c664e8cfbd4119d318570c81d49972c79a6734a` |
| Records | 105 |
| Last verified test count | 129/129 tests passed in successful production workflow run `#81` |
| Public deployment | Actions run `#81` succeeded; public artifacts are synchronized |
| Source health | `ok` in the successful production workflow |
| Discovery | `ok` in the successful production workflow |
| Freshness | `ok` in the successful production workflow |
| System status | `ok` in the successful production workflow |
| Excel sync | `true`; manifest, dataset and internal snapshot agree |
| LaunchAgent | unloaded / service not found; not a production automation path |

Current quality distribution and deal-type distribution should be read from the synchronized release artifacts for Build ID `607838a99475`. The record count is 105. These are build facts, not coverage targets.

## Recent completed milestones

- **AUD-01 closed:** unavailable MOEX quotes render honestly and market-data health is reported separately from the core deal pipeline.
- **AUD-03 closed:** strict XLSX verification enforces sheet-specific dataset contracts instead of relying on a global workbook text search.
- **AUD-02 implementation complete:** documentation-only pushes are excluded from the production refresh, automated path-policy checks pass, and the workflow-changing commit completed its production-trigger proof. This documentation-only commit performs the final end-to-end trigger proof required to close AUD-02.
- **CI-01 baseline established:** successful run `#60` at `1c990c1f249218de69234f8d61b92cf847ea2bad` produced Build ID `c87d0f63f7e3`, 91 records, 111/111 tests and synchronized public artifacts.
- **CI-01 T1-T4 verified:** release contract, replay semantics, validation/production split, stale-main bot safety and failure diagnostics are implemented and verified through production run `#81`.

The production-hardening protections remain in force, including required-source health, synchronized artifacts, replay canonical fixed-point semantics, deal-type-specific statuses, technical-noise suppression, complete Build ID hashing and shared current-deal selection.

The public Pages release contract is dashboard HTML, `build_manifest.json`, `precedent_transactions.csv` and `precedent_transactions.xlsx`. `latest_snapshot.json` is internal-only; public 404 is expected while the architecture remains unchanged.

Final LaunchAgent policy: GitHub Actions scheduled production refresh is the only official production automation path. The local LaunchAgent remains unloaded by default, is not part of the production release contract and is retained only as an explicit emergency/manual local fallback. It must not run during development, integration, branch work, PR work or while a GitHub Actions production refresh may run. Restoring it must be an intentional manual action after confirming a clean working tree and local-only use.

## Current open questions

- Historical failed runs in the `#50`-`#55` range showed the same failed verifier step / repeated failure pattern. The exact assertion is unavailable here; they are likely in the same pre-fix family, but that is not independently proven without the logs.
- `config.json` contains an account-specific contact value in the disabled SEC user-agent setting. It is already public and is not an active credential, but a future privacy review should decide whether to replace it with a project-level contact identifier.

No other open issue is asserted here without current repository evidence.

## Next recommended work

Choose one coherent priority from [`PRODUCT_ROADMAP.md`](PRODUCT_ROADMAP.md), preferably official-source coverage or DCM extraction completeness. Update this file after a significant milestone or published release; do not use it as a commit-by-commit changelog.
