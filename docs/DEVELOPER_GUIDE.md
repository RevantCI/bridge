# Developer Guide

The "why" and "where things stand" companion to
[`DEVELOPER_SETUP.md`](DEVELOPER_SETUP.md) (the "how to get it running"
doc). This is a curated summary for personal/team reference — the full
detail always lives in [`ARCHITECTURE.md`](ARCHITECTURE.md) (design
rationale) and [`BUILD_LOG.md`](BUILD_LOG.md) (session-by-
session build log, currently ~1850 lines). Read those two when you need the
full story on something; use this doc to find out *whether* you need to.

---

## 1. Tech stack and why

| Layer | Choice | Why |
|---|---|---|
| Desktop shell | **Tauri v2** (Rust) | Native OS webview instead of bundling Chromium → smaller binary, faster cold start, lower idle memory. Matters for an all-day tool on modest field hardware. Rejected **Electron** for this reason. |
| Frontend | **Svelte 4 + TypeScript + Tailwind** | A real web-app UI (colored status badges, inline findings, tabbed panels) that a native widget toolkit fights rather than enables. Also gives a direct path to a future web deployment. Rejected **Python + Tkinter** (the original app's stack) for this reason. |
| Business logic | **Python 3.12/3.13 sidecar** (`bridge-engine`, PyInstaller-bundled) | Reuses the 29 (now 30) existing, proven `tc_ai_bridge` modules from the legacy app rather than rewriting them. |
| Sidecar transport | **JSON-lines over stdin/stdout** | Transport-agnostic protocol defined once in `engine/greek_room_engine/protocol.py`. Desktop uses stdio (`stdio_transport.py` / `src-tauri/src/sidecar.rs`); a future web deployment reuses the same `GreekRoomEngine.handle_request()` behind an HTTP wrapper — no protocol or UI rewrite needed. |

**Trade-off accepted:** Rust has a learning curve for a team with none; in
practice, day-to-day work stays in the Python engine and Svelte frontend —
the Rust shell is intentionally thin (spawn sidecar, route JSON, expose a
few Tauri commands).

**Core architectural principle:** Greek Room says what's *objectively
suspicious*, AI says what it *might mean*, and the human says what the
translation should be. Bridge never silently rewrites Scripture or alignment
groups. Basic-mode AI may record only policy-approved, high-confidence tN/tW
review selections grounded in bundled evidence; Advanced mode keeps them as
editable proposals, and every stored selection records its provenance. Full detail:
[`ARCHITECTURE.md`](ARCHITECTURE.md).

**Unicode semantic-comparison invariant (V1.1):** authoritative Scripture is
never normalized or rewritten for comparison. Stage 7 derives transient NFC,
Unicode-case-folded comparison keys by walking extended grapheme clusters and
preserving Letter, Number, and Mark material. Canonically equivalent NFC/NFD
spellings therefore compare consistently, while compatibility distinctions are
not erased. Punctuation and symbols remain comparison boundaries. Internal
ZWJ/ZWNJ/WORD JOINER controls are retained in orthographic runs; standalone
directional controls do not become semantic tokens. The one explicit exception
is Stage 7's controlled Biblical-Hebrew category matching, which can derive an
unpointed consonantal key without changing UHB token identity or stored text.

Grapheme safety is not universal lexical segmentation. The generic comparison
tokenizer intentionally does not claim dictionary-quality boundaries for
Thai, Khmer, Lao, Myanmar, or other no-space writing systems. Persistent spans
remain exact half-open Unicode code-point offsets over raw text, and normalized
comparison keys must never be used to apply a correction.

**Never integrated directly:** Greek Room's `ephesus/` web API (Docker,
database, its own web UI) — Bridge only uses the underlying check modules,
not the reference web app around them.

---

## 2. Phase roadmap — planning vs. actual outcome

The original plan (Claude Code sessions that did Phases 1-3) laid out 7
phases. What actually shipped often diverged from the plan, for good
reasons — this table is the fast way to see both.

