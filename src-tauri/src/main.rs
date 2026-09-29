// Prevents an additional console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;
mod sidecar;

use sidecar::EngineSidecar;
use tauri::Manager;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(EngineSidecar::new())
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let sidecar = handle.state::<EngineSidecar>();
                if let Err(e) = sidecar.start(&handle).await {
                    eprintln!("Failed to start GreekRoomEngine sidecar: {e}");
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::engine_call,
            commands::engine_log_recent,
            commands::pick_project_folder,
            commands::pick_import_file,
            commands::pick_json_file,
            commands::pick_save_path,
        ])
        .build(tauri::generate_context!())
        .expect("error while running translationCore AI Bridge")
        // The sidecar is built to outlive any single request and nothing used
        // to stop it, so every closed window (and every Ctrl+C'd `tauri dev`)
        // left a bridge-engine.exe running. Besides the stray process, it kept
        // an open handle on the executable, which made the *next* build fail
        // inside tauri-build with a bare "Access is denied" as it tried to
        // refresh target/'s copy of that binary.
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                app.state::<EngineSidecar>().shutdown(app);
            }
        });
}
