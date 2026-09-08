# Bridge — Indic & Source-Script Font Support

**Repository path:** `docs/plans/FONT_SUPPORT_PLAN.md`
**Status:** Implemented 2026-09-08. This document is kept as the design
rationale; where it and the shipped code disagree, the code is right and
`docs/BUILD_LOG.md` ("Indic and source-script font support") records why —
notably that the Noto families are published only as variable fonts, that
there is no "Noto Serif Greek" family (Gentium Plus took its place), and
that Ezra SIL has no bold cut.
**Target application:** Bridge — Scripture Translation Quality Workbench
**Baseline:** v0.9.2 (`package.json`, `src-tauri/tauri.conf.json`)
**Scope:** Correct glyph rendering for Tamil and the other Indian gateway languages, plus Hebrew/Greek source text.

---

## 1. Goal

Bridge currently sets one global font stack in `src/index.css:43`:

```css
body { margin: 0; font-family: -apple-system, "Inter", Segoe UI, Helvetica, Arial, sans-serif; }
```

None of those faces cover Tamil, Devanagari, Bengali, Telugu, Kannada, Malayalam, Gujarati, Gurmukhi, Odia, or Urdu. Target-language scripture therefore renders through whatever the WebView2 default fallback happens to be, which varies by machine and gives Tamil reviewers a face they did not choose. On a machine with no Indic font installed at all, it renders as tofu.

After this change:

- **Tamil** renders in Vijaya where available, Nirmala UI as second choice, bundled Noto Serif Tamil as the guaranteed floor.
- **Every other Indian gateway language** renders in its bundled Noto Serif face.
- **Hebrew and Greek source text** renders in a face that handles pointing, cantillation, and polytonic diacritics correctly.
- No network access is required at any point, at build time or runtime.

---

## 2. Design decision: fallback-by-coverage, not language detection

The obvious implementation is to read `ProjectInfo.targetLanguageId` (ISO 639-3, e.g. `"tam"` — see `src/lib/types/finding.ts:471`), map it to a script, and set a font stack accordingly. **Do not do this.** It is more code, and it is worse.

CSS font fallback already resolves per-glyph by coverage. If the stack lists every bundled Indic face, the browser walks it for each character and picks the first font that actually has that glyph. Latin UI chrome hits Inter and stops. A Tamil character passes over Inter (no coverage) and lands on Vijaya. A Devanagari character passes over Inter *and* Vijaya and lands on Noto Serif Devanagari. The scripts do not overlap, so there is no ambiguity to resolve.

This gives three things for free:

- **Zero component churn.** Target text is rendered in at least eight components (`AlignmentModal`, `CorrectionReviewPanel`, `EvidenceInspector`, `FindingContextMenu`, `ProjectReportScreen`, `SemanticAlignmentMode`, `TopBar`, `VerseNotesPopup`, plus `VerseList`). None of them need to be told what language they are showing.
- **Mixed-script strings work.** A finding message like `Missing word "அருள்" in verse 3` renders the Latin in Inter and the Tamil in Vijaya, in one text node, correctly.
- **New gateway languages need no code change.** Adding a Devanagari language later is a data change, not a code change.

The webview lazy-loads font files only when a glyph actually needs one, so declaring ten `@font-face` families costs nothing at runtime on a Tamil-only project. Only the faces actually exercised get read off disk.

A second, narrower layer handles what fallback cannot: per-script `line-height`. That is done with an explicit `--font-target` variable on the small number of scripture panes, covered in §6.

---

## 3. Licensing — read before bundling anything

**Vijaya and Nirmala UI must not be bundled.** Both are Microsoft fonts that ship with Windows. Microsoft licenses them for use on licensed Windows installations but grants no redistribution right. Placing either TTF in the repo or in the installer is a licence violation. They are named in the CSS stack only, which resolves installed system fonts by family name in WebView2 and requires no permission.

This is fine in practice: Bridge's build target is `x86_64-pc-windows-msvc`, so Vijaya is present on essentially every real user's machine. The bundled Noto Serif faces exist to guarantee a floor on macOS/Linux dev machines and on any stripped Windows install.

