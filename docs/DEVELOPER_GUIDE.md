# Developer Guide

The "why" and "where things stand" companion to
[`DEVELOPER_SETUP.md`](DEVELOPER_SETUP.md) (the "how to get it running"
doc). This is a curated summary for personal/team reference — the full
detail always lives in [`ARCHITECTURE.md`](ARCHITECTURE.md) (design
rationale) and [`BUILD_LOG.md`](BUILD_LOG.md) (session-by-
session build log, currently ~1850 lines). Read those two when you need the
full story on something; use this doc to find out *whether* you need to.

---

## 1. Tech stack and why

| Layer | Choice | Why |
|---|---|---|
| Desktop shell | **Tauri v2** (Rust) | Native OS webview instead of bundling Chromium → smaller binary, faster cold start, lower idle memory. Matters for an all-day tool on modest field hardware. Rejected **Electron** for this reason. |
| Frontend | **Svelte 4 + TypeScript + Tailwind** | A real web-app UI (colored status badges, inline findings, tabbed panels) that a native widget toolkit fights rather than enables. Also gives a direct path to a future web deployment. Rejected **Python + Tkinter** (the original app's stack) for this reason. |
| Business logic | **Python 3.12/3.13 sidecar** (`bridge-engine`, PyInstaller-bundled) | Reuses the 29 (now 30) existing, proven `tc_ai_bridge` modules from the legacy app rather than rewriting them. |
| Sidecar transport | **JSON-lines over stdin/stdout** | Transport-agnostic protocol defined once in `engine/greek_room_engine/protocol.py`. Desktop uses stdio (`stdio_transport.py` / `src-tauri/src/sidecar.rs`); a future web deployment reuses the same `GreekRoomEngine.handle_request()` behind an HTTP wrapper — no protocol or UI rewrite needed. |

**Trade-off accepted:** Rust has a learning curve for a team with none; in
practice, day-to-day work stays in the Python engine and Svelte frontend —
the Rust shell is intentionally thin (spawn sidecar, route JSON, expose a
few Tauri commands).

**Core architectural principle** (unchanged since project start): Greek Room
says what's *objectively suspicious*, AI says what it *might mean*, the
human says what it *should be*. Nothing auto-applies to project files —
every finding carries an explicit human decision state. Full detail:
[`ARCHITECTURE.md`](ARCHITECTURE.md).

**Never integrated directly:** Greek Room's `ephesus/` web API (Docker,
database, its own web UI) — Bridge only uses the underlying check modules,
not the reference web app around them.

---

## 2. Phase roadmap — planning vs. actual outcome

The original plan (Claude Code sessions that did Phases 1-3) laid out 7
phases. What actually shipped often diverged from the plan, for good
reasons — this table is the fast way to see both.

| Phase | Planned | Actual outcome |
|---|---|---|
| **1** | Protocol & sidecar consolidation | ✅ Done. `BridgeEngine` = `GreekRoomEngine` + `tc_ai_bridge` behind one JSON protocol. |
| **2** | Svelte frontend wired to real sidecar | ✅ Done. Single-window UI, confirmed on a real Windows machine with a real translationCore project. |
| **3** | Decision persistence, chapter switching, whole-book, Settings, Export | ✅ Done. Stable finding IDs, `checks.start/status/cancel/retry` background jobs replacing a blocking frontend loop. |
| *(unplanned)* | — | Import pipeline built first, ahead of schedule — a working import blocks everything downstream. Also: a 66-book import that took 4–6 min and hit a hard timeout is now ~5–6s (lazy per-book normalization); a real security fix (plaintext API keys could persist to disk); the background job system above. |
| **4** | USFM structural checker + versification | ✅ Done (2026-08-20 / 2026-08-21). Both vendored from `BibleNLP/greek-room`, wired into the existing check pipeline. Backend/protocol-only — no dedicated UI panel, matching how other checks surface as inline findings. |
| **5** | Names & Transliteration (Uroman + Smart Edit Distance) | ✅ Done (2026-08-21). Whole-book spelling-consistency check wired into `verse.runChecks`'s existing `"local"` checks list — no frontend change needed. |
| **6** | Alignment Intelligence (UAlign corpus stats) | ✅ Statistics engine done (2026-08-24). Turned out to need a real prerequisite not in the original plan: you can't compute stats over "human-approved alignments" with no way to create one — so the **manual word-alignment editor** (see `ALIGNMENT.md`) was built first, then corpus statistics (co-occurrence, translation probability, PMI, optional SED phonetic boost) computed from Bridge's own completed alignments — not a vendored `ualign.py`. Backend/protocol-only, two read-only methods, no UI yet. |
| **7** | Paratext/Logos connectors, AI explain, drag-and-drop | ✅ All four slices have real work as of 2026-08-24, on a best-effort basis for the two needing a live external app. AI alignment proposals and drag-and-drop: done and verified end-to-end. AI explain: wired and tested against real materialized tN/tW evidence (found and fixed a real TWL resource-layout bug and a missing translationAcademy bundle along the way), verified with a fake transport (no live API key available that session). Paratext connector: companion plugin exists and compiles against Paratext's real interfaces, not yet loaded by a running Paratext instance. Logos connector: PowerShell/COM bridge script exists, process/protocol wiring tested, actual COM calls unverified (no Logos installed). |

