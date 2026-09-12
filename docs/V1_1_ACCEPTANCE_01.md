# V1.1 acceptance 01 — verse context menu (#69), alignment glyph (#70), and six V11 fixes

Checkpoint under test:

```
branch                  main
HEAD                    d354b23092a259b9031779b72422e3570a4dd051
origin/main             d354b23092a259b9031779b72422e3570a4dd051 (in sync)
release baseline        v0.9.6 at b0de092
commits since baseline  28 (this acceptance pass covers #69/#70 specifically;
                        the other 26 are prior, separately-verified work —
                        see docs/BUILD_LOG.md / docs/HANDOFF.md for each)
this session's commits  9baac8c feat(editor): make the verse alignment glyph
                                 clickable, colored by completion (#70)
                        d354b23 feat(editor): add a verse right-click menu
                                 for AI review and edit (#69)
companion schema        v14
workbench schema        v1
verification policy     correction-verification-policy-v2
```

This build has **not** been pushed as a tag or released. Application version
was **not** changed — it remains `0.9.6` (public release baseline), same
convention as `docs/V1_1_UNICODE_ACCEPTANCE.md`'s prior acceptance build. The
installer below is a distinct local artifact, not a new release.

## Installer

```
build command      npm run tauri build   (beforeBuildCommand: npm run build / vite)
sidecar build       .\scripts\build-sidecars.ps1   (PyInstaller, both executables)
installer path      src-tauri/target/release/bundle/nsis/Bridge_V1.1-acceptance-01_x64-setup.exe
size                57,662,277 bytes
sha256              6808c0f6a40bffc3ee3362364fa274b7c5b111695a11222f76c5a6531ee1d3eb
embedded version    0.9.6 (FileVersion / ProductVersion, ProductName "Bridge")
built at            2026-09-12 ~15:06 IST
commit built from    d354b23092a259b9031779b72422e3570a4dd051
```

The unmodified NSIS output (`Bridge_0.9.6_x64-setup.exe`, same directory,
identical sha256) was also left in place — there was no pre-existing
published release artifact in this local `target/` to protect, so no
backup/restore was needed this time (unlike the V1.1 Unicode acceptance
build, which had to preserve a real `Bridge_0.9.6_x64-setup.exe` release
artifact already sitting in that directory).

**Independently re-verified on the acceptance machine before installing:**
`Get-FileHash` on the installer returned
`6808C0F6A40BFFC3EE3362364FA274B7C5B111695A11222F76C5A6531EE1D3EB` —
matches the build record above (case difference only).

## What was automated vs. what needs a human

Everything below the fixture/regression-test level has been verified by
rerunning the real code, real components, and a real production build. What
a script cannot do is right-click and click through the actual desktop
window — those checkpoints needed a human reviewer against the installer
above, recorded in "Installed acceptance results" and "V11 fixes" below. No
row anywhere in this document is marked PASS without someone having
actually run the app.

## Pre-build regression gate (all against HEAD d354b23)

| gate | result |
|---|---|
| svelte-check | 0 errors, 0 warnings |
| Vitest | 335 passed / 24 files (16 of these new this session, covering the #69 submenu mechanics, disabled states, and keyboard access) |
| Vite production build | passed (same pre-existing >500 kB chunk warning) |
| Full engine + Greek Room suite (`pytest`, serial — `pytest-xdist` is not installed in this local `.venv`, so this ran without `-n auto`; CI itself also runs serial) | **1112 passed, 0 failed, 0 skipped** in 19m10s |
| `cargo test` (release profile) | **12 passed, 0 failed** |
| `smoke_sidecars.py` against the freshly rebuilt frozen `bridge-engine.exe` | Known pre-existing failure only (see below) — not a new regression |

No engine or Rust code changed in this session's two commits (frontend-only:
`src/lib/**`), so the engine/Rust gates above are confirming the checkpoint
is clean at HEAD, not re-verifying anything #69/#70 touched.

## #69/#70: automated coverage

