# Data rules

Этот документ описывает business semantics, которые нельзя менять как косметику. Полная dataclass/schema живёт в коде.

## Deal types

- `M&A` — acquisition, disposal, merger, stake transaction.
- `ECM` — IPO, SPO and other equity issuance.
- `DCM` — bonds, notes and debt financing.
- `other` — контекст, который не должен притворяться сделкой. В current `deals_only` mode публичный flow ограничен M&A/ECM/DCM.

## Record kinds

- `deal` — transaction/issuance suitable for the deal stream.
- `watchlist` — material M&A claim requiring confirmation.
- `denial` — disputed or denied claim.
- `technical_filing` — exchange/regulatory plumbing stored for traceability, not treated as a banker transaction.

Streams must be mutually intelligible: a routine DCM placement is not a rumor; a technical filing is not a current key deal.

## Quality statuses

- `approved` — no blocking quality flags, required deal-type fields are present, and evidence is either a confirmed official/issuer source or independently corroborated.
- `review` — potentially useful, but requires human verification.
- `rejected` — blocked from key-deal presentation.

One confirmed secondary publication is not sufficient for `approved`. For DCM and ECM transaction records, missing amount or currency is a blocking completeness flag; technical filings are not judged by transaction-completeness fields.

Quality status and deal status answer different questions: evidence quality versus transaction stage.

## Deal statuses

- `Rumor` — a possible transaction without confirmation.
- `Reported` — reported claim based on non-confirmed evidence.
- `In talks` — negotiations are explicitly reported.
- `Confirmed` — confirmed evidence without a more specific stage.
- `Announced` — transaction or issuance announced/planned.
- `Priced` — book closed / offering priced.
- `Issued` — securities actually placed or issuance completed.
- `Closed` — completed M&A transaction only.
- `Denied` — claim denied or disputed.

## M&A rules

- Separate `target_or_issuer`, `acquirer_or_investor` and `seller`; do not infer buyer from seller language.
- A disclosed stake belongs only to M&A.
- Transaction value and enterprise value are different concepts.
- A denial clears transaction value and enterprise value.
- Missing buyer/target can block approval even when the headline sounds transactional.

## DCM rules

- Issuer belongs in `target_or_issuer`; buyer is `Not applicable` unless the schema changes deliberately.
- `Priced != Issued`; `Issued != Closed`; DCM never uses `Closed`.
- Keep volume/currency, instrument, security code, ISIN, coupon, yield, maturity, tenor and issue price separate.
- Distinct security identifiers or bond series must not be collapsed merely because the issuer is the same.
- One coordinated placement may contain several distinct issue identities while remaining one deal-level lifecycle; preserve the complete issue set on the canonical deal.
- Shared strong identifiers or exact stored source lineage can connect preliminary and final DCM stages despite material changes in date, amount or headline. Issuer, date, amount and title similarity alone cannot establish that continuity.
- DCM lifecycle consolidation is monotonic: a preliminary source cannot downgrade `Issued`, replace the final amount or displace stronger official evidence.
- Registration, trading codes, REPO, coupon payment, redemption and technical buyback notices may be stored as technical records but do not create banker tasks.

## ECM rules

- Issuer belongs in `target_or_issuer`.
- Keep offering size, price per share, discount, bookrunners and free float separate.
- Market roundups, aggregate IPO statistics, dividend stories and share buybacks are not automatically ECM transactions.
- `Priced` and `Issued` have the same stage distinction as DCM; `Closed` remains reserved for M&A.

## Unknown versus not applicable

- Use `Not disclosed` when a relevant value is unknown.
- Use `Not applicable` when the field does not apply to the deal type.
- Use numeric `0` only when the source explicitly states zero and zero is meaningful.
- Blank technical storage values must not be rendered or modeled as disclosed zeroes.
- If an amount and currency are extractable from source text, normal parsing/canonicalization must populate them instead of preserving `Not disclosed`.

## Live versus historical

| Layer | Purpose | Old deals allowed? |
|---|---|---|
| Live event feed | 24h/72h monitoring | No |
| Current/latest transactions | Recent material live deal flow, currently capped at 10 | No curated history; no padding |
| Persistent archive | Deduplicated public transaction history | Yes |
| Historical curated precedents | Analyst-reviewed valuation benchmarks | Yes, including 2016 records |

Curated IDs use `CURATED-` and are valid in the database, Excel `Deals`, `Financials`, `Multiples` and precedent analytics. They must not appear in live/current lists. Current selection also applies a recent cutoff and quality/materiality rules; returning fewer than 10 is correct.

