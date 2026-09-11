# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read it before writing code here. It records the constraints that are not visible
from the source and the ones that are expensive to get wrong. If a request in your
session conflicts with anything in this file, stop and say so rather than working
around it — ask the maintainer (@RevantCI).

`CONTRIBUTING.md` is the companion: this file holds the technical constraints, that
one holds the idea → issue → PR flow.

## What this is

Bridge is a local-first Bible translation QA workbench (a rewrite of a legacy
Python/Tkinter tool): one Tauri+Svelte desktop window driving a single
long-lived Python sidecar process (`bridge-engine`) over a JSON-lines
stdio protocol. The sidecar composes Greek Room QA/NLP checks (Wildebeest,
USFM structural checker, versification) with 30+ pre-existing
`tc_ai_bridge` business-logic modules (translationCore project I/O,
alignment, import, Paratext/Logos, transaction safety) — none of that
existing logic was rewritten, only wrapped behind one protocol.

Windows (`x86_64-pc-windows-msvc`) is the only verified target so far;
macOS/Linux are planned but unverified.

## Commands

### Python engine (`engine/`)

```bash
cd engine
pip install -e ".[dev]"
pytest tests/ greek_room_engine/tests/ -q -p no:cacheprovider
```

Single test file or test: `pytest tests/test_bridge_service.py -v` or
`pytest tests/test_bridge_service.py::test_open_real_fixture_project -v`.
Set `PYTHONDONTWRITEBYTECODE=1` first if re-running after editing vendored
files (stale `.pyc` in `vendor/*/__pycache__` can otherwise mask an edit).

Sanity-check the raw protocol without any UI: `echo '{"id":"1","method":"ping","params":{}}' | python main.py`.
`python demo.py` runs a live walkthrough against a throwaway fixture project.

