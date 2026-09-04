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
    sidecar
        .send_request("engine.info", serde_json::json!({}))
        .await
}

/// Recent sidecar diagnostics (spawn/restart/terminate, request timeouts,
/// and relayed stderr) for the Diagnostics panel. Live updates after this
/// initial fetch arrive via the "engine-log" event instead of polling.
#[tauri::command]
pub async fn engine_log_recent(
    sidecar: State<'_, EngineSidecar>,
    limit: Option<usize>,
) -> Result<Vec<crate::sidecar::LogEntry>, String> {
    Ok(sidecar.recent_log(limit.unwrap_or(200)).await)
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
    rx.await
        .map_err(|e| format!("folder picker cancelled unexpectedly: {e}"))
}

/// Selects one USFM/SFM file or a translationCore/translationStudio archive.
/// Folder imports (including Paratext and multi-book projects) use the
/// existing folder picker so users are never forced to select files one by one.
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

#[tauri::command]
pub async fn project_open(
    sidecar: State<'_, EngineSidecar>,
    path: String,
    project_id: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "project.open",
            serde_json::json!({ "path": path, "projectId": project_id.unwrap_or_default() }),
        )
        .await
}

#[tauri::command]
pub async fn project_list(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar
        .send_request("project.list", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn project_list_book_progress(
    sidecar: State<'_, EngineSidecar>,
) -> Result<Value, String> {
    sidecar
        .send_request("project.listBookProgress", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn project_forget(
    sidecar: State<'_, EngineSidecar>,
    project_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "project.forget",
            serde_json::json!({ "projectId": project_id }),
        )
        .await
}

#[tauri::command]
pub async fn project_delete(
    sidecar: State<'_, EngineSidecar>,
    project_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "project.delete",
            serde_json::json!({ "projectId": project_id }),
        )
        .await
}

#[tauri::command]
pub async fn project_scan(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar
        .send_request("project.scan", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn project_report(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar
        .send_request("project.report", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn project_collection_report(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar
        .send_request("project.collectionReport", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn project_inspect_import(
    sidecar: State<'_, EngineSidecar>,
    path: String,
    metadata: Option<Value>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "project.inspectImport",
            serde_json::json!({ "path": path, "metadata": metadata.unwrap_or(Value::Null) }),
        )
        .await
}

#[tauri::command]
pub async fn project_import(
    sidecar: State<'_, EngineSidecar>,
    path: String,
    metadata: Value,
    allow_duplicate: Option<bool>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "project.import",
            serde_json::json!({
                "path": path,
                "metadata": metadata,
                "allowDuplicate": allow_duplicate.unwrap_or(false),
            }),
        )
        .await
}

#[tauri::command]
pub async fn chapter_verses(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
) -> Result<Value, String> {
    sidecar
        .send_request("chapter.verses", serde_json::json!({ "chapter": chapter }))
        .await
}

#[tauri::command]
pub async fn chapter_verse_data(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "chapter.verseData",
            serde_json::json!({ "chapter": chapter }),
        )
        .await
}

#[tauri::command]
pub async fn checks_start(
    sidecar: State<'_, EngineSidecar>,
    scope: String,
    chapters: Vec<String>,
    checks: Vec<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "checks.start",
            serde_json::json!({ "scope": scope, "chapters": chapters, "checks": checks }),
        )
        .await
}

#[tauri::command]
pub async fn checks_status(
    sidecar: State<'_, EngineSidecar>,
    job_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request("checks.status", serde_json::json!({ "jobId": job_id }))
        .await
}

#[tauri::command]
pub async fn checks_cancel(
    sidecar: State<'_, EngineSidecar>,
    job_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request("checks.cancel", serde_json::json!({ "jobId": job_id }))
        .await
}

#[tauri::command]
pub async fn checks_retry(
    sidecar: State<'_, EngineSidecar>,
    job_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request("checks.retry", serde_json::json!({ "jobId": job_id }))
        .await
}

#[tauri::command]
pub async fn verse_get(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "verse.get",
            serde_json::json!({ "chapter": chapter, "verse": verse }),
        )
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
pub async fn check_list_for_verse(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "check.listForVerse",
            serde_json::json!({ "chapter": chapter, "verse": verse }),
        )
        .await
}

#[tauri::command]
pub async fn check_validate_selection(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    tool: String,
    group_id: String,
    check_id: String,
    selections: Value,
    nothing_to_select: bool,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "check.validateSelection",
            serde_json::json!({
                "chapter": chapter, "verse": verse, "tool": tool,
                "groupId": group_id, "checkId": check_id,
                "selections": selections, "nothingToSelect": nothing_to_select,
            }),
        )
        .await
}

#[tauri::command]
pub async fn check_save_selection(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    tool: String,
    group_id: String,
    check_id: String,
    selections: Value,
    nothing_to_select: bool,
    provenance: String,
    expected_fingerprint: String,
    metadata: Option<Value>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "check.saveSelection",
            serde_json::json!({
                "chapter": chapter, "verse": verse, "tool": tool,
                "groupId": group_id, "checkId": check_id,
                "selections": selections, "nothingToSelect": nothing_to_select,
                "provenance": provenance, "expectedFingerprint": expected_fingerprint,
                "metadata": metadata.unwrap_or_else(|| serde_json::json!({})),
            }),
        )
        .await
}

#[tauri::command]
pub async fn check_clear_selection(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    tool: String,
    group_id: String,
    check_id: String,
    provenance: String,
    expected_fingerprint: String,
    metadata: Option<Value>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "check.clearSelection",
            serde_json::json!({
                "chapter": chapter, "verse": verse, "tool": tool,
                "groupId": group_id, "checkId": check_id,
                "provenance": provenance, "expectedFingerprint": expected_fingerprint,
                "metadata": metadata.unwrap_or_else(|| serde_json::json!({})),
            }),
        )
        .await
}

