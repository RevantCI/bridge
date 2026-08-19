# translationCore AI Bridge

Local-first translation QA workbench. Greek Room (Wildebeest, OWL, USFM,
Uroman, alignment statistics) runs as an offline Python sidecar; the
desktop shell is Tauri + React. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for the full design rationale and roadmap.

## Repo layout

```
engine/           Python GreekRoomEngine package (the sidecar)
src/              React frontend
src-tauri/        Rust shell (spawns + talks to the sidecar)
docs/             Architecture notes
```

## Getting started

### 1. Python engine

```bash
cd engine
pip install -e ".[dev]"
pytest greek_room_engine/tests/ -v
```

Sanity-check the stdio protocol directly:

```bash
echo '{"id":"1","method":"ping","params":{}}' | python main.py
```

### 2. Frontend (dev mode, without Tauri)

```bash
npm install
npm run dev
```

Runs against `HttpTransport` unless a Tauri context is detected — useful
for iterating on UI without the Rust build.

### 3. Full desktop app

Requires the Rust toolchain (not available in the scaffolding environment
this was generated in — verify `cargo build` works on your machine first).

```bash
# Build the sidecar binary
cd engine
pyinstaller --onefile --name greek-room-engine main.py
# Copy dist/greek-room-engine into src-tauri/binaries/ with the correct
# target-triple suffix — see src-tauri/binaries/README.txt

cd ..
npm install
npm run tauri dev
```

## Current status: v0.8.1 — Phase 2 in progress (Svelte frontend wired to real sidecar)

**Verified working (in this build environment):**
- ✅ `BridgeEngine` — 17/17 pytest, real fixture project, real file writes (Phase 1)
- ✅ Svelte frontend — `npm run build` and `svelte-check` both clean, 0 errors, 0 warnings
- ✅ Vite dev server boots and serves correctly
- ✅ Real components: `ImportScreen`, `TopBar`, `VerseList` (renders findings as real inline colored marks using actual `start_offset`/`end_offset`, not hardcoded demo spans), `ReviewPanel` (live Greek Room re-check on verse focus, Accept/Reject/Ignore wired to real `verse.decide`, Edit wired to real `verse.edit`)
- ✅ `QAIssue` → `QaFinding` category mapping fixed and tested against the *actual* codes `local_checks.py` produces (tN/tW/Alignment color-coding is now correct, not guessed)

**NOT verified — needs your machine:**
- ⬜ `cargo tauri dev` — no Rust toolchain in this environment. Rust command layer (`commands.rs`) was rewritten to call real `BridgeEngine` methods but has never compiled.
- ⬜ Native drag-and-drop file import — Tauri's webview doesn't expose real filesystem paths via the browser `DragEvent` API for security reasons; `ImportScreen.svelte` currently shows an honest error message on drop and directs to the working "Browse for folder" button (uses Tauri's native dialog, which **is** wired to a real backend call). Wiring real drag-drop needs `@tauri-apps/api`'s `onDragDropEvent` listener — flagged as a follow-up, not silently faked.
- ⬜ Settings modal, Export modal — currently placeholder text in `App.svelte`; `SettingsModal.svelte`/`ExportModal.svelte` components not yet built out to match the wireframe

### Running the frontend alone (no Tauri, no Rust needed)

```bash
npm install
npm run build      # verify it compiles — should be 0 errors
npm run dev         # starts a browser-viewable dev server at localhost:1420
```

Note: without Tauri, `bridge.ping()` etc. will fail since there's no sidecar to talk to — but you'll see the UI shell and can confirm it renders.

### Running the full desktop app (needs Rust + Node)

```bash
cd engine
pyinstaller --onefile --name bridge-engine main.py
# copy dist/bridge-engine(.exe) into src-tauri/binaries/ with the correct
# target-triple suffix — see src-tauri/binaries/README.txt

cd ..
npm install
npm run tauri dev
```

This last step has not been run anywhere yet — it's the next real risk to retire, same as `pytest` was for Phase 1.
