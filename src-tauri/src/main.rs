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
            commands::pick_import_file,
            commands::project_open,
            commands::project_list,
            commands::project_list_book_progress,
            commands::project_forget,
            commands::project_delete,
            commands::project_scan,
            commands::project_report,
            commands::project_collection_report,
            commands::project_inspect_import,
            commands::project_import,
            commands::chapter_verses,
            commands::chapter_verse_data,
            commands::checks_start,
            commands::checks_status,
            commands::checks_cancel,
            commands::checks_retry,
            commands::verse_get,
            commands::verse_run_checks,
            commands::verse_decide,
            commands::verse_edit,
            commands::check_list_for_verse,
            commands::check_validate_selection,
            commands::check_save_selection,
            commands::check_clear_selection,
            commands::issue_resolution_list,
            commands::issue_resolution_save,
            commands::issue_resolution_queue_paratext,
            commands::issue_resolution_retry_paratext,
            commands::alignment_get,
            commands::alignment_status,
            commands::alignment_realign,
            commands::alignment_unalign,
            commands::alignment_save,
            commands::alignment_complete,
            commands::alignment_undo,
            commands::alignment_backups,
            commands::alignment_restore,
            commands::lexicon_get_entry,
            commands::alignment_ai_propose,
            commands::alignment_ai_apply_proposal,
            commands::ai_explain,
            commands::ai_review_start,
            commands::ai_review_status,
            commands::ai_review_cancel,
            commands::ai_review_retry,
            commands::ai_review_list_chapter,
            commands::paratext_get_state,
            commands::paratext_set_reference,
            commands::logos_get_state,
            commands::logos_set_reference,
            commands::settings_get,
            commands::settings_set,
            commands::pick_save_path,
            commands::export_aligned,
            commands::export_non_aligned,
        ])
        .run(tauri::generate_context!())
        .expect("error while running translationCore AI Bridge");
}
