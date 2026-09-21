# Bridge full-app manual QA checklist

This checklist is the executable manual test plan for the installed Windows
desktop application. It complements [`QA_TEST_MATRIX.md`](QA_TEST_MATRIX.md),
which records release evidence and historical status, and
[`ACCEPTANCE_TEST_GUIDE.md`](ACCEPTANCE_TEST_GUIDE.md), which is a focused
0.9.7 acceptance walkthrough. Checking a box here means the named test was run
for the build recorded below; it does not change the status in the release
matrix.

## Execution tracking

GitHub tracks this run in [master QA issue #150](https://github.com/RevantCI/bridge/issues/150)
and the [QA project view](https://github.com/users/RevantCI/projects/6/views/4).
The native sub-issue hierarchy is the authoritative progress roll-up; the
checkboxes below provide a quick execution index.

- [ ] [#151 — QA 00: Test preparation and release smoke](https://github.com/RevantCI/bridge/issues/151)
- [ ] [#152 — QA 01: Installation, upgrade, launch, and shutdown](https://github.com/RevantCI/bridge/issues/152)
- [ ] [#153 — QA 02: Project Home and import](https://github.com/RevantCI/bridge/issues/153)
- [ ] [#154 — QA 03: Project management, dashboard, and collections](https://github.com/RevantCI/bridge/issues/154)
- [ ] [#155 — QA 04: Scripture navigation, rendering, and editing](https://github.com/RevantCI/bridge/issues/155)
- [ ] [#156 — QA 05: Local checks, background jobs, and finding review](https://github.com/RevantCI/bridge/issues/156)
- [ ] [#157 — QA 06: Translation Notes/Words and AI review](https://github.com/RevantCI/bridge/issues/157)
- [ ] [#158 — QA 07: Manual word alignment](https://github.com/RevantCI/bridge/issues/158)
- [ ] [#159 — QA 08: Cross-verse alignment](https://github.com/RevantCI/bridge/issues/159)
- [ ] [#160 — QA 09: Alignment Review: Word, Semantic, Passage, and QA](https://github.com/RevantCI/bridge/issues/160)
- [ ] [#161 — QA 10: Correction proposal, apply, re-analysis, and verification](https://github.com/RevantCI/bridge/issues/161)
- [ ] [#162 — QA 11: Project QA report and AI triage](https://github.com/RevantCI/bridge/issues/162)
- [ ] [#163 — QA 12: Settings, resources, privacy, and connectors](https://github.com/RevantCI/bridge/issues/163)
- [ ] [#164 — QA 13: Export and interoperability](https://github.com/RevantCI/bridge/issues/164)
- [ ] [#165 — QA 14: Accessibility, localization, and visual quality](https://github.com/RevantCI/bridge/issues/165)
- [ ] [#166 — QA 15: Reliability, recovery, performance, and data safety](https://github.com/RevantCI/bridge/issues/166)
- [ ] [#167 — QA 16: Final regression and release sign-off](https://github.com/RevantCI/bridge/issues/167)

## Run record

- [ ] Tester:
- [ ] Date and time:
- [ ] Bridge version / commit:
- [ ] Installer filename:
- [ ] Installer SHA-256:
- [ ] Windows version and architecture:
- [ ] Display size and scale:
- [ ] Test-data location:
- [ ] Network state: online / offline / both
- [ ] AI provider and model, if used:
- [ ] Paratext version and active project, if used:
- [ ] Logos version and open resource, if used:
- [ ] Evidence folder or URL:

Use a fresh copy of every test project. Never run edit, correction, alignment,
or recovery cases against the only copy of a translator's project.

## Result and priority conventions

- Check the box only after the expected result is observed.
- Record failures as `FAIL — <defect URL or short note>` beside the case.
- Record unavailable dependencies as `BLOCKED — <reason>`; do not mark them as
  passed.
- `P0` protects Scripture, audit history, or the ability to open/use the app.
- `P1` protects a primary user workflow. `P2` covers quality and edge behavior.
- Capture a screenshot or short recording for every failure and for the release
  sign-off cases.

## Recommended test data

- [ ] `DATA-001 P0` Keep one untouched backup and one disposable working copy of
  each fixture; verify their paths are different.
- [ ] `DATA-002 P1` Prepare a small English USFM project with headings, poetry,
  footnotes, milestones, repeated words, a verse bridge (`3-4`), and a lettered
  verse (`3a`).
- [ ] `DATA-003 P1` Prepare Tamil and Odia projects containing real non-Latin
  text, combining marks, and known findings.
- [ ] `DATA-004 P1` Prepare one RTL target project and Hebrew/Greek source data.
- [ ] `DATA-005 P1` Prepare a multi-book folder and a translationCore project
  with existing alignments, selections, and check decisions.
- [ ] `DATA-006 P1` Prepare malformed, duplicate-verse, unknown-language, and
  path-traversal archive samples for negative import tests.
- [ ] `DATA-007 P1` Prepare an eligible Stage 9B correction fixture and a
  cross-verse semantic/alignment fixture.
- [ ] `DATA-008 P2` Prepare a large collection or book for performance and
  cancellation tests.

## Release smoke subset

Run this subset on every candidate installer before the full suite:

- [ ] `SMK-001 P0` Install, launch, and reach Project Home with the engine ready.
- [ ] `SMK-002 P0` Import one non-Latin USFM file and open its first verse.
- [ ] `SMK-003 P0` Run checks, review a finding, restart, and confirm the decision
  persists.
- [ ] `SMK-004 P0` Edit a verse, save it, observe rechecking, and confirm the edit
  survives restart.
- [ ] `SMK-005 P0` Open Align Words, save a valid alignment, and confirm it
  survives restart.
- [ ] `SMK-006 P0` Export aligned and non-aligned USFM, then re-import both.
- [ ] `SMK-007 P1` Generate the QA report and export one filtered CSV.
- [ ] `SMK-008 P0` Close Bridge normally and confirm no `bridge-engine.exe`
  remains.

## 1. Installation, upgrade, launch, and shutdown

- [ ] `INS-001 P0` Install on a machine without Bridge; the installer completes,
  a Start entry is created, and Windows shows the expected unsigned-app warning
  without any unexplained error.
- [ ] `INS-002 P1` Launch from the Start entry; one Bridge window opens, the
  loading state clears, and Project Home is usable.
- [ ] `INS-003 P0` Confirm both packaged workers are present and normal import,
  check, and USFM validation actions do not report a missing sidecar.
- [ ] `INS-004 P1` Launch while offline; Project Home, import, local checks,
  alignment, review, report, and export remain available.
- [ ] `INS-005 P1` Launch Bridge twice; the result is predictable and no project
  data is corrupted or silently shared between conflicting sessions.
- [ ] `INS-006 P0` Upgrade over the previous supported build; registered projects,
  settings, decisions, alignments, proposals, and histories remain readable.
- [ ] `INS-007 P0` Open a project database created by the previous build; forward
  migration completes without losing old rows or changing Scripture.
- [ ] `INS-008 P0` Close the window normally; the app exits, the engine records an
  orderly stdin-close exit, no worker remains, and no `_MEI*` directory leaks.
- [ ] `INS-009 P1` End the app while a whole-book job is running; after cleanup or
  restart, Bridge starts again, reports/recoveries are coherent, and no locked
  worker prevents the next build or launch.
- [ ] `INS-010 P2` Uninstall Bridge; the application binaries are removed while
  user projects are not deleted.

## 2. Project Home and import

- [ ] `IMP-001 P0` Import one `.usfm` file through the picker; inspect/preview
  shows the correct book, language, Bible, destination, and capability status,
  then creates one usable project.
- [ ] `IMP-002 P1` Import valid `.sfm` and `.txt` Scripture files; marker
  validation accepts them and preserves their text.
- [ ] `IMP-003 P0` Import a folder with several books; Bridge creates one linked
  project per book and opens the collection without waiting for all siblings to
  normalize.
- [ ] `IMP-004 P0` Open a translationCore project; existing alignments,
  selections, decisions, source files, and app data are preserved.
- [ ] `IMP-005 P1` Import `.tcore`, `.tstudio`, and `.zip` archives; each is safely
  extracted and produces the same preview/import flow.
- [ ] `IMP-006 P1` Import a Paratext-style folder; metadata and books are detected
  and the source folder remains unchanged.
- [ ] `IMP-007 P1` Import an unknown-language file; language, project, and Bible
  fields are required, searchable, validated, and saved correctly.
- [ ] `IMP-008 P0` Import malformed markers or duplicate verses; Bridge shows an
  explicit failure and never reports a clean import/check.
- [ ] `IMP-009 P0` Import a path-traversal archive; it is rejected and no file is
  written outside the chosen destination.
- [ ] `IMP-010 P0` Import UTF-8 BOM, Tamil, Odia, Hebrew, and Greek content; text
  is preserved without replacement characters or Windows encoding errors.
- [ ] `IMP-011 P1` Drag exactly one file from Explorer onto Bridge; the same
  inspect, preview, duplicate review, and import flow opens as with the picker.
- [ ] `IMP-012 P1` Drag exactly one folder; the drop overlay is clear and the
  folder is inspected as a project source.
- [ ] `IMP-013 P2` Drop zero/multiple paths or an unsupported item; Bridge explains
  the constraint, imports nothing, and remains usable.
- [ ] `IMP-014 P0` Import the exact same source twice; Bridge offers the existing
  project by default and writes a separate suffixed copy only after explicit
  separate-copy intent.
- [ ] `IMP-015 P0` Import changed content with matching book/language/Bible
  metadata; possible overlap and coverage are shown without automatic merge or
  overwrite.
- [ ] `IMP-016 P1` Inspect a source whose books are scattered across unrelated
  projects; Bridge warns with exact coverage but does not treat them as one
  complete duplicate.
- [ ] `IMP-017 P1` Inspect a source exactly covered by one existing collection;
  Bridge offers that collection and blocks the default duplicate import.
- [ ] `IMP-018 P1` Cancel at preview and metadata stages; no partial project,
  registry entry, or unexpected destination content remains.

## 3. Project management, dashboard, and collections

- [ ] `PRJ-001 P0` Restart after import; Project Home discovers managed projects
  and lists recent external projects.
- [ ] `PRJ-002 P1` Open a recent project card without browsing for its folder;
  the correct project and last useful context open.
- [ ] `PRJ-003 P1` Move a registered project, use Locate, and confirm its stable
  project ID and history remain attached.
- [ ] `PRJ-004 P0` Move a multi-book collection parent and locate/reopen it; every
  sibling remains switchable through portable collection metadata.
- [ ] `PRJ-005 P1` Remove a project folder outside Bridge; its card remains with
  Locate and Forget actions rather than disappearing silently.
- [ ] `PRJ-006 P0` Choose Forget for a missing project; only the registry entry is
  removed and no project files are deleted.
- [ ] `PRJ-007 P1` Open a corrupt-registry scenario; Bridge quarantines the bad
  registry, rediscovers managed projects, and reports recovery clearly.
- [ ] `PRJ-008 P1` Open a large Project Home; discovery finishes within the
  agreed budget, related matches are bounded, and scrolling remains responsive.
- [ ] `PRJ-009 P1` On the dashboard, verify book/chapter progress, approved counts,
  check state, and navigation match the underlying project.
- [ ] `PRJ-010 P1` Switch books while verse/check/review state is populated; no
  chapter/verse data from the previous book appears in the new book.
- [ ] `PRJ-011 P1` First-open a lazy sibling; preparation is visible, normalization
  finishes, and other collection members remain intact.
- [ ] `PRJ-012 P2` Move among Projects, dashboard, editor, Alignment Review, and QA
  report with breadcrumbs; each returns to the expected project and screen.

## 4. Scripture navigation, rendering, and editing

- [ ] `EDT-001 P1` Navigate with book, chapter, and verse selectors; the selected
  reference, Scripture row, review panel, and connector reference stay in sync.
- [ ] `EDT-002 P1` Use previous/next chapter controls at the first, middle, and
  last chapter; buttons disable correctly at boundaries.
- [ ] `EDT-003 P1` Enter a valid reference in Jump; Bridge opens the exact verse
  and scrolls the selected row to the top.
- [ ] `EDT-004 P2` Enter malformed, missing, bridge, and lettered references;
  valid forms navigate and invalid forms fail clearly without changing context.
- [ ] `EDT-005 P1` Rapidly switch chapters/books during loads; stale responses do
  not overwrite the final selection.
- [ ] `EDT-006 P1` Verify headings, poetry, footnotes, notes, milestones, and custom
  markers render without appearing as broken raw syntax.
- [ ] `EDT-007 P1` Open and close a footnote/note popup; multiple notes paginate,
  the anchor is correct, and keyboard focus is restored.
- [ ] `EDT-008 P0` Edit a verse, save, and reopen it; exact Unicode text and verse
  identity persist and the original imported USFM remains preserved.
- [ ] `EDT-009 P1` Cancel an edit; neither displayed text nor project files change.
- [ ] `EDT-010 P0` Attempt a concurrent/stale save; Bridge refuses it and does not
  overwrite the newer text.
- [ ] `EDT-011 P1` Edit a verse with alignments and reviews; dependent state is
  marked invalid/stale and rechecking begins visibly.
- [ ] `EDT-012 P1` Start editing, then receive Paratext/Logos navigation; Bridge
  refuses or defers the move and keeps the edit safe.
- [ ] `EDT-013 P1` Edit Tamil/Indic decomposed text; combining marks and grapheme
  clusters remain intact in display, save, diff, and restart.
- [ ] `EDT-014 P1` Edit a verse bridge or lettered segment; navigation and saved
  decisions keep the exact displayed verse string.
- [ ] `EDT-015 P2` Select single and multiple verses where supported; the range is
  visible and the action applies only to the selected references.

## 5. Local checks, background jobs, and finding review

- [ ] `CHK-001 P0` Run checks for one verse; progress completes, findings attach to
  the correct verse, and the app stays responsive.
- [ ] `CHK-002 P1` Run chapter and whole-book checks; counts progress monotonically
  and results do not leak across scopes.
- [ ] `CHK-003 P1` Cancel a running job; status becomes Cancelled, completed work is
  not presented as a full success, and Retry is available.
- [ ] `CHK-004 P1` Retry a cancelled/failed job; only failed or unfinished work
  resumes and completed results are not duplicated.
- [ ] `CHK-005 P1` Navigate during a job; status remains visible while findings and
  progress stay attached to their correct book/chapter/verse.
- [ ] `CHK-006 P1` Exercise spelling, punctuation, USFM structure,
  versification-sensitive, and names/transliteration findings; each has a clear
  category, severity, message, and location.
- [ ] `CHK-007 P0` Accept a finding with a proposed correction; Scripture changes
  only after the explicit action, the verse rechecks, and the finding moves to
  Accepted with its underline cleared.
- [ ] `CHK-008 P1` Accept a finding with no correction; the decision persists but
  Scripture does not change.
- [ ] `CHK-009 P1` Ignore a finding; its underline clears, it appears in Ignored,
  and it remains ignored after navigation and restart.
- [ ] `CHK-010 P1` Re-run checks after decisions; stable finding IDs reattach prior
  decisions instead of creating duplicate undecided items.
- [ ] `CHK-011 P1` Right-click a finding near each window edge; the menu remains
  fully visible and contains exactly Accept finding and Ignore.
- [ ] `CHK-012 P1` Open the finding menu with Shift+F10 and the Menu key; arrow,
  Home/End, Enter, Escape, Tab, and outside-click behavior is correct and focus
  returns to the verse row.
- [ ] `CHK-013 P1` Right-click a verse with no finding; AI review scopes and Edit
  verse appear, while a finding span still opens only finding actions.
- [ ] `CHK-014 P0` Review findings on `3-4` and `3a`; decisions persist against the
  exact reference after restart.
- [ ] `CHK-015 P1` Force a checker error or unavailable optional component; Bridge
  reports limited/unavailable status rather than false-clean success.

## 6. Translation Notes/Words and AI review

- [ ] `TH-001 P1` Open a newly imported project; Translation Helps shows Preparing
  until real tN/tW indexes are available and never invents resources.
- [ ] `TH-002 P1` Open a verse with tN/tW checks; source quote, occurrence,
  selection, provenance, evidence, and current status are correct.
- [ ] `TH-003 P0` Edit a selection to an exact target substring and occurrence;
  save succeeds, persists, and highlights the intended occurrence only.
- [ ] `TH-004 P0` Enter target text not present in the current verse; save is
  rejected and the previous selection remains unchanged.
- [ ] `TH-005 P1` Add multiple selections, remove one, save, and restart; ordering,
  occurrence data, and provenance persist.
- [ ] `TH-006 P1` Mark Nothing to select; it persists, and contradictory AI problem
  evidence warns instead of silently treating it as passed.
- [ ] `TH-007 P1` Clear a selection; the current state changes without deleting
  its lifecycle/audit history.
- [ ] `TH-008 P1` With no API key, AI review controls explain unavailability and
  the manual/offline workflow remains fully usable.
- [ ] `TH-009 P1` In Basic mode, run verse AI review; only grounded,
  high-confidence, unambiguous same-verse selections are applied.
- [ ] `TH-010 P0` Confirm Basic AI review never overwrites an imported or human
  selection.
- [ ] `TH-011 P1` In Advanced mode, run review; proposals and evidence appear but
  no translationCore state changes until Apply AI proposal.
- [ ] `TH-012 P1` Apply, edit, and clear an Advanced proposal; each path records the
  correct provenance and survives restart.
- [ ] `TH-013 P1` Run chapter and book AI review while navigating; work stays
  responsive and results land on the correct references.
- [ ] `TH-014 P1` Cancel during a provider request, then Retry; cancelled work is
  incomplete and only unfinished/failed verses resume.
- [ ] `TH-015 P1` Edit a reviewed verse; an explicit stale warning appears, Run AI
  review again refreshes it, and stale evidence is not shown as current.
- [ ] `TH-016 P1` Review cross-verse, split, reordered, and implicit mappings;
  companion mappings are described and never applied as verse-local tC
  selections.
- [ ] `TH-017 P1` Exhaust the structural passage budget; the card says Needs
  extended passage review, never omission or Nothing to select.
- [ ] `TH-018 P2` Record real-provider latency, token usage, output quality, and any
  unsupported-model fallback without exposing the API key in screenshots/logs.

## 7. Manual word alignment

- [ ] `ALN-001 P1` Open Align Words from the review panel and per-row `⇄` glyph;
  both open the same verse and the glyph color matches completion status.
- [ ] `ALN-002 P0` Create and save 1:1, 1:many, many:1, and many:many groups; exact
  source/target token identities are preserved.
- [ ] `ALN-003 P0` Align repeated target words; occurrence and total-occurrence
  values round-trip after close and restart.
- [ ] `ALN-004 P1` Drag tokens/groups in both directions; drop targets, selected
  state, and conflict feedback are clear.
- [ ] `ALN-005 P0` Confirm an established/protected group is not silently merged or
  overwritten by a conflicting operation.
- [ ] `ALN-006 P1` Unalign a group, Undo, and restore selected state; the word bank
  and groups return exactly to the saved version.
- [ ] `ALN-007 P0` Attempt a stale/concurrent editor save; it is rejected without
  overwriting the other edit.
- [ ] `ALN-008 P1` Edit target Scripture; alignment reconciles where safe and the
  verse is visibly marked invalid when identities changed.
- [ ] `ALN-009 P1` Try Complete with unaligned source or target tokens; completion
  is blocked with actionable guidance.
- [ ] `ALN-010 P1` Complete a fully valid verse; green status persists and feeds
  corpus statistics.
- [ ] `ALN-011 P1` Open a project with missing original-language resources; Bridge
  gives import guidance and never downloads or invents tokens.
- [ ] `ALN-012 P1` Verify Greek/Hebrew tokens, punctuation, morphology/gloss
  popups, and RTL ordering render correctly.
- [ ] `ALN-013 P1` Close/reopen the project; groups, completion, invalid state, and
  append-only history persist.
- [ ] `ALN-014 P1` Generate an AI alignment proposal with no key; a structured
  unavailable message appears and no write occurs.
- [ ] `ALN-015 P1` Review a real AI alignment proposal; nothing changes until
  explicit Apply and protected groups survive.
- [ ] `ALN-016 P1` Export aligned USFM and re-import it; `zaln`/`w` groups and
  repeated occurrences round-trip.

## 8. Cross-verse alignment

- [ ] `XVA-001 P1` Open the cross-verse tool with a valid range; source/target
  passage streams show the intended references and current links.
- [ ] `XVA-002 P1` Search/filter the virtual passage stream; matching verses stay
  selectable and no-match feedback is clear.
- [ ] `XVA-003 P0` Create a cross-verse link; source and target identities,
  relationship, provenance, and history persist after restart.
- [ ] `XVA-004 P1` Remove an unlinked selection and an existing link; only the
  intended relationship changes.
- [ ] `XVA-005 P1` Run the offline suggestion path; corpus evidence is shown and no
  network requirement is introduced.
- [ ] `XVA-006 P1` With no API key, the AI suggestion action is hidden/disabled
  while offline suggestions still work.
- [ ] `XVA-007 P1` With a real provider, run Suggest with AI; readable reasons and
  AI-only versus both-agree provenance are distinguishable.
- [ ] `XVA-008 P0` Confirm both-agree pairs auto-link only when corroborated;
  high-confidence uncorroborated pairs remain unapplied.
- [ ] `XVA-009 P0` Stop a batch on the first refused/conflicting link; later pairs
  are not silently applied and proposing alone writes nothing.
- [ ] `XVA-010 P1` Close/reopen after links and removals; UI, statistics, and
  append-only change log agree.

## 9. Alignment Review: Word, Semantic, Passage, and QA

- [ ] `REV-001 P1` Open Alignment Review; QA is the initial mode and Word,
  Semantic, Passage, and QA tabs are keyboard reachable.
- [ ] `REV-002 P1` Switch modes repeatedly; the selected finding/reference remains
  coherent and no stale evidence from another project appears.
- [ ] `REV-003 P1` Run passage/chapter/book/range analysis; stage progress is
  visible and the persisted job completes without freezing the editor.
- [ ] `REV-004 P1` Navigate during analysis; the active job remains visible and the
  queue refreshes only with results for the selected canonical scope.
- [ ] `REV-005 P1` Filter and paginate the QA queue; counts, rows, and empty state
  match the active scope.
- [ ] `REV-006 P1` Inspect source meaning, target location, relationship,
  confidence, resources, and provenance; evidence agrees across list and detail.
- [ ] `REV-007 P1` Open a cross-verse finding; Bridge identifies the mapped target
  verse and navigates there without offering an unsafe native verse-local apply.
- [ ] `REV-008 P1` Record Confirmed issue, Accept translation as correct, Needs
  review, and note actions as applicable; latest state and history update.
- [ ] `REV-009 P0` Restart and revisit the scope; reviewer, timestamp, note,
  disposition, and full append-only history persist.
- [ ] `REV-010 P1` Switch between two previously analysed scopes; each restores its
  own queue, counts, and review history.
- [ ] `REV-011 P1` Analyze a scope with no findings; the completion/empty message is
  explicit and not confused with a running or failed job.
- [ ] `REV-012 P1` Force analysis failure/cancellation; the state is retryable and
  previous successful evidence is not relabeled as current success.
- [ ] `REV-013 P1` Verify limited lexical/structural retrieval is disclosed when no
  multilingual embedding provider is available.
- [ ] `REV-014 P0` Edit source/current target text relevant to a mapping; content
  fingerprints prevent reuse of stale mapping/evidence.
- [ ] `REV-015 P2` Compare the same finding in Word, Semantic, Passage, and QA
  views; terminology and reference ownership stay consistent.

## 10. Correction proposal, apply, re-analysis, and verification

- [ ] `COR-001 P0` Select a confirmed eligible QA issue; Correction shows current
  text, target span, affected meaning, evidence, provenance, and eligibility.
- [ ] `COR-002 P1` Open an ineligible finding; Bridge explains why and exposes no
  unsafe apply path.
- [ ] `COR-003 P1` Create a manual proposal for an exact span; proposed full verse
  and explanation are correct and Scripture remains unchanged.
- [ ] `COR-004 P1` Generate a provider proposal; only relevant correction intent
  and evidence are sent, and the returned wording still requires review.
- [ ] `COR-005 P0` Edit a proposal; a new history event/version is written and the
  previous wording remains visible.
- [ ] `COR-006 P0` Reject a proposal; rejection writes history, does not delete it,
  and does not change Scripture.
- [ ] `COR-007 P0` Regenerate/supersede a proposal; the old proposal remains in the
  append-only history with an explicit relationship to the replacement.
- [ ] `COR-008 P0` Change Scripture after proposal review, then try Apply; compare-
  and-swap refuses the stale proposal and leaves current text untouched.
- [ ] `COR-009 P0` Open Apply confirmation, review exact before/after wording, then
  cancel; no write or applied ledger state occurs.
- [ ] `COR-010 P0` Confirm Apply once; exactly one authorized Scripture write and
  one application intent occur, with no duplicate on repeated input.
- [ ] `COR-011 P0` Restart immediately around apply; recovery reports a coherent
  applied/not-applied state and never writes the correction twice.
- [ ] `COR-012 P0` Run affected re-analysis; the application remains verification
  pending and is not called corrected merely because a finding disappeared.
- [ ] `COR-013 P0` Verify correction with current positive Stage 6B/7/8 evidence;
  pass/fail/uncertain reasoning is visible and traceable.
- [ ] `COR-014 P0` On failed or uncertain verification, confirm Mark corrected is
  unavailable and Scripture remains as explicitly applied.
- [ ] `COR-015 P0` On passed verification, choose Mark correction as corrected;
  only this explicit acknowledgement closes the QA issue.
- [ ] `COR-016 P0` Restart and inspect proposal/application/verification history;
  all superseded and lifecycle records remain readable and ordered.

## 11. Project QA report and AI triage

- [ ] `RPT-001 P1` Generate a whole-collection report; background progress,
  cancellation, completion, and return-to-report behavior are clear.
- [ ] `RPT-002 P1` Compare report book/chapter totals and findings with dashboard
  and review state; counts and current/stale distinctions agree.
- [ ] `RPT-003 P1` Filter by book, category, fixed-by, result, severity, and text;
  combine filters and confirm tiles, charts, rows, and pagination agree.
- [ ] `RPT-004 P1` Clear filters; the full report and original counts return.
- [ ] `RPT-005 P1` Inspect rows for Greek Room, tN, tW, alignment, AI review,
  Ignore, and correction outcomes; labels and provenance are accurate.
- [ ] `RPT-006 P1` Open a report row; Bridge navigates to the correct book,
  chapter, verse, and relevant review context.
- [ ] `RPT-007 P1` Include a lazy/missing collection sibling; the report handles it
  explicitly instead of hanging or silently omitting the book.
- [ ] `RPT-008 P1` Cancel generation; partial output is not presented as a complete
  report and generation can be started again.
- [ ] `RPT-009 P1` Exercise empty and failed report states; recovery actions work
  and the rest of the app stays responsive.
- [ ] `RPT-010 P1` Export filtered CSV and TSV; only filtered rows are included,
  UTF-8 BOM and quoting preserve commas/newlines/non-Latin text, and headers are
  reviewer-friendly.
- [ ] `RPT-011 P1` Print to PDF; only report content prints, every filtered row is
  present across pages, and charts/table do not clip.
- [ ] `RPT-012 P1` With no API key, report stays usable and Run AI triage explains
  why it is unavailable.
- [ ] `RPT-013 P1` Run real AI triage; progress, cancellation, retry, latency,
  spend, verdict distribution, and uncertain failures are observable.
- [ ] `RPT-014 P0` Move the triage threshold and apply overrides; only visibility
  changes—findings, decisions, report data, and exports remain authoritative.
- [ ] `RPT-015 P1` Force a dead endpoint; triage fails cleanly, the sidecar remains
  alive, and the untriaged report is unchanged.
- [ ] `RPT-016 P1` Restart; persisted verdicts/overrides reappear only when their
  finding hashes are current.

## 12. Settings, resources, privacy, and connectors

- [ ] `SET-001 P1` Open every Settings pane—AI, Quality, Connections, Resources,
  and Security—by mouse and keyboard; controls, descriptions, and close behavior
  are correct.
- [ ] `SET-002 P1` Switch Basic/Advanced reviewer mode; the intended controls and
  automation policy change without losing project state.
- [ ] `SET-003 P1` Change supported non-secret settings, save, restart, and confirm
  values persist.
- [ ] `SET-004 P0` Save an API key; settings files, diagnostics, errors, reports,
  and screenshots never expose the plaintext secret.
- [ ] `SET-005 P1` Replace/clear the key; provider availability updates and the old
  key is no longer usable.
- [ ] `SET-006 P1` Inspect Resources with Old/New Testament projects; correct
  UHB/UGNT version, owner, license, language, and provenance are shown.
- [ ] `SET-007 P1` Open a project initialized with a different resource version;
  Bridge warns and does not silently replace source tokens.
- [ ] `SET-008 P1` Disconnect the network and confirm bundled fonts/resources work
  with no login or download prompt.
- [ ] `SET-009 P1` With Paratext closed or plugin absent, Refresh reports a clean
  unavailable state and Bridge remains responsive.
- [ ] `SET-010 P1` With the companion loaded and matching project active, enable
  Paratext navigation; moves synchronize both directions without loops.
- [ ] `SET-011 P0` Activate a different Paratext project; Bridge refuses note
  handoff/navigation writes and identifies the project mismatch.
- [ ] `SET-012 P1` Create a tN/tW issue resolution and queue Paratext handoff while
  offline; audit and Notes 1.1 copy persist, Retry sends once, and repeats do not
  duplicate the thread.
- [ ] `SET-013 P1` With Logos unavailable, Refresh reports a clean COM/unavailable
  state and does not crash or time out.
- [ ] `SET-014 P1` With Logos open, enable navigation and move references both
  directions; supported references synchronize without feedback loops.
- [ ] `SET-015 P1` Disable each connector; polling/network-shaped work stops and
  Bridge navigation no longer follows that application.
- [ ] `SET-016 P2` Open Diagnostics; recent engine logs stream, copy/readability is
  adequate, non-Latin text is intact, and no secret is present.

## 13. Export and interoperability

- [ ] `EXP-001 P0` Before export eligibility, Export is disabled with a clear
  reason; once requirements are met it becomes available.
- [ ] `EXP-002 P0` Export aligned USFM; filename/location are chosen explicitly and
  the result is valid, re-importable USFM 3 with occurrence-aware groups.
- [ ] `EXP-003 P0` Export non-aligned USFM; it is valid and re-importable without
  leaking alignment milestones.
- [ ] `EXP-004 P0` Compare source and export for headings, poetry, footnotes,
  milestones, ESFM/custom markers, verse bridges, and lettered segments; no
  silent structural loss occurs.
- [ ] `EXP-005 P0` Confirm source-template export preserves untouched material and
  clearly discloses fallback behavior when no source template exists.
- [ ] `EXP-006 P1` Export Tamil, Odia, Hebrew, and Greek content; encoding and
  directionality survive external open and re-import.
- [ ] `EXP-007 P1` Cancel the save dialog and an in-progress export; no false
  success or corrupt destination file is reported.
- [ ] `EXP-008 P1` Choose an unwritable destination or existing filename; error/
  overwrite behavior is explicit and the app remains usable.
- [ ] `EXP-009 P0` Re-import both export variants as new test projects; verse text,
  structure, references, and aligned occurrence identities match expectations.
- [ ] `EXP-010 P2` Compare the report CSV/TSV and Scripture export destinations;
  recent paths and file types do not bleed into the wrong dialog.

## 14. Accessibility, localization, and visual quality

- [ ] `A11Y-001 P1` Complete primary import → check → review → edit → export using
  only the keyboard; focus is always visible and never trapped.
- [ ] `A11Y-002 P1` Verify logical Tab/Shift+Tab order across Project Home,
  dashboard, editor, modals, menus, Alignment Review, and report.
- [ ] `A11Y-003 P1` Open/close every modal and popup; initial focus is sensible,
  Escape works where expected, and focus returns to the invoker.
- [ ] `A11Y-004 P1` With a screen reader, inspect buttons, icon-only controls,
  inputs, tabs, status/live regions, progress, findings, and charts; names and
  state are meaningful.
- [ ] `A11Y-005 P1` Check error, warning, success, selected, stale, and disabled
  states without relying on color alone.
- [ ] `A11Y-006 P1` Inspect text/background, focus, link, disabled, and chart
  contrast at normal and high-contrast settings.
- [ ] `A11Y-007 P1` Test 100%, 125%, and 150% Windows display scaling; text and
  controls do not clip or overlap.
- [ ] `A11Y-008 P1` Test 1366×768 and a narrow resized window; menus stay in the
  viewport and essential actions remain reachable.
- [ ] `A11Y-009 P2` Test long project names, book names, paths, finding messages,
  evidence, and reviewer notes; wrapping/truncation preserves access to content.
- [ ] `A11Y-010 P1` Inspect Tamil, Odia, Devanagari, Malayalam, Telugu, Bengali,
  Kannada, Gujarati, Gurmukhi, Sinhala, Thai, Khmer, Myanmar, Lao, Arabic,
  Hebrew, Greek, Vietnamese, and decomposed Latin samples; no tofu, detached
  marks, or corrupted graphemes appear.
- [ ] `A11Y-011 P1` Open an RTL target project; reading order, token panes,
  punctuation, selections, diffs, inputs, and mixed LTR metadata are usable.
- [ ] `A11Y-012 P2` Zoom where WebView permits; scrolling and sticky regions do not
  hide active content or focus.
- [ ] `A11Y-013 P1` Verify every icon-only control has a visible tooltip or
  accessible name and no CDN/icon-font dependency renders as an empty box.
- [ ] `A11Y-014 P2` Verify animations/spinners stop at terminal states and do not
  obscure status text.
- [ ] `A11Y-015 P2` Review wording for translator/reviewer clarity: no raw protocol
  names, stack traces, or unexplained stage codes in normal workflows.

## 15. Reliability, recovery, performance, and data safety

- [ ] `ROB-001 P0` Disconnect/reconnect the network during local work; offline
  features continue and only the explicitly invoked AI action fails/retries.
- [ ] `ROB-002 P0` Terminate the engine while a project is open; Bridge reports the
  restart, reconnects the project, and does not display stale state as current.
- [ ] `ROB-003 P0` Force app termination during check/report/AI/alignment work;
  restart yields a coherent resumable/failed state and no duplicate write.
- [ ] `ROB-004 P0` Fill or make the destination unwritable during save/export;
  Bridge reports failure and preserves the last good project/file.
- [ ] `ROB-005 P0` Corrupt a disposable progress/findings cache; recovery is
  explicit and Scripture plus review audit remain intact.
- [ ] `ROB-006 P0` Re-run imports, checks, analyses, reports, retries, and applies;
  idempotent actions do not duplicate projects, findings, notes, links, or writes.
- [ ] `ROB-007 P0` Edit/re-import a tokenized verse; lineage/history remains
  attached through the supported successor/split/merge behavior.
- [ ] `ROB-008 P0` Change upstream text/evidence; dependent derived records become
  stale and no old analysis is presented as current.
- [ ] `ROB-009 P0` Verify latest jobs are authoritative while superseded attempts
  remain available for audit.
- [ ] `ROB-010 P1` Exercise large-book checks and report generation; record elapsed
  time, peak memory, UI response, cancellation latency, and any timeout.
- [ ] `ROB-011 P1` Rapidly navigate while background work runs; interactive
  requests remain responsive and final UI state matches the last action.
- [ ] `ROB-012 P1` Leave Bridge open for an extended session with navigation
  polling; memory/CPU do not grow continuously and connector loops do not occur.
- [ ] `ROB-013 P0` Search app data, project files, exports, and logs after AI use;
  no plaintext API key or unintended provider payload is stored.
- [ ] `ROB-014 P0` Monitor network activity offline and during local workflows; no
  runtime request occurs until a human explicitly invokes an AI feature.
- [ ] `ROB-015 P0` Compare the working project with its untouched backup after the
  suite; only explicitly authorized edits/alignments/corrections and expected
  Bridge metadata differ.

## 16. Final regression and release sign-off

- [ ] `REL-001 P0` All P0 cases pass, or each exception has explicit maintainer
  approval and a linked follow-up issue.
- [ ] `REL-002 P1` All P1 failures/blockers are linked, owned, prioritized, and
  reflected in release notes.
- [ ] `REL-003 P1` Run `npm run check`, `npm run test`, and `npm run build`; record
  exact results rather than assuming documentation-only changes prove the app.
- [ ] `REL-004 P1` Run the complete Python suite plus `cargo check` and `cargo
  test`; record counts and environment.
- [ ] `REL-005 P0` Run frozen-sidecar smoke against the exact packaged workers and
  record any known mismatch separately from new failures.
- [ ] `REL-006 P0` Record installer/app/worker filenames, sizes, versions, hashes,
  signature state, and source commit.
- [ ] `REL-007 P1` Update `QA_TEST_MATRIX.md` only with evidence actually observed
  during this run; do not convert unrun cases to PASS.
- [ ] `REL-008 P0` Tester and release owner review the failures, sign off, and
  retain the completed checklist with the release artifacts.

## Board card template

Use this when creating the QA item in the GitHub project:

- **Title:** `QA: Run full installed-app manual regression`
- **View/tab:** `QA`
- **Type/label:** `area: testing` (and `QA` if that label exists)
- **Status:** `Todo`
- **Priority:** highest while preparing a release
- **Body:** Link to this file, name the candidate build, assign the tester, and
  list any `BLOCKED` dependencies (real AI key, Paratext, Logos, RTL fixture,
  large collection).
- **Done when:** the run record is complete, every P0 is resolved, every remaining
  failure/blocker has a linked issue and owner, release evidence is updated, and
  the completed checklist is attached or committed.
