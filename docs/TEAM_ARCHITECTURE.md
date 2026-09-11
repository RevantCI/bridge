# Team architecture: workbench database, identity, optional hub, dashboard

Design record for GitHub issues #44 (persistence), #45 (users and roles), #46
(collaboration), #47 (project management) and the test-suite work that has to land
first. Written 2026-09-11 after the maintainer settled the four open questions listed
under *Decisions*. `docs/DECISIONS.md` carries the five-line versions; this file is the
long form. Verify any claim here against the code before building on it — the repo's
standing rule applies to this document too.

The framing from the 2026-09-09 comment on #44 holds: Bridge already has a per-project
SQLite database (`FoundationRepository`, schema v14) for the semantic pipeline. This is
not "files → database". It is *which remaining file-based stores get a database home,
who is recorded as acting, and how a team shares that state without giving up offline
work*.

---

## 1. Decisions

| Question | Decision | Why |
|---|---|---|
| Where migrated Bridge-private data lives | A **second per-project SQLite**, `bridge-workbench.sqlite3`, beside the v14 semantic DB. The v14 DB is not touched. A small app-level `workspace.sqlite3` holds users, devices, the project registry and a cached rollup per project. | The v14 DB's open-time contract (`RECORD_DEPENDENCY_TABLES`, `recovery_check`) is about analysis records with a lifecycle; human decisions and progress rollups are not that. A project folder stays self-contained: zip it, move it, hand it to a consultant, the decisions travel with it. A locked or corrupt workbench DB cannot block the correction ledger, or the reverse. |
| How a user proves identity to the hub | **Username + admin-issued join code**, which becomes a per-device token. Local mode is "pick a name", no password. | No passwords to support, but nobody can act as someone else by accident, so attribution and roles mean something. |
| First sync slice | **Decisions, findings, progress, assignments.** Scripture text never travels through the hub. | Keeps Stage 9B.3b's authorized write as the only Scripture writer. Each team member imports the same source as today. |
| Dashboard placement | **A separate web app served by the hub**, built from the same Svelte components over an HTTP transport behind `bridgeClient.ts`. | Admins and reporters need only a browser. The desktop exe stays lean and never depends on the hub. |

Assumptions recorded alongside, not re-asked:

- Historical rows written with `actor_id="human"` are **not** backfilled to a real user.
  They render as an explicit `legacy:human` actor. Reassigning them would misattribute
  human decisions.
- `ai_review_results` and `triage_verdicts` are migrated rather than discarded; they cost
  tokens to regenerate. `check_cache` starts empty (a cache miss recomputes).
- Hub server code is an optional `[server]` extra. The PyInstaller desktop sidecar never
  imports it. Offline-first remains an invariant (`DECISIONS.md` 2026-09-11).

## 2. Target shape

```
DESKTOP (offline, authoritative for its own work)
  Bridge.exe ── stdio ── bridge-engine
      <project>/                                       translationCore files: unchanged
      <project>/.apps/translationCoreAI/passageSemantic/bridge-semantic.sqlite3   v14, unchanged
      <project>/.apps/translationCoreAI/bridge-workbench.sqlite3        NEW  WorkbenchRepository
      %LOCALAPPDATA%\Bridge\data\workspace.sqlite3                     NEW  WorkspaceRepository

TEAM HUB (optional; one small process per team, on a LAN box or hosted)
  bridge-engine --serve      same package, HTTP JSON-RPC with the same envelope, plus /auth and /sync
      hub.sqlite3            users, roles per project, join codes, devices, project events
      serves the dashboard's static bundle

DASHBOARD (browser)          projects, book progress, assignments (admin), reports (reporter)
```

Sync is an exchange of **append-only change-log events** per project: push local
unsynced events, pull the hub's events after a cursor, apply them through the same
repository with the existing `expected_revision` optimistic-concurrency check. A conflict
never overwrites a human decision; it is recorded in `sync_conflicts` for a person to
resolve.

## 3. Workbench database (per project)