| Phase | Planned | Actual outcome |
|---|---|---|
| **1** | Protocol & sidecar consolidation | ✅ Done. `BridgeEngine` = `GreekRoomEngine` + `tc_ai_bridge` behind one JSON protocol. |
| **2** | Svelte frontend wired to real sidecar | ✅ Done. Single-window UI, confirmed on a real Windows machine with a real translationCore project. |
| **3** | Decision persistence, chapter switching, whole-book, Settings, Export | ✅ Done. Stable finding IDs, `checks.start/status/cancel/retry` background jobs replacing a blocking frontend loop. |
| *(unplanned)* | — | Import pipeline built first, ahead of schedule — a working import blocks everything downstream. Also: a 66-book import that took 4–6 min and hit a hard timeout is now ~5–6s (lazy per-book normalization); a real security fix (plaintext API keys could persist to disk); background check jobs; and Milestone 3B.3's schema-constrained, evidence-grounded automatic tN/tW review with resumable verse/chapter/book jobs and persisted current/stale results. |
| **4** | USFM structural checker + versification | ✅ Done (2026-08-20 / 2026-08-21). Both vendored from `BibleNLP/greek-room`, wired into the existing check pipeline. Backend/protocol-only — no dedicated UI panel, matching how other checks surface as inline findings. |
| **5** | Names & Transliteration (Uroman + Smart Edit Distance) | ✅ Done (2026-08-21). Whole-book spelling-consistency check wired into `verse.runChecks`'s existing `"local"` checks list — no frontend change needed. |
| **6** | Alignment Intelligence (UAlign corpus stats) | ✅ Statistics engine done (2026-08-24). Turned out to need a real prerequisite not in the original plan: you can't compute stats over "human-approved alignments" with no way to create one — so the **manual word-alignment editor** (see `ALIGNMENT.md`) was built first, then corpus statistics (co-occurrence, translation probability, PMI, optional SED phonetic boost) computed from Bridge's own completed alignments — not a vendored `ualign.py`. Backend/protocol-only, two read-only methods, no UI yet. |
| **7** | Paratext/Logos connectors, AI explain, drag-and-drop | ✅ All four slices have real work. AI alignment proposals and drag-and-drop are verified end-to-end. AI explain is wired to real materialized tN/tW evidence. The Paratext companion performs identity-gated, idempotent Project Note handoff and preserves sent state after restart. The Logos PowerShell/COM bridge is process/protocol tested; later live Logos 53.1 inbound/outbound navigation was also verified. |
| *(Stage 3 follow-up)* | — | Language-independent semantic passage mapping and a 40-case IRVTam discovery queue are built. All 40 Luke/Philippians proposals were human-reviewed and verified after restart: 38 confirmed, one corrected, and one rejected (95% combined proposal agreement). This became the validation evidence base for the later passage-semantic stages; the Beta 15 instructions below are retained as a historical checkpoint, not the current resume boundary. |
| *(Passage-semantic Stages 4-8)* | Source/target semantic inventories, passage-aware location, meaning preservation, bidirectional QA | ✅ Done (2026-09-01 / 2026-09-02). Deterministic throughout — none of these stages uses a language model. Note the numbering collision: these are semantic **Stages**, a different axis from the Greek Room **Phases** above. Production caveat: `SemanticEmbeddingProvider.available` is `False` in the shipped app, so location runs there use lexical/structural evidence only; `scripts/seed_review_fixture.py` seeds a project with a fixture provider for exercising the review UI. |
| *(Stage 9A)* | Human QA review, evidence inspection, disposition workflow | ✅ Done, including Stage 9A.4 orchestration (2026-09-03). A 2026-09-04 follow-up kept a running analysis job visible while the reviewer navigates (it was previously dropped), and fixed the Logos VBScript shim going silent on any COM error, and bounded the Bridge navigation publish retry. Alignment Review is a top-level Word/Semantic/Passage/QA surface; `qaReview.*`, `semanticReview.*` and `reviewHistory.*` record decisions with optimistic concurrency. **Run analysis** now executes Stages 5–8 as a persisted background job for passage/chapter/book/range and refreshes the queue. Findings are classified only — no correction generation or application, which remains Stage 9B. Normal runtime visibly reports limited retrieval until a production multilingual embedding provider is configured. |
| *(Stage 9B)* | Correction wording, review, explicit apply, affected re-analysis, semantic verification | ✅ Done through **9B.4**. 9B.0 schema/eligibility, 9B.1 wording generation, 9B.2 review UI, 9B.3a persistence/recovery, 9B.3b the first authorized Scripture write behind explicit human confirmation, 9B.3c affected re-analysis, and 9B.4 positive semantic verification plus explicit `CORRECTED` acknowledgement are present. Schema is **v14**. Stage 8 target-hash and resource-conflict blockers, Case C source-inventory consistency, and terminal verification refresh were repaired before release v0.9.6. A correction is never verified merely because a finding disappeared: current Stage 6B/7/8 evidence must positively satisfy the original obligation, and `PASSED` alone never sets `CORRECTED`. |
| *(Project QA report)* | — | ✅ Done (2026-09-04). **Generate report** on the project screen builds a whole-collection QA report in a background sidecar job (`report.generate/status/get/cancel/export`, `tc_ai_bridge/qa_report.py`, `report_jobs.py`): every book's Greek Room / tN / tW / alignment / AI-review progress, and every issue as a filterable row (category, book, chapter, verse, issue, AI proposal, fixed by human/machine, pass/fail) with charts and CSV / TSV / print-to-PDF export. Needed one piece of new persistence: a succeeded check job now snapshots its findings to `.apps/translationCoreAI/checkFindings/<book>/<chapter>.json` (the rollup only ever kept ids). Installed-app acceptance still NOT RUN. |
| *(AI triage)* | — | ✅ Done (2026-09-07). Optional, **online-only** false-positive scoring layered on that report — see §5. Backend, protocol and report-screen UI; live model behaviour and installed-app acceptance NOT RUN. |