#[tauri::command]
pub async fn issue_resolution_list(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "issueResolution.list",
            serde_json::json!({ "chapter": chapter, "verse": verse }),
        )
        .await
}

#[tauri::command]
pub async fn issue_resolution_save(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    tool: String,
    group_id: String,
    check_id: String,
    expected_fingerprint: String,
    selected_text: String,
    issue_summary: String,
    reviewer_note: String,
    proposed_correction: String,
    evidence: Value,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "issueResolution.save",
            serde_json::json!({
                "chapter": chapter, "verse": verse, "tool": tool,
                "groupId": group_id, "checkId": check_id,
                "expectedFingerprint": expected_fingerprint,
                "selectedText": selected_text, "issueSummary": issue_summary,
                "reviewerNote": reviewer_note, "proposedCorrection": proposed_correction,
                "evidence": evidence,
            }),
        )
        .await
}

#[tauri::command]
pub async fn issue_resolution_queue_paratext(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    resolution_id: String,
    expected_project_id: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "issueResolution.queueParatext",
            serde_json::json!({
                "chapter": chapter, "verse": verse, "resolutionId": resolution_id,
                "expectedProjectId": expected_project_id.unwrap_or_default(),
            }),
        )
        .await
}

#[tauri::command]
pub async fn issue_resolution_retry_paratext(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    resolution_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "issueResolution.retryParatext",
            serde_json::json!({
                "chapter": chapter, "verse": verse, "resolutionId": resolution_id,
            }),
        )
        .await
}

#[tauri::command]
pub async fn alignment_get(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "alignment.get",
            serde_json::json!({ "chapter": chapter, "verse": verse }),
        )
        .await
}

#[tauri::command]
pub async fn lexicon_get_entry(
    sidecar: State<'_, EngineSidecar>,
    strong: String,
    morph: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "lexicon.getEntry",
            serde_json::json!({ "strong": strong, "morph": morph }),
        )
        .await
}