`engine/tc_ai_bridge/workbench_repository.py`, `WorkbenchRepository`,
`WORKBENCH_SCHEMA_VERSION` starting at 1 with its own `schema_migrations` ladder. Connection
discipline copied from `FoundationRepository` (`passage_semantic_repository.py:1070-1086`):
one fresh `sqlite3.connect` per call, `row_factory=Row`, `foreign_keys ON`, `busy_timeout
5000`, `synchronous FULL`, `journal_mode WAL`, `query_only` when read-only; a
pre-migration backup before every version bump. Every version bump gets a
`test_workbench_vN_to_vN+1_keeps_vN_rows_readable` test in the established style.

Common columns on every mutable table: `project_id`, `book_id`, `revision` (≥1),
`actor_id`, `device_id`, `created_at`, `updated_at`, `payload_json`. `payload_json` keeps
today's JSON file content unchanged so readers do not reshape; columns are lifted only
where a query filters on them today.

### 3.1 Human-owned records (move; these are the product)

| Table | Replaces | Key / lifted columns |
|---|---|---|
| `human_decisions` | `decisions/`, `qaDecisions/`, `review/`, `terminology/` | `kind IN (check, qa, verse_status, terminology)`, `book_id, chapter, verse, key`, `decision` |
| `issue_resolutions` | `issueResolutions/` | `resolution_id`, `status`, `recheck_status`, `paratext_status`; compacted in-record `history` stays in payload, lifecycle events go to `change_log` |
| `ai_review_results` | `aiReview/` | `(book_id, chapter, verse)`, `input_fingerprint`, `generated_at` |
| `alignment_history` | `alignmentHistory/` | id = today's filename (so `restore_verse_alignment_history` keeps working); `backup_path` points at files that stay on disk |
| `alignment_diagnostics` | `alignmentDiagnostics/` | append-only |
| `team_assignments`, `team_members` | `team/` | assignee becomes a `user_id` once `workspace.users` exists |
| `semantic_mappings` | `semanticMappings/` | `(book_id, fingerprint)` |
| `semantic_validation_runs` | `semanticValidation/` | `suite_id` |
| `project_state` | `import.json` mirror, `project.json` mirror, paratext `live_sync_state`, the `migration` status row | `key`, `revision` |

### 3.2 Derived data (rebuildable caches)

| Table | Replaces | Note |
|---|---|---|
| `progress_chapters`, `progress_findings`, `progress_totals` | `.bridge/progress.json` | Normalised. One decision = two row updates instead of rewriting the whole book file. `load_progress_rollup()` reassembles today's dict. |
| `check_findings` | `checkFindings/<book>/<ch>.json` | Chapter-level blob; `qa_report` reads whole chapters. |
| `check_cache` | `checkCache.json` | Starts empty. |
| `triage_verdicts` | `triage/<book>.json` | Migrated if present. |
| `metrics_events`, `metrics_counters` | `metrics/<book>.json` | Append-only; the 2000-event cap goes away. |
| `file_backups` | index over `backups/<stamp>/` | Files stay; this only avoids `rglob`. |

### 3.3 `change_log`

```
change_log(seq INTEGER PRIMARY KEY AUTOINCREMENT,
           event_id TEXT NOT NULL UNIQUE,          -- uuid4, stable across sync
           project_id, book_id, table_name, row_key,
           op TEXT,                                -- upsert | delete | domain ops
           base_revision, new_revision,
           actor_id, device_id, created_at,
           payload_json TEXT,                      -- full row image after the change
           journal_tx_id TEXT,                     -- TransactionJournal id when a tC-file write was involved
           synced_at TEXT)                         -- NULL until the hub acks
```

- One `_write()` method does the revision check exactly as
  `passage_semantic_repository.py:3717-3733`, raises `WorkbenchConflict` on mismatch, then
  inserts the `change_log` row **in the same `BEGIN IMMEDIATE` transaction**. Callers never
  touch `change_log`.
- `BEFORE DELETE` and `BEFORE UPDATE` triggers reject every change except `synced_at`. The
  append-only audit invariant in `CLAUDE.md` moves here: today's `audit/*.json` copies are
  exactly "full row image at time of change", so audit rows *are* change-log rows.
  Existing `audit/` files are imported as `op='legacy_audit'` and then frozen, never
  deleted.
- `expected_revision=None` means last-writer-wins, which is what every file writer does
  today; call sites can start passing revisions later without a schema change.

### 3.4 Stays on disk, deliberately