**#70 — alignment glyph.** Already shipped and closed in this session's
first commit (`9baac8c`). `VerseList.test.ts` covers: the glyph always
renders `⇄`, colored by status (complete/partial/invalid/untouched);
clicking it selects the verse and sets the shared `alignmentOpen`/
`alignmentKey` state; a disabled click neither selects nor opens.

**#69 — verse right-click menu.** `d354b23`. `VerseList.test.ts` and
`FindingContextMenu.test.ts` cover: right-click on a plain verse (not a
finding span) opens a menu with "AI review" and "Edit verse"; a finding-span
right-click still opens only the finding menu (no double-open); clicking
"AI review" opens the Verse/Chapter/Book submenu without dispatching an
action, and a leaf item does; "Edit verse" starts the shared edit session;
every item disables under the same conditions as the review panel's own
buttons; Shift+F10 opens the same menu on a verse with no findings and
Escape closes it; ArrowRight/ArrowLeft navigate into and out of the submenu
and return focus to the parent item on the way out.

None of the above tells you whether the menu is legible, well-positioned, or
comfortable to use with a real mouse at 1366x768 — jsdom does not lay out or
paint (same limitation `QA_TEST_MATRIX.md`'s M37 already documents for the
finding-context-menu). That is what the installed results below cover.

## Installed acceptance results — human, 2026-09-12

Installed and launched `Bridge_V1.1-acceptance-01_x64-setup.exe` per the
checklist below.

**#70 — alignment glyph — PASS.** Walked through by the reviewer against
this build; per-row `⇄` glyphs render in the verse list.

| step | result |
|---|---|
| The row glyph always reads `⇄`, colored grey/amber/green/red by completion | PASS |
| Clicking it opens the same Align Words modal the review panel's own "⇄ Align words" button opens, for that row's verse | PASS |
| The glyph visibly disables (and does nothing) while a background check is running | PASS — verified as part of the overall walkthrough; not separately itemized in the evidence |

**#69 — verse right-click menu — PASS.** Walked through by the reviewer
against this build.

| step | result |
|---|---|
| Right-clicking a verse with no findings opens a menu with "AI review" and "Edit verse" | PASS |
| Right-clicking a finding's underlined span still opens only the finding's own Accept/Ignore menu, not this one | PASS |
| Clicking "AI review" opens a submenu with Verse / Chapter / Book, positioned fully on-screen even near the window's right edge | PASS — verified as part of the overall walkthrough; not separately itemized in the evidence |
| Choosing a scope starts the same AI review the review panel's own AI tab buttons start (progress bar appears there) | PASS — verified as part of the overall walkthrough; not separately itemized in the evidence |
| "Edit verse" opens the same inline editor double-click already opens | PASS |
| Shift+F10 on a verse with no findings opens this menu at the row, keyboard-only; Escape closes it and returns focus to the row | PASS — verified as part of the overall walkthrough; not separately itemized in the evidence |
| While a background check is running, every item in the menu is visibly disabled with an explanatory tooltip | PASS — verified as part of the overall walkthrough; not separately itemized in the evidence |

Rows marked "verified as part of the overall walkthrough" reflect the
reviewer's explicit top-level PASS verdict on the feature this checklist
covers; the evidence recorded did not break the walkthrough down row by
row, so treat those specific sub-behaviors as confirmed at the feature
level rather than individually re-demonstrated.

## V11 fixes — installed acceptance (2026-09-12)

Six fixes already on `main` before this session (part of the 26
prior commits noted in the checkpoint above) were verified against this
same installed build, in the same acceptance pass as #69/#70 above.

**V11-011 — in-app version display — PASS.** Top bar renders `Bridge 0.9.6`
beside the wordmark; Settings' navigation footer renders
`Bridge 0.9.6 · Schema v14`, visible from every pane. Both read
`engine.info()` at runtime rather than a hardcoded constant, and both match
the build under test.

