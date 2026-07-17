# CIS-SOURCES-01A — official deal-data source landscape

Research date: **17 July 2026 (Europe/Moscow)**

Repository baseline: `e0f058527b7cc164ffd905511547484f2bca0621`

Production data inspected: Build ID `a88b0b4ba423`, dataset SHA-256 `a88b0b4ba42361970ab1b1f14aca1ec490f8b3d1fc4debc5c10b0861424e5e83`, 119 records.

This is a research-only document. It does not activate a source, change the dataset, or claim production coverage.

## Executive summary

**Verified fact.** The strongest currently public, deal-level official surfaces outside the connected Russia/MOEX and narrow Uzbekistan/UZSE baseline are:

1. [KASE Market and Company News](https://kase.kz/en/information/news/all) — the best first DCM source: stable numeric detail IDs, deep date-filtered archive, multilingual HTML, and frequent issue-level terms.
2. [AMX news](https://amx.am/en/news) — a low-complexity corporate-bond source with ISIN, quantity, denomination, coupon, placement dates and listing date on one page.
3. [Moldova Stock Exchange news](https://www.bvm.md/en/news/) — a low-noise DCM source with stable numeric details, exact ISIN/amount/currency and prospectus links.
4. [Openinfo material fact 25](https://openinfo.uz/ru/facts/25) — a structured ECM/DCM registration source with stable fact IDs, but its marginal geographic value is lower because narrow UZSE coverage is already connected.
5. [Kazakhstan ARDFM decisions](https://www.gov.kz/memleket/entities/ardfm/press/news?lang=en) — the cleanest M&A regulatory candidate, but observed volume is low and permission does not prove closing.
6. [Azerbaijan CBA ESID](https://www.cbar.az/meas?language=en) — authoritative and deep, with 1,300+ indexed issuer documents, but it needs PDF-link extraction and an exact category whitelist before implementation.

**Recommendation.** CIS-SOURCES-01B should implement only the first three exchange feeds: KASE, AMX and BVM. They share a narrow corporate-securities use case, have real live samples, and can materially add three official-country surfaces without opening a broad regulatory-disclosure firehose.

**Inference.** Kazakhstan is the market most likely to add new `approved` records after Wave 1. KASE combines the highest observed useful-event frequency with explicit issue identifiers and terms. Armenia and Moldova should add fewer records, but their event pages are cleaner and should have a higher approval ratio than a generic news/disclosure feed.

**Single greatest uncertainty.** Public accessibility was verified, but unattended production use and permitted repeated extraction were not confirmed through explicit machine-use licences for most exchanges. Robots status is not a licence. Wave 1 therefore needs a short permission/terms checkpoint and conservative factual extraction with canonical links.

## Research answer in one page

| Question | Answer |
|---|---|
| First 2–4 sources | KASE Market and Company News; AMX listing/allocation news; BVM news. Openinfo fact 25 is next. |
| Most likely new approved records | Kazakhstan, primarily KASE corporate DCM. |
| Best M&A candidate | Kazakhstan ARDFM acquisition/major-participant permission decisions; FAS and national competition authorities remain research candidates. |
| Best ECM candidate | Openinfo fact 25 for registered share issues; CBA Armenia prospectus decisions and NBG Georgia public issuers are corroborating alternatives. |
| Best DCM candidate | KASE, followed by AMX and BVM. |
| Lowest observed noise | BVM corporate-bond admissions; ARDFM acquisition-permission posts are lower volume but also low noise. |
| Highest legal/reuse risk | Kyrgyz Stock Exchange: its pages state that copying is allowed only with written permission. Belarus sources also carry unresolved sanctions/access and reuse risk. |
| Metadata/link-only | KSE; Interfax e-disclosure pending permission; NSD licensed/public boundary; Belarus BCSE/CSD/state-property sources pending access and terms. |
| Roadmap markets | Kyrgyzstan, Belarus, Tajikistan; Georgia as regional-adjacent only. |
| Availability-only / blocked | Turkmenistan: no stable public corporate deal-level infrastructure was verified. |
| Honest claim after Wave 1 | Connected official exchange monitoring for Russia, Uzbekistan, Kazakhstan, Armenia and Moldova; not comprehensive CIS coverage. Georgia remains adjacent and unconnected. |

## Methodology

### Scope and evidence labels

The research separately inspected Russia, Kazakhstan, Uzbekistan, Kyrgyzstan, Belarus, Armenia, Azerbaijan, Moldova and Tajikistan as core product markets; Turkmenistan for availability only; and Georgia as a **regional-adjacent** market. Georgia is not described as a current CIS member.

Each source was evaluated across the fields in [`CIS_SOURCE_MATRIX.csv`](CIS_SOURCE_MATRIX.csv). High-priority samples are in [`CIS_SOURCE_SAMPLES.csv`](CIS_SOURCE_SAMPLES.csv), and event mappings are in [`CIS_EVENT_TAXONOMY.md`](CIS_EVENT_TAXONOMY.md).

The following labels are used deliberately:

- **Verified fact:** supported by a live official page or the checked-in production dataset.
- **Observed live behavior:** page/index/detail/pagination behavior seen during this research; not a guarantee of future stability.
- **Inference:** a conclusion from observed structure or samples.
- **Recommendation:** proposed product treatment, not an implemented rule.
- **Unresolved:** not proven from public evidence in this task.

### Live checks performed

For P0/P1 candidates, the research opened the current index, inspected a dated or paginated archive, opened or located detail publications, and collected three samples where possible. The 90-day window is 18 April–17 July 2026. When three relevant samples were not available inside it, the sample window was extended to 365 days and marked explicitly.

**Observed live behavior:**

- KASE exposes a date-filtered index and stable `/information/news/show/{id}` details. The live index contains both useful issuance events and large volumes of routine/technical notices.
- AMX exposes a year/month-filtered news index and stable numeric detail URLs. Only one of the three selected corporate DCM samples fell in 90 days, so the window was extended to 365 days.
- BVM exposes simple paginated news and stable `/en/news/{id}/` details. Three corporate bond issues were found, one just outside 90 days.
- Openinfo exposes stable `f-25-{id}` identifiers and `/facts/25/{id}` details in Uzbek, Russian and English.
- ARDFM uses stable numeric `gov.kz` details. Three control/acquisition-relevant samples required the 365-day window.
- Azerbaijan ESID exposes filters and `page`/`per-page` pagination and showed more than 1,300 records; document-level PDF links are opened from rows rather than exposed as stable detail pages in the static index.
- AMX [`robots.txt`](https://amx.am/robots.txt) permits all paths. The [`gov.kz` robots file](https://www.gov.kz/robots.txt) disallows search, uploads and some service paths but not the ordinary ARDFM news details reviewed here. Robots files for several other priority domains could not be independently retrieved in this environment and are marked accordingly rather than guessed.

### What was not done

No CAPTCHA, anti-bot or login was bypassed. No credentials were used. No undocumented endpoint was labelled an API. No source was load-tested. No production workflow or connector was run. Search snippets and secondary articles were used only to locate official pages, never as approval evidence.

## Current dataset gap audit

### Verified production distribution

The audit read `data/precedent_transactions.json` and `output/build_manifest.json` without modifying them.

| Dimension | Count / finding |
|---|---:|
| Total records | 119 |
| Russia geography | 61 |
| Geography `Not disclosed` | 48 |
| United States geography | 10 |
| M&A | 35 |
| ECM | 10 |
| DCM | 74 |
| Approved | 17 |
| Review | 76 |
| Rejected | 26 |
| Deal | 28 |
| Watchlist | 54 |
| Technical filing | 36 |
| Denial | 1 |
| 0–90 days | 94 |
| 91–365 days | 9 |
| 1–3 years | 7 |
| More than 3 years | 9 |

The 10 United States rows are `CURATED-` historical M&A precedents. Excluding them, the current/non-curated archive contains 109 records: 94 aged 0–90 days, 9 aged 91–365 days and 6 aged 1–3 years.

### Country and quality cross-check

| Geography | Approved | Review | Rejected | Total |
|---|---:|---:|---:|---:|
| Russia | 7 | 49 | 5 | 61 |
| Not disclosed | 0 | 27 | 21 | 48 |
| United States historical precedents | 10 | 0 | 0 | 10 |

**Verified fact.** There are no current/non-curated records explicitly labelled with a non-CIS geography: all 109 are `Russia` or `Not disclosed`. This is not proof that they are in scope.

**Inference from titles.** At least 13 current rows are likely global/non-CIS or not transaction events despite lacking a usable geography boundary. They include stories about Amazon, SpaceX, the US equity issuance market, Trump trades in Nvidia/Boeing, Jim Cramer’s Arm position, and generic US/global bond-market commentary. One Amazon item is incorrectly labelled `Russia`, demonstrating that geography cannot be inferred safely from a Russian-language publisher.

Likely out-of-scope current IDs identified by title review:

- `DL-ad103303a957915b` — Trump/social-post stock-buying story;
- `DL-71a9d2943257610f`, `DL-ae1e65593fa575d8`, `DL-3c400018ff8f7b5b` — Nebius/global AI stories requiring an explicit issuer/market scope decision;
- `DL-7b25965c17ea42d6`, `DL-622d99b994e527ab` — Amazon bond issuance;
- `DL-3c0392914bb7d450` — Jim Cramer/Arm portfolio sale;
- `DL-32fe42111a2c1256`, `DL-ec890718ba131f71` — duplicated US market-supply commentary;
- `DL-884a90d63a74113a` — SpaceX bond story;
- `DL-b10ff92f48cadefa` — aggregate US IPO/share-sale statistics;
- `DL-32f044efd41bc454` — Trump personal trades;
- `DL-d278dd8790af9685` — USD/REPO market-access notice, not a new issue.

### Source-country audit

The schema has no `source_country` field. A conservative URL-domain/publisher inference produced:

| Inferred publisher jurisdiction | Records |
|---|---:|
| Russia | 104 |
| Russia / unclear (Google News representation) | 3 |
| Kazakhstan | 1 |
| United States | 11 |

This is a publisher-location heuristic, not a transaction-geography fact. Ten of the US-source rows are curated precedents; one is a current low-quality secondary item.

### Weak evidence and noise

**Verified fact.** Fifty-five records have `unverified_source`; the same 55 have `evidence_label=unverified`. Thirty-seven records are missing an issuer, 18 are missing both M&A parties, 15 lack currency and 14 lack transaction value. These deficiencies explain much of the 76-record review bucket.

The largest review-noise sources are:

| Source | Records | Review | Technical filings | Unverified-source rows | Finding |
|---|---:|---:|---:|---:|---|
| MOEX disclosure | 40 | 39 | 35 | 0 | Strong official source but broad intake produces routine registrations, trading conditions, buybacks and other plumbing. |
| Finam | 7 | 3 | 0 | 7 | Secondary watchlist discovery; four rejected. |
| BCS Express | 6 | 3 | 0 | 6 | Secondary watchlist/denial discovery; three rejected. |
| Finance Mail | 5 | 4 | 0 | 5 | Several global-market false positives. |
| Vedomosti | 4 | 2 | 0 | 4 | Useful discovery but not sufficient for approval alone. |
| InvestFuture | 3 | 3 | 0 | 3 | All unverified watchlist rows. |

**Recommendation.** New official-source connectors should not imitate the existing broad MOEX intake. They should start from a small allowlist of economic event categories and should store technical filings separately without banker tasks.

### Coverage-scope field recommendation

Add, in a later implementation task, a record-level field:

```text
coverage_scope:
  core_cis
  regional_adjacent
  global_precedent
  out_of_scope
```

Recommended semantics:

- `core_cis`: current/live deal whose economic issuer/target market is one of the nine core markets.
- `regional_adjacent`: current/live deal in a deliberately included adjacent market, initially Georgia.
- `global_precedent`: curated historical benchmark; never enters current flow.
- `out_of_scope`: discovery item retained only for audit or rejected before deal presentation.

**Recommendation.** `coverage_scope` must be derived from issuer/target economic geography and security market, not publisher language, publisher domain or a broad keyword. Unknown should remain `Not disclosed`; it must not silently default to `core_cis`.

## Country-by-country findings

### Russia

**Verified fact.** Russia already has the deepest connected surface through MOEX. The current archive shows why additional Russian sources must solve evidence quality rather than increase raw event count: 35 of 40 MOEX rows are technical filings.

Official candidates include [Interfax e-disclosure](https://e-disclosure.ru/portal/), the [Bank of Russia securities register](https://www.cbr.ru/registries/rcb/ecb/), [Bank of Russia corporate-relations decisions](https://www.cbr.ru/issuers_corporate/), [FAS news](https://fas.gov.ru/news), NSD and federal privatization sources.

**Recommendation.** Do not add another broad Russia firehose in Wave 1. Research e-disclosure as metadata/link-only until copying terms are clear; use CBR registration and FAS decisions as targeted corroboration. Preserve the existing MOEX technical-noise controls.

### Kazakhstan

**Verified fact.** [KASE](https://kase.kz/en/information/news/all) is the strongest implementation candidate. Samples exposed explicit ISIN/registration numbers, currency, programme relationships, maturity and coupon information. Its archive also shows high noise from government bonds, ratings, coupon events, buybacks and routine listing maintenance.

[AIX offer documents](https://aix.kz/listings/continuous-disclosure-obligations/prospectus/) confirm that post-28 December 2021 offer documents are published through RAS. The current [company disclosure surface](https://aix.kz/listings/continuous-disclosure-obligations/company-disclosures-2/) did not expose sufficiently stable unattended item/detail links for a P0/P1 recommendation.

[ARDFM](https://www.gov.kz/memleket/entities/ardfm/press/news?lang=en) published explicit acquisition and major-participant consents, including [Halyk/COMRUN](https://www.gov.kz/memleket/entities/ardfm/press/news/details/1200784?lang=ru). These are excellent regulatory-stage M&A facts but do not prove signing or closing.

**Recommendation.** KASE is Wave 1; ARDFM is Wave 2 with a narrow acquisition-permission title/category filter; AIX remains research-more.

### Uzbekistan

**Verified fact.** Openinfo fact 25 has stable identifiers and unusually complete registration fields. Examples include [UZS 700bn corporate bonds](https://openinfo.uz/ru/facts/25/1745), [HUMO PAY shares](https://openinfo.uz/ru/facts/25/1726) and [Uzbekneftegaz shares](https://openinfo.uz/en/facts/25/1732).

**Observed live behavior.** Fact 25 mixes public-market finance with closed subscriptions and state/internal recapitalizations. It is authoritative for registration but does not prove bookbuilding, pricing or placement completion.

**Recommendation.** Add Openinfo fact 25 in Wave 2, after Wave 1 adds new countries. Classify `registered` or `announced`, never `Issued`, unless a later official event proves placement. State Assets Management Agency, competition and e-auction sources remain research-more because completed transaction results and company-stake filters were not sufficiently verified.

### Kyrgyzstan

**Verified fact.** The [KSE issuer pages](https://www.kse.kg/en/PublicInfo/JSC_Kyrgyzaltyn) have issuer profiles and archives. KSE pages explicitly state: copying of materials is only with written permission. The Financial Market Regulation Service also publishes securities-registration notices and participant reporting through [fsa.gov.kg](https://fsa.gov.kg/).

**Recommendation.** KSE is link-only unless written permission is obtained. FSA is research-more for registration-stage metadata. Do not implement a content-copying KSE connector in CIS-SOURCES-01B.

### Belarus

**Unresolved.** BCSE, the central depository, Ministry of Finance, National Bank and state-property institutions exist, but this task did not verify a stable, unattended, current deal-level archive with clear reuse terms. Access and sanctions constraints make a one-load observation insufficient.

**Recommendation.** Keep Belarus blocked/link-only for implementation. Use only canonical links and minimal factual metadata after a separate legal/access review; do not store copied full text.

### Armenia

**Verified fact.** [AMX news](https://amx.am/en/news) is a practical DCM surface. The [Ameriabank sample](https://amx.am/en/news/%22ameriabank%22_cjsc%27s_bonds_will_be_listed_on_armenia_stock_exchange/2574) gives issuance, placement and listing dates, quantity, denomination, ISIN, coupon and maturity. Older samples show the same layout.

The [Central Bank of Armenia](https://www.cba.am/en/chairman-decisions) publishes prospectus-registration decisions, including a recent [UITE Expo bond programme](https://www.cba.am/en/chairman-decisions/9441/preview/).

**Recommendation.** AMX is Wave 1. CBA decisions should later corroborate programme registration; they should not independently imply pricing or issuance.

### Azerbaijan

**Verified fact.** CBA regulations define ESID as the centralized official disclosure system, require free public access, and require prospectuses, final terms, issue results, significant transactions and significant-stake changes. See the [ESID rules](https://www.cbar.az/law-93/regulations-on-disclosure-of-information-by-issuers-in-the-securities-market?language=en) and [system description](https://www.cbar.az/page-182/about-esid?language=en).

**Observed live behavior.** The [ESID index](https://www.cbar.az/meas?language=en) supports issuer, information-type, date, security and state-registration-number filters and numbered pages. Current rows included bond final terms and prospectuses. The static index does not expose a normal stable detail URL; users open a PDF/document from the row.

**Recommendation.** ESID is Wave 2 after proving document href stability, defining a whitelist, and testing Azerbaijani/PDF extraction. Exclude annual reports, shareholder meetings, insider transactions, recalls and routine changes by default.

### Moldova

**Verified fact.** [BVM news](https://www.bvm.md/en/news/) is a clean corporate DCM source. The [25th MAIB issue](https://www.bvm.md/en/news/1655/) discloses ISIN, MDL 172.88m issue value, dates, coupon formula and prospectus. The [23rd issue](https://www.bvm.md/en/news/1635/) has the same structure.

The [CNPF authorized prospectus index](https://www.cnpf.md/ro/prospecte-autorizate-6512.html) provides regulatory corroboration and a multi-year offer archive.

**Recommendation.** BVM is Wave 1. CNPF is a later corroborating source. Programme and issue must remain separate: a MDL 2bn programme target is not the amount of each ISIN.

### Tajikistan

**Verified fact.** CASE and National Bank sites are live, and CASE publishes securities-market documents. The National Bank published a [2026 securities issuance plan](https://nbt.tj/files/monetary_policy/2026/eng_%D0%BD%D0%B0%D2%9B_%D0%BC%D0%BE_%D1%84%D0%B5%D0%B2_2026.pdf), but that is central-bank paper rather than corporate DCM.

**Recommendation.** Research only. No candidate met P0/P1 requirements: a stable recent corporate deal index plus usable samples was not verified.

### Turkmenistan — availability only

**Verified fact.** The [State Commodity and Raw Materials Exchange](https://www.exchange.gov.tm/quotations) is live, supports dated quotations and file download, and publishes commodity trades. Those events are not M&A, ECM or DCM.

**Recommendation.** Reject the commodity exchange for deal ingestion. Keep the securities-market lead blocked: no stable public corporate deal-level archive and sample event were verified. Make no coverage claim.

### Georgia — regional adjacent, not CIS

**Verified fact.** The [National Bank of Georgia public-issuer table](https://nbg.gov.ge/en/supervision/public-companies) contains company IDs, security type, ISIN, approval date and approved-document links. Recent 2026 bond approvals were visible. [GSE securities](https://gse.ge/en/securities/) and [GSE news](https://gse.ge/en/news) provide exchange corroboration.

**Recommendation.** Georgia is a strong Wave 3 regional-adjacent candidate, not a core CIS claim. The NBG table is cleaner for new issuance discovery than GSE news, which was recently dominated by delistings.

## Official source-family inventory and gaps

The machine-readable inventory contains one row per reviewed surface. The cross-country result is:

| Source family | Strongest verified examples | Common limitation |
|---|---|---|
| Stock exchange | KASE, AMX, BVM | Technical/listing noise; listing is not always issuance completion. |
| Securities regulator | ARDFM, CBA Armenia, CNPF Moldova, CBA Azerbaijan | Registration/permission stage differs from transaction stage. |
| Central bank | CBA Azerbaijan ESID, NBG public issuers | Many other central-bank pages are macro/sovereign rather than corporate events. |
| Central depository | NSD, KACD, CDA, NDC leads | Public event feeds and reuse terms are often unclear; high corporate-action noise. |
| Corporate disclosure portal | Openinfo, Interfax e-disclosure, ESID | Excellent evidence but high volume and copying/document-link constraints. |
| Prospectus database | CBA Armenia, CNPF, NBG | Prospectus approval does not prove pricing or issuance. |
| Competition authority | ARDFM financial permissions; national competition leads | Individual decision publication is inconsistent; party/stake data can be sparse. |
| Privatization/state assets | Samruk-Kazyna, Uzbekistan Davaktiv, national agencies | Auction lists mix company stakes with real estate and other assets. |
| Sovereign/state holdings | Samruk-Kazyna and official holding pages | Episodic, no unified event taxonomy. |
| Issuer IR | Useful in every active market | No unified index; must be corroborating and issuer-specific. |
| Development institutions | EDB/issuer pages and national institutions | Often project finance or general news, not securities events. |
| Tender-offer register | No consistently usable cross-market public register verified | Treat issuer/exchange/regulator notices as country-specific alternatives. |
| Auction/placement results | KASE and BVM strongest; state auctions mixed | Government bonds and non-company assets must be excluded. |
| Secondary media | Current Russia-heavy discovery layer | Tier 3 cannot independently approve a record. |

## Access, robots and reuse analysis

### Access findings

- **Unattended public HTML verified:** KASE, AMX, BVM, Openinfo, ARDFM and CBA ESID indexes/details used here required no login.
- **Pagination/archive verified:** KASE date filters; AMX date filters/index; BVM older numeric news; ESID page/per-page; KSE issuer archives; NBG long issuer table.
- **JavaScript/document complexity:** AIX RAS, Fedresurs, state auction portals and ESID document-opening behavior need browser/network-level engineering investigation. No hidden endpoint is approved by this research.
- **Authentication mixed or unresolved:** central depositories, auction portals and certain professional/issuer submission areas. Public reader access must be separated from issuer login.
- **Reliability caution:** a successful page load is evidence of current availability, not an SLA. Repeated requests were not load tests.

### Reuse findings

- **Highest explicit risk:** KSE says copying is allowed only with written permission. Recommendation: canonical link plus minimal metadata only.
- **High unresolved risk:** Interfax e-disclosure, NSD data products, Belarus sources and central-depository datasets. Recommendation: link-only/metadata-only pending permission.
- **Medium unresolved risk:** KASE, Openinfo and ESID allow public access, but explicit bulk machine-reuse licences were not located. Recommendation: factual field extraction, short summaries, canonical links, conservative frequency and contact operators before scale-up.
- **Lower observed risk:** ordinary government decision pages and AMX/BVM factual event pages, still subject to their terms and database rights.

No recommendation relies on `robots.txt` as permission. Robots is recorded as an operational signal only.

## Country scorecards

Scores are qualitative, 0 (unavailable/worst) to 5 (strongest). `Maintenance cost` is scored inversely: 5 means low cost, 0 means very high cost.

| Country / market | Official sources | Recent volume | M&A | ECM | DCM | Structured data | Stable archive | Access reliability | Reuse safety | Language/parser feasibility | Approved-yield | Maintenance cost | Wave |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Russia | 5 | 5 | 4 | 4 | 5 | 4 | 5 | 3 | 2 | 5 | 4 | 2 | Existing; targeted Wave 2/3 only |
| Kazakhstan | 5 | 5 | 4 | 4 | 5 | 4 | 5 | 4 | 3 | 5 | 5 | 4 | Wave 1 |
| Uzbekistan | 5 | 3 | 3 | 4 | 4 | 5 | 4 | 4 | 3 | 5 | 4 | 4 | Wave 2; narrow UZSE already connected |
| Kyrgyzstan | 3 | 2 | 2 | 2 | 2 | 2 | 3 | 4 | 1 | 5 | 2 | 3 | Research only / link-only |
| Belarus | 3 | 2 | 2 | 2 | 3 | 2 | 3 | 2 | 1 | 5 | 2 | 1 | Blocked |
| Armenia | 5 | 4 | 2 | 3 | 5 | 4 | 5 | 5 | 4 | 3 | 4 | 5 | Wave 1 |
| Azerbaijan | 5 | 4 | 2 | 3 | 5 | 4 | 5 | 5 | 4 | 2 | 4 | 3 | Wave 2 |
| Moldova | 5 | 3 | 2 | 3 | 4 | 4 | 5 | 5 | 4 | 3 | 4 | 5 | Wave 1 |
| Tajikistan | 2 | 1 | 1 | 1 | 2 | 1 | 2 | 3 | 3 | 4 | 1 | 1 | Research only |
| Turkmenistan | 1 | 0 | 0 | 0 | 0 | 1 | 1 | 3 | 2 | 4 | 0 | 2 | Blocked / availability only |
| Georgia (regional adjacent) | 5 | 5 | 2 | 4 | 5 | 4 | 5 | 5 | 4 | 2 | 5 | 4 | Wave 3, adjacent label required |

## Recommended implementation waves

No wave activates all sources in a country. The volume estimates are directional ranges from observed publication patterns, not promises.

### Wave 1 — narrow official exchange DCM

**Countries and exact sources**

- Kazakhstan — KASE Market and Company News.
- Armenia — AMX listing/allocation news.
- Moldova — BVM news.

**Exact categories**

- KASE: corporate bond book opening/guidance/pricing, placement result, issue/listing notice with issuer + identifier + amount; issuer M&A only when acquisition/disposal is explicit.
- AMX: corporate bond listing pages with issuance/placement dates and ISIN; exclude government allocation and routine issuer news.
- BVM: corporate bond admission; mandatory withdrawal only as M&A review; exclude government bonds and provisional technical registrations.

**Expected useful records per 90 days:** 18–33 total (KASE 12–20, AMX 4–8, BVM 2–5).

**Expected approved/review mix:** 60–75% approved, 25–40% review after primary-page parsing. Registration/listing without amount, currency or stage evidence remains review.

**Parser types:** server-rendered HTML list/detail parsers with linked-document capture; no inferred API.

**Technical noise risk:** medium at KASE, low at AMX/BVM. Government paper, coupon/redemption, buybacks, ratings, REPO and listing maintenance must be negative fixtures.

**Dedup/lifecycle risks:** multiple tranches under one programme; one issue across book-open, priced, admitted and issued stages; separate ISINs must not collapse; programme amount must not replace issue amount.

**Test coverage expected:** index parsing; pagination/date filters; detail parsing in all supported languages used; stage normalization; amount/currency; ISIN/ticker; negative taxonomy; lifecycle monotonicity; repeat-fetch idempotence; source-health failure on empty/malformed required pages.

**Permission/reuse:** store factual fields and canonical URL, not copied full articles; contact source operators or document a terms conclusion before production-scale polling.

**Acceptance criteria:**

1. Three fixtures per source from the samples file plus at least three negative fixtures.
2. Zero banker tasks from technical/government/coupon/buyback notices.
3. Stable source event key using official item ID and security identifiers.
4. No lifecycle duplicate across repeat fetch/replay.
5. Source health fails closed on empty index/detail or changed structure.
6. Production claim updated only after a successful release and public verification.

### Wave 2 — structured registration and regulatory M&A

**Countries and exact sources**

- Uzbekistan — Openinfo material fact 25.
- Kazakhstan — ARDFM acquisition/major-participant permission decisions.
- Azerbaijan — CBA ESID, only whitelisted document types.

**Exact categories:** Openinfo fact 25 share/bond issues; ARDFM acquisition of subsidiary and major-participant consent with explicit target; ESID prospectus, final terms, issue result, significant transaction and significant-share acquisition/alienation.

**Expected useful records per 90 days:** 14–30. Expected approved/review mix 40–60% approved and 40–60% review because registration and regulatory permission frequently precede economic completion.

**Complexity:** low for Openinfo and ARDFM; high for ESID PDF/document extraction and Azerbaijani language. Technical-noise risk is medium for Openinfo, low for ARDFM, very high for broad ESID unless whitelisted.

**Acceptance criteria:** stable ESID document href; PDF text extraction with source-file hash; stage never exceeds the disclosed event; closed subscriptions flagged for economic-purpose review; regulatory consents never become `Closed` without transaction evidence.

### Wave 3 — corroboration and regional-adjacent expansion

**Countries and exact sources**

- Georgia (regional adjacent) — NBG public companies/public securities, corroborated by GSE.
- Armenia — CBA prospectus decisions as corroboration.
- Moldova — CNPF authorized prospectuses and issue-result decisions as corroboration.
- Russia — FAS decisions and CBR issue register, narrowly and without widening MOEX technical intake.

**Expected useful records per 90 days:** 10–25, mainly DCM registration/corroboration and a small number of M&A regulatory events. Approved share should be 50–70% when the source corroborates an existing official record; standalone registration remains review.

**Permission/reuse:** Georgia must be displayed and stored as `regional_adjacent`, never as CIS. Interfax e-disclosure, KSE and Belarus sources remain outside this wave until explicit permission/access questions are resolved.

## Key risks

1. **Stage inflation:** registration/listing/permission may be mapped incorrectly to `Issued` or `Closed`.
2. **Lifecycle duplicates:** programme, tranche, book, pricing, listing and settlement notices can create multiple records for one economic lifecycle.
3. **Security collapse:** distinct ISINs from the same issuer/programme can be merged incorrectly.
4. **Technical noise:** government bonds, coupon payments, redemption, buybacks, REPO, ratings and listing maintenance dominate some feeds.
5. **Closed-subscription ambiguity:** a share issue may be internal recapitalization rather than market ECM.
6. **Geography leakage:** publisher location/language is not transaction geography.
7. **Reuse/legal:** public readability does not establish permission for repeated extraction or copied content.
8. **Language:** Armenian, Azerbaijani, Georgian, Uzbek and Tajik require deterministic field extraction and original-title preservation; machine translation must not replace primary evidence.
9. **Access drift:** JavaScript redesigns, PDF-link changes and intermittent regional access can silently empty a feed.

## Sources explicitly rejected

- Turkmenistan State Commodity and Raw Materials Exchange as a deal connector: its live events are commodity sales, not M&A/ECM/DCM.
- Social media, Telegram channels, anonymous aggregators, scraped reposts, SEO farms and search snippets as canonical evidence.
- Generic state-auction streams without a company-stake filter.
- Government bond, central-bank paper and treasury-auction streams for the corporate deal product.
- Tier 3 media as a sole basis for `approved`.

## Unanswered questions

1. Will KASE, AMX and BVM confirm unattended factual extraction and polling at the intended frequency?
2. Does ESID expose a stable public document URL and immutable document identifier for every row?
3. Can AIX RAS provide a stable public item index or documented endpoint without session/cookie dependence?
4. Is there an official Belarus deal-level archive accessible reliably from the intended production environment, and what metadata may be reused?
5. Will KSE grant written permission for metadata/content extraction, and if so under what limits?
6. Which competition authorities publish a complete decision set rather than selected press releases?
7. How should private/closed share issues be separated between true ECM, state recapitalization and technical capital changes?
8. Should sovereign and municipal DCM remain entirely out of scope, or become a separately labelled future stream?

## Readiness conclusion

**READY FOR IMPLEMENTATION PLANNING**, with a narrow CIS-SOURCES-01B scope limited to KASE, AMX and BVM and with a permission/terms checkpoint before production activation.

The research is sufficiently complete to design CIS-SOURCES-01B. It is not sufficient to activate every roadmap source, to claim comprehensive CIS coverage, or to implement ESID/AIX/KSE/Belarus sources without the unresolved checks above.