Real Wildebeest (`wildebeest-nlp`, not the PyPI package literally named
`wildebeest` — that's an unrelated project) requires **Python 3.12, not
3.13** (a 3.13 compile-time change rejects a lone-surrogate escape in one of
its docstrings). Without it, `WildebeestAdapter` degrades to a mock
automatically — `pip install -e ".[dev]"` alone always works; add the
`wildebeest` extra only on a 3.12 interpreter.

### Frontend (`/`, repo root)

```bash
npm install
npm run check    # svelte-check, should be 0 errors/warnings
npm run test     # Vitest component/store tests (jsdom) — added Stage 9A.2
npm run build    # production Vite build
npm run dev      # browser-only dev server at localhost:1420 — no sidecar, bridge.ping() etc. will fail
```

`npm run check` + `npm run test` + `npm run build` are the frontend
verification gate. Vitest uses jsdom, which does not lay out or paint — it
catches logic/structure regressions, not real 1366x768 rendering; a visual
check still needs the actual desktop app.

### Full desktop app (Windows, MSVC toolchain + Rust required)

```powershell
npm install
.\scripts\build-sidecars.ps1
npm run tauri dev
```

`build-sidecars.ps1` builds **two** PyInstaller executables from
`engine/bridge-engine.spec` and `engine/bridge-usfm-checker.spec` and copies
both target-triple-suffixed binaries into `src-tauri/binaries/` — both are
required; `bridge-engine.exe` deliberately never re-invokes itself to run
the USFM checker script. Verify the frozen pair directly (not just source)
with `python scripts/smoke_sidecars.py engine/dist/bridge-engine.exe`.

`src-tauri/` has both: `cargo check`/`cargo build` for compile success, and a
handful of real `#[test]` unit tests (`passage_semantic_wire::tests`,
`sidecar::tests` — 10 as of 2026-09-07) run with `cargo test`. Run both, not
just the compile check.

## Architecture

### Process boundary

```
Bridge.exe (Tauri/Rust shell + Svelte frontend)
   │  spawns once at startup, JSON-lines over stdin/stdout
   ▼
bridge-engine (PyInstaller-bundled Python sidecar, stays alive all session)
   │
   ▼
tc_ai_bridge business logic  +  GreekRoomEngine QA adapters
```

`engine/bridge_service.py` (`BridgeEngine`) is the single dispatcher — read
it first. It composes `greek_room_engine/engine.py`'s `GreekRoomEngine`
(offline QA adapters) with the 30 `tc_ai_bridge/*.py` modules, and exposes
one flat JSON-RPC-style method namespace (`Methods` class + `if m ==
Methods.X:` chain in `handle_request`). Every result — whether from
Wildebeest, the USFM checker, or a `tc_ai_bridge` QAIssue — gets normalized
into one `QaFinding` shape (`greek_room_engine/models/finding.py`) so the
UI never special-cases which engine produced it.

Three-way division of responsibility that the whole design hinges on:
Greek Room says "this is objectively suspicious," AI (when wired up) says
"here's what it may mean," the human decides. Nothing auto-applies to
project files — every finding carries an explicit review `status`.

### Two different vendoring shapes for the same upstream repo

Both the USFM structural checker (`engine/vendor/greekroom-usfm/`) and
versification support (`engine/vendor/greekroom-versification/`) are
unpublished code pulled from `BibleNLP/greek-room` at a pinned commit — not
real dependencies, not on PyPI. **They're integrated differently, and that
difference is deliberate, not inconsistent:**

- The USFM checker is a 4,000-line CLI script with no reusable functions,
  so it runs as an isolated subprocess/helper executable
  (`bridge-usfm-checker[.exe]`), invoked via `UsfmAdapter`.
- `versification.py` is a genuine library (real classes/methods on
  in-memory dicts), so `tc_ai_bridge/versification.py` imports it directly
  into the long-lived `bridge-engine` process — no subprocess.

Each vendor directory's `NOTICE.md` records provenance, license, and the
concrete bugs found while integrating it (Windows encoding crashes, an
upstream PyPI/GitHub version-skew bug, a class-level-state crash on a
second call in the same process, catastrophic GIL contention under thread
concurrency). Read the relevant `NOTICE.md` before touching either vendor
tree or adding a third — don't edit vendored files in place; adaptations
belong in Bridge's own adapter/wrapper code.

### On-disk project shape

A raw Scripture import becomes a translationCore-compatible book project:

```
<project>/manifest.json
<project>/<book>.usfm                          original source, preserved verbatim
<project>/<book>/<chapter>.json                 verse-keyed target Scripture
<project>/.apps/translationCore/alignmentData/<book>/<chapter>.json
<project>/.apps/translationCore/index/{translationNotes,translationWords}/<book>/
<project>/.bridge/import.json                   SHA-256 provenance + per-tool capability status
<project>/.bridge/progress.json                 per-book rollup: checked chapters + finding id → status
<project>/.apps/translationCoreAI/checkFindings/<book>/<chapter>.json
                                                the findings behind those ids, from the last succeeded
                                                check job — what the project QA report reads
```

`TranslationCoreProject` (`tc_ai_bridge/tc_project.py`) is the reader/writer
for this; `project_import.py` is the normalizer. translationNotes/Words are
never fabricated for a raw import — they're `requires-resource-index` until
a real background materialization pass runs (`resource_materializer.py`),
matching real translationCore's own boundary between "imported Scripture"
and "materialized checking tool indexes."

### Multi-book collections

Upstream translationCore rejects multi-book projects; Bridge imports a
folder/Paratext project with several books as one project **per book**,
linked via `.bridge/collection.json` on every sibling. Only the first book
is normalized eagerly; the rest carry `.bridge/lazy-import.json` and
normalize on first open (this is why a 66-book import is ~5s, not minutes).

## Hard invariants

These are the things that cost real people real work if they break. Every one of
them is enforced somewhere in the code or the tests; none of them is aspirational.

**The correction ledger is append-only.** Proposals are never updated in place and
never deleted. An edit, a rejection or a supersession writes a new row and the
previous wording survives as a snapshot
(`passage_semantic_repository.py`'s proposal history, added in Stage 9B.1).
Crash recovery, the audit trail, and the ability to explain to a translation team
why a verse changed all depend on this. The same rule holds for the tN/tW
disposition history in `tc_project.py` — compacting a record must not compact its
lifecycle events.

**Token lineage is identity.** Tokens carry a `lineage_id` and an
`instance_fingerprint` (`token_lineages` / `token_instances`, unique on the pair).
Code that re-tokenises, re-imports, or rebuilds an inventory must resolve lineage
through `token_lineage_candidates` — `SAME_LINEAGE` / `POSSIBLE_SUCCESSOR` /
`SPLIT_FROM` / `MERGED_FROM` / `NO_CORRESPONDENCE` — not mint fresh ids. A broken
lineage silently detaches a team's review history from the text it was about.
This is the same class of rule as gotcha 3 below: identity has to survive a
re-run, or decisions keyed to it are lost.

**Staleness propagates through the dependency graph.** `record_dependencies`
plus `pending_invalidations` are what mark downstream analysis `STALE` rather
than silently keeping it. If you add a derived record type, register it — there
are two real tests asserting it, both in `engine/tests/test_correction_stage9b0.py`:
`test_every_writable_dependency_type_is_registered` checks that every writable
record type appears in the authoritative `RECORD_DEPENDENCY_TABLES` map at the top
of `passage_semantic_repository.py`, and
`test_dependency_tables_all_exist_and_are_stale_propagatable` checks each mapped
table can actually carry a `STALE` lifecycle. (The comment at
`passage_semantic_repository.py:63` names a `test_dependency_graph_invariants` that
does not exist under that name — trust the test files, not the comment.) A derived value that never goes stale is worse
than no derived value.

**Latest job authoritative, history retained.** `lifecycle_status` carries
`SUPERSEDED` precisely so a superseded analysis attempt can stay on disk. Do not
prune superseded rows to save space.

**Schema changes are migrations.** The companion SQLite database is at
**schema v14** (`DATABASE_SCHEMA_VERSION` in
`engine/tc_ai_bridge/passage_semantic_repository.py`). There is no `migrations/`
directory and no `.sql` files — the schema and every `_MIGRATION_V1` … `_V14`
block live in that one module, applied in order. Any change needs: a version
bump, a new forward migration block, a migration test in the established
`test_v13_to_v14_migration_is_additive_and_keeps_v13_data_readable` style — build a
database at the previous version, migrate forward, assert the old rows are still
readable — and a note in `docs/HANDOFF.md`. The repository refuses to open a
database newer than it understands, and never downgrades. Never edit the schema in
place and never assume a user's project can be recreated — for a translation team,
that database *is* months of work.

**Offline operation is a product invariant, not a preference.** Do not introduce a
runtime dependency on a network service, a hosted API, or a login, in any code path
a translator hits during normal work. The one bundled network-shaped thing —
`ai_client.py` — is explicitly optional, human-invoked, and never on the path that
imports, checks, or opens a project. If a feature seems to need a network call, say
so and stop; that is an architecture decision, not an implementation detail.

## The analysis pipeline, and why stage numbers matter

The passage-aware semantic pipeline runs in numbered stages, followed by human
review and correction. Note the numbering collision flagged in
`DEVELOPER_GUIDE.md`: these semantic **Stages** are a different axis from the
Greek Room **Phases**, and the two are easy to confuse in older notes.

| Stage | Does | Lives in |
|---|---|---|
| 4 | Runtime integration | `passage_semantic_runtime.py` |
| 5 | Source semantic inventory, from UHB/UGNT | `source_semantic_inventory.py` |
| 6A | Target semantic inventory | `target_semantic_inventory.py` |
| 6B | Passage-aware source→target location | `semantic_location.py` |
| 7 | Meaning-preservation analysis | `meaning_analysis.py` |
| 8 | Bidirectional source-coverage / target-support QA | `qa_audit.py` |
| 9A | Human review UI: the QA findings queue | `qa_review` methods + Alignment Review |
| 9B.0–9B.4 | Correction proposal → review → authorized apply → affected re-analysis → positive verification → human `CORRECTED` acknowledgement | `correction_*` services |

Get the numbers right before quoting them: **6B is the location engine and 7 is
meaning preservation**, not 7 and 8. The test files are named for their stage
(`test_semantic_location_stage6b.py`, `test_meaning_analysis_stage7.py`,
`test_qa_audit_stage8.py`) and so are the goldens — use them as the source of
truth over any prose, including this file.

Each stage's module docstring states what it deliberately does *not* do, and those
refusals are load-bearing:

- **Stage 5 is source-only.** It never reads target Scripture.
- **Stage 6A is target-only, and is built independently of Stage 5 on purpose.**
  That independence is what makes the later comparison meaningful. Do not
  "optimise" Stage 6A by seeding it from Stage 5 output.
- **Stage 7 never relocates target expressions** — it analyses frozen Stage 6B
  locations.
- **Stage 8 never re-runs Stage 6B location search and never re-judges Stage 7.**
- **Stage 9B.4 never re-judges Stage 7 meaning.** Verification asks whether the
  original failed obligation is now positively satisfied by current Stage 6B/7/8
  evidence. A correction is never verified merely because a finding disappeared,
  and `PASSED` alone never sets `CORRECTED`.

## Goldens and thresholds

**The goldens are two files**, and they are not in a `goldens/` directory —
they sit beside the tests that read them:

```
engine/tests/fixtures/stage5-source-golden-v1.json    <- test_source_semantic_inventory_stage5.py
engine/tests/fixtures/stage6b-location-golden-v1.json <- test_semantic_location_stage6b.py
```

There are no Vitest snapshots and no `__snapshots__` directories anywhere in the
repo. `golden-notice` keys on the filename, so **a new golden must have `golden` in
its name** and live in that directory or CI will not flag a change to it.

**Never re-baseline a golden as part of another change.** If your change makes one
fail, that is a finding to report, not a file to regenerate. A re-baseline is its own
commit doing nothing else, with the reason in the message.
`.github/workflows/ci.yml`'s `golden-notice` job raises a warning naming the files
whenever one moves — it does not block, so it is a prompt to look, not a gate. Nothing
mechanical will stop you re-baselining by accident; this rule is the only thing that
does.

**The confidence thresholds are uncalibrated.** The 0.85 / 0.9 cut-offs in
`qa_audit.py`'s `severity_for()` (MEANING_SHIFT → HIGH, and HIGH → CRITICAL) are
placeholders, as is every confidence value elsewhere in the pipeline —
`MEANING_CALIBRATION_VERSION` is literally `"meaning-uncalibrated-v1"`, and raw
score and calibrated value are deliberately kept as separate fields so a real
calibration can land later. Do not build behaviour that assumes these numbers are
meaningful, and do not tune them to make a test pass.

**Known-pinned bug: Tamil negation.** `meaning_analysis._comparison_norm` does
`re.findall(r"[^\W_]+")` over NFD-decomposed text. Indic combining marks are not
alphanumeric, so a Tamil word is **split at every virama and vowel sign** and the
marks are discarded: `இல்லை` becomes two tokens. Stage 7's POLARITY branch tests
whole tokens, so it cannot see the negative and returns `CONTRADICTED` against a
Greek negative — a false contradiction, on this project's primary target language.
(`_category` survives because it substring-matches, so QUANTITY, TEMPORAL and
PARTICIPANT still work. The docstring's claim that Tamil vowel signs "remain
intact" is wrong.) This is pinned deliberately by
`test_tamil_negation_polarity_limit_is_pinned_not_worked_around`, which asserts
both the comparator's current output and that Stage 9B.4 verification reports the
resulting disagreement as `UNCERTAIN` rather than papering over it. When Stage 7
is fixed that test fails on purpose. Do not work around it locally in an unrelated
change. **This is scheduled work, not accepted behaviour.**

## Non-obvious gotchas (confirmed still true in current code, not assumed)

1. `TranslationCoreProject.summary` is a `@property` — `summary()` crashes.
2. `TranslationCoreProject.__init__` creates its own `self.journal`; never
   create a second one.
3. Finding ids must be **stable** (`_stable_finding_id()` in
   `bridge_service.py`, a sha1 of `chapter:verse:engine:check_type:disambiguator`),
   not `uuid4()` — decisions are keyed by finding id and must survive
   re-running checks.
4. `verse.runChecks` re-applies prior decisions from
   `qa_decisions_for_verse()` after running checks — keep this inline in
   the check flow, don't split it into a separate call.
5. Windows stdout must stay UTF-8
   (`sys.stdout.reconfigure(encoding="utf-8")` in `stdio_transport.py`) —
   removing it makes the sidecar crash silently on any non-Latin verse
   text and the Rust side just sees a timeout. Same failure mode shows up
   in file I/O throughout the vendored tools (default Windows `cp1252`
   choking on Tamil/Odia/Hebrew) — explicit `encoding="utf-8"`/`"utf-8-sig"`
   everywhere text touches disk, not just at the stdio boundary.
6. `plugins.shell.sidecar` must **not** appear in `tauri.conf.json` — not a
   valid field, causes a startup panic. Sidecar exec permission comes
   entirely from `src-tauri/capabilities/default.json`'s
   `shell:allow-execute` entry.
7. Store keys in `stores.ts` are composite `"chapter:verse"` — use
   `verseKey()`, not a bare verse number (silently collides data across
   chapters). The same class of bug exists at the book level when
   switching books; `resetBookState()` clears chapter/verse-keyed stores
   on `switchBook()` for exactly this reason.
8. The sidecar binary name must match the Rust target triple exactly
   (`bridge-engine-x86_64-pc-windows-msvc.exe` — get the triple from
   `rustc -vV`).
9. Avoid icon-font classes for icon-only controls with no text fallback —
   an offline/PyInstaller build can't reach a CDN icon font and they
   render as empty boxes; use Unicode glyphs or pair with a label.
10. `icons/icon.ico` missing → `cargo tauri dev` fails; placeholders are
    committed under `src-tauri/icons/`, referenced from `tauri.conf.json`'s
    `bundle.icon`.
11. `cargo metadata ... program not found` even though `cargo --version`
    works elsewhere usually means the current shell predates Rust's PATH
    changes — open a fresh terminal, don't fight it.
12. USFM verse bridges (`3-4`) and lettered segments (`3a`) are real,
    already-seen input — `_qaissue_to_finding`/finding conversion uses the
    first numeric component as the anchor while project navigation keeps
    the exact string; several vendored/wrapper functions pass these
    through as an identity fallback rather than crashing. Don't assume
    every `verse` parameter is a bare integer string.
13. A **running `bridge-engine.exe` blocks the next Rust build**:
    `tauri-build` copies each `externalBin` into `target/`, and Windows
    refuses to overwrite a running executable, so it panics with a bare
    `PermissionDenied: Access is denied.` that names nothing. `RunEvent::Exit`
    now stops the sidecar by closing its stdin (`run_stdio_loop` ends on EOF),
    with a `taskkill /T` backstop — a *tree* kill, because terminating the
    PyInstaller bootloader alone leaves the real Python child holding the
    file. A sidecar busy inside a long request when the app dies abruptly can
    still orphan; `Stop-Process -Name bridge-engine -Force` clears it.

## Working in this repo

**Never trust a doc's or an upstream dependency's description of what it
does — install/vendor it, run it against real input, and read what actually
happens before writing an adapter around it.** Every external integration
attempted so far (Wildebeest, the USFM checker, versification) turned out
to have a real, non-obvious problem invisible from reading the docs alone:
a wrong PyPI package name, a Python-version compile break, an unpublished
dependency, a Windows-only crash, upstream's own GitHub/PyPI releases
drifting apart, a class-level-state bug that only appears on a second call,
catastrophic slowdown only visible under real thread concurrency. This
applies to this file and to `docs/*.md` too — verify a claim against the
current code before relying on it for follow-up work.

Read `docs/DEVELOPER_GUIDE.md` first — it's the oriented summary of stack
decisions and the phase roadmap (planned vs. actual outcome per phase), kept
current. Don't assume the next task is just the next numbered phase; the
guide's roadmap table shows what's actually done.

`docs/BUILD_LOG.md` (formerly `DEVELOPER_HANDOFF.md`) is the authoritative,
continuously-updated detailed record underneath that summary — the full
investigation behind every decision and gotcha (exact root causes, file:line
references, session-by-session narrative). Read it when the guide's summary
isn't enough, and **keep appending to it** as work progresses — it's the
record `DEVELOPER_GUIDE.md` gets distilled from, not a doc to let go stale.

`docs/ARCHITECTURE.md` has the original design rationale (some file paths
there are stale — prefer `BUILD_LOG.md` and the actual code when they
disagree). `docs/ALIGNMENT.md` and `docs/IMPORTS.md` document the
manual-alignment and import subsystems respectively. `docs/QA_TEST_MATRIX.md`
is the release gate — a feature isn't release-ready because its unit tests
pass; check the matrix's source/frozen/desktop rows.

`docs/TEAM_ARCHITECTURE.md` (2026-09-11) is the design record for the planned
direction behind issues #44–#47: a second per-project `bridge-workbench.sqlite3`
for the Bridge-private stores (the v14 semantic DB is not extended), a named
user + device on every write, an *optional* team hub that syncs review state,
and a hub-served dashboard. Until that work lands, the single-user, file-based
description above is what the code does; when it lands, this file's on-disk
shape and invariants sections must be updated in the same commit.

## How to work here

`CONTRIBUTING.md` has the full flow. The short version, and the parts that apply
to an AI-assisted session specifically:

1. **Non-trivial work should have an issue**, so the reason survives the commit.
   File it with the Idea template; there is no acceptance step to wait for.
2. **Small and single-purpose.** One issue per PR. A PR that touches the engine,
   the schema and the UI at once cannot be reviewed properly by one person.
3. **Work goes directly onto `main`.** There is no branch protection and no
   required review, so CI on `main` is the only automated gate — treat a red run
   as a real failure, not a formality. Branch when you want a second opinion
   before something lands, not as a matter of routine.
4. **Say what you verified.** In the PR description, separate what you ran and
   watched work from what you believe to be true because the code looks right.
   This matters more here than anywhere else: a confident explanation is not
   evidence. "I built the installer, imported a project and the findings
   appeared" is evidence. "The tests pass" is evidence. "This should now handle
   the edge case" is not.
5. **Report surprises, don't absorb them.** If you find a bug adjacent to your
   task, file it. Don't fix it quietly in the same PR.
6. **Verification gates.** Frontend: `npm run check` + `npm run test` + `npm run
   build`. Engine: the pytest suite. Shell: `cargo check` *and* `cargo test` —
   both, not just the compile. `.github/workflows/ci.yml` runs the first three on
   every PR; `docs/QA_TEST_MATRIX.md` is the release gate beyond that, and a
   feature is not release-ready just because its unit tests pass.
7. **Don't trust the frozen build because source passed.** The two have diverged
   before. `scripts/smoke_sidecars.py` checks the frozen pair, and it is
   currently `continue-on-error` in `release.yml` because of a known,
   pre-existing `project.inspectImport` classification mismatch — so a green
   release build is not evidence the sidecars are healthy.

## Stop and ask before writing any code

These are cheap to start and expensive to undo. If a task appears to require one,
raise it as a question in the issue rather than deciding it in a commit:

- Changing the companion database schema (currently v14)
- Anything that adds a server, an account, a login, or a network round-trip on a
  runtime path a translator hits
- Re-baselining either golden
- Changing the confidence thresholds or the auto-apply behaviour
- A second Scripture writer, or an alternative path for applying corrections to
  the text — Stage 9B.3b's authorized write behind an explicit human confirmation
  is deliberately the only one
- Bundling or switching the multilingual embedding model
  (`SemanticEmbeddingProvider.available` is `False` in the shipped app today, so
  production location runs use lexical/structural evidence only — that is a known
  state, not a bug to fix in passing)
- Adding a third vendored upstream tree under `engine/vendor/`

---

*Maintainer: @RevantCI. When in doubt, the answer is a question in the issue, not
a commit.*
