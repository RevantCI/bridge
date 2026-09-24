//! Tauri commands exposed to the frontend via `invoke()`.
//!
//! Every BridgeEngine protocol method (engine/bridge_service.py) goes through
//! one generic command, `engine_call`, which forwards the method name and its
//! params to EngineSidecar::send_request unchanged. The frontend's api client
//! (src/lib/api/bridgeClient.ts) owns the typed surface: it names the method,
//! builds the params object the engine expects, and unwraps the envelope. The
//! per-method timeout table in sidecar.rs keys on the same method string, so
//! adding a protocol method is an engine handler plus one client line and no
//! Rust rebuild (#115; before it, 90 one-line forwarders lived here).
//!
//! The commands that stay named are the ones that are not engine calls: the
//! sidecar's own diagnostics log and the native OS file dialogs.

use crate::sidecar::EngineSidecar;
use serde_json::Value;
use tauri::State;
use tauri_plugin_dialog::DialogExt;

/// Forward one protocol request to bridge-engine. `method` is the engine's
/// method string (e.g. "project.open"); `params` is passed through verbatim,
/// and the engine's own dispatcher applies its defaults for absent keys (the
/// same defaults the removed Rust forwarders used to fill in). The result is
/// the raw engine envelope; bridgeClient.ts unwraps `success` / `result`.
#[tauri::command]
pub async fn engine_call(
    sidecar: State<'_, EngineSidecar>,
    method: String,
    params: Option<Value>,
) -> Result<Value, String> {
    sidecar
        .send_request(&method, params.unwrap_or_else(|| serde_json::json!({})))
        .await
}

#[tauri::command]
pub async fn engine_log_recent(
    sidecar: State<'_, EngineSidecar>,
    limit: Option<usize>,
) -> Result<Vec<crate::sidecar::LogEntry>, String> {
    Ok(sidecar.recent_log(limit.unwrap_or(200)).await)
}

#[tauri::command]
pub async fn pick_project_folder(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let (tx, rx) = tokio::sync::oneshot::channel();
    app.dialog().file().pick_folder(move |folder| {
        let _ = tx.send(folder.map(|f| f.to_string()));
    });
    rx.await
        .map_err(|e| format!("folder picker cancelled unexpectedly: {e}"))
}

#[tauri::command]
pub async fn pick_import_file(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let (tx, rx) = tokio::sync::oneshot::channel();
    app.dialog()
        .file()
        .add_filter(
            "Bible translation projects",
            &["usfm", "sfm", "txt", "tcore", "tstudio", "zip"],
        )
        .pick_file(move |file| {
            let _ = tx.send(file.map(|f| f.to_string()));
        });
    rx.await
        .map_err(|e| format!("file picker cancelled unexpectedly: {e}"))
}

/// A JSON file to read, e.g. a house-style export from another book
/// (layered-rules Phase 6.4, housestyle.import).
#[tauri::command]
pub async fn pick_json_file(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let (tx, rx) = tokio::sync::oneshot::channel();
    app.dialog()
        .file()
        .add_filter("JSON", &["json"])
        .pick_file(move |file| {
            let _ = tx.send(file.map(|f| f.to_string()));
        });
    rx.await
        .map_err(|e| format!("file picker cancelled unexpectedly: {e}"))
}

#[tauri::command]
pub async fn pick_save_path(
    app: tauri::AppHandle,
    default_name: String,
) -> Result<Option<String>, String> {
    let (tx, rx) = tokio::sync::oneshot::channel();
    app.dialog()
        .file()
        .set_file_name(&default_name)
        .save_file(move |path| {
            let _ = tx.send(path.map(|p| p.to_string()));
        });
    rx.await
        .map_err(|e| format!("save dialog cancelled unexpectedly: {e}"))
}