### 2.1 Complete project history and current continuation

Bridge has two numbering systems. The original product roadmap uses **Phases
1–7**; the later passage-semantic architecture uses **Stages 1–9**. They are
different axes, and both are now implemented. This chronology reconciles the
historical checkpoints below with the current repository.

#### Original Phases 1–7

1. **Protocol and sidecar consolidation.** `BridgeEngine` unified Greek Room
   and `tc_ai_bridge` behind the JSON sidecar protocol. Existing project,
   decision, edit, and transaction-journal behavior stayed authoritative.
2. **Real desktop frontend.** Svelte/Tauri was connected to the real sidecar,
   with a single-window Windows/WebView2 project, chapter, verse, finding, and
   navigation workflow.
3. **Persistent application workflow.** Stable projects, decisions, edits,
   settings, background check jobs, aligned/non-aligned export, restart
   recovery, safe provider settings, and collection-aware import landed. The
   import path was reduced from roughly 4–6 minutes for 66 books to about 5–6
   seconds through lazy per-book normalization.
4. **USFM and versification.** The Greek Room structural checker and
   deterministic versification detection, org-reference normalization, and
   back-versification map were integrated. Reference numbers remain anchors,
   not universal semantic boundaries.
5. **Names and transliteration.** Whole-book consistency checking combined
   Uroman with vendored Smart Edit Distance and performance-safe candidate
   blocking. Similarity remains evidence, never proof of an error.
6. **Alignment intelligence.** Bridge first added the manual Word Alignment
   editor required to create human-approved data, then calculated
   co-occurrence, translation probability, PMI, and optional phonetic-boost
   statistics from Bridge's completed alignments. Native translationCore
   alignment remains the verse-local lexical representation.
7. **External integrations and AI assistance.** AI alignment proposals,
   evidence-grounded AI explanations, native drag-and-drop import,
   identity-gated Paratext note handoff, and Paratext/Logos navigation were
   implemented. Proposals require the appropriate human action; external
   availability never becomes authority over Bridge state.

#### Translation-help and Beta 6–15 evolution

The beta sequence progressively added occurrence-aware tN/tW review, Basic and
Advanced modes, resumable verse/chapter/book AI jobs, current/stale lifecycle,
clear cancellation and retry, exact target selections, persisted resolutions,
Paratext handoff, language-aware passage mappings, and the ranked semantic
validation UI. Installed acceptance established project preservation,
human-selection protection, restart persistence, explicit Apply AI proposal,
`Cancelled` status, and alignment/export behavior.

The IRVTam validation corpus supplied 40 machine proposals across Luke and
Philippians. Human review produced 38 confirmations, one correction, one
rejection, and 95% combined proposal agreement. The durable cross-verse
regression is:

```text
source PHP 1:3  τῷ Θεῷ μου
target PHP 1:6  என் தேவனை
CROSS_VERSE_REORDERED · meaning preserved
```

This is a representative corpus case, not a Tamil rule.

#### Passage-semantic Stages 1–9

- **Stages 1, 2, and 2.1:** repository analysis, codebase-specific technical
  design, and the review/lifecycle, semantic-unit, ownership, lineage,
  Unicode-coordinate, policy-version, and SQLite amendments.
- **Stage 3:** canonical schemas, token lineage/instances, semantic units,
  lexical solutions, coverage accounts, correction proposals, SQLite
  migration/recovery/backup, and cross-language validation foundation.
- **Stage 4:** current-text authority and runtime integration. Editable chapter
  JSON supplies wording; preserved imported USFM supplies structure. Edits
  stale dependent records without silently relocating human work.
