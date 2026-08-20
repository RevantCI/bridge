Drop both PyInstaller-built worker binaries here, named per Tauri's
platform-suffix convention, e.g.:

  bridge-engine-x86_64-pc-windows-msvc.exe
  bridge-usfm-checker-x86_64-pc-windows-msvc.exe
  bridge-engine-x86_64-apple-darwin
  bridge-usfm-checker-x86_64-apple-darwin
  bridge-engine-aarch64-apple-darwin
  bridge-usfm-checker-aarch64-apple-darwin
  bridge-engine-x86_64-unknown-linux-gnu
  bridge-usfm-checker-x86_64-unknown-linux-gnu

Build it from /engine with:

  cd engine
  pip install -e ".[dev]"
  pyinstaller --clean --noconfirm bridge-engine.spec
  pyinstaller --clean --noconfirm bridge-usfm-checker.spec

Then copy both dist/bridge-engine and dist/bridge-usfm-checker (or their
.exe forms) into this folder with the correct target-triple suffix.
tauri.conf.json's bundle.externalBin entries pick them up automatically.

From the repository root, scripts/build-sidecars.ps1 performs both builds,
discovers the local Rust target triple, and copies both artifacts here.
