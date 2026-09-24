# Language QA review fixes — desktop acceptance (A52–A55)

These are the desktop test cases for the four Language QA fixes on
`language-qa`. The fixes are commits `e74eb2d`, `ca4dc5f`, `bfd717f` and
`0da441a`. The engine and frontend unit tests already pass. What is still
missing is proof that the real app behaves correctly:

| Row | Behaviour to confirm |
|---|---|
| A52 | Inline marks appear in every chapter, not only on the Language QA panel's first page. |
| A53 | Verses with footnotes and cross-references get marks, and **Use** edits the right words. |
| A54 | `\wj` verses get marks. |
| A55 | Language QA decisions do not change the dashboard's review progress. |

The rows themselves are in [QA_TEST_MATRIX.md](QA_TEST_MATRIX.md). The
background for each fix is in [BUILD_LOG.md](BUILD_LOG.md), in the
2026-09-24 entry "Language QA review fixes".

Every expected result below was checked against the engine before this
document was written. The fixture was imported in a scratch folder and
scanned, and the findings, offsets and suggestions quoted here come from
that run. If the app shows something different, the app is wrong or the
build is stale. Do not read it as a mistake in this document.

---

## 0. Setup

### 0.1 Build the app that contains the fixes

The fixes change the Python engine, so the sidecars must be rebuilt. The
source tree alone is not enough.

1. Close Bridge completely. A running `bridge-engine.exe` blocks the build;
   see gotcha 13 in `CLAUDE.md`. If it is still running, run
   `Stop-Process -Name bridge-engine -Force`.
2. Check that the branch is at `0da441a` or later:
   `git log --oneline -1` on `language-qa`.
3. From the repository root:
   ```powershell
   .\scripts\build-sidecars.ps1
   npm run tauri dev
   ```
4. **Pass condition:** Bridge opens to the project screen.

### 0.2 Create the test fixture

Real IRV Philippians produces only 31 Language QA findings. It has no inline
finding next to a footnote and no `\wj` at all, so it cannot exercise these
cases. Use this generated Titus file instead:

- chapters 1 and 2 have 40 identical verses each;
- chapter 3 has 45 verses;
- verses 3:41–3:45 are the special cases.

Save this as `make_lqa_fixture.py` anywhere, then run it with the engine's
Python:

```python
from pathlib import Path

PLAIN = "அவன் அந்த காகம்  பார்த்தான்."          # note the TWO spaces before பார்த்தான்
SPECIAL = {
    41: "அவன் சொன்னான்\\f + \\ft இது ஒரு குறிப்பு.\\f* அந்த காகம் பறந்தது.",  # footnote BEFORE the flagged words
    42: "அந்த பட்டணம்\\f + \\ft பட்டணம் என்பது ஊர்.\\f* அழகாக இருந்தது.",  # footnote AFTER the flagged words
    43: "அவன் வந்தான் \\f + \\ft இரண்டு  இடைவெளி\\f* பின்பு போனான்.",      # doubled space INSIDE the footnote
    44: "இயேசு: \\wj அவர்கள் அவனை கொன்றார்கள்\\wj* என்றார்.",               # words of Jesus
    45: "\\wj அந்த\\wj* காகம் பறந்தது.",                                      # marker BETWEEN the two words
}
lines = ["\\id TIT Language QA acceptance fixture", "\\usfm 3.0", "\\h தீத்து",
         "\\toc1 தீத்து", "\\mt1 தீத்து"]
for chapter in (1, 2, 3):
    lines += [f"\\c {chapter}", "\\p"]
    for verse in range(1, (45 if chapter == 3 else 40) + 1):
        text = SPECIAL.get(verse, PLAIN) if chapter == 3 else PLAIN
        lines.append(f"\\v {verse} {text}")
Path("56TITLQA.SFM").write_text("\n".join(lines) + "\n", encoding="utf-8")
```

```powershell
.\engine\.venv\Scripts\python.exe make_lqa_fixture.py
```

### 0.3 Import it

1. In Bridge, import `56TITLQA.SFM` as a new project.
   - Language: **Tamil**, code `ta`. This matters: the வல்லினம் rule only runs
     when the book is detected as Tamil.
   - Any project name, for example `LQA acceptance`.
2. Open the book.
3. Wait for the Language QA panel header, bottom or side of the editor, to
   read **Language QA · completed**. This takes a few seconds.