- **Stage 5:** comprehensive UHB/UGNT source semantic inventory. tN/tW/TWL
  enrich and validate the inventory rather than defining it.
- **Stage 6A:** an independent target semantic inventory whose construction
  does not assume source expectations.
- **Stage 6B:** passage-aware source-to-target location with structural-window
  expansion and controlled search budgets. Exhaustion means review is needed,
  not omission.
- **Stage 7:** deterministic meaning-preservation assessment, separate from
  location and coverage.
- **Stage 8:** separate source-coverage and target-support audits, conservative
  possible-error classifications, and explicit resource-conflict evidence.
- **Stage 9A:** the Word/Semantic/Passage/QA Alignment Review surface,
  evidence inspection, review history, dispositions, scoped queues, and
  persisted analysis jobs.
- **Stage 9B.0–9B.4:** correction eligibility and wording, proposal review,
  crash-safe application ledger, explicit human apply with exact CAS,
  affected-passage re-analysis, positive semantic verification, and separate
  human `CORRECTED` acknowledgement.

#### Stabilization and releases

- **v0.9.4:** Stage 9B.4 acceptance boundary and correction verification.
- **v0.9.5:** canonical acceptance-fixture repair.
- **v0.9.6:** Case C source-inventory consistency and terminal verification
  refresh repair. This is the current public release at commit `b0de092`.
- **V1.1, local after v0.9.6:** Stage 7 comparison became Unicode-canonical and
  grapheme-safe. The Tamil polarity defect was fixed without a language branch;
  semantic/cache versions were advanced while schema stayed v14 and the public
  app version stayed 0.9.6.

Local baseline immediately before this documentation consolidation:

```text
branch                         main
public baseline                b0de092 / v0.9.6
V1.1 implementation            5cc3ce7
V1.1 tests                     ef49e9e
V1.1 handoff                   4444ea7
companion schema               v14
public application version     0.9.6
remote status                  local main 3 commits ahead before this docs commit
```

The verified V1.1 gates are 175 focused tests, 1069 full Python/Greek Room
tests, 310 frontend tests, Svelte check with zero errors/warnings, production
frontend build, 12 Rust tests, `cargo check`, and `git diff --check`.

The next safe operational sequence is to push V1.1 only when authorized, build
an internal installed-acceptance package without publishing a release, verify
real multilingual projects and cache invalidation, record the results, and
obtain an explicit V1.2 boundary. Do not begin export/Scripture Burrito,
cross-verse visualization, new providers, or new semantic dimensions merely
because the numbered phases and stages are complete.

### Historical Beta 15 developer handoff — 2026-08-31

> This subsection is retained as an audit snapshot. Its “next” instructions
> describe the repository on 2026-08-31 and are superseded by §2.1 and the
> latest sections of `HANDOFF.md`.

Start from `main` at `933d48c` (`feat(dashboard): split project dashboard into
book list and report panels`) or a later descendant. The working tree was clean
before this handoff update. The bundled proposal artifact remains
[`validation/irvtam-semantic-mapping-candidates.json`](validation/irvtam-semantic-mapping-candidates.json):
40 `MACHINE_PROPOSED` rows generated with `gpt-5.6`. Do not rewrite that file
as though the model originally produced human-confirmed data.

Manual installed-app validation is complete for every bundled candidate:

| Book | Reviewed | Confirmed | Corrected | Rejected | Displayed agreement |
|---|---:|---:|---:|---:|---:|
| Luke | 28/28 | 27 | 1 | 0 | 96% |
| Philippians | 12/12 | 11 | 0 | 1 | 92% |
| **Combined** | **40/40** | **38** | **1** | **1** | **95%** |

Bridge was restarted after review. Both book-specific decision sets and their
calibration totals persisted. The reviewed set covers `SAME_VERSE`,
`CROSS_VERSE`, `CROSS_VERSE_REORDERED`, `SPLIT_ACROSS_VERSES`,
`MERGED_ACROSS_VERSES`, `REORDERED_WITHIN_VERSE`, `CLAUSE_MOVED`,
`SENTENCE_REORDERED`, `PRONOMINALIZED`, `GRAMMATICALLY_ENCODED`, `IMPLICIT`,
and `PARAPHRASED`. The known regression is explicitly human-confirmed:

```text
PHP 1:3  τῷ Θεῷ μου
PHP 1:6  என் தேவனை
CROSS_VERSE_REORDERED · PRESERVED · proposed confidence 0.99
candidate a9d12c8a97e405ae0709
```

