# Testing and release

Выбирай уровень проверки по риску изменения. Маленькая задача не требует полного production audit; публикуемая сборка не может ограничиться targeted test.

## Verification levels

| Change | Required minimum |
|---|---|
| Documentation-only | `git diff --check`, links/paths, privacy scan, confirm only docs changed |
| Small code change | Targeted test(s), relevant regression tests, `git diff --check` |
| Classification/data logic | Affected extraction/classification/quality tests plus relevant cases from `REGRESSIONS.md`; inspect representative outputs |
| Data/artifact change | Full tests, rebuild dependent artifacts, replay immutability, strict verifier |
| Excel change | Relevant builder(s), formulas/error scan, five-sheet contract, visual QA |
| Release | Full CI, bot commit if data changed, Pages deployment, public manifest and downloaded artifact verification |

## Core commands

### Tests

```bash
python3 -m unittest discover -s tests -v
```

For a narrow change, run an exact test first:

```bash
python3 -m unittest discover -s tests -p 'test_core.py' -k test_name -v
```

### Offline/demo

```bash
python3 run.py --demo
```

### Live pipeline

Run only when the task authorizes network/data changes:

```bash
python3 run.py --live
```

### Replay

```bash
python3 run.py --replay
```

### Public artifact verifier

```bash
python3 scripts/verify_public_artifacts.py
```

### Excel builders

Local analyst/visual-QA path:

```bash
node scripts/build_precedents_workbook.mjs
```

Public CI-compatible path:

```bash
python3 scripts/build_precedents_workbook_ci.py
```

The local path requires the workspace-provided `@oai/artifact-tool`; do not add its runtime or `node_modules` to git. The CI path uses dependencies from `requirements-ci.txt`.

## Replay rule

Replay must not mutate `data/precedent_transactions.json`.

For any data/artifact release candidate:

1. compute the database SHA-256;
2. run `python3 run.py --replay`;
3. compute SHA-256 again;
4. require byte-for-byte equality;
5. run a second replay when investigating replay/idempotency regressions.

Replay may refresh dependent presentation/snapshot state from saved inputs; it must not create, merge or rewrite transactions.

## Excel rules

The workbook contract is exactly five sheets:

1. `Summary`
2. `Deals`
3. `Financials`
4. `Multiples`
5. `Sources & QA`

For Excel-affecting changes:

- use both builder paths when the change concerns shared workbook semantics;
- verify Build ID and exact deal-ID set against the database;
- scan for `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#N/A`;
- inspect counts as counts, percentages as percentages and multiples as `x` values;
- visually inspect renders of all five sheets for clipped headers, serial dates, overlaps and unreadable widths;
- keep QA PNGs and inspection sidecars out of git.

## Build ID and synchronization

Canonical identity is `SHA-256(data/precedent_transactions.json)`. Build ID is its first 12 characters. A synchronized candidate requires:

- manifest full SHA, Build ID and count match the database;
- snapshot health matches and says `xlsx_synced=true`;
- HTML exposes the same Build ID;
- CSV matches every canonical field and row;
- XLSX contains the same Build ID and exact deal-ID set;
- no artifact comes from an older/newer build.

The strict verifier enforces most of this contract. It does not replace visual QA or public download verification.

## CI order

Push trigger policy:

- changes limited to `docs/**`, `AGENTS.md`, `README.md`, `SECURITY.md` or `LICENSE` do not start the production workflow;
- production code, config, source data, builders, verifier, tests, dependencies and workflow changes start it;
- generated `output/**`, `site/**` and `data/precedent_transactions.json` remain ignored so the bot commit cannot trigger a refresh loop;
- mixed documentation + production changes start the workflow;
- `schedule` and `workflow_dispatch` always start the autonomous production pipeline because push path filters do not apply to them.

Current `.github/workflows/deal-desk.yml` performs:

```text
tests
→ live fetch
→ install CI workbook dependency
→ XLSX build
→ replay
→ tests + artifact verifier
→ prepare Pages artifact
→ bot commit of public data/output when changed
→ upload Pages artifact
→ deploy
```

Concurrency cancels a stale in-progress run when a newer run supersedes it. Do not reorder artifact creation so that a database write can happen after the final XLSX build without another synchronization cycle.

## Deployment verification

The Pages job makes one deploy attempt and retries once after a transient failure. A successful workflow is not sufficient by itself. Verify:

- Actions run targets the intended production commit and completes successfully;
- bot data commit, if created, descends from that commit;
- public `build_manifest.json` equals the repository manifest;
- public HTML shows the same Build ID and record count;
- public CSV and XLSX download successfully;
- downloaded HTML/CSV/XLSX/manifest match the bot commit (prefer SHA-256 or byte comparison);
- public page has no relevant browser console errors.

## Safe git sequence

1. Inspect `git status --short --branch`, HEAD and `origin/main`.
2. Preserve user changes; never use destructive recovery.
3. Before release work, update with `git pull --ff-only` when safe.
4. If only generated public artifacts block a pull, stash only those named files after classifying the diff.
5. Never overwrite a newer bot commit with stale local output.
6. Commit only files in task scope; scan for credentials/private paths.
7. Push normally; never force push.

For newly created untracked documentation, remember that plain `git diff --check` does not inspect untracked files. Review them before staging, stage only the intended paths, then also run `git diff --cached --check`.

## Definition of Done

### Task done

Requested scope is implemented, targeted verification passes, docs are updated if durable behavior changed, and unrelated files are untouched.

### Local release candidate

Full tests pass; database/artifacts are synchronized; replay is byte-stable; strict verifier passes; Excel technical and visual QA pass; repository state is understood. This is **not** a published release.

### Published release

Intended commit is on `origin/main`; the correct Actions run succeeds; any bot commit is identified; Pages deployment succeeds; public manifest, HTML, CSV and XLSX are independently verified against the published build.
