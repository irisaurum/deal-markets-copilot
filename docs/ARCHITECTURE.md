# Architecture

Это описание текущей реализации, а не целевой архитектуры.

## System pipeline

```text
Sources
→ Fetch and source health
→ Deduplication
→ Classification
→ Technical/noise suppression
→ Deal extraction
→ Field normalization
→ Quality gate
→ Archive/precedent merge
→ Financial enrichment
→ Multiple eligibility
→ Analyst workflow
→ HTML/JSON/CSV
→ XLSX
→ Replay
→ Strict verification
→ GitHub Actions
→ GitHub Pages
```

`run.py` координирует pipeline. В `--live` он получает данные, обновляет archive и строит public artifacts. В `--replay` он повторно строит отчёт и snapshot из сохранённых данных без network fetch и без мутации database.

## Module map

| Module | Responsibility | Main input | Main output / coupling |
|---|---|---|---|
| `models.py` | Typed domain containers | Raw field values | `Event`, `ClassifiedEvent`, `DealRecord`; shared schema contract |
| `sources.py` | RSS/Atom, MOEX, issuer pages, Google News, SEC/GDELT adapters, URL resolution | `config.json`, network responses | `Event[]`, market quotes; failures feed source health |
| `classifier.py` | Category, score, coverage matching, event-level dedupe | `Event`, coverage config | `ClassifiedEvent`; coupled to keyword and technical-notice rules |
| `deals.py` | Deal extraction, normalization, persistent merge, quality gate, buckets, financials and multiples | Classified events and JSON datasets | Normalized deal rows, CSV, current-deal selection |
| `workflow.py` | New-signal comparison, hypotheses, tasks, market-move actions, readout | Actionable classified events, quotes, previous snapshot | `workflow` section of snapshot/report |
| `report.py` | HTML dashboard and Telegram-safe digest rendering | Events, workflow, deals, health | `output/deal_markets_brief.html`, digest text |
| `telegram.py` | Optional local/GitHub-secret Telegram delivery | Environment variables, digest | Telegram API request; disabled by default |
| `run.py` | End-to-end orchestration and health/build calculation | CLI mode, config, all modules | Database, HTML, snapshot and CSV; XLSX sync status |

Important coupling:

- `classifier.py` decides the first category, but `deals.py` owns transaction semantics and final quality.
- `select_key_deals()` and `select_deal_buckets()` are the shared current-flow contract used by HTML, verifier and CI workbook.
- `_multiple_is_eligible()` is shared by analytics and the CI workbook.
- Build health depends on database bytes and the existing XLSX manifest; the CI sequence rebuilds XLSX and then uses replay to refresh health.

## Data stores

- `data/precedent_transactions.json` — version-controlled persistent normalized archive and canonical public dataset.
- `data/curated_precedents.json` — analyst-reviewed historical benchmark transactions; IDs use the `CURATED-` prefix and are excluded from current flow.
- `data/financials.json` — sourced financial inputs keyed by deal ID for multiple calculations.
- `data/sample_events.json` — offline demo inputs; not production evidence.

## Generated artifacts

- `output/deal_markets_brief.html` — dashboard.
- `output/latest_snapshot.json` — last run health, events, quotes and workflow state.
- `output/precedent_transactions.csv` — flat export of the canonical dataset.
- `output/precedent_transactions.xlsx` — five-sheet analyst workbook.
- `output/build_manifest.json` — Build ID, dataset SHA-256, count and generation time.

## Build synchronization

The bytes of `data/precedent_transactions.json` are hashed with SHA-256. The first 12 hexadecimal characters are the Build ID. The manifest stores the full hash, Build ID and row count. Snapshot health and HTML expose the same identity. CSV must reproduce every public field in row order. XLSX must contain the same deal IDs and Build ID.

```text
database bytes
  ├─→ SHA-256 / Build ID
  ├─→ manifest
  ├─→ snapshot health
  ├─→ HTML
  ├─→ CSV
  └─→ XLSX
```

`scripts/verify_public_artifacts.py` rejects mixed builds, field-level CSV drift, missing/phantom workbook IDs, unsafe links, invalid core fields and selected business regressions.

## Excel builders

- `scripts/build_precedents_workbook.mjs` — local analyst build using `@oai/artifact-tool`, formula inspection and five visual QA renders.
- `scripts/build_precedents_workbook_ci.py` — public GitHub runner fallback using XlsxWriter with the same five-sheet contract.

The required sheets are `Summary`, `Deals`, `Financials`, `Multiples`, `Sources & QA`.

## CI flow

`.github/workflows/deal-desk.yml` runs on relevant pushes, manual dispatch and weekday schedule:

1. checkout and Python 3.12 setup;
2. tests;
3. `run.py --live`;
4. install CI workbook dependency;
5. build XLSX;
6. `run.py --replay` to synchronize health;
7. tests and artifact verifier;
8. assemble the Pages artifact;
9. commit changed public data/output as the bot;
10. upload and deploy Pages, retrying a transient deployment failure once.

Workflow concurrency cancels an older in-progress run when a newer run supersedes it.
