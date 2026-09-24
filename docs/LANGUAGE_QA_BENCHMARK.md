# Language QA benchmark

Per-rule precision and recall of Bridge's offline Language QA, measured on
the Tamil IRV against the Round 2 and Pass 3 review reports. This is Phase 2
of the layered-rules plan in [LANGUAGE_QA_PLAN.md](LANGUAGE_QA_PLAN.md): it
decides whether a rule earns inline status, and it guards every later phase
against regression.

## What the numbers mean — read this first

- **Every review row is an AI proposal.** The reports say so on every row
  ("AI proposal awaiting human review"). On 2026-09-24 the maintainer
  decided to use all of them as positives: a false positive can be corrected
  later. So **precision here is agreement with the AI review, not with
  verified truth.** A rule can be right where the review is silent, and
  wrong where the review agrees.
- **"Maybe"** marks a row the reports contradict themselves on:
  - two rows at one place proposing different fixes;
  - a fix that another row at the same verse proposes to undo;
  - a flag on a form the Pass 3 reviewers confirmed is house style
    (`IRV_Pass3_Handoff.md` §5). These are `இந்த` + bare hard consonant,
    `அந்த தேச-` bare, `-விட` bare, names ending in `-க்கு`, and digits in
    verse text.
- **Strict** counts only positives. **Lenient** also counts maybes as
  positives.
- **A human verdict against an AI proposal is also "maybe", not a
  negative.** The Philippians report's Rejected/Disputed rows are the only
  human verdicts in the inputs. That pass answered a different question:
  was the inconsistency worth an editorial fix. The maintainer said its
  dispositions are not linguistic ground truth (BUILD_LOG, B3 entry), and
  php 1:29 later went from Rejected to Confirmed.
- **The inputs contain no verified negatives.** The "negative" columns are
  reserved for a future human-labelled set. The rejected leads the brief
  suggested seeding negatives from do not hold up. php 1:29 was confirmed.
  php 3:14 and 4:18 are real bare boundaries that B4 excludes only for
  scope. So the labelled fixtures carry positive and "maybe" examples, and
  no invented negatives.
- The reviews flag **minority forms**: "in this book -க்கு before க/ச/த/ப is
  doubled 178 times and bare 10 times". A rule that also fires on a book's
  majority form counts those findings as false positives, although some may
  be real errors the review did not list. Every unmatched finding is written
  to the result file for a human to label.

## Inputs (outside the repository)

| Input | Expected layout |
|---|---|
| `--irv-dir` | A folder of IRV books as SFM, one per book, named like `01GENIRVTam.SFM`. Each file's own `\id` line identifies the book. |
| `--reviews` | Folders or files. A folder contributes its top-level `*_Issues.csv` files, so `v1-before-split/` is not read. |

The CSV columns are: `Book, Chapter, Verse, Issue Type, Priority Category,
Severity, Confidence, Original Tamil, Suggested Correction, Explanation,
Source / Reference Note, Reviewer Decision Needed, Status`. Some files name
the reference column `Source / ESV Reference Note` or add a `Review Scope`
or `Detected By` column; extra columns are ignored.

`Book` may be a code (`PSA`) or an English name (`1 Samuel`). Rows are
skipped when Chapter is `Intro`, `Book-level` or empty, when Verse is `—`
or empty, or when there is no `Original Tamil`.

The run of 2026-09-24 used:
- `C:\Users\Benz\Documents\IRV Tamil`, all 66 books;
- `D:\Claude Lab\Revant work\Claude outputs`: 16 Round 2 reports (GEN–2CH,
  EZR, RUT, PSA) and 5 Pass 3 reports (GEN, EXO, LEV, NUM, DEU);
- `C:\Users\Benz\Documents\Claude outputs\Philippians_Round2_QA_Issues.csv`,
  whose rows carry human verdicts.

## Scope

| Issue Type | Bucket | Engine layer that should find it |
|---|---|---|
| Confirmed typo, Possible typo | typo | lexicon, integrity |
| Sandhi / word-joining | sandhi | pattern rules |
| Punctuation, only spacing / repetition / space-before | punctuation | integrity |
| Name consistency | name | house style (Phase 6 name pack) |
| USFM marker, Footnote / cross-reference | usfm | integrity, where a text-only rule can see it |

Out of scope, and reported as counts only (LQA-3+): Grammar, Plural
agreement, Case/object marker, Source comparison, Possible missed source
word, Addition not in source, Textual-basis review, Theological consistency,
Reviewer decision, and Punctuation rows about comma or semicolon policy.

## Method

1. Each book is parsed with `parse_scripture_file` and
   `imported_verse_text`, exactly as import writes chapter JSON.
2. It is scanned by the app's own `LanguageQaManager`. There is no second
   copy of the rules.
3. A finding is a **true positive** when it overlaps a positive row at the
   same chapter and verse: the NFC-normalised texts must be substrings of
   one another in either direction. The row must also be of a type the
   rule can find (`RULE_BUCKETS`). A வல்லினம் finding cannot be "confirmed"
   by a Source comparison row that happens to cover the same words.
4. **Recall** is counted per bucket, over rows whose `Original Tamil` is
   found in the scanned verse text. Unanchored rows are counted separately:
   headings, `\ms` lines, text changed since the review.

## Running it

```powershell
.\engine\.venv\Scripts\python.exe scripts\language_qa_benchmark.py `
  --irv-dir "C:\Users\Benz\Documents\IRV Tamil" `
  --reviews "D:\Claude Lab\Revant work\Claude outputs" "C:\Users\Benz\Documents\Claude outputs\Philippians_Round2_QA_Issues.csv" `
  --gate
