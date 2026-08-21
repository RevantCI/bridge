# Developer handoff: Bridge v0.8.0-beta.1

Updated: 2026-08-21

## Current release state

The current working release adds the complete manual word-alignment loop. The
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
- Export/import: nested many-to-many `zaln`/`w` milestones are parsed into tC
  groups and aligned export writes re-importable USFM 3 over the retained source
  template.
- Automated source gate: 122 Python tests (96 at this release's alignment
  milestone, +26 added for Phase 4's versification work, including edge
  cases and concurrency regression tests); Svelte, Rust, frozen-sidecar and
  NSIS results are recorded in the QA matrix, not assumed here.
- Explicitly deferred: AI alignment proposals, UAlign statistics, original-source
  resource downloads, and live Paratext/Logos synchronization.

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
- **Phase 5 (Names & Transliteration, Uroman + Smart Edit Distance)**: not started.
- **Phase 6 (Alignment Intelligence, UAlign corpus stats)**: the statistics
  engine itself is not started. But the manual word-alignment editor added in
  `feat(alignment)` (see `docs/ALIGNMENT.md`) wasn't in the original plan at
  all — it's a prerequisite Phase 6 actually needs, since you can't compute
  corpus statistics over "human-approved alignments" if there was previously
  no way to create or approve one inside Bridge. That gap is now closed;
  Phase 6's actual statistics work still needs to be built on top of it.
- **Phase 7 (Paratext/Logos connectors, AI explain, drag-and-drop)**: not
  started. `ai_client.py`'s endpoint has been configurable since Phase 3 but
  is still not called by any protocol method.

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
  ARCHITECTURE.md, DEVELOPER_HANDOFF.md (this file), IMPORTS.md
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
including a wall-clock regression bound tight enough that the unfixed
behavior blows through it by 5-10x. Full details in
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