- `backups/` and `transactions/` (crash recovery must not depend on the database opening).
- `paratextNotes/*.xml` (Paratext's own format).
- `.bridge/source.<ext>`, `original-manifest.json` (verbatim copies of user input).
- `.bridge/collection.json`, `.bridge/lazy-import.json` (read before any project object,
  and therefore any per-project DB, exists; the workspace DB caches them).
- `settings.json` DPAPI-wrapped secrets (`secret_store.py` is Windows ctypes; keep it out
  of SQLite).
- Everything translationCore reads.

### 3.5 Migration and the API seam

- Lazy, on first open, inside `TranslationCoreProject.__init__` after journal recovery.
  Per store in its own transaction, `INSERT OR IGNORE` on natural keys, progress recorded
  in `project_state('migration')`. Readers fall back to `_legacy_*` file readers until the
  status is `complete`. Source files are never deleted by the migration.
- `TransactionJournal` stays for tC-file writes. `apply_scripture_edit` records
  `journal_tx_id` on its change-log row with the same ordering as the existing
  `journal_prepared_callback`.
- `TranslationCoreProject` keeps every public method name and signature. The redirected
  groups: check decisions, QA decisions, verse status, terminology, AI review, issue
  resolutions, alignment history, progress, check-finding snapshots, check cache, triage,
  paratext sync state, the audit tail in `apply_scripture_edit`, the backups index.
  `MetricsStore`, `TeamWorkflow`, `SemanticMappingStore` and
  `semantic_validation_service` take a `store` argument.
- `bridge_service.py` changes only to construct the workspace repository, pass identity
  in, and read `project_progress_cache` for the multi-book dashboard.

## 4. Workspace database (app level)

`%LOCALAPPDATA%\Bridge\data\workspace.sqlite3`: `users(user_id, display_name, created_at,
active)`, `devices(device_id, machine_id, os_user)` (satisfies #42), `projects` (the
current `project-registry.json`), `settings_kv` (non-secret settings), `hub_credentials`
(device token, DPAPI-wrapped), `project_progress_cache(project_path, book_id, totals_json,
updated_at, source_seq)`. The rollup cache is refreshed after each workbench commit and
repaired on next open if `source_seq` lags the workbench `change_log`.

## 5. Identity and roles

- Local "login" is choosing or creating a display name at startup. No password.
- Every workbench write carries `actor_id = user_id`. Display names resolve at read time.
- The `actor_id="human"` defaults (`passage_semantic_repository.py:3693, 4210, 4275`,
  `qa_review.py:66`, `correction_wording.py:588-646`) become required parameters.
  `settings.reviewer_name` becomes a derived value of the current user; translationCore
  file `username` fields keep receiving the display name. This fixes #64.
- Roles: `project_admin` (assigns work, manages users and join codes), `editor` (runs
  checks, decides, verifies), `reporter` (reads results and reports). `team.py`'s
  `translator / reviewer / consultant / administrator` map to
  `editor / editor / reporter / project_admin`. Local single-user mode is implicit
  `project_admin` of one's own projects. One `authorize(user, project, action)` helper is
  used by the engine dispatcher so the hub and the desktop share the rules.

## 6. Engine process model (prerequisite for the hub)

- `BridgeEngine` state (`bridge_service.py:429-536`) splits into `Workspace` (settings,
  registry, users, job managers) and `ProjectSession` (project, semantic runtime, the
  per-book caches). Requests gain an optional `projectId`; the stdio desktop path keeps a
  current-session default so the frontend does not change. This also ends "opening
  project B clobbers project A".
- `greek_room_engine/transport/http_transport.py` (today a 35-line stub typed against
  `GreekRoomEngine`) becomes a real transport for `BridgeEngine.handle_request` with the
  same envelope. The snake_case Tauri command → dotted method mapping moves out of
  `commands.rs` into a shared table so the web transport can reuse it.
- `bridge-engine --serve --data-dir <hub>`: FastAPI + uvicorn behind the optional
  `[server]` extra, excluded from the PyInstaller spec. Threaded request handling here
  only; the stdio loop stays single-threaded (#12 owns the job coordinator).

## 7. Hub and sync (first slice)

- Auth: an admin creates a join code on the hub; the device posts `{joinCode,
  displayName}` and receives a device token. Every request carries it; `authorize()`
  checks the role.
- `POST /sync/push` (idempotent on `event_id`), `GET /sync/pull?projectId&afterHubSeq`.
  Devices link a project by `.bridge/project.json` `projectId` plus the `import.json`
  source `sha256`. Pulled events apply through the repository with `base_revision`
  checks; a divergent local unsynced change goes to `sync_conflicts` and a UI prompt.
- Devices poll the hub on a slow interval when online; presence is "last sync at".
  Server push (SSE) is a later slice.

## 8. Dashboard

- `dashboard/` is a second Vite entry sharing `src/lib/components` and
  `src/lib/api/bridgeClient.ts` over a new `httpTransport.ts`; the hub serves the static
  bundle.
- Screens: projects and book progress (all roles); assign work per book or chapter
  (project_admin); reports and CSV export (reporter and up); users and join codes
  (project_admin).
- The desktop exe gains only a small Team section in Settings: hub URL, join code, sync
  status.

## 9. Test suite (lands first)

- `engine/tests/` becomes packages mirroring engine boundaries: `service`, `jobs`,
  `persistence`, `semantic`, `review`, `correction`, `alignment`, `ai`, `project_io`,
  `connectors`, `resources`, `versification`, plus `support/` for shared builders and
  `tooling/` for the selection script's own tests. `fixtures/` and the two goldens do not
  move.
- `[tool.pytest.ini_options]`: `testpaths`, `pythonpath`, `--strict-markers`,
  `--durations=25`; markers `slow`, `subprocess`, `desktop`, `resources`, `stage3db`,
  `external`; directory→marker auto-tagging in `tests/conftest.py`.
- `pytest-xdist` with `-n auto`. Safe: the autouse `LOCALAPPDATA` isolation is per test,
  session fixtures are paths only, the vendored GIL hazard is thread-level and xdist is
  process-level.
- `scripts/affected_tests.py`: static import graph from changed files to the test files
  that transitively import them. Hub modules (`bridge_service.py`, `tc_project.py`,
  `models.py`, `passage_semantic_*.py`, conftests, `pyproject.toml`, constraints, `ci.yml`)
  select everything; unknown non-Python paths select everything.
- CI: pull requests run the selection with `-n auto`; **every push to `main` runs the full
  suite** (it is the only gate); a nightly full run and a weekly serial run catch what
  selection or parallelism hides.
- Then the RPC-wiring tests appended to stage files move to `tests/service/`, and shared
  builders move to `tests/support/`, so most stage tests stop importing
  `bridge_service.py`.

## 10. Order of work

1. Test suite: baseline, mechanical moves, config + xdist, selection + CI, decoupling.
2. Workbench DB: skeleton + `change_log`; human-owned stores + lazy migration; derived
   stores + workspace rollup cache; registry/settings into the workspace DB; sync
   readiness (cursor API, offline event export/import).
3. Identity: users, devices, required `actor_id`, roles enum, `authorize()`.
4. Engine session model + HTTP transport + `--serve`.
5. Hub first slice: join codes, push/pull, conflicts.
6. Dashboard.

## 11. Performance expectations (to be measured, not assumed)

- One human decision today: whole-book `progress.json` rewrite plus a `qaDecisions` file
  plus an `audit` file, each temp + fsync + replace on Windows. After the workbench DB: one
  SQLite transaction, one WAL fsync.
- `project.report` and `qa_report`: N chapter file opens become one `SELECT` per book.
  The 66-book dashboard: 66 file reads become one `project_progress_cache` query.
- Watch: WAL growth in a long-lived sidecar (`wal_checkpoint(TRUNCATE)` on project
  close), users copying a project folder while it is open, antivirus locks on `-wal`.
- The hub is never on the offline path. The desktop never waits on it.

## 12. Docs to keep in step

`CLAUDE.md` (on-disk shape gains the workbench DB; "schema changes are migrations" covers
two ladders; the single-user premise becomes "optional team"), `docs/DECISIONS.md`,
`docs/ARCHITECTURE.md`, `docs/HANDOFF.md`, `docs/BUILD_LOG.md` — each updated with the
commit that changes the behaviour it describes, not afterwards.