```

Options:

| Option | What it does |
|---|---|
| `--update-doc` | Rewrites the generated block below. |
| `--write-baseline` | Rewrites `benchmark/baseline.json`, the aggregate numbers only. |
| `--write-labelled` | Rewrites the Phase 2.4 fixtures in `engine/tests/fixtures/language_qa/labelled/`. |

The full result goes to `benchmark/results/<date>-<pack>.json`, which is not
committed because it quotes Scripture and review text. It holds every
unmatched finding and every unmatched row.

**The gate is local.** The IRV text and the reports live outside the
repository, so CI cannot run it (maintainer decision, 2026-09-24). Run
`--gate` before committing a change to a rule, and record its output in
BUILD_LOG. It fails when:
- an inline rule's strict precision is below 0.90;
- any rule's strict precision fell more than 2 points below
  `benchmark/baseline.json`. Rules with fewer than 10 findings are too small
  to compare.

## Results

<!-- benchmark:start -->
_Generated 2026-09-24T19:57:43 by scripts/language_qa_benchmark.py._

Pack version `language-qa-7+ta-irv@1.0.0`; books: 1CH, 1KI, 1SA, 2CH, 2KI, 2SA, DEU, EXO, EZR, GEN, JDG, JOS, LEV, NUM, PHP, PSA, RUT.

Per rule (a finding is a true positive when it overlaps a review row of a compatible type at the same verse):

| Rule | Inline | Findings | TP (strict) | FP (strict) | of which on a house form | Precision strict | Precision lenient | Matched maybe | Matched negative |
|---|---|---|---|---|---|---|---|---|---|
| `common/punctuation.repeated` | no | 1 | 1 | 0 | 0 | 100.0% | 100.0% | 0 | 0 |
| `common/unicode.invisible` | no | 1 | 1 | 0 | 0 | 100.0% | 100.0% | 0 | 0 |
| `ta-irv/integrity.space-before-note-end` | no | 74 | 55 | 19 | 0 | 74.3% | 74.3% | 0 | 0 |
| `ta-irv/sandhi.clitic.fused` | no | 4 | 0 | 4 | 0 | 0.0% | 0.0% | 0 | 0 |
| `ta-irv/sandhi.vallinam.accusative` | yes | 500 | 275 | 225 | 0 | 55.0% | 55.2% | 1 | 0 |
| `ta-irv/sandhi.vallinam.dative` | yes | 396 | 197 | 199 | 0 | 49.8% | 49.8% | 0 | 0 |
| `ta-irv/sandhi.vallinam.demonstrative` | yes | 80 | 33 | 47 | 13 | 41.2% | 55.0% | 11 | 0 |
| `ta-irv/sandhi.vallinam.manner-adverb` | yes | 13 | 2 | 11 | 0 | 15.4% | 15.4% | 0 | 0 |
| `ta-irv/tamil.repeated-word` | no | 33 | 0 | 33 | 0 | 0.0% | 0.0% | 0 | 0 |
| `ta-irv/tamil.wordlist-variant` | no | 2473 | 49 | 2424 | 0 | 2.0% | 2.0% | 0 | 0 |
| `ta-irv/typo.divine-name.dative-stem` | no | 13 | 9 | 4 | 0 | 69.2% | 69.2% | 0 | 0 |
| `ta-irv/typo.divine-name.vowel-drop` | no | 11 | 11 | 0 | 0 | 100.0% | 100.0% | 0 | 0 |
| `ta-irv/typo.suffix.dropped-tha` | no | 2 | 2 | 0 | 0 | 100.0% | 100.0% | 0 | 0 |

Per review bucket (recall counts only rows whose Original Tamil is found in the scanned verse):

| Bucket | Positive rows | Maybe rows | Negative rows | Unanchored | Found (positive) | Recall strict | Recall lenient |
|---|---|---|---|---|---|---|---|
| typo | 839 | 13 | 0 | 80 | 68 | 8.9% | 8.8% |
| sandhi | 1877 | 34 | 0 | 110 | 501 | 28.3% | 28.5% |
| punctuation | 72 | 0 | 0 | 22 | 9 | 18.0% | 18.0% |
| name | 528 | 3 | 0 | 144 | 0 | 0.0% | 0.0% |
| usfm | 680 | 4 | 0 | 421 | 64 | 24.4% | 24.3% |
<!-- benchmark:end -->

## History

| Date | Pack | Change | `tamil.vallinam-missing` strict precision / sandhi recall |
|---|---|---|---|
| 2026-09-24 | language-qa-7 | Phase 2 baseline, before any rule change. **The gate fails:** the only inline rule reaches 37.9% strict precision; 77 of its 193 false positives fall on confirmed house forms. | 37.9% / 6.8% |
| 2026-09-24 | language-qa-7+ta-irv@1.0.0 | Phase 3: rules move into the `ta-irv` pack; B1/B2 split into four vallinam rules with corpus abstains (house forms, root nouns, clitics); one wrong-consonant rule and five IRV defect-shape rules added. House-form false positives on the demonstrative rule fall from 77 to 13. **The gate passes on sign-offs, not on the 90% floor:** the maintainer signed off every vallinam rule for inline display at its measured precision (docs/DECISIONS.md). The column is now the best vallinam rule. | 55.0% (accusative; demonstrative 41.2%) / 28.3% |