**The Noto faces are OFL 1.1** and are redistributable. OFL requires the licence text travel with the fonts — §4 covers this.

---

## 4. Fonts to bundle

Bundle by **script**, not by language. Devanagari alone covers Hindi, Marathi, and Nepali; Bengali covers Assamese.

| Family | Covers |
|---|---|
| Noto Serif Tamil | Tamil (fallback under Vijaya) |
| Noto Serif Devanagari | Hindi, Marathi, Nepali |
| Noto Serif Bengali | Bengali, Assamese |
| Noto Serif Telugu | Telugu |
| Noto Serif Kannada | Kannada |
| Noto Serif Malayalam | Malayalam |
| Noto Serif Gujarati | Gujarati |
| Noto Serif Gurmukhi | Punjabi |
| Noto Serif Oriya | Odia |
| Noto Nastaliq Urdu | Urdu |

Note that Urdu is the exception: Noto Serif has no Urdu member, and Nastaliq is a genuinely different writing style rather than a serif/sans variant. It also needs more vertical space than any other face here — see §6.

Source scripts:

| Family | Covers | Licence |
|---|---|---|
| Ezra SIL | Hebrew with full pointing and cantillation (UHB) | OFL 1.1 |
| Noto Serif Greek | Polytonic Greek (UGNT) | OFL 1.1 |

Ezra SIL is preferred over SBL Hebrew here specifically because SBL's licence requires individual registration, which does not survive redistribution in an installer. Ezra is OFL and handles UHB's cantillation marks correctly.

**Weights:** Regular and Bold only. Skip the variable versions — the static pair is smaller and there is no intermediate weight anywhere in the app's type system. That is 24 files at roughly 40–90 KB each once compressed, so about 1.5–2 MB total.

### 4.1 Acquisition and conversion

Download the static TTFs from the Google Fonts repository (`github.com/notofonts`) and Ezra SIL from SIL. Convert to WOFF2:

```bash
pip install fonttools brotli
fonttools ttLib.woff2 compress NotoSerifTamil-Regular.ttf
```

**Do not subset the Indic or Hebrew fonts.** Complex-script shaping depends on the full GSUB/GPOS tables. Aggressive subsetting will silently break Tamil conjuncts, Devanagari ligatures, and Hebrew mark positioning — and it will break them in ways that look like a rendering bug rather than a font bug, which is expensive to debug later.

**Commit the WOFF2 files to the repo.** A download-at-build-time step is at odds with Bridge being local-first and would break offline builds. 2 MB is an acceptable one-time cost.

---

## 5. File placement and build wiring

There is currently **no `public/` directory** in the repo, and `vite.config.ts` does not set `publicDir`. Vite's default is `<root>/public`, so creating the directory is sufficient — no config change is needed.

Create:

```
public/
  fonts/
    OFL.txt
    README.md                    ← provenance: source URL + version for each file
    NotoSerifTamil-Regular.woff2
    NotoSerifTamil-Bold.woff2
    ... (one pair per family from §4)
    EzraSIL-Regular.woff2
    EzraSIL-Bold.woff2
```

Files here are copied verbatim into `dist/` and served from `tauri://localhost/fonts/…` at runtime.

**CSP:** `src-tauri/tauri.conf.json:24` has `"csp": null`, so no `font-src` directive is needed. If CSP is ever tightened later, it must include `font-src 'self'` or every bundled font will be blocked.

**Bundle resources:** `tauri.conf.json:40` lists `"resources": ["resources/"]` — this is for the Python sidecar and is unrelated. Fonts ride along inside the frontend `dist/` and need no entry here.

**Attribution:** add a line to the Settings modal's resources pane (`SettingsModal.svelte`, the pane already rendering `originalLanguageResource` metadata around line 228) noting that bundled fonts are licensed under OFL 1.1, with `OFL.txt` shipped alongside them.

---

## 6. CSS changes

All of this lands in `src/index.css`. There is no Tailwind font extension needed — `tailwind.config.js` does not currently override `fontFamily`, and adding one would create a second source of truth.

### 6.1 `@font-face` declarations

Add a block after the `@tailwind` directives and before `:root`. One pair per family:

