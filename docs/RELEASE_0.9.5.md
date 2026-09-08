# Bridge 0.9.5

Bridge 0.9.5 is a maintenance release on top of 0.9.4. It repairs the Stage
9B.4 acceptance fixtures so the seeded A/B cases are actually visible in the
Alignment Review QA queue, and adds a regression test that reads the real
queue API instead of the database. Companion storage remains schema v14.

**No product frontend, backend, or Rust behavior changed since 0.9.4.** The
only functional change is in test and acceptance-fixture code; the version
bump and a rebuilt installer are provided so testers can pin the fixture fix
to a numbered build.

## Highlights

- Seeds the Stage 9B.4 A/B acceptance fixtures through
  `repository.save_qa_finding()`, the same canonical path Stage 8's
  `QaAuditEngine` uses, instead of a minimal insert plus hand-patched SQL.
  One atomic write now maintains `payload_json`, every denormalized Stage 9A
  queue column, and the scope-reference rows together.
- Fixes the resulting queue blindness: with no `qa_finding_scope_references`
  rows and an empty `book` column, `query_qa_findings()` could never match a
  real UI scope, so case A showed `Showing 0 of 0 possible issues` even
  though the finding was present and correct in the payload.
- Takes fixture severity from `QaAuditPolicy.severity_for()` rather than a
  literal, so the fixture cannot drift from the product's own severity policy.
- Adds `engine/tests/test_correction_acceptance_queue_visibility.py`: it
  seeds A and B with the real seeder into a fresh folder, opens them through
  `BridgeEngine`/`project.open`, and asserts against the actual
  `qaReview.getQueue` API (never SQLite) at the acceptance scope
  PHP 1:3–PHP 1:6, plus a third test that checks the denormalized columns and
  scope rows directly so a payload-only regression cannot pass.

## What did not change

- Fixture identity is unchanged: `finding-1`, `CONFIRMED_TRANSLATION_ERROR`,
  `HUMAN_APPROVED`, `STALE` after apply, PHP 1:3 → PHP 1:6, revision 1 at
  creation, so every existing `expected_finding_revision=1` caller still holds.
- `query_qa_findings()` is unchanged, nothing special-cases `finding-1`, and
  the UI does not bypass the queue.
- Stage 9B.4 verification semantics, proposal/application/affected-analysis
  state, and the correction workflow are untouched.
- The `NOT_ANALYZED` sentence in `AlignmentQaMode.svelte` was a consequence of
  the empty queue, not a cause; no frontend repair was needed.

## Verification

```text
full Python + Greek Room       1024 passed, 0 failed
frontend Vitest                 307 passed / 24 files
npm run check                   0 errors / 0 warnings
npm run build                   passed
cargo check                     passed
cargo test                      12 passed
git diff --check                passed
```

## Important behavior

- Verification never changes Scripture.
- A `PASSED` verification does not silently mark a finding `CORRECTED`; the
  reviewer must explicitly acknowledge the correction.
- Semantic verification does not approve or rebuild translationCore Word
  Alignment. An edited verse remains invalid/reviewable until aligned normally.
- Historical findings, human decisions, applications, analysis jobs, and
  verification records remain persisted.

## Known limitations

Carried forward unchanged from 0.9.4:

- Real cross-language positive verification requires evidence strong enough to
  relocate the corrected source obligation. Without a configured production
  multilingual embedding provider or persisted human-approved lexical
  precedent, Bridge correctly abstains with `UNCERTAIN` and
  `PROVIDER_LIMITED` rather than claiming `PASSED`.
- Tamil Stage 7 normalization, broader REFERENT/PARTICIPANT/TEMPORAL coverage,
  correction-history timestamp ordering, and richer cross-verse visualization
  remain stabilization work.
- The existing frozen-sidecar smoke test still stops at a pre-existing import
  duplicate-classification mismatch.
- The Windows installer is unsigned and may show a SmartScreen warning.
- Windows x64 is the verified target; macOS and Linux remain unverified.
- Installed Stage 9B.4 A/B/C acceptance (`docs/STAGE_9B4_ACCEPTANCE.md`) has
  still not been run end to end by a tester.

## Windows installer

`Bridge_0.9.5_x64-setup.exe`

SHA-256:
`58ABC03FAF19D6880F093A9AA7A722F94302FDBCB0B89339B6B335CEF4008F0C`