**What the fixture should produce.** Use this as a sanity check before you
start. If these numbers are wrong, stop and report it.

| Item | Expected |
|---|---|
| Total Language QA findings | **244** |
| Inline findings in chapter 3 (marks you can see) | **43** |
| Position of chapter 3's first inline finding in the panel's list | item **162** (zero-based index 161), well past the panel's first page of 100 |
| Coverage | "Coverage incomplete", with **Coverage details (1)**: `Chapter 3: 45: 1 candidate(s) spanning inline USFM markup omitted.` That is expected; see A54.3. |

Titus really has 16/15/15 verses, so Bridge's versification or USFM checks
may also complain about the extra verses. That is expected noise and not
part of these tests.

**How to read a mark.** A வல்லினம் finding is a **yellow highlight** on two
words. A termbase finding is a double underline, but this fixture has none.
Right-clicking a yellow highlight opens a menu with `Use "<suggestion>"`,
**Edit** and **Ignore**.

To see a verse's raw text with its markers, double-click the verse to open
the editor, look, then press ✕ (Cancel). Never press ✓ unless the step says
to.

---

## A52 — Inline marks cover the whole book

**The bug being fixed.** Marks were fed from the panel's own first page of
100 findings. In a book with more than 100 findings, every mark past that
point was missing. On this fixture, the old build showed marks in chapter 1
and the start of chapter 2, and none at all in chapter 3.

### A52.1 Marks in the first chapter (baseline)

1. Go to chapter 1.
2. Look at verse 1.

**Expected:** `அந்த காகம்` in 1:1 has a yellow highlight. Every verse
1:1–1:40 has the same highlight.

### A52.2 Marks deep in the book, past the panel's first page

1. Go to chapter 2 and scroll to **2:40**.
2. Go to chapter 3 and scroll to **3:40**.

**Expected:**
- `அந்த காகம்` is highlighted in 2:40 and in 3:40.
- In chapter 3, every verse 3:1–3:40 is highlighted.
- Marks may take up to about 5 seconds to appear after you change chapter,
  because the marks refresh every 5 s and on every chapter change.

**Fail:** chapter 3, or the later part of chapter 2, has no highlights.

### A52.3 The menu works on a deep mark

1. Right-click the highlight in **3:40**.

**Expected:**
- The menu shows `Use "அந்தக் காகம்"`, **Edit** and **Ignore**.
- Press Esc to close it without choosing.

### A52.4 Switching chapters swaps the marks

1. From chapter 3, go to chapter 1, then back to chapter 3.

**Expected:**
- Each chapter shows its own highlights.
- No highlight from the previous chapter is left drawn on the wrong verse.

### A52.5 The panel still pages

1. Leave the panel collapsed and read its header.
2. Expand the panel and step through its pages.
3. While paging, glance at the verse text.

**Expected:**
- Collapsed, the header still shows the total of 244.
- Expanded, it lists findings 50 at a time and you can page forward.
- Paging the panel does **not** change the highlights in the verse text.

---

## A53 — Footnoted and cross-referenced verses are checked, and Use lands correctly

**The bugs being fixed:**
- Any verse containing a backslash was skipped entirely, so footnoted verses
  had no Language QA at all.
- Once that was fixed, **Use** on a mark *after* a footnote would have cut
  the verse in the wrong place. On the old build it refused with "The
  suggested fix is stale because the verse text changed."

### A53.1 Footnote before the flagged words (3:41) — mark

1. Go to **3:41**.

**Expected:**
- The verse reads `அவன் சொன்னான்` [footnote marker] `அந்த காகம் பறந்தது.`
- `அந்த காகம்`, *after* the footnote marker, is highlighted yellow.
- The footnote marker button opens a note reading `இது ஒரு குறிப்பு.`

### A53.2 Footnote before the flagged words (3:41) — Use

This is the key test.

1. Right-click the highlight in 3:41.
2. Choose `Use "அந்தக் காகம்"`.

**Expected:**
- The notice says "Fix applied and verse re-checked."
- The verse now reads `… அந்தக் காகம் பறந்தது.`
- The highlight is gone.
- Double-click 3:41 to see the raw text. It must be exactly:
  ```
  அவன் சொன்னான்\f + \ft இது ஒரு குறிப்பு.\f* அந்தக் காகம் பறந்தது.
  ```
  The footnote is byte-for-byte unchanged. Only `க்` was inserted after
  `அந்த`. Press ✕ to close.
