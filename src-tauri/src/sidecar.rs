//! Manages the long-lived GreekRoomEngine sidecar process.
//!
//! Per the architecture doc (§4): the sidecar starts once with the app and
//! stays alive for the session, so NLP resources (Wildebeest, Uroman, etc.)
//! are loaded once rather than per-call. Requests/responses are correlated
//! by the `id` field defined in the shared JSON protocol (protocol.py).

use serde::Serialize;
use serde_json::Value;
use std::collections::{HashMap, VecDeque};
use std::io::Write;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::{oneshot, Mutex};

type PendingMap = Arc<Mutex<HashMap<String, oneshot::Sender<Value>>>>;
type LogBuffer = Arc<Mutex<VecDeque<LogEntry>>>;

/// A diagnostics-panel entry: sidecar lifecycle events (spawn/terminate/
/// respawn), request timeouts, and stderr lines relayed from the Python
/// process (which is where its own unhandled-exception tracebacks land —
/// see stdio_transport.py). Kept as a bounded in-memory ring buffer plus a
/// best-effort append to disk, since the in-memory copy is lost if the
/// whole Tauri process (not just the sidecar) goes down.
#[derive(Clone, Serialize)]
pub struct LogEntry {
    pub ts_ms: u64,
    pub level: String,
    pub message: String,
}

const LOG_CAPACITY: usize = 400;

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn append_log_file(app: &AppHandle, entry: &LogEntry) {
    let Ok(dir) = app.path().app_log_dir() else { return };
    if std::fs::create_dir_all(&dir).is_err() {
        return;
    }
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("engine-events.log"))
    {
        let _ = writeln!(file, "{} [{}] {}", entry.ts_ms, entry.level, entry.message.replace('\n', " "));
    }
}

async fn record_log(log: &LogBuffer, app: &AppHandle, level: &str, message: String) {
    let entry = LogEntry { ts_ms: now_ms(), level: level.to_string(), message };
    {
        let mut buf = log.lock().await;
        buf.push_back(entry.clone());
        while buf.len() > LOG_CAPACITY {
            buf.pop_front();
        }
    }
    let _ = app.emit("engine-log", &entry);
    append_log_file(app, &entry);
}

fn request_timeout_seconds(method: &str) -> u64 {
    match method {
        "project.import" => 300,
        // Inspecting a whole Bible parses every Scripture file and computes
        // source fingerprints for duplicate detection. Project Home may also
        // discover a large pre-Beta-3 managed library on its first run.
        "project.inspectImport" | "project.list" => 180,
        // The first check for a book starts the isolated structural
        // checker, whose own hard timeout is 120 seconds. Keep enough
        // headroom for process startup/report parsing.
        "verse.runChecks" => 150,
        // A single call to an OpenAI-compatible endpoint: ai_client.py's own HTTP
        // timeout is 240s (with retries on transient 5xx/429).
        "alignment.aiPropose" => 260,
        // ai.explain can make up to two sequential real model calls.
        "ai.explain" => 300,
        // Logos starts a persistent -STA PowerShell helper on first use.
        "logos.getState" | "logos.setReference" => 20,
        // A whole-Bible report payload (tens of thousands of rows) takes a
        // while to serialize and ship over stdio; the export writes it
        // back out. report.status/report.cancel stay interactive.
        "report.get" | "report.export" => 180,
        _ => 30,
    }
}

pub struct EngineSidecar {
    child: Arc<Mutex<Option<CommandChild>>>,
    pending: PendingMap,
    app: Mutex<Option<AppHandle>>,
    start_lock: Mutex<()>,
    generation: Arc<AtomicU64>,
    log: LogBuffer,
    started_once: Arc<AtomicBool>,
}

