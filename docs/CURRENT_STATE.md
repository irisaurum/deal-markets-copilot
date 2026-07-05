# Current state

Last verified: **2026-07-05 05:28 MSK (Europe/Moscow)**.

| Field | Verified value |
|---|---|
| Branch | `main` |
| Last verified production release commit | `a95d86614879ea423a7f0e8c2e62a61c80c81e46` (`chore: refresh deal desk`) |
| Last production workflow commit | `5fab3ad0374422e7dae787f092df2453205e6929` (`ci: skip production refresh for docs-only pushes`) |
| Last bot/data commit | `a95d86614879ea423a7f0e8c2e62a61c80c81e46` (`chore: refresh deal desk`) |
| Last verified production Build ID | `f92e83d7a516` |
| Dataset SHA-256 | `f92e83d7a516b477d3acacb7933f00dec16a1b3c4aeeff7d869f5e2ace3d639e` |
| Records | 87 |
| Last verified test count | 73 tests passed in the AUD-02 verification cycle |
| Public deployment | Actions run `#45` succeeded; Pages deployment succeeded; public manifest matches the production release manifest |
| Source health | `ok`; all required source runs returned usable records |
| Discovery | `ok` |
| Freshness | `ok` |
| System status | `ok` |
| Excel sync | `true`; manifest, dataset and snapshot agree |

Current quality distribution: 18 `approved`, 47 `review`, 22 `rejected`. Current dataset contains 27 M&A, 8 ECM and 52 DCM records. These are build facts, not coverage targets.

## Recent completed milestones

- **AUD-01 closed:** unavailable MOEX quotes render honestly and market-data health is reported separately from the core deal pipeline.
- **AUD-03 closed:** strict XLSX verification enforces sheet-specific dataset contracts instead of relying on a global workbook text search.
- **AUD-02 implementation complete:** documentation-only pushes are excluded from the production refresh, automated path-policy checks pass, and the workflow-changing commit completed its production-trigger proof. This documentation-only commit performs the final end-to-end trigger proof required to close AUD-02.

The production-hardening protections remain in force, including required-source health, synchronized artifacts, replay immutability, deal-type-specific statuses, technical-noise suppression, complete Build ID hashing and shared current-deal selection.

## Current open questions

- The database count changed from 86 to 87 during the production-hardening cycle. The project is synchronized at 87 records, but the exact semantic reason for the increase has not been separately documented in a forensic data diff.
- `config.json` contains an account-specific contact value in the disabled SEC user-agent setting. It is already public and is not an active credential, but a future privacy review should decide whether to replace it with a project-level contact identifier.

No other open issue is asserted here without current repository evidence.

## Next recommended work

Choose one coherent priority from [`PRODUCT_ROADMAP.md`](PRODUCT_ROADMAP.md), preferably official-source coverage or DCM extraction completeness. Update this file after a significant milestone or published release; do not use it as a commit-by-commit changelog.
