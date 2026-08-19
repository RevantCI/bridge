//! Tauri commands exposed to the frontend via `invoke()`.
//!
//! These are thin wrappers around EngineSidecar::send_request, matching
//! BridgeEngine's actual protocol methods (engine/bridge_service.py) —
//! not the old Greek-Room-only placeholder commands from v0.7.5. Keeping
//! this layer thin means swapping the transport later (e.g. HTTP for a
//! web build) only touches the frontend's api client, not these command
//! signatures. See docs/ARCHITECTURE.md for the web deployment note.

use crate::sidecar::EngineSidecar;
use serde_json::Value;
use tauri::State;
use tauri_plugin_dialog::DialogExt;

#[tauri::command]
pub async fn engine_ping(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar.send_request("ping", serde_json::json!({})).await
}

#[tauri::command]
pub async fn engine_info(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar.send_request("engine.info", serde_json::json!({})).await
}

/// Opens the native OS folder picker and returns the chosen path, or null
/// if the user cancelled. Separate from project_open so the frontend can
/// show the picker immediately without waiting on the sidecar.
#[tauri::command]
pub async fn pick_project_folder(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let (tx, rx) = tokio::sync::oneshot::channel();
    app.dialog().file().pick_folder(move |folder| {
        let _ = tx.send(folder.map(|f| f.to_string()));
    });
    rx.await.map_err(|e| format!("folder picker cancelled unexpectedly: {e}"))
}

#[tauri::command]
pub async fn project_open(sidecar: State<'_, EngineSidecar>, path: String) -> Result<Value, String> {
    sidecar.send_request("project.open", serde_json::json!({ "path": path })).await
}

#[tauri::command]
pub async fn project_scan(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar.send_request("project.scan", serde_json::json!({})).await
}

#[tauri::command]
pub async fn chapter_verses(sidecar: State<'_, EngineSidecar>, chapter: String) -> Result<Value, String> {
    sidecar.send_request("chapter.verses", serde_json::json!({ "chapter": chapter })).await
}

#[tauri::command]
pub async fn verse_get(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
) -> Result<Value, String> {
    sidecar
        .send_request("verse.get", serde_json::json!({ "chapter": chapter, "verse": verse }))
        .await
}

#[tauri::command]
pub async fn verse_run_checks(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    checks: Vec<String>,
) -> Result<Value, String> {
    let params = serde_json::json!({ "chapter": chapter, "verse": verse, "checks": checks });
    sidecar.send_request("verse.runChecks", params).await
}

#[tauri::command]
pub async fn verse_decide(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    finding_id: String,
    status: String,
    comment: Option<String>,
) -> Result<Value, String> {
    let params = serde_json::json!({
        "chapter": chapter, "verse": verse,
        "findingId": finding_id, "status": status,
        "comment": comment.unwrap_or_default(),
    });
    sidecar.send_request("verse.decide", params).await
}

#[tauri::command]
pub async fn verse_edit(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    new_text: String,
) -> Result<Value, String> {
    let params = serde_json::json!({ "chapter": chapter, "verse": verse, "newText": new_text });
    sidecar.send_request("verse.edit", params).await
}

#[tauri::command]
pub async fn settings_get(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar.send_request("settings.get", serde_json::json!({})).await
}

#[tauri::command]
pub async fn settings_set(sidecar: State<'_, EngineSidecar>, params: Value) -> Result<Value, String> {
    sidecar.send_request("settings.set", params).await
}
