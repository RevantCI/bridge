# Language QA rule packs

Language QA rules that are specific to a language or a translation are data, not
Python. They live in a **rule pack**: a directory of JSON files under
`engine/tc_ai_bridge/language_packs/<pack>/`. The engine loads a pack once per
process, on first use, and tests it before using it. The loader is
`engine/tc_ai_bridge/language_packs/loader.py`, and it is the authority when this
page and the code disagree.

The only pack today is **`ta-irv`**, the Tamil IRV pack. Its rules come from the
layered-rules brief's Phase 3: the B1/B2 வல்லினம் rules, migrated and split, plus
IRV defect shapes taken from the review reports. Language-neutral checks, such as
Unicode, spacing and repeated punctuation, stay in `language_qa.py` as `common/*`
rules.

Related:

- `docs/LANGUAGE_QA_BENCHMARK.md` explains how each rule's precision is measured.
- `docs/DECISIONS.md` records why rules are data, why overrides only narrow, and
  the inline sign-off.
- `docs/LANGUAGE_QA_TAMIL_SPECIFICATION.md` maps the 56 proofreading items to
  pack ids.

## Layout

```
language_packs/ta-irv/
  pack.json                       pack metadata + ordered list of rule files
  rules/<rule id>.json            one rule per file
```

`pack.json` holds `pack`, `version` (semver), `language`, `script`, `description`
and `rules`. `rules` is an ordered list of paths relative to the pack directory.
The pack version appears in every finding as
`ruleVersion = "<pack>@<version>#<rule version>"`, for example
`ta-irv@1.0.0#1`. An ignore recorded under a different `ruleVersion` expires: the
finding comes back flagged `previouslyIgnored` (see DECISIONS.md). So bumping the
pack version sends every ignore of every pack rule back for re-check. Bump a
single rule's `version` when only that rule changed.

The pack is **bundled data**. `engine/bridge-engine.spec` lists the directory
explicitly, because PyInstaller's import analysis cannot see JSON read from
beside a module.

## A rule

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | Lowercase and dotted: `<category>.<family>.<shape>`. The finding's `ruleId` is `<pack>/<id>`. |
| `version` | yes | Positive integer. Bump it when the rule's behaviour changes. |
| `legacyId` | no | The pre-pack rule name, for example `tamil.vallinam-missing`. The finding's `rule` field and its **finding id** are derived from `legacyId` when it is present, so decisions made before the migration keep matching. |
| `enabled` | no (true) | `false` ships the rule switched off. Its examples are not run. |
| `category` | yes | Drives the default layer and the benchmark bucket. Values: `sandhi`, `word-joining`, `typo` (layer `pattern`); `punctuation`, `spacing`, `unicode` (layer `integrity`); `termbase`, `name` (layer `housestyle`). |
| `layer` | no | Overrides the category's default layer. |
| `severity`, `confidence` | yes | `high`, `medium` or `low`. |
| `inline` | no (false) | Draw the finding as a mark in the verse editor, with the right-click menu. |
| `inlineSignOff` | no | `{by, date, reason, precisionStrict}`. The maintainer's sign-off for drawing the rule inline below the benchmark's 90% floor. `by` and `date` are required. See "Inline and the gate" below. |
| `title` | no | `{ta, en}`, used for display. |
| `message` | yes | `{en: "..."}`. A `str.format` template (see "Placeholders"). |
| `rationale` | no | A template, shown in the finding's "why". |
| `match` | yes | A `token-context` or `regex` match (below). |
| `abstain` | no | Conditions under which the rule stays silent (below). |
| `fix` | no | How the suggested replacement is built (below). No `fix` means no suggestion. |
| `examples` | no | `{incorrect: [...], correct: [...]}`. These run as tests every time the pack loads. |
| `provenance` | no | Free text: where the rule and its numbers came from. |

An unknown key is an error. That is deliberate: a misspelled `abstian` must not
be ignored silently.

### `token-context` match

A token-context match looks at **one pair of adjacent words separated only by
whitespace**. Punctuation, digits and markup between the words make the rule
abstain. `gap` must be `"whitespace"`.

The previous word is split into a base and an optional linking consonant:
`அந்தக்` is base `அந்த` plus link `க`. The split happens only when the word
ends in a hard consonant (க ச த ப) followed by pulli and has more than two code
points.

```json
"match": {
  "type": "token-context",
  "prev": { "lexical": ["அந்த", "இந்த", "எந்த"] },
  "gap": "whitespace",
  "next": { "initial": ["க", "ச", "த", "ப"] },
  "link": "none"
}
```

