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
            commands::engine_ping,
            commands::engine_info,
            commands::pick_project_folder,
            commands::project_open,
            commands::project_scan,
            commands::chapter_verses,
            commands::chapter_verse_data,
            commands::verse_get,
            commands::verse_run_checks,
            commands::verse_decide,
            commands::verse_edit,
            commands::settings_get,
            commands::settings_set,
        ])
        .run(tauri::generate_context!())
        .expect("error while running translationCore AI Bridge");
}