impl EngineSidecar {
    pub fn new() -> Self {
        Self {
            child: Arc::new(Mutex::new(None)),
            pending: Arc::new(Mutex::new(HashMap::new())),
            app: Mutex::new(None),
            start_lock: Mutex::new(()),
            generation: Arc::new(AtomicU64::new(0)),
            log: Arc::new(Mutex::new(VecDeque::new())),
            started_once: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Most recent diagnostics entries, oldest first, for the frontend's
    /// diagnostics panel and for `get_engine_log` at startup (live updates
    /// after that arrive via the "engine-log" event instead of polling).
    pub async fn recent_log(&self, limit: usize) -> Vec<LogEntry> {
        let buf = self.log.lock().await;
        let skip = buf.len().saturating_sub(limit);
        buf.iter().skip(skip).cloned().collect()
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

        let mut sidecar_command = app
            .shell()
            .sidecar("bridge-engine")
            .map_err(|e| format!("failed to resolve sidecar: {e}"))?;

        // The bundled tN/tW/tA/UHB/UGNT snapshot ships via bundle.resources
        // (tauri.conf.json) rather than inside bridge-engine.spec's onefile
        // archive now — see that spec's own comment for why (PyInstaller's
        // onefile bootloader used to re-extract all ~45MB of it on every
        // single launch). main.py reads this flag into
        // BRIDGE_BUNDLED_RESOURCES_DIR before tc_ai_bridge's resource
        // resolvers run. A missing/unresolvable resource_dir() (should not
        // happen in a real build) just means the sidecar falls back to its
        // own sys._MEIPASS/source-tree resolution, same as before this
        // change — not fatal to startup.
        // tauri.conf.json declares "resources/" (array form), which
        // preserves that source folder name under the resolved resource
        // root — i.e. the bundled tree lands at resource_dir()/resources,
        // not resource_dir() itself.
        if let Ok(resources_dir) = app.path().resource_dir() {
            let resources_dir = resources_dir.join("resources");
            sidecar_command = sidecar_command.args(["--resources-dir", &resources_dir.to_string_lossy()]);
        }

        let (mut rx, child) = sidecar_command
            .spawn()
            .map_err(|e| format!("failed to spawn sidecar: {e}"))?;

        *self.child.lock().await = Some(child);
        let process_generation = self.generation.fetch_add(1, Ordering::SeqCst) + 1;

        // A respawn (as opposed to the very first startup) means something
        // killed the previous process out from under an open project —
        // self.project on the new process is blank, so the frontend needs
        // telling: it can't tell from a generic log line alone.
        let is_respawn = self.started_once.swap(true, Ordering::SeqCst);
        record_log(
            &self.log, app, "info",
            if is_respawn { "Sidecar restarted".to_string() } else { "Sidecar started".to_string() },
        ).await;
        if is_respawn {
            let _ = app.emit("engine-respawned", ());
        }

        let pending = self.pending.clone();
        let child_slot = self.child.clone();
        let generation = self.generation.clone();
        let log = self.log.clone();
        let app_for_reader = app.clone();
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
                        let line = String::from_utf8_lossy(&line_bytes).to_string();
                        eprintln!("[bridge-engine] {line}");
                        // stdio_transport.py sends its own tracebacks here (see
                        // "[unhandled]"); everything else is routine logging —
                        // still worth keeping for the diagnostics panel, just
                        // not worth alarming over.
                        let level = if line.contains("[unhandled]") || line.to_lowercase().contains("traceback") {
                            "error"
                        } else {
                            "warn"
                        };
                        record_log(&log, &app_for_reader, level, line).await;
                    }
                    CommandEvent::Terminated(payload) => {
                        eprintln!("[bridge-engine] terminated: {:?}", payload);
                        record_log(
                            &log, &app_for_reader, "error",
                            format!("Sidecar process terminated: {:?}", payload),
                        ).await;
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
        let timeout_seconds = request_timeout_seconds(method);
        match tokio::time::timeout(std::time::Duration::from_secs(timeout_seconds), rx).await {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(_)) => Err("sidecar response channel closed unexpectedly".into()),
            Err(_) => {
                self.pending.lock().await.remove(&id);
                if let Some(app) = self.app.lock().await.clone() {
                    record_log(
                        &self.log, &app, "error",
                        format!("Request '{method}' timed out after {timeout_seconds}s"),
                    ).await;
                }
                Err(format!("sidecar request '{method}' timed out"))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::request_timeout_seconds;

    #[test]
    fn large_project_discovery_and_inspection_have_bounded_headroom() {
        assert_eq!(request_timeout_seconds("project.inspectImport"), 180);
        assert_eq!(request_timeout_seconds("project.list"), 180);
        assert_eq!(request_timeout_seconds("project.import"), 300);
        assert_eq!(request_timeout_seconds("ping"), 30);
    }

    #[test]
    fn interactive_check_requests_keep_the_short_timeout() {
        // Beta 7 fixes dispatcher blocking at its source.  Extending these
        // timeouts would hide the regression and leave cancel/status unusable.
        assert_eq!(request_timeout_seconds("checks.status"), 30);
        assert_eq!(request_timeout_seconds("checks.cancel"), 30);
        assert_eq!(request_timeout_seconds("check.listForVerse"), 30);
    }

    #[test]
    fn report_polling_stays_interactive_while_payload_transfer_has_headroom() {
        assert_eq!(request_timeout_seconds("report.generate"), 30);
        assert_eq!(request_timeout_seconds("report.status"), 30);
        assert_eq!(request_timeout_seconds("report.cancel"), 30);
        assert_eq!(request_timeout_seconds("report.get"), 180);
        assert_eq!(request_timeout_seconds("report.export"), 180);
    }
}
