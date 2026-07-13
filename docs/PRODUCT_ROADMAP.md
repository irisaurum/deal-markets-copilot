# Product roadmap

## Current product

Deal Markets Copilot is an **open-source deal intelligence and analyst workflow system for M&A, ECM and DCM**.

Its value chain is:

```text
event
→ signal/noise decision
→ evidence quality
→ structured transaction
→ banker relevance
→ analyst action
→ working output
```

The current product collects public events, keeps an auditable source trail, separates current flow from historical precedents, creates a Russian-first deal-intelligence dashboard and analyst workflow for Russia and CIS markets, and publishes synchronized HTML/JSON/CSV/XLSX. English remains available as an interface toggle; source titles and primary evidence are never machine-translated.

## Current strengths

- One public-source pipeline across M&A, ECM and DCM.
- Explicit quality, evidence and record-kind layers rather than a flat news feed.
- Type-specific deal cards and persistent transaction archive.
- Technical/noise suppression before analyst-task generation.
- Source-backed precedent analytics with eligibility and sample-size controls.
- Five-sheet Excel output aligned with the dashboard build.
- Automated CI refresh and public Pages deployment.
- Useful as a transparent portfolio project and lightweight analyst screen.
- Explicit country/market context and a public source-coverage map that separates connected sources from roadmap candidates.

## Current limitations

- Public sources only; reliability and disclosure depth vary.
- Russia remains the deepest live market; CIS coverage is deliberately narrow and must not be read as comprehensive.
- Limited, Technology-heavy reviewed precedent sample.
- DCM extraction is incomplete when notices omit structured terms.
- Some records remain `review` because primary evidence or parties are missing.
- Google News remains a discovery layer for part of coverage.
- It is not a replacement for Bloomberg, Dealogic, Capital IQ or LSEG.
- It is not investment advice and not a substitute for transaction documents.

## Committed work

These are current product commitments already expressed by code and invariants:

- preserve live/current versus historical separation;
- prefer evidence quality over filling a fixed number of cards;
- keep DCM status semantics distinct from M&A;
- keep generated artifacts synchronized and verifiable;
- expose uncertainty, sample size and missing disclosure honestly;
- keep public-data and no-trading-system boundaries.

## Proposed priorities

The following are proposals, not committed scope. Select one coherent item before implementation:

1. Expand official CIS source coverage only after access, reuse terms and a narrow event taxonomy are verified.
2. More complete DCM term extraction.
3. Field-level provenance rather than only record/source-level evidence.
4. Human review metadata and history.
5. Larger, better segmented precedent universe.
6. Better attention filtering in the review stream.
7. Less visual prominence for low-value technical filings.
8. Source-level SLA and health history.

Potential sequencing: official sources → DCM completeness → provenance/review history → precedent expansion → UI attention controls. Re-evaluate after each milestone rather than treating this as a fixed delivery plan.

## CIS source roadmap

| Market | Current state | Product rule |
|---|---|---|
| Russia / MOEX | Connected | Preserve the existing classifier, quality gates and technical-notice suppression. |
| Uzbekistan / UZSE | Connected, narrow | Collect only material fact 25 (securities issue), link every event to the primary disclosure and ignore records outside the configured archive window. |
| Kazakhstan / KASE and AIX | Roadmap | Do not ingest until permitted unattended access and stable announcement endpoints are confirmed; high-volume routine notices require a narrow taxonomy. |
| Uzbekistan / Openinfo | Roadmap | Add only after a stable public index or documented API is available; whitelist deal-relevant fact types. |
| Kyrgyzstan / KSE | Roadmap | Do not copy content without permission; retain as a link-only research candidate. |
| Belarus / BCSE and CSD | Roadmap | Confirm authoritative endpoints and reuse terms before implementation. |

Source activation is a code-and-config decision, not a presentation claim. A roadmap card does not count as current coverage, and an empty optional CIS source never turns overall health green by itself.

## Out of scope

- Trading, order routing, portfolio management or broker integration.
- Investment recommendations or automated deal conclusions.
- Claiming terminal-grade completeness from public data.
- Storing confidential client information, MNPI or broker exports.
- Replacing legal, financial or primary-document review.