- `prev` conditions test the **base** of the previous word.
- `next` conditions test the following word.
- `link` sets which shape of the pair the rule is about:
  - `none`: the pair is bare, so the linking consonant is missing (`அந்த காகம்`).
  - `mismatch`: the pair is linked with the wrong consonant (`அந்தச் காகம்`).
  - `any`: the pair is bare or correctly linked. Used by the clitic-fusion rule.

The finding span runs from the start of the previous word to the end of the
next word, in raw code points.

### `regex` match

```json
"match": { "type": "regex", "on": "visible", "pattern": "…(?<span>…)…" }
```

- `on: "visible"` (the default) matches the lifted verse text that the reader
  sees.
- `on: "raw"` matches the raw text, markup included. Only rules whose layer is
  `integrity` may use it. `integrity.space-before-note-end` uses it to see
  `\f … \f*`.
- The finding span is the named group `span` if there is one, otherwise the whole
  match. An empty match is skipped.
- Patterns are compiled with the `regex` module after NFC normalisation, so
  `\p{L}`, `\p{M}` and similar classes work. Use `[\p{L}\p{M}]+` for a Tamil
  word: vowel signs and pulli are marks (`\p{M}`), not letters.

### Conditions

A condition is an object. Every key in it must hold for the condition to match.

| Key | Test |
|---|---|
| `lexical` | The token is one of these (compared after NFC). |
| `notLexical` | The token is none of these. |
| `suffix` | A regex searched at the token's end; `$` is added if missing. |
| `regex` | A regex searched anywhere in the token. |
| `minLength` | The token has at least this many code points. |
| `initial` | The token's first code point is in the set. |
| `prefix` | The token starts with one of these stems. |
| `listRef` | The token is in a named list supplied at scan time. Today the only list is `housestyle.properNouns`. It is empty until Phase 6, and a missing list is empty. |

This is a closed set on purpose: it is not a grammar engine (DECISIONS.md).

### Abstains

```json
"abstain": [
  { "prev": { "lexical": ["அந்த"] }, "next": { "prefix": ["தேச", "தேவ"] },
    "origin": "IRV corpus house form after அந்த: தேச- bare 31/doubled 8 …" }
]
```

An abstain has a `prev` condition, a `next` condition, or both, plus an `origin`.
If a pair matches the rule and any one of its abstains, there is no finding. For
`regex` rules only `next` is meaningful. Every abstain in `ta-irv` states the
corpus counts behind it in its `origin`.

### Fixes

| `fix.type` | Match type | Replacement |
|---|---|---|
| `insert-link` | token-context | Previous word + next word's initial + pulli + the original gap + next word (`அந்த காகம்` → `அந்தக் காகம்`). |
| `replace-link` | token-context | Wrong link swapped for the right one (`அந்தச் காகம்` → `அந்தக் காகம்`). |
| `fuse-link` | token-context | Base + link + next word, with the space removed (clitic fusion). |
| `replace` | regex | `fix.text`, literally. |
| `expand` | regex | `match.expand(fix.template)`, so `\g<name>` back-references work. |

The replacement preserves the raw spelling of everything it does not change. It
is offered as a suggestion. Nothing is applied without the translator choosing
"Use".

### Placeholders

`message` and `rationale` are formatted with:

- token-context: `{prev}` (base), `{word}` (whole previous word), `{next}`,
  `{initial}`, `{link}`, `{fix}`;
- regex: `{span}`, `{fix}`.

### Examples are tests

```json
"examples": {
  "incorrect": [ { "text": "…", "span": "அந்த பெண்", "fix": "அந்தப் பெண்", "origin": "EXO 2:2" } ],
  "correct":   [ { "text": "…", "origin": "GEN 4:14 (house form)" } ]
}
```

At load, each example runs through the real `scan_text`:

- An `incorrect` example must produce a finding of **this rule** exactly on
  `span`. If `fix` is given, the finding's suggestion must equal it.
- A `correct` example must produce no finding of this rule.
- An example may carry `lists` (for example
  `{"housestyle.properNouns": ["…"]}`) to exercise a `listRef`.

If any example fails, the pack is refused with a `PackError` naming the rule, the
example and its origin. The pack's tests (`engine/tests/service/test_language_pack.py`)
load it, and so does every Tamil scan. A pack with a failing example therefore
cannot reach a translator.

In `ta-irv`, examples are real IRV verses. Where there are enough of them, they
are chosen from places the review reports also flagged. Where a shape has fewer
than twelve real occurrences, the builder derives an example from a real verse
and says so in `origin` ("derived from …").

## Project overrides

A project may narrow a bundled pack with
`<project>/.apps/translationCoreAI/language-packs/<pack>/overrides.json`:

