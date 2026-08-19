# Bridge

Local-first translation QA workbench. Greek Room (Wildebeest, OWL, USFM,
Uroman, alignment statistics) and the existing translationCore business
logic (project reading, alignment, Paratext/Logos connectors, transaction
safety) both run inside one Python sidecar (`BridgeEngine`); the desktop
shell is Tauri + Svelte. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for the full design rationale and roadmap.

## Repo layout

```
engine/           BridgeEngine sidecar (GreekRoomEngine + tc_ai_bridge, one protocol)
src/              Svelte frontend
src-tauri/        Rust shell (spawns + talks to the sidecar)
docs/             Architecture notes
```

## Getting started

### 1. Python engine

```bash
cd engine
pip install -e ".[dev]"
pytest tests/ greek_room_engine/tests/ -v
```

Should show **17 passed**. Try `python demo.py` for a live walkthrough
against a throwaway fixture project — no real translationCore project
needed.

Sanity-check the stdio protocol directly:

```bash
echo '{"id":"1","method":"ping","params":{}}' | python main.py
```

### 2. Frontend (dev mode, without Tauri)

```bash
npm install
npm run build     # should be 0 errors
npm run dev        # browser-viewable dev server at localhost:1420
```

Without Tauri, `bridge.ping()` etc. will fail (no sidecar to talk to) —
but you'll see the UI shell render.

### 3. Full desktop app

Requires the Rust toolchain (rustup.rs) plus, on Windows, the
**Desktop development with C++** workload via Visual Studio Build Tools
(Tauri needs the MSVC linker — installing Rust alone isn't enough).

```bash
cd engine
pyinstaller --onefile --name bridge-engine main.py
# copy dist/bridge-engine(.exe) into src-tauri/binaries/ with the correct
# target-triple suffix (check yours with `rustc -vV`, look at `host:`)
# e.g. bridge-engine-x86_64-pc-windows-msvc.exe
# see src-tauri/binaries/README.txt

cd ..
npm install
npm run tauri dev
```

## Current status: v0.8.1 — Phase 2 (Svelte frontend wired to real sidecar)

**Verified end-to-end, including on a real Windows machine (not just this build environment):**
- ✅ `BridgeEngine` — 17/17 pytest, real fixture project, real file writes (Phase 1)
- ✅ Svelte frontend — `npm run build` and `svelte-check` both clean, 0 errors, 0 warnings
- ✅ `cargo tauri dev` — compiles and launches an actual window on Windows (MSVC toolchain)
- ✅ Real components: `ImportScreen`, `TopBar`, `VerseList` (renders findings as real inline colored marks using actual `start_offset`/`end_offset`), `ReviewPanel` (live Greek Room re-check on verse focus, Accept/Reject/Ignore wired to real `verse.decide`, Edit wired to real `verse.edit`)
- ✅ `QAIssue` → `QaFinding` category mapping tested against the *actual* codes `local_checks.py` produces
- ✅ Windows console UTF-8 fix — Tamil/Hebrew verse text no longer crashes the sidecar's stdout (see Troubleshooting below)

**Pending reconfirmation:**
- ⬜ Full click-through on a real translationCore project (open → verse list populates → findings show) after the UTF-8 fix — the fix is in and unit-verified, but hasn't yet been reconfirmed against a real project folder end-to-end. Next thing to check.

**Known incomplete (by design, not bugs):**
- ⬜ Native drag-and-drop file import — Tauri's webview doesn't expose real filesystem paths via the browser `DragEvent` API for security reasons; `ImportScreen.svelte` shows an honest error on drop and directs to the working "Browse for folder" button (real native dialog, wired). Needs `@tauri-apps/api`'s `onDragDropEvent` listener instead — flagged as a follow-up.
- ⬜ Settings modal, Export modal — currently placeholder text in `App.svelte`; not yet built out to match the approved wireframe.

## Troubleshooting (real issues hit getting this running on Windows)

These bit us once already — check here before re-debugging from scratch.

- **`icons/icon.ico` not found during `cargo tauri dev`** — Tauri needs real icon files at the paths listed in `tauri.conf.json`'s `bundle.icon`. Placeholder icons are included in this repo (`src-tauri/icons/`); if they're ever deleted, regenerate with any image tool and re-list them there.
- **`unknown field 'sidecar', expected 'open'` in `plugins.shell`** — an invalid `"plugins": {"shell": {"sidecar": true}}` block does not belong in `tauri.conf.json`. Sidecar execution permission comes entirely from `src-tauri/capabilities/default.json`'s `shell:allow-execute` entry. If you see this error, check `tauri.conf.json` for a stray `"plugins"` block and delete it.
- **`sidecar request 'verse.get' timed out`** on a real project — almost always means the Python sidecar crashed on printing non-ASCII (Tamil/Hebrew/etc) verse text to a Windows console stdout, which defaults to a legacy codepage, not UTF-8. Fixed in `stdio_transport.py` via explicit `sys.stdout.reconfigure(encoding="utf-8")` — if you ever refactor that file, keep the reconfigure calls at the top of `run_stdio_loop`.
- **`pip install -e ".[dev]"` fails with `Could not find a version that satisfies the requirement install`** — this means pip received extra stray arguments, almost always from PowerShell's PSReadLine predictive-text duplicating a pasted command. Retype the command directly instead of pasting, or press `Esc` before pasting to clear ghost suggestion text.
- **`cargo metadata ... program not found`** even though `cargo --version` works in another window — the current PowerShell session was opened before Rust's PATH changes applied. Close and open a fresh terminal window; Windows doesn't refresh an already-open shell's environment variables.

## `.gitignore`

A `.gitignore` tailored to this repo's actual Python + Rust/Tauri + Svelte
structure is included at the repo root. Notably: `Cargo.lock` and
`package-lock.json` are deliberately **not** ignored (commit them — this
is an application, reproducible builds matter), but compiled sidecar
`.exe` files, `node_modules/`, and `target/` are.