The two non-confirmed records require careful interpretation:

- `dababa8fb3c5280df4c0` (LUK 3:34, `translate-names`) was saved as
  `HUMAN_CORRECTED`. Its saved mapping has the two exact spans in LUK 3:33 and
  3:34, `CROSS_VERSE + SPLIT_ACROSS_VERSES + PARAPHRASED`, `PRESERVED`, and
  confidence `0.99`. That payload currently matches the machine proposal in
  all material mapping fields. Treat it as proof of the correction workflow,
  not as evidence that a relationship or threshold is wrong.
- `a55017aa58d2d1fcb657` (PHP 1:5, translationWord `fellowship`) was rejected.
  The rejected proposal mapped `τῇ κοινωνίᾳ` to
  `நீங்கள் எங்களோடு ஊழியத்தில் ஐக்கியப்பட்டிருப்பதால்` in PHP 1:3 at
  confidence `0.97`. The audit contains no reviewer note, so it establishes a
  negative regression fixture but does **not** by itself justify a particular
  prompt, relationship, or confidence adjustment. Obtain or derive explicit
  linguistic evidence before changing production policy.

The per-project source audits remain local companion data, not repository
fixtures:

```text
%LOCALAPPDATA%\Bridge\data\projects\tam_irv_luk\.apps\translationCoreAI\semanticValidation\irvtam-v0.1.json
%LOCALAPPDATA%\Bridge\data\projects\tam_irv_php\.apps\translationCoreAI\semanticValidation\irvtam-v0.1.json
```

Next implementation steps, in order:

1. Export a sanitized, deterministic human-validation fixture keyed by
   candidate ID, proposal manifest hash/fingerprint, expected decision, and
   accepted/corrected mapping. Do not check in machine-specific paths or depend
   on the mutable local audit files in tests.
2. Add regressions for all 40 decisions, the PHP 1:3 → 1:6 sentinel, the
   corrected multi-span contract, the rejected fellowship proposal, audit
   persistence, and byte-identical USFM/native-selection preservation.
3. Calibrate by confidence band and relationship. Do not lower global
   safeguards or introduce Tamil-specific logic from one rejection. Any
   classifier change must have a stated linguistic cause and its own fixture.
4. Complete the remaining manual `Needs discussion` path. No `unsure` event is
   present in the current audits, so QA item M32 is still partial even though
   every proposal has a terminal confirm/correct/reject decision.
5. Run the focused semantic suites, complete Python suite, Svelte check,
   production frontend build, UI-state tests, Rust tests, frozen-sidecar smoke,
   and NSIS packaging. Then perform installed Beta 15 upgrade/persistence,
   validation, USFM-preservation, alignment, export, and Paratext acceptance.

Do not mark Beta 15 complete merely from the 40/40 review count. The checked-in
fixture, evidence-supported calibration decision, automated gates, exact
artifact provenance, and installed acceptance are still release requirements.

**Lesson worth keeping in mind for future phases:** every external
integration attempted so far (Wildebeest, USFM checker, versification,
Uroman) turned out to have a real, non-obvious problem that only surfaced by
actually running the code — wrong PyPI package name, a Python 3.13
compatibility break, an unpublished dependency, a Windows-only `strftime`
crash, a version-skew bug between upstream's GitHub and PyPI releases, a
class-level-state crash on a second call, a silently different data license
hiding inside an otherwise-permissive vendor tree. Verify by running, not by
reading a doc's description — including this repo's own docs.

**Deliberately not yet done** (scope decisions, not bugs):

- Live original-language resource downloads (current baseline is a pinned,
  bundled snapshot — see §4).
- Automatic continuous Paratext or Logos synchronization. Bridge currently
  performs explicit one-shot Paratext issue handoffs; the live Paratext path is
  verified, while Logos remains unverified against a running installation.
- A dedicated UI panel for alignment corpus statistics (protocol-only today).
- A second-language semantic-mapping corpus validation. The first IRVTam set is
  now fully reviewed, but its sanitized regression fixture and Beta 15 release
  gates described above are still pending.
- Manual alignment does not invent source tokens — it requires original-
  language tokens already present from import.

---

## 3. Dependencies

### Python (`engine/pyproject.toml`)

