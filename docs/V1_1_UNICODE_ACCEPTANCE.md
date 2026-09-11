# V1.1 Unicode/grapheme-safe comparison — installed acceptance

Checkpoint under test:

```
branch                  main
HEAD                    1ac110b0db88d66a8359c4271c9adf445ce93ff7
origin/main             b0de0929c073d4f699d3fd1122715752ded770e0 (ahead 4, behind 0)
release baseline        v0.9.6 at b0de092
V1.1 commits            5cc3ce7 fix(semantic): make Unicode comparison grapheme-safe
                        ef49e9e test(semantic): cover world-script normalization
                        4444ea7 docs(handoff): record V1.1 Unicode stabilization
history consolidation   1ac110b docs(history): consolidate project roadmap and handoff
companion schema        v14
verification policy     correction-verification-policy-v2
```

This build has **not** been pushed, tagged, or released. Application version
was **not** changed — it remains `0.9.6` (public release baseline). The
acceptance installer below is a distinct local artifact, not a new release.

## Installer

```
build command      npm run tauri build   (beforeBuildCommand: npm run build / vite)
sidecar build       .\scripts\build-sidecars.ps1   (PyInstaller, both executables)
installer path      src-tauri/target/release/bundle/nsis/Bridge_V1.1-prerelease_x64-setup.exe
size                57,763,124 bytes
sha256              c961c640c60ba73485da2f4c840829b3da74266982bbe2a05a7acef30112b52c
embedded version    0.9.6 (FileVersion / ProductVersion, ProductName "Bridge")
built at            2026-09-10 18:09:52 +0530
commit built from    1ac110b0db88d66a8359c4271c9adf445ce93ff7
```

The published release artifact (`Bridge_0.9.6_x64-setup.exe`, sha256
`c7328d6c0bd48c570b0a24391630744d6f0449cf7fe6217ecf4f6ef0bc7d0c3d`, built
2026-09-09 from the `b0de092` release commit — before V1.1 existed) sits in
the same `nsis/` output directory, untouched. It was backed up before this
build ran (the NSIS bundler always writes `Bridge_0.9.6_x64-setup.exe`
because the app version is unchanged) and restored byte-for-byte afterward;
both files' hashes were verified before and after. Do not confuse the two —
the acceptance build carries a different filename specifically so it can't
be mistaken for the release.

## What was automated vs. what needs a human

Everything below the fixture/regression-test level (application logic
compiled into this installer) has been verified by rerunning the code
against real, non-mocked script data. What a script cannot do is click
through the actual desktop window — those checkpoints are left **PENDING**
for a human reviewer against the installer above, with exact steps given.
Do not mark a PENDING row PASS/FAIL without actually running the app.

## Pre-build regression gate (all against HEAD 1ac110b)

| gate | result |
|---|---|
| Focused Unicode/Stage7/Stage8/all Stage9B sub-stages/Case C/cache-contract (13 files) | **409 passed, 0 failed** |
| Full engine + Greek Room suite (`tests/` + `greek_room_engine/tests/`) | **1063 passed, 1 skipped, 0 failed** (skip is an environment-dependent vendored Smart Edit Distance guard in `test_alignment_statistics.py`, unrelated to Stage 7/8/9B4 or Unicode comparison — not independently re-confirmed to avoid a redundant ~48-minute rerun) |
| svelte-check | 0 errors, 0 warnings |
| Vitest | 310 passed / 24 files |
| Vite production build | passed (same pre-existing >500 kB chunk warning) |
| cargo check / cargo test | passed (12/12 Rust tests) |
| `git diff --check` (`b0de092..HEAD`) | clean |

No code changed between the last full verification pass and this checkpoint
except the `1ac110b` docs-only commit, so these numbers are current for HEAD.

## Case A — Tamil known regression

**Automated (unit level):** `test_unicode_semantic_comparison_v11.py::test_world_script_marks_survive_comparison_token_construction["Tamil"]`
confirms `இல்லை` survives `comparison_normalize` unchanged (previously
fragmented to `இல ல` by the pre-V1.1 comparator). Confirmed passing above.

