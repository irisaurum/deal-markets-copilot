# CIS official-source event taxonomy

Status: preliminary research mapping for CIS-SOURCES-01B planning. Nothing here is implemented.

## Global rules

### Event qualification

An event is deal-relevant only when it describes an economic transfer, a securities capital-raising lifecycle, or an official approval/offer connected to one. A familiar word such as `acquisition`, `issue`, `placement` or `transaction` is not sufficient without parties/instrument and stage context.

The source type answers **who published**; the event category answers **what happened**; quality status answers **how reliable and complete the evidence is**; deal status answers **where the transaction is in its lifecycle**. These dimensions must not be collapsed.

### M&A taxonomy

Potentially relevant:

- acquisition or disposal of shares/assets;
- acquisition of control or a major-participant status linked to an economic transfer;
- merger or legal combination with economic continuity;
- voluntary, mandatory or squeeze-out offer;
- privatization sale or completed sale of a state stake;
- competition/financial-regulator acquisition approval;
- signed or completed sale with buyer, seller/target and stake/value where disclosed.

Default exclusions:

- ordinary related-party or supplier transactions;
- board/management appointments;
- affiliate-list changes without an economic transfer;
- internal reorganization, inheritance or beneficial-owner restatement without consideration;
- pledge/security creation;
- permission to transact when no acquisition target is named;
- portfolio trading by individuals or funds;
- general meeting notices, analyst targets and market commentary.

### ECM taxonomy

Potentially relevant:

- IPO, SPO, rights issue or accelerated bookbuild;
- additional share issue or private placement that raises new capital;
- prospectus/offer registration connected to new shares;
- book opening, pricing, placement result and final issue report;
- new-capital listing when issue identity and economic purpose are clear.

Default exclusions:

- dividends, buybacks and ordinary treasury-share actions;
- stock splits, nominal-value changes and ticker changes;
- routine admission maintenance;
- registration of a closed issue whose economic purpose/subscriber is not disclosed — retain as technical/review until verified;
- aggregate IPO-market statistics;
- shareholder-meeting resolutions with no new issue.

### DCM taxonomy

Potentially relevant:

- bond/note/sukuk programme announcement;
- new tranche or issue with security identity;
- book opening, guidance and revised guidance;
- pricing/book closure;
- placement, issuance, settlement and final placement result;
- exchange admission when tied to a new issue and terms are available;
- prospectus/final terms/issue-result filing for corporate debt.

Default exclusions:

- coupon or principal payment;
- redemption/maturity;
- issuer or investor buyback unless a separately approved analytical stream exists;
- REPO/collateral/Lombard-list notice;
- rating-only announcement;
- trading-hours/settlement instructions;
- routine listing maintenance, amendments or depository-balance changes;
- government/central-bank/municipal paper in the corporate-deal stream;
- an instrument screen or market aggregate with no issuer-specific new issue.

## Stage mapping

Use the strongest stage explicitly supported by evidence. Later stages are monotonic and may not be downgraded by a preliminary notice.

| Source wording / event | Project status | Guardrail |
|---|---|---|
| programme registered; prospectus approved | `Announced` | Programme is not a placed issue. |
| issue decision; issue registered; final terms published | `Announced` | Never infer pricing or issuance. |
| offer opens; subscription starts; book opens | `Announced` | Retain offer window separately. |
| guidance or revised guidance | `Announced` | Guidance is not price. |
| book closed; final yield/coupon/price fixed | `Priced` | Book closure equals `Priced`, not `Issued`. |
| placement completed; issue result approved; securities issued | `Issued` | Require explicit placement/issuance/result evidence. |
| listed/admitted after a disclosed completed placement | `Issued` | Listing alone may remain `Announced`. |
| acquisition permission/competition clearance | `Announced` or `Confirmed` | Never `Closed` without completion evidence. |
| signed acquisition agreement | `Announced` or `Confirmed` | Preserve conditions/approvals. |
| acquisition completed/title transferred | `Closed` | M&A only. |
| denial | `Denied` | Clear unsupported value/EV as required by existing rules. |

Registration sub-stages should be retained in provenance even when the public status remains `Announced`:

```text
programme_registered
prospectus_approved
issue_registered
offer_open
bookbuilding
priced
placement_completed
issue_result_registered
listed
settled
```

## Country-specific mappings

### Russia

Relevant categories:

- MOEX: explicit corporate book opening, final pricing, placement result, issuer-specific new issue/listing with amount and security identifier.
- Interfax e-disclosure: acquisition/disposal of voting shares; mandatory offer; major transaction only when it is an economic acquisition; issue decision; prospectus; placement terms; issue result.
- Bank of Russia: registration of programme/issue/prospectus and issue-result decisions as lifecycle evidence.
- FAS: merger/economic-concentration approval with named parties.
- Rosimushchestvo: completed state-stake sale with buyer, stake and result.

Noise/exclusions:

- MOEX registrations/amendments without economic terms; REPO; trading conditions; buybacks; coupon/redemption; government bonds; instrument screens.
- affiliate lists, annual reports, shareholder meetings and routine e-disclosure attachments.
- CBR Lombard-list and monetary-market notices.
- Fedresurs insolvency, creditor, licence and routine legal notices.

### Kazakhstan

Relevant categories:

- KASE `Securities`/`Instruments`: corporate book opening, guidance, pricing, placement result, new issue/listing with issuer + ISIN/registration number + amount.
- KASE corporate event: explicit acquisition/disposal, tender offer or completed transaction.
- ARDFM: `permission to acquire a subsidiary`, `consent to acquire major participant status`, bank/insurer acquisition decision.
- AIX RAS: `Offer Document`, final terms, inside information describing issuance or M&A, placement result.
- Samruk-Kazyna/state register: IPO/SPO, completed privatization/state-stake sale.

Noise/exclusions:

- KASE sovereign/municipal paper, coupon/redemption, buybacks, ratings, trading openings, index/market summaries and listing amendments.
- ARDFM licence, branch opening, new-bank creation and personnel decisions unless an actual acquisition is named.
- major-participant consent that reflects inheritance/internal ownership restatement remains review, not an approved economic M&A deal.

### Uzbekistan

Relevant categories:

- Openinfo/UZSE fact 25: corporate bond or share issue with registration number, amount and method.
- Openinfo significant share acquisition/alienation categories only when transaction date, stake and parties are explicit.
- NAPP/CBU: issue registration or bank ownership approval as corroboration.
- Davaktiv/e-auksion: sale result for a company shareholding, not merely a lot announcement.

Noise/exclusions:

- fact 6 shareholder/board decisions unless a specific new issuance is resolved and later registered;
- related-party transactions, dividends, management, annual reports and state directives;
- closed share subscriptions with no economic purpose/subscriber remain technical/review;
- real estate, equipment and commodity auction lots.

### Kyrgyzstan

Relevant categories:

- FSA weekly state registration of corporate share/bond issues and recognized issue results.
- KSE issue result, new listing and ownership/control change — link/metadata only pending written permission.
- state-property completed company-stake sale.

Noise/exclusions:

- dividends/accrued security income, governance changes, quarterly/annual reports and trade statistics;
- generic listing/rule announcements;
- copying KSE full content without written permission.

### Belarus

Relevant categories if access/permission is later resolved:

- BCSE corporate bond admission/placement result with issue identity;
- Ministry of Finance issue/prospectus registration;
- completed privatization/state-share sale;
- issuer-confirmed M&A or issuance.

Noise/exclusions:

- sovereign paper, routine trading/depository events, coupon/redemption and sanctions-driven access artefacts;
- full-content ingestion while reuse terms remain unresolved.

### Armenia

Relevant categories:

- AMX corporate bond `will be listed` pages when they disclose issuance/placement dates, ISIN, quantity and denomination;
- AMX corporate allocation/placement result;
- CBA governor decision registering a prospectus/programme or supplement;
- Competition Commission concentration decision; completed state-stake sale.

Noise/exclusions:

- government bond auctions; issuer branch openings; dividends; meetings; periodic reports; REPO admission;
- AMX listing whose underlying placement date is old or unrelated to new capital should be archived but not presented as a current new issue.

### Azerbaijan

Relevant ESID categories:

- `Prospectus or Information Memorandum`;
- `Final terms`;
- `Report on results of the issuance`;
- `Information on acquisition and alienation of significant share`;
- `Decision to conclude a transaction of special significance` only with deal parties/economic transfer;
- `Inside information` only after transaction keyword and party validation.

Noise/exclusions:

- annual/semiannual reports; charter documents; shareholder meetings; insider transactions; bond recall; collateral replacement; rights changes; guarantees; withdrawal from circulation;
- a final-terms PDF is `Announced`, not `Issued`;
- two same-day documents from one issuer do not merge without state registration number/ISIN continuity.

### Moldova

Relevant categories:

- BVM corporate bond admission with ISIN, issue value and dates;
- BVM mandatory withdrawal/squeeze-out request as M&A review;
- CNPF authorized prospectus, issue registration and issue-result decision;
- Competition Council merger authorization; Public Property completed stake sale.

Noise/exclusions:

- government bonds, temporary/provisional technical admissions, trade statistics and routine listing maintenance;
- programme target amount must not be copied into each issue;
- each MAIB ISIN is a separate issue identity even within one programme.

### Tajikistan

Relevant categories if a stable index emerges:

- CASE corporate security listing/placement result;
- corporate prospectus/issue registration;
- Antimonopoly acquisition decision; completed state-stake sale.

Noise/exclusions:

- National Bank securities issuance plans, government paper, market summaries and old general reports;
- no connector recommendation without current deal-level samples.

### Turkmenistan — availability only

No category is approved for implementation. Commodity-exchange trades, export contracts and raw-material quotations are not M&A/ECM/DCM. Central-bank or securities-regulator pages remain blocked until stable corporate event evidence is verified.