#[tauri::command]
pub async fn alignment_status(
    sidecar: State<'_, EngineSidecar>,
    chapter: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "alignment.status",
            serde_json::json!({ "chapter": chapter.unwrap_or_default() }),
        )
        .await
}

#[tauri::command]
pub async fn alignment_realign(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    top_ids: Vec<String>,
    bottom_ids: Vec<String>,
    expected_original: Value,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "alignment.realign",
            serde_json::json!({
                "chapter": chapter, "verse": verse, "topIds": top_ids,
                "bottomIds": bottom_ids, "expectedOriginal": expected_original,
            }),
        )
        .await
}

#[tauri::command]
pub async fn alignment_unalign(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    bottom_ids: Vec<String>,
    expected_original: Value,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "alignment.unalign",
            serde_json::json!({
                "chapter": chapter, "verse": verse, "bottomIds": bottom_ids,
                "expectedOriginal": expected_original,
            }),
        )
        .await
}

#[tauri::command]
pub async fn alignment_save(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    alignment: Value,
    expected_original: Value,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "alignment.save",
            serde_json::json!({
                "chapter": chapter, "verse": verse, "alignment": alignment,
                "expectedOriginal": expected_original,
            }),
        )
        .await
}

#[tauri::command]
pub async fn alignment_complete(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "alignment.complete",
            serde_json::json!({ "chapter": chapter, "verse": verse }),
        )
        .await
}

#[tauri::command]
pub async fn alignment_undo(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    expected_original: Value,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "alignment.undo",
            serde_json::json!({
                "chapter": chapter, "verse": verse, "expectedOriginal": expected_original,
            }),
        )
        .await
}

#[tauri::command]
pub async fn alignment_backups(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "alignment.backups",
            serde_json::json!({ "chapter": chapter, "verse": verse }),
        )
        .await
}

#[tauri::command]
pub async fn alignment_restore(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    history_id: String,
    expected_original: Value,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "alignment.restore",
            serde_json::json!({
                "chapter": chapter, "verse": verse, "historyId": history_id,
                "expectedOriginal": expected_original,
            }),
        )
        .await
}

/// Read-only: asks AI for individual token links and returns a deterministically
/// compiled proposal for human review. Nothing is written to project files by this
/// call — see alignment_ai_apply_proposal for the separate, explicit apply step.
#[tauri::command]
pub async fn alignment_ai_propose(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    mode: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "alignment.aiPropose",
            serde_json::json!({
                "chapter": chapter, "verse": verse,
                "mode": mode.unwrap_or_else(|| "gap_fill".to_string()),
            }),
        )
        .await
}

#[tauri::command]
pub async fn alignment_ai_apply_proposal(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    proposal: Value,
    expected_original: Value,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "alignment.aiApplyProposal",
            serde_json::json!({
                "chapter": chapter, "verse": verse, "proposal": proposal,
                "expectedOriginal": expected_original,
            }),
        )
        .await
}

/// One-click AI preparation of a verse's checks for the human reviewer. Read-only:
/// nothing is written to project files. Can take a real model call's worth of time,
/// see sidecar.rs's per-method timeout table.
#[tauri::command]
pub async fn ai_explain(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "ai.explain",
            serde_json::json!({ "chapter": chapter, "verse": verse }),
        )
        .await
}

#[tauri::command]
pub async fn ai_review_start(
    sidecar: State<'_, EngineSidecar>,
    scope: String,
    chapter: Option<String>,
    verse: Option<String>,
    mode: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "ai.review.start",
            serde_json::json!({
                "scope": scope,
                "chapter": chapter.unwrap_or_default(),
                "verse": verse.unwrap_or_default(),
                "mode": mode.unwrap_or_default(),
            }),
        )
        .await
}

#[tauri::command]
pub async fn ai_review_status(
    sidecar: State<'_, EngineSidecar>,
    job_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request("ai.review.status", serde_json::json!({ "jobId": job_id }))
        .await
}

#[tauri::command]
pub async fn ai_review_cancel(
    sidecar: State<'_, EngineSidecar>,
    job_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request("ai.review.cancel", serde_json::json!({ "jobId": job_id }))
        .await
}