```css
@font-face {
  font-family: "Noto Serif Tamil";
  src: url("/fonts/NotoSerifTamil-Regular.woff2") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
@font-face {
  font-family: "Noto Serif Tamil";
  src: url("/fonts/NotoSerifTamil-Bold.woff2") format("woff2");
  font-weight: 700;
  font-style: normal;
  font-display: swap;
}
/* …repeat for each family in §4 */
```

`font-display: swap` is right here: these are local files with no network latency, and swap avoids any invisible-text flash on a slow first paint.

### 6.2 Font tokens in `:root`

Add to the existing `:root` block, after the type scale. Comment them in the same explanatory style the file already uses for `--tn`/`--gr`/`--pass` and the `--fs-*` ramp:

```css
  /* Font stacks. Target-script faces are appended to --font-ui rather than
     applied per-component: CSS resolves fallback per glyph by coverage, so
     Latin chrome hits Inter and stops, a Tamil glyph passes over Inter to
     Vijaya, a Devanagari glyph passes over both to Noto Serif Devanagari.
     Mixed-script strings (a finding message quoting target text) therefore
     render correctly in a single text node with no language plumbing.
     Vijaya and Nirmala UI ship with Windows and are named, never bundled --
     Microsoft grants no redistribution right. The Noto faces are bundled
     under OFL 1.1 and exist as the floor on macOS/Linux and stripped
     Windows installs. Adding a gateway language needs no code change here
     so long as its script is already in the chain. */
  --font-indic:
    "Vijaya", "Nirmala UI",
    "Noto Serif Tamil", "Noto Serif Devanagari", "Noto Serif Bengali",
    "Noto Serif Telugu", "Noto Serif Kannada", "Noto Serif Malayalam",
    "Noto Serif Gujarati", "Noto Serif Gurmukhi", "Noto Serif Oriya",
    "Noto Nastaliq Urdu";

  --font-ui: -apple-system, "Inter", Segoe UI, Helvetica, Arial, var(--font-indic), sans-serif;

  /* Scripture panes use this directly so line-height can be tuned for Indic
     ascender/descender depth without touching the UI chrome's rhythm. */
  --font-target: var(--font-indic), var(--font-ui);

  --font-hebrew: "Ezra SIL", "SBL Hebrew", serif;
  --font-greek: "Noto Serif Greek", "Gentium Plus", serif;
```

Ordering note: Vijaya sits ahead of the Noto faces and covers only Tamil, so it cannot shadow any other script. Nirmala UI is broader — it covers most Indic scripts on Windows 8+ — and sits second deliberately, per the requested stack. On a Windows machine this means non-Tamil Indian languages get Nirmala UI rather than bundled Noto Serif. That is the intended behaviour: Nirmala is a competent face, it is what those users see elsewhere on their system, and the bundled Noto still catches every non-Windows case. If a reviewer later prefers Noto Serif uniformly for non-Tamil scripts, move `"Nirmala UI"` to sit after the Noto entries — a one-line change.

### 6.3 Apply to `body`

Replace `src/index.css:43`:

```css
body { margin: 0; font-family: var(--font-ui); }
```

This single line is what makes every one of the eight-plus target-text components render correctly, with no changes to any of them.

### 6.4 Scripture pane tuning

Indic scripts carry deeper ascenders and descenders than Latin and need more leading. The main verse pane already uses a generous value, but the editing textarea and the alignment surfaces do not.

| File | Line | Rule | Change |
|---|---|---|---|
| `VerseList.svelte` | 384 | `.vtext` | add `font-family: var(--font-target);` — keep `line-height: 1.85` |
| `VerseList.svelte` | 419 | `.vedit textarea` | add `font-family: var(--font-target);` and raise `line-height: 1.7` → `1.85` so text does not shift when a verse enters edit mode |
| `AlignmentModal.svelte` | 481 | `.aligned-card .word` | add `font-family: var(--font-target);` |
| `AlignmentModal.svelte` | ~455 | `.interlinear` | add `font-family: var(--font-hebrew);` — this pane is source text |

