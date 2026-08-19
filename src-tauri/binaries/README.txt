Drop the PyInstaller-built sidecar binary here, named per Tauri's
platform-suffix convention, e.g.:

  bridge-engine-x86_64-pc-windows-msvc.exe
  bridge-engine-x86_64-apple-darwin
  bridge-engine-aarch64-apple-darwin
  bridge-engine-x86_64-unknown-linux-gnu

Build it from /engine with:

  cd engine
  pip install -e ".[dev]"
  pyinstaller --onefile --name bridge-engine main.py

Then copy dist/bridge-engine (or .exe) into this folder with the
correct target-triple suffix. tauri.conf.json's bundle.externalBin
entry ("binaries/bridge-engine") picks it up automatically for
whichever platform you're building on.
