//! Manages the long-lived GreekRoomEngine sidecar process.
//!
//! Per the architecture doc (§4): the sidecar starts once with the app and
//! stays alive for the session, so NLP resources (Wildebeest, Uroman, etc.)
//! are loaded once rather than per-call. Requests/responses are correlated
//! by the `id` field defined in the shared JSON protocol (protocol.py).

use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;
use tauri::AppHandle;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::{oneshot, Mutex};

type PendingMap = Arc<Mutex<HashMap<String, oneshot::Sender<Value>>>>;

pub struct EngineSidecar {
    child: Mutex<Option<CommandChild>>,
    pending: PendingMap,
}

impl EngineSidecar {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            pending: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Spawn the sidecar binary and start the background reader task that
    /// demultiplexes stdout lines back to whichever `send_request` call is
    /// waiting on that response `id`.
    pub async fn start(&self, app: &AppHandle) -> Result<(), String> {
        let sidecar_command = app
            .shell()
            .sidecar("bridge-engine")
            .map_err(|e| format!("failed to resolve sidecar: {e}"))?;

        let (mut rx, child) = sidecar_command
            .spawn()
            .map_err(|e| format!("failed to spawn sidecar: {e}"))?;

        *self.child.lock().await = Some(child);

        let pending = self.pending.clone();
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
                        eprintln!(
                            "[bridge-engine] {}",
                            String::from_utf8_lossy(&line_bytes)
                        );
                    }
                    CommandEvent::Terminated(payload) => {
                        eprintln!("[bridge-engine] terminated: {:?}", payload);
                        break;
                    }
                    _ => {}
                }
            }
        });

        Ok(())
    }

    /// Send one JSON-RPC-style request to the sidecar and await its
    /// matching response by `id`. Timeout protects the UI from hanging
    /// forever if the sidecar crashes mid-request.
    pub async fn send_request(&self, method: &str, params: Value) -> Result<Value, String> {
        let id = uuid::Uuid::new_v4().to_string();
        let request = serde_json::json!({ "id": id, "method": method, "params": params });

        let (tx, rx) = oneshot::channel();
        self.pending.lock().await.insert(id.clone(), tx);

        {
            let mut child_guard = self.child.lock().await;
            let child = child_guard
                .as_mut()
                .ok_or_else(|| "sidecar not started".to_string())?;
            let mut line = request.to_string();
            line.push('\n');
            child
                .write(line.as_bytes())
                .map_err(|e| format!("failed to write to sidecar stdin: {e}"))?;
        }

        match tokio::time::timeout(std::time::Duration::from_secs(30), rx).await {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(_)) => Err("sidecar response channel closed unexpectedly".into()),
            Err(_) => {
                self.pending.lock().await.remove(&id);
                Err(format!("sidecar request '{method}' timed out"))
            }
        }
    }
}
