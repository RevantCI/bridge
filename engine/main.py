"""
Entrypoint for the Bridge sidecar process.

Bundled via PyInstaller into a standalone executable (no Python runtime
required on the translator's machine). Tauri spawns this once at app
startup and keeps it alive for the whole session (doc §4).

    pyinstaller --onefile --name bridge-engine main.py
"""
from bridge_service import BridgeEngine
from greek_room_engine.transport.stdio_transport import run_stdio_loop

if __name__ == "__main__":
    run_stdio_loop(BridgeEngine())
