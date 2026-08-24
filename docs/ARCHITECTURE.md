# translationCore AI Bridge — Architecture

## Core principle

> Our application owns the workflow, UI, project state, human decisions and AI.
> Greek Room is a local, offline QA/NLP engine underneath it.

Three-way division of responsibility, never blurred:

- **Greek Room** says: "This is objectively/statistically suspicious."
- **AI** says: "Here is what it may mean in this passage."
- **Human** says: "This is what the translation should be."

Findings are never auto-applied to project files. Everything funnels through
a `QaFinding` with an explicit human-review `status` (open → accepted /
rejected / ignored / fixed / needs_discussion).

## Stack decision: Tauri (not Electron, not Python+Tkinter)

- **vs. Electron**: Tauri uses the OS's native webview instead of bundling
  Chromium — smaller binary, faster cold start, lower idle memory. Matters
  for an all-day desktop tool on modest field hardware.
- **vs. Python+Tkinter**: the wireframe is a real product UI (colored status
  badges, inline findings, tabbed panels) that a native widget toolkit
  fights rather than enables. A Tauri frontend is a web app (React), which
  also gives a direct path to a future web deployment — Tkinter has none.
- **Trade-off accepted**: Rust has a learning curve if the team has none;
  most day-to-day work stays in the Python engine and React frontend layers
  though, not the (intentionally thin) Rust shell.

## Process boundary

```
Bridge.exe                      (Tauri/Rust shell + Svelte frontend)
        │
        │ spawns once at startup, JSON-lines over stdin/stdout
        ▼
bridge-engine                    (PyInstaller-bundled Python sidecar)
        │
        ▼
   Wildebeest / standalone USFM checker / translationCore project logic
```

The sidecar starts once and stays alive for the whole session — NLP
resources (Wildebeest corpus properties, Uroman tables, etc.) are loaded
once, not per call. **Verified 2026-08-21** (see `docs/DEVELOPER_HANDOFF.md`'s
Phase 5 research breadcrumb): `uroman.Uroman()` construction takes ~1.8-2.1s
on real hardware to load its full romanization table set, after which
`romanize_string()` calls measured effectively instant — this recommendation
was real and worth following, not just an assumed best practice.

**Never integrated directly**: Greek Room's `ephesus/` web API (Docker,
database, its own web UI). We only use the underlying check modules.

## Protocol

Transport-agnostic JSON request/response, defined once in
`engine/greek_room_engine/protocol.py`:

```json
// request
{ "id": "...", "method": "verse.check", "params": { ... } }

// response
{ "id": "...", "success": true, "findings": [ QaFinding, ... ] }
```

- **Desktop transport**: stdio, via `transport/stdio_transport.py` (Python
  side) and `src-tauri/src/sidecar.rs` (Rust side, correlates responses to
  requests by `id` using oneshot channels).
- **Web transport (future)**: `transport/http_transport.py` wraps the same
  `GreekRoomEngine.handle_request()` behind an HTTP endpoint (e.g. FastAPI).
  The frontend's `src/api/engineClient.ts` already branches on `isTauri` to
  select `DesktopTransport` vs `HttpTransport` — extending web support means
  standing up the HTTP wrapper, not redesigning the protocol or rewriting
  UI components.

## The `QaFinding` model

Single universal result shape (`engine/greek_room_engine/models/finding.py`,
mirrored in `src/types/finding.ts`). Every checker — Wildebeest, OWL, USFM,
alignment stats, or a future AI explainer — normalizes into this. The UI
never needs to special-case which engine produced a finding.

## Adapter boundary — why it matters

Greek Room is Alpha (`pyproject.toml` currently at `0.0.20`, with visible
package-layout churn). Our app **never** imports Greek Room's internal
modules directly. Every engine gets a thin `CheckAdapter` subclass
(`engine/greek_room_engine/adapters/`) that:

1. Normalizes that engine's native output into `QaFinding[]`
2. Fails soft (`is_available()`) rather than crashing the whole request if
   the upstream package isn't installed
3. Isolates us from upstream's internal churn — when Greek Room updates, we
   pin an exact upstream commit, run a regression corpus, and only then
   bump the adapter

`WildebeestAdapter` currently ships with a **mock fallback** so protocol,
caching, and UI work isn't blocked on the real `wildebeest` pip package
being wired in yet. Swap in the real import (see the `_WILDEBEEST_AVAILABLE`
branch) when ready — `is_available()` deliberately returns `True` either
way, but `using_real_engine()` tells you (and the UI, via `engine.info`)
which mode is actually active.

## Roadmap (from the original design doc)

