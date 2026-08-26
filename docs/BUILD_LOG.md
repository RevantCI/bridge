# Build log: Bridge v0.8.0-beta.8

Updated: 2026-08-25

> **Start with [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) instead** for an
> oriented, up-to-date summary of the stack decisions, phase roadmap, and
> dependencies. Come here for the full investigation behind a specific
> decision or gotcha — exact root causes, file:line references, and the
> session-by-session narrative that the summary distills. This file is the
> continuously-updated detailed record; `DEVELOPER_GUIDE.md` is what to read
> first to get oriented.

## Current release state

The current working release adds the complete manual word-alignment loop and
Milestone 3A's offline original-language source baseline. The
authoritative design and limitations are in `docs/ALIGNMENT.md`; the release
gate is `docs/QA_TEST_MATRIX.md`.

- Protocol: `alignment.get/status/realign/unalign/save/complete/undo/backups/restore`.
- UI: per-verse alignment modal with occurrence-aware source/target token
  selection, all four group cardinalities, word bank, issues, status, completion,
  undo and selected-history restore. RTL/LTR direction is applied independently.
- Persistence: optimistic conflict comparison, exact token-identity validation,
  transaction-journal rollback, per-verse durable history, restart persistence,
  and tC word-alignment completed/invalid/pending markers.
- Rechecking: each alignment mutation immediately reruns local and Greek Room
  verse checks and refreshes editor state.
- AI provider compatibility: structured Responses requests first use the
  configured reasoning effort. If and only if a provider/model returns an
  explicit HTTP 400 unsupported-`reasoning` error, Bridge retries once without
  that optional object and records `provider-default`; unrelated 400 errors
  remain failures.
- Export/import: nested many-to-many `zaln`/`w` milestones are parsed into tC
  groups and aligned export writes re-importable USFM 3 over the retained source
  template.
- Original-language resources: raw OT/NT imports are initialized from exact,
  checksum-verified unfoldingWord UHB v3.0.0/UGNT v0.34 packs. All 66 books,
  31,103 verses, and 443,131 canonical tokens are bundled with CC BY-SA 4.0
  licenses, attribution, exact upstream commits, source/artifact hashes, and a
  reproducible generator. Aligned USFM and native tC projects are never
  overwritten; legacy raw-import recovery only fills empty source arrays and
  stops on a resource-version mismatch.
- Automated source gate: 197 Python tests pass in the maintained Windows/
  Python 3.12.4 environment as of the 2026-08-25 Milestone 1 baseline.
  Svelte and Rust source gates pass. Beta 2 frozen-sidecar and NSIS results,
  including exact artifact hashes and the remaining manual installer acceptance,
  are recorded in the QA matrix. The former load-sensitive versification
  wall-clock bound is now a deterministic concurrency-invariant test.
- Explicitly deferred: live original-source resource downloads and automatic
  Paratext/Logos synchronization. AI alignment proposals and UAlign-derived
  corpus statistics (count/probability/PMI/SED-boost) are implemented; see the
  Phase 6/7 sections further down.

## Phase roadmap status — read this first before picking up new work

The original plan (from the Claude Code sessions that did Phases 1-3, see
below) laid out 7 phases. Actual status as of 2026-08-21:

- **Phases 1-3**: done.
- **Phase 4 (USFM Checker + Versification): done (2026-08-21).** The USFM
  structural checker was completed first (vendored, wired up, verified
  against both source and a frozen packaged build — see that section
  further down). **Versification (detection, org-normalization, and a
  back-versification map) is now also done** — vendored separately, wired
  into the protocol as `versification.detect`/`orgRef`/`backVersificationMap`,
  and verified against both source and a real frozen build (see the
  Versification section further down). Nothing in Phase 4 has UI beyond
  what already existed — both halves are backend/protocol-only this pass,
  matching how the USFM checker itself shipped without a dedicated panel.
- **Phase 5 (Names & Transliteration, Uroman + Smart Edit Distance): done
  (2026-08-21).** A whole-book spelling-consistency check (Uroman +
  vendored Smart Edit Distance) is wired into `verse.runChecks` behind the
  existing `"local"` checks list — no frontend change needed, same as the
  USFM checker. See "Names & Transliteration — Phase 5 complete" further
  down.
- **Phase 6 (Alignment Intelligence, UAlign corpus stats): statistics engine
  done (2026-08-24).** The manual word-alignment editor added in
  `feat(alignment)` (see `docs/ALIGNMENT.md`) wasn't in the original plan at
  all — it was a prerequisite Phase 6 actually needed, since you can't
  compute corpus statistics over "human-approved alignments" if there was
  previously no way to create or approve one inside Bridge. That gap closed
  first; Phase 6's actual statistics work is now built on top of it —
  co-occurrence counts, translation probability, PMI, and an optional
  Smart-Edit-Distance phonetic boost, computed directly from Bridge's own
  completed alignments (not a vendored `ualign.py` — see the dedicated
  section further down for why). Backend/protocol-only this pass, same
  shape as Phases 4-5: two new read-only methods
  (`alignment.corpusStats.summary`/`forVerse`), no UI yet, no QaFinding
  output — AI alignment proposals stay in Phase 7, a scope decision made
  explicitly with the user before writing any code.
