//! Manages the long-lived GreekRoomEngine sidecar process.
//!
//! Per the architecture doc (§4): the sidecar starts once with the app and
//! stays alive for the session, so NLP resources (Wildebeest, Uroman, etc.)
//! are loaded once rather than per-call. Requests/responses are correlated
//! by the `id` field defined in the shared JSON protocol (protocol.py).

use serde_json::Value;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tauri::AppHandle;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::{oneshot, Mutex};

type PendingMap = Arc<Mutex<HashMap<String, oneshot::Sender<Value>>>>;

pub struct EngineSidecar {
    child: Arc<Mutex<Option<CommandChild>>>,
    pending: PendingMap,
    app: Mutex<Option<AppHandle>>,
    start_lock: Mutex<()>,
    generation: Arc<AtomicU64>,
}

impl EngineSidecar {
    pub fn new() -> Self {
        Self {
            child: Arc::new(Mutex::new(None)),
            pending: Arc::new(Mutex::new(HashMap::new())),
            app: Mutex::new(None),
            start_lock: Mutex::new(()),
            generation: Arc::new(AtomicU64::new(0)),
        }
    }

    /// Spawn the sidecar binary and start the background reader task that
    /// demultiplexes stdout lines back to whichever `send_request` call is
    /// waiting on that response `id`.
    pub async fn start(&self, app: &AppHandle) -> Result<(), String> {
        *self.app.lock().await = Some(app.clone());
        let _start_guard = self.start_lock.lock().await;
        if self.child.lock().await.is_some() {
            return Ok(());
        }

        let sidecar_command = app
            .shell()
            .sidecar("bridge-engine")
            .map_err(|e| format!("failed to resolve sidecar: {e}"))?;

        let (mut rx, child) = sidecar_command
            .spawn()
            .map_err(|e| format!("failed to spawn sidecar: {e}"))?;

        *self.child.lock().await = Some(child);
        let process_generation = self.generation.fetch_add(1, Ordering::SeqCst) + 1;

        let pending = self.pending.clone();
        let child_slot = self.child.clone();
        let generation = self.generation.clone();
        tauri::async_runtime::spawn(async move {
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Stdout(line_bytes) => {
                        let line = String::from_utf8_lossy(&line_bytes);
                        if let Ok(value) = serde_json::from_str::<Value>(line.trim()) {
                            if let Some(id) = value.get("id").and_then(|v| v.as_str()) {
                                // "__ready__" is the startup handshake, not a
                                // real request/response pairing — ignore it here.
                                if id == "__ready__" {
                                    continue;
                                }
                                let mut map = pending.lock().await;
                                if let Some(sender) = map.remove(id) {
                                    let _ = sender.send(value);
                                }
                            }
                        }
                    }
                    CommandEvent::Stderr(line_bytes) => {
                        eprintln!("[bridge-engine] {}", String::from_utf8_lossy(&line_bytes));
                    }
                    CommandEvent::Terminated(payload) => {
                        eprintln!("[bridge-engine] terminated: {:?}", payload);
                        break;
                    }
                    _ => {}
                }
            }

            // Only the reader belonging to the currently registered process
            // may clear it. This prevents a late termination event from an
            // older process from erasing a newly restarted child.
            if generation.load(Ordering::SeqCst) == process_generation {
                *child_slot.lock().await = None;
                // Dropping every sender wakes in-flight calls immediately
                // with a closed-channel error instead of making them wait for
                // the full request timeout.
                pending.lock().await.clear();
            }
        });

        Ok(())
    }

    /// Send one JSON-RPC-style request to the sidecar and await its
    /// matching response by `id`. Timeout protects the UI from hanging
    /// forever if the sidecar crashes mid-request.
    pub async fn send_request(&self, method: &str, params: Value) -> Result<Value, String> {
        if self.child.lock().await.is_none() {
            let app = self
                .app
                .lock()
                .await
                .clone()
                .ok_or_else(|| "sidecar has not been initialized".to_string())?;
            self.start(&app).await?;
        }

        let id = uuid::Uuid::new_v4().to_string();
        let request = serde_json::json!({ "id": id, "method": method, "params": params });

        let (tx, rx) = oneshot::channel();
        self.pending.lock().await.insert(id.clone(), tx);

        {
            let mut child_guard = self.child.lock().await;
            let child = match child_guard.as_mut() {
                Some(child) => child,
                None => {
                    self.pending.lock().await.remove(&id);
                    return Err(
                        "sidecar stopped before the request was sent; retry to restart it".into(),
                    );
                }
            };
            let mut line = request.to_string();
            line.push('\n');
            if let Err(error) = child.write(line.as_bytes()) {
                // The process may have died before its termination event was
                // delivered. Clear the stale handle so the next request can
                // start a fresh sidecar instead of repeatedly writing to it.
                *child_guard = None;
                self.pending.lock().await.remove(&id);
                return Err(format!(
                    "failed to write to sidecar stdin: {error}; retry to restart it"
                ));
            }
        }

        // A whole-Bible import can parse and normalize dozens of files. Keep
        // the normal interactive timeout short, but give that bounded local
        // operation enough time to finish on slower disks.
        let timeout_seconds = match method {
            "project.import" => 300,
            // The first check for a book starts the isolated structural
            // checker, whose own hard timeout is 120 seconds. Keep enough
            // headroom for process startup/report parsing. A background-job
            // protocol can replace this longer interactive timeout later.
            "verse.runChecks" => 150,
            // A single call to an OpenAI-compatible endpoint: ai_client.py's own HTTP
            // timeout is 240s (with retries on transient 5xx/429), so this must clear
            // that comfortably or the UI would report "timed out" while the sidecar is
            // still legitimately waiting on a slow model.
            "alignment.aiPropose" => 260,
            // ai.explain can make up to two sequential real model calls (an alignment
            // proposal, then the full evidence-backed review) — needs more headroom
            // than a single alignment.aiPropose call.
            "ai.explain" => 300,
            // logos.getState/setReference start a persistent -STA PowerShell helper on
            // first use; real measured startup during development was well over a
            // second even before any COM call, so the default interactive timeout is
            // too tight for a cold first call.
            "logos.getState" | "logos.setReference" => 20,
            _ => 30,
        };
        match tokio::time::timeout(std::time::Duration::from_secs(timeout_seconds), rx).await {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(_)) => Err("sidecar response channel closed unexpectedly".into()),
            Err(_) => {
                self.pending.lock().await.remove(&id);
                Err(format!("sidecar request '{method}' timed out"))
            }
        }
    }
}