- The footnote marker still opens `இது ஒரு குறிப்பு.`

**Fail:**
- A "stale" message appears;
- the text changes in the wrong place, for example inside or next to the
  footnote;
- or the footnote is damaged or lost.

### A53.3 Footnote after the flagged words (3:42) — mark and Use

1. Go to **3:42**. `அந்த பட்டணம்` at the start is highlighted.
2. Right-click it and choose `Use "அந்தப் பட்டணம்"`.

**Expected:** the raw text, seen by double-click then ✕, is:
```
அந்தப் பட்டணம்\f + \ft பட்டணம் என்பது ஊர்.\f* அழகாக இருந்தது.
```

### A53.4 Text inside a footnote is not checked (3:43)

The footnote in 3:43 contains a deliberate doubled space
(`இரண்டு  இடைவெளி`).

1. Go to **3:43**.
2. In the expanded panel, look for any entry for **TIT 3:43**.

**Expected:**
- No highlight in 3:43.
- The panel lists **no** Language QA finding for TIT 3:43.
- Lifting the footnote out also leaves no doubled space between `வந்தான்`
  and `பின்பு`.

### A53.5 An unbalanced footnote is skipped and named

This case is created by editing, because it cannot be imported cleanly.

1. Double-click **3:40**. Replace the whole text with this. It has a
   footnote that is opened and never closed:
   ```
   அவன் அந்த காகம் பார்த்தான்.\f + \ft முடிவில்லாத குறிப்பு
   ```
2. Press ✓ (Save & re-check).
3. Wait for Language QA to reach **completed** again.

**Expected:**
- 3:40 has **no** yellow highlight, even though `அந்த காகம்` is in it. The
  verse was deliberately not checked.
- Expand the panel's **Coverage details**. It contains:
  ```
  Chapter 3: 40: Unbalanced \f: 1 open, 0 close; verse not checked.
  ```
- Bridge's own local checks may also raise a "USFM marker imbalance"
  finding for 3:40. That is expected and separate.

**Clean-up:** edit 3:40 back to `அவன் அந்த காகம்  பார்த்தான்.`, with two
spaces, and save. Its highlight should return within a few seconds. This
also confirms marks refresh after an edit.

### A53.6 A real IRV verse with a cross-reference (optional, real data)

1. Open the existing **IRV Philemon** project (`ta_irvv_phm_book`).
2. Go to verse **2**. It starts with a cross-reference to `கொலோ 4:17`.

**Expected:**
- The verse is now checked. The Language QA panel does not list verse 2
  among the skipped or omitted verses.
- Before these fixes, every Philemon verse with a note (2, 3, 7, 8, 10, 23,
  24) was skipped.
- None of these verses has a வல்லினம் pattern, so no highlight is expected.
  The point is that the verses are no longer skipped.

---

## A54 — `\wj` and other character-marker verses are checked

**The bug being fixed.** The same bail-out as A53: `\wj` verses got no
Language QA.

### A54.1 Words of Jesus (3:44)

1. Go to **3:44**. The verse contains `\wj … \wj*`.

**Expected:**
- `அவனை கொன்றார்கள்`, inside the words of Jesus, is highlighted yellow.
- Right-click shows `Use "அவனைக் கொன்றார்கள்"`.
- The panel may also list a low-severity `tamil.wordlist-variant` finding on
  `அவனை`. That is panel-only and expected.

### A54.2 Use inside `\wj` keeps the markers

1. In 3:44, choose `Use "அவனைக் கொன்றார்கள்"`.

**Expected:** the raw text, seen by double-click then ✕, is:
```
இயேசு: \wj அவர்கள் அவனைக் கொன்றார்கள்\wj* என்றார்.
```
Both `\wj` and `\wj*` are untouched.

### A54.3 A marker *between* the two words is reported, not guessed (3:45)

1. Go to **3:45**. Its raw text is `\wj அந்த\wj* காகம் பறந்தது.`, with the
   closing marker between `அந்த` and `காகம்`.

**Expected:**
- **No** highlight in 3:45.
- No single stretch of raw text holds that pair without covering the marker,
  so the candidate is dropped and counted rather than drawn over markup.
- **Coverage details** contains:
  ```
  Chapter 3: 45: 1 candidate(s) spanning inline USFM markup omitted.
  ```

---