**Automated (integration level):** the Stage 9B.4 acceptance fixtures
(`A-passed-controlled`, `B-failed-controlled`, seeded fresh under this
checkpoint via `scripts/seed_correction_acceptance.py`) apply a real Tamil
correction — target text `என் தேவனை` → `என் தேவனையே`, both containing
Tamil vowel-sign/virama combining marks — through the actual application
pipeline. Read-only inspection (`scripts/inspect_correction_application.py`)
confirms: `application_state: COMPLETED`, the edit landed byte-for-byte as
intended, `wordAlignment.wordAlignmentState: INVALID` (correctly
invalidated), `verificationStatus: PENDING` (not yet run — correct
pre-Verify state).

**PENDING — human, installed build:**

1. Open `Bridge_V1.1-prerelease_x64-setup.exe`, install, launch.
2. Open a project containing a verse pair with source Greek `οὐ` and target
   Tamil `இல்லை` (or open the seeded `A-passed-controlled` /
   `B-failed-controlled` projects at
   `%TEMP%\...\v11-acceptance-0.9.6\` and re-run from
   `docs/STAGE_9B4_ACCEPTANCE.md` Cases A/B).
3. Record: source reference, target reference, displayed source text,
   displayed target text exactly as rendered, Stage 7 result, Stage 8
   result.
4. Confirm Stage 7 reports `POLARITY = PRESERVED` and Stage 8 does **not**
   emit `NEGATION_PROBLEM` solely from the combining marks.

| step | result |
|---|---|
| Stage 7 POLARITY | PENDING |
| Stage 8 NEGATION_PROBLEM absent | PENDING |

## Case B — canonical Unicode equivalence (NFC/NFD)

**Automated:** `test_unicode_semantic_comparison_v11.py::test_canonically_equivalent_nfc_and_nfd_have_one_comparison_key`
proves NFC and NFD input for `café`, `Việt`, `Ἰησοῦς`, Hebrew, Tamil, and
Devanagari all normalize to the identical comparison key. Confirmed passing
above.

**Scripture-safety, verified by design and by observation:**
`unicode_comparison.py`'s functions are pure (return new strings, mutate
nothing) and its module docstring states the contract explicitly: "creates
transient comparison keys only... never mutates or persists Scripture
text." The Stage 9B.4 fixture inspection above additionally confirms
Scripture only changes via an explicit, human-approved correction
(`canonicalEdit.oldText`/`newText`), never as a side effect of comparison.

**PENDING — human, installed build:**

1. Import or open a project containing `café` or `Việt` in NFD form (a
   text editor can write either form explicitly).
2. Record raw text before analysis, run any check, record raw text after —
   confirm byte/text identical.
3. Confirm the semantic comparison result is unaffected by which
   normalization form was imported.

| step | result |
|---|---|
| Scripture byte-identical before/after analysis | PENDING |
| Semantic result identical regardless of NFC/NFD import | PENDING |

## Case C — Stage 9B.4 correction-loop regression

Reused the existing Stage 9B.4 acceptance fixture/procedure
(`docs/STAGE_9B4_ACCEPTANCE.md`, `scripts/seed_correction_acceptance.py`,
`scripts/inspect_correction_application.py`) rather than duplicating it,
per instructions — this is a real regression check of the same production
flow the fix must not break, not a new spec.

**Automated:** seeded fresh under this checkpoint (see
`v11-acceptance-0.9.6/acceptance-manifest.json`):

- Case C (`C-uncertain-production`) ran the real Stage 5→6A→6B→7→8 pipeline
  and reproduced the expected cross-verse `QUANTITY_PROBLEM` at source
  `PHP 1:3` / target `PHP 1:6` (28 total findings) — matching the documented
  production shape.
- Case A/B controlled fixtures applied their Tamil corrections cleanly (see
  Case A above) and left `verificationStatus: PENDING`,
  `correctedAcknowledgement: false` — correct pre-Verify state.

**PENDING — human, installed build:** run the full click-by-click procedure
in `docs/STAGE_9B4_ACCEPTANCE.md` (Verify correction on A/B, confirm
PASSED/FAILED, restart persistence, Case C's confirm→correct→apply→
re-analyze→verify→UNCERTAIN flow) against the seeded projects under the new
comparator. What must still hold, unchanged from that document:

| checkpoint | result |
|---|---|
| Case A reaches PASSED, disposition stays CONFIRMED_TRANSLATION_ERROR until explicit acknowledgement | PENDING |
| Case B reaches FAILED with positive contradiction evidence | PENDING |
| Case C reaches UNCERTAIN with `PROVIDER_LIMITED`, not FAILED, and `POSSIBLY_MISSING` never becomes FAILED | PENDING |
| Word Alignment never auto-approved/rebuilt by verification | PENDING |
| Restart persistence (close/reopen Bridge) holds for all three | PENDING |

## Case D — Greek/Hebrew source safety

**Automated:** `test_original_language_resources.py` (9 tests) and
`test_source_semantic_inventory_stage5.py` (16 tests) — all 25 passed,
confirmed above. Notably `test_uhb_genesis_1_1_matches_translationcore_golden_tokens`
exercises real UHB Hebrew text carrying points and cantillation marks
(`בְּ⁠רֵאשִׁ֖ית`) — exactly the character class the pre-V1.1 comparator
could corrupt — and `test_ugnt_titus_1_1_preserves_repeated_word_occurrences`
covers real UGNT Greek. `test_all_66_bundled_book_packs_pass_hash_and_metadata_validation`
confirms no resource-integrity regression across the full bundled
Hebrew/Greek/Aramaic canon.

**PENDING — human, installed build:** open a project with real UHB/UGNT
source (e.g. the Titus fixture from `scripts/smoke_sidecars.py`, or any real
project) and confirm source analysis completes without a resource
validation failure or visibly corrupted source token.

| step | result |
|---|---|
| UHB/UGNT passage analyzes without resource-validation failure | PENDING |
| No source-token corruption visible in the reviewer UI | PENDING |

## Unrelated finding (out of scope, disclosed for transparency)

`scripts/smoke_sidecars.py` run against the freshly rebuilt frozen
`bridge-engine.exe` failed one assertion: re-checking an already-registered
project via `project.inspectImport` returned `classification:
"possibleDuplicate"` instead of the expected `"exactDuplicate"`. Confirmed
via `git show --stat` that none of the three V1.1 commits (or the docs
commit) touch `project_registry.py` or `project_import.py` — this is not a
V1.1 regression. It also isn't one of this task's defined stop conditions.
Likely cause: the project registry resolves to a fixed path under the real
`%LOCALAPPDATA%\Bridge\data\project-registry.json` rather than the
smoke test's per-run override, so repeated local runs accumulate entries
across sessions. Not investigated further — out of scope for this
acceptance pass; flagged here rather than silently dropped.

## Scripture-safety checklist (all cases)

- [x] Comparison normalization never rewrites authoritative Scripture on
      disk — verified by code (pure functions, documented contract) and by
      the Stage 9B.4 fixture audit trail (edits only via explicit human
      correction).
- [x] Persisted spans remain Unicode code-point offsets — unchanged by
      V1.1; `unicode_comparison.py` produces transient comparison text only,
      never a persisted coordinate.
- [x] No normalized text used as a correction coordinate — the correction
      application path (`correction_verification.py`) keys off exact
      target reference/span/hash, not comparison output.
- [x] No fuzzy correction matching introduced.
- [x] Existing project authority rules intact — nothing in V1.1 touches
      `tc_project.py` or the transaction journal.

## Final acceptance status

Automated regression: **clean** (0 failures across every gate run against
this checkpoint). Installed, human-driven acceptance (Cases A–D's PENDING
rows above): **not yet performed** — left for the reviewer, per instructions
not to self-mark PASS on anything that requires the actual packaged UI.