| Version | Scope | Status |
|---|---|---|
| **v0.7.5** | `GreekRoomEngine` sidecar, stable JSON protocol, `QaFinding` model, Wildebeest (mock fallback). | ✅ Built |
| **v0.8.0-beta.1** | Real sidecar/UI core loop, fast multi-book import, background QA jobs, persistent decisions and edits, standalone USFM checker, manual word-alignment editor, aligned/non-aligned USFM export. | Release candidate |
| v0.8.x | Stabilization: installed-build UX/accessibility and large-project performance acceptance. | Next |
| v0.9.0 | Versification plus Uroman/Smart Edit Distance name consistency. | ✅ Built |
| v0.9.x | Alignment Intelligence — AI proposals and UAlign-derived statistics from human-approved alignments. | Split: statistics ✅ Built (2026-08-24, backend/protocol-only, no UI); AI proposals still Planned (Phase 7) |
| v1.0.x | Paratext/Logos live navigation and optional AI + Greek Room synthesis. | Planned |

## Phase 1 outcome: BridgeEngine

`engine/bridge_service.py` is the actual sidecar dispatcher now (see `main.py`). It composes:

- `GreekRoomEngine` — offline QA adapters (unchanged from v0.7.5)
- `tc_ai_bridge` — the existing 29 business-logic modules, copied in unmodified except for excluding `ui.py` and `__main__.py` (confirmed via import test that nothing else depends on those two files)

Key implementation notes discovered while wiring this up (worth knowing before extending it further):

- `TranslationCoreProject.summary` is a **property**, not a method.
- `TranslationCoreProject.__init__` already creates its own `self.journal` (a `TransactionJournal` scoped to the right `companion_dir()`) — don't create a second one.
- Decision persistence already exists and is correct: `record_qa_decision()` / `qa_decisions_for_verse()` write atomic, audited JSON under `companion_dir()/qaDecisions/...`. `BridgeEngine.decide_verse()` calls these directly rather than reinventing an in-memory store.
- All of this was verified against a **real fixture project** built directly from reading `TranslationCoreProject`'s actual parsing code (see `tests/test_bridge_service.py`), not assumed — including a real transaction-journal backup being created on `verse.edit` and a real QA-decision JSON file landing on disk on `verse.decide`.

Protocol methods implemented so far: `ping`, `engine.info`, `project.open`,
`project.scan`, `project.inspectImport`, `project.import`, `chapter.verses`,
`chapter.verseData`, `checks.start/status/cancel/retry`, `verse.get/runChecks/decide/edit`,
`alignment.get/status/realign/unalign/save/complete/undo/backups/restore`,
`settings.get/set`, `export.aligned`, and `export.nonAligned`.

Not yet wired (real logic exists in `tc_ai_bridge` but no protocol method calls it yet): Paratext/Logos connectors, AI client (`ai_client.py`), Git service, reporting, terminology/Psalms QA. These are Phase-appropriate follow-ups per the table above, not gaps in the design.

## Explicit non-goals (for now)

- No automatic file modification. Suggestions only; "Apply" is a
  post-v0.7.5 feature requiring undo entries + re-verification of flagged
  text before writing.
- No neural retraining. "Human approvals become corpus evidence" means
  local statistical recomputation (fertility, PMI, frequency), not model
  training.
- No dependency on an AI API for core QA. Greek Room checks must work with
  zero internet connectivity; only the optional "Explain with AI" layer is
  online.

## What still needs a real decision

- Exact upstream Greek Room commit to pin (`third_party/greek-room/UPSTREAM_COMMIT.txt`)
- License inventory before distribution (Greek Room is BSD-3-Clause at the
  repo root but the `greekroom` package classifier says Apache — reconcile
  before shipping; Uroman has its own attribution requirement — **verified
  2026-08-21**: both the PyPI wheel and upstream's own `pyproject.toml`
  classify it "Apache Software License", but the actual bundled
  `LICENSE.txt` is not Apache 2.0 text — it's a custom MIT-style permissive
  license requiring a specific acknowledgment sentence in any publication
  using it. Same classifier-drift pattern as `greekroom`, not a new problem
  shape. See `docs/DEVELOPER_HANDOFF.md`'s Phase 5 breadcrumb.)
- Real `wildebeest`/`greekroom` pip packages need to be added to
  `engine/pyproject.toml` and the mock fallback in `WildebeestAdapter`
  replaced/validated against real output
- Rust/Tauri toolchain wasn't available in the scaffolding environment —
  `cargo build` in `src-tauri/` has not been verified to compile; do this
  first on a real dev machine