### Georgia — regional adjacent

Relevant categories:

- NBG new public-security approval with issuer, security type, ISIN, approval date and approved documents;
- GSE corporate listing/placement corroboration;
- GSE mandatory redemption as M&A review;
- Competition Agency merger clearance; completed state-stake sale.

Noise/exclusions:

- delisting, meeting notices, treasury auctions and routine security reference updates;
- every record must carry `coverage_scope=regional_adjacent` if that field is later implemented.

## Source-to-event mapping for recommended waves

| Source | Allowlist | Default deal type | Maximum initial stage | Primary exclusions |
|---|---|---|---|---|
| KASE news | corporate book/price/placement/issue listing; explicit issuer M&A | DCM; occasional ECM/M&A | `Issued` only with placement/result wording | sovereign; REPO; coupon; redemption; buyback; ratings; maintenance |
| AMX news | corporate bond issue/listing with placement dates; allocation result | DCM | `Issued` when placement completion/period is explicit; else `Announced` | government auctions; issuer housekeeping; REPO |
| BVM news | corporate bond admission; mandatory withdrawal | DCM; M&A review | `Issued` for explicit issue/admission; M&A max `Announced` | government bonds; provisional registration; statistics |
| Openinfo fact 25 | registered corporate bond/share issue | DCM/ECM | `Announced` | internal/technical recapitalization until purpose known |
| ARDFM | acquisition/subsidiary/major participant permission | M&A | `Confirmed` at most | licences; branch/new-bank creation; ownership restatement |
| CBA ESID | prospectus; final terms; issue result; significant stake/transaction | DCM/ECM/M&A | category-dependent | reports; meetings; insider; recall; collateral; guarantees |
| NBG public issuers | new public security approval | DCM/ECM | `Announced` | legacy table changes; missing documents |

## Preliminary dedup keys

### Source-event key

Prefer the source's immutable identity:

```text
source_name + source_event_id
```

Candidate IDs:

- KASE/BVM/AMX/gov.kz: numeric detail ID;
- Openinfo: `f-{fact_type}-{id}`;
- ESID: document category + state registration number + issuer + publication date + immutable PDF hash/URL;
- regulator decision: decision number + decision date + operator;
- auction: lot/result ID, never title alone.

### Economic identity keys

DCM/ECM priority:

1. ISIN or state registration number;
2. issuer + exact programme + tranche/series;
3. issuer + security type + currency + issue date + amount, only when identifiers are absent;
4. source lineage and explicit cross-reference between preliminary/final documents.

M&A priority:

1. official decision/offer ID tied to named acquirer and target;
2. normalized acquirer + target + stake + announcement date;
3. target + seller + buyer + canonical source lineage;
4. title similarity only as a candidate, never sufficient to merge.

### Keys that are not sufficient

- issuer name alone;
- same programme alone;
- same publisher/date;
- same amount/currency;
- similar headline;
- same family beneficial owner;
- same target with a different buyer or security identity.

## Preliminary lifecycle rules

1. Lifecycle progression is monotonic: `Announced` → `Priced` → `Issued` for ECM/DCM; `Announced/Confirmed` → `Closed` for M&A.
2. A registration/prospectus event may enrich an issued record but may not downgrade it.
3. A listing notice may establish `Issued` only when the page states placement/issuance completion or gives completed placement dates; otherwise keep `Announced` and a `listed` sub-stage.
4. Programme and tranche are separate entities. Programme amount is never the transaction amount of a tranche.
5. Multiple ISINs remain multiple security identities. They may share one deal-level financing lifecycle only when the source explicitly presents them as coordinated tranches.
6. Revised guidance updates the same book only with shared issue identity/source lineage.
7. A regulator permission and later closing may merge when acquirer/target and official lineage match; permission alone never implies closing.
8. Significant-share or major-participant notices stay review until an economic transfer is explicit; inheritance/internal restructuring is not M&A.
9. Mandatory withdrawal/squeeze-out is a new M&A lifecycle only when the offer/request and target security are explicit.
10. Repeat fetch and replay must not create new economic events. Canonicalized source URLs and document hashes should be byte-stable.
11. Technical filings can attach to a deal as lifecycle evidence but do not create banker tasks.
12. Government/sovereign paper must not enter the corporate DCM stream without an explicitly separate future product decision.

## Approval expectations

An official source can support `approved`, but officialness alone is insufficient.

- DCM/ECM approval still needs issuer, amount, currency, instrument/security identity, stage and canonical evidence.
- M&A approval still needs target and acquirer (plus seller/stake/value when applicable) and explicit transaction context.
- Registration-only records with missing placement/completion evidence can be approved as an `Announced` transaction only when the registered issue itself is the relevant economic event and required fields are complete.
- A source row or PDF that cannot be reopened by canonical URL should remain review until stable evidence retention is solved.
- Tier 3 media may discover/corroborate but never independently approve.