#[tauri::command]
pub async fn ai_review_retry(
    sidecar: State<'_, EngineSidecar>,
    job_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request("ai.review.retry", serde_json::json!({ "jobId": job_id }))
        .await
}

#[tauri::command]
pub async fn ai_review_list_chapter(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "ai.review.listForChapter",
            serde_json::json!({ "chapter": chapter }),
        )
        .await
}

#[tauri::command]
pub async fn semantic_validation_list(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar
        .send_request("semanticValidation.list", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn semantic_validation_decide(
    sidecar: State<'_, EngineSidecar>,
    candidate_id: String,
    decision: String,
    reviewer: String,
    note: Option<String>,
    corrected_mapping: Option<Value>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "semanticValidation.decide",
            serde_json::json!({
                "candidateId": candidate_id,
                "decision": decision,
                "reviewer": reviewer,
                "note": note.unwrap_or_default(),
                "correctedMapping": corrected_mapping.unwrap_or(Value::Null),
            }),
        )
        .await
}

#[tauri::command]
pub async fn passage_semantic_status(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar
        .send_request("passageSemantic.status", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn passage_semantic_project_metadata(
    sidecar: State<'_, EngineSidecar>,
) -> Result<Value, String> {
    sidecar
        .send_request("passageSemantic.getProjectMetadata", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn passage_semantic_current_passage(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    end_chapter: Option<String>,
    end_verse: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "passageSemantic.getCurrentPassage",
            serde_json::json!({
                "chapter": chapter,
                "verse": verse,
                "endChapter": end_chapter.unwrap_or_default(),
                "endVerse": end_verse.unwrap_or_default(),
            }),
        )
        .await
}

#[tauri::command]
pub async fn passage_semantic_stale_summary(
    sidecar: State<'_, EngineSidecar>,
) -> Result<Value, String> {
    sidecar
        .send_request("passageSemantic.getStaleSummary", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn passage_semantic_migration_report(
    sidecar: State<'_, EngineSidecar>,
) -> Result<Value, String> {
    sidecar
        .send_request("passageSemantic.getMigrationReport", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn passage_semantic_rebuild_passage(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    end_chapter: Option<String>,
    end_verse: Option<String>,
    tokenizer_profile: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "passageSemantic.rebuildCurrentPassage",
            serde_json::json!({
                "chapter": chapter,
                "verse": verse,
                "endChapter": end_chapter.unwrap_or_default(),
                "endVerse": end_verse.unwrap_or_default(),
                "tokenizerProfile": tokenizer_profile
                    .unwrap_or_else(|| "bridge-unicode-word-v1".to_owned()),
            }),
        )
        .await
}

#[tauri::command]
pub async fn source_semantic_build_range(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    end_chapter: Option<String>,
    end_verse: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "sourceSemantic.buildRange",
            serde_json::json!({
                "chapter": chapter,
                "verse": verse,
                "endChapter": end_chapter.unwrap_or_default(),
                "endVerse": end_verse.unwrap_or_default(),
            }),
        )
        .await
}

#[tauri::command]
pub async fn source_semantic_get_range(
    sidecar: State<'_, EngineSidecar>,
    inventory_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "sourceSemantic.getRange",
            serde_json::json!({"inventoryId": inventory_id}),
        )
        .await
}

#[tauri::command]
pub async fn source_semantic_get_unit(
    sidecar: State<'_, EngineSidecar>,
    unit_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "sourceSemantic.getUnit",
            serde_json::json!({"unitId": unit_id}),
        )
        .await
}

#[tauri::command]
pub async fn source_semantic_get_coverage_accounts(
    sidecar: State<'_, EngineSidecar>,
    inventory_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "sourceSemantic.getCoverageAccounts",
            serde_json::json!({"inventoryId": inventory_id}),
        )
        .await
}

#[tauri::command]
pub async fn source_semantic_get_diagnostics(
    sidecar: State<'_, EngineSidecar>,
    inventory_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "sourceSemantic.getDiagnostics",
            serde_json::json!({"inventoryId": inventory_id}),
        )
        .await
}

#[tauri::command]
pub async fn target_semantic_build_range(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    end_chapter: Option<String>,
    end_verse: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "targetSemantic.buildRange",
            serde_json::json!({
                "chapter": chapter, "verse": verse,
                "endChapter": end_chapter.unwrap_or_default(),
                "endVerse": end_verse.unwrap_or_default(),
            }),
        )
        .await
}

#[tauri::command]
pub async fn target_semantic_get_range(
    sidecar: State<'_, EngineSidecar>,
    inventory_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "targetSemantic.getRange",
            serde_json::json!({"inventoryId": inventory_id}),
        )
        .await
}