- **Phase 7 (Paratext/Logos connectors, AI explain, drag-and-drop): all four
  slices have real, tested work as of 2026-08-24, on a best-effort basis for
  the two that need a live external application to fully verify.** AI
  alignment proposals and drag-and-drop import are done and verified
  end-to-end (source + frozen). AI explain is wired and tested against real
  materialized evidence (a real TWL resource-layout bug and a missing
  translationAcademy bundle were both found and fixed along the way — see
  below), verified with a fake transport since no real API key was available
  this session. The Paratext connector's real, previously-missing companion
  plugin now exists and compiles against Paratext's actual installed
  interfaces, but was not deployed or loaded by a running Paratext instance
  this session (a protected-system-directory write was correctly blocked by
  this session's own safety controls). The Logos connector's real,
  previously-missing PowerShell/COM bridge script now exists and its
  process/protocol wiring is genuinely tested, but the actual COM automation
  calls inside it are unverified — Logos was not installed on this machine.
  See "Paratext/Logos connectors and AI explain — Phase 7 continued" further
  down for the full detail, what's verified vs. not, and exact next steps.

Between Phase 3 and now, real unplanned work also landed that mattered more
than staying on the numbered track: a 66-book import that took 4-6 minutes
and hit a hard timeout is now ~5-6 seconds (lazy per-book normalization), a
real security fix (plaintext API keys could persist to disk), and a
cancellable/retryable background job system replacing a blocking frontend
loop. None of that was in the original 7 phases either — it was necessary,
so it got done. Don't assume the next piece of work has to be the next
numbered phase in sequence; check what's actually broken or blocking first.

**A hard-won practice from this project so far, worth continuing**: every
external integration attempted (Wildebeest, the USFM checker, versification)
turned out to have a real, non-obvious problem that only surfaced by actually
running the code — wrong PyPI package name, a Python 3.13 compatibility
break, an unpublished dependency, a Windows-only `strftime` crash, a
version-skew bug between upstream's own GitHub and PyPI releases, a
class-level-state crash on a second call in the same process, a silently
different data license hiding inside an otherwise BSD-licensed vendor tree.
Don't trust a doc's
description of what a new integration will do — install it, run it against
real input, and read what actually happens before writing an adapter around
it. This is equally true of *this* documentation: verify claims made here
against the actual code before relying on them for follow-up work, the same
way you'd verify any third-party dependency's claims about itself.

### Versification — now done, see the dedicated section further down

This section originally recorded a research breadcrumb ("versification.py
was located in the same upstream repo, but not read, not vendored, and not
verified — do that next"). That work is now done (2026-08-21); see
"Versification — Phase 4 complete" further down in this document, and
`engine/vendor/greekroom-versification/NOTICE.md` for full provenance. Two
things from that breadcrumb turned out to matter and weren't visible until
the code was actually read and run: `versification.py` is a genuine
importable library (unlike the USFM checker's monolithic CLI script), so
it's wired in as a direct import, not a subprocess/helper executable; and
its `data/standard_mappings/*.json` files carry a **different license (CC
BY-SA 4.0) than the BSD-3-Clause code around them** — see the dedicated
section for why that's a real distinction, not a rubber-stamp of the USFM
checker's licensing precedent.

## Project context (carried over from the Claude Code sessions that did Phases 1-3)

This section summarizes what the earlier Claude Code work (`docs/CLAUDE_CODE_HANDOVER.md`,
not committed to this repo — it lives in the original handover doc) established, so this
file is self-contained for whoever picks it up next.

**What Bridge is:** a local-first Bible translation QA workbench replacing a legacy Python
Tkinter tool. One window, one Python sidecar process, Tauri/Svelte desktop shell.

**Core principle** (see `docs/ARCHITECTURE.md`):
- Greek Room says: "This is objectively suspicious."
- AI says: "Here is what it may mean in this passage."
- Human says: "This is what the translation should be."
- Nothing auto-applies to project files without human approval.

**Tech stack:** Tauri v2 (Rust) shell, Svelte 4 + TypeScript + Tailwind frontend, Python 3.13
PyInstaller-bundled sidecar (`bridge-engine`), Greek Room (Wildebeest adapter, mock fallback
if the real package isn't installed) plus 29 pre-existing `tc_ai_bridge` business-logic
modules (alignment, Paratext, Logos, AI, now also import), JSON-over-stdio protocol, pytest.
Windows is the primary target (`x86_64-pc-windows-msvc`); macOS/Linux are planned.

**Repo layout skeleton:**

```
engine/
  bridge_service.py          ← the sidecar dispatcher, read this first
  main.py                    ← sidecar entrypoint (PyInstaller target)
  greek_room_engine/         ← QA adapter layer (engine.py, models/finding.py,
                                protocol.py, adapters/, transport/stdio_transport.py)
  tc_ai_bridge/               ← 29 existing business-logic modules, not rewritten
                                (now 30, with project_import.py added — see below)
  tests/                      ← pytest suite

src/
  App.svelte, lib/stores.ts, lib/api/bridgeClient.ts, lib/types/finding.ts,
  lib/components/{ImportScreen,TopBar,VerseList,ReviewPanel,SettingsModal,ExportModal}.svelte

src-tauri/
  src/{main.rs,sidecar.rs,commands.rs}
  tauri.conf.json, capabilities/default.json, binaries/, icons/

docs/
  ARCHITECTURE.md, DEVELOPER_GUIDE.md, BUILD_LOG.md (this file), IMPORTS.md
```

### Phases 1-3 (done, before this import work)

- **Phase 1 — Protocol & sidecar consolidation:** `BridgeEngine` composes
  `GreekRoomEngine` + `tc_ai_bridge` behind one JSON protocol (`ping`, `engine.info`,
  `project.open`, `project.scan`, `chapter.verses`, `chapter.verseData`, `verse.get`,
  `verse.runChecks`, `verse.decide`, `verse.edit`, `settings.get`, `settings.set`,
  `export.aligned`, `export.nonAligned`). 24/24 pytest passing against a real fixture
  project with verified real file writes.
- **Phase 2 — Svelte frontend wired to the real sidecar:** full single-window UI
  (ImportScreen, TopBar, VerseList with inline colored findings, ReviewPanel with live
  Greek Room re-check and Accept/Reject/Ignore/Edit). Windows UTF-8 stdout fix applied.
- **Phase 3 — Decision persistence, chapter switching, whole-book, Settings & Export:**
  stable finding ids so decisions survive re-runs, chapter switching, "Run whole book"
  automation, `SettingsModal` (any OpenAI-compatible provider/endpoint/model/key),
  `ExportModal` (aligned JSON + simplified USFM export). Automation now uses
  sidecar-owned `checks.start/status/cancel/retry` jobs with real per-stage
  progress; cancellation is cooperative at check boundaries and failed or
  cancelled jobs remain retryable.

**This import-pipeline work (below) was new ground, not the originally planned Phase 4.**
The original roadmap after Phase 3 was: Phase 4 = USFM structural checker
+ versification; Phase 5 = names/transliteration (Uroman + SED); Phase 6 = alignment
intelligence (UAlign corpus stats); Phase 7 = Paratext/Logos connectors wired to the
protocol + AI explain + drag-and-drop import. Import work was picked up first because a
working import pipeline blocks everything downstream (you need real Scripture in the app
before checks/alignment/names work matter). **The USFM structural checker half of Phase 4
is now done (2026-08-20, see below)** — versification, and Phases 5-7, still haven't been
started.

### Gotchas still in force (from Phases 1-3, verified still true in the current code)

1. `TranslationCoreProject.summary` is a `@property`, not a method — calling `summary()` crashes.
2. `TranslationCoreProject.__init__` creates its own `self.journal`. Never create a second one.
3. Finding ids are stable (`_stable_finding_id()` in `bridge_service.py`, a sha1 of
   `chapter:verse:engine:check_type:disambiguator`) so decisions persist across runs.
   Don't revert to random `uuid4()` ids.
4. `verse.runChecks` re-applies prior decisions from `qa_decisions_for_verse()` after
   running checks — this must stay in the check flow, not a separate call.
5. Windows stdout UTF-8 fix (`sys.stdout.reconfigure(encoding="utf-8")` in
   `stdio_transport.py`) is critical — without it, non-Latin verse text crashes the
   sidecar silently and the Rust side just sees a timeout. Never remove it.
6. `plugins.shell.sidecar` must NOT be in `tauri.conf.json` — not a valid field, causes
   a startup panic. Sidecar permission comes entirely from `capabilities/default.json`'s
   `shell:allow-execute` entry.
7. Store keys are composite `chapter:verse` (e.g. `"1:3"`) — use `verseKey()` from
   `stores.ts`, not verse-only keys (silently collides data across chapters).
8. `ai_client.py`'s `OpenAIResponsesClient` endpoint is configurable via `base_url`;
   don't reintroduce a hardcoded `ENDPOINT` constant.
9. The sidecar binary name must match the Rust target triple exactly
   (`bridge-engine-x86_64-pc-windows-msvc.exe` on Windows — get the triple from `rustc -vV`).
10. Don't use icon-font classes (`ti-settings` etc.) for icon-only controls with no
    fallback label — PyInstaller/offline builds can't reach CDN icon fonts and they
    render as empty boxes. Use Unicode characters or pair with a text label.

### Known gaps still open (from Phases 1-3, verified still true in the current code)

- ~~USFM edit round-trip is still a stub~~ — **done 2026-08-20.** The real
  write logic wasn't missing from `tc_ai_bridge` at all — it turned out
  `TranslationCoreProject.apply_scripture_edit()` in `tc_project.py` was
  already a complete, working implementation (writes the target chapter
  JSON, reconciles alignment by word/occurrence signature, marks word
  alignment invalid, flags touched tN/tW index entries `verseEdits=True`,
  full journal transaction with rollback). `bridge_service.py`'s
  `edit_verse()` was just never calling it — it had its own separate no-op
  stub instead. Now it does: `edit_verse()` is a thin wrapper again, matching
  every other method in this file. The frontend (`ReviewPanel.svelte`) was
  already fully built for this (save, update store, re-run checks) and
  needed no changes beyond two small robustness fixes found while wiring
  this in: saving unchanged text is now a silent no-op instead of throwing
  an unhandled rejection (`apply_scripture_edit` correctly rejects a no-op
  edit; the UI just didn't call it before, so it never surfaced), and a real
  failure now shows an inline error instead of vanishing silently. Covered
  by two new tests in `test_bridge_service.py` that verify the edit actually
  lands (not just "committed": true) and that `WA_INVALID` surfaces on the
  next `verse.runChecks`. Full suite: 39/39 passing. Not click-tested in a
  running Tauri window this session (same build constraint as the other
  frontend work above) — worth a real click-through: edit a verse, confirm
  the new text persists after switching chapters and reopening the project,
  and that a stale-alignment finding appears.
- ~~`export.nonAligned` was a simplified reconstruction~~ — **superseded.** Both
  USFM exporters now use the retained source as a structural template and
  report the simplified fallback only for projects with no source USFM.
- **OWL repeated-word adapter doesn't exist yet** (`adapters/owl_adapter.py`).
- ~~Real Wildebeest package is still untested~~ — **done 2026-08-20, real
  engine wired up and passing tests. Requires Python 3.12, not 3.13.**

  **Root cause of the original blocker**: `pip install wildebeest` installs
  the wrong package (a same-named, unrelated ShopRunner image-processing
  library — never use it). The real one, from Ulf Hermjakob/USC-ISI, is on
  PyPI as **`wildebeest-nlp`** (only release: 0.9.2). Installing that under
  Python 3.13 fails to *compile* with `UnicodeEncodeError: ...surrogates not
  allowed` — one of its docstrings contains a literal `\uDC80`-`\uDCFF`
  escape as prose (describing surrogateescape handling, ironically), and
  **Python 3.13 newly disallows lone-surrogate escapes in docstrings at
  compile time** ([CPython issue #142411](https://github.com/python/cpython/issues/142411)
  confirms this is an intentional 3.13 change). Confirmed the same broken
  docstring is still on upstream's GitHub `master`, so installing from
  GitHub wouldn't have helped either. **Python 3.12.10 does not hit this
  restriction — confirmed working.** The machine this was developed on has
  since been switched from 3.13 to 3.12 entirely.

  **Engine now has a dedicated venv**: `engine/.venv` (gitignored), built
  with `py -3.12 -m venv .venv`, populated via
  `.venv\Scripts\python.exe -m pip install -e ".[dev,wildebeest]"`. The
  `wildebeest` extra in `pyproject.toml` pins `wildebeest-nlp==0.9.2` and is
  optional, not a hard dependency — `WildebeestAdapter` degrades to its mock
  whether it's installed or not, so a plain `pip install -e ".[dev]"` on any
  supported Python still works. Run tests via
  `engine\.venv\Scripts\python.exe -m pytest tests/ greek_room_engine/tests/ -q`
  (45 passed, includes 6 new real-engine tests, auto-skipped when the extra
  isn't installed).

  **Found and fixed a real related bug while investigating**: the adapter's
  `try: import wildebeest.wb_analysis ... except ImportError` only caught
  `ImportError`. Since the real failure mode is `UnicodeEncodeError`, simply
  having `wildebeest-nlp` installed (even with zero other code changes)
  would have crashed the entire sidecar at startup instead of degrading to
  the mock. Widened to `except Exception` — done and safe regardless of
  which Python version anyone else builds with.

  **What `_check_with_wildebeest()` now actually does** (previous version
  called a `wb_ana.check()` function that doesn't exist in the real
  package — that whole implementation was speculative and never once run
  against the real dependency). The real entry point is
  `wb_analysis.process(string=, lang_code=, json_output=<IO>)`, which
  returns an aggregate analysis report grouped by category — not a flat
  per-position issue list. Verified directly against 0.9.2 with real inputs
  (not documented anywhere upstream). Only three of its categories are
  wired into findings, each checked against real triggering input:
  `notable-token` (mixed-script tokens), `non-canonical` (NFD vs NFC form,
  with a real suggested-replacement), and zero-width/invisible characters
  from `block.ZERO_WIDTH`. Deliberately **not** treating every top-level key
  as a finding — most of the rest (`letter-script`, `block`'s ordinary
  per-character tallies) are corpus-level descriptive counts, not defects;
  verified a clean real Tamil verse produces zero findings from the real
  engine. `char-conflict` and `pattern` are real categories in the schema
  that no test input in this session happened to trigger — their shape is
  unverified, so they're not wired up. Don't guess it; verify against real
  triggering input first, the same way the rest of this was done.

  **Not yet done**: PyInstaller packaging for the real engine wasn't
  attempted this session. `wildebeest-nlp` ships a `data/` directory
  alongside its code — untested whether `wb_analysis.process()` reads
  anything from it at runtime (none of the three wired categories needed it
  in testing, but that doesn't rule out other paths). If building a frozen
  `.exe` with the real engine included, add
  `--collect-data wildebeest` to the PyInstaller command below as a
  defensive measure and verify carefully — this is unverified insurance,
  not a confirmed-necessary step.
- **Drag-and-drop import is still not wired** — no `onDragDropEvent` listener from
  `@tauri-apps/api` exists in `src/`; `ImportScreen` still requires the file picker.

### USFM structural checker — Phase 4 half done (2026-08-20)

New adapter, `engine/greek_room_engine/adapters/usfm_adapter.py`, registered
in `GreekRoomEngine`. Catches duplicate/missing verse numbers, unclosed
inline markers, and other structural USFM problems — a real gap nothing
else in the app checked before this.

**This is vendored, unpublished third-party code, not a normal
dependency — read this before touching it.** Unlike Wildebeest,
`greekroom`'s `usfm` submodule is **not published on PyPI** (only `owl`
and `gr_utilities` are, confirmed by inspecting the actual installed
wheel — `usfm`/`versification`/`wildebeest` exist only in the
`BibleNLP/greek-room` GitHub source tree). The decision to vendor it
anyway — rather than wait on upstream packaging or build a lesser
in-house checker — was made explicitly, with the license and long-term
maintenance cost discussed first. Don't undo that decision by casually
"cleaning up" or replacing this without the same consideration.

**Where it lives**: `engine/vendor/greekroom-usfm/` — `usfm_check.py`,
`ualign_utilities.py`, `Bible_USFM_tag_data.jsonl`,
`Bible_USFM_explanations.txt`, and a nested `greekroom/gr_utilities/`
package (see below for why). Full provenance — source URL, pinned commit
`18ddcf0e6c03fa2774b73b21186115d712e4cba9`, BSD 3-Clause license text and
attribution, and an explicit "don't edit these files in place" policy —
is in `NOTICE.md` in that directory. **Read `NOTICE.md` before re-syncing
against upstream or making any change here.**

**How it's invoked**: as an isolated subprocess (`UsfmAdapter.check_book()`),
not an import. In source mode the adapter uses the active Python interpreter
and the vendored script. In a frozen build it resolves the sibling
`bridge-usfm-checker[.exe]`, a separate PyInstaller artifact with a
Bridge-owned entrypoint (`engine/usfm_checker_main.py`). This matters:
`bridge-engine.exe` always starts the JSON-RPC loop and cannot be used as
`python.exe usfm_check.py`. The helper bundles the pinned vendor directory,
`regex`, both checker data files, and the license/notice. The adapter passes
stdin as `DEVNULL`, validates the exit code and report, and returns an
explicit `checker_error` for a timeout/crash/missing report instead of
silently treating failure as a clean book.

**Its own `-j/--json` output flag is dead code** — accepted by its
argparse setup but never referenced anywhere else in the 4,000 lines.
Verified by reading the source, not assumed; don't try to use `-j` and
expect a file to appear. The `.txt` report is the only real output to
parse, and its indentation depth to reach an individual issue varies by
category (3 or 4 levels) — `_parse_report()` in the adapter tracks an
indentation stack rather than assuming a fixed depth, and recognizes three
distinct real location-reference formats found by testing (see the
function's own docstring and `test_usfm_adapter.py` for the real captured
report text each was found in).

**Two real bugs found and fixed while integrating** — both documented
inline where fixed, in case they inform an upstream bug report later
(see the earlier discussion in this doc about contributing a packaging
fix upstream):
- A line in `usfm_check.py` used `%-d`/`%-H` in a `strftime` format string
  — glibc-only extensions Windows' C runtime doesn't support, raising
  `ValueError` immediately on startup on this Windows dev machine.
  Patched in place (marked `# BRIDGE PATCH`, per `NOTICE.md`'s policy for
  changes that are genuinely unavoidable) to the portable zero-padded
  equivalent — cosmetic only, just a report timestamp.
- The vendored `usfm_check.py` (pinned commit) calls
  `general_util.mkdirs_in_path()`, which doesn't exist in the *published*
  `greekroom==0.0.20` PyPI package's `gr_utilities.general_util` —
  **upstream's own GitHub source and PyPI release have already drifted
  apart from each other.** Fixed by also vendoring `general_util.py` from
  the *same* pinned commit (`greekroom/gr_utilities/` inside the vendor
  directory) and prioritizing it on the subprocess's own `PYTHONPATH`,
  rather than relying on the separately pip-installed `greekroom` package
  for this specific tool's dependencies. This is why the subprocess's
  `PYTHONPATH` matters — don't "simplify" it to just use whatever
  `greekroom` happens to be pip-installed.

**Wiring into checks**: whole-book, not per-verse — see
`UsfmAdapter`'s and `BridgeEngine._usfm_findings_for_book()`'s own
docstrings for why (each run spawns a subprocess loading a real tag
database). `bridge_service.py` computes and caches findings once per
book (keyed by project path), then filters to the requested chapter/verse
inside `run_verse_checks` whenever `"local"` or `"usfm"` is requested —
so it activates automatically with the frontend's existing default checks
list, no frontend change needed. A finding with no specific verse (e.g. a
whole-chapter "missing verse N") surfaces on that chapter's first verse,
since the UI has no chapter-level display slot. **Not invalidated by
`verse.edit`** — re-running the subprocess after every edit would be far
too slow, and a single verse edit essentially never changes book-wide
structure; re-opening the project re-runs it fresh. Findings get the same
stable-id treatment as Wildebeest/tN/tW findings, so decisions persist
across sessions.

**Verified**: `test_usfm_adapter.py` (parser unit tests against real
captured report text, not synthetic guesses; real end-to-end subprocess
tests against real broken and clean USFM; a subprocess-failure test
confirming explicit failure rather than false-clean degradation) plus
book-level success/failure caching tests in `test_bridge_service.py`.
`scripts/smoke_sidecars.py` runs the actual frozen `bridge-engine.exe` and
helper against balanced USFM containing duplicate and missing verses, then
asserts real `engine="usfm"` findings. Verified on Windows 2026-08-20.
Historical result at that milestone: 56 passed, 1 optional-Wildebeest module skipped.

**Packaging**: run `scripts/build-sidecars.ps1`; it builds both committed
specs and copies both target-suffixed artifacts into `src-tauri/binaries/`.
Tauri declares both in `bundle.externalBin`. Chapter/book automation starts a
sidecar-owned background job and polls lightweight status snapshots, so the
stdio dispatcher stays responsive while the helper runs. `verse.runChecks`
retains a 150-second timeout for the separate live per-verse recheck path.

### Versification — Phase 4 complete (2026-08-21)

New module, `engine/tc_ai_bridge/versification.py`, wrapping the vendored
Greek Room versification tool at `engine/vendor/greekroom-versification/`
(see that directory's `NOTICE.md` for full provenance, license, and the real
bugs found while integrating it — summarized below). Adds three sidecar
protocol methods: `versification.detect`, `versification.orgRef`,
`versification.backVersificationMap`.

**Different books/traditions number chapters and verses differently** — the
concrete motivating example: Psalm 3's Hebrew ('org') text opens with a
descriptive title ("A Psalm of David, when he fled from Absalom his son")
counted as verse 1, which most English ('eng') Bibles don't number as its
own verse. So eng verse 1 ("LORD, how are they increased that trouble me!")
is org verse 2, and the whole rest of the chapter is shifted by one. Six
standard schemas are supported: `org` (original Hebrew/Greek), `eng`
(English/Protestant), `rsc`/`rso` (Russian Synodal canonical/Orthodox),
`vul` (Vulgate/Catholic), `lxx` (Septuagint/Orthodox) — the same six
`versification.py` itself defines, sourced from real Paratext/Copenhagen
Alliance mapping tables, not invented by Bridge.

**This is vendored, unpublished third-party code, like the USFM checker —
but integrated differently, not by copying that precedent blindly.**
Confirmed freshly this session (not assumed from the USFM checker's
already-established facts): still not on PyPI; still BSD-3-Clause code from
the same pinned commit `18ddcf0e6c03fa2774b73b21186115d712e4cba9`. But two
things turned out to be genuinely different, found only by reading the
source and running it against real data:

1. **`versification.py` is a real library, not a CLI script.**
   `BibleStructure`, `Versification`, `VersifiedCorpus`,
   `VersificationMatch`, and `BackVersification` are classes with methods
   that operate on in-memory dicts — unlike `usfm_check.py`'s 4,000 lines
   with no reusable functions. So this is **imported directly into the
   long-lived `bridge-engine` process**, not run as a subprocess/helper
   executable. `tc_ai_bridge/versification.py` builds `VersifiedCorpus`
   objects straight from Bridge's own already-parsed chapter/verse text
   (`TranslationCoreProject.verses()`/`target_verse_text()`) — it never
   calls the vendored tool's file-based `load_corpus`/`write_corpus`/`main()`
   entry points at all.
2. **The mapping data carries a different license than the code around
   it.** `data/standard_mappings/*.json` originates from the Copenhagen
   Alliance Versification Working Group, not greek-room itself, and that
   project's own `LICENSE.md` splits code (Apache 2.0) from **data (CC
   BY-SA 4.0 — attribution + share-alike)**. Bridge's own root license is
   GPLv3 (already copyleft), which makes bundling attributed, unmodified CC
   BY-SA 4.0 reference data low-risk — but this was a real, separate
   decision, not a rubber-stamp of the USFM checker's BSD-3-Clause-only
   precedent. See `engine/vendor/greekroom-versification/NOTICE.md` for the
   full reasoning; re-review if these JSON files are ever modified before
   redistribution.

**Two real bugs found by actually running the vendored code against real
data** (documented in full in that directory's `NOTICE.md`, including how
each was reproduced):

- `Versification.load_versifications()` keeps **class-level** state
  (`Versification.versification_d`, `Versification.org`) that is never
  reset. A second real call in the same process — exactly what a naive
  per-project-open call from a long-lived `bridge-engine.exe` would do —
  hits a duplicate-schema branch, logs an error, and returns a
  half-constructed object with no `verse_id_list`; the very next line then
  crashes with `AttributeError`. Reproduced directly by calling it twice,
  not assumed from the USFM checker's own gotchas. Fixed in Bridge's
  wrapper by loading exactly once per process (lock + flag guard) —
  nothing outside `tc_ai_bridge/versification.py` should import the
  vendored `versification` module or call `load_versifications()` directly.
- `VersifiedCorpus.load_corpus()`/`write_corpus()` (and `main()`'s other
  file opens) use bare `open()` with no explicit encoding, which reproduces
  the exact same Windows `cp1252` `UnicodeDecodeError` already found and
  patched in `usfm_check.py`, confirmed here with a real Tamil string. **Not
  patched**, unlike the USFM checker's two `# BRIDGE PATCH` markers — Bridge's
  usage never calls those file-based methods (point 1 above), so this bug is
  architecturally avoided rather than fixed. If anything ever calls
  `load_corpus`/`write_corpus`/`main()` directly, patch it the same way.
- `vref.txt` (390 KB) and `psalm-descriptive-titles.txt` were deliberately
  **not** vendored: verified by reading the source that neither is read by
  any of the five classes Bridge actually calls, only by the CLI `main()`
  Bridge never invokes.

**Protocol methods** (all whole-book-scoped, cached per project path like
the USFM findings, computed lazily on first request rather than on every
`project.open`):

- `versification.detect` — sniffs the best-fitting schema for the open
  project's book against all six standard schemas and returns every
  schema's match cost, not just a bare label, so a caller can show how
  confident the detection is.
- `versification.orgRef` — normalizes one chapter:verse into its `org`
  equivalent (defaulting to the project's own detected schema). Returns a
  `mapping` field — `same` / `mapped` / `merge` / `split` — because
  cross-tradition shifts aren't always 1:1; callers should branch on that
  field rather than parsing `orgRef` as free text.
- `versification.backVersificationMap` — the inverse: every `org` verse in
  the book mapped back to the project's own numbering, for display/export
  use without hand-rolling the mapping direction.

**Verified**: `engine/tests/test_versification.py` (22 tests against the
real vendored data — including the Psalm 3 shift and its back-versification
round trip, real merge/split mappings, unknown books, USFM verse
bridges/segments passed straight through, and a direct real-bug-reproduction
test that calls the module's public functions twice in a row to confirm the
class-level-state crash found above stays fixed) plus protocol-level
coverage in `test_bridge_service.py` (a Ruth fixture proving identity
mapping for a fully-canonical book, and a dedicated Psalms fixture proving
the real cross-tradition shift flows end-to-end through `handle_request`).
Full source suite: 122 passed.

**Concurrency — a second real bug found, this time by writing concurrency
edge case tests rather than by reading the source.** `detect_schema()`'s
scan over a schema's full verse list is pure Python and ~0.5s
single-threaded — but running several of those scans on different threads
*at once* doesn't scale proportionally under CPython's GIL, it degrades
catastrophically: measured directly at 16 concurrent callers taking **~47
seconds each** (not the ~8s naive linear scaling predicts — over 90x worse
than sequential). Reproduced with a genuinely fresh subprocess and
fine-grained per-thread timing, not assumed from general GIL folklore.
Since `bridge_service.py` calls this once per book on first request and
caches the result, the realistic trigger is a burst of near-simultaneous
`versification.detect` calls before any of those caches are warm — which
would look exactly like the sidecar hanging. Fixed by serializing the scan
with the same lock `_ensure_loaded()` already uses; the identical 16-thread
scenario then completes in ~8s total. `to_org_ref`/`back_versification_map`
do plain dict lookups (not this scan) and were separately measured safe
unlocked under the same concurrency — this isn't a "lock everything"
fix, and don't assume it's free insurance for code added to this module
later without re-measuring. Guarded by `test_versification_concurrency.py`,
which deterministically instruments the expensive matcher boundary and
asserts that concurrent callers never overlap there. Full details in
`engine/vendor/greekroom-versification/NOTICE.md`'s finding 4.

**Packaging — a real gap found and fixed, not assumed to be handled by
precedent**: because this is imported directly into `bridge-engine.exe`
rather than run as a separate helper (unlike the USFM checker), the
vendored `versification.py` + `data/` tree and its one third-party
dependency (`regex`) are invisible to PyInstaller's static import analysis
— `main.py` never imports them directly; `tc_ai_bridge/versification.py`
only reaches them via a runtime `sys.path.insert` + `import`. Left alone,
a frozen build would have shipped with `versification.detect` crashing on
first use. Fixed in `bridge-engine.spec`: `datas` now includes
`vendor/greekroom-versification`, extracted under `sys._MEIPASS` in a
frozen build (`tc_ai_bridge/versification.py`'s `_vendor_root()` resolves
the same way `resource_materializer.bundled_resources_source()` already
does), and `hiddenimports` now includes `regex`. **Verified against a real
PyInstaller build this session**, not left as an assumption: built
`bridge-engine.exe` from the updated spec, ran it as a real subprocess over
its stdio JSON-RPC protocol, and confirmed `versification.detect`/`orgRef`/
`backVersificationMap` all return correct real results (including the
Psalm 3 shift) from inside the genuinely frozen executable. The existing
`scripts/smoke_sidecars.py` frozen-sidecar smoke test also still passes
against the rebuilt executable.

**Not done in this pass**: no UI surfaces any of this yet (no schema
indicator, no dual-reference display, no export-time renumbering) — matching
how the USFM checker itself shipped as backend/protocol-only. `versification
.detect`'s result isn't wired into the findings feed as an informational
notice; it's exposed as project metadata a future UI can call on demand,
not injected automatically. Per-book detection results are cached only for
the lifetime of the process/current project (same lifetime as the USFM
findings cache), not persisted to disk.

### Names & Transliteration — Phase 5 complete (2026-08-21)

This section originally recorded a research breadcrumb (nothing wired up,
just an investigation of whether Uroman and Smart Edit Distance were even
real, installable dependencies). That work is now done — a whole-book
names/spelling-consistency check is wired into the protocol, tested against
both source and a real frozen build. The original research findings below
are kept as-is (still accurate, still worth reading for *why* things are
built the way they are); the "What was actually built" subsection further
down covers the implementation, the two real bugs found while building it,
and what's verified. **Verify all of this again before relying on it** —
same standing instruction as everywhere else in this doc.

**Uroman is a real, currently installable PyPI dependency — it does not
follow the Wildebeest name-trap pattern.** `pip install uroman` installs
the genuine package by Ulf Hermjakob, USC/ISI (same research group as
Wildebeest and the vendored `greek-room` tools), current release
`1.3.1.1`, `Requires-Python: >=3.10`, one real dependency
(`regex>=2024.5.15`, compatible with the `regex>=2023.10.3` floor already
in `engine/pyproject.toml` for the USFM checker). Confirmed by actually
installing it and reading the wheel's own METADATA — not assumed from the
package name alone, per this project's standing rule.

- **API, verified by direct use, not docs**: `uroman.Uroman()` is the
  entry point. Construction loads the full romanization table set — real
  measured cost on this machine was **1.8-2.1 seconds** — after which
  `romanize_string(s, lcode=...)` calls measured effectively instant
  (0.0000s) on repeat calls, confirmed by timing both a first and second
  call. This is a real, substantial cost that validates
  `docs/ARCHITECTURE.md`'s "loaded once, not per call, per Uroman's own
  documented recommendation" line — that line was written before anyone
  had actually read Uroman's docs or run the code; it's now confirmed true
  for a concrete, non-hypothetical reason (a multi-second table load), not
  rubber-stamped.
- **Data**: ships ~4.2 MB of real resource files inside the wheel itself
  (`UnicodeData.txt` at 1.9 MB, `romanization-auto-table.txt` at ~1 MB,
  `Chinese_to_Pinyin.txt`, `Scripts.txt`, etc. — 13 files total), resolved
  at runtime via `Path(__file__).parent / "data"` (confirmed by reading
  `Uroman.default_data_dir()`'s source directly). This is the same shape
  of packaging risk already flagged as unverified insurance for
  `wildebeest-nlp`'s own `data/` directory in the Real Wildebeest section
  above, and the same shape of problem versification's vendor tree solved
  with `bridge-engine.spec`'s `datas` entry — **not yet tested against a
  frozen PyInstaller build this session**; treat as a real open item, not
  a formality, before shipping.
- **Verified against real cross-script Biblical name data on Windows**,
  not synthetic strings: Hindi/Urdu/English "Nepal" (नेपाल → `nepaal`,
  نیپال → `nipal`, matching Uroman's own paper example exactly), Greek
  Ἰωάννης → `Ioannes`, Tamil யோவான் → `yoovaan`, Arabic محمد → `mhmd`,
  Hebrew יוֹחָנָן → `yochanan`. No network access was used or required —
  entirely offline, matching Bridge's own connectivity requirement.
- **License — real, confirmed drift, same shape of bug as the
  `greekroom` package's Apache/BSD classifier mismatch already recorded
  above, not a new problem shape.** Both the published wheel's METADATA
  *and* upstream's own `pyproject.toml` on GitHub classify the license as
  `"License :: OSI Approved :: Apache Software License"`. The actual
  bundled `LICENSE.txt` (confirmed identical between the PyPI wheel and
  upstream's GitHub `LICENSE.txt`, so this is an upstream authoring
  mistake, not a wheel-build artifact) is **not Apache 2.0 text at all** —
  it's a custom MIT-style permissive license with a mandatory attribution
  clause: *"Any publication of projects using uroman shall acknowledge its
  use: 'This project uses the universal romanizer software "uroman"
  written by Ulf Hermjakob, USC Information Sciences Institute
  (2015-2020)'."* This confirms `docs/ARCHITECTURE.md`'s previously
  unverified "Uroman has its own attribution requirement" note was right,
  but for a more specific reason than assumed — it isn't an extra clause
  layered on top of Apache 2.0, the Apache classifier itself is simply
  wrong. Bridge will need to surface that exact acknowledgment string
  somewhere real (an about screen, a NOTICE.md, export metadata), not just
  bundle a copy of the license file.

**Smart Edit Distance (SED) is not a separately published tool and not
part of a different repo — it lives in the same pinned `BibleNLP/greek-room`
commit (`18ddcf0e6c03fa2774b73b21186115d712e4cba9`) already vendored for
the USFM checker and versification**, at
`smart_edit_distance/src/smart_edit_distance.py` plus
`smart_edit_distance/data/string-distance-cost-rules.txt` (general rules)
and a second Devanagari-specific cost file. Confirmed not on PyPI under
`smart-edit-distance`, `smart_edit_distance`, or inside the published
`greekroom` PyPI package (`0.0.20`, which — per the USFM checker's own
established precedent — only ships `owl`/`gr_utilities`, not this). Same
integration shape as the USFM checker and versification: unpublished,
vendor it from the pinned commit, don't wait on upstream packaging.

- **Shape: closer to versification.py than to usfm_check.py.** It's a
  single ~430-line file, pure Python standard library only (`argparse`,
  `logging`, `re`, `sys`, `typing` — zero third-party imports, and no
  import of Uroman itself despite the module's own docstring describing
  the two as complementary). A `SmartEditDistance` class holds
  per-instance state (`self.ht`, `self.max1`/`self.max2`, etc.) — no
  class-level shared state like the real bug found in
  `Versification.load_versifications()`, so the same second-call crash
  class of bug doesn't reproduce here (checked directly by instantiating
  it twice). This argues for a direct import into the long-lived
  `bridge-engine` process, the same way `versification.py` was integrated,
  not a subprocess/helper executable like the USFM checker.
- **License: plain BSD-3-Clause, same as the repo root — no hidden
  second license this time.** Checked directly because versification's
  CC BY-SA data-license surprise means this can no longer be assumed;
  this time there wasn't one. The cost-rule `.txt` data files carry no
  separate license notice of their own.
- **Real bug found by actually running it against the real data file —
  the third confirmed instance of the exact same bug class this project
  keeps finding in every one of these vendored/adjacent tools.**
  `SmartEditDistance.load_smart_edit_distance_data()` calls bare
  `open(raw_cost_file)` with no explicit encoding when given a string
  path. The real `string-distance-cost-rules.txt` contains 117 non-ASCII
  bytes (confirmed by reading it as raw bytes, not assumed from the
  filename). Loading it under this machine's default Windows locale
  (`cp1252`) throws `UnicodeDecodeError: 'charmap' codec can't decode byte
  0x90 in position 3802: character maps to <undefined>` — reproduced live,
  not inferred. Needs the same explicit `encoding="utf-8"` fix already
  applied to `usfm_check.py` (2 call sites) and identified-but-architecturally-
  avoided in `versification.py`'s file-based methods.
- **Functional verification, combined with real Uroman output, not
  hypothetical pairs**: loaded the real cost-rules file (417 entries / 834
  compiled rules) and ran `string_distance_cost()` on name pairs. Results
  matched the module's own docstring examples exactly: `"Josef Schumann"`
  vs `"Joseph Schuman"` scored **0.03** (plain Levenshtein: 3),
  `"Muhammad"` vs `"Mohamed"` scored **0.22** (plain Levenshtein: 3),
  `"Jim"` vs `"Kim"` correctly stayed at the default substitution cost of
  **1.0** (matching the docstring's own claim that these should read as
  more different than the phonetic-variant pairs above). A live
  cross-script test combining both tools — Tamil யோவான் (uroman:
  `yoovaan`) vs English `"John"` — scored **1.52**, correctly landing
  between "same word, different spelling convention" and "unrelated
  strings." This is the first time in this session anything actually
  chained Uroman's output into SED's cost function, not just tested each
  tool in isolation.

The above was investigation only when first written — nothing was built
yet, deliberately, until the real shape of both dependencies was confirmed.
Everything below this point was added afterward, once the user confirmed
the check's actual design.

#### What was actually built

**Design decision, made explicitly with the user before writing any code**:
of three options presented (a general whole-book phonetic spelling check; a
translationWords-names-anchored consistency check requiring a new,
unproven candidate-extraction heuristic; or infrastructure-only with no
check at all), the user chose the general whole-book check. It compares
every pair of distinct target-language word types used in the open book
and flags pairs whose *romanized* forms are suspiciously close (low Smart
Edit Distance cost) but not identical. It never claims two spellings are
the same name or that either is wrong — only that they're objectively
close — keeping it on the "Greek Room says: this is objectively
suspicious" side of the architecture doc's three-way design boundary. The
names-anchored alternative was explicitly rejected as riskier: it would
have required guessing which target word renders a given name from
translationWords occurrence data alone (no word alignment exists for most
verses), a real semantic claim Greek Room has no reliable way to verify.

**Vendored**: `engine/vendor/greekroom-smart-edit-distance/` — pinned to
the exact same `BibleNLP/greek-room` commit already used for the USFM
checker and versification (`18ddcf0e6c03fa2774b73b21186115d712e4cba9`).
Confirmed via the GitHub API tree listing that `smart_edit_distance.py`
plus two cost-rule data files are the *entire* contents of that directory
at this commit. See that directory's `NOTICE.md` for full provenance.
`uroman>=1.3.1.1` was added as a real, hard dependency in
`engine/pyproject.toml` (not optional/mock-fallback like Wildebeest — it
has no known installability problem on any currently supported Python
version). `regex`'s floor was raised from `>=2023.10.3` to `>=2024.5.15`
to satisfy uroman's own requirement — same package, no real conflict.

**New code**: `engine/greek_room_engine/adapters/names_adapter.py`
(`NamesAdapter`, registered in `GreekRoomEngine`), a new
`GreekRoomEngine.check_book_names()` method mirroring
`check_book_usfm()`'s shape, and `BridgeEngine._names_findings_for_book()`
in `bridge_service.py` mirroring `_usfm_findings_for_book()` — same
whole-book caching-per-project-path pattern, same cache-clearing on
`project.open`/`project.import`, same stable-id treatment (here keyed on
the two spellings being compared, sorted, so decisions survive repeat
runs regardless of which spelling a given run happens to treat as
"majority"). Wired into `run_verse_checks` behind `"local" in checks or
"names" in checks` — the exact same gating shape as the USFM checker —
which is why **no frontend change was needed**: `App.svelte` and
`ReviewPanel.svelte` already always send `checks: ["local", "greekroom"]`.

**Two real bugs found by actually running this against real data, not by
reading the source**, on top of the encoding bug already found and
documented (architecturally avoided, not patched) during the research
phase and recorded in the vendor directory's `NOTICE.md`:

1. **A real false-positive class**: testing against plain English
   "church"/"churches" — an ordinary, correctly-spelled singular/plural
   pair, not a spelling inconsistency — scored **0.70** under the general
   cost-rules file, because rules tuned for name-like variation (dropped
   vowels, consonant doubling) also happen to cover common inflectional
   endings. The vendored module's own docstring frames its "Jim"/"Kim"
   example (cost 1.0) as meaningfully different, which suggested a
   threshold just under 1.0 — but 1.0 alone isn't a safe ceiling. The
   threshold (`_MAX_COST` in `names_adapter.py`) was tuned down to **0.4**,
   the highest value that still keeps every real phonetic-variant pair
   found this session (Josef Schumann/Joseph Schuman = 0.03, Muhammad/
   Mohamed = 0.22, a synthetic Titus/Tituss typo = 0.02, Yohaan/Yohan =
   0.02) while excluding the church/churches false positive. This is an
   inherent limitation of an edit-distance-family metric applied to
   morphologically rich languages, not something a threshold alone fully
   solves — expect some inflectional false positives to still surface near
   this ceiling; the human reviewer is the actual filter, per this
   adapter's own design-boundary docstring.
2. **A real, serious performance bug**: the first working version pruned
   comparison candidates by length-bucket only (only compare romanized
   forms within a couple of characters of each other in length). Measured
   directly against a synthetic ~3000-distinct-word-type vocabulary (a
   plausible single-book size): **133 seconds**. Length-bucket pruning
   alone still leaves well over a million length-compatible pairs, and
   each `string_distance_cost` call is a non-trivial DP. Fixed with
   character-bigram "blocking" (`NamesAdapter._candidate_pairs`), a
   standard approximate record-linkage technique: a real near-duplicate
   pair (1-2 edits) shares almost all of its bigrams, so requiring most
   bigrams to overlap before ever calling the expensive comparison throws
   away the overwhelming majority of unrelated pairs cheaply first.
   Measured result on the same 3000-token benchmark: **5.5 seconds** (a
   ~24x improvement). An 8000-token benchmark (worse than most single
   books) took 27.9s — still tolerable for a backgrounded preflight job
   (the same job shape already tolerates the USFM checker's 120s subprocess
   timeout), but scaling is worse than linear with the current blocking
   parameters (`_MAX_BIGRAM_MISMATCH`, `_MAX_BIGRAM_BUCKET` in
   `names_adapter.py`) — a real area for future tuning if a genuinely huge
   single-book vocabulary turns out to need it, not claimed as fully solved.
   Both benchmarks used adversarial uniformly-random letter strings (worst
   case for bigram blocking, since real language text has far more skewed
   bigram frequency); real target-language vocabulary should perform at
   least as well.

**Known, deliberately unaddressed limitations** (documented rather than
silently absent, matching this project's own established practice):
whole-book in-process comparison has no mid-flight cancellation support
(unlike the USFM checker's subprocess, which the check-job preflight can
terminate) — acceptable given the measured timings above, revisit if real
usage shows otherwise. The Devanagari-specific supplementary cost-rules
file is vendored but not loaded (see the vendor directory's `NOTICE.md`).
No UI surfaces this beyond the existing findings list — same as how the
USFM checker and versification both shipped backend/protocol-only.

**Verified**:
- `engine/greek_room_engine/tests/test_names_adapter.py` (9 tests) — real
  uroman + real vendored SED, no mocks: a planted typo gets flagged and
  anchored at its own occurrence; the real Muhammad/Mohamed cost (0.22) is
  asserted exactly, not just "some finding exists"; the church/churches
  false-positive class and the vendored module's own Jim/Kim example are
  both asserted to NOT be flagged; a bigram-blocking performance regression
  guard.
- `engine/tests/test_names_check.py` (6 tests) — protocol-level, through
  `BridgeEngine.handle_request`: a real finding surfaces via
  `verse.runChecks` with `checks: ["names"]`, is correctly absent when
  "names" isn't requested, has a stable id across a fresh `BridgeEngine`
  instance (simulating an app restart), is listed as `usingRealEngine` in
  `engine.info`, doesn't leak across a `project.open` switch to a different
  project, and — importantly, since every other test above this one only
  exercised English, where Uroman's romanization step is close to a no-op
  — a real Tamil case through full verse sentences (not isolated words):
  an inconsistently included/omitted long-a vowel sign on the same name
  ("யோவான்" vs "யோவன்") is correctly flagged, exercising
  `whitespace_tokens`' real combining-mark/punctuation handling on actual
  target-language text, not bypassing it with synthetic tokens. Bridge's
  real target languages are mostly non-Latin, so this was worth confirming
  before treating the check as done, not just a nice-to-have extra test.
- Full source suite: **137 passed** (122 before this phase + 15 new).
  `npm run check` still reports 0 errors/0 warnings (no frontend files
  touched).
- **Frozen build, verified this session** (not left as an open item like
  Wildebeest's packaging was): built both sidecars via
  `scripts/build-sidecars.ps1` against the updated
  `engine/bridge-engine.spec` (now also bundling
  `vendor/greekroom-smart-edit-distance` and uroman's data files via
  `collect_data_files('uroman')`, the same `sys._MEIPASS` extraction
  pattern versification's vendor tree already uses). Ran the real frozen
  `bridge-engine.exe` as an actual subprocess over its stdio JSON-RPC
  protocol with a real planted "Tituss"/"Titus" typo: `engine.info`
  reports `usingRealEngine: true` for the `names` adapter, and
  `verse.runChecks` returned the correct real finding
  (`original_text: "Tituss"`, `suggested_replacement: "Titus"`, cost
  `0.02`) — confirming uroman's ~4.2MB bundled data directory and the
  vendored SED tree both actually resolve correctly under `sys._MEIPASS`
  in a genuinely frozen executable, not just in source mode. This had been
  explicitly flagged as unverified in the original research breadcrumb;
  it no longer is.

### Alignment corpus statistics — Phase 6 complete (2026-08-24)

**Investigation first, same discipline as every prior phase.** "UAlign" was
an unresearched name in the roadmap, same as Uroman/SED were before Phase 5.
The first, false lead: `ualign_utilities.py` already sits vendored in two
places (`engine/vendor/greekroom-usfm/` and
`engine/vendor/greekroom-versification/greekroom/usfm/`) and looked, from
the name alone, like it might already be the statistics engine. Reading it
showed otherwise — it's a small set of generic Bible-reference/HTML utility
classes (`BibleUtilities`, `BibleRefSpan`, `ScriptDirection`, ...) already
actively imported by `usfm_check.py` and `versification.py`, not dead
weight and not UAlign itself. Its own docstring pointed at the real answer:
"utilities, taken from script `ualign.py`."

Pulling the pinned `BibleNLP/greek-room` commit's full GitHub tree (no `gh`
CLI on this machine — used the raw GitHub API and
`raw.githubusercontent.com` directly instead) found `utilities/ualign.py`:
a real, 3,598-line, unpublished script at the same pinned commit
(`18ddcf0e6c03fa2774b73b21186115d712e4cba9`) already vendored three times
for the USFM checker, versification, and Smart Edit Distance. Confirmed not
on PyPI under any plausible name and outside the published `greekroom`
package (`0.0.20`, which — per the USFM checker's own established
precedent — only ships `owl`/`gr_utilities`). Its `AlignmentModel` class
computes exactly the statistics ARCHITECTURE.md's own non-goal section
names ("local statistical recomputation — fertility, PMI, frequency"):
bilingual co-occurrence counts, per-word fertility distributions, joint
counts, and a Smart-Edit-Distance-boosted translation probability. Its own
docs page (`site/content/en/align.md`) independently confirms the same
statistic vocabulary (count, probability, joint count, phonetic/SED score)
in the context of a word-alignment *visualization* tool.

**Decision: reimplement the statistics against Bridge's own data, don't
vendor `ualign.py`.** Its actual I/O contract is built for a
`fast_align`-style pipeline — Pharaoh-format alignment files, `"e ||| f |||
ref"` triple-pipe parallel-text files, before/after ttable model files —
plus it bundles HTML visualization, morphology-variant checking, and a
spell-checker Bridge doesn't want. None of that matches tC's own
`alignmentData/<book>/<chapter>.json` shape or Bridge's in-memory
`VerseAlignment`/`TokenRef` objects. Vendoring it and subprocessing it like
`usfm_check.py` would mean synthesizing fake files in its exact expected
format just to extract a few numbers back out of HTML/log output designed
for a different UI. License-wise this also sidesteps the one real
entanglement risk `ualign.py`'s usage comment references — an external,
separately-licensed `fast_align` binary to produce an initial alignment —
since Bridge already has human-approved alignments as input and never needs
to run an aligner from scratch. The formulas below mirror `ualign.py`'s own
`AlignmentModel.support_probability()` (verified by reading that method
directly) but are original, small, textbook implementations, not copied
code — no new vendor license obligation beyond the SED tree already
vendored and licensed for Phase 5.

**A related false lead worth recording**: `tc_ai_bridge/
alignment_reliability.py` already exists and sounds on-topic, but it's
AI-link-proposal compilation (confidence thresholds, protected-group
merging for Phase 7's AI alignment suggestions), not corpus statistics —
real evidence Phase 7 already has scaffolding, and further reason to keep
this phase scoped to statistics only. That scope split (statistics this
session, AI proposals deferred to Phase 7) was decided explicitly with the
user before any code was written, matching ARCHITECTURE.md's v0.9.x
roadmap line which had bundled both under one entry.

**What was built**: `engine/tc_ai_bridge/alignment_statistics.py`
(`build_corpus_stats()`, `CorpusStatsTable`, `CorpusPairStats`) plus two new
`bridge_service.py` protocol methods, `alignment.corpusStats.summary` and
`alignment.corpusStats.forVerse`. Scans every verse marked complete — tC's
own `tools/wordAlignment/completed/<chapter>/<verse>.json` markers, the
same signal `alignment.complete` writes via `mark_word_alignment_completed`
— across the open book, plus (by default) every already-normalized sibling
book in the same multi-book collection (`.bridge/collection.json`); a
sibling still marked lazy is skipped rather than force-materialized just to
compute statistics. The scan reads only chapters that actually contain a
completed-verse marker, and reads each such chapter's alignment JSON
exactly once regardless of how many completed verses it holds — the real
cost driver is completed verses, not the project's total verse count,
which matters for a whole-Bible-sized collection where most verses are
never touched by manual alignment. `corpusStats.forVerse` returns, for
every top↔bottom link in one verse's *current* alignment groups (it does
not need to be complete itself): joint count, source/target counts,
translation probability, PMI, and — when Uroman and the vendored SED are
both available — a romanized SED cost and phonetic-boosted probability for
sparse pairs. PMI is reimplemented directly in the new module (the same
standard formula also sitting unused in vendored `ualign_utilities.py`,
not imported from it, to avoid coupling this module to
`versification.py`'s vendor-path/sys.path lifecycle for two lines of math
with no vendor-specific tuning). The SED-boost path reuses the exact same
vendored Smart Edit Distance tree and loading pattern already established
in `names_adapter.py`, plus its own separate lazy Uroman singleton — a
deliberate, documented tradeoff: sharing Uroman's singleton across the
`greek_room_engine`/`tc_ai_bridge` layers would need a real refactor of
already-shipped, tested Phase 5 code, out of scope here, so a session using
both the names check and corpus stats pays Uroman's one-time ~1.8-2.1s
table load twice rather than once.

Caching mirrors the USFM/versification/names pattern (per project path,
cleared on `project.open`) but goes one step further: it's *also*
invalidated by every alignment-mutating call (`realign`/`unalign`/`save`/
`complete`/`undo`) for the currently open book, rather than only on the
next project reopen — cheap enough (a linear scan over already-completed
verses, not a subprocess or whole-book vocabulary comparison) that keeping
it fresh on every mutation was worth it.

**Measured, not guessed, per this project's own standing rule**: a
synthetic but realistically-shaped 2,000-completed-verse corpus (50
chapters × 40 verses × 6 token pairs, comparable to a heavily-aligned large
book) scanned in well under a second of real compute — the entire pytest
process for that one test, including Python startup, was 2.42s. This is
genuinely CPU-only, zero AI/API cost: no LLM tokens, no network calls, just
counting already-known token pairs from alignment JSON already on disk
plus a few arithmetic formulas over those counts.

**Verified**: `engine/tests/test_alignment_statistics.py` (7 new tests, no
mocks) — completed-only filtering (an incomplete sibling verse is excluded),
hand-computed PMI/probability values checked against the formula directly,
multi-book aggregation with a real lazy-sibling skip, protocol-level
`summary`/`forVerse` calls through `BridgeEngine.handle_request`, cache
invalidation when a verse is newly marked complete, a real (not mocked)
Uroman + vendored-SED case (a Greek name romanizing to "Ioannes" paired
against a target spelling romanizing to "Ioanes" scores a real SED cost of
0.02 and a boosted probability at or above the plain co-occurrence
probability — and, checked separately, not every cross-script "same name"
pair clears SED's `max_cost=1` ceiling: Ἰωάννης/"Ioannes" against Tamil
யோவான்/"yoovaan" — the exact real romanization pair from Phase 5's own
investigation — scores no cost at all, handled by the None/None graceful
fallback, which is expected: SED is tuned for near-duplicate spellings, not
open transliteration variance), and the 2,000-verse performance measurement
above. Full source suite: **144 passed** (137 + 7 new), plus the one
pre-existing, load-sensitive `test_versification_concurrency.py` failure
noted at the top of this document — confirmed unrelated to this phase's
changes, reproducible on unmodified `main`.

**Frozen build, verified this session (2026-08-24)**: no new PyInstaller
`datas`/`hiddenimports` entries were needed — this module reuses the
`vendor/greekroom-smart-edit-distance` tree and `uroman` data files already
bundled for Phase 5 — but "expected to work" was checked rather than
assumed. `scripts/smoke_sidecars.py` was extended to call
`alignment.corpusStats.summary`/`forVerse` immediately after its existing
`alignment.complete` step (the fixture verse's realigned single group is
still complete at that point, before the script's own `alignment.undo`
call). Ran the real frozen `bridge-engine.exe` as an actual subprocess over
its stdio JSON-RPC protocol: `corpusStats.summary` correctly reported
`versesScanned: 1`, and `corpusStats.forVerse` returned a real
`jointCount: 1`/`translationProbability: 1.0` pair for the completed
verse's own link. `bridge-engine.spec` needed no changes for this.

**Not done in this pass**: no UI surfaces this yet (no reliability
color-coding in the alignment editor, no corpus-stats panel) — matching how
the USFM checker, versification, and the names check all shipped their
first pass backend/protocol-only. No QaFinding output — this phase was
scoped to data only, per the explicit choice made with the user; a future
phase could flag statistically-outlier links in already-completed
alignments, the same way Phase 5's names check flags outlier spellings, but
that needs its own threshold-tuning investigation against real data, the
same way Phase 5's 0.4 cost ceiling was tuned rather than guessed. All
testing so far — this phase and every prior one — uses small, hand-written
synthetic fixtures (a handful of made-up words per test), not a real
published translation at any real scale (e.g. a real Tamil IRV-sized
corpus); real tools (Uroman, SED) have been verified against real
individual words/names, but never against a large real corpus's actual
statistical distribution. That's a real gap worth closing before trusting
these statistics' *usefulness* (as opposed to their correctness) on an
actual translation project, not yet attempted.

### AI alignment proposals and drag-and-drop import — Phase 7, part 1 (2026-08-24)

A prior session's investigation (recorded in the previous revision of this
section) found that `tc_ai_bridge/ai_client.py`'s `propose_alignment()` and
`tc_ai_bridge/alignment_reliability.py`'s `compile_link_proposal()` were
already real, complete implementations from Phases 1-3 — deterministic
confidence thresholds, protected/locked existing-group handling, connected-
component group compilation — with **zero test coverage anywhere in the repo**
and no protocol method calling either one. This session verified that was
still true (`grep -rl "OpenAIResponsesClient\|compile_link_proposal"
--include=*.py` outside `tc_ai_bridge/` matched only `bridge_service.py`'s
unrelated `structural_issues` import), then wired and tested it, and
separately wired drag-and-drop import. The user was asked explicitly which
Phase 7 slice(s) to prioritize (see the AskUserQuestion in this session);
AI explain and the live Paratext/Logos connectors were deliberately not
attempted — see their own subsections below for the real, confirmed
blockers.

**AI alignment proposals — new protocol methods, `alignment.aiPropose` and
`alignment.aiApplyProposal`, in `bridge_service.py`.** Deliberately two
separate calls, not one: `aiPropose` is read-only (asks AI for individual
token links, then `compile_link_proposal` compiles them deterministically
into legal tC groups) and writes nothing to project files; `aiApplyProposal`
is a separate, explicit, human-triggered step. This keeps AI alignment on
the same "nothing auto-applies without human approval" side of
`docs/ARCHITECTURE.md`'s three-way design boundary as every other Greek
Room/AI feature in Bridge.

- `BridgeEngine.__init__` gained an `ai_transport: Optional[Transport] = None`
  parameter — the same `Callable[[url, headers, body, timeout], (status,
  bytes)]` shape `ai_client.OpenAIResponsesClient` already accepted,
  threaded one level up so `propose_ai_alignment()` can be unit-tested with
  a fake HTTP transport instead of a real OpenAI-compatible API key. This is
  exactly the dependency-injection pattern the previous session's
  investigation flagged as the way to test this without live network
  access. Production code paths still pass `None`, meaning "use the real
  network" (`ai_client.default_transport`).
- `apply_ai_alignment_proposal()` reuses the *exact* identity-checked save
  pipeline manual realign/save already goes through (`_save_alignment`,
  including `validate_preparation_proposal`'s defense-in-depth check that an
  AI proposal cannot detach/remap an already-established group, on top of
  `compile_link_proposal`'s own protection) — an AI-sourced edit gets no
  more trust than a manual one.
- `propose_ai_alignment()`'s returned `proposal` object keeps
  `compile_link_proposal`'s own snake_case field names
  (`top_ids`/`bottom_ids`/`requires_human_review`/...) verbatim, breaking
  this file's usual camelCase protocol convention on purpose: the object
  must round-trip byte-for-byte from `aiPropose`'s response back into
  `aiApplyProposal`'s request body, which calls `alignment_engine.
  apply_proposal()` expecting those exact keys. Re-keying it in either
  direction would risk a lossy/asymmetric conversion for no real benefit,
  since the frontend only needs to read `top_ids`/`bottom_ids` generically
  to resolve token labels — the same way `AlignmentModal.svelte` already
  does for ordinary alignment groups. See the comment at the return
  statement in `propose_ai_alignment()` for the same rationale inline.
- `settings.record_ai_usage()` (`tc_ai_bridge/secret_store.py`) was itself
  real, already-implemented, dead code before this session — nothing called
  it, confirmed by grepping the whole `engine/` tree. `alignment.aiPropose`
  is now its first real caller, so `settings.get`'s `aiUsage` total actually
  accumulates real token/cost data instead of always reading zero.
- Rust: `alignment_ai_propose`/`alignment_ai_apply_proposal` commands added
  to `commands.rs` and registered in `main.rs`'s `generate_handler!`, the
  same thin-wrapper shape as every other alignment command.
  `sidecar.rs`'s per-method timeout table gained
  `"alignment.aiPropose" => 260` — `ai_client.py`'s own HTTP timeout is 240s
  with retries, so the default 30s interactive timeout would have made the
  UI report "timed out" while the sidecar was still legitimately waiting on
  a real model call. This one call is a direct blocking request (like
  `verse.runChecks`'s existing 150s), not routed through the `checks.start`
  background-job system — consistent with that method's own precedent for a
  single-verse operation, and simpler than building job-tracking for what
  is, from the UI's perspective, one blocking button press.
- Frontend: `AlignmentModal.svelte` gained an "Ask AI to propose alignment"
  button next to the existing manual align/unalign controls, and a
  preview panel for the returned proposal — shows only the non-`existing`
  groups (what would actually change), a `requires_human_review` warning
  banner summarizing conflict/uncertain-link/target-only counts when
  present, and explicit "Apply proposal & save" / "Discard proposal"
  buttons. Applying reuses the same `refreshChecks()` path (re-run
  local+Greek Room checks, update stores) every other alignment mutation in
  this component already uses. `bridgeClient.ts` gained
  `aiProposeAlignment`/`aiApplyAlignmentProposal`, and `types/finding.ts`
  gained `AlignmentAiProposal`/`AlignmentAiProposeResponse` (documented
  inline with the same snake_case rationale as above).

**Verified**: `engine/tests/test_ai_alignment_propose.py` (4 new tests, real
`compile_link_proposal`/`apply_proposal` logic exercised through
`BridgeEngine.handle_request` with a fake transport, no mocks of Bridge's
own code) — `alignment.aiPropose` fails with a clear `ai_error` when no API
key is configured; a real accepted link compiles into a new group while the
existing protected group survives untouched, and `settings.
get_ai_usage_totals()` reflects the call; a cross-link between two different
already-established groups is correctly rejected as a
`protected_alignment_conflict` (not applied, `requires_human_review: true`)
rather than silently merging two independent human decisions; and
`alignment.aiApplyProposal` saves a proposal through the normal
identity-checked pipeline, filling the previously-empty word bank and
empty-bottom group. One real fixture bug found while writing these: the
project's existing test fixtures for alignment data always include
`"type": "bottomWord"` on every bottom-side token because
`TokenRef.to_dict(bottom=True)` always adds it — a first draft of this
session's fixture helper omitted it, which made `alignment.aiApplyProposal`
spuriously report "changed on disk" (the raw-file identity check in
`save_verse_alignment` compares byte-for-byte against `expectedOriginal`,
which came from a real `to_dict()` call that *does* include `type`). Fixed
in the test fixture, not in product code — this is a pre-existing,
already-correct on-disk data contract this session hadn't matched yet, not
a Bridge bug. Full source suite: 148 passed (144 + 4 new), plus the one
pre-existing, load-sensitive `test_versification_concurrency.py` failure
noted at the top of this document (confirmed unrelated, reproduced again
this session under background load). `npm run check` (0 errors/0 warnings)
and `npm run build` (succeeds, same pre-existing chunk-size warning) both
still pass. `cargo check` succeeds.

**Not done in this pass**: not click-tested in a running Tauri window (no
sidecar binary was built this session — same build constraint noted
elsewhere in this document). `mode: "audit"` is wired end-to-end on the
backend and typed on the frontend but the UI only ever requests
`"gap_fill"` — `compile_link_proposal`'s own docstring frames `audit` as a
read-only whole-verse comparison "not meant to be applied directly", and
`aiApplyAlignmentProposal`'s `validate_preparation_proposal` call correctly
rejects an audit-mode proposal that would detach an established group, but
no UI surfaces an audit-only read-only comparison view yet. AI usage
totals accumulate in `settings.json` but are still not displayed anywhere
in `SettingsModal.svelte` — `get_ai_usage_totals()`'s data has been real
since this phase but remains invisible to the user; a small, separate UI
gap worth closing later.

**Drag-and-drop import — `bridgeClient.ts` gained `onFileDrop()`**, using
Tauri v2's native OS drag-and-drop (`getCurrentWebview().onDragDropEvent`,
confirmed against the installed `node_modules/@tauri-apps/api/webview.d.ts`
rather than assumed from memory — its `DragDropEvent` union is
`{type:'enter'|'over'|'drop', paths, position} | {type:'leave'}`), kept
behind the same "only `bridgeClient.ts` imports `@tauri-apps/api`" rule the
file's own header comment already states. `ImportScreen.svelte` listens in
`onMount`/unlistens in `onDestroy`, reuses the exact same `inspect(path)`
function the existing file/folder pickers already call (so drag-drop gets
every validation/preview/warning path the picker flow already has, free),
shows a dashed drop-target highlight only while a drag is over the initial
picker screen (not during import-review, where a drop is intentionally
ignored — dropping a second source while reviewing the first would be
confusing, matching how the existing "Choose another source" flow requires
an explicit reset first), and rejects a multi-path drop with a clear error
instead of silently importing only the first path and discarding the rest.
No Rust/`tauri.conf.json` change was needed — Tauri v2's window-level
`dragDropEnabled` defaults to `true` and nothing in `tauri.conf.json` turns
it off (checked, not assumed). **Not click-tested in a running Tauri
window** in this session (same build constraint as above) — `npm run
check`/`npm run build` verify the code compiles and type-checks, not that
a real OS-level file drag actually reaches the webview and imports
correctly; worth a real click-through (drag a `.usfm` file, then a
multi-book folder, onto the window) before treating this as fully verified.

### Paratext/Logos connectors and AI explain — Phase 7 continued (2026-08-24)

Picked up immediately after part 1 above, in the same session, on the user's
explicit "go ahead on all counts on a best-effort basis" instruction — with
the honest caveat given back at the time: two of these three slices
fundamentally need a live external application (Paratext, Logos) this
machine either didn't have running or didn't have installed at all, so
"best effort" here means real, compiling, protocol-correct code that has
never been exercised against the real external app. Every such gap is
flagged explicitly below and in the new files' own README/header comments —
never silently presented as more verified than it is.

**translationWordsLinks resource-layout bug — found and fixed first, because
AI explain depends on it.** `knowledge_base.py`'s `twl_occurrences()` reads
`translationWordsLinks/<version>/{kt,names,other}/groups/<book>/<term>.json`
— a *resource-level* layout, keyed by category and term — but
`resource_materializer.materialize_translation_words()` only ever wrote the
*project-level* check-index shape
(`.apps/translationCore/index/translationWords/<book>/<group>.json`),
confirmed by reading both functions directly, not assumed from the earlier
research breadcrumb. Fixed with a new function,
`materialize_translation_words_links_index()`, that parses the exact same
bundled `twl_<BOOK>.tsv` a second time (no shared-parsing risk with the
already-tested project-level writer) into the resource-level shape,
called from `materialize_book_checks()` alongside the two existing
materializers. Verified with 3 new tests, including one that calls
`TranslationHelpsKnowledgeBase.twl_occurrences()` directly and confirms it
now returns real data — not just "the files got written."

**translationAcademy — bundled for the first time, and its own real reading
bug found and fixed.** Two real gaps stacked here, found only by actually
downloading and inspecting the content, the same way every other resource
gap in this project has been found:

1. `ensure_resources_installed()`'s resource list was
   `('translationNotes', 'translationWordsLinks', 'translationWords')` —
   `translationAcademy` was never in it, so even after bundling real content
   under `engine/resources/`, nothing would ever copy it into application
   storage. Fixed by adding it to that tuple.
2. The real content itself: downloaded the actual
   `git.door43.org/unfoldingWord/en_ta` repository at tag `v90` (the same
   tag already used for tN/TW/TWL — confirmed to exist via that Gitea
   instance's own API, not GitHub; `unfoldingWord/en_ta` and
   `unfoldingWord/en_tn` both 404 on api.github.com, confirming this
   content was never on GitHub proper for either resource, and the earlier
   P0 bundling pass's own "Door43" references meant the Gitea instance all
   along) — a real 2.2MB, 728-file, CC BY-SA 4.0 archive, not a synthetic
   fixture. Extracting and inspecting it directly showed
   `knowledge_base.py`'s `_find_article()`/`global_checking_evidence()` were
   both written for a **flat** `"<identifier>.md"` file shape — correct for
   translationWords (confirmed by the earlier, already-passing P0
   acceptance tests) but wrong for translationAcademy, whose real articles
   are **directories** (`checking/accuracy-check/{title.md, sub-title.md,
   01.md}`). This is the same bug *class* every vendored/bundled
   integration in this project has hit — an assumption written before real
   content existed to check it against — just newly found in
   `knowledge_base.py` instead of a vendored tool. Fixed with a dedicated
   `_find_ta_article_dirs()` (left `_find_article()` itself untouched, since
   translationWords' flat-file use of it is correct and already tested) plus
   updated `ta_articles()`/`global_checking_evidence()` to read `01.md` for
   body content and `title.md` for a real human-readable title instead of
   using the raw `"01"` filename stem. Verified with 4 new tests against the
   real downloaded content, including all 13 of `global_checking_evidence()`'s
   hardcoded checking-category identifiers confirmed as real, existing
   slugs (not guessed).

**`ai.explain` — new protocol method wiring `ai_client.OpenAIResponsesClient
.prepare_verse_review()`**, itself real, complete, already-implemented code
from Phases 1-3 that had zero protocol wiring and zero test coverage before
this pass (same shape of gap as `alignment.aiPropose`'s scaffolding in part
1 above). Read-only — nothing is written to project files; the human
reviewer sees AI's evidence-backed check-review preparation and whole-verse
QA as something to confirm or reject, same "AI says what it may mean, human
decides" boundary as everywhere else in Bridge. Verified with 2 tests using
the same fake-transport injection seam as `alignment.aiPropose`, against
*real* materialized translationNotes/translationWords evidence (a real
import + `verse.runChecks` preflight, not synthetic fixtures) — the fake AI
response's `check_reviews` are built from checkIds discovered from the real
project data, not guessed, so the test genuinely exercises
`prepare_verse_review`'s "every supplied check must come back or the model
response is rejected" validation. `bridge-engine.spec` needed no new
`datas`/`hiddenimports` entries (this reuses the `resources` tree, now
including translationAcademy, already bundled wholesale). Frozen build
verified via an extended `scripts/smoke_sidecars.py`: since that fixture
project has no application-storage `resources/` folder of its own, `ai
.explain` legitimately hits `knowledge_base_error` before `ai_client.py`'s
own missing-API-key check ever runs — the smoke test accepts either clean
error code, since both prove the bundle (imports, and now translationAcademy
data) is genuinely intact rather than crashing.

**Frontend**: `ReviewPanel.svelte` gained a "🤖 Explain with AI" button and
a results section (summary, per-check verdict/rationale/suggested
correction, whole-verse QA issues) — deliberately no new evidence-browser
UI; check reviews and issues render with the same finding-card visual
language the rest of the panel already uses. `bridgeClient.ts` gained
`aiExplainVerse()`; `types/finding.ts` gained `AiExplainResult`/
`AiCheckReview`/`AiQaIssue` (documented inline with the same snake_case
wire-shape rationale as `AlignmentAiProposal` in part 1 — these mirror
`AICheckReview.to_dict()`/`QAIssue.to_dict()`'s real Python output verbatim,
since it's read-only display data with no round-trip requirement to get
"wrong" the way the alignment proposal has, but declaring the true shape
still beats a silently-incorrect camelCase guess).

**Paratext companion plugin — the real, previously-missing artifact now
exists.** `paratext_connector.py`'s `ParatextConnectorClient` only ever
talked to a companion plugin over a named pipe
(`\\.\pipe\translationCoreAIBridge`) that did not exist anywhere in this
repo; building one had been flagged as "a different technology stack, a
genuinely separate undertaking" by the investigation earlier this session.
It turned out to be more tractable than that framing suggested, once
actually investigated rather than assumed:

- The real Paratext plugin interface DLLs
  (`PluginInterfaces.dll`/`CorePluginInterfaces.dll`/
  `EmbeddedUiPluginInterfaces.dll`) are already installed locally at
  `C:\Program Files\Paratext 9`. Reflecting into them directly (PowerShell's
  `[System.Reflection.Assembly]::LoadFrom` + `GetTypes()`/`GetMethods()`,
  not documentation) gave the real interface surface: `IPluginHost
  .add_VerseRefChanged(ReferenceChangedHandler)`,
  `SetReferenceForSyncGroup(IVerseRef, SyncReferenceGroup)`, `IVerseRef`,
  `IParatextChildState`, `IProject`/`IReadOnlyProject`, and
  `ParatextInternal.IParatextPlugin` (the real, if oddly-namespaced, base
  interface every plugin implements) — everything
  `tc_ai_bridge/navigation.py`'s `NavigationBroker` design already needs.
- No Visual Studio, modern .NET SDK, or NuGet install was needed: the C#
  compiler bundled with Windows' own .NET Framework
  (`csc.exe`) compiles directly against those installed DLLs plus
  `System.Web.Extensions.dll` (bundled, provides `JavaScriptSerializer` for
  JSON with no external dependency) and `netstandard.dll` (also already
  present — the plugin interfaces are themselves built against
  netstandard2.0, discovered from the compiler's own first-attempt `CS0012`
  errors, not assumed).
- The real plugin *deployment* mechanism was confirmed from Paratext's own
  official demo-plugins wiki (`ubsicap/paratext_demo_plugins`, fetched
  directly via `raw.githubusercontent.com`, not assumed): a compiled DLL
  renamed to `.ptxplg`, copied into
  `C:\Program Files\Paratext 9\plugins\{PluginFolder}\` while Paratext is
  closed. No marketplace registration or signing is required for local
  development use.
- New code: `paratext_plugin/TranslationCoreAIBridgePlugin.cs` — implements
  `get_state` (reads the active window's verse reference/project/sync
  group) and `set_reference` (calls `SetReferenceForSyncGroup`) over the
  exact newline-delimited JSON protocol `paratext_connector.py`'s
  `_exchange()` already speaks. **`create_note` is deliberately NOT
  implemented** — it returns a clear "not implemented" error — because
  Bridge already has a complete, working Paratext Notes 1.1 XML writer
  (`tc_ai_bridge/paratext_notes.py`) that writes notes directly to disk
  without needing the plugin at all; a live `AddNote()` call would need an
  `IWriteLock`/`IScriptureTextSelection`/`CommentParagraph` this session had
  no way to construct or verify against a real running Paratext instance.
- **What's verified**: the plugin compiles cleanly (`paratext_plugin
  /build.ps1`) against the real reflected interfaces. **What's not**:
  it has never been loaded by a running Paratext instance. Deploying it
  requires writing into `C:\Program Files\Paratext 9\plugins\...`, a
  protected system directory — this session's own safety controls correctly
  blocked that write rather than silently proceeding. See
  `paratext_plugin/README.md` for the exact remaining steps (close
  Paratext, run `build.ps1 -Deploy` elevated, check
  `%LOCALAPPDATA%\Paratext95\ParatextLog.log` for the plugin loading).

**Logos bridge script — the real, previously-missing artifact now exists,
with its own genuinely-tested process wiring.**
`logos_connector.py`'s `LogosConnectorClient` spawns
`logos_connector/logos_bridge.ps1` as a persistent `-STA` PowerShell helper
and talks to it over its own stdin/stdout — that script did not exist
anywhere in the repo before this pass, and Logos is not installed on this
machine (the user is installing it; a colleague with a working Logos
install will do the real functional testing).

- The real COM API surface (type library `Logos4Lib`, GUID
  `{81490292-5570-4D02-A2AC-7B828DBD0A8A}`; `new LogosLauncher().Application`;
  `LogosApplication.ApiVersion/.Activate()/.Exit()/.ExecuteUri()/
  .CreateNavigationRequest()/.Navigate(request)/.DataTypes.LoadReference()/
  .GetDataType()`; `PanelActivated`/`PanelChanged`/`PanelOpened`/
  `PanelClosed`/`Exiting` events) was pulled from `LogosBible
  /Logos4ComApiDemo`'s actual `.cs`/`.csproj` source, fetched directly from
  `raw.githubusercontent.com` (the wiki page itself 403'd), the same
  standard this project applies to every other integration.
- **Two things are genuinely unverified and flagged inline in the script's
  own header** (the most likely things to need a real fix once tested
  against live Logos): the exact COM ProgID string
  (`"Logos4Lib.LogosLauncher"` follows the standard `tlbimp` naming
  convention but was never seen registered for real — `Get-LogosLauncher`
  searches the registry for a plausible alternative and reports it if the
  literal string fails), and reading the *currently active panel's*
  reference (`Get-CurrentReferenceInfo`'s `$app.ActivePanel` guess) — the
  official demo only shows *pushing* a reference via `Navigate()`, never
  reading one back, so there was no real source to confirm this against.
  Both paths are wrapped in defensive `try`/`catch` so a wrong guess
  degrades to an empty/error response rather than crashing the helper.
- No live COM event push is attempted — a plain PowerShell script has no
  message loop to reliably pump COM callbacks, and `navigation.py`'s
  `NavigationBroker` is already designed around a *polling* connector
  (its echo-suppression/settling-window logic exists specifically to make
  repeated polling safe), so a poll-only helper matches the existing
  design rather than falling short of it.
- **What's genuinely verified, real subprocess-level testing, not just
  syntax-checking**: `engine/tests/test_logos_connector.py` (4 tests) proves
  `LogosConnectorClient` actually spawns this exact script in `-STA` mode,
  exchanges real newline-delimited JSON, and a real "Logos isn't installed"
  COM failure round-trips as a clean `LogosConnectorError` — not a hang, not
  a malformed-response error. A real bug was found and fixed this way: the
  first draft double-printed the `close` action's response (an inline
  `WriteLine` inside the request-dispatch `switch` *and* the general
  response-write path after it) — caught by actually running the script
  with real stdin input, not by reading the code.

**Python-side connector protocol wiring — deliberately scoped to direct
pass-through, not full automatic live sync.** New methods:
`paratext.getState`/`paratext.setReference`,
`logos.getState`/`logos.setReference`. `BridgeEngine` caches one
`LogosConnectorClient` instance per process (unlike Paratext's stateless
per-call named-pipe open, spawning a fresh `-STA` PowerShell process on
every poll would be far too slow — real measured cold-start well over a
second), registered with `atexit` for best-effort clean shutdown (a known,
documented limitation: `atexit` does not run on a hard kill, e.g. Tauri
force-terminating the sidecar — see `logos_connector/README.md`). This
deliberately does **not** wire `navigation.py`'s
`NavigationBroker`/`NavigationOwnership` into an automatic background
polling loop yet — that's a real, separate UX design (conflict handling, a
background job, a live-sync toggle) worth its own pass once these two
connectors have been proven against real running Paratext/Logos instances.
What's here is already useful on its own: a future "Connections" panel can
show live state and let a reviewer manually push Bridge's current verse
into either application. Verified with 4 protocol-level tests (clean error
codes for both connectors with no companion running) plus the real Logos
subprocess tests above, run again through the full `BridgeEngine
.handle_request` dispatch this time. Frozen build verified via
`scripts/smoke_sidecars.py`: `paratext.getState` fails cleanly with no
companion plugin, and `logos.getState` genuinely spawns the bundled
`logos_bridge.ps1` from under `sys._MEIPASS` (confirming a new
`bridge-engine.spec` `datas` entry — `logos_connector/`, invisible to
PyInstaller's static analysis the same way every other runtime-resolved
vendor/helper path in this project has been) and gets the real "Logos isn't
installed" COM error, not a missing-file/spawn error.

**Full source suite after this continuation**: see `docs/QA_TEST_MATRIX.md`'s
A20-A26 rows for the exact test counts and what each verifies. `npm run
check` (0 errors/0 warnings) and `npm run build` both still pass. `cargo
check` succeeds with the six new Tauri commands
(`ai_explain`/`paratext_get_state`/`paratext_set_reference`/
`logos_get_state`/`logos_set_reference`, plus the two from part 1)
registered and per-method sidecar timeouts tuned (`ai.explain` needs up to
two sequential real model calls; `logos.*` needs headroom for the helper's
slow cold start).

**Not done in this pass**: no click-through in a running Tauri window for
any of this (same build constraint as part 1 — no interactive window
automation available in this environment, confirmed by two failed
standard Windows foreground-focus tricks earlier in the session). The
Paratext plugin has never been loaded by real Paratext. The Logos bridge
script has never made a real COM call. No "Connections" panel UI exists yet
for either connector — only the protocol methods and (for Logos) the fake
`get_state`/`set_reference` failure paths are exercised. `mode: "audit"`
for `alignment.aiPropose` remains backend-only with no UI. AI usage totals
still accumulate in `settings.json` but still aren't surfaced anywhere in
`SettingsModal.svelte`.

Continue building Bridge's import workflow so users can bring in individual
USFM/SFM files, whole-Bible folders, Paratext folders, and translationCore
projects, then use the normalized data for local QA, Greek Room,
translationNotes, translationWords, and word alignment.

The import foundation described below is implemented and verified. It has since
been committed as `9ed60cb feat(import): add translationCore-compatible Scripture
imports` — the working tree is currently clean. The "Working-tree warning" section
near the end of this document is kept for historical reference (it describes what
that commit touched) but no longer describes an uncommitted state.

## What is implemented

### Backend normalization

`engine/tc_ai_bridge/project_import.py` provides two public entry points:

- `inspect_import(source_path)`: read-only detection and metadata preview.
- `import_source(source_path, destination_root, metadata)`: staged,
  non-overwriting import and normalization.

Accepted input:

- `.usfm` and `.sfm` files.
- Marker-based `.txt` Scripture files.
- Folders containing one or many Scripture books.
- Paratext-style folders with `Settings.xml`.
- Existing translationCore project folders.
- `.tcore`, `.tstudio`, and ZIP project archives.

For raw Scripture, each book becomes a translationCore-compatible book project:

```text
<project>/
  manifest.json
  <book>.usfm
  <book>/headers.json
  <book>/<chapter>.json
  .apps/translationCore/alignmentData/<book>/<chapter>.json
  .apps/translationCore/index/translationNotes/<book>/
  .apps/translationCore/index/translationWords/<book>/
  .apps/translationCore/checkData/...
  .bridge/import.json
```

Important behavior:

- Original source bytes are preserved.
- `.bridge/import.json` records SHA-256 provenance and capability status.
- Existing translationCore indexes, decisions, comments, and alignments are
  copied intact.
- Older tC/tS projects with target chapter JSON but no alignment data receive
  unaligned target word banks so `TranslationCoreProject` can open them.
- Each unaligned target token is represented once in `wordBank`, with correct
  `occurrence` and `occurrences` values.
- Nested USFM 3 `zaln`/`w` alignment milestones are converted into occurrence-aware
  translationCore 1:1, 1:many, many:1, and many:many groups.
- Malformed alignment structures are not guessed; target words remain in
  `wordBank` for review.
- Multi-book folders produce one compatible project entry per book. All source
  files are copied immediately, the first book is normalized and opened, and
  remaining books carry `.bridge/lazy-import.json` until first open. Every
  sibling has `.bridge/collection.json`, so the full selector survives restart.
- ZIP entries are validated against path traversal before extraction.
- Imports use private staging and collision suffixes instead of deleting or
  overwriting existing projects.

### Sidecar protocol

`engine/bridge_service.py` adds:

- `project.inspectImport`
- `project.import`

The project response now also supplies confirmed `targetLanguageId`,
`targetLanguageDirection`, `projectName`, and `bibleName`.

Greek Room now receives the confirmed language identifier from
`manifest.target_language.id`, rather than the display-language name. Local QA
already gets its language context from the manifest via `PluginRegistry`.

USFM verse bridges/segments such as `3-4` and `3a` no longer crash local finding
conversion. Findings use the first numeric component as their numeric anchor,
while project navigation retains the exact verse string.

### Tauri and frontend

The Tauri layer adds:

- Native import-file picker with USFM/SFM/TXT/TCORE/TSTUDIO/ZIP filters.
- Thin commands for inspection and import.
- A five-minute sidecar safety timeout remains for import, but whole-Bible raw
  import no longer relies on it: the real 66-book OV Tamil source measured
  5.17 seconds from source and 6.21 seconds through the frozen packaged sidecar
  after lazy book normalization was introduced.

`src/lib/components/ImportScreen.svelte` now provides:

- Separate file import, folder import, and open-existing-project actions.
- Read-only preview before import.
- Detected-book list, verse counts, alignment status, and warnings.
- Required Language, Project name, Bible/translation name, and text direction.
- Offline searchable ISO 639-3 catalog using `iso-639-3@3.0.1`.
- Import is disabled until the required metadata is valid.

The complete catalog adds about 94 KB gzip to the production bundle and causes
Vite's non-fatal 500 KB chunk warning. It can be split later if startup size
becomes a concern.

## Critical design boundary: tN/tW are not fabricated

Raw USFM contains Scripture, not translationNotes or translationWords checks.
translationCore first imports Scripture and later materializes tool indexes from
installed, versioned checking resources. Bridge follows that boundary.

Current behavior:

- Imported existing translationCore projects immediately expose any real tN/tW
  indexes they already contain.
- Raw imports record `requires-resource-index` for translationNotes and
  translationWords until the first background-check preflight for that book.
- Compatible index directories are created, but no fake/empty check entries are
  generated.
- Local Scripture QA, Greek Room, and word-alignment preparation work now.
- Bundled-resource acquisition and real per-book tN/tW materialization are
  implemented; online resource/version selection is still future work.

## Recommended next work

### P0 — Resource acquisition and tN/tW index materialization (done 2026-08-20)

**Approach taken:** bundle a pinned English tN/tW/TWL snapshot in the repo
(matching real translationCore's own default of shipping English checking
helps in the installer) rather than fetching on demand — Bridge's own
premise is field translation teams with unreliable connectivity, so a raw
import must produce real tN/tW checks with zero network access.

What's bundled, under `engine/resources/en/translationHelps/` (~42 MB,
committed):

- `translationNotes/v90_unfoldingWord/tn_<BOOK>.tsv` — raw Door43
  `unfoldingWord/en_tn` tag v90, 56 of 66 books.
- `translationWordsLinks/v90_unfoldingWord/twl_<BOOK>.tsv` — raw
  `unfoldingWord/en_twl` tag v90, same 56 books.
- `translationWords/v90_unfoldingWord/bible/{kt,names,other}/*.md` — raw
  `unfoldingWord/en_tw` tag v90 articles (953 files), plus each resource's
  own `manifest.yaml`/`LICENSE.md` for provenance and attribution.
- **10 Old Testament books are not currently in the upstream release**
  (Numbers, 1-2 Chronicles, Ecclesiastes, Isaiah, Jeremiah, Ezekiel, Daniel,
  Amos, Zechariah) — verified directly against the live Door43 catalog on
  2026-08-20, not a gap in this bundling pass. Re-run the same fetch against
  a newer tag later to pick up whichever of these ship next; nothing else
  needs to change.

**New code:**

- `engine/tc_ai_bridge/resource_materializer.py` — pure parser/writer.
  `ensure_resources_installed(app_resources_root)` copies the bundled
  snapshot into application-owned storage once (mirrors how `project_root`
  itself is a copy separate from the repo — `TranslationHelpsKnowledgeBase`
  resolves resources relative to a project's own path, i.e.
  `settings_root/resources/...`, never the repo). `materialize_book_checks()`
  parses the bundled TN/TWL TSVs for one book and writes real
  `.apps/translationCore/index/{translationNotes|translationWords}/<book>/<group>.json`
  entries with a full `contextId` (`reference`, `tool`, `groupId` — the TA
  slug for tN, the term slug for tW — `checkId`, `quoteString`,
  `occurrenceNote`). Always fully regenerates those files: safe, because
  Bridge's own Accept/Reject/Ignore decisions live in the project's separate
  `decisions/` companion directory (stable finding ids) and are re-applied
  onto findings after checks run — never stored inside these index files.
- `project_import.py` gained `apply_resource_materialization()`, which pins
  `tc_en_check_version_translationNotes`/`...translationWords` in
  `manifest.json` and records real `ready`/`unavailable` capability status
  (never a fabricated `ready` with zero checks) in `.bridge/import.json`.
- `bridge_service.py` prepares these indexes in the background checking
  preflight, and **only for raw USFM/SFM/Paratext imports**. Import no longer
  blocks on every book's tN/tW data. An imported existing translationCore/
  translationStudio project keeps its own real indexes untouched, per the
  tN/tW design boundary in `docs/IMPORTS.md`. tN/tW are gateway-language
  (English) checking helps applied to any target-language translation, so this
  doesn't depend on the imported project's target language.

**Verified:** `test_resource_materializer.py` (5 tests, all against the real
bundled Titus TN/TWL slice, not a synthetic fixture) — parses into the
correct `contextId` shape, is idempotent, correctly reports `unavailable`
for an unreleased book (tested with Isaiah), and an end-to-end
import→`verse.runChecks` call surfaces real `translation_note`/
`translation_word` findings. Historical suite after lazy whole-Bible import: 79/79
passing (2026-08-21).

**Still open / not done in this pass:**

- **`knowledge_base.py`'s own TWL reader is still unfed.** It expects a
  *different*, pre-materialized layout —
  `translationWordsLinks/<version>/{kt,names,other}/groups/<book>/<term>.json`
  — used only by `ai_client.py`'s evidence-gathering (the unwired Phase 7
  `ai.explain`). This pass bundled the raw TWL TSVs and materializes
  *project-level* check indexes from them directly; it does not also build
  that second, resource-level grouped-JSON shape. Needed before Phase 7 can
  gather TW evidence, not needed for `verse.runChecks`.
- **`translationAcademy` was not bundled.** Nothing on the `verse.runChecks`
  path reads it today (`local_checks.py` never imports `knowledge_base.py`);
  it's only needed for TA article evidence in the same unwired `ai.explain`
  path. `knowledge_base.py.resolve('translationAcademy')` will raise
  `KnowledgeBaseError` if something calls it before this exists — currently
  nothing on any wired protocol method does.
- **PyInstaller build needs `--add-data` to ship the bundle**, and should
  now be run from the `engine/.venv` Python 3.12 environment (see the real
  Wildebeest section above), e.g. (from `engine/`, Windows path separator
  is `;`):
  `.venv\Scripts\python.exe -m PyInstaller --onefile --name bridge-engine --add-data "resources;resources" main.py`.
  Without `--add-data`, a frozen `.exe` has no bundled tN/tW snapshot and
  every raw import falls back to `unavailable` on a machine where
  `ensure_resources_installed` has never run before (dev-mode runs are
  unaffected since `bundled_resources_source()` reads straight from
  `engine/resources`). If the real Wildebeest engine (`wildebeest-nlp`,
  installed via the `wildebeest` extra) should be in the build, also add
  `--collect-data wildebeest` — unverified insurance for its `data/`
  directory, see the real Wildebeest section above. This was not verified
  against an actual PyInstaller build in this session — no sidecar binary
  was built. Confirm the frozen `.exe` actually finds the resource bundle
  via `sys._MEIPASS`, and that Greek Room findings still say
  `usingRealEngine: true` in `engine.info`, before shipping.
- **Only English is bundled.** Non-English tN/tW (or a refreshed English
  version) still needs the online path described in the original P0 below —
  not built in this pass, since it wasn't required to satisfy the
  acceptance criteria against real data.

Original acceptance criteria (all met):

- A raw USFM import followed by resource preparation produces non-zero real
  tN/tW checks for known verses. ✓
- `verse.runChecks` returns those items as translation-note/translation-word
  findings. ✓
- Resource versions and hashes are visible in provenance (pinned
  `tc_en_check_version_*` fields; `knowledge_base.py`'s existing
  `provenance_manifest()` hashes each bundled `manifest.yaml`). ✓
- Re-running indexing is deterministic and does not erase human decisions. ✓

### P0 — Multi-book collection navigation (done 2026-08-20)

`TopBar.svelte`'s book `<select>` was previously a dead placeholder — one
hardcoded option, no `on:change`. It now lists every sibling from
`ProjectInfo.importedProjects` and calls `project.open` on selection.

Implementation notes for whoever touches this next:

- `project.open` does **not** echo back `importedProjects` (only
  `project.import` does — see `bridge_service.py`'s `_project_info()` vs
  `import_project()`). The sibling list is therefore carried forward on the
  frontend across a switch (`App.svelte`'s `switchBook()`) rather than
  re-fetched from the backend. If the app is closed and reopened, or a book is
  opened individually via "Open an existing project," the sibling list is
  gone and the selector falls back to showing just that one book — this is
  accepted as in-session-only, matching the P0 scope (switching immediately
  after import).
- `stores.ts` gained `resetBookState()`, called before switching: chapter and
  verse numbers restart at 1 in every book, so `chapterVerseNums`,
  `verseTexts`, `findingsByVerse`, and `loadedChapters` must be cleared on
  switch or the new book would show the old book's data under matching
  chapter/verse keys — the same class of bug gotcha #7 was written to avoid,
  just at the book level instead of the chapter level.
- `App.svelte` factored the "land on first chapter, load it, select first
  verse" sequence out of `handleOpened()` into `enterCurrentProject()`, shared
  by both initial open and `switchBook()`.
- Verified: `npm run check` (0 errors), `npm run build` (succeeds, same
  pre-existing chunk-size warning as before). Not exercised in a running
  Tauri window in this session — no sidecar binary was built/available to
  launch `npm run tauri dev` end-to-end. Whoever picks this up next should
  do a real click-through (import a multi-book folder, switch between books,
  confirm chapter/verse state doesn't bleed across books) before treating
  this as fully verified.

### P1 — Maintained full USFM parser

The current parser is conservative and the original source is always preserved,
but normalized extraction still uses regular expressions. Replace or augment it
with a maintained USFM parser for full marker placement, verse bridges/segments,
tables, peripheral material, and project validation. Nested alignment milestones
are supported by the current targeted parser and source-template export; retain
both behaviors during that migration.

### P1 — Direct Paratext import

Local Paratext folders are detected and `Settings.xml` is used for metadata.
Direct Scripture retrieval from Paratext/API is not wired. Keep that separate
from the existing note connector and require explicit project selection.

### P1 — Import reporting and recovery

Add an import-results screen showing all created project paths, warnings,
unaligned milestone counts, resource-index status, and a way to open any book.
For a multi-book failure, either make the whole collection atomic or clearly
report which book projects completed.

## Verification completed

From `engine/`:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests/ greek_room_engine/tests/ -q -p no:cacheprovider
Remove-Item Env:PYTHONDONTWRITEBYTECODE
```

Result: `32 passed`.

From the repository root:

```powershell
npm run check
npm run build
```

Results:

- Svelte check: 0 errors and 0 warnings.
- Production build: successful, with only the language-catalog chunk-size
  warning described above.

From `src-tauri/`:

```powershell
cargo check
```

Result: successful.

`git diff --check` also passes; only Windows LF-to-CRLF notices are printed.

`npm install` reports seven dependency advisories (six moderate and one high).
No automatic `npm audit fix --force` was run because it can introduce breaking
dependency changes. Audit and upgrade these separately.

## Tests added

`engine/tests/test_project_import.py` covers:

- Read-only USFM preview and missing-language detection.
- Raw SFM normalization and provenance.
- Multi-book folder import.
- Basic USFM 3 alignment preservation.
- Existing tC archive check-index preservation.
- ZIP path-traversal rejection.
- End-to-end sidecar import and automatic project opening.
- Verse-bridge import and checking.

## Upstream translationCore research

The implementation was compared against:

- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/actions/Import/LocalImportWorkflowActions.js
- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/FileConversionHelpers/UsfmFileConversionHelpers.js
- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/FileConversionHelpers/ZipFileConversionHelpers.js
- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/manifestHelpers.js
- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/ProjectValidation/ProjectStructureValidationHelpers.js

Key upstream behavior confirmed:

- tC accepts USFM/SFM/TXT and TCORE/TSTUDIO files through its local file picker.
- USFM import generates a manifest, copies the source, and creates target chapter
  JSON.
- Alignment data is created when alignment milestones are present.
- Missing project/language details are handled during validation.
- Upstream translationCore rejects multiple-book projects; Bridge deliberately
  imports them as a collection of book-wise projects instead.

## Working-tree warning (historical — now committed as `9ed60cb`)

At the time this document was originally written the working tree was uncommitted;
it has since been committed. Files involved in this import work were:

- `engine/tc_ai_bridge/project_import.py` (new)
- `engine/tests/test_project_import.py` (new)
- `engine/bridge_service.py`
- `src/lib/components/ImportScreen.svelte`
- `src/lib/api/bridgeClient.ts`
- `src/lib/types/finding.ts`
- `src-tauri/src/commands.rs`
- `src-tauri/src/main.rs`
- `src-tauri/src/sidecar.rs`
- `package.json`
- `package-lock.json`
- `docs/IMPORTS.md` (new)
- `README.md`

`src-tauri/Cargo.toml` and `vite.config.ts` were also modified in the broader
working session and are part of the same commit.

