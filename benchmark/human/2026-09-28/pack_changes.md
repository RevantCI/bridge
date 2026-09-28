# ta-irv candidate pack changes (from human review)

## Human precision per rule (house-style suppressions excluded, as the benchmark does)

| rule | labelled | TP | FP | house | unsure | precision | inline? |
|---|---|---|---|---|---|---|---|
| common/spacing.extra | 15 | 15 | 0 | 0 | 0 | 100% | no |
| ta-irv/integrity.space-before-note-end | 15 | 0 | 15 | 0 | 0 | 0% | no |
| ta-irv/lexicon.known-misspelling | 43 | 43 | 0 | 0 | 0 | 100% | yes |
| ta-irv/lexicon.rare-near-common | 21 | 0 | 21 | 0 | 0 | 0% | no |
| ta-irv/sandhi.vallinam.accusative | 50 | 35 | 15 | 0 | 0 | 70% | no |
| ta-irv/sandhi.vallinam.dative | 49 | 46 | 3 | 0 | 0 | 94% | yes |
| ta-irv/sandhi.vallinam.demonstrative | 8 | 7 | 1 | 0 | 0 | 88% | no |
| ta-irv/sandhi.vallinam.manner-adverb | 1 | 1 | 0 | 0 | 0 | 100% | no |
| ta-irv/tamil.repeated-word | 20 | 0 | 20 | 0 | 0 | 0% | no |
| ta-irv/typo.divine-name.vowel-drop | 1 | 1 | 0 | 0 | 0 | 100% | no |

## Recall check (abstained contexts)

| class | missed | correct skip | house | unsure | missed rate |
|---|---|---|---|---|---|
| A_ai_rootnoun | 1 | 29 | 0 | 0 | 3% |
| B_ai_baremajority | 5 | 45 | 0 | 0 | 10% |
| D_rku_dative | 17 | 0 | 0 | 0 | 100% |
| E_kku_exception | 5 | 7 | 0 | 0 | 42% |
| G_marker | 2 | 0 | 2 | 0 | 50% |
| H_demonstrative_houseform | 9 | 0 | 0 | 0 | 100% |

## Systematic findings from the labels

