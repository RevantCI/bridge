# Bridge 0.9.6

Bridge 0.9.6 is a focused Stage 9B.4 reliability release. It repairs the real
Case C affected-analysis failure discovered after a human-applied cross-verse
correction and fixes stale verification text after a terminal affected-analysis
job.

Companion storage remains schema v14 and correction verification remains
`correction-verification-policy-v2`.

## Highlights

- Keeps rebuilt Stage 5 source inventories internally consistent when bundled
  tN/tW/TWL resource revisions change. Stable semantic fingerprints remain
  meaning-only, while immutable persisted unit identities now bind the exact
  evidence revision and audit-owner identity they contain.
- Preserves the strict invariant that every source semantic unit may reference
  only evidence included in its published source inventory. The validator was
  not weakened or bypassed.
- Adds a genuine production regression covering Stage 5 -> 6A -> 6B -> 7 -> 8,
  a natural PHP 1:3 -> PHP 1:6 cross-verse quantity finding, human confirmation,
  human-authored correction, application, and affected re-analysis.
- Refreshes backend-owned correction verification after every terminal
  affected-analysis transition, including `FAILED`, `CANCELLED`, and
  `COMPLETED_WITH_WARNINGS`.
- Retains historical failed/retried analysis attempts while keeping the latest
  associated job authoritative.

## Safety properties retained

- No Scripture is changed without explicit human Apply confirmation.
- Source semantic provenance and editable target references remain distinct.
- PHP 1:3 remains untouched when the target correction is applied at PHP 1:6.
- Word Alignment for an edited verse remains invalid/reviewable.
- A completed analysis never silently means human approval or a verified
  correction.
- `UNCERTAIN`/`PROVIDER_LIMITED` remains the correct no-provider outcome for
  real cross-language Case C; verification verdict policy is unchanged.
- No Tamil-, PHP-, quantity-, or fixture-specific runtime rule was added.

## Verification

```text
focused Stage 5/foundation/invalidation/Stage 9B.3a-9B.4/real Case C  159 passed
full Python + Greek Room                                                1026 passed
frontend Vitest                                                         310 passed / 24 files
CorrectionReviewPanel Vitest                                             54 passed
npm run check                                                             0 errors / 0 warnings
npm run build                                                             passed
cargo check                                                               passed
cargo test                                                                12 passed
Tauri/NSIS release build                                                  passed
git diff --check                                                          passed
```

## Known limitations

- Real cross-language positive verification still requires evidence strong
  enough to relocate the corrected source obligation. Without a configured
  production multilingual provider or persisted human-approved lexical
  precedent, Bridge correctly abstains with `UNCERTAIN` and
  `PROVIDER_LIMITED`.
- The frozen-sidecar smoke test passes the 0.9.6 version handshake but still
  stops at the previously documented synthetic duplicate-project
  classification mismatch.
- The Windows installer is unsigned and may show a SmartScreen warning.
- Windows x64 is the verified target; macOS and Linux remain unverified.
- Installed Cases A and B passed. The repaired real Case C has a production
  automated regression and a fresh manual acceptance package, but its final
  installed click-through remains the next operational check.

## Windows installer

`Bridge_0.9.6_x64-setup.exe`

SHA-256:
`C7328D6C0BD48C570B0A24391630744D6F0449CF7FE6217ECF4F6EF0BC7D0C3D`
