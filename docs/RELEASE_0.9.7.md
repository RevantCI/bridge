# Bridge 0.9.7

Bridge 0.9.7 lets Stage 6B's location engine consult completed
translationCore Word Alignment as location evidence, closes three defects
a follow-up review found in that change before it ever reached a release,
and removes a pointless Edit→Save round-trip before a manually written
correction proposal can be applied.

Companion storage moves from schema v14 to **v15** (additive; a v14
database opens and migrates automatically, and every pre-existing record
reads back unchanged). Correction verification remains
`correction-verification-policy-v2`.

## Highlights

- Stage 6B now scores a `WORD_ALIGNMENT` evidence component from any
  same-verse translationCore alignment group already marked completed,
  at the same weight (0.65) the existing `HUMAN_PRECEDENT` component
  uses — a source verse a translator has already aligned to its target
  now helps Stage 6B locate a QA finding correctly, rather than that
  alignment work going unused by location search. Cross-verse alignment
  and any embedding-provider direction remain future work under #54.
- Fixed a casefolding bug that could silently drop this new evidence for
  any target text containing a cased word pair (most scripts with
  separate upper/lower case) — word/occurrence identity now compares
  exact NFC text, never casefolded, matching how occurrences are counted
  everywhere else in Bridge.
- The new alignment-evidence dependency edge is now written in the same
  transaction as the location run it protects, closing a crash window
  that could otherwise leave a run permanently immune to invalidation.
- A verse-bridge alignment group (e.g. one spanning "PHP 1:2–3") is now
  actually excluded from this evidence, matching what was already
  documented — previously nothing enforced it.
- Alignment state changes made through a scripture edit, a correction
  application, or completing an alignment now all correctly refresh the
  memo Stage 6B's invalidation check compares against — previously two of
  those three paths could leave a just-published, still-correct location
  run spuriously marked stale on the next time the project is opened.
- A manually written correction proposal is now usable immediately —
  "Review application" no longer requires an Edit→Save round-trip first.
  That round-trip was already unchecked self-review with no distinct
  reviewer required, so this removes a step that added no real review,
  not a safety control. Existing proposals stuck in this state are
  repaired automatically, in place, the next time they're opened.

## Safety properties retained

- No Scripture is changed without explicit human Apply confirmation.
- A wrong or unresolved Word Alignment match never becomes location
  evidence — anything but exactly one clean match on both the source and
  target side is dropped entirely rather than guessed at, costing that
  one alignment group's contribution, never a whole search.
- Nothing in this release ever writes to translationCore's own alignment
  data or completion markers; Bridge only reads them.
- Every automatic reseed of a stuck correction proposal's review status
  is attributed to a `MIGRATION` actor, never the named human reviewer,
  and is fully audited as its own event.
- The optimistic-concurrency `revision` a reviewer's session has cached
  is never invalidated behind their back by an automatic reseed.
- No weight, threshold, or scoring formula changed for any existing
  evidence component; the Stage 6B golden fixture is byte-identical.

## Verification

```text
full engine + Greek Room pytest             1149 passed, 1 skipped (serial, 16:58)
frontend Vitest                             336 passed / 24 files
svelte-check                                0 errors / 0 warnings
cargo check / cargo test                    passed / 12 passed
npm run build (production)                  passed
git diff --check                            passed
Installed acceptance (Cases A-D)            PENDING — to be run by the maintainer against
                                             this release's published installer; see
                                             docs/ACCEPTANCE_TEST_GUIDE.md Step 5 and
                                             docs/archive/V1_1_UNICODE_ACCEPTANCE.md for the
                                             procedure and results table.
```

An initial parallel (`pytest -n auto`) run surfaced 4 failures and 2 flaky
`cargo test` failures, all in background-job/process-timing tests running
under heavy concurrent CPU load (the parallel test workers and a
simultaneous `cargo test` compile). Re-run serially and in isolation, both
suites are fully clean (see numbers above) — logged here rather than
silently discarded, since a flake explained is worth more than a flake
forgotten.

## Known limitations

- Cross-verse Word Alignment evidence and any embedding-provider-backed
  location matching remain future work (#54 follow-on).
- The author-≠-reviewer distinction for correction proposals is
  deliberately not built yet; a human-authored proposal is approved by
  its own author today, same as before this release, just without the
  Edit→Save ceremony. A dedicated reviewer field is planned for the
  #74–#81 team-workflow milestone.
- The Windows installer is unsigned and may show a SmartScreen warning.
- Windows x64 is the verified target; macOS and Linux remain unverified.
- Installed acceptance Cases A–D (Tamil negation, NFC/NFD equivalence,
  the Stage 9B.4 correction loop, and Greek/Hebrew source safety) were not
  run before this release was published — see `## Verification` above.

## Windows installer

`Bridge_0.9.7_x64-setup.exe` — the release asset attached by
`.github/workflows/release.yml`'s own CI build (run
[34806217730](https://github.com/RevantCI/bridge/actions/runs/34806217730),
concluded `success`), not the local build below — 59,872,723 bytes
(~57.1 MiB).

SHA-256 (CI-built, the actual release asset):
`CDB662CF6211988AC6637D6FE34FFBF06C1037959CAA6CA122EBB389A331D78F`

A separate local build made for this gate run (same source, same
`0.9.7` version, different machine/timestamp — installer builds aren't
byte-reproducible here) is 57,685,729 bytes with SHA-256
`77B5806DBE5619AB7F1F5A0351364AF57B0B4859D3A5E797E3AB420590550E47`,
kept only as this session's own verification copy, not shipped.

`scripts/smoke_sidecars.py` against the frozen pair (both the local and
CI builds): fails on the same known, pre-existing `project.inspectImport`
duplicate-classification mismatch documented in `CLAUDE.md`
(continue-on-error in CI for this exact reason) — unrelated to anything
this release changed, not a new regression. Everything else the smoke
check exercises passed, and CI's own `Frontend checks` / `Rust tests`
steps (svelte-check, Vitest, `cargo test`) all passed independently of
this session's local gate run.
