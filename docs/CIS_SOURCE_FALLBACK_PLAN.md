# CIS-SOURCES-01C-A — lawful fallback activation plan

Prepared: 2026-07-21. This plan recommends one primary source, one fallback and one later source. It does not authorize production activation.

## Decision

| Rank | Source | Final status | Why this position |
|---|---|---|---|
| Primary | CNPF Moldova official Atom feed | `READY_WITH_CONSERVATIVE_LIMITS` | Official syndication feed, explicit official reproduction permission with attribution, new official Moldova regulatory coverage, manageable parser complexity. |
| Fallback | Openinfo Uzbekistan fact 25 | `RESEARCH_MORE` | Official attribution-based reuse wording and highly structured fact details, but the current fact-25 index is 404 and current UZSE coverage creates material overlap. |
| Later | Kazakhstan ARDFM official RSS | `ENABLE_AFTER_WRITTEN_CONFIRMATION` | Stable official RSS and clean narrow M&A permissions, but public derived reuse is not expressly authorized and volume is low. |

Do not enable multiple uncertain sources together. KASE, BVM and AMX remain on their separate permission/access tracks.

## Primary — CNPF Moldova

Official surfaces: [Atom feed](https://www.cnpf.md/ro/feed), [terms](https://www.cnpf.md/ro/termeni-si-conditii-6436.html), [prospectuses](https://www.cnpf.md/ro/prospecte-autorizate-6512.html).

### Why it is the fastest lawful candidate

- Permission clarity: high. Dedicated official terms authorize reproduction with source attribution, subject to applicable copyright law and any clearly indicated page-specific restriction.
- Unattended access: high. The official Atom feed returned public XML without authentication.
- Officialness: primary regulator evidence.
- Parser complexity: low-to-medium. Parse a standard feed, then a capped number of ordinary detail pages.
- Time to production: estimated 1–2 focused engineering days plus the repository's required data/artifact release gate. This is an estimate, not completed implementation.
- Noise: broad feed is noisy, but an exact allowlist and negative fixtures can constrain it without changing classification semantics.

### Expected 90-day contribution

- Useful candidates: approximately **5–8**.
- Expected approved/review mix: approximately **4–6 approved** and **1–2 review**, assuming explicit issue-result/takeover evidence and existing quality rules. This is an inference from the current feed sample, not a guaranteed production count.
- Current-source overlap: low-to-medium. It overlaps BVM at issuer/country level but provides regulator-stage decisions and issue results; BVM is disabled, so it creates the first active official Moldova surface.

### Activation prerequisites

1. Use only the official feed URL; no undocumented endpoints.
2. One feed request every twelve hours; no more than eight candidate details per run.
3. Whitelist explicit corporate bond/share issue results and takeover-prospectus approvals.
4. Exclude insurance, consumer, administrative, liquidation, redemption, coupon and technical items.
5. Store factual metadata, short title, event ID, canonical/document links and exact attribution; no full text.
6. Stop on a specific restriction, terms conflict, access control, `403/429`, parser drift or missing required feed.
7. Add replay, deduplication, lifecycle, negative-fixture, source-health and artifact-parity tests before activation.

### Stage and lifecycle limits

- Prospectus or offer approval: `Announced`.
- Regulatory takeover approval: `Announced` or `Confirmed`; never `Closed` without completion evidence.
- Bond/share issue result: `Issued` only when the decision explicitly states the actual issue/placement result and amount; programme authorization is not a completed issue.
- Technical registrations and capital-maintenance actions remain non-deals or review according to existing rules.

### Honest product claim after activation

“Deal Markets Copilot includes a conservative official CNPF Moldova feed for selected corporate securities issue results and takeover approvals, with canonical-source attribution. It is not comprehensive Moldova market coverage and does not treat regulatory approval as transaction closing.”

What remains unconnected: BVM exchange lifecycle news; full Moldova prospectus archive; non-whitelisted CNPF decisions; issuer IR; any event whose economic substance is not explicit.

## Fallback — Openinfo Uzbekistan fact 25

Official detail and reuse evidence: [fact 25 example](https://openinfo.uz/ru/facts/25/1745); official contact: [portal contacts](https://openinfo.uz/ru/contacts).

### Why second

- Permission clarity: medium-high for ordinary material use because the official footer requires a link to `openinfo.uz`; repeated polling and public derived exports still need confirmation.
- Structured factual fields and stable numeric detail IDs lower parser and hallucination risk.
- Expected 90-day candidates: **5–15**.
- Expected approved/review mix: approximately **2–6 approved** and **3–9 review/excluded**, because closed subscriptions, registration-only events and unclear economic purpose are common.
- Overlap: high with the already connected narrow UZSE support. It deepens Uzbekistan rather than adding a new market.
- Estimated implementation effort after access resolution: **1–2 focused engineering days plus release verification**.

### Remaining prerequisite

The current `/ru/facts/25` index must be restored or replaced by a documented official index/feed. `info@napp.uz` should confirm low-frequency automated polling and public normalized JSON/CSV/XLSX under the footer's attribution condition. No undocumented endpoint should be inferred from page internals.

### Limits and honest claim

Registration or prospectus evidence is `Announced`/`Registered`, never `Issued`. Closed subscription requires economic-purpose review. Honest claim: “structured official Uzbekistan securities-registration disclosures with attribution,” not new-country coverage and not proof of placement.

## Later — Kazakhstan ARDFM

Official surfaces: [RSS](https://www.gov.kz/api/v1/public/rss/ardfm/news/ru), [news](https://www.gov.kz/memleket/entities/ardfm/press/news?lang=en), [contacts](https://www.gov.kz/memleket/entities/ardfm/contacts).

### Why later

- Stable official RSS and ordinary detail pages make technical effort low.
- A narrow acquisition/major-participant title filter has low noise.
- Permission for repeated extraction and public derived outputs is unresolved; formal written confirmation is required.
- Expected 90-day useful yield: **1–4** decisions.
- Expected approved/review mix: approximately **1–3 approved/confirmed-stage records** and **0–2 review**, depending on named target, stake and decision detail.
- Overlap: medium with Kazakhstan coverage, but it adds M&A regulatory evidence rather than KASE DCM.
- Estimated implementation effort after permission: **about 1 focused engineering day plus release verification**.

### Remaining prerequisite and lifecycle limit

Obtain a formal answer through the eOtinish route linked from the official contact page covering factual metadata, short titles, twelve-hour RSS polling, canonical links, public JSON/CSV/XLSX and attribution. An acquisition or major-participant permission is `Announced`/`Confirmed`, never `Closed` without separate completion evidence.

Honest product claim: “selected Kazakhstan financial-sector regulatory permissions,” not broad Kazakhstan M&A coverage.

## Sources not selected for the first queue

- **KASE:** stable but explicit written-permission restriction; wait for `mds@kase.kz` / `infodep@kase.kz`.
- **BVM:** stable but factual reuse, polling and public exports unresolved; wait for `office@bvm.md`.
- **AMX:** ordinary unattended access is blocked by Cloudflare challenge; request feed or allowlisting from `info@amx.am`.
- **CBA Armenia:** public access but all-rights-reserved terms and only registration-stage evidence; written confirmation required.
- **Azerbaijan ESID:** current reachability, stable document identity, PDF extraction and reuse all unresolved.
- **NBG Georgia:** valid later research candidate but must remain `regional_adjacent`; it is outside the first activation queue.

## Exact implementation handoff

Proceed with **CIS-SOURCES-01C-B — CNPF Moldova conservative official-feed activation** only. Do not combine it with outreach-dependent sources. The full acceptance contract and stop conditions are specified in [CIS_SOURCE_ACTIVATION_RESEARCH.md](CIS_SOURCE_ACTIVATION_RESEARCH.md).