#[tauri::command]
pub async fn target_semantic_get_unit(
    sidecar: State<'_, EngineSidecar>,
    unit_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "targetSemantic.getUnit",
            serde_json::json!({"unitId": unit_id}),
        )
        .await
}

#[tauri::command]
pub async fn target_semantic_get_diagnostics(
    sidecar: State<'_, EngineSidecar>,
    inventory_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "targetSemantic.getDiagnostics",
            serde_json::json!({"inventoryId": inventory_id}),
        )
        .await
}

#[tauri::command]
pub async fn target_semantic_get_search_spans(
    sidecar: State<'_, EngineSidecar>,
    inventory_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "targetSemantic.getSearchSpans",
            serde_json::json!({"inventoryId": inventory_id}),
        )
        .await
}

#[tauri::command]
pub async fn target_semantic_get_capabilities(
    sidecar: State<'_, EngineSidecar>,
    inventory_id: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "targetSemantic.getCapabilities",
            serde_json::json!({"inventoryId": inventory_id.unwrap_or_default()}),
        )
        .await
}

#[tauri::command]
pub async fn semantic_location_run_range(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    end_chapter: Option<String>,
    end_verse: Option<String>,
    max_candidate_evaluations: Option<u64>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "semanticLocation.runRange",
            serde_json::json!({
                "chapter": chapter, "verse": verse,
                "endChapter": end_chapter.unwrap_or_default(),
                "endVerse": end_verse.unwrap_or_default(),
                "maxCandidateEvaluations": max_candidate_evaluations,
            }),
        )
        .await
}

#[tauri::command]
pub async fn semantic_location_status(
    sidecar: State<'_, EngineSidecar>,
    run_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "semanticLocation.status",
            serde_json::json!({"runId": run_id}),
        )
        .await
}

#[tauri::command]
pub async fn semantic_location_get_range(
    sidecar: State<'_, EngineSidecar>,
    run_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "semanticLocation.getRange",
            serde_json::json!({"runId": run_id}),
        )
        .await
}

#[tauri::command]
pub async fn semantic_location_get_relationship(
    sidecar: State<'_, EngineSidecar>,
    relationship_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "semanticLocation.getRelationship",
            serde_json::json!({"relationshipId": relationship_id}),
        )
        .await
}

#[tauri::command]
pub async fn semantic_location_get_candidates(
    sidecar: State<'_, EngineSidecar>,
    run_id: String,
    source_owner_unit_id: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "semanticLocation.getCandidates",
            serde_json::json!({
                "runId": run_id,
                "sourceOwnerUnitId": source_owner_unit_id.unwrap_or_default(),
            }),
        )
        .await
}

#[tauri::command]
pub async fn semantic_location_get_diagnostics(
    sidecar: State<'_, EngineSidecar>,
    run_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "semanticLocation.getDiagnostics",
            serde_json::json!({"runId": run_id}),
        )
        .await
}

#[tauri::command]
pub async fn meaning_analysis_run_range(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    end_chapter: Option<String>,
    end_verse: Option<String>,
    location_run_id: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "meaningAnalysis.runRange",
            serde_json::json!({
                "chapter": chapter, "verse": verse,
                "endChapter": end_chapter.unwrap_or_default(),
                "endVerse": end_verse.unwrap_or_default(),
                "locationRunId": location_run_id.unwrap_or_default(),
            }),
        )
        .await
}

