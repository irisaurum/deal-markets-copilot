# New chat templates

Use one thread for one coherent unit of work. Do not use one endless thread for the whole project.

Every new session should start from `AGENTS.md`, read `docs/CURRENT_STATE.md`, and use `docs/START_HERE.md` to select only relevant documents. Do not perform a full repository audit unless explicitly requested.

## Template A — Bug diagnosis and fix

```text
Goal
Diagnose and fix: <observable bug>.

Context
Start from AGENTS.md and docs/CURRENT_STATE.md. Use START_HERE to read only the affected subsystem and relevant REGRESSIONS entry.

Constraints
Preserve unrelated user changes. Reproduce the bug before editing. Fix the root cause. Do not run a full repo audit or live pipeline unless required by the affected layer.

Done when
The scenario is reproduced, the fix has a targeted regression test, relevant tests pass, and the diff contains only task-scope files. Do not commit/push unless requested.
```

## Template B — New feature

```text
Goal
Implement: <one coherent feature and user outcome>.

Context
Start from AGENTS.md and docs/CURRENT_STATE.md. Read PRODUCT_ROADMAP and ARCHITECTURE sections relevant to the feature.

Constraints
Keep existing data invariants and public-build synchronization. Separate proposed design choices from confirmed requirements. Avoid unrelated refactoring.

Done when
Acceptance behavior works, targeted and regression tests pass, documentation is updated where durable behavior changed, and verification matches the change risk.
```

## Template C — Data/source improvement

```text
Goal
Improve <source, field or classification rule> for <specific coverage>.

Context
Start from AGENTS.md and docs/CURRENT_STATE.md. Read ARCHITECTURE, DATA_RULES and relevant REGRESSIONS only.

Constraints
Prefer primary public sources. Preserve direct URLs and evidence provenance. Do not weaken quality gates or turn empty source results green. Do not invent missing values.

Done when
Success, empty, malformed and failure cases are tested; dedupe and current/historical separation remain correct; affected artifacts are rebuilt only if data changed.
```

## Template D — Release verification

```text
Goal
Publish and independently verify the already-approved release candidate <commit>.

Context
Start from AGENTS.md and docs/CURRENT_STATE.md. Read TESTING_AND_RELEASE and relevant CI regressions.

Constraints
Do not add features. Do not overwrite newer bot output. Use safe fast-forward git operations only. Stop and diagnose before changing code if CI fails.

Done when
The intended commit is pushed, the correct Actions run succeeds, the bot commit is identified, and public manifest, HTML, CSV and XLSX match one Build ID and record count.
```

## Short example — DCM completeness

```text
Goal
Improve extraction of coupon, maturity and ISIN from official DCM notices.

Context
Read `AGENTS.md`, `docs/CURRENT_STATE.md`, `docs/ARCHITECTURE.md`, `docs/DATA_RULES.md` and DCM-related entries in `docs/REGRESSIONS.md`. Inspect `sources.py`, `classifier.py` and the relevant parts of `deals.py`.

Constraints
Priced != Issued; DCM never uses Closed. Keep distinct issues separate. Missing terms remain Not disclosed. No full repository audit.

Done when
Representative official notices and adversarial non-ISIN text are covered by targeted tests; no technical filing becomes a banker task; affected release checks pass.
```
