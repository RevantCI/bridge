"""Build the bundled `ta-irv` Language QA rule pack from the IRV corpus.

    python scripts/build_ta_irv_pack.py --irv-dir "C:/…/IRV Tamil" [--reviews DIR_OR_CSV …]

The rule DEFINITIONS below are hand-written: match shapes, messages, fixes,
and the reason for each abstain. The corpus supplies two things, and this
script is how they were derived, so either can be rebuilt and reviewed.

1. The exception lists. `notLexical` holds the -ஐ / -க்கு words IRV mostly
   writes bare before a hard consonant: at least MIN_CONTEXTS such contexts,
   with fewer doubled than bare. `prefix` abstains hold the next-word stems a
   demonstrative or manner adverb is mostly bare before (e.g. இந்த தேச-:
   bare 46, doubled 0). Each is recorded in the rule with its counts. These
   are the corpus's own majority forms, which is also the method the Round 2
   reviewers used ("doubled 178 times and bare 10 times").
2. Each rule's examples, which run as tests every time the pack loads:
   - incorrect examples are real IRV occurrences the rule flags, preferring
     those the Round 2 / Pass 3 review also flagged;
   - correct examples are real occurrences it must not flag (the doubled
     form, a house form, a clitic);
   - where the corpus has fewer than 10 real occurrences, the rest are
     derived from a real verse by one stated edit, and their `origin` says so.

The pack is then loaded through the real loader, which runs every example.
A build that produces a failing example fails here, not in the app.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))

import regex  # noqa: E402

from tc_ai_bridge import language_qa_benchmark as bench  # noqa: E402
from tc_ai_bridge.language_packs import loader  # noqa: E402
from tc_ai_bridge.language_qa import WORD, lift_inline_usfm, scan_text  # noqa: E402
from tc_ai_bridge.project_import import imported_verse_text, parse_scripture_file  # noqa: E402

PACK_DIR = REPO / "engine" / "tc_ai_bridge" / "language_packs" / "ta-irv"
PACK_VERSION = "1.0.0"
HARD = ["க", "ச", "த", "ப"]
MIN_CONTEXTS = 3
EXAMPLES = 12
DEMONSTRATIVES = ["அந்த", "இந்த", "எந்த"]
MANNER = ["அப்படி", "இப்படி", "எப்படி"]
# After a trigger these begin a clitic or a quotative, never a doubling
# site; the clitics get their own rule (sandhi.clitic.fused).
CLITICS_AND_QUOTATIVES = ["தான்", "கூட", "மட்டும்", "ஆவது", "போல", "என்று", "என", "எனும்"]
HOUSE_NAMES_IN_KKU = ["ஈசாக்கு", "ஏனோக்கு"]  # IRV_Pass3_Handoff.md §5: nominatives, not datives
MISSING_MESSAGE = ('Possible missing வல்லினம் at this word boundary: "{prev} {initial}..." normally takes '
                   '"{prev}{initial}் {initial}...". Verify before editing.')
MISSING_RATIONALE = '"{prev}" before a {initial}-initial word takes the linking {initial}்'
# Inline status needs strict benchmark precision >= 0.90 AND the maintainer's
# sign-off (layered-rules brief §3.3). On 2026-09-24 the maintainer signed
# off every வல்லினம் rule as inline below 0.90: "if it is a false positive
# the user will click Ignore, and the system will learn from its mistake".
# The benchmark measures agreement with a review that flagged only minority
# forms, not accuracy. The gate exempts a signed-off rule from the 0.90 floor,
# but still fails it if its precision falls more than 2 points below the
# value recorded here. Values: the strict precision measured when signed off.
SIGN_OFF_REASON = ("Maintainer sign-off 2026-09-24: keep all வல்லினம் rules inline; false positives are "
                   "handled by Ignore and learned from (Phase 6). Precision is agreement with the "
                   "minority-form AI review, not verified accuracy.")
SIGN_OFF = {rule_id: {"by": "maintainer (session of 2026-09-24)", "date": "2026-09-24",
                      "reason": SIGN_OFF_REASON, "precisionStrict": precision}
            for rule_id, precision in {
                # Measured by scripts/language_qa_benchmark.py on 2026-09-24 (pack 1.0.0).
                "sandhi.vallinam.demonstrative": 0.4125,
                "sandhi.vallinam.manner-adverb": 0.1538,
                "sandhi.vallinam.accusative": 0.55,
                "sandhi.vallinam.dative": 0.4975,
                # No finding in any reviewed book yet: the gate asks for a
                # value once it has one.
                "sandhi.vallinam.wrong-consonant": None,
            }.items()}
PROPER_NOUNS = {"next": {"listRef": "housestyle.properNouns"},
                "origin": "A proper noun after the trigger: the project's house-style name list (Phase 6). "
                          "Empty until then; the names adapter's majority forms were evaluated as a seed "
                          "and rejected (BUILD_LOG, Phase 3)."}


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


RAW_VERSES: list[tuple[str, str, str, str]] = []  # (book, chapter, verse, raw text), for raw-text rules


def corpus(irv_dir: Path) -> list[tuple[str, str, str, str]]:
    """(book, chapter, verse, visible text) for every liftable IRV verse."""
    verses = []
    for sfm in sorted(irv_dir.glob("*.SFM")):
        book = parse_scripture_file(sfm)
        for chapter, items in book.chapters.items():
            for verse, raw in items.items():
                text = imported_verse_text(raw)
                lifted, _ = lift_inline_usfm(text)
                if lifted is not None and "\\" not in lifted.visible:
                    verses.append((book.book_id, chapter, verse, lifted.visible))
                    RAW_VERSES.append((book.book_id, chapter, verse, text))
    return verses


NOTE = regex.compile(r"\\([fx])\s.*?\\\1\*", regex.DOTALL)


def raw_note_examples(pack, rule_id: str) -> dict[str, list]:
    """A raw-text rule's examples: the word before a note plus the whole note,
    so the snippet stays well-formed markup."""
    incorrect, correct = [], []
    for book, chapter, verse, text in RAW_VERSES:
        for m in NOTE.finditer(text):
            before = regex.search(r"\S+\s*$", text[:m.start()])
            snippet = (before.group() if before else "") + m.group()
            findings = [f for f in scan_text(snippet, book="x", chapter="1", verse="1", tamil=True, pack=pack)["findings"]
                        if f["ruleId"] == f"ta-irv/{rule_id}"]
            item = {"text": snippet, "origin": f"{book.upper()} {chapter}:{verse}"}
            if findings and len(incorrect) < 40:
                incorrect.append({**item, "span": findings[0]["originalText"], "fix": findings[0]["suggestedReplacement"]})
            elif not findings and len(correct) < 40:
                correct.append(item)
    return {"incorrect": spread(incorrect, EXAMPLES), "correct": spread(correct, EXAMPLES)}


def root_nouns(verses) -> tuple[list[str], list[str]]:
    """Words whose ending is part of the noun itself, not a case suffix, judged
    by Tamil morphology as the corpus attests it:
    - a root in -ஐ takes -யை as its own accusative (படை -> படையை,
      மலை -> மலையை); a real accusative never takes a second one (no அதையை);
    - a root in -க்கு has a locative in -க்கில் or a dative -க்குக்கு
      (கிழக்கு -> கிழக்கில்); a real dative has neither (no எனக்கில்)."""
    tokens = {nfc(m.group()) for _, _, _, text in verses for m in WORD.finditer(text)}
    acc = sorted(t for t in tokens if t.endswith("ை") and t + "யை" in tokens)
    dat = sorted(t for t in tokens if t.endswith("க்கு") and (t[:-1] + "ில்" in tokens or t + "க்கு" in tokens))
    return acc, dat


def pair_stats(verses):
    doubled, bare = collections.Counter(), collections.Counter()
    pair_bare, pair_doubled = collections.Counter(), collections.Counter()
    for _, _, _, text in verses:
        words = list(WORD.finditer(text))
        for a, b in zip(words, words[1:]):
            if not text[a.end():b.start()].isspace():
                continue
            prev, nxt = nfc(a.group()), nfc(b.group())
            if nxt[:1] not in HARD:
                continue
            base, link = loader._split(prev)
            stem = nxt[:3]
            if link == nxt[0]:
                doubled[base] += 1
                pair_doubled[(base, stem)] += 1
            elif link is None:
                bare[base] += 1
                pair_bare[(base, stem)] += 1
    return doubled, bare, pair_bare, pair_doubled


def bare_majority(doubled, bare, ending: str) -> list[dict]:
    rows = []
    for base in set(doubled) | set(bare):
        total = doubled[base] + bare[base]
        if base.endswith(ending) and total >= MIN_CONTEXTS and doubled[base] < bare[base]:
            rows.append({"word": base, "bare": bare[base], "doubled": doubled[base]})
    return sorted(rows, key=lambda r: (-r["bare"], r["word"]))


def stem_abstains(triggers, pair_bare, pair_doubled) -> list[dict]:
    out = []
    for trigger in triggers:
        stems = sorted(
            (stem for (base, stem) in set(pair_bare) | set(pair_doubled) if base == trigger
             and pair_bare[(base, stem)] + pair_doubled[(base, stem)] >= MIN_CONTEXTS
             and pair_bare[(base, stem)] > pair_doubled[(base, stem)]),
            key=lambda s: (-pair_bare[(trigger, s)], s))
        if stems:
            counts = ", ".join(f"{s}- bare {pair_bare[(trigger, s)]}/doubled {pair_doubled[(trigger, s)]}" for s in stems)
            out.append({"prev": {"lexical": [trigger]}, "next": {"prefix": stems},
                        "origin": f"IRV corpus house form after {trigger}: {counts}"
                                  + (" (also IRV_Pass3_Handoff.md §5)" if "தேச" in stems else "")})
    return out


def definitions(doubled, bare, pair_bare, pair_doubled, acc_roots, dat_roots) -> list[dict]:
    accusative_exceptions = bare_majority(doubled, bare, "ை")
    dative_exceptions = bare_majority(doubled, bare, "க்கு")
    acc_words = sorted({r["word"] for r in accusative_exceptions} | set(acc_roots))
    dat_words = sorted({r["word"] for r in dative_exceptions} | set(dat_roots) | set(HOUSE_NAMES_IN_KKU))
    trigger_base = "^(?:" + "|".join(DEMONSTRATIVES + MANNER) + ")$|ை$|க்கு$"
    clitic_base = "^(?:" + "|".join(MANNER) + ")$|ை$|க்கு$"
    common_abstain = [
        {"next": {"lexical": CLITICS_AND_QUOTATIVES},
         "origin": "Clitic or quotative after the trigger: never the spaced doubled form; see sandhi.clitic.fused."},
        PROPER_NOUNS,
    ]

    def missing(rule_id, title_ta, title_en, prev, extra_abstain, provenance, confidence="medium"):
        return {
            "id": rule_id, "version": 1, "legacyId": "tamil.vallinam-missing",
            "category": "sandhi", "severity": "medium", "confidence": confidence, "inline": False,
            "title": {"ta": title_ta, "en": title_en},
            "message": {"en": MISSING_MESSAGE}, "rationale": MISSING_RATIONALE,
            "match": {"type": "token-context", "prev": prev, "gap": "whitespace",
                      "next": {"initial": HARD}, "link": "none"},
            "abstain": common_abstain + extra_abstain, "fix": {"type": "insert-link"},
            "provenance": provenance,
        }

    return [
        missing("sandhi.vallinam.demonstrative", "வல்லினம் மிகுதல் — சுட்டு", "Vallinam doubling after a demonstrative",
                {"lexical": DEMONSTRATIVES}, stem_abstains(DEMONSTRATIVES, pair_bare, pair_doubled),
                "B1 (BUILD_LOG 2026-09-22). IRV doubles after அந்த 89%, இந்த 84%, எந்த 86% of hard-initial contexts."),
        missing("sandhi.vallinam.manner-adverb", "வல்லினம் மிகுதல் — விதம்", "Vallinam doubling after a manner adverb",
                {"lexical": MANNER}, stem_abstains(MANNER, pair_bare, pair_doubled),
                "B2 (BUILD_LOG 2026-09-23). IRV doubles after அப்படி 97%, இப்படி 92%, எப்படி 87%."),
        missing("sandhi.vallinam.accusative", "வல்லினம் மிகுதல் — இரண்டாம் வேற்றுமை", "Vallinam doubling after the accusative -ஐ",
                {"suffix": "ை$", "minLength": 3, "notLexical": acc_words}, [],
                "Generalises B4 (five pronouns) to the -ஐ ending, as the layered-rules brief asks. "
                f"notLexical ({len(acc_words)} words) is two corpus tests: (1) root nouns, {len(acc_roots)} words "
                "whose -ஐ is part of the noun, shown by their own accusative in -யை (படை -> படையை, மலை -> "
                "மலையை, கை -> கையை); a real accusative never takes a second (no அதையை); (2) the "
                f"{len(accusative_exceptions)} -ஐ words IRV writes bare in most of at least {MIN_CONTEXTS} "
                "hard-initial contexts (bare/doubled): "
                + "; ".join(f"{r['word']} {r['bare']}/{r['doubled']}" for r in accusative_exceptions[:40])
                + ("; …" if len(accusative_exceptions) > 40 else "") + ". IRV overall: -ஐ doubled 14,496, bare 3,082."),
        missing("sandhi.vallinam.dative", "வல்லினம் மிகுதல் — நான்காம் வேற்றுமை", "Vallinam doubling after the dative -க்கு",
                {"suffix": "க்கு$", "minLength": 4, "notLexical": dat_words}, [],
                "Generalises B3 (three datives) to the -க்கு ending. notLexical is (1) root nouns and names in "
                f"-க்கு, {len(dat_roots)} words shown by a locative in -க்கில் or a dative -க்குக்கு "
                "(கிழக்கு -> கிழக்கில், விளக்கு, வழக்கு, ஈசாக்கு, அபிமெலேக்கு); a real dative has "
                "neither (no எனக்கில்); (2) IRV's bare-majority -க்கு words (bare/doubled): "
                + "; ".join(f"{r['word']} {r['bare']}/{r['doubled']}" for r in dative_exceptions)
                + "; (3) the names IRV_Pass3_Handoff.md §5 lists as nominatives. "
                "-ற்கு is a different ending and is not matched."),
        {
            "id": "sandhi.vallinam.wrong-consonant", "version": 1,
            "category": "sandhi", "severity": "medium", "confidence": "medium", "inline": False,
            "title": {"ta": "வல்லினம் — தவறான மெய்", "en": "Wrong linking consonant"},
            "message": {"en": 'The linking "{link}்" does not match the following "{initial}...": '
                              '"{prev}{initial}் {initial}..." is expected. Verify before editing.'},
            "rationale": 'The linking consonant repeats the next word\'s first consonant ({initial})',
            "match": {"type": "token-context", "gap": "whitespace", "link": "mismatch",
                      "prev": {"regex": trigger_base, "notLexical": sorted(set(acc_words) | set(dat_words))},
                      "next": {"initial": HARD}},
            "abstain": common_abstain, "fix": {"type": "replace-link"},
            "provenance": "Only after a base the வல்லினம் rules cover (a demonstrative, a manner adverb, "
                          "-ஐ or -க்கு). In IRV every other 'wrong link' is a name ending in a consonant "
                          "(காத் Gad, மோவாப் Moab), which this must never touch.",
        },
        {
            "id": "sandhi.clitic.fused", "version": 1,
            "category": "word-joining", "severity": "low", "confidence": "low", "inline": False,
            "title": {"ta": "இடைச்சொல் — சேர்த்து எழுதுதல்", "en": "Clitic written apart"},
            "message": {"en": '"{word} {next}" is normally written as one word, "{fix}". Verify before editing.'},
            "rationale": "தான் / கூட are clitics: fused, with the linking consonant",
            "match": {"type": "token-context", "gap": "whitespace", "link": "any",
                      "prev": {"regex": clitic_base, "notLexical": sorted(set(acc_words) | set(dat_words))},
                      "next": {"lexical": ["தான்", "கூட"]}},
            "abstain": [], "fix": {"type": "fuse-link"},
            "provenance": "Layered-rules brief §3.3: shipped enabled, low confidence, panel-only; never the "
                          "spaced form அதைத் தான். Its fate is the project's to decide through decisions "
                          "(Phase 6 learner). Only after a manner adverb, -ஐ or -க்கு. Spaced கூட after "
                          "the comitative -ஓடு (அவனோடு கூட) is the postposition 'with' and is not matched.",
        },
        {
            "id": "typo.divine-name.vowel-drop", "version": 1,
            "category": "typo", "severity": "high", "confidence": "high", "inline": False,
            "title": {"ta": "யெகோவா — நெடில் விடுபட்டது", "en": "Divine name: dropped long vowel"},
            "message": {"en": '"{span}" drops the ா of யெகோவா; "{fix}" is expected. Verify before editing.'},
            "rationale": "யெகோவா keeps its long ா before the case ending",
            "match": {"type": "regex", "on": "visible", "pattern": "யெகோவவ"},
            "fix": {"type": "replace", "text": "யெகோவாவ"},
            "provenance": "Known IRV defect shape carried over from 14 books of Round 2. IRV: யெகோவவ 11, யெகோவாவ 3,488.",
        },
        {
            "id": "typo.divine-name.dative-stem", "version": 1,
            "category": "typo", "severity": "high", "confidence": "high", "inline": False,
            "title": {"ta": "யெகோவா — நான்காம் வேற்றுமை அடி", "en": "Divine name: dative stem"},
            "message": {"en": '"{span}" builds the dative without the -வு- stem; "{fix}" is expected. Verify before editing.'},
            "rationale": "The dative of யெகோவா is யெகோவாவுக்கு",
            "match": {"type": "regex", "on": "visible", "pattern": "யெகோவாக்க"},
            "fix": {"type": "replace", "text": "யெகோவாவுக்க"},
            "provenance": "Known IRV defect shape (Round 2). IRV: யெகோவாக்க 13.",
        },
        {
            "id": "typo.suffix.dropped-tha", "version": 1,
            "category": "typo", "severity": "medium", "confidence": "high", "inline": False,
            "title": {"ta": "-வதற்கு — த விடுபட்டது", "en": "Dropped த in -வதற்கு"},
            "message": {"en": '"{span}" drops the த of -வதற்கு; "{fix}" is expected. Verify before editing.'},
            "rationale": "The purposive verbal noun is -வதற்கு",
            # A verb stem (two or more letters) before -வற்கு, then the end of the
            # word. அவற்கு/இவற்கு-type pronoun forms have a one-letter stem.
            "match": {"type": "regex", "on": "visible",
                      "pattern": r"(?<![\p{L}\p{M}])(?P<span>(?P<stem>\p{L}[\p{L}\p{M}]{2,}?)வற்கு)(?![\p{L}\p{M}])"},
            "fix": {"type": "expand", "template": r"\g<stem>வதற்கு"},
            "provenance": "Known IRV defect shape (Round 2). IRV: 2 real occurrences (நடத்துவற்கு, செய்வற்கு), "
                          "each with its -வதற்கு form attested; -வதற்கு 328.",
        },
        {
            "id": "integrity.digits-in-text", "version": 1, "enabled": False,
            "category": "typo", "layer": "integrity", "severity": "low", "confidence": "low", "inline": False,
            "title": {"ta": "எண்கள் வசனத்தில்", "en": "Digits in verse text"},
            "message": {"en": 'Digits "{span}" in verse text; check the project\'s numeral policy.'},
            "rationale": "Numeral policy",
            "match": {"type": "regex", "on": "visible", "pattern": r"\p{Nd}+"},
            "provenance": "DISABLED: the Pass 3 reviewers confirmed digits in verse text are IRV house form "
                          "(IRV_Pass3_Handoff.md §5), and IRV has 2,423 of them; enabled, it would also crowd "
                          "the book finding cap. A project override cannot enable it (overrides only narrow): "
                          "enabling is a pack change for the maintainer.",
        },
        {
            "id": "integrity.space-before-note-end", "version": 1,
            "category": "spacing", "severity": "low", "confidence": "medium", "inline": False,
            "title": {"ta": "குறிப்பு முடிவுக்கு முன் இடைவெளி", "en": "Space before a note's end marker"},
            "message": {"en": "Space before the closing note marker; the note's text carries a trailing space."},
            "rationale": "No space before \\f* or \\x*",
            "match": {"type": "regex", "on": "raw", "pattern": r"(?P<span> +)\\[fx]\*"},
            "fix": {"type": "replace", "text": ""},
            "provenance": "Layered-rules brief §3.4 (integrity.space-before-footnote-end), extended to \\x*. "
                          "Matched on the raw text, since notes are lifted out of the visible text. IRV: 214.",
        },
    ]


def window(text: str, start: int, end: int, words: int = 2) -> str:
    """The span with up to `words` words either side: a real snippet of the verse."""
    tokens = list(regex.finditer(r"\S+", text))
    first = next(i for i, t in enumerate(tokens) if t.end() > start)
    last = next(i for i, t in enumerate(tokens) if t.end() >= end)
    lo, hi = max(0, first - words), min(len(tokens) - 1, last + words)
    return text[tokens[lo].start():tokens[hi].end()]


def spread(items: list, count: int) -> list:
    if len(items) <= count:
        return items
    step = len(items) / count
    return [items[int(i * step)] for i in range(count)]


def reviewed_places(paths: list[str]) -> set[tuple[str, str, str]]:
    if not paths:
        return set()
    files = []
    for value in paths:
        path = Path(value)
        files.extend(sorted(path.glob("*_Issues.csv")) if path.is_dir() else [path])
    return {(r.book, r.chapter, r.verse) for r in bench.load_review_rows(files) if r.label in {"positive", "maybe"}}


def choose_examples(pack, verses, reviewed) -> dict[str, dict[str, list]]:
    flagged = collections.defaultdict(list)
    for book, chapter, verse, text in verses:
        for f in scan_text(text, book=book, chapter=chapter, verse=verse, tamil=True, pack=pack)["findings"]:
            if f["ruleId"].startswith("ta-irv/"):
                flagged[f["ruleId"].split("/", 1)[1]].append((book, chapter, verse, text, f))
    out = {}
    for rule in pack.rules:
        if not rule.enabled:
            out[rule.id] = {"incorrect": [], "correct": []}
            continue
        hits = flagged.get(rule.id, [])
        hits.sort(key=lambda h: ((h[0], h[1], h[2]) not in reviewed, h[0], int(h[1]), h[2]))
        chosen = spread([h for h in hits if (h[0], h[1], h[2]) in reviewed], EXAMPLES // 2)
        chosen += [h for h in spread(hits, EXAMPLES) if h not in chosen][:EXAMPLES - len(chosen)]
        incorrect = []
        for book, chapter, verse, text, finding in chosen:
            snippet = window(text, finding["start"], finding["end"])
            incorrect.append({"text": snippet, "span": finding["originalText"],
                              "fix": finding["suggestedReplacement"],
                              "origin": f"{book.upper()} {chapter}:{verse}"
                                        + (" (also in the review reports)" if (book, chapter, verse) in reviewed else "")})
        out[rule.id] = {"incorrect": incorrect, "correct": correct_examples(rule, verses, flagged)}
    return out


def correct_examples(rule, verses, flagged) -> list[dict]:
    """Real snippets the rule must not flag."""
    found = []
    if rule.match_type == "token-context":
        for book, chapter, verse, text in verses:
            words = list(WORD.finditer(text))
            for a, b in zip(words, words[1:]):
                if not text[a.end():b.start()].isspace():
                    continue
                prev, nxt = nfc(a.group()), nfc(b.group())
                base, link = loader._split(prev)
                if rule.prev is not None and not rule.prev.matches(base, {}):
                    continue
                shape = None
                if rule.id == "sandhi.clitic.fused":
                    if prev.endswith(("த்தான்", "க்கூட")):
                        shape = "fused clitic"
                elif nxt[:1] in HARD and link == nxt[:1] and rule.link != "any":
                    shape = "correctly linked"
                elif nxt[:1] in HARD and link is None and any(
                        (x.prev is None or x.prev.matches(base, {})) and (x.next is None or x.next.matches(nxt, {}))
                        for x in rule.abstain if x.origin.startswith(("IRV corpus", "Clitic"))):
                    shape = "house form"
                if shape:
                    found.append((shape, book, chapter, verse, window(text, a.start(), b.end(), 1)))
        if rule.id == "sandhi.clitic.fused":
            found = []
            for book, chapter, verse, text in verses:
                for m in regex.finditer(r"(?:அப்படி|இப்படி|எப்படி|\p{L}[\p{L}\p{M}]*ை|\p{L}[\p{L}\p{M}]*க்கு)(?:த்தான்|க்கூட)(?![\p{L}\p{M}])", text):
                    found.append(("fused clitic", book, chapter, verse, window(text, m.start(), m.end(), 1)))
                for m in regex.finditer(r"\p{L}[\p{L}\p{M}]*ஓடு கூட(?![\p{L}\p{M}])", text):
                    found.append(("comitative கூட", book, chapter, verse, window(text, m.start(), m.end(), 1)))
    else:
        corrected = {"typo.divine-name.vowel-drop": r"யெகோவாவ[\p{L}\p{M}]*",
                     "typo.divine-name.dative-stem": r"யெகோவாவுக்கு",
                     "typo.suffix.dropped-tha": r"\p{L}[\p{L}\p{M}]*வதற்கு",
                     "integrity.space-before-note-end": None}[rule.id]
        if corrected:
            for book, chapter, verse, text in verses:
                m = regex.search(corrected, text)
                if m:
                    found.append(("correct form", book, chapter, verse, window(text, m.start(), m.end(), 1)))
        else:
            return []  # raw-text rules: raw_note_examples
    by_shape = collections.defaultdict(list)
    for item in found:
        by_shape[item[0]].append(item)
    # Round-robin over shapes (correctly linked, house form, …) so each is
    # represented and the total reaches EXAMPLES where the corpus allows.
    queues = [spread(items, EXAMPLES * 2) for _, items in sorted(by_shape.items())]
    picked = []
    while any(queues) and len(picked) < EXAMPLES * 2:
        for queue in queues:
            if queue:
                picked.append(queue.pop(0))
    examples = []
    seen = set()
    for shape, book, chapter, verse, snippet in picked:
        if snippet in seen:
            continue
        seen.add(snippet)
        origin = f"{book.upper()} {chapter}:{verse} ({shape})" if book else f"constructed ({shape})"
        examples.append({"text": snippet, "origin": origin})
    return examples[:max(EXAMPLES, 10)]


def top_up(examples: dict[str, list], rule_id: str, verses) -> None:
    """Where the corpus has fewer than 10 real incorrect occurrences, derive
    the rest from real verses by one stated edit."""
    incorrect = examples["incorrect"]
    if len(incorrect) >= 10:
        return
    edits = {
        "typo.suffix.dropped-tha": (r"(\p{L}[\p{L}\p{M}]{2,}?)வதற்கு(?![\p{L}\p{M}])", r"\1வற்கு", "த removed from -வதற்கு"),
        "sandhi.vallinam.wrong-consonant": None,
        "sandhi.clitic.fused": (r"(அப்படி|இப்படி|எப்படி|\p{L}[\p{L}\p{M}]*ை|\p{L}[\p{L}\p{M}]*க்கு)த்தான்(?![\p{L}\p{M}])",
                                r"\1த் தான்", "fused தான் written apart"),
        "typo.divine-name.vowel-drop": (r"யெகோவாவ", "யெகோவவ", "ா removed"),
        "typo.divine-name.dative-stem": (r"யெகோவாவுக்க", "யெகோவாக்க", "வு removed"),
        "integrity.space-before-note-end": None,
    }.get(rule_id)
    if rule_id == "sandhi.vallinam.wrong-consonant":
        swap = {"க": "ச", "ச": "த", "த": "ப", "ப": "க"}
        pattern = regex.compile(r"(?<![\p{L}\p{M}])(அந்த|இந்த|எந்த|அப்படி|இப்படி|எப்படி|\p{L}[\p{L}\p{M}]*ை)([கசதப])் ([கசதப])")
        for book, chapter, verse, text in verses:
            m = pattern.search(text)
            if not m or m.group(2) != m.group(3):
                continue
            wrong = f"{m.group(1)}{swap[m.group(2)]}் "
            snippet = window(text, m.start(), m.end() + 4, 1).replace(m.group(0), wrong + m.group(3), 1)
            incorrect.append({"text": snippet, "span": None, "fix": None,
                              "origin": f"derived from {book.upper()} {chapter}:{verse} (linking consonant changed)"})
            if len(incorrect) >= 10:
                break
        return
    if rule_id == "integrity.space-before-note-end":
        return
    if edits is None:
        return
    pattern, repl, how = edits
    for book, chapter, verse, text in verses:
        m = regex.search(pattern, text)
        if not m:
            continue
        snippet = window(text, m.start(), m.end(), 1)
        derived = regex.sub(pattern, repl, snippet, count=1)
        if derived == snippet or any(e["text"] == derived for e in incorrect):
            continue
        incorrect.append({"text": derived, "span": None, "fix": None,
                          "origin": f"derived from {book.upper()} {chapter}:{verse} ({how})"})
        if len(incorrect) >= 10:
            break


def fill_spans(pack, rule_id, examples) -> None:
    """Derived examples get their span and fix from the rule itself, then run
    through the loader's example check like every other example."""
    for example in examples["incorrect"]:
        if example.get("span") is None:
            findings = [f for f in scan_text(example["text"], book="x", chapter="1", verse="1", tamil=True, pack=pack)["findings"]
                        if f["ruleId"] == f"ta-irv/{rule_id}"]
            if not findings:
                raise SystemExit(f"{rule_id}: derived example not flagged: {example}")
            example["span"] = findings[0]["originalText"]
            example["fix"] = findings[0]["suggestedReplacement"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--irv-dir", required=True, type=Path)
    parser.add_argument("--reviews", nargs="*", default=[])
    args = parser.parse_args()
    verses = corpus(args.irv_dir)
    print(f"{len(verses)} verses", file=sys.stderr)
    rules = definitions(*pair_stats(verses), *root_nouns(verses))
    for rule in rules:
        if rule["id"] in SIGN_OFF:
            rule["inline"] = True
            rule["inlineSignOff"] = SIGN_OFF[rule["id"]]
    meta = {"pack": "ta-irv", "version": PACK_VERSION, "language": "ta", "script": "Taml",
            "description": "Tamil IRV rule pack: sandhi (வல்லினம்) shape rules and known IRV defect shapes. "
                           "Built by scripts/build_ta_irv_pack.py from the IRV corpus; see docs/LANGUAGE_QA_RULE_PACK.md.",
            "rules": [f"rules/{rule['id']}.json" for rule in rules]}
    pack = loader._build(meta, rules)  # no examples yet: they are chosen with this pack
    examples = choose_examples(pack, verses, reviewed_places(args.reviews))
    for rule in rules:
        rule_examples = examples[rule["id"]]
        if rule["match"].get("on") == "raw" and rule.get("enabled", True):
            rule_examples = examples[rule["id"]] = raw_note_examples(pack, rule["id"])
        top_up(rule_examples, rule["id"], verses)
        fill_spans(pack, rule["id"], rule_examples)
        rule["examples"] = rule_examples
        print(f"{rule['id']}: {len(rule_examples['incorrect'])} incorrect, {len(rule_examples['correct'])} correct",
              file=sys.stderr)
    (PACK_DIR / "rules").mkdir(parents=True, exist_ok=True)
    for old in (PACK_DIR / "rules").glob("*.json"):
        old.unlink()
    for rule in rules:
        (PACK_DIR / "rules" / f"{rule['id']}.json").write_text(
            json.dumps(rule, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    (PACK_DIR / "pack.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8", newline="\n")
    loader.default_pack.cache_clear()
    loader.load_pack("ta-irv")  # runs every example; raises on the first failure
    print("pack built and every example passes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
