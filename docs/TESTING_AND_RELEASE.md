# Testing and release

Выбирай уровень проверки по риску изменения. Маленькая задача не требует полного production audit; публикуемая сборка не может ограничиться targeted test.

## Verification levels

| Change | Required minimum |
|---|---|
| Documentation-only | `git diff --check`, links/paths, privacy scan, confirm only docs changed |
| Small code change | Targeted test(s), relevant regression tests, `git diff --check` |
| Classification/data logic | Affected extraction/classification/quality tests plus relevant cases from `REGRESSIONS.md`; inspect representative outputs |
| Data/artifact change | Full tests, rebuild dependent artifacts, replay canonicalization/idempotency, strict verifier |
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

Replay is not ingestion. It must not create new economic events, change economic deal semantics or create lifecycle duplicates.

Replay may persist deterministic schema migration, source canonicalization and quality recomputation when that is required to bring `data/precedent_transactions.json` to the canonical fixed point. After the first canonicalization replay, a repeated replay must be byte-stable for the dataset.

For any data/artifact release candidate:

1. compute the database SHA-256;
2. run `python3 run.py --replay`;
3. compute SHA-256 again;
4. if replay persisted canonicalization, treat the new SHA as the final dataset SHA and run dependent artifact builds only after that persisted state;
5. run `python3 run.py --replay` again;
6. require byte-for-byte equality against the final dataset SHA.

Replay may refresh dependent presentation/snapshot state from saved inputs. It may rewrite deterministic canonical fields, but it must not create, merge or rewrite economic transactions outside the current canonicalization rules.

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
- dependent artifacts are generated only after the final persisted dataset state;
- HTML exposes the same Build ID;
- CSV matches every canonical field and row;
- XLSX contains the same Build ID and exact deal-ID set;
- JSON and CSV `quality_score` values are synchronized;
- no artifact comes from an older/newer build.

The strict verifier enforces most of this contract. It does not replace visual QA or public download verification.

## Public release contract

The public GitHub Pages contract contains exactly these release artifacts:

- dashboard HTML;
- `build_manifest.json`;
- `precedent_transactions.csv`;
- `precedent_transactions.xlsx`.

`latest_snapshot.json` is an internal-only artifact. It is not part of the public Pages contract, and a public 404 for that path is expected until the architecture deliberately changes.

## CI order

Trigger policy:

- pull requests run deterministic validation only: tests plus checked-in artifact contract verification;
- push to `main` runs deterministic validation for production-relevant paths only;
- push to `main` does not run live discovery, replay, bot commit or Pages deploy;
- changes limited to `docs/**`, `AGENTS.md`, `README.md`, `SECURITY.md` or `LICENSE` do not start production refresh;
- generated `output/**`, `site/**` and `data/precedent_transactions.json` remain ignored so the bot commit cannot trigger a refresh loop;
- mixed documentation + production changes on push run deterministic validation;
- `schedule` and `workflow_dispatch` own the autonomous production refresh because push path filters do not apply to them.

Current `.github/workflows/deal-desk.yml` validation path performs:

```text
pull_request or production-relevant push to main
→ tests
→ checked-in artifact contract verification
```

Current `.github/workflows/deal-desk.yml` production refresh path performs:

```text
schedule or workflow_dispatch
→ install pinned production dependencies
→ tests
→ restore external orchestration state and inject one UTC clock
→ fetch only eligible sources and save state
→ compute publish_delta
→ strict verifier + parent check for both delta and no-op
→ if delta: replay canonicalization/persistence
→ workbook + manifest generation
→ second replay health synchronization
→ local allowlisted bot commit
→ repeated stale-main check and explicit main-only fast-forward push
→ Pages deploy
```

The first replay step persists deterministic canonicalization before dependent artifacts are generated. The workbook and manifest are then built from the final dataset state. The second replay synchronizes health/presentation state against those dependent artifacts before the strict verifier gates the bot commit and Pages deployment.

Strict verifier failures write a compact GitHub Actions step summary with failed stage, invariant, artifact/file, row/field or Deal ID when available, expected/actual when available and the recommended next action. The summary does not replace traceback output or weaken assertions.

Before any bot push or Pages deploy, the workflow fetches `origin/main` and compares it with the run base SHA. This check also runs when the refresh produced no data commit. If `origin/main` moved, the workflow fails safely with expected and actual SHA values in the step summary. It does not rebase, merge, force-push or overwrite the remote; start a new production refresh on current `main`. A normal candidate pushes only `HEAD:refs/heads/main` to `origin`, without force.

Production refresh uses one concurrency group, `deal-desk-pages`, with `cancel-in-progress: false`. A valid production writer finishes; later slots queue and cannot overlap discovery or push. Validation runs use unique concurrency groups and cannot cancel a production refresh.

Operational cache restore/save uses separate `actions/cache` v4 actions. Keys are schema-, runner-platform- and main-scoped, with a stable restore prefix and unique run ID/attempt save suffix to respect immutable cache semantics. An `always()` validation step permits cache save only when the atomic state file exists and has the expected schema; no-op and known source-failure paths therefore retain operational state without allowing a missing/corrupt state directory to supersede it.

The workflow has exactly one `*/30 * * * *` cron. GitHub scheduling may be delayed, so this is a target cadence rather than a real-time SLA. Source requests still follow explicit 30/120/360/720-minute policies and deterministic UTC slots.

Operational polling state is external to Git and replay. It is restored/saved through a versioned GitHub Actions cache and written atomically. A missing cache does not bypass deterministic slot gating; corrupted state fails closed before transport. Cache retention is not a release artifact guarantee.

When `publish_delta=false`, the live step must print `NO_PUBLISH_DELTA`, preserve dataset bytes/Build ID, and skip replay/build regeneration, bot commit, push, Pages upload and deploy. Strict verification of the checked-in synchronized build and read-only parent verification still run.

Do not reorder artifact creation so that a database write can happen after the final XLSX build without another synchronization cycle.

If the strict verifier fails, there must be no bot commit and no Pages deployment.

## LaunchAgent policy

Final CI-01 policy:

- GitHub Actions scheduled production refresh is the only official production automation path.
- LaunchAgent remains unloaded by default and is not part of the production release contract.
- The local LaunchAgent is retained only as an emergency/manual local fallback.
- It must not run during development, integration, branch work, PR work or while a GitHub Actions production refresh may run.
- Restoring LaunchAgent must be explicit and manual; no task should restore it automatically.
- Before any manual restore, confirm the working tree is clean, the run is intentional and the output will be treated as local-only unless it later goes through the normal CI release path.

## Deployment verification

The Pages job makes one deploy attempt and retries once after a transient failure. A successful workflow is not sufficient by itself. Verify:

- Actions run targets the intended production commit and completes successfully;
- bot data commit, if created, descends from that commit;
- public `build_manifest.json` equals the repository manifest and its `dataset_sha256` equals the final dataset SHA;
- public HTML shows the same Build ID and record count;
- public CSV and XLSX download successfully;
- downloaded HTML/CSV/XLSX/manifest match the bot commit and belong to one build (prefer SHA-256 or byte comparison);
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

Full tests pass; database/artifacts are synchronized; replay reaches a canonical fixed point and is byte-stable after canonicalization; strict verifier passes; Excel technical and visual QA pass; repository state is understood. This is **not** a published release.

### Published release

Intended commit is on `origin/main`; the correct Actions run succeeds; any bot commit is identified; Pages deployment succeeds; public manifest, HTML, CSV and XLSX are independently verified against the published build.
