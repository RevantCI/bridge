# Bridge 0.9.4

Bridge 0.9.4 advances the human correction and semantic-verification workflow,
repairs end-to-end affected re-analysis, and adds a script-aware multilingual
font stack. Companion storage remains schema v14.

## Highlights

- Adds Stage 9B.4 positive semantic verification and a separate, explicit
  human acknowledgement before a finding can become `CORRECTED`.
- Preserves source and target provenance independently for cross-verse
  correction and verification.
- Repairs correction review candidate-span loading by retaining semantic
  location run identity.
- Allows safe re-seeding of identical content-addressed coverage accounts
  during affected re-analysis while preserving mutable human review state.
- Separates meaning-failure evidence from resource disagreement so eligible
  confirmed translation issues can enter the correction workflow.
- Adds controlled PASSED/FAILED acceptance fixtures, a real production
  UNCERTAIN fixture, and a read-only correction-application inspector.
- Bundles and applies fonts for Tamil and other Indic scripts, Hebrew,
  polytonic Greek, and Urdu, with script-aware source and Scripture styling.

## Verification

```text
full Python + Greek Room       1014 passed, 0 failed
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

## Windows installer

`Bridge_0.9.4_x64-setup.exe`

SHA-256:
`6F3960A6AEB6BF03568267A9E421EB9B62C09EF893364126E56905A32D763951`