- Next-word prefixes the reviewer marked 'case form, but no doubling here' (count): தேவ- ×11, சார- ×1, சீக- ×1. A prefix with ≥3 is a house-style abstain to add to EVERY vallinam rule as `next.prefix` (provenance curated).
- Proper noun as next word: doubling required in 17 cases, not required in 8. **Do not abstain on proper nouns**; drop the `housestyle.properNouns` abstain from the vallinam rules (keep the list only for the lexicon/name checks).
- Root-noun false alarms: வெட்டாந்தரை, வெண்மை, வகை, முழுமை, தொண்டை, தீவினை, குற்றமில்லாமை, அநேகமுறை. Of these, 3 end in the abstract-noun suffix -மை → add `prev.notSuffix: ["மை"]` (a -மை noun's accusative is -மையை, so bare -மை is never a case form); the rest go to `notLexical`.
- Projected precision after those two systematic abstains (before any per-word edits): sandhi.vallinam.accusative 95% (35/37), sandhi.vallinam.dative 100% (46/46), sandhi.vallinam.demonstrative 100% (7/7), sandhi.vallinam.manner-adverb 100% (1/1)

## Layer 1 — rule edits

- **ta-irv/sandhi.vallinam.accusative**: ADD to `notLexical` (reviewer: not a case form): அநேகமுறை, குற்றமில்லாமை, தீவினை, தொண்டை, முழுமை, வகை, வெட்டாந்தரை, வெண்மை
- **ta-irv/sandhi.vallinam.accusative**: REMOVE from `notLexical` (reviewer: real case form, doubling required): அசுத்தமானவைகளை, அபிகாயிலை, அரசாட்சியை, ஆயுதத்தை, உரியதை, கடுங்கோபத்தை, கோட்டைகளை, சுருளை, ஜீவனை, திராட்சைக்காய்களை, நினைவுகளை, படகை, யெகோவாவை, வெட்கத்தை, வெள்ளிக்காசை
- **ta-irv/sandhi.vallinam.dative**: REMOVE from `notLexical` (reviewer: real case form, doubling required): கிழக்கு, சந்ததிகளுக்கு, சபைக்கு, சிலைகளுக்கு, தூணுக்கு, நீதிமானுக்கு, யோபுக்கு, வானராணிக்கு
- **sandhi.vallinam.dative**: extend `prev.suffix` to `(?:க்கு|ற்கு)$` — reviewer confirmed doubling after -ற்கு in:
    - GEN 26:21 «அதற்கு சித்னா» → அதற்குச் சித்னா
    - GEN 26:33 «அதற்கு சேபா» → அதற்குச் சேபா
    - GEN 33:17 «இடத்திற்கு சுக்கோத்» → இடத்திற்குச் சுக்கோத்
    - GEN 34:17 «செய்துகொள்வதற்கு சம்மதிக்கவில்லை» → செய்துகொள்வதற்குச் சம்மதிக்கவில்லை
    - GEN 35:3 «விண்ணப்பத்திற்கு பதில்» → விண்ணப்பத்திற்குப் பதில்
    - GEN 37:35 «மகனிடத்திற்கு பாதாளத்தில்» → மகனிடத்திற்குப் பாதாளத்தில்
    - GEN 41:55 «அதற்கு பார்வோன்» → அதற்குப் பார்வோன்
    - JHN 1:38 «என்பதற்கு போதகரே» → என்பதற்குப் போதகரே
    - JHN 1:41 «என்பதற்கு கிறிஸ்து» → என்பதற்குக் கிறிஸ்து
    - JHN 1:42 «என்பதற்கு பேதுரு» → என்பதற்குப் பேதுரு
    - JHN 5:30 «பிதாவிற்கு சித்தமானதையே» → பிதாவிற்குச் சித்தமானதையே
    - JHN 11:15 «உள்ளவர்களாகிறதற்கு சாத்தியம்» → உள்ளவர்களாகிறதற்குச் சாத்தியம்
    - JHN 11:55 «கொள்வதற்கு தங்களுடைய» → கொள்வதற்குத் தங்களுடைய
    - PSA 20:6 «விண்ணப்பத்திற்கு பதில்கொடுப்பார்» → விண்ணப்பத்திற்குப் பதில்கொடுப்பார்
    - PSA 33:17 «காப்பாற்றுவதற்கு குதிரை» → காப்பாற்றுவதற்குக் குதிரை
    - PSA 37:25 «அப்பத்திற்கு பிச்சை» → அப்பத்திற்குப் பிச்சை
    - PSA 102:13 «அதற்கு தயவு» → அதற்குத் தயவு
- **Not case-suffix findings** (reviewer wants a join or a rewrite — keep these words in `notLexical`; they are evidence for a split-word / compound check, not for the vallinam rules):
    - GEN 47:31 «கை கோலில்» → கைக்கோலில்  (not a case-suffix finding: compound/fused word)
    - PSA 48:13 «வரை கவனித்து» → சுவரைக் கவனித்து  (not a case-suffix finding: first word rewritten)
- **all sandhi rules**: emit the finding on the first word when the pair straddles a poetry line / inline marker (reviewer confirmed):
    - PSA 135:21 «யெகோவாவுக்கு
சீயோனிலிருந்து» → யெகோவாவுக்குச் சீயோனிலிருந்து
    - PSA 143:11 «ஆத்துமாவை
பிரச்சனைகளுக்கு» → ஆத்துமாவைப் பிரச்சனைகளுக்கு
- **sandhi.vallinam.demonstrative**: drop the per-trigger `prefix` house-form abstain for these (reviewer: doubling required):
    - GEN 21:23 «இந்த தேசத்திற்கும்» → இந்தத் தேசத்திற்கும்
    - GEN 26:20 «இந்த தண்ணீர்» → இந்தத் தண்ணீர்
    - GEN 28:15 «இந்த தேசத்திற்கு» → இந்தத் தேசத்திற்கு
    - GEN 34:2 «அந்த தேசத்தின்» → அந்தத் தேசத்தின்
    - GEN 36:20 «அந்த தேசத்தின்» → அந்தத் தேசத்தின்
    - GEN 42:6 «அந்த தேசத்திற்கு» → அந்தத் தேசத்திற்கு
    - GEN 43:11 «இந்த தேசத்தின்» → இந்தத் தேசத்தின்
    - GEN 50:11 «அந்த தேசத்தின்» → அந்தத் தேசத்தின்
    - PSA 147:20 «எந்த தேசத்திற்கும்» → எந்தத் தேசத்திற்கும்
- Demonstrative house-form verdicts (sheet 3): அந்த தேச-: FLAG, அந்த தேவ-: HOUSE, இந்த தண்-: FLAG, இந்த தரி-: FLAG, இந்த திர-: FLAG, இந்த தீங-: FLAG, இந்த தூண-: FLAG, இந்த தேச-: FLAG, இப்படி தேவ-: HOUSE, எந்த தேச-: FLAG, எந்த தேவ-: HOUSE
- **Clitic policy** (sheet 3): ஆவது → FUSED, என → SPACED_BARE, எனும் → SPACED_BARE, என்று → SPACED_BARE, கூட → SPACED_BARE, தான் → FUSED, போல → SPACED_BARE, மட்டும் → SPACED_BARE
    - FUSED → keep abstain in vallinam rules and enable `sandhi.clitic.fused` suggesting the fused form; SPACED_DOUBLED → remove that clitic from the abstain list so the vallinam rule fires; SPACED_BARE → keep abstain, disable clitic.fused for that word.
- **tamil.repeated-word**: 0 true / 20 false. If false dominates, add a reduplication abstain (அடுக்குத்தொடர்: தங்கள் தங்கள், வெவ்வேறு, ஒவ்வொரு…) or set `inline: false` / disable.

## Layer 2 — lexicon

- `lexicon_curated.csv`: 44 confirmed misspellings → `scripts/build_tamil_lexicon.py --curated`.
- Reviewer false alarms on `lexicon.rare-near-common` are in `labelled/typo.jsonl` as `negative`; add those forms to the lexicon's protected/common set so they are never proposed again.

## Layer 3 — house style

- `housestyle_import.json`: 1 entries (1 proper nouns from lexicon FP_NAME only — sandhi rows never feed the name list, see above; provenance `curated`). Bundle as the ta-irv seed and import into each project.