#[tauri::command]
pub async fn meaning_analysis_status(
    sidecar: State<'_, EngineSidecar>,
    run_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "meaningAnalysis.status",
            serde_json::json!({"runId": run_id}),
        )
        .await
}

#[tauri::command]
pub async fn meaning_analysis_get_range(
    sidecar: State<'_, EngineSidecar>,
    run_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "meaningAnalysis.getRange",
            serde_json::json!({"runId": run_id}),
        )
        .await
}

#[tauri::command]
pub async fn meaning_analysis_get_assessment(
    sidecar: State<'_, EngineSidecar>,
    assessment_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "meaningAnalysis.getAssessment",
            serde_json::json!({"assessmentId": assessment_id}),
        )
        .await
}

#[tauri::command]
pub async fn meaning_analysis_get_components(
    sidecar: State<'_, EngineSidecar>,
    assessment_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "meaningAnalysis.getComponents",
            serde_json::json!({"assessmentId": assessment_id}),
        )
        .await
}

#[tauri::command]
pub async fn meaning_analysis_get_diagnostics(
    sidecar: State<'_, EngineSidecar>,
    run_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "meaningAnalysis.getDiagnostics",
            serde_json::json!({"runId": run_id}),
        )
        .await
}

// --- Stage 8 QA audit (analysis, read-only) --------------------------------

#[tauri::command]
pub async fn qa_audit_run_range(
    sidecar: State<'_, EngineSidecar>,
    chapter: String,
    verse: String,
    end_chapter: Option<String>,
    end_verse: Option<String>,
    meaning_run_id: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "qaAudit.runRange",
            serde_json::json!({
                "chapter": chapter,
                "verse": verse,
                "endChapter": end_chapter.unwrap_or_default(),
                "endVerse": end_verse.unwrap_or_default(),
                "meaningRunId": meaning_run_id.unwrap_or_default(),
            }),
        )
        .await
}

#[tauri::command]
pub async fn qa_audit_status(
    sidecar: State<'_, EngineSidecar>,
    run_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request("qaAudit.status", serde_json::json!({"runId": run_id}))
        .await
}

#[tauri::command]
pub async fn qa_audit_get_range(
    sidecar: State<'_, EngineSidecar>,
    run_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request("qaAudit.getRange", serde_json::json!({"runId": run_id}))
        .await
}

#[tauri::command]
pub async fn qa_audit_get_source_coverage(
    sidecar: State<'_, EngineSidecar>,
    run_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "qaAudit.getSourceCoverage",
            serde_json::json!({"runId": run_id}),
        )
        .await
}

#[tauri::command]
pub async fn qa_audit_get_target_support(
    sidecar: State<'_, EngineSidecar>,
    run_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "qaAudit.getTargetSupport",
            serde_json::json!({"runId": run_id}),
        )
        .await
}

#[tauri::command]
pub async fn qa_audit_get_finding(
    sidecar: State<'_, EngineSidecar>,
    finding_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "qaAudit.getFinding",
            serde_json::json!({"findingId": finding_id}),
        )
        .await
}

#[tauri::command]
pub async fn qa_audit_get_diagnostics(
    sidecar: State<'_, EngineSidecar>,
    run_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "qaAudit.getDiagnostics",
            serde_json::json!({"runId": run_id}),
        )
        .await
}

// --- Stage 9A human review (writes decisions, never Scripture) -------------

