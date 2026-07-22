# CIS-SOURCES-01C-A — official-source activation research

Research date: 2026-07-21
Scope: BVM, KASE and AMX activation paths, plus only the previously researched fallback sources named in the task.
This document is operational research, not a legal opinion. Ambiguous website terms and database-rights questions require written operator confirmation or professional legal review before broader use.

## Executive decision

- **BVM:** `ENABLE_AFTER_WRITTEN_CONFIRMATION`. Ordinary unattended HTML is stable, but no official wording was found that permits repeated extraction and publication of normalized public CSV/XLSX/JSON. BVM also sells electronic information products and archive access.
- **KASE:** `ENABLE_AFTER_WRITTEN_CONFIRMATION`. Ordinary unattended HTML is stable. The official footer states: “Copying materials only with written permission.” KASE market-data agreements do not establish a free news-reuse route.
- **AMX:** `REQUEST_TECHNICAL_ACCESS`. Normal browser access works, but ordinary unattended requests return a Cloudflare challenge shell. No official RSS/API/news export was located, and the linked Terms of Use route returned a visible 404.
- **Fastest lawful activation:** CNPF Moldova, `READY_WITH_CONSERVATIVE_LIMITS`. CNPF publishes an official Atom feed and official terms authorizing reproduction with source attribution, subject to copyright law and any page-specific restriction. The first engineering task should implement only narrowly whitelisted CNPF issue-result and takeover-decision events.
- **No source was activated and no outreach was sent.**

## Methodology and evidence labels

The existing specifications remain the source of truth for event semantics and historic yield: [research](CIS_SOURCE_RESEARCH.md), [matrix](CIS_SOURCE_MATRIX.csv), [samples](CIS_SOURCE_SAMPLES.csv), [taxonomy](CIS_EVENT_TAXONOMY.md), and [Wave 1 implementation](CIS_SOURCE_WAVE1_IMPLEMENTATION.md). This task rechecked only access, official terms, data services, contact paths and the lawful activation route.

Evidence was assessed in this order: official terms; copyright/data-use policy; feed/API documentation; official data-service/licensing pages; FAQ; robots only as an operational signal; official contact pages; contextual public-information rules. A public page or permissive `robots.txt` is not treated as a reuse licence.

Labels:

- `VERIFIED_PERMISSION`: official wording covers the relevant use.
- `VERIFIED_RESTRICTION`: official wording restricts the relevant use.
- `VERIFIED_PUBLIC_ACCESS_ONLY`: access is established, but reuse is not.
- `INFERENCE`: an operational conclusion drawn from direct evidence.
- `UNRESOLVED`: official evidence does not answer the question.
- `NEEDS_WRITTEN_CONFIRMATION`: activation depends on an operator answer.

Checks used ordinary low-volume requests and normal browser navigation only. No CAPTCHA or Cloudflare bypass, proxy rotation, undocumented API approval, login, form submission or acceptance of contractual terms was attempted. Small byte differences between repeated dynamic pages are not treated as instability when the same index and records remained present.

## Intended use tested against the terms

The product would poll one public official index conservatively, open a capped number of official detail pages, and retain only factual transaction metadata: official event ID, short original title, issuer, amount, currency, ISIN, dates, lifecycle stage, canonical page and official document links. It would not retain full article text, reproduce page design, bypass controls or resell source content. It would publish normalized factual records in a free, non-commercial portfolio/educational product, including public CSV/XLSX/JSON, with source attribution and canonical links.

The public export is material: permission to read a page, or even to use information internally, does not by itself establish permission to repeatedly poll it or redistribute a normalized public dataset.

## Wave 1 decisions

### BVM — Moldova Stock Exchange

