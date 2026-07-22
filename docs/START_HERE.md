# Start here

## What this project is

Deal Markets Copilot — open-source system мониторинга M&A, ECM и DCM и analyst workflow. Она превращает публичные market events в проверяемые сделки, banker relevance, analyst actions и синхронные HTML/JSON/CSV/XLSX outputs.

Начинай любую сессию с [`../AGENTS.md`](../AGENTS.md) и [`CURRENT_STATE.md`](CURRENT_STATE.md). Не читай всю документацию без необходимости.

## How context is organized

- `AGENTS.md` — постоянные правила и invariants.
- `CURRENT_STATE.md` — последний проверенный snapshot.
- `ARCHITECTURE.md` — фактическая архитектура и связи модулей.
- `DATA_RULES.md` — business/data semantics и eligibility rules.
- `REGRESSIONS.md` — известные failure modes и защита.
- `TESTING_AND_RELEASE.md` — уровни проверки, Excel, CI и release runbook.
- `PRODUCT_ROADMAP.md` — текущий продукт, limits и предлагаемые приоритеты.
- `DECISIONS_LOG.md` — почему приняты долгоживущие решения.
- `NEW_CHAT_TEMPLATE.md` — короткие prompts для новых сессий.
- `SETUP.md` — запуск и настройка.
- `CIS_SOURCE_WAVE1_IMPLEMENTATION.md` — implementation и activation boundary для KASE, AMX и BVM.
- `CIS_SOURCE_CNPF_IMPLEMENTATION.md` — conservative Atom adapter и activation boundary для CNPF Moldova.

## Reading matrix

| Task type | Что читать после `AGENTS.md` и `CURRENT_STATE.md` |
|---|---|
| Small bug | Relevant subsystem + relevant section of `REGRESSIONS.md` |
| Data/classification | `ARCHITECTURE.md`, `DATA_RULES.md`, relevant regressions |
| Excel | `DATA_RULES.md`, `TESTING_AND_RELEASE.md`, workbook builder |
| CI/release | `TESTING_AND_RELEASE.md`, relevant regressions, workflow YAML |
| Product feature | `PRODUCT_ROADMAP.md`, `ARCHITECTURE.md` |
| New source | `ARCHITECTURE.md`, `DATA_RULES.md`, `config.json`, source fetcher |
| UI/dashboard | Relevant `report.py` section + `DATA_RULES.md` |
| Setup | `SETUP.md` |
| New thread | `NEW_CHAT_TEMPLATE.md` |

Главный принцип: **do not read every document for every task**. Текущий код и конфигурация всегда выше старой документации и чатов.