```json
{ "rules": {
    "sandhi.vallinam.manner-adverb": { "inline": false },
    "sandhi.clitic.fused": { "enabled": false },
    "sandhi.vallinam.accusative": { "abstain": [ { "next": { "lexical": ["…"] }, "origin": "team decision" } ] }
} }
```

- Accepted: `enabled: false`, `inline: false`, and extra `abstain` entries.
- Refused and reported: anything that widens a rule. That means enabling a
  disabled rule, drawing a rule inline, or changing a pattern, severity,
  message or fix. Unknown rule ids and malformed abstains are refused the same
  way.
- A refusal does not discard the whole file. The acceptable parts still apply,
  and each refusal appears as a `Rule pack: …` entry in the status
  `limitations` (the panel's coverage notes).
- A no-op is not a refusal. For example, `inline: true` on a rule that is
  already inline changes nothing.

The overrides change the pack's fingerprint, which is part of the scan's
per-chapter cache key, so saving an override causes the affected chapters to be
rescanned.

## Inline and the gate

The benchmark gate (`scripts/language_qa_benchmark.py --gate`) requires an inline
rule to reach **90% strict precision**, unless the rule carries an
`inlineSignOff`. A signed-off rule instead must stay within **2 points** of the
`precisionStrict` it was signed off at. A sign-off with no recorded precision
fails the gate until one is measured. Every `ta-irv` வல்லினம் rule is signed off,
by the maintainer's instruction of 2026-09-24 (DECISIONS.md).

## `ta-irv@1.0.0`

| Rule | Replaces | Inline | Shape | Strict precision (2026-09-24) |
|---|---|---|---|---|
| `sandhi.vallinam.demonstrative` | B1 | yes, signed off | அந்த/இந்த/எந்த + bare hard consonant | 41.2% (80 findings) |
| `sandhi.vallinam.manner-adverb` | B1 | yes, signed off | அப்படி/இப்படி/எப்படி + bare | 15.4% (13) |
| `sandhi.vallinam.accusative` | B2 | yes, signed off | -ஐ accusative + bare; root nouns abstain | 55.0% (500) |
| `sandhi.vallinam.dative` | B2 | yes, signed off | -க்கு dative + bare; root nouns and house names abstain | 49.8% (396) |
| `sandhi.vallinam.wrong-consonant` | new | yes, signed off | linked with the wrong hard consonant | no findings in the benchmark books |
| `sandhi.clitic.fused` | new | no | manner adverb, -ஐ or -க்கு + தான்/கூட written apart | 0.0% (4) |
| `typo.divine-name.vowel-drop` | new | no | யெகோவவ for யெகோவாவ | 100% (11) |
| `typo.divine-name.dative-stem` | new | no | யெகோவாக்க (the dative is யெகோவாவுக்கு) | 69.2% (13) |
| `typo.suffix.dropped-tha` | new | no | -வற்கு for -வதற்கு | 100% (2) |
| `integrity.space-before-note-end` | new | no | space before `\f*` / `\x*` (raw) | 74.3% (74) |
| `integrity.digits-in-text` | new | disabled | digits in verse text: an IRV house form (Pass 3 §5) | — |

These precision figures measure agreement with the AI review, not accuracy
(`docs/LANGUAGE_QA_BENCHMARK.md`).

B1 and B2 share `legacyId: "tamil.vallinam-missing"`. Their finding ids, and so
their existing decisions, carry over. Their `ruleVersion` changed, though, so an
existing ignore comes back once for re-check. That is intended (DECISIONS.md,
"An ignore expires…").

## Rebuilding `ta-irv`

The pack is generated from the corpus, and the generated JSON is committed:

```powershell
engine\.venv\Scripts\python.exe scripts\build_ta_irv_pack.py `
  --irv-dir "C:\Users\Benz\Documents\IRV Tamil" `
  --reviews "D:\Claude Lab\Revant work\Claude outputs" "…\Philippians_Round2_QA_Issues.csv"
```

The builder computes every corpus-derived part of the pack:

- the abstains: house forms from the bare/doubled counts per trigger and stem
  (`MIN_CONTEXTS = 3`), and root nouns (a ை-word whose +யை form is attested; a
  க்கு-word whose -க்கில் or -க்குக்கு form is attested);
- the examples;
- the sign-offs.

After a rebuild, run `pytest tests/service/test_language_pack.py` and the
benchmark with `--gate`, and record the before and after numbers in
`docs/BUILD_LOG.md`. Editing a rule JSON by hand is allowed for a one-off fix, but
the next rebuild overwrites it. Put lasting changes in the builder.