Operator: Moldova Stock Exchange (Bursa de Valori a Moldovei)
Official index: [News](https://www.bvm.md/en/news/)
Access date: 2026-07-21

#### Technical access

- `VERIFIED_PUBLIC_ACCESS_ONLY`: the index, `/en/news/page/50`, and numeric detail pages returned ordinary public HTML without authentication.
- Two ordinary index requests returned HTTP 200 and approximately 28 KB; the same index structure and records remained available.
- Stable detail example: [MAIB bond issue 25](https://www.bvm.md/en/news/1655/).
- Romanian and Russian index variants also returned ordinary HTML.
- The sample prospectus link is a relative BVM-hosted PDF (`/fckeditorfiles/prospect - Copy 4.pdf`); the page also links external CNPF material. Document ownership therefore has to be checked per link.
- No official RSS, XML, JSON or news API was located. The official site returned a 404 representation for `robots.txt`; that is only an operational observation.

#### Official terms, services and contact evidence

| Label | Official evidence | Finding and interpretation | Confidence | Unresolved point |
|---|---|---|---|---|
| `VERIFIED_PUBLIC_ACCESS_ONLY` | [Products Services](https://www.bvm.md/en/services), Moldova Stock Exchange | BVM says it supplies interested parties products and services in paper and electronic form, including a bulletin, company information, statistics, orders and archive access. This confirms an official data-service route, not free news reuse. | high | Whether the public news pages are outside the paid-product framework. |
| `VERIFIED_PUBLIC_ACCESS_ONLY` | [Legislation](https://www.bvm.md/en/legislation) and the linked official fee list | The fee list includes an electronic bulletin, emailed statistics, one-off company information and third-party archive access. It does not expressly price or license the proposed news connector. | high | Applicable agreement, tariff and non-commercial exception. |
| `UNRESOLVED` | BVM English, Romanian and Russian pages reviewed | No official website terms, copyright policy or reuse statement was found that covers factual extraction, title storage, repeated polling or public derived exports. | medium | All intended-use permission dimensions. |
| `NEEDS_WRITTEN_CONFIRMATION` | [Contacts](https://www.bvm.md/en/contac), Moldova Stock Exchange | `office@bvm.md` is the official general address. The contact page lists the Marketing, Listing and Quotation Department and Electronic Systems Department. | high | Which department owns approval and whether a written agreement is required. |

#### Dimension-by-dimension answer

| Dimension | Answer |
|---|---|
| public_read_access | YES — public ordinary HTML. |
| unattended_access | YES technically; permission to automate remains unresolved. |
| factual_extraction | UNRESOLVED. |
| metadata_storage | UNRESOLVED. |
| title_storage | UNRESOLVED. |
| canonical_linking | UNRESOLVED in official terms; technically stable. |
| repeated_polling | UNRESOLVED; no published rate limit found. |
| derived_data_publication | UNRESOLVED, including public CSV/XLSX/JSON. |
| attribution_requirement | UNRESOLVED. |
| written_permission_requirement | Treat as YES for activation until BVM confirms otherwise. |
| technical_blocker | None at conservative volume. |
| legal_or_terms_uncertainty | High: no intended-use reuse grant and a paid information-service framework exists. |

**BVM activation decision: `ENABLE_AFTER_WRITTEN_CONFIRMATION`.** Proposed ceiling after approval: one poll every six hours, no more than two index pages and ten detail pages per run. Contact `office@bvm.md`, addressed to Marketing, Listing and Quotation plus Electronic Systems. Ask separately about factual extraction, short-title storage, canonical links, low-frequency polling, public normalized exports, attribution, agreement and tariff. Drafts are in [the outreach pack](CIS_SOURCE_OUTREACH_PACK.md).

### KASE — Kazakhstan Stock Exchange

Operator: Kazakhstan Stock Exchange JSC
Official index: [Market and Company News](https://kase.kz/en/information/news/all)
Access date: 2026-07-21

#### Technical access

- `VERIFIED_PUBLIC_ACCESS_ONLY`: the index and numeric detail pages returned ordinary public HTML without authentication.
- Two ordinary index requests returned HTTP 200 and approximately 513 KB; the same content surface remained available.
- Stable detail example: [KMF Bank bond issues](https://kase.kz/en/information/news/show/1567249).
- English, Russian and Kazakh detail variants returned ordinary HTML. The archive supports ordinary date-filter navigation and numeric details.
- No undocumented endpoint is treated as an approved API.

#### Official terms, data services and contact evidence

| Label | Official evidence | Finding and interpretation | Confidence | Unresolved point |
|---|---|---|---|---|
| `VERIFIED_RESTRICTION` | [KASE news index](https://kase.kz/en/information/news/all), Kazakhstan Stock Exchange JSC footer | “Copying materials only with written permission.” The wording is broad enough that the proposed extraction and public export cannot proceed on an assumed factual-data exception. | high | Whether KASE distinguishes facts, short titles and canonical links from copied materials. |
| `VERIFIED_PUBLIC_ACCESS_ONLY` | [Delayed Market Data](https://kase.kz/en/information/delayed-trade-information) and its official standard agreement | Delayed trading data is delivered via API; distribution to clients requires the specified agreement. The agreement treats derived information and redistribution separately. It is trading-data evidence, not a news licence. | high | Whether a separate news/disclosure feed or agreement exists. |
| `VERIFIED_PUBLIC_ACCESS_ONLY` | [Real-Time Market Data](https://kase.kz/en/information/real-time-data), [End of Day](https://kase.kz/en/information/information-about-trading-results), [Historical Data](https://kase.kz/en/information/archived-trade-information) | KASE offers official data products. None of these pages establishes free reuse of news metadata in a public portfolio dataset. | high | Applicable product, tariff and non-commercial route. |
| `NEEDS_WRITTEN_CONFIRMATION` | [Contacts](https://kase.kz/en/about/contacts), Kazakhstan Stock Exchange JSC | `mds@kase.kz` handles information products/statistics and commercial dissemination; `infodep@kase.kz` handles site content, trades and quotations. | high | Which channel controls news reuse and whether both approvals are needed. |

The published trading-data agreements and fees should not be quoted as a price for the news connector. A news-specific tariff or a documented free/non-commercial permission route was not found.

#### Dimension-by-dimension answer

| Dimension | Answer |
|---|---|
| public_read_access | YES — public ordinary HTML. |
| unattended_access | YES technically; contractual permission is unresolved. |
| factual_extraction | UNRESOLVED because of the written-permission restriction. |
| metadata_storage | UNRESOLVED. |
| title_storage | UNRESOLVED. |
| canonical_linking | UNRESOLVED in the official wording; technically stable. |
| repeated_polling | UNRESOLVED; no news-specific rate limit found. |
| derived_data_publication | UNRESOLVED, including public CSV/XLSX/JSON. |
| attribution_requirement | UNRESOLVED; permission may impose a format. |
| written_permission_requirement | YES, unless KASE confirms a narrower exception in writing. |
| technical_blocker | None at conservative volume. |
| legal_or_terms_uncertainty | High: factual-data distinction, public portfolio classification and applicable agreement. |

**KASE activation decision: `ENABLE_AFTER_WRITTEN_CONFIRMATION`.** Proposed ceiling after approval: one poll every six hours, no more than two date-filtered index pages and twelve details per run. Send one request to `mds@kase.kz` and copy `infodep@kase.kz`. Ask whether the free public product is classified as commercial dissemination, and request the exact agreement/tariff if required.

### AMX — Armenia Securities Exchange

Operator: Armenia Securities Exchange
Official index: [News](https://amx.am/en/news)
Access date: 2026-07-21

#### Technical access and official alternatives

- `VERIFIED_PUBLIC_ACCESS_ONLY`: a normal interactive browser displayed the public index, numeric details, contact page and footer without login.
- `VERIFIED_RESTRICTION` operationally: two ordinary unattended requests returned HTTP 200 challenge shells of 3,063 bytes containing the Cloudflare challenge platform, not news records. The same happened for a detail request.
- No challenge was solved or bypassed. Browser readability is not unattended access.
- The footer links [Terms of Use](https://amx.am/en/pages/terms_of_use), but the route displayed a 404 on the access date. The footer states “All Rights Reserved.”
- [AMX services](https://amx.am/en/about_us/services) did not expose an official news API, RSS, XML or structured export. The site offers a newsletter, but it was not subscribed to and is not a machine-readable connector contract.
- [Contact](https://amx.am/en/contact) lists `info@amx.am`.

#### CBA Armenia alternative

[CBA chairman decisions](https://www.cba.am/en/chairman-decisions) are public ordinary HTML and can corroborate prospectus-registration stage. [CBA Terms of Use](https://www.cba.am/en/SitePages/terms-of-use.aspx) protect website content and provide no reproduction, automated-polling or public-derived-dataset grant; the footer says “All Rights Reserved.” CBA is therefore not a permission-resolved substitute. It also cannot prove placement or `Issued` merely from prospectus registration.

#### Dimension-by-dimension answer

| Dimension | Answer |
|---|---|
| public_read_access | YES in a normal browser. |
| unattended_access | NO for the tested ordinary client; Cloudflare challenge shell. |
| factual_extraction | UNRESOLVED. |
| metadata_storage | UNRESOLVED. |
| title_storage | UNRESOLVED. |
| canonical_linking | UNRESOLVED in official terms. |
| repeated_polling | NO using the current ordinary path; terms/rates unresolved. |
| derived_data_publication | UNRESOLVED, including public CSV/XLSX/JSON. |
| attribution_requirement | UNRESOLVED. |
| written_permission_requirement | UNRESOLVED, but written technical and reuse approval is required before activation. |
| technical_blocker | Cloudflare challenge for ordinary unattended requests; no documented feed located. |
| legal_or_terms_uncertainty | High: the linked terms route is unavailable and the footer reserves rights. |

**AMX source-specific decision: `REQUEST_ALLOWLIST_OR_ACCESS`; taxonomy status: `REQUEST_TECHNICAL_ACCESS`.** Ask `info@amx.am` for a public or licensed structured feed, RSS/XML export, or expressly allowlisted low-frequency access, plus permission for the exact derived public use. Proposed ceiling if approved: one poll every twelve hours, one index page and six detail pages per run. No Armenian legal/permission draft is supplied because reliable legal nuance was not available.

## Fallback-source findings

### CNPF Moldova — primary

Operator: National Commission for Financial Markets (CNPF)
Official sources: [Atom feed](https://www.cnpf.md/ro/feed), [authorized prospectuses](https://www.cnpf.md/ro/prospecte-autorizate-6512.html), [terms and conditions](https://www.cnpf.md/ro/termeni-si-conditii-6436.html), [contacts](https://www.cnpf.md/ro/contacte-6351.html)
Access date: 2026-07-21

- `VERIFIED_PERMISSION`: the terms say reproduction is authorized with the source named and within applicable copyright law; they say any site-specific restriction or prior-consent requirement will be clearly indicated. This supports factual extraction, metadata/title storage and attributed publication for pages without a specific restriction.
- `VERIFIED_PUBLIC_ACCESS_ONLY`: the official Atom feed returned ordinary XML without authentication. It provides stable canonical links and dates.
- A generic hidden footer string says reproduction is permitted only with CNPF permission. The dedicated terms page is the direct policy page and is more specific, but the inconsistency is a residual risk. The implementation must retain exact attribution and stop if a page-specific restriction appears.
- No explicit automated frequency is published. The original research inference proposed 12-hour polling; the later product requirement supersedes it with 30-minute eligibility, one conditional feed request and no more than eight new or changed whitelisted details per eligible run.
- Recent feed items support approximately 5–8 useful 90-day events: bond/share issue results and takeover approvals. A broad feed would be noisy, so the source is not `READY_TO_ENABLE` without a narrow classifier-free source allowlist and negative fixtures.

Final status: **`READY_WITH_CONSERVATIVE_LIMITS`**. Required attribution: `Source: CNPF Moldova — [canonical official link]`. Store no full text. Prospectus approval is `Announced`; issue results can support `Issued` only when actual issue/placement result is explicit; takeover approval is `Announced` or `Confirmed`, never `Closed` without completion evidence.

### Openinfo fact 25 — fallback

Official sources: [fact 25 detail](https://openinfo.uz/ru/facts/25/1745), [contacts](https://openinfo.uz/ru/contacts)
Operator: National Agency for Perspective Projects of Uzbekistan
Access date: 2026-07-21

- `VERIFIED_PERMISSION`: the official footer says use of published materials requires a link to `openinfo.uz`. This supports attributed factual use, but does not expressly address repeated machine polling or a public derived database.
- The current `/ru/facts/25` index returned a 404 page, while numeric detail 1745 returned structured public content and a stable identifier. The linked old portal returned only an application shell in an ordinary request.
- Current UZSE support overlaps geographically and some events are registration-only. Incremental value is 5–15 candidate records per 90 days, with a high review share for closed subscriptions or unclear economic purpose.

Final status: **`RESEARCH_MORE`**. Exact blocker: restore or document a stable official fact-25 index/feed, then confirm low-frequency polling and public derived exports with `info@napp.uz`. Registration never means `Issued`.

### Kazakhstan ARDFM — later permission candidate

Official sources: [news](https://www.gov.kz/memleket/entities/ardfm/press/news?lang=en), [official RSS](https://www.gov.kz/api/v1/public/rss/ardfm/news/ru), [contacts](https://www.gov.kz/memleket/entities/ardfm/contacts)
Operator: Agency of the Republic of Kazakhstan for Regulation and Development of the Financial Market
Access date: 2026-07-21

- `VERIFIED_PUBLIC_ACCESS_ONLY`: ordinary public details and an official RSS endpoint are available without authentication.
- The site footer reserves rights and no intended-use reproduction licence was located. Public-government access and RSS availability do not alone authorize the public derived dataset.
- A narrow title/category filter could capture acquisition of a subsidiary and major-participant consent. Expected yield is 1–4 useful decisions per 90 days with low event noise.

Final status: **`ENABLE_AFTER_WRITTEN_CONFIRMATION`**. Use the official eOtinish route linked by the contact page for a formal answer; `info@finreg.kz` is shown as a registry/general address and expressly not for appeals. Any activation would poll RSS every 12 hours and inspect at most five candidate details. Regulatory permission is never `Closed` transaction evidence.

### Azerbaijan CBA ESID

Official sources: [ESID index](https://www.cbar.az/meas?language=en), [About ESID](https://www.cbar.az/page-182/about-esid?language=en), [disclosure rules](https://www.cbar.az/law-93/regulations-on-disclosure-of-information-by-issuers-in-the-securities-market?language=en), [contacts](https://www.cbar.az/page-97/contacts?language=en)
Operator: Central Bank of the Republic of Azerbaijan
Access date: 2026-07-21

- The official rules require free public access to issuer disclosures, prospectuses, final terms, issue results and material transactions. That proves access purpose, not unrestricted reuse or derived-dataset publication.
- Earlier checked-in research verified filters and more than 1,300 documents, but no stable visible detail URL. Current recheck from this environment failed DNS resolution, so current unattended stability is not asserted.
- PDF/Azerbaijani extraction, immutable document hrefs, source-file hashing and a strict category whitelist are still required.

Final status: **`RESEARCH_MORE`**. Exact blocker: current reachability, stable immutable document identity, reuse/public-export permission and PDF extraction proof. Official contact is `mail@cbar.az`; expected useful yield remains approximately 5–10 per 90 days only after a whitelist is proven.

### CBA Armenia

Official sources: [chairman decisions](https://www.cba.am/en/chairman-decisions), [Terms of Use](https://www.cba.am/en/SitePages/terms-of-use.aspx), [contact](https://www.cba.am/en/SitePages/contactdetails.aspx)
Operator: Central Bank of the Republic of Armenia
Access date: 2026-07-21

Public ordinary access is technically available, but the official terms reserve intellectual-property rights and do not authorize the intended reuse. Final status: **`ENABLE_AFTER_WRITTEN_CONFIRMATION`**. Expected yield is 3–10 registration/prospectus items per 90 days. It is corroboration only and does not resolve AMX placement/listing coverage.

### NBG Georgia — regional adjacent only

Official sources: [public companies and public securities](https://nbg.gov.ge/en/supervision/public-companies), [public information](https://nbg.gov.ge/en/about-us/public-information)
Operator: National Bank of Georgia
Access date: 2026-07-21

The issuer table is public, has ISIN/approval dates/document links, and lists `cm.corporate@nbg.gov.ge` for questions. NBG's public-information page establishes access to public information and copies; the located no-licence statistics terms apply to Interactive Statistics, not necessarily issuer documents or a derived public transaction dataset. Final status: **`RESEARCH_MORE`**. Georgia must remain labelled `regional_adjacent`. It is not in the recommended first three activation steps.

## Comparative permission conclusion

Only CNPF currently supports both an unattended official feed and sufficiently direct official wording for the intended attributed factual use. Openinfo has a clearer reuse statement than the exchanges but lacks a currently working index. KASE has an explicit written-permission restriction. BVM has stable access but no reuse grant and a paid data-service context. AMX lacks ordinary unattended access and resolved reuse terms.

Professional legal review remains advisable before treating any public normalized dataset as commercially reusable, before increasing request rates, or when source terms conflict, change, or invoke database rights. Operator confirmation should explicitly cover public CSV/XLSX/JSON, not only internal research.

## Minimal source diagnostics recommendation

Run #143 exposed only aggregate source health, so the failing source could not be identified from retained logs. A future change should retain one sanitized row per source with:

- `source_id`, state, `enabled`, `required`;
- index URL class, request status, parser status;
- items discovered, accepted and excluded;
- exact health reason, timestamp and sanitized error class;
- no credentials, query secrets, response bodies or article text.

Placement:

1. Emit a structured one-line row to workflow logs immediately after each source finishes and again before strict verification exits.
2. Persist the detailed sanitized rows in the internal snapshot under a source-health collection.
3. Put only aggregate states plus failing `source_id` and sanitized reason code in the public build manifest, if public diagnostics are desired.
4. Print a compact per-source table in release diagnostics before the strict verifier failure.

Strict required-source failure must remain unchanged.

## Risks and stop conditions

- Terms may change after this access date; record the policy URL and retrieval time in implementation evidence.
- Copyright permission may not resolve sui-generis database rights, commercial classification or bulk extraction.
- A feed is an access mechanism, not automatically a redistribution licence.
- A prospectus or regulatory approval is not proof of pricing, placement, issuance or closing.
- Stop and disable a source on a new challenge, explicit restriction, `403/429`, policy change, missing required feed, parser drift or operator objection.

## Exact next engineering task

**CIS-SOURCES-01C-B — implement CNPF Moldova conservative official-feed activation.** Add one disabled-by-default CNPF connector using only `https://www.cnpf.md/ro/feed`; whitelist explicit corporate bond/share issue results and takeover-prospectus approvals; cap each run at one feed request plus eight candidate details; retain source attribution and canonical URLs; store no full text; add negative fixtures for insurance, consumer, administrative, liquidation, redemption and technical decisions; enforce the lifecycle limits above; prove replay stability, strict health, artifact parity and no regression to canonical DCM records before any production activation decision.

Separate future task: **CIS-DIAGNOSTICS-01 — persist and emit sanitized per-source health rows before strict verification, with failed-source identification tests and no weakening of strict source health.**
