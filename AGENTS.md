# Deal Markets Copilot — правила для Codex

## A. Project purpose

Deal Markets Copilot — open-source deal intelligence and analyst workflow system для M&A, ECM и DCM. Он собирает события из публичных источников, отсекает шум, классифицирует транзакции, нормализует поля, применяет quality controls, хранит evidence, формирует analyst workflow и публикует синхронизированные HTML/JSON/CSV/XLSX.

Это не Bloomberg, не торговая система, не инвестиционная рекомендация и не замена первичным документам.

## B. Repository map

- `src/deal_markets_copilot/` — fetch, classification, deal logic, workflow, reports.
- `data/` — persistent archive, curated precedents, financial inputs, demo events.
- `output/` — generated HTML, snapshot, CSV, XLSX, manifest.
- `scripts/` — workbook builders, verifier, scheduled launcher.
- `tests/` — unit and regression tests.
- `docs/` — modular project context and runbooks.
- `.github/workflows/` — CI, refresh and Pages deployment.

Подробная карта: [`docs/START_HERE.md`](docs/START_HERE.md).

## C. Before changing anything

1. Прочитай `AGENTS.md`.
2. Прочитай `docs/CURRENT_STATE.md`.
3. Через `docs/START_HERE.md` выбери только документы для текущей задачи.
4. Проверь `git status --short --branch` и текущую ветку.
5. Не считай старый чат, handoff, Build ID или run ID доказательством текущего состояния.

## D. Core invariants

- Historical precedents must never be mixed with live/current deal flow.
- Не дополняй current deal lists старыми или low-quality records.
- DCM никогда не использует M&A status `Closed`.
- Book closure = `Priced`; фактическое размещение облигаций = `Issued`.
- Technical filings, REPO, redemptions, coupon payments, routine registrations и buybacks не создают banker tasks.
- Unknown = `Not disclosed`; not applicable = `Not applicable`; не выдумывай нули.
- Один weak secondary source не делает сделку `approved`.
- `--replay` не должен изменять persistent database.
- Любое material JSON change требует синхронизации зависимых артефактов.
- Build ID выводится из полных bytes database, а не из выбранных полей.
- Public precedent median всегда показывает `n`; при `n < 3` показывай `N/M`.
- Не считай multiples без eligibility: approved M&A, disclosed EV, aligned currency и своевременно доступные financials.
- Пустой результат required source не может молча давать green health.
- Никогда не публикуй вместе артефакты из разных builds.

## E. Task scoping

- Один thread — одна связная единица работы.
- Не проводи полный аудит репозитория для узкой задачи.
- Читай только релевантные файлы и документы.
- Не запускай live pipeline для docs-only изменений.
- Не запускай full release gate для мелкого несвязанного изменения.
- Начинай с targeted investigation и targeted tests.
- Full release verification нужен только для production logic, data artifacts или publication changes.

## F. Verification

| Тип изменения | Минимальная проверка |
|---|---|
| Docs-only | `git diff --check` + проверка links/paths |
| Code logic | targeted tests + relevant regression tests |
| Data/artifacts | tests + rebuild + replay + strict verifier |
| Release | full CI + public manifest + public artifact verification |

Подробный runbook: [`docs/TESTING_AND_RELEASE.md`](docs/TESTING_AND_RELEASE.md).

## G. Git and safety

- Never use `git reset --hard`.
- Never force push.
- Never overwrite a newer bot commit with stale local output.
- Never delete user changes.
- Never commit credentials, private paths, client data or MNPI.
- Never commit `node_modules`, QA renders or inspection sidecars.
- Перед pull/push всегда проверяй branch, status и upstream drift.

## H. Documentation routing

- Current snapshot: `docs/CURRENT_STATE.md`.
- System and module boundaries: `docs/ARCHITECTURE.md`.
- Deal semantics and data invariants: `docs/DATA_RULES.md`.
- Known failures and protections: `docs/REGRESSIONS.md`.
- Tests, Excel, CI and publication: `docs/TESTING_AND_RELEASE.md`.
- Product direction and limits: `docs/PRODUCT_ROADMAP.md`.
- Rationale for durable choices: `docs/DECISIONS_LOG.md`.
- Prompt starters for a new thread: `docs/NEW_CHAT_TEMPLATE.md`.
- Installation and first run: `docs/SETUP.md`.
