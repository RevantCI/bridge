# ta-irv candidate pack changes (from human review)

## Human precision per rule (house-style suppressions excluded, as the benchmark does)

| rule | labelled | TP | FP | house | unsure | precision | inline? |
|---|---|---|---|---|---|---|---|
| common/spacing.extra | 8 | 8 | 0 | 0 | 0 | 100% | no |
| ta-irv/lexicon.known-misspelling | 10 | 4 | 4 | 0 | 2 | 50% | no |
| ta-irv/sandhi.clitic.fused | 6 | 2 | 0 | 0 | 4 | 100% | no |
| ta-irv/sandhi.compound.direction | 25 | 25 | 0 | 0 | 0 | 100% | yes |
| ta-irv/sandhi.vallinam.accusative | 40 | 39 | 1 | 0 | 0 | 98% | yes |
| ta-irv/sandhi.vallinam.dative | 40 | 39 | 1 | 0 | 0 | 98% | yes |
| ta-irv/sandhi.vallinam.demonstrative | 17 | 17 | 0 | 0 | 0 | 100% | no |
| ta-irv/sandhi.vallinam.manner-adverb | 20 | 20 | 0 | 0 | 0 | 100% | yes |
| ta-irv/sandhi.vallinam.wrong-consonant | 1 | 1 | 0 | 0 | 0 | 100% | no |
| ta-irv/typo.divine-name.dative-stem | 4 | 4 | 0 | 0 | 0 | 100% | no |
| ta-irv/typo.divine-name.vowel-drop | 4 | 4 | 0 | 0 | 0 | 100% | no |
| ta-irv/typo.suffix.dropped-tha | 2 | 2 | 0 | 0 | 0 | 100% | no |

## Recall check (abstained contexts)

| class | missed | correct skip | house | unsure | missed rate |
|---|---|---|---|---|---|
| T_theva_abstain | 0 | 4 | 16 | 0 | 0% |

## Systematic findings from the labels

- Proper noun as next word: doubling required in 9 cases, not required in 0. **Do not abstain on proper nouns**; drop the `housestyle.properNouns` abstain from the vallinam rules (keep the list only for the lexicon/name checks).
- Root-noun false alarms: சேட்டை, தோவேக்கு. Of these, 0 end in the abstract-noun suffix -மை → add `prev.notSuffix: ["மை"]` (a -மை noun's accusative is -மையை, so bare -மை is never a case form); the rest go to `notLexical`.
- Projected precision after those two systematic abstains (before any per-word edits): sandhi.vallinam.accusative 100% (39/39), sandhi.vallinam.dative 100% (39/39), sandhi.vallinam.demonstrative 100% (17/17), sandhi.vallinam.manner-adverb 100% (20/20)
- **தேவ- house rule validation** (other books): no-doubling confirmed 20, doubling required 0. Keep the pack-wide abstain.
- **Split words** (candidate `word-joining.orphan-syllable`): 10 of 23 judged are real splits → build the rule from `labelled/word-joining.jsonl`; the `negative` rows are the interjections/names to exclude.
    - EZK 13:5 «சு வரை» → சுவரை
    - EZK 22:30 «சு வரை» → சுவரை
    - EZK 41:5 «சு வரை» → சுவரை
    - 1CH 5:8 «நே போ» → நேபோ
    - DEU 34:1 «நே போ» → நேபோ
    - ISA 46:1 «நே போ» → நேபோ
    - JER 48:1 «நே போ» → நேபோ
    - NEH 7:33 «நே போ» → நேபோ
    - NUM 32:3 «நே போ» → நேபோ
    - NUM 32:38 «நே போ» → நேபோ

## Layer 1 — rule edits

- **ta-irv/sandhi.vallinam.accusative**: ADD to `notLexical` (reviewer: not a case form): சேட்டை
- **ta-irv/sandhi.vallinam.dative**: ADD to `notLexical` (reviewer: not a case form): தோவேக்கு

## Layer 2 — lexicon

- `lexicon_curated.csv`: 14 confirmed misspellings → `scripts/build_tamil_lexicon.py --curated`.
- Reviewer false alarms on `lexicon.rare-near-common` are in `labelled/typo.jsonl` as `negative`; add those forms to the lexicon's protected/common set so they are never proposed again.

## Layer 3 — house style

- `housestyle_import.json`: 0 entries (0 proper nouns from lexicon FP_NAME only — sandhi rows never feed the name list, see above; provenance `curated`). Bundle as the ta-irv seed and import into each project.