## A55 — Language QA decisions do not change review progress

**The bug being fixed.** Use and Ignore on a Language QA mark were counted in
the book's review progress. A verse with no real review could show as
"Reviewed" just because a வல்லினம் mark was ignored.

The dashboard shows **Reviewed X/Y** only once at least one chapter has been
checked, so run a check first.

### A55.0 Setup

1. On a **fresh** import of the fixture, run the chapter check for
   **chapter 3**. Use the same check that makes the dashboard say
   "Checked 1/3 chapters".
   - The fresh import matters because A53/A54 edited chapter 3. You can
     also do A55 before A53/A54.
2. Wait until it finishes.
3. Go to the project dashboard and write down the book's **Reviewed X/Y**
   and **Checked N/3 chapters**.
4. Back in the editor, pick a chapter-3 verse that meets all three
   conditions:
   - it shows **✓** next to its number (checked, no open findings);
   - it has a yellow highlight;
   - you have not touched it yet.

   3:41 or 3:42 are the likely candidates. A verse with open Greek Room
   findings cannot tell old behaviour from new, so do not use one. Write the
   verse down.

### A55.1 Ignore does not count as review

1. Right-click the chosen verse's highlight and choose **Ignore**.
2. The highlight disappears and the notice says "Occurrence ignored."
3. Go to the dashboard.

**Expected:**
- **Reviewed X/Y** is exactly the number you wrote down.
- **Checked N/3** is unchanged.

**Fail:** Reviewed went up by 1. That was the old behaviour.

### A55.2 Ignore still works after reopening

1. Close the project and reopen it, or switch to another book and back.
2. Wait for Language QA to reach **completed**.

**Expected:**
- The ignored highlight does **not** come back.
- The decision is still recorded and still hides that finding. It just is
  not counted as review.

### A55.3 Use does not count as review either

1. On another ✓ verse with a highlight, choose `Use "…"`.
2. The fix applies.
3. Go to the dashboard.

**Expected:** the Language QA "accepted" decision does not raise
**Reviewed**.

Caveat: Use re-runs the verse's checks. If that re-check itself adds or
clears Greek Room findings on the verse, the count can move for that reason.
If Reviewed moves, check the verse's own findings in the review panel before
calling it a failure.

### A55.4 Control: Greek Room decisions still count

1. Pick a chapter-3 verse with exactly **one** open Greek Room or local
   finding. It shows no ✓ and has a numbered finding in the review panel.
2. Accept or ignore that finding from the review panel or its right-click
   menu.
3. Go to the dashboard.

**Expected:** **Reviewed** goes up by 1, exactly as before these fixes. This
proves the exclusion is specific to Language QA.

---

## Recording the result

For each case, write down:
- PASS or FAIL;
- the date;
- the build: `git log --oneline -1` and whether the sidecars were rebuilt;
- for any FAIL, what you saw instead, with a screenshot if you can.

| Case | Result | Notes |
|---|---|---|
| Fixture sanity (244 / 43 / item 162 / 1 coverage detail) | | |
| A52.1 marks, chapter 1 | | |
| A52.2 marks at 2:40 and 3:40 | | |
| A52.3 menu on a deep mark | | |
| A52.4 chapter switch | | |
| A52.5 panel still pages | | |
| A53.1 3:41 mark after footnote | | |
| A53.2 3:41 Use, raw text exact, footnote intact | | |
| A53.3 3:42 Use | | |
| A53.4 3:43 no finding from footnote text | | |
| A53.5 unbalanced `\f` skipped with named reason | | |
| A53.6 IRV Philemon noted verses checked (optional) | | |
| A54.1 3:44 `\wj` mark | | |
| A54.2 3:44 Use keeps `\wj` markers | | |
| A54.3 3:45 crossing reported, no mark | | |
| A55.1 Ignore leaves Reviewed unchanged | | |
| A55.2 Ignore persists after reopen | | |
| A55.3 Use leaves Reviewed unchanged | | |
| A55.4 Greek Room decision still counts | | |

Then, in [QA_TEST_MATRIX.md](QA_TEST_MATRIX.md), change rows A52–A55 from
"PASS (desktop pending)" to **PASS** or **FAIL**, with the date and a
one-line summary. Add a short dated note to [BUILD_LOG.md](BUILD_LOG.md). A
FAIL is a finding to report or file as an issue; do not work around it
quietly.
