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

## 2026-09-15 — The workspace database gets its own versioned ladder

**Decision:** `workspace.sqlite3` is the third versioned schema (`WORKSPACE_SCHEMA_VERSION`),
alongside the semantic database (v16) and the workbench (v2). v1 is exactly the unversioned
`devices`/`users` the first cut created, kept as `IF NOT EXISTS` so an existing file is
adopted; every later change is a forward block. No CLAUDE.md carve-out.
**Because:** the alternative -- keep `CREATE TABLE IF NOT EXISTS` and call the database
disposable -- is false for one table: `users` and `devices` ids are stamped on immutable
workbench `change_log` rows, so they must persist. Consistency with the other two ladders
costs one more version number and ~80 lines; the first non-additive change then has a home.
**Rules out:** ad-hoc column checks in `workspace_repository.py`; recreating the identity
tables. Long form: `docs/TEAM_ARCHITECTURE.md` §4, `docs/BUILD_LOG.md` 2026-09-15 (#77).
**Revisit when:** never for the ladder itself; the *contents* are revisited when the hub
adds `hub_credentials`.

## 2026-09-16 — One local user per installation until after v1; the hub after v1

**Decision:** Bridge keeps a single local user per installation (the OS-seeded name,
editable in Settings) through the v1 release. No user picker at startup, no in-app
user switching, no per-user or owner-annotated dashboard. Hub login and sync (#80)
are taken up after v1. Identity plumbing (#78: required `actor_id`, roles enum,
`authorize()`) still lands, because rows written without it cannot be re-attributed.
**Because:** the maintainer wants v1 simple, and today's users are one person per
laptop. Every workbench row already carries a stable `user_id` and `device_id`, so
adding a picker later attributes new rows correctly without touching old ones.
**Rules out:** for now, #97 (local login, switch user, owner column) — closed as
deferred, not rejected; anything in the UI that assumes several users on one machine.
**Revisit when:** v1 has shipped and a team shares a machine, or the hub slice starts.

## 2026-09-24 — Language QA benchmark: AI review rows are the positives, contradictions are "maybe"

**Decision:** The Phase 2 benchmark treats every in-scope row of the IRV Round 2 and Pass 3 reports as a positive (maintainer instruction). A row the reports contradict (a disagreeing fix, a reversal, a Pass 3 confirmed house form) or a human verdict against it is "maybe". Nothing is a negative.
**Because:** these are the only labelled data there is. The alternatives were strict human-confirmed rows only (5 in Philippians) or waiting for human review. The Philippians Rejected rows answered a different question and are not ground truth.
**Rules out:** reading benchmark precision as accuracy against verified truth; it is agreement with the AI review, and `docs/LANGUAGE_QA_BENCHMARK.md` says so at the top.
**Revisit when:** a human-labelled set exists; it fills the reserved "negative" class.

## 2026-09-24 — The accuracy gate is local; the latency gate is in CI

**Decision:** `scripts/language_qa_benchmark.py --gate` runs locally before a rule change and its output goes in BUILD_LOG. `scripts/benchmark_language_qa.py --gate --cores 2` runs in CI.
**Because:** the IRV text and review reports live outside the repository and are not committed. The latency benchmark uses a synthetic project and runs anywhere.
**Rules out:** CI catching a precision regression by itself; committing the IRV corpus or the reports to make it do so.
**Revisit when:** a redistributable benchmark slice is approved for the repository, or a self-hosted runner with the corpus exists.

## 2026-09-24 — Language QA has one polled status channel, not engine push

**Decision:** One count-only `languageQa.status` poll (`languageQaInline.ts`) feeds the marks and the panel. It runs at 500 ms while a pass is active and backs off to 10 s when idle, and a local edit or decision nudges it.
**Because:** the sidecar reader (`sidecar.rs`) routes stdout only to a pending request id, so the engine cannot push. Adding push needs a Rust and protocol change, larger than this phase. The brief allows the polled fallback.
**Rules out:** per-component Language QA pollers, since the panel no longer polls.
**Revisit when:** the protocol gains server-initiated messages for any other reason.

## 2026-09-24 — An ignore expires when its rule or pack version changes

**Decision:** An "ignored" or "rejected" Language QA decision recorded under a different pack version or rule revision is not re-applied. The finding returns flagged `previouslyIgnored` for re-checking.
**Because:** the layered-rules brief requires it: a changed rule may now be right where it was wrong. The alternative, silently keeping old ignores, hides a changed rule's new findings.
**Rules out:** treating an ignore as permanent. Every `RULE_VERSION` bump sends existing ignores back for re-check.
**Revisit when:** per-rule revisions replace the pack-wide version as the only trigger (Phase 3 pack).

## 2026-09-24 — Language QA rules are bundled data, generated from the corpus

**Decision:** Tamil rules live in a JSON rule pack (`engine/tc_ai_bridge/language_packs/ta-irv/`), loaded once per process and self-tested at load: every rule's examples run through the real `scan_text`, and a failure refuses the pack. The pack is generated by `scripts/build_ta_irv_pack.py` from the IRV corpus and the review reports, and is committed.
**Because:** abstains and examples need numbers from the corpus, such as "அந்த தேச- bare 31, doubled 8". Hand-written Python rules had no record of where their exceptions came from. The alternative, a grammar engine, is far beyond what the benchmark can justify.
**Rules out:** rules edited in Python; match primitives outside the closed set in `docs/LANGUAGE_QA_RULE_PACK.md`; shipping a pack whose examples fail.
**Revisit when:** a second language pack needs a primitive the set lacks.

## 2026-09-24 — A project override may only narrow a bundled rule

**Decision:** `.apps/translationCoreAI/language-packs/ta-irv/overrides.json` may disable a rule, take it off inline display, or add abstains. Anything else is refused, listed in the pack's `problems`, and the rest of the override still applies.
**Because:** a project that widens a rule changes what the benchmark measured without the benchmark knowing. Widening, including enabling `integrity.digits-in-text`, is a pack change.
**Rules out:** per-project new rules and per-project inline promotion.
**Revisit when:** Phase 6 scoped ignores need a new override shape.

## 2026-09-24 — Every வல்லினம் rule is inline on the maintainer's sign-off, below the 90% floor

**Decision:** The four vallinam rules and the wrong-consonant rule are drawn inline. Each carries an `inlineSignOff` holding the precision it was signed off at (41.2% to 55.0% strict; 15.4% for manner adverbs; none measured for wrong-consonant). The gate fails a signed-off rule that falls more than 2 points below its sign-off. The 90% floor still applies to any rule without one.
**Because:** this was the maintainer's instruction: a false positive costs one Ignore, and Phase 6 learns from ignores. The measured precision is agreement with a minority-form AI review, not accuracy, so it understates the rules.
**Rules out:** reading "inline" as "90% precise"; promoting a rule inline without a recorded sign-off.
**Revisit when:** a human-labelled set exists, or the ignore rate on a rule shows it is noise.

## 2026-09-24 — A bare ை/க்கு word before a hard consonant is a root noun when the corpus inflects it

**Decision:** The accusative and dative rules abstain on words the IRV corpus shows to be root nouns rather than case forms. For ை, that is a word whose +யை form is attested (படை→படையை). For க்கு, it is a word whose ‑ில் or +க்கு form is attested (கிழக்கு→கிழக்கில்). The list is computed by the pack builder and stored as a `notLexical` abstain with its counts.
**Because:** "படை" (army) ends in ை but is not an accusative, and it takes no வல்லினம். The maintainer asked for a rule, not a word-by-word list. Attested inflection is the evidence available offline.
**Rules out:** a morphological analyser; hand-curated exception lists for this shape.
**Revisit when:** the Phase 5 lexicon provides part of speech.

## 2026-09-24 — The names adapter is not a seed for the house-style proper-noun list

**Decision:** `housestyle.properNouns` ships empty, and the vallinam rules abstain on its members once Phase 6 fills it. The names adapter's majority forms were evaluated as a seed and rejected.
**Because:** its majority forms include common words (they are transliteration matches, not a name list), and it takes about 15 s per book, over the pack load budget.
**Rules out:** deriving the name list from the adapter at scan time.
**Revisit when:** Phase 6 builds the name pack from a curated source.

## 2026-09-24 — The persisted Language QA scan is its own workbench table, holding results before decisions

**Decision:** Language QA results persist in a new `language_qa_cache` table (workbench v4), one row per chapter. Each row holds every verse's raw findings keyed by the verse's text hash. Decisions are applied on every pass, never cached.
**Because:** the brief named `check_cache`. But every reader of that table (`load_check_cache`: USFM, names, QA report, triage, analytics) loads all of a book's rows, and 150 chapter payloads would ride on each of those reads. Caching before decisions means a decision rescans nothing, and a live edit rescans only the edited verse.
**Rules out:** storing Language QA sections in `check_cache`; decision state inside the cache key.
**Revisit when:** `check_cache` gains per-section reads.

## 2026-09-24 — The Language QA job stage runs outside `_checker_lock`

**Decision:** The check-job stage runs the Language QA book pass on the job's thread in its preflight. It is serialised with the background worker by Language QA's own pass lock, not by `_checker_lock`.
**Because:** the dispatcher takes `_checker_lock` for `verse.runChecks`, so holding it for a book pass would make a save wait seconds. This violates the performance contract. The brief asked for `_checker_lock`; the pass lock gives the same guarantee, one authoritative pass at a time, without that cost.
**Rules out:** a second concurrent Language QA worker; blocking the dispatcher on Language QA.
**Revisit when:** Language QA needs a resource that `_checker_lock` guards.

## 2026-09-24 — A collection QA run is offered after import, never started automatically

**Decision:** `collection.runChecks` runs only when the user clicks "Run QA on all N books". The button is on the dashboard, which is where a multi-book import lands. While a run is active the app is read-only: no editing, no book switching, no `checks.start`. Pause takes effect between books.
**Because:** the brief requires it. A whole Bible is 66 sequential book jobs on one worker thread, which is an unattended operation (measured wall time in BUILD_LOG). An automatic start would lock a translator out of the book they just imported.
**Rules out:** background whole-collection checking while a translator works; pausing mid-book.
**Revisit when:** checks run in a separate worker process that can yield to edits.

## 2026-09-24 — Export is gated by one function, and the override is a recorded decision

**Decision:** `export.aligned` and `export.nonAligned` consult `reporting.publication_gate(project)`. Its blocking items are open AI critical issues, open Language QA findings with severity high and confidence high, and tN/tW checks marked needs-discussion. With blocking items open, nothing is written until the reviewer ticks "Export anyway". The override is then recorded as a `kind='qa'` decision with key `export.override`, listing the items open at that moment, so it lands in `change_log`.
**Because:** the brief requires one gate definition fed by every source. The full book report takes minutes, so the export gate reads persisted state only. Blocking with an override keeps export possible while making it deliberate.
**Rules out:** an export that silently ignores open blocking findings; a hard block with no override; a second gate definition.
**Revisit when:** a team role model decides who may override (TEAM_ARCHITECTURE §5).

## 2026-09-24 — The lexicon's data budget: about 3 MB, bounded by frequency

**Decision:** `language_packs/ta-irv/lexicon.json` lists every IRV word seen at least 3 times (19,618 of 79,208 distinct forms, capped at `--top`, default 60,000). It also carries the 9,515 words common enough to suggest (at least 6 occurrences), their precomputed one-cluster deletion buckets (55k keys), and 151 curated pairs. It is 3.0 MB on disk, takes about 150 ms to parse, and adds about 15 MB of resident memory once loaded. It is loaded lazily, off the dispatcher.
**Because:** the LQA-1 100 KiB budget was for runtime source, not data. The performance contract caps added RSS at 50 MB and startup at 200 ms, and a lazy load adds nothing to startup. A word left out of the list is by definition rare, which is the only thing the rule asks of it. Precomputing the buckets is what keeps a lookup a dict read.
**Rules out:** shipping the full 79k-form table or building buckets at load.
**Revisit when:** a second language pack needs a lexicon, or the frozen build's per-launch extraction makes 3 MB noticeable.

## 2026-09-24 — The lexicon is never updated from decisions

**Decision:** Translator decisions on lexicon findings (a Use, a false positive) are listed by `scripts/lexicon_feedback_report.py` for a person to fold into the curated corrections. Neither the engine nor the scan ever writes the lexicon.
**Because:** the brief, and `passage-aware-semantic-alignment.md` §31: learning may improve ranking, never become an unconditional rule. A decision is one reviewer's call at one verse, while the curated map is a hard rule applied everywhere.
**Rules out:** automatic lexicon growth; a decision silently becoming a `known-misspelling` pair.
**Revisit when:** not planned. House-style learning (Phase 6) narrows and ranks, and it is a separate mechanism.

<!-- New entries go above this line. -->