`VerseList.svelte:420` currently sets `font-family: inherit` on the textarea; the explicit `--font-target` supersedes it and should replace it rather than sit alongside.

For `LexiconPopup.svelte`, `.headword` (line 89) and `.lemma` (line 100) render source-language words at `--fs-3xl`/`--fs-2xl`. Both need `font-family: var(--font-hebrew)` — but the component takes a `direction` prop defaulting to `"rtl"` (line 7) and is used for Greek as well, so gate it: bind the font to the same signal that already drives direction rather than hardcoding Hebrew. If that plumbing turns out to be more than a few lines, leave the Greek case to `--font-ui` fallback for now and note it — Greek is far less sensitive to face choice than pointed Hebrew is.

**Urdu:** Nastaliq needs roughly 2.0 line-height to avoid clipping its steep baseline cascade. Bridge has no Urdu project today, so do not add a special case now. Note it in `BUILD_LOG.md` as a known adjustment for whenever an Urdu project first lands.

---

## 7. Explicitly out of scope

- **A user-facing font picker in Settings.** Settings persist through the Python sidecar (`bridge.getSettings()` / `SettingsData` in `src/lib/types/finding.ts`), so a font preference would need an engine-side schema change and a settings migration. Not worth it before the fallback chain has been validated in real use.
- **Font detection / enumerating installed families.** Not needed, since fallback resolves by coverage. If a picker is ever built, do detection in Rust with the `font-kit` crate — the browser `queryLocalFonts()` API triggers a permission prompt, and the canvas-measurement hack is unreliable for Indic scripts.
- **`lang` attributes on scripture panes.** Worth doing eventually for shaping-engine hints and screen readers, but it is a separate change touching the same eight components, and the font work does not depend on it.
- **The queued font-size setting.** Related but independent; the `--fs-*` ramp in `:root` is the seam for it and this change does not disturb that ramp.

---

## 8. Verification

Bridge's test suite is pytest on the engine side; none of this is engine code, so verification is manual and visual.

1. `npm install` → `.\scripts\build-sidecars.ps1` → `npm run tauri dev`.
2. Open the Tamil IRVTam validation project. Confirm verse text in `VerseList` renders in Vijaya — it is a serif face with distinctly rounded loops, unmistakable against Nirmala UI's flatter sans forms. Confirm no tofu boxes anywhere.
3. Enter edit mode on a verse. Text must not shift or reflow — same face, same leading, same size as the read view.
4. Open the alignment modal on an aligned verse. Source column in Ezra SIL with cantillation marks correctly positioned above and below the consonants, not floating or overlapping. Target words in Vijaya.
5. Open the report screen. Confirm Tamil renders correctly inside the issues table and inside any finding message that mixes English and Tamil in one string — this is the case that proves fallback-by-coverage is working rather than a lucky default.
6. Temporarily rename Vijaya out of the stack in `--font-indic` and reload. Text must fall through to Noto Serif Tamil, not to tofu. This is the only way to verify the bundled files are actually being served, since Vijaya masks them on every Windows machine.
7. Build a release bundle and confirm the fonts are present in the installed app's frontend assets.

---

## 9. Commit sequence

Per the project's staged-commit convention for anything touching shared surfaces:

1. **Add font assets.** `public/fonts/` with WOFF2 files, `OFL.txt`, and the provenance `README.md`. No CSS yet — this commit is pure addition and cannot regress anything.
2. **Add `@font-face` and `:root` tokens** to `src/index.css`. Still inert: nothing references the new variables yet.
3. **Switch `body` to `var(--font-ui)`.** This is the behavioural commit and the one to review carefully — it changes rendering app-wide. Verify steps 2, 5, and 6 of §8 before moving on.
4. **Scripture pane tuning** (`VerseList`, `AlignmentModal`, `LexiconPopup`).
5. **Attribution line** in `SettingsModal`, plus a `BUILD_LOG.md` entry recording the bundled font versions, the Vijaya non-redistribution constraint, and the Urdu line-height note for future reference.

Steps 1–3 are independently useful. If step 4 turns out to be fiddlier than expected, stopping after step 3 still leaves Tamil rendering correctly everywhere.