**Lesson worth keeping in mind for future phases:** every external
integration attempted so far (Wildebeest, USFM checker, versification,
Uroman) turned out to have a real, non-obvious problem that only surfaced by
actually running the code — wrong PyPI package name, a Python 3.13
compatibility break, an unpublished dependency, a Windows-only `strftime`
crash, a version-skew bug between upstream's GitHub and PyPI releases, a
class-level-state crash on a second call, a silently different data license
hiding inside an otherwise-permissive vendor tree. Verify by running, not by
reading a doc's description — including this repo's own docs.

**Deliberately not yet done** (scope decisions, not bugs):

- Live original-language resource downloads (current baseline is a pinned,
  bundled snapshot — see §4).
- Automatic/live Paratext or Logos synchronization (current connectors are
  one-shot/manual, and only partially verified against live apps — see
  Phase 7 above).
- A dedicated UI panel for alignment corpus statistics (protocol-only today).
- Manual alignment does not invent source tokens — it requires original-
  language tokens already present from import.

---

## 3. Dependencies

### Python (`engine/pyproject.toml`)

| Package | Type | Notes |
|---|---|---|
| `regex>=2024.5.15` | Required | Needed by the vendored USFM checker and by `versification.py`'s own dependency; floor raised to also satisfy `uroman`'s requirement. |
| `uroman>=1.3.1.1` | Required | Real PyPI package (name-checked — unlike Wildebeest, not a name trap). Same author (Ulf Hermjakob, USC/ISI) as Wildebeest and the vendored Greek Room tools. No known installability problems on any current Python version, so it's a hard dependency, not optional. License note: PyPI/upstream both claim "Apache" but the actual bundled `LICENSE.txt` is a custom MIT-style license with its own mandatory attribution clause — verified by reading the installed package, not the metadata. |
| `wildebeest-nlp==0.9.2` | Optional (`[wildebeest]` extra) | Real package name is `wildebeest-nlp`, **not** `wildebeest` (that name belongs to an unrelated ShopRunner image-processing package). Pinned to the only release that exists. Does not install under Python 3.13 (a docstring contains a lone-surrogate escape 3.13 rejects at compile time — confirmed still broken on upstream's GitHub HEAD too). The `WildebeestAdapter` degrades to a mock automatically whether this extra is installed or not, so leaving it uninstalled is always safe — just means Wildebeest-specific checks won't run for real. |
| `greekroom` (published PyPI package) | **Not used** | Left commented out in `pyproject.toml`. Only ships `owl` and `gr_utilities` submodules — USFM checker, versification, and Smart Edit Distance are none of those, so all three are vendored separately from source instead (see §4). |
| `pytest>=7.0`, `pyinstaller>=6.0` | Dev only | Test running and sidecar packaging. |

### Frontend (`package.json`)

| Package | Notes |
|---|---|
| `@tauri-apps/api`, `@tauri-apps/plugin-dialog`, `@tauri-apps/cli` | Tauri v2 core + native file dialogs. |
| `iso-639-3` | Offline searchable language catalog for import metadata (adds ~94 KB gzip to the bundle — Vite's non-fatal 500 KB chunk warning is from this; splittable later if startup size becomes a concern). |
| `svelte`, `svelte-check`, `@sveltejs/vite-plugin-svelte`, `@tsconfig/svelte` | Svelte 4 + TS tooling. |
| `tailwindcss`, `postcss`, `autoprefixer` | Styling. |
| `usfm-js` | USFM parsing/serialization on the frontend. |
| `word-aligner` | Alignment-related utility (translationCore ecosystem package). |
| `vite`, `typescript` | Build tooling. |

---

## 4. Vendored packages & bundled data

### Vendored source (not available as installable packages)

All three live under `engine/vendor/`, sourced from
[`BibleNLP/greek-room`](https://github.com/BibleNLP/greek-room), pinned
commit `18ddcf0e6c03fa2774b73b21186115d712e4cba9` (USFM checker and
versification; SED vendored separately, no PyPI package exists under any
name for it either):

| Vendored dir | Source path in upstream repo | Why vendored, not `pip install` |
|---|---|---|
| `engine/vendor/greekroom-usfm/` | `greekroom/greekroom/usfm/` | Not published on PyPI at all — only `owl` and `gr_utilities` are part of the `greekroom` package; `usfm` exists only in the source tree. Monolithic CLI script — invoked via subprocess/temp-dir, not a direct Python import (path-sensitive internal import: `from ualign_utilities import ...`). |
| `engine/vendor/greekroom-versification/` | `greekroom/greekroom/versification/` | Same repo/commit as USFM. Unlike the USFM checker, this one **is** a genuine importable library, so it's wired in as a direct import. Its `data/standard_mappings/*.json` files carry **CC BY-SA 4.0**, a different license than the BSD-3-Clause code around them — real distinction to track, not a rubber-stamp of the USFM checker's licensing precedent. |
| `engine/vendor/greekroom-smart-edit-distance/` | `smart_edit_distance/` | Not published on PyPI under any name (checked `smart-edit-distance` and `smart_edit_distance`, neither exists), and not part of the `greekroom` PyPI package either. |

Each vendored directory has its own `NOTICE.md` with full provenance
(source URL, path, pinned commit, fetch date) — check those before updating
or re-vendoring anything.

### Bundled offline data (`engine/resources/`)

Bridge ships original-language source text and English translation-helps
data so a raw Scripture import produces real, working checks and alignment
targets **without any network access** — the whole premise is field teams
with unreliable connectivity.

| Path | Contents | Size | Source |
|---|---|---|---|
| `engine/resources/hbo/bibles/uhb/` | Hebrew OT tokens | ~3.9 MB | unfoldingWord UHB v3.0.0, checksum-verified, exact pinned commit |
| `engine/resources/el-x-koine/bibles/ugnt/` | Greek NT tokens | ~1.5 MB | unfoldingWord UGNT v0.34, checksum-verified, exact pinned commit |
| `engine/resources/en/translationHelps/` | translationNotes, translationWords, translationWordsLinks, translationAcademy | ~42 MB | Pinned English unfoldingWord snapshot (raw Door43 TSV for tN), matching real translationCore's own practice of shipping English checking helps in its installer |

All 66 books / 31,103 verses / 443,131 canonical tokens are covered.
Existing aligned USFM or native translationCore projects are **never**
overwritten by this baseline — it only fills empty source arrays and stops
outright on a resource-version mismatch for legacy raw-import recovery. Full
generation process and licensing (CC BY-SA 4.0, with attribution) is
documented alongside the resources and reproducible via
`npm run vendor:original-language`
(`scripts/vendor-original-language-resources.mjs`).

### Critical design boundary: tN/tW are not fabricated

Raw USFM contains Scripture, not translationNotes or translationWords
checks. translationCore imports Scripture first and materializes tool
indexes from installed, versioned checking resources afterward — Bridge
follows the same boundary. A raw import records
`requires-resource-index` until the first background-check preflight for
that book actually materializes real entries from the bundled data above;
Bridge never generates fake/empty check entries to fill the gap.

---

## 5. Where the deeper docs live

| Doc | Covers |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Full design rationale, protocol shape, `QaFinding` model. |
| [`BUILD_LOG.md`](BUILD_LOG.md) | Session-by-session build log — the ground truth for anything this guide summarizes. Also the current gotcha list and known-gaps list, verified as of each update. |
| [`IMPORTS.md`](IMPORTS.md) | Import pipeline design: supported inputs, normalized project schema, duplicate-safety logic, provenance. |
| [`ALIGNMENT.md`](ALIGNMENT.md) | Manual word-alignment protocol, persistence, completion states. |
| [`QA_TEST_MATRIX.md`](QA_TEST_MATRIX.md) | Release gate — what's tested, how, and current pass/fail status per release candidate. |
