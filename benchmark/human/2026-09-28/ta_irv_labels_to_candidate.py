#!/usr/bin/env python3
"""Turn the returned ta-irv reviewer workbook into a candidate rule-pack update.

    python ta_irv_labels_to_candidate.py ta-irv_reviewer_workbook.xlsx [--out ta-irv_candidate]

Reads the reviewer's dropdown verdicts (sheets 1A, 1B, 2, 3, 4) joined to the hidden
`_data` sheet, and writes, in --out:

  human_labels.jsonl          every labelled row with a machine verdict code (ground truth)
  summary.json / summary.md   human precision per rule, recall check per abstain class,
                              inline recommendation (>= 0.90 human precision)
  labelled/<bucket>.jsonl     fixtures in engine/tests/fixtures/language_qa/labelled/ format
                              (expect = confirmed findings; maybe = house forms; negative = false alarms)
  housestyle_import.json      Layer 3: word-in-project abstains + properNouns, provenance "curated",
                              loadable with the housestyle.import RPC / bundled as a seed
  lexicon_curated.csv         Layer 2: confirmed misspellings in Round-2 Issues CSV shape,
                              for scripts/build_tamil_lexicon.py --curated
  pack_changes.md             Layer 1: concrete edits to ta-irv rules (notLexical add/remove,
                              -ற்கு, clitic policy, demonstrative house forms, repeated-word)

No file under the repo is modified; the coding agent applies pack_changes.md.
"""
from __future__ import annotations
import argparse, collections, csv, json, re, sys, unicodedata
from pathlib import Path
from openpyxl import load_workbook

nfc = lambda s: unicodedata.normalize("NFC", s or "")
BOOK = {"ஆதியாகமம்": "GEN", "சங்கீதம்": "PSA", "யோவான்": "JHN"}
RULE_BY_LABEL = {
    "வல்லினம்: -ஐ (இரண்டாம் வேற்றுமை)": "ta-irv/sandhi.vallinam.accusative",
    "வல்லினம்: -க்கு (நான்காம் வேற்றுமை)": "ta-irv/sandhi.vallinam.dative",
    "வல்லினம்: அந்த/இந்த/எந்த": "ta-irv/sandhi.vallinam.demonstrative",
    "வல்லினம்: அப்படி/இப்படி/எப்படி": "ta-irv/sandhi.vallinam.manner-adverb",
}
# verdict prefix -> code
V1A = {"சரி — மிகல் தேவை; பரிந்துரை சரி": "TP", "சரி — மிகல் தேவை; ஆனால் வேறு வடிவம்": "TP_OTHER_FIX",
       "தவறு — இது வேற்றுமை உருபு அல்ல": "FP_ROOT", "தவறு — வேற்றுமை உருபுதான்; ஆனால் இங்கு மிகல் வேண்டாம்": "FP_NODOUBLE",
       "IRV வழக்கு": "HOUSE", "தெரியவில்லை": "UNSURE"}
V1B = {"மிகல் தேவை — கருவி விட்டுவிட்டது": "MISSED", "மிகல் தேவையில்லை": "CORRECT_SKIP", "IRV வழக்கு": "HOUSE", "தெரியவில்லை": "UNSURE"}
V2 = {"சரி — பிழை; பரிந்துரை 1 சரி": "TP1", "சரி — பிழை; பரிந்துரை 2 அல்லது 3 சரி": "TP23",
      "சரி — பிழை; ஆனால் சரியான வடிவம் வேறு": "TP_OTHER_FIX", "தவறு — சொல் சரியானது": "FP",
      "தவறு — ஆட்பெயர்": "FP_NAME", "தெரியவில்லை": "UNSURE"}
V4 = {"சரி — பிழை": "TP", "தவறு — பிழை இல்லை": "FP", "தெரியவில்லை": "UNSURE"}
V3W = {"வேற்றுமை உருபு — மிகல் தேவை": "CASE_FORM_FLAG", "வேர்ச்சொல் / பெயர்": "ROOT_KEEP",
       "வேற்றுமை உருபுதான் — ஆனால் IRV வழக்காக": "HOUSE", "தெரியவில்லை": "UNSURE"}