| Package | Type | Notes |
|---|---|---|
| `regex>=2024.5.15` | Required | Needed by the vendored USFM checker and by `versification.py`'s own dependency; floor raised to also satisfy `uroman`'s requirement. |
| `uroman>=1.3.1.1` | Required | Real PyPI package (name-checked — unlike Wildebeest, not a name trap). Same author (Ulf Hermjakob, USC/ISI) as Wildebeest and the vendored Greek Room tools. No known installability problems on any current Python version, so it's a hard dependency, not optional. License note: PyPI/upstream both claim "Apache" but the actual bundled `LICENSE.txt` is a custom MIT-style license with its own mandatory attribution clause — verified by reading the installed package, not the metadata. |
| `wildebeest-nlp==0.9.2` | Optional (`[wildebeest]` extra) | Real package name is `wildebeest-nlp`, **not** `wildebeest` (that name belongs to an unrelated ShopRunner image-processing package). Pinned to the only release that exists. Does not install under Python 3.13 (a docstring contains a lone-surrogate escape 3.13 rejects at compile time — confirmed still broken on upstream's GitHub HEAD too). The `WildebeestAdapter` degrades to a mock automatically whether this extra is installed or not, so leaving it uninstalled is always safe — just means Wildebeest-specific checks won't run for real. |
| `greekroom` (published PyPI package) | **Not used** | Left commented out in `pyproject.toml`. Only ships `owl` and `gr_utilities` submodules — USFM checker, versification, and Smart Edit Distance are none of those, so all three are vendored separately from source instead (see §4). |
| `pytest>=7.0`, `pyinstaller>=6.0` | Dev only | Test running and sidecar packaging. |

### Frontend (`package.json`)

| Package | Notes |
|---|---|
| `@tauri-apps/api`, `@tauri-apps/plugin-dialog`, `@tauri-apps/cli` | Tauri v2 core + native file dialogs. |
| `iso-639-3` | Offline searchable language catalog for import metadata (adds ~94 KB gzip to the bundle — Vite's non-fatal 500 KB chunk warning is from this; splittable later if startup size becomes a concern). |
| `svelte`, `svelte-check`, `@sveltejs/vite-plugin-svelte`, `@tsconfig/svelte` | Svelte 4 + TS tooling. |
| `tailwindcss`, `postcss`, `autoprefixer` | Styling. |
| `usfm-js` | USFM parsing/serialization on the frontend. |
| `word-aligner` | Alignment-related utility (translationCore ecosystem package). |
| `vite`, `typescript` | Build tooling. |

---

## 4. Vendored packages & bundled data

### Vendored source (not available as installable packages)

All three live under `engine/vendor/`, sourced from
[`BibleNLP/greek-room`](https://github.com/BibleNLP/greek-room), pinned
commit `18ddcf0e6c03fa2774b73b21186115d712e4cba9` (USFM checker and
versification; SED vendored separately, no PyPI package exists under any
name for it either):

| Vendored dir | Source path in upstream repo | Why vendored, not `pip install` |
|---|---|---|
| `engine/vendor/greekroom-usfm/` | `greekroom/greekroom/usfm/` | Not published on PyPI at all — only `owl` and `gr_utilities` are part of the `greekroom` package; `usfm` exists only in the source tree. Monolithic CLI script — invoked via subprocess/temp-dir, not a direct Python import (path-sensitive internal import: `from ualign_utilities import ...`). |
| `engine/vendor/greekroom-versification/` | `greekroom/greekroom/versification/` | Same repo/commit as USFM. Unlike the USFM checker, this one **is** a genuine importable library, so it's wired in as a direct import. Its `data/standard_mappings/*.json` files carry **CC BY-SA 4.0**, a different license than the BSD-3-Clause code around them — real distinction to track, not a rubber-stamp of the USFM checker's licensing precedent. |
| `engine/vendor/greekroom-smart-edit-distance/` | `smart_edit_distance/` | Not published on PyPI under any name (checked `smart-edit-distance` and `smart_edit_distance`, neither exists), and not part of the `greekroom` PyPI package either. |

Each vendored directory has its own `NOTICE.md` with full provenance
(source URL, path, pinned commit, fetch date) — check those before updating
or re-vendoring anything.

### Bundled offline data (`engine/resources/`)

Bridge ships original-language source text and English translation-helps
data so a raw Scripture import produces real, working checks and alignment
targets **without any network access** — the whole premise is field teams
with unreliable connectivity.

| Path | Contents | Size | Source |
|---|---|---|---|
| `engine/resources/hbo/bibles/uhb/` | Hebrew OT tokens | ~3.9 MB | unfoldingWord UHB v3.0.0, checksum-verified, exact pinned commit |
| `engine/resources/el-x-koine/bibles/ugnt/` | Greek NT tokens | ~1.5 MB | unfoldingWord UGNT v0.34, checksum-verified, exact pinned commit |
| `engine/resources/en/translationHelps/` | translationNotes, translationWords, translationWordsLinks, translationAcademy | ~42 MB | Pinned English unfoldingWord snapshot (raw Door43 TSV for tN), matching real translationCore's own practice of shipping English checking helps in its installer |

All 66 books / 31,103 verses / 443,131 canonical tokens are covered.
Existing aligned USFM or native translationCore projects are **never**
overwritten by this baseline — it only fills empty source arrays and stops
outright on a resource-version mismatch for legacy raw-import recovery. Full
generation process and licensing (CC BY-SA 4.0, with attribution) is
documented alongside the resources and reproducible via
`npm run vendor:original-language`
(`scripts/vendor-original-language-resources.mjs`).

### Critical design boundary: tN/tW are not fabricated

Raw USFM contains Scripture, not translationNotes or translationWords
checks. translationCore imports Scripture first and materializes tool
indexes from installed, versioned checking resources afterward — Bridge
follows the same boundary. A raw import records
`requires-resource-index` until the first background-check preflight for
that book actually materializes real entries from the bundled data above;
Bridge never generates fake/empty check entries to fill the gap.

---

## 5. AI triage — optional false-positive scoring

Greek Room checks are deliberately noisy: they say "this is objectively
suspicious," and a lot of what is suspicious is fine. AI triage is an
**optional, online-only overlay** that asks the configured model how likely
each already-persisted finding is to be a false positive, so the report
screen can hide the noisiest ones behind a slider.

It is an overlay in the strict sense: no check, report, decision or export
path reads a verdict, a finding is never rewritten, and with no API key and
no verdicts the report renders exactly as it did before triage existed.
That is the local-first requirement — nothing offline may depend on it.

**Modules.** `tc_ai_bridge/triage.py` (hashing, batching, context, parsing,
the per-book run), `tc_ai_bridge/triage_prompts.py` (four prompt families,
kept separate so wording can be tuned without touching logic), and
`triage_jobs.py` (a `ReportJobManager`-shaped background job in its own
lock domain).

**RPCs.** `triage.run` (`book?`, `force?`), `triage.status`,
`triage.cancel`, `triage.override` (`book`, `hash`, `verdict` — empty
clears), `triage.clear`, `triage.results`. `triage.results` is in
`report.get`'s 180 s timeout class; everything else stays interactive at
30 s so a long run can always be cancelled.

**Stored shape** — `.apps/translationCoreAI/triage/<book>.json`:

```json
{"schemaVersion": 1, "bookId": "rut", "updatedAt": "...",
 "entries": {"<hash20>": {
    "findingId": "...", "chapter": "1", "verse": "3-4",
    "checkType": "wildebeest.script.mixed", "family": "mechanical",
    "verdict": "false_positive|true_positive|uncertain",
    "confidence": 0, "reason": "...", "model": "...", "timestamp": "...",
    "userOverride": null }}}
```

Four design points worth knowing before changing any of it:

1. **One file per book, not per chapter, and not SQLite.** Measured on the
   real 66-book collections: the first open of any file on Windows costs
   ~20–27 ms regardless of size, so file *count* dominates — 66 files read
   in ~2 s where 1,189 would take ~25–30 s. Bridge's existing
   `bridge-semantic.sqlite3` is per book too, so joining it would not have
   made a collection read one query; it would only have inherited the
   passage-semantic runtime's recovery states, migrations and per-open
   integrity check.
2. **Records are keyed by a hash of the finding's *evidence*** — NFC- and
   whitespace-normalised `original_text`, `suggested_replacement`,
   `explanation` and evidence pairs, plus book/chapter/verse/check type.
   Deliberately **not** `_stable_finding_id`, which must stay stable across
   an edit so a human decision survives. A verdict about evidence that
   changed is worthless, so it is discarded rather than carried forward.
   Offsets are excluded so text shifting inside a verse does not orphan
   every verdict in it. `qa_report` stamps this hash on Greek Room rows as
   `triageHash`, and the report screen merges verdicts by dict lookup.
3. **Nothing is ever re-bought.** A run over unchanged findings makes zero
   model calls. A `userOverride` is skipped even under `force` — overriding
   is also how a reviewer stops paying for a finding they have judged.
4. **Failure is always survivable.** An unparseable response or a network
   error degrades that batch to `uncertain` at confidence 0 — the one shape
   the slider can never hide — and logs the raw text. The reason names the
   actual cause. A run whose every batch failed reports `failed`, not
   `succeeded`.

**Concurrency.** `triage.override` (dispatcher thread) and the run worker
both load-merge-save the same book file under one `BridgeEngine._triage_lock`,
and the worker re-reads immediately before merging each batch, so an
override recorded mid-run survives. This is the same lost-update class that
`.bridge/progress.json` still has between its two writers — see the known
gaps in `BUILD_LOG.md`.

**The slider** lives in `AppSettings.triage_hide_threshold` (default 90,
`0` = off, otherwise clamped to 50–100). Only a `false_positive` verdict at
or above the threshold hides anything; `uncertain` and `true_positive` are
always shown, because hiding a real translation error is a far worse
failure than leaving a false positive on screen.

---

## 6. Finding context menu — one component, two surfaces

`src/lib/components/FindingContextMenu.svelte` is presentation only: it takes
`x`/`y`, a `findingLabel` and an `actions` array, and dispatches `action` and
`close`. It owns Escape/Tab/outside-click dismissal, roving arrow-key focus,
focus restore, and viewport clamping (`positionInsideViewport`, `EDGE_GAP = 8`).
Two very different surfaces mount it, and **neither owns it** — put dismissal
or positioning behaviour in the component, and only the action list in a caller:

| Caller | Findings from | Menu offers | Decisions written as |
|---|---|---|---|
| `VerseList.svelte` (verse editor) | `findingsByVerse` store — engine `QaFinding`s | **Accept finding** (applies the proposed correction, then files the accept) / **Ignore** | `FindingStatus` via `decideLocalFinding`, shared with `ReviewPanel.svelte` |
| `AlignmentQaMode.svelte` (QA review queue) | `QaFindingList.svelte` rows, which dispatch `contextmenu` upward | **Apply proposed fix** plus the four `REVIEWER_ACTIONS` | `QaDisposition` via `decideFinding`, labels from `REVIEWER_ACTIONS` |

Three rules a new contributor will otherwise get wrong:

1. **The menu is never the only route to an action** — that is an
   accessibility defect, and it is what issue #38 was reopened for. Both
   surfaces must respond to `ContextMenu` and `Shift+F10` and advertise
   `aria-keyshortcuts`.
2. **One tab stop per list, not per finding.** `QaFindingList`'s listbox
   viewport and `VerseList`'s verse row are each a single tab stop, with arrow
   keys moving the active item inside them. Making every row or every
   `<mark>` focusable would put hundreds of tab stops in a checked chapter.
3. **The two surfaces do not share a decision vocabulary, on purpose** — and
   "accept" means opposite things in them (`Accept finding` = "this is a real
   problem"; `Accept translation as correct` = "there is no problem"). Every
   item carries a `title` hint saying which way it points. Don't unify the two
   models to make the labels match.
4. **The editor menu mirrors `ReviewPanel`'s own two actions on an open Greek
   Room finding, and should keep doing so.** It deliberately has no separate
   apply-fix item: applying a correction and accepting the finding that
   prompted it are one act, so `Accept finding` does both when
   `suggested_replacement` and offsets are present and files the accept alone
   when they are not. A correction that fails to apply is *not* accepted
   instead — surface the reason and leave the menu open.
5. **Key decisions by the displayed verse string, not `QaFinding.verse`.**
   That field is a numeric anchor (`bridge_service.py:238` takes the first
   numeric component), so a verse bridge `3-4` becomes `3` and the decision
   lands under the wrong reference and misses the `"chapter:verse"` store key.
   `ReviewPanel` uses `$currentChapter`/`$selectedVerse`; `VerseList` carries
   the exact verse on its `contextMenu` state for the same reason.

---

## 7. Where the deeper docs live

| Doc | Covers |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Full design rationale, protocol shape, `QaFinding` model. |
| [`BUILD_LOG.md`](BUILD_LOG.md) | Session-by-session build log — the ground truth for anything this guide summarizes. Also the current gotcha list and known-gaps list, verified as of each update. |
| [`IMPORTS.md`](IMPORTS.md) | Import pipeline design: supported inputs, normalized project schema, duplicate-safety logic, provenance. |
| [`ALIGNMENT.md`](ALIGNMENT.md) | Manual word-alignment protocol, persistence, completion states. |
| [`QA_TEST_MATRIX.md`](QA_TEST_MATRIX.md) | Release gate — what's tested, how, and current pass/fail status per release candidate. |