#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn qa_review_get_queue(
    sidecar: State<'_, EngineSidecar>,
    book: Option<String>,
    chapter: Option<i64>,
    canonical_references: Option<Vec<String>>,
    kinds: Option<Vec<String>>,
    severities: Option<Vec<String>>,
    dispositions: Option<Vec<String>>,
    review_statuses: Option<Vec<String>>,
    lifecycle_statuses: Option<Vec<String>>,
    order: Option<String>,
    limit: Option<u32>,
    cursor: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "qaReview.getQueue",
            serde_json::json!({
                "book": book.unwrap_or_default(),
                "chapter": chapter,
                "canonicalReferences": canonical_references.unwrap_or_default(),
                "kinds": kinds.unwrap_or_default(),
                "severities": severities.unwrap_or_default(),
                "dispositions": dispositions.unwrap_or_default(),
                "reviewStatuses": review_statuses.unwrap_or_default(),
                "lifecycleStatuses": lifecycle_statuses.unwrap_or_default(),
                "order": order.unwrap_or_else(|| "CANONICAL".to_string()),
                "limit": limit.unwrap_or(50),
                "cursor": cursor.unwrap_or_default(),
            }),
        )
        .await
}

#[tauri::command]
pub async fn qa_review_get_finding(
    sidecar: State<'_, EngineSidecar>,
    finding_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "qaReview.getFinding",
            serde_json::json!({"findingId": finding_id}),
        )
        .await
}

#[tauri::command]
pub async fn qa_review_decide_finding(
    sidecar: State<'_, EngineSidecar>,
    finding_id: String,
    disposition: String,
    expected_entity_revision: i64,
    expected_target_content_hashes: Option<Vec<String>>,
    note: Option<String>,
    promote: Option<bool>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "qaReview.decideFinding",
            serde_json::json!({
                "findingId": finding_id,
                "disposition": disposition,
                "expectedEntityRevision": expected_entity_revision,
                "expectedTargetContentHashes": expected_target_content_hashes.unwrap_or_default(),
                "note": note.unwrap_or_default(),
                "promote": promote.unwrap_or(false),
            }),
        )
        .await
}

#[tauri::command]
pub async fn qa_review_add_note(
    sidecar: State<'_, EngineSidecar>,
    entity_type: String,
    entity_id: String,
    note: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "qaReview.addNote",
            serde_json::json!({
                "entityType": entity_type,
                "entityId": entity_id,
                "note": note,
            }),
        )
        .await
}

#[tauri::command]
pub async fn semantic_review_decide_location(
    sidecar: State<'_, EngineSidecar>,
    relationship_id: String,
    decision: String,
    expected_entity_revision: i64,
    note: Option<String>,
    selected_candidate_id: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "semanticReview.decideLocation",
            serde_json::json!({
                "relationshipId": relationship_id,
                "decision": decision,
                "expectedEntityRevision": expected_entity_revision,
                "note": note.unwrap_or_default(),
                "selectedCandidateId": selected_candidate_id.unwrap_or_default(),
            }),
        )
        .await
}

#[tauri::command]
pub async fn semantic_review_decide_meaning(
    sidecar: State<'_, EngineSidecar>,
    assessment_id: String,
    meaning_status: String,
    expected_entity_revision: i64,
    note: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "semanticReview.decideMeaning",
            serde_json::json!({
                "assessmentId": assessment_id,
                "meaningStatus": meaning_status,
                "expectedEntityRevision": expected_entity_revision,
                "note": note.unwrap_or_default(),
            }),
        )
        .await
}

#[tauri::command]
pub async fn review_history_get_entity_history(
    sidecar: State<'_, EngineSidecar>,
    entity_type: String,
    entity_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "reviewHistory.getEntityHistory",
            serde_json::json!({
                "entityType": entity_type,
                "entityId": entity_id,
            }),
        )
        .await
}

// --- Stage 9A.4 persisted analysis orchestration --------------------------

#[tauri::command]
pub async fn analysis_job_start(
    sidecar: State<'_, EngineSidecar>,
    requested_scope: Value,
    expected_analysis_fingerprint: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "analysisJob.start",
            serde_json::json!({
                "requestedScope": requested_scope,
                "expectedAnalysisFingerprint": expected_analysis_fingerprint,
            }),
        )
        .await
}

