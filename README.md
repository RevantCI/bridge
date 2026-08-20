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

## Importing Scripture

The desktop import screen accepts individual USFM/SFM files, multi-book or
Paratext folders, and translationCore/translationStudio project archives. It
previews detected books, asks the user to confirm language/Project/Bible details,
and provides an offline searchable ISO 639-3 language catalog. See
[`docs/IMPORTS.md`](docs/IMPORTS.md) for the normalized project schema, supported
alignment import, provenance safeguards, and the separate tN/tW resource-indexing
stage.

## Getting started

### Prerequisites

- **Python 3.11 or newer** for the BridgeEngine sidecar.
- **Node.js 18 or newer** and npm for the Svelte frontend.
- For the full desktop app, the **Rust toolchain** from
  [rustup.rs](https://rustup.rs/).
- On Windows, the **Desktop development with C++** workload from Visual
  Studio Build Tools. Tauri needs the MSVC compiler and linker.

The Python and Node.js dependencies only need to be installed once (and
again whenever their dependency files change).

### 1. Python engine

```bash
cd engine
pip install -e ".[dev]"
pytest tests/ greek_room_engine/tests/ -v
```

Should show **52 passed, 1 skipped** without the optional real Wildebeest
extra. Try `python demo.py` for a live walkthrough
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
npm run dev       # browser-viewable dev server at localhost:1420
```

This starts only the frontend UI. Without Tauri, `bridge.ping()` and other
engine-backed features will fail because there is no sidecar process. Use
this mode for frontend work; use the next section to run the functional app.

### 3. Full desktop app

Requires the Rust toolchain (rustup.rs) plus, on Windows, the
**Desktop development with C++** workload via Visual Studio Build Tools
(Tauri needs the MSVC linker — installing Rust alone isn't enough).

From the repository root on 64-bit Windows with the MSVC toolchain:

```powershell
npm install
.\scripts\build-sidecars.ps1
npm run tauri dev
```

The build script creates and copies **two** target-suffixed executables:
the long-lived JSON-RPC `bridge-engine` and the isolated
`bridge-usfm-checker`. Both are required; the frozen engine deliberately
does not try to execute a Python script through itself.

Verify the frozen process boundary directly:

```powershell
python scripts\smoke_sidecars.py `
  engine\dist\bridge-engine.exe
```

The smoke fixture has balanced markers but duplicate and missing verses,
so only the real whole-book checker can make it pass.

For another platform, the build script reads the `host:` value from
`rustc -vV` and applies the target triple to both generated filenames.
Omit `.exe` on macOS and Linux; see `src-tauri/binaries/README.txt` for
filename examples.

`npm run tauri dev` starts the frontend development server, compiles the Rust
shell, launches the sidecar, and opens the Bridge desktop window.

## Current development status: Phase 3 (decision persistence, whole-book, Settings & Export)

**New in this phase, all verified (24/24 pytest, clean Svelte build + type-check):**
- ✅ **Stable finding IDs** — findings previously got a random id every time checks ran, so a saved decision could never be matched back later. Fixed via deterministic ids; proven with a real accept → re-check → still-accepted test.
- ✅ **Decision persistence** — reopening a project or re-running checks now correctly restores prior Accept/Reject/Ignore state instead of resetting to "open".
- ✅ **Chapter switching** — the top bar's chapter dropdown actually works now (it didn't before).
- ✅ **"Run whole book"** — wired to actually load and check every chapter, with per-chapter progress. Store keys are now `chapter:verse` composite (`verseKey()` in `stores.ts`) so multiple chapters' data can coexist without collisions.
- ✅ **Settings modal, for real** — AI provider pane supports **any OpenAI-Responses-API-compatible endpoint**, not just OpenAI: Provider / Base URL / Model / API key are all freely editable and persist via `settings.get`/`settings.set`. Also made `ai_client.py`'s endpoint configurable (was hardcoded to `api.openai.com`) — though note `ai_client.py` still isn't called by any protocol method yet (that's Phase 7); this is groundwork, not a live AI connection.
- ✅ **Export modal, for real** — two working exporters: `export.aligned` (full JSON: text + alignment + decisions per verse, nothing simplified) and `export.nonAligned` (simplified USFM reconstruction — `\id`/`\c`/`\v` markers only). Export is enabled only once every chapter in the whole book is loaded and approved.

**Known, deliberate scope limits (not bugs):**
- `export.nonAligned`'s USFM is a real reconstruction from `target_chapter()` data, but does **not** preserve the original file's footnotes, section headers, or poetry markup — that structure isn't tracked per-verse anywhere in the current data model. Documented in the exporter's own docstring.
- "Any API" in Settings means any endpoint speaking the OpenAI Responses API shape — not literally any provider's native request format (e.g. raw Anthropic API has a different schema).

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
