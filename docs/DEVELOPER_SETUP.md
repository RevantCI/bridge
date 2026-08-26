# Developer Setup

Practical guide to getting Bridge running on a dev machine, building it, and
running the test suite. For *why* things are built this way, see
[`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) and [`ARCHITECTURE.md`](ARCHITECTURE.md).
For QA/release sign-off, see [`QA_TEST_MATRIX.md`](QA_TEST_MATRIX.md).

Windows is the primary, maintained target (`x86_64-pc-windows-msvc`).
macOS/Linux are planned but not the day-to-day dev environment yet.

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.12** | Required, not 3.11 or 3.13. Package metadata allows 3.11+, but the real `wildebeest-nlp` dependency fails to compile under 3.13 (a docstring escape CPython 3.13 newly rejects). |
| **Node.js 18+** and npm | For the Svelte frontend. |
| **Rust toolchain** ([rustup.rs](https://rustup.rs/)) | Only needed for the full desktop app, not frontend-only work. |
| **Windows: Desktop development with C++** workload (Visual Studio Build Tools) | Tauri needs the MSVC linker — installing Rust alone is not enough. |

Python and Node dependencies only need installing once (and again when their
dependency files change).

## 1. Python engine

```powershell
cd engine
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -c constraints-py312-windows.txt -e ".[dev,wildebeest]"
.venv\Scripts\python.exe -m pytest tests/ greek_room_engine/tests/ -v
```

Expect **224 passed** on the maintained Windows/Python 3.12 environment
(baseline as of 2026-08-26).

Try `python demo.py` for a live walkthrough against a throwaway fixture
project — no real translationCore project needed. Good first smoke test on a
new machine.

Sanity-check the stdio protocol directly:

```powershell
echo '{"id":"1","method":"ping","params":{}}' | python main.py
```

## 2. Frontend only (browser dev server, no Tauri)

```powershell
npm install
npm run build     # should be 0 errors
npm run dev        # localhost:1420
```

This starts only the frontend UI. Without Tauri there's no sidecar process,
so `bridge.ping()` and other engine-backed calls will fail — expected. Use
this mode for pure frontend/UI work; use section 3 for anything that needs
the real engine.

## 3. Full desktop app

Requires the Rust toolchain plus, on Windows, the Desktop development with
C++ workload (see Prerequisites — Tauri needs the MSVC linker).

From the repo root, on 64-bit Windows with the MSVC toolchain:

```powershell
npm install
.\scripts\build-sidecars.ps1
npm run tauri dev
```

`npm run tauri dev` starts the frontend dev server, compiles the Rust shell,
launches the sidecar, and opens the Bridge desktop window.

`build-sidecars.ps1` produces **two** target-suffixed executables — both
required:

- `bridge-engine` — the long-lived JSON-RPC sidecar.
- `bridge-usfm-checker` — an isolated executable for the USFM structural
  checker (the frozen `bridge-engine` deliberately does not try to execute a
  Python script through itself).

The script reads the target triple from `rustc -vV`'s `host:` value and
applies it to both filenames (e.g.
`bridge-engine-x86_64-pc-windows-msvc.exe`). For another platform, omit
`.exe`; see `src-tauri/binaries/README.txt` for examples.

Verify the frozen process boundary directly (useful when something passes
`pytest` but misbehaves in the packaged app):

```powershell
python scripts\smoke_sidecars.py engine\dist\bridge-engine.exe
```

The smoke fixture exercises the frozen manual-alignment protocol, aligned
USFM export and undo, then checks balanced-marker Scripture containing
duplicate and missing verses — only the real whole-book checker can make it
pass.

## Building a distributable installer

A packaged Windows build produces an NSIS installer (see
[`QA_TEST_MATRIX.md`](QA_TEST_MATRIX.md) for the current beta acceptance
status and exact artifact hashes). Run the Tauri bundler
(`npm run tauri build`) after the sidecars are built; consult
`src-tauri/tauri.conf.json`'s `bundle` config for target settings.

## `.gitignore` conventions

`Cargo.lock` and `package-lock.json` are deliberately **committed** — this is
an application, not a library, so reproducible builds matter more than lock
flexibility. Compiled sidecar `.exe` files, `node_modules/`, and `target/`
are ignored.

## Troubleshooting (real issues hit getting this running on Windows)

These have actually happened on this project — check here before
re-debugging from scratch.

- **`icons/icon.ico` not found during `cargo tauri dev`** — Tauri needs real
  icon files at the paths listed in `tauri.conf.json`'s `bundle.icon`.
  Placeholder icons are committed at `src-tauri/icons/`; if they're ever
  deleted, regenerate with any image tool and re-list them there.
- **`unknown field 'sidecar', expected 'open'` in `plugins.shell`** — an
  invalid `"plugins": {"shell": {"sidecar": true}}` block does not belong in
  `tauri.conf.json`. Sidecar execution permission comes entirely from
  `src-tauri/capabilities/default.json`'s `shell:allow-execute` entry. If you
  see this error, check `tauri.conf.json` for a stray `"plugins"` block and
  delete it.
- **`sidecar request 'verse.get' timed out`** on a real project — almost
  always means the Python sidecar crashed printing non-ASCII (Tamil/Hebrew/
  etc.) verse text to a Windows console stdout, which defaults to a legacy
  codepage, not UTF-8. Fixed in `stdio_transport.py` via explicit
  `sys.stdout.reconfigure(encoding="utf-8")` — if you ever refactor that
  file, keep the reconfigure calls at the top of `run_stdio_loop`.
- **`pip install -e ".[dev]"` fails with `Could not find a version that
  satisfies the requirement install`** — this means pip received extra stray
  arguments, almost always from PowerShell's PSReadLine predictive-text
  duplicating a pasted command. Retype the command directly instead of
  pasting, or press `Esc` before pasting to clear ghost suggestion text.
- **`cargo metadata ... program not found`** even though `cargo --version`
  works in another window — the current PowerShell session was opened before
  Rust's PATH changes applied. Close and open a fresh terminal window;
  Windows doesn't refresh an already-open shell's environment variables.

## Code-level gotchas (won't show up as install errors, but will cost you an hour)

1. `TranslationCoreProject.summary` is a `@property`, not a method — calling
   `summary()` crashes.
2. `TranslationCoreProject.__init__` creates its own `self.journal`. Never
   create a second one.
3. Finding ids are stable (`_stable_finding_id()` in `bridge_service.py`, a
   sha1 of `chapter:verse:engine:check_type:disambiguator`) so decisions
   persist across runs. Don't revert to random `uuid4()` ids.
4. `verse.runChecks` re-applies prior decisions from
   `qa_decisions_for_verse()` after running checks — this must stay in the
   check flow, not a separate call.
5. Store keys are composite `chapter:verse` (e.g. `"1:3"`) — use
   `verseKey()` from `stores.ts`, not verse-only keys (silently collides data
   across chapters).
6. `ai_client.py`'s `OpenAIResponsesClient` endpoint is configurable via
   `base_url`; don't reintroduce a hardcoded `ENDPOINT` constant.
7. The sidecar binary name must match the Rust target triple exactly.
8. Don't use icon-font classes (`ti-settings` etc.) for icon-only controls
   with no fallback label — PyInstaller/offline builds can't reach CDN icon
   fonts and they render as empty boxes. Use Unicode characters or pair with
   a text label.
9. The USFM checker has a path-sensitive internal import
   (`from ualign_utilities import ...`) — wrap it via CLI/temp-dir, don't
   import it directly.
10. Every external integration attempted so far (Wildebeest, the USFM
    checker, versification) turned out to have a real, non-obvious problem
    that only surfaced by actually running the code. **Don't trust a
    dependency's own docs — install it, run it against real input, and read
    what actually happens before writing an adapter around it.** The same
    applies to this repo's own docs: verify claims against the actual code
    before relying on them.

## Running the QA gate

- Python: `pytest tests/ greek_room_engine/tests/ -v` from `engine/` — expect
  224 passed on the current baseline.
- Svelte: `npm run check` (svelte-check) and `npm run build`.
- Rust: standard `cargo build`/`cargo test` inside `src-tauri/`.
- Full release acceptance (frozen sidecars, NSIS installer, exact artifact
  hashes): [`docs/QA_TEST_MATRIX.md`](QA_TEST_MATRIX.md).
