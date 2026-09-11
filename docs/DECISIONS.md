# Decisions

Architectural and product decisions, newest first. Five lines each — this is a log, not
a design document.

Every entry answers: what was decided, why, and what it rules out. A decision with no
recorded reason gets re-litigated every few weeks, which is the thing this file exists
to prevent. Rejected ideas belong here too.

**Format**

```
## YYYY-MM-DD — Short title
**Decision:** what we are doing.
**Because:** the reason, including the alternative we didn't take.
**Rules out:** what this closes off, and what would have to change to reopen it.
**Revisit when:** a condition, or "not planned".
```

---

## 2026-09-11 — Bridge-private state gets a second per-project SQLite, not v15

**Decision:** The file-based Bridge-private stores (decisions, QA dispositions, audit
copies, progress, AI review, triage, issue resolutions, alignment history, metrics, team)
move into a new `bridge-workbench.sqlite3` beside the v14 semantic DB, with an append-only
`change_log`. translationCore-compatible files stay exactly as they are. A small app-level
`workspace.sqlite3` holds users, devices, the registry and a per-project rollup cache.
**Because:** the v14 DB's invariants (`RECORD_DEPENDENCY_TABLES`, `recovery_check`) are about
analysis records with a lifecycle; forcing decision tables into them weakens the tests that
protect staleness. A project folder must stay self-contained so a copied or shared project
keeps its review history, which rules out one app-level store as the primary.
**Rules out:** extending the semantic schema for non-analysis data; any Bridge feature that
needs the app-level DB to open a project. Long form: `docs/TEAM_ARCHITECTURE.md`.
**Revisit when:** the two databases need a cross-file transaction that the transaction
journal cannot provide.

## 2026-09-11 — Identity is a chosen name plus a device, never a password

**Decision:** Every recorded action carries a `user_id` and `device_id`. Locally a user
picks a display name at startup. In team mode an admin issues a join code that becomes a
per-device token. Roles are `project_admin`, `editor`, `reporter`. Historical `"human"`
rows stay as an explicit `legacy:human` actor and are not backfilled.
**Because:** the need is "who did it", not account security. Passwords add support cost for
field teams; username-only on a shared hub lets anyone act as anyone. A join code is the
smallest thing that makes attribution and roles real.
**Rules out:** password accounts and reset flows; reassigning past decisions to a named
user. Narrows #45 to this scope.
**Revisit when:** Bridge is hosted for people who are not already a known team.

## 2026-09-11 — The team hub is an optional sync peer, not the primary store

**Decision:** Collaboration is an optional `bridge-engine --serve` hub that exchanges
per-project change-log events with desktops and serves a separate browser dashboard. The
first slice syncs decisions, findings, progress and assignments only. Scripture text never
travels through the hub. Hub code lives behind an optional `[server]` extra and is never in
the desktop sidecar.
**Because:** offline-first is an invariant (entry below). A device must keep working with
the hub unreachable, so the desktop's own databases stay authoritative and the hub merges
events with the existing `expected_revision` check. Keeping Scripture out preserves Stage
9B.3b as the only Scripture writer.
**Rules out:** client-server Bridge; the hub as a second Scripture writer; a dashboard the
desktop exe depends on. Narrows #46 and #47.
**Revisit when:** a team needs live co-editing of verse text rather than shared review state.

## 2026-09-11 — Ideas are issues; no proposal stage, no status labels

**Decision:** New ideas go straight to an issue using the Idea template. There is no
Discussions stage, no `status:proposed`/`status:accepted` gate, and no ceremony
between filing and working. Triage is the maintainer reading open issues, labelling
them by `effort:`/`area:`, or closing them with a written reason.
**Because:** the alternative considered was ideas-in-Discussions promoted to issues on
acceptance, which keeps the board short and true. On a two-person project that is more
bookkeeping than it buys: it needs Discussions enabled, three more labels, and a
promotion step that is really just the maintainer deciding — which they can do on the
issue itself.
**Rules out:** reading "issue exists" as "we agreed to do this". The board is now a
mix of committed work and unsorted ideas, and the labels are what distinguish them.
**Revisit when:** the open-issue count stops being readable in one sitting, or a third
person joins.

## 2026-09-11 — Work goes directly onto main; CI is the only gate

**Decision:** No branch protection, no required review, no CODEOWNERS. Commits land on
`main`. `.github/workflows/ci.yml` runs the frontend, engine and Rust suites on every
push to `main` and on every PR.
**Because:** with two people, a required second review is a queue of one, and the real
defect risk in this project is not "nobody looked" — it is that the Python analysis
engine had no automated test run at all. Fixing the gate was worth more than adding
process around the merge.
**Rules out:** relying on review as a safety net. Everything now depends on CI being
honest, which is why `golden-notice` warns rather than blocks and why a red run on
`main` is treated as a real failure rather than a formality.
**Revisit when:** a third person joins, or a defect reaches a translation team that a
second reader would plausibly have caught.

## 2026-09-11 — Offline-first is an invariant, not a default

**Decision:** No feature may require a network call, an account or a login on a path a
translator uses during normal work.
**Because:** the users are translation teams working in the field, often without reliable
internet. It is the product's actual differentiator.
**Rules out:** a hosted database as the primary store, server-side analysis, and
login-gated features. A collaborative Bridge has to be sync-based, not client-server.
**Revisit when:** never for the desktop app. A separate web product is a separate decision.

<!-- New entries go above this line. -->