## Quality gate principles

- Validate transaction context, identity, parties, amount/currency, source type, evidence and materiality together.
- Target prices and other non-transaction numbers must not become transaction values.
- One weak or aggregator source is not sufficient for `approved`.
- `approved` records must be `record_kind=deal` and have no blocking quality flags.
- Denials, technical records and rejected rows do not enter key deals.
- Human review remains required before relying on a transaction in client work.

## Source and evidence principles

- Prefer official exchange, regulator and issuer sources; reputable publishers are secondary evidence; Google News is discovery.
- Preserve direct publisher URLs when resolved and update both primary fields and the source array.
- A source representation is an access/discovery URL; a publication is one material; a publisher is the publishing organization; independent corroboration is a distinct publication/evidence source.
- `source_count` counts canonical publications, not URL representations or publisher labels.
- Direct, Google News, redirect and tracking URL representations of the same publication remain attached to one canonical source under `representations` when more than one raw URL exists.
- Exact canonical URL identity is strong evidence. URL canonicalization lowercases scheme/host, removes fragments, normalizes repeated/trailing slashes and removes only the explicit tracking allowlist (`utm_*`, `gclid`, `fbclid`, `yclid`, `mc_cid`, `mc_eid`, Google News `oc`); other query parameters remain identity-bearing.
- For legacy rows without per-source titles, direct + Google rows merge only for an unambiguous one-to-one exact publisher/date pair. Missing metadata and one-to-many groups remain separate.
- Same publisher does not imply same publication. Different publishers and separately published/attributed articles remain independent unless stronger publication identity is available.
- Every stored source URL must be safe `http` or `https`.
- An empty required source or malformed feed is a health problem, not a quiet successful run.
- Exchange-news source identity is `source_id + immutable source_event_id`; economic identity separately prefers ISIN/state registration number, then exact programme plus series/tranche.
- A publication containing several ISINs preserves separate security events under shared source lineage. Programme target value is not an issue amount.
- CNPF source identity is `cnpf_moldova + immutable Atom entry ID`; a stable Atom ID is never replaced by title/date/issuer fallback identity.
- A CNPF registration, prospectus or programme approval remains `Announced`. `Issued` requires explicit issue/placement-result evidence plus issuer, amount, currency and ISIN/registration identity; takeover approval is never `Closed`.
- CNPF retains only factual fields, short original title, official identifiers, canonical/document links and exact source attribution. A page-specific reproduction restriction stops the item.
- Deterministic `quantity × denomination` is permitted only with unambiguous units and currency; retain both operands and an amount-derivation flag.
- Public readability and robots behavior are not reuse licences. Sources with unresolved terms stay implemented-disabled or link-only/blocked and do not count as connected coverage.

## Deduplication principles

- Exact event IDs remove exact duplicates.
- Near-duplicate headlines may merge only when they represent the same transaction.
- Prefer the stronger source when two events duplicate one another.
- Different bond/issue identifiers override superficial issuer similarity.
- Database merging preserves earliest `first_seen_at`, latest `last_seen_at`, strongest source and complementary disclosed fields.
- `first_seen_at` is assigned only when an economic event is first created. Re-observing byte-equivalent official evidence does not advance `last_seen_at`; it advances only when normalized event meaning or canonical evidence changes.
- Poll attempts, success times, request counters, validators, fingerprints and backoff are operational state. They remain outside the economic dataset and replay.

## Financial enrichment

- Financial inputs are keyed by deal ID and must preserve period end, public availability date, currency, metric basis and source.
- Use a positive disclosed EV and positive financial denominator in the same currency.
- Financial information published after the deal announcement cannot enter the announcement-date precedent median.
- Do not substitute equity value for EV without an explicit supported transformation.

## Multiple eligibility and medians

An observation is model-eligible only when it is an approved, non-denied M&A deal with disclosed EV, aligned-currency revenue and/or EBITDA, and financials available on or before announcement.

Show the observation count for each multiple. Publish a median only at `n >= 3`; otherwise show `N/M`. `N/M` means insufficient or non-comparable disclosure, not zero.

## Time windows

- Normal live discovery: 24 hours (`1d`).
- Saturday, Sunday and Monday catch-up: 72 hours (`3d`).
- Persistent discovery archive: configured separately, currently 90 days.
- Current/latest deal selection: recent cutoff, currently 365 days, evaluated using `Europe/Moscow` date.
- Source freshness health uses Moscow time and a stricter business-hours threshold than off-hours/weekends.