V3C = {"ஒட்டி எழுத": "FUSED", "பிரித்து, மிகலுடன்": "SPACED_DOUBLED", "பிரித்து, மிகலின்றி": "SPACED_BARE", "தெரியவில்லை": "UNSURE"}
V3D = {"மிகல் தேவை": "FLAG", "IRV வழக்கு": "HOUSE", "தெரியவில்லை": "UNSURE"}

def code(v, table):
    v = nfc(str(v or "")).strip()
    if not v: return None
    for k, c in table.items():
        if v.startswith(nfc(k)): return c
    return "UNKNOWN:" + v

def clean(display: str) -> str:
    return display.replace("⟦", "").replace("⟧", "")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("workbook"); ap.add_argument("--out", default="ta-irv_candidate")
    a = ap.parse_args(); out = Path(a.out); (out / "labelled").mkdir(parents=True, exist_ok=True)
    wb = load_workbook(a.workbook, data_only=True)
    data = {}
    for r in wb["_data"].iter_rows(min_row=2, values_only=True):
        if not r[0]: continue
        data[r[0]] = dict(zip(["id", "sheet", "cls", "rule", "fid", "book", "ch", "v", "start", "end", "original", "prev", "next", "suggestions"], r))
        if isinstance(data[r[0]]["suggestions"], str) and data[r[0]]["suggestions"].startswith("["):
            data[r[0]]["suggestions"] = json.loads(data[r[0]]["suggestions"])
    labels, fixtures = [], collections.defaultdict(list)
    house_entries, proper_nouns, curated_rows = [], collections.OrderedDict(), []
    name_contexts, nodouble_next, root_fp_words = [], collections.Counter(), []
    notlex_add, notlex_remove = collections.defaultdict(set), collections.defaultdict(set)
    pack_notes = collections.defaultdict(list)

    def ev(d): return {"book": d["book"], "chapter": str(d["ch"]), "verse": str(d["v"])}

    # ---- 1A flagged sandhi ----
    for r in wb["1A சந்தி கண்டறிந்தவை"].iter_rows(min_row=2, values_only=True):
        rid, rule_l, _b, _c, _v, display, original, suggestion, verdict, is_name, fix_other, note = r[:12]
        if not rid: continue
        d = data[rid]; c = code(verdict, V1A); prev = nfc(original).split()[0] if original else ""
        nxt = nfc(original).split()[-1] if original and len(nfc(original).split()) > 1 else ""
        labels.append({**d, "kind": "flagged", "verdict": c, "nextIsName": nfc(is_name) == "ஆம்", "correctForm": nfc(fix_other), "note": nfc(note)})
        if c is None or c == "UNSURE": continue
        text = clean(display)
        if c in ("TP", "TP_OTHER_FIX"):
            fixtures["sandhi"].append({"text": text, "origin": f"{BOOK[_b]} {_c}:{_v} (human review 2026)",
                                       "expect": [{"ruleId": d["rule"], "category": "sandhi", "span": nfc(original), "fix": nfc(fix_other) or nfc(suggestion)}]})
        elif c == "HOUSE":
            fixtures["sandhi"].append({"text": text, "origin": f"{BOOK[_b]} {_c}:{_v} (human review 2026)", "expect": [],
                                       "maybe": [{"span": nfc(original), "fix": nfc(suggestion), "reason": "reviewer: IRV house form, accepted bare"}]})
            nodouble_next[nxt[:3]] += 1
        else:  # FP_ROOT / FP_NODOUBLE
            fixtures["sandhi"].append({"text": text, "origin": f"{BOOK[_b]} {_c}:{_v} (human review 2026)", "expect": [],
                                       "negative": [{"span": nfc(original), "ruleId": d["rule"], "reason": c}]})
            if c == "FP_ROOT": notlex_add[d["rule"]].add(prev); root_fp_words.append(prev)
            if c == "FP_NODOUBLE" and nxt: nodouble_next[nxt[:3]] += 1
        if nfc(is_name) == "ஆம்" and nxt: name_contexts.append({"pair": nfc(original), "verdict": c, "book": BOOK[_b], "ref": f"{_c}:{_v}"})

    # ---- 1B abstained ----
    for r in wb["1B சந்தி விடப்பட்டவை"].iter_rows(min_row=2, values_only=True):
        rid, cls_l, _b, _c, _v, display, pair, verdict, is_name, fix_other, note = r[:11]
        if not rid: continue
        d = data[rid]; c = code(verdict, V1B)
        labels.append({**d, "kind": "abstained", "verdict": c, "nextIsName": nfc(is_name) == "ஆம்", "correctForm": nfc(fix_other), "note": nfc(note)})
        if c is None or c == "UNSURE": continue
        if c == "MISSED":
            fixed = nfc(fix_other); prev_w = nfc(d["prev"])
            # A correction that fuses the pair (compound) or rewrites the first word (a different defect,
            # e.g. a split word) is NOT evidence that prev is a case form: report it separately.
            fixed_first = fixed.split()[0] if fixed else ""
            keeps_prev = (not fixed) or (len(fixed.split()) > 1 and fixed_first[:-2] == prev_w and fixed_first.endswith("்"))
            if not keeps_prev:
                pack_notes["other-defect"].append(f"{BOOK[_b]} {_c}:{_v} «{nfc(d['original'])}» → {fixed}  (not a case-suffix finding: " + ("compound/fused word" if len(fixed.split()) == 1 else "first word rewritten") + ")")
                fixtures["sandhi"].append({"text": clean(display), "origin": f"{BOOK[_b]} {_c}:{_v} (human review 2026, other defect)", "expect": [],
                                           "maybe": [{"span": nfc(d["original"]).replace("\n", " "), "fix": fixed, "reason": "reviewer: needs joining/rewrite; not a case-suffix sandhi finding"}]})
                continue
            pack_notes[d["cls"]].append(f"{BOOK[_b]} {_c}:{_v} «{nfc(d['original'])}» → {fixed or '(reviewer: doubling required)'}")
            if d["cls"] in ("A_ai_rootnoun", "B_ai_baremajority"): notlex_remove["ta-irv/sandhi.vallinam.accusative"].add(prev_w)
            if d["cls"] == "E_kku_exception": notlex_remove["ta-irv/sandhi.vallinam.dative"].add(prev_w)
            fixtures["sandhi"].append({"text": clean(display), "origin": f"{BOOK[_b]} {_c}:{_v} (human review 2026, missed)",
                                       "expect": [{"ruleId": "ta-irv/sandhi.vallinam.dative" if d["cls"] == "D_rku_dative" else ("ta-irv/sandhi.vallinam.demonstrative" if d["cls"] == "H_demonstrative_houseform" else "ta-irv/sandhi.vallinam.accusative" if "ai" in d["cls"] else "ta-irv/sandhi.vallinam.dative"),
                                                   "category": "sandhi", "span": nfc(d["original"]).replace("\n", " "), "fix": nfc(fix_other) or ""}]})
        elif c == "HOUSE":
            nodouble_next[nfc(d.get("next") or "")[:3]] += 1   # house style attaches to the NEXT word family, never to prev
        if nfc(is_name) == "ஆம்" and d.get("next"): name_contexts.append({"pair": nfc(d["original"]).replace("\n", " "), "verdict": c, "book": BOOK[_b], "ref": f"{_c}:{_v}"})

    # ---- 2 lexicon ----
    for r in wb["2 எழுத்துப்பிழை"].iter_rows(min_row=2, values_only=True):
        rid, rule_l, _b, _c, _v, display, original, s1, s2, s3, why, verdict, fix_other, note = r[:14]
        if not rid: continue
        d = data[rid]; c = code(verdict, V2)
        labels.append({**d, "kind": "flagged", "verdict": c, "correctForm": nfc(fix_other), "note": nfc(note)})
        if c is None or c == "UNSURE": continue
        text = clean(display)
        if c.startswith("TP"):
            right = nfc(fix_other) if c == "TP_OTHER_FIX" else (nfc(s1) if c == "TP1" else nfc(fix_other) or nfc(s2))
            fixtures["typo"].append({"text": text, "origin": f"{BOOK[_b]} {_c}:{_v} (human review 2026)",
                                     "expect": [{"ruleId": d["rule"], "category": "typo", "span": nfc(original), "fix": right}]})
            if right:
                curated_rows.append([BOOK[_b], _c, _v, "Confirmed typo", "Spelling", "High", "High", nfc(original), right,
                                     f"Human review 2026 ({d['rule']})", "", "No", "accepted"])
        else:
            fixtures["typo"].append({"text": text, "origin": f"{BOOK[_b]} {_c}:{_v} (human review 2026)", "expect": [],
                                     "negative": [{"span": nfc(original), "ruleId": d["rule"], "reason": c}]})
            if c == "FP_NAME": proper_nouns[nfc(original)] = ev(d)

    # ---- 4 other ----
    for r in wb["4 பிற"].iter_rows(min_row=2, values_only=True):
        rid, rule_l, _b, _c, _v, display, original, suggestion, verdict, note = r[:10]
        if not rid: continue
        d = data[rid]; c = code(verdict, V4)
        labels.append({**d, "kind": "flagged", "verdict": c, "note": nfc(note)})
        if c is None or c == "UNSURE": continue
        bucket = "punctuation" if "spacing" in d["rule"] or "integrity" in d["rule"] else "sandhi"
        cat = "spacing" if "spacing" in d["rule"] else ("usfm" if "integrity" in d["rule"] else "word-joining")
        entry = {"text": clean(display).replace("＼", "\\"), "origin": f"{BOOK[_b]} {_c}:{_v} (human review 2026)"}
        if c == "TP": entry["expect"] = [{"ruleId": d["rule"], "category": cat, "span": nfc(original).replace("＼", "\\"), "fix": nfc(suggestion).replace("＼", "\\")}]
        else: entry["expect"] = []; entry["negative"] = [{"span": nfc(original).replace("＼", "\\"), "ruleId": d["rule"], "reason": "FP"}]
        fixtures["usfm" if cat == "usfm" else "punctuation" if cat == "spacing" else "sandhi"].append(entry)
        if "repeated-word" in d["rule"]: pack_notes["repeated-word"].append(f"{c}: «{nfc(original)}» ({BOOK[_b]} {_c}:{_v})")

    # ---- 3 house style word lists ----
    clitic_policy, dem_policy = {}, {}
    for r in wb["3 வீட்டு நடை"].iter_rows(min_row=2, values_only=True):
        wid, list_l, word, suffix, bare3, dbl3, irv, example, verdict, note = r[:10]
        if not wid: continue
        d = data.get(wid, {}); cls = d.get("cls", "")
        if cls == "clitic":
            c = code(verdict, V3C); clitic_policy[nfc(word)] = c
        elif cls == "dem_houseform":
            c = code(verdict, V3D); dem_policy[nfc(word)] = c
        else:
            c = code(verdict, V3W); rule = "ta-irv/sandhi.vallinam.dative" if cls == "dat_exception" else "ta-irv/sandhi.vallinam.accusative"
            if c == "CASE_FORM_FLAG": notlex_remove[rule].add(nfc(word))
            elif c == "HOUSE": house_entries.append({"scope": "word-in-project", "ruleId": rule, "word": nfc(word), "provenance": "curated", "state": "active", "evidence": []})
        labels.append({"id": wid, "kind": "word", "cls": cls, "word": nfc(word), "verdict": c, "note": nfc(note)})

    # ---- summaries ----
    per_rule = collections.defaultdict(collections.Counter)
    for l in labels:
        if l["kind"] == "flagged" and l.get("verdict"): per_rule[l["rule"]][l["verdict"]] += 1
    summary = {"rules": {}, "abstained": {}, "clitics": clitic_policy, "demonstrativeHouseForms": dem_policy}
    for rule, cnt in per_rule.items():
        tp = sum(v for k, v in cnt.items() if k.startswith("TP")); house = cnt.get("HOUSE", 0)
        fp = sum(v for k, v in cnt.items() if k.startswith("FP")); unsure = cnt.get("UNSURE", 0)
        judged = tp + fp + house
        prec = tp / (tp + fp) if tp + fp else None           # house-style suppressed excluded, as the harness does
        prec_incl_house = tp / judged if judged else None
        summary["rules"][rule] = {"labelled": sum(cnt.values()), "tp": tp, "fp": fp, "house": house, "unsure": unsure,
                                  "precisionHuman": prec, "precisionHumanIncludingHouse": prec_incl_house,
                                  "inlineRecommended": bool(prec is not None and prec >= 0.90 and tp + fp >= 20), "verdicts": dict(cnt)}
    per_cls = collections.defaultdict(collections.Counter)
    for l in labels:
        if l["kind"] == "abstained" and l.get("verdict"): per_cls[l["cls"]][l["verdict"]] += 1
    for cls, cnt in per_cls.items():
        judged = cnt["MISSED"] + cnt["CORRECT_SKIP"] + cnt["HOUSE"]
        summary["abstained"][cls] = {**dict(cnt), "missedRate": (cnt["MISSED"] / judged) if judged else None}
    summary["notLexicalAdd"] = {k: sorted(v) for k, v in notlex_add.items()}
    summary["notLexicalRemove"] = {k: sorted(v) for k, v in notlex_remove.items()}
    summary["properNouns"] = list(proper_nouns)
    names_double = sum(1 for n in name_contexts if n["verdict"] in ("TP", "TP_OTHER_FIX", "MISSED"))
    names_nodouble = sum(1 for n in name_contexts if n["verdict"] in ("FP_NODOUBLE", "CORRECT_SKIP", "HOUSE"))
    summary["properNounContexts"] = {"doublingRequired": names_double, "noDoubling": names_nodouble, "rows": name_contexts}
    summary["noDoubleNextPrefixes"] = dict(nodouble_next.most_common())
    summary["rootFalsePositives"] = {"words": root_fp_words, "endingInMai": [w for w in root_fp_words if w.endswith("மை")]}
    # projected precision if the two systematic abstains (next-word prefix with >=3 FP_NODOUBLE, and -மை root nouns) are applied
    sys_prefixes = {p for p, n in nodouble_next.items() if n >= 3}
    for l in labels:
        if l["kind"] != "flagged" or l["rule"] not in per_rule: continue
        pass
    projected = {}
    for l in labels:
        if l["kind"] != "flagged" or not l.get("verdict") or l["rule"] not in RULE_BY_LABEL.values(): continue
        toks = nfc(l["original"]).split(); nxt = toks[-1] if len(toks) > 1 else ""; prv = toks[0]
        v = l["verdict"]
        fixed = (v == "FP_NODOUBLE" and nxt[:3] in sys_prefixes) or (v == "FP_ROOT" and (prv.endswith("மை") or prv in notlex_add.get(l["rule"], set())))
        if v in ("TP", "TP_OTHER_FIX"): projected.setdefault(l["rule"], [0, 0])[0] += 1
        elif v.startswith("FP") and not fixed: projected.setdefault(l["rule"], [0, 0])[1] += 1
    summary["projectedPrecisionAfterAbstains"] = {r: {"tp": tp, "fp": fp, "precision": tp / (tp + fp) if tp + fp else None, "systemAbstainPrefixes": sorted(sys_prefixes)} for r, (tp, fp) in projected.items()}

    # ---- write ----
    (out / "human_labels.jsonl").write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in labels) + "\n", encoding="utf-8")
    for bucket, items in fixtures.items():
        (out / "labelled" / f"{bucket}.jsonl").write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n", encoding="utf-8")
    seen = set(); dedup = []
    for e in house_entries + [{"scope": "word-in-project", "ruleId": "", "list": "properNouns", "word": w, "provenance": "curated", "state": "active", "evidence": [e]} for w, e in proper_nouns.items()]:
        key = (e["scope"], e.get("ruleId", ""), e["word"], e.get("list", ""))
        if key in seen: continue
        seen.add(key); dedup.append(e)
    (out / "housestyle_import.json").write_text(json.dumps({"schemaVersion": 1, "bookId": "*", "entries": dedup}, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "lexicon_curated.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["Book", "Chapter", "Verse", "Issue Type", "Priority Category", "Severity", "Confidence", "Original Tamil",
                                       "Suggested Correction", "Explanation", "Source / Reference Note", "Reviewer Decision Needed", "Status"])
        w.writerows(curated_rows)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# ta-irv candidate pack changes (from human review)", ""]
    md += ["## Human precision per rule (house-style suppressions excluded, as the benchmark does)", "", "| rule | labelled | TP | FP | house | unsure | precision | inline? |", "|---|---|---|---|---|---|---|---|"]
    for rule, s in sorted(summary["rules"].items()):
        p = "" if s["precisionHuman"] is None else f"{s['precisionHuman']:.0%}"
        md.append(f"| {rule} | {s['labelled']} | {s['tp']} | {s['fp']} | {s['house']} | {s['unsure']} | {p} | {'yes' if s['inlineRecommended'] else 'no'} |")
    md += ["", "## Recall check (abstained contexts)", "", "| class | missed | correct skip | house | unsure | missed rate |", "|---|---|---|---|---|---|"]
    for cls, s in sorted(summary["abstained"].items()):
        mr = "" if s["missedRate"] is None else f"{s['missedRate']:.0%}"
        md.append(f"| {cls} | {s.get('MISSED',0)} | {s.get('CORRECT_SKIP',0)} | {s.get('HOUSE',0)} | {s.get('UNSURE',0)} | {mr} |")
    md += ["", "## Systematic findings from the labels", ""]
    if summary["noDoubleNextPrefixes"]:
        md.append("- Next-word prefixes the reviewer marked 'case form, but no doubling here' (count): " + ", ".join(f"{k}- ×{n}" for k, n in summary["noDoubleNextPrefixes"].items()) + ". A prefix with ≥3 is a house-style abstain to add to EVERY vallinam rule as `next.prefix` (provenance curated).")
    pn = summary["properNounContexts"]
    md.append(f"- Proper noun as next word: doubling required in {pn['doublingRequired']} cases, not required in {pn['noDoubling']}. " + ("**Do not abstain on proper nouns**; drop the `housestyle.properNouns` abstain from the vallinam rules (keep the list only for the lexicon/name checks)." if pn['doublingRequired'] > pn['noDoubling'] else "Keep the proper-noun abstain."))
    rf = summary["rootFalsePositives"]
    if rf["words"]: md.append(f"- Root-noun false alarms: {', '.join(rf['words'])}. Of these, {len(rf['endingInMai'])} end in the abstract-noun suffix -மை → add `prev.notSuffix: [\"மை\"]` (a -மை noun's accusative is -மையை, so bare -மை is never a case form); the rest go to `notLexical`.")
    md.append("- Projected precision after those two systematic abstains (before any per-word edits): " + ", ".join(f"{r.split('/')[-1]} {p['precision']:.0%} ({p['tp']}/{p['tp']+p['fp']})" for r, p in summary["projectedPrecisionAfterAbstains"].items() if p["precision"] is not None))
    md += ["", "## Layer 1 — rule edits", ""]
    for rule, ws in summary["notLexicalAdd"].items(): md.append(f"- **{rule}**: ADD to `notLexical` (reviewer: not a case form): {', '.join(ws)}")
    for rule, ws in summary["notLexicalRemove"].items(): md.append(f"- **{rule}**: REMOVE from `notLexical` (reviewer: real case form, doubling required): {', '.join(ws)}")
    if pack_notes.get("D_rku_dative"):
        md += ["- **sandhi.vallinam.dative**: extend `prev.suffix` to `(?:க்கு|ற்கு)$` — reviewer confirmed doubling after -ற்கு in:"] + [f"    - {x}" for x in pack_notes["D_rku_dative"]]
    if pack_notes.get("other-defect"):
        md += ["- **Not case-suffix findings** (reviewer wants a join or a rewrite — keep these words in `notLexical`; they are evidence for a split-word / compound check, not for the vallinam rules):"] + [f"    - {x}" for x in pack_notes["other-defect"]]
    if pack_notes.get("G_marker"):
        md += ["- **all sandhi rules**: emit the finding on the first word when the pair straddles a poetry line / inline marker (reviewer confirmed):"] + [f"    - {x}" for x in pack_notes["G_marker"]]
    if pack_notes.get("H_demonstrative_houseform"):
        md += ["- **sandhi.vallinam.demonstrative**: drop the per-trigger `prefix` house-form abstain for these (reviewer: doubling required):"] + [f"    - {x}" for x in pack_notes["H_demonstrative_houseform"]]
    if dem_policy: md += ["- Demonstrative house-form verdicts (sheet 3): " + ", ".join(f"{k}: {v}" for k, v in dem_policy.items())]
    if clitic_policy: md += ["- **Clitic policy** (sheet 3): " + ", ".join(f"{k} → {v}" for k, v in clitic_policy.items()),
                              "    - FUSED → keep abstain in vallinam rules and enable `sandhi.clitic.fused` suggesting the fused form; SPACED_DOUBLED → remove that clitic from the abstain list so the vallinam rule fires; SPACED_BARE → keep abstain, disable clitic.fused for that word."]
    if pack_notes.get("repeated-word"):
        fps = sum(1 for x in pack_notes["repeated-word"] if x.startswith("FP")); tps = sum(1 for x in pack_notes["repeated-word"] if x.startswith("TP"))
        md += [f"- **tamil.repeated-word**: {tps} true / {fps} false. If false dominates, add a reduplication abstain (அடுக்குத்தொடர்: தங்கள் தங்கள், வெவ்வேறு, ஒவ்வொரு…) or set `inline: false` / disable."]
    md += ["", "## Layer 2 — lexicon", "", f"- `lexicon_curated.csv`: {len(curated_rows)} confirmed misspellings → `scripts/build_tamil_lexicon.py --curated`.",
           "- Reviewer false alarms on `lexicon.rare-near-common` are in `labelled/typo.jsonl` as `negative`; add those forms to the lexicon's protected/common set so they are never proposed again.",
           "", "## Layer 3 — house style", "", f"- `housestyle_import.json`: {len(dedup)} entries ({len(proper_nouns)} proper nouns from lexicon FP_NAME only — sandhi rows never feed the name list, see above; provenance `curated`). Bundle as the ta-irv seed and import into each project."]
    (out / "pack_changes.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({k: (v if k != "rules" else {r: {"precision": s["precisionHuman"], "inline": s["inlineRecommended"]} for r, s in v.items()}) for k, v in summary.items() if k in ("rules", "abstained")}, ensure_ascii=False, indent=1))
    print(f"wrote {out}/: human_labels.jsonl ({len(labels)}), labelled/*.jsonl, housestyle_import.json ({len(dedup)}), lexicon_curated.csv ({len(curated_rows)}), pack_changes.md, summary.json")

if __name__ == "__main__":
    main()