#[tauri::command]
pub async fn analysis_job_status(
    sidecar: State<'_, EngineSidecar>,
    job_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request("analysisJob.status", serde_json::json!({"jobId": job_id}))
        .await
}

#[tauri::command]
pub async fn analysis_job_cancel(
    sidecar: State<'_, EngineSidecar>,
    job_id: String,
) -> Result<Value, String> {
    sidecar
        .send_request("analysisJob.cancel", serde_json::json!({"jobId": job_id}))
        .await
}

#[tauri::command]
pub async fn analysis_job_get_recent(
    sidecar: State<'_, EngineSidecar>,
    limit: Option<u32>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "analysisJob.getRecent",
            serde_json::json!({"limit": limit.unwrap_or(20)}),
        )
        .await
}

#[tauri::command]
pub async fn analysis_job_get_scope_status(
    sidecar: State<'_, EngineSidecar>,
    requested_scope: Value,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "analysisJob.getScopeStatus",
            serde_json::json!({"requestedScope": requested_scope}),
        )
        .await
}

#[tauri::command]
pub async fn paratext_get_state(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar
        .send_request("paratext.getState", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn paratext_set_reference(
    sidecar: State<'_, EngineSidecar>,
    reference: String,
    origin_id: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "paratext.setReference",
            serde_json::json!({ "reference": reference, "originId": origin_id.unwrap_or_default() }),
        )
        .await
}

#[tauri::command]
pub async fn logos_get_state(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar
        .send_request("logos.getState", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn logos_set_reference(
    sidecar: State<'_, EngineSidecar>,
    reference: String,
    origin_id: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "logos.setReference",
            serde_json::json!({ "reference": reference, "originId": origin_id.unwrap_or_default() }),
        )
        .await
}

#[tauri::command]
pub async fn navigation_status(
    sidecar: State<'_, EngineSidecar>,
    context: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "navigation.status",
            serde_json::json!({ "context": context.unwrap_or_default() }),
        )
        .await
}

#[tauri::command]
pub async fn navigation_poll(
    sidecar: State<'_, EngineSidecar>,
    context: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "navigation.poll",
            serde_json::json!({ "context": context.unwrap_or_default() }),
        )
        .await
}

#[tauri::command]
pub async fn navigation_bridge_changed(
    sidecar: State<'_, EngineSidecar>,
    reference: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "navigation.bridgeChanged",
            serde_json::json!({ "reference": reference }),
        )
        .await
}

#[tauri::command]
pub async fn navigation_resolve(
    sidecar: State<'_, EngineSidecar>,
    request_id: String,
    accepted: bool,
    bridge_reference: Option<String>,
    context: Option<String>,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "navigation.resolve",
            serde_json::json!({
                "requestId": request_id,
                "accepted": accepted,
                "bridgeReference": bridge_reference.unwrap_or_default(),
                "context": context.unwrap_or_default(),
            }),
        )
        .await
}

#[tauri::command]
pub async fn settings_get(sidecar: State<'_, EngineSidecar>) -> Result<Value, String> {
    sidecar
        .send_request("settings.get", serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn settings_set(
    sidecar: State<'_, EngineSidecar>,
    params: Value,
) -> Result<Value, String> {
    sidecar.send_request("settings.set", params).await
}

/// Opens a native "Save As" dialog and returns the chosen path, or null
/// if cancelled. Used by the Export modal before calling export_aligned /
/// export_non_aligned — the sidecar writes directly to whatever path this
/// returns.
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

#[tauri::command]
pub async fn export_aligned(
    sidecar: State<'_, EngineSidecar>,
    output_path: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "export.aligned",
            serde_json::json!({ "outputPath": output_path }),
        )
        .await
}

#[tauri::command]
pub async fn export_non_aligned(
    sidecar: State<'_, EngineSidecar>,
    output_path: String,
) -> Result<Value, String> {
    sidecar
        .send_request(
            "export.nonAligned",
            serde_json::json!({ "outputPath": output_path }),
        )
        .await
}
