# Current state

Last verified: **2026-07-04 08:16 MSK (Europe/Moscow)**.

| Field | Verified value |
|---|---|
| Branch | `main` |
| Repository HEAD | `0da24558e432c4c2199251e752df67a4f0ed63ea` |
| `origin/main` | `0da24558e432c4c2199251e752df67a4f0ed63ea` |
| Last production code commit | `c21c00c79d70c2ba2943bd919f6c77261f26a138` (`fix: harden production deal pipeline`) |
| Last bot/data commit | `0da24558e432c4c2199251e752df67a4f0ed63ea` (`chore: refresh deal desk`) |
| Build ID | `94a6f42ca0da` |
| Dataset SHA-256 | `94a6f42ca0dab968a12167b151b362a4f8b5567c12312e48726c51e32f02505e` |
| Records | 87 |
| Last verified test count | 58 tests passed in the production-hardening verification cycle; not rerun during the documentation-only review |
| Public deployment | Actions run `#41` and Pages deployment succeeded; public manifest matches repository manifest |
| Source health | `ok`; all required source runs returned usable records |
| Discovery | `ok` |
| Freshness | `ok` |
| System status | `ok` |
| Excel sync | `true`; manifest, dataset and snapshot agree |

Current quality distribution: 18 `approved`, 47 `review`, 22 `rejected`. Current dataset contains 27 M&A, 8 ECM and 52 DCM records. These are build facts, not coverage targets.

## Last completed milestone

Production-hardening audit completed and published. It added or strengthened:

- explicit failure state for an empty required source;
- deeper XLSX synchronization verification;
- separation of distinct DCM issues during deduplication;
- DCM-specific `Priced` / `Issued` semantics;
- suppression of technical and non-transaction analyst tasks;
- byte-stable replay behavior;
- `N/M` for public medians with fewer than three observations;
- consistent direct-URL normalization across source fields;
- ISIN validation;
- Moscow-time recent cutoff;
- one current-deal selection rule for dashboard and Excel.

## Current open questions

- The database count changed from 86 to 87 during the production-hardening cycle. The project is synchronized at 87 records, but the exact semantic reason for the increase has not been separately documented in a forensic data diff.
- `config.json` contains an account-specific contact value in the disabled SEC user-agent setting. It is already public and is not an active credential, but a future privacy review should decide whether to replace it with a project-level contact identifier.

No other open issue is asserted here without current repository evidence.

## Next recommended work

Choose one coherent priority from [`PRODUCT_ROADMAP.md`](PRODUCT_ROADMAP.md), preferably official-source coverage or DCM extraction completeness. Update this file after a significant milestone or published release; do not use it as a commit-by-commit changelog.