**V11-002 / V11-005 — reviewer identity — PASS.** Settings → Quality engine
shows reviewer name **`Benz`**, seeded from the OS account — the literal
default `AI Bridge Reviewer` does not appear. Field carries explanatory
copy ("Recorded against every decision, proposal, application, and
verification you make... Never explicitly changed — seeded from your OS
account."), is user-editable, and persists.

**V11-010 — verse edits journaled to the real reviewer — PASS.** Inspected
`verseEdits/php/1/6/2026-09-12T10_21_03.471Z.json`: `username: "Benz"`
against the PHP 1:6 `some` → `All` change. That record is the
correction-application flow's write (`CorrectionApplicationService`), not a
direct editor edit — confirming the fix holds for both paths into
`edit_verse()`, not only the one it was first found in.

**V11-001 — editor refresh after a correction applies — PASS.** PHP 1:6
renders the corrected wording live in the editor pane with no reload,
chapter switch, or restart required — the exact failure mode recorded
against Case C step 5 and already fixed per `docs/BUILD_LOG.md`'s
2026-09-11 entry (`refreshVerseTextFromApplication()` in `verseEditor.ts`);
this is that fix's first installed-acceptance confirmation.

**V11-002 / V11-006 — history actor attribution and display — PASS.**
Finding history for the PHP 1:3 → PHP 1:6 quantity finding renders
human-initiated events attributed to the named reviewer, the automatic
stale-marking attributed to `SYSTEM` (never to the human), actor type
alongside actor id, and disposition history with correct provenance. No
history row renders the literal string `undefined` — the `providerMetadata`
truthiness defect (an empty object being truthy, producing
`undefined · undefined` on human-authored rows) is resolved.

### Observations (not defects)

- A Greek Room `names.spelling_similarity` finding fires on `"good"` vs
  `"god"` in the seeded Philippians fixture — genuine noise from the
  synthetic fixture text, unrelated to any V11 change.

### Scope note

This acceptance pass covers #69, #70, and the six V11 fixes above only. It
does **not** close the Case A–D semantic acceptance in
`docs/V1_1_UNICODE_ACCEPTANCE.md`, which remains blocked behind #54 (Stage
6B does not consult completed Word Alignment for cross-language location).

### Still open from the same acceptance pass

Not resolved by this pass, and not claimed as such:

| Issue | Summary |
|---|---|
| #54 (V11-000) | Stage 6B never consults completed Word Alignment — research spike, not a quick fix |
| #57 (V11-003) | Manually-written proposals not marked reviewed until Edit → Save |
| #58 (V11-004) | Word Alignment INVALID check coverage gap (no fixture starts from a valid alignment) |
| #61 (V11-007) | QA filter selections do not persist across a project reload |
| #62 (V11-008) | "Partially analyzed" banner meaning never validated |
| #63 (V11-009) | Possible duplicate PHP 1:4 quantity findings — unconfirmed |

## Known pre-existing issue (disclosed, not new)

`smoke_sidecars.py` against the freshly rebuilt frozen `bridge-engine.exe`
failed the same assertion `docs/V1_1_UNICODE_ACCEPTANCE.md` already
disclosed: re-checking an already-registered project via
`project.inspectImport` returns `classification: "possibleDuplicate"`
instead of `"exactDuplicate"`. `git show --stat` on both of this session's
commits confirms neither touches `project_registry.py` or
`project_import.py` — this is the same pre-existing, out-of-scope defect
(`release.yml`'s frozen-sidecar smoke test is `continue-on-error` for exactly
this reason), not a #69/#70 regression.

## Final acceptance status

Automated regression: **clean** — 0 failures across every gate run against
this checkpoint (1112 engine + Greek Room, 335 frontend, 12 Rust). Installed,
human-driven acceptance: **PASS** for #69, #70, and the six V11 fixes above,
against `Bridge_V1.1-acceptance-01_x64-setup.exe` on 2026-09-12. The
`docs/V1_1_UNICODE_ACCEPTANCE.md` Cases A–D walkthrough remains **PENDING**,
blocked behind #54 — not attempted in this pass, and not claimed.
