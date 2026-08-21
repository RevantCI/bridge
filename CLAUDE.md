# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
npm run build    # production Vite build
npm run dev      # browser-only dev server at localhost:1420 — no sidecar, bridge.ping() etc. will fail
```

No frontend test framework is configured; `npm run check` + `npm run build`
are the whole frontend verification gate.

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

Rust has no `#[test]` unit tests; `cargo check`/`cargo build` (compile
success) is the verification bar for `src-tauri/`.

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

`docs/DEVELOPER_HANDOFF.md` is the authoritative, continuously-updated
handoff doc — read its "Phase roadmap status" section first to see what's
actually done vs. planned before picking up new work; don't assume the
next task is just the next numbered phase. `docs/ARCHITECTURE.md` has the
original design rationale (some file paths there are stale — prefer
`DEVELOPER_HANDOFF.md` and the actual code when they disagree).
`docs/ALIGNMENT.md` and `docs/IMPORTS.md` document the manual-alignment and
import subsystems respectively. `docs/QA_TEST_MATRIX.md` is the release
gate — a feature isn't release-ready because its unit tests pass; check
the matrix's source/frozen/desktop rows.
