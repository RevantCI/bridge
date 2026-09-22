# Language QA — offline, Tamil first

Tracking: [#169](https://github.com/RevantCI/bridge/issues/169).
The user's complete framework is preserved in
[LANGUAGE_QA_TAMIL_SPECIFICATION.md](LANGUAGE_QA_TAMIL_SPECIFICATION.md).

## Problem and scope

Translators need automatic language checks after import/open and Scripture edits,
without network access, large language models, or blocking the editor. This work
lives on `language-qa` as a separate target-text QA layer. The supplied 56-check,
six-gate Tamil publication framework is the roadmap, not a claim that a rule
engine can certify publication readiness.

## Smallest useful implementation (LQA-1)

- Automatically inspect the current book after opening/importing it and after
  Bridge Scripture edits. Refresh external chapter changes during status polling.
- Use declared language plus sampled Unicode script evidence. Tamil script can
  suggest Tamil; conflicting metadata remains explicit. A shared script alone
  cannot distinguish Hindi/Marathi/Nepali or Bengali/Assamese. Unknown languages
  receive only common technical checks, with language-specific coverage unavailable.
- Check replacement/private-use/control characters, normalization, suspicious
  whitespace, repeated punctuation and words, and invalid Tamil dependent-sign
  sequences. Respect legal decomposed Tamil vowels, Grantha letters, க்ஷ and ஸ்ரீ.
- Keep original Unicode offsets and content hashes. Findings are read-only review
  candidates, never automatic Scripture edits or publication approvals.
- Display progress, actual coverage, limitations, errors, pause/resume and paged
  findings in a separate Language QA panel. Preserve exact verse bridges/segments.

## Resource and concurrency contract

No new runtime dependency, model, dictionary download, vendor tree or database
migration. Use Python's Unicode library and the already bundled `regex` package.
One short-lived worker per engine; debounce edits, yield between verses and wait
briefly after foreground requests. Read one bounded chapter at a time; reuse
unchanged chapter results in memory using SHA-256 content hashes (timestamps alone
are insufficient). Bound chapter/verse sizes, retained findings
and response pages; report limits as incomplete coverage. Changing books or editing
invalidates old results immediately and prevents old workers publishing them.

LQA-1 results are disposable in-memory analysis, automatically regenerated on
reopen. They are not review decisions, and no audit history is deleted. Durable
review dispositions and cross-session caches belong to a later approved workbench
migration. Preserved original USFM is not current edited Scripture: scan target
chapter JSON. Inline USFM is conservatively excluded from this first text pass;
the report discloses that omission. Dedicated USFM checks remain authoritative.

Budgets to verify: under 100 KiB new runtime source; no dependency change; bounded
2 MiB chapter input, 20,000 code points per verse, 100 findings per verse, 3,000
retained findings per book and 100 per response. Measure pure-check throughput and
foreground responsiveness under load. These are budgets, not a promise of zero
CPU use on every computer. Frozen-size and installed 1366×768 acceptance must be
measured before release.

## Staged coverage of the supplied framework

| Stage | Framework items | Delivery and evidence needed |
|---|---|---|
| LQA-1 | Parts of 1, 9, 35–38; automatic trigger portion of 55; text/rule hashes from 56 | Common technical rules and Tamil character integrity, separate background UI. UTF-8 file errors are explicit; NFC is advisory. No general spellchecker or grammar certification. |
| LQA-2 | 1–10, 20–21, 49–51 | Approved, versioned Tamil house-style/termbase/name packs with allowed and prohibited variants; dictionary and morphology feasibility measured offline. Sandhi, agreement, suffixes and joined/split forms need expert-labelled correct/incorrect examples, exceptions and validation before enabling each rule. Rare words or spelling similarity alone are never errors. |
| LQA-3 | 11–17, 22–24, 53 | Integrate existing source/semantic evidence and approved references with clear applicability and uncertainty. Source meaning, textual basis, theology and consultant decisions cannot be certified from text-only heuristics. No silent source substitution. |
| LQA-4 | 25–34, 48, remainder of 55–56 | Surface existing USFM/versification checks and extend current-text/notes/headings/reference coverage through the established parser work; avoid a new competing parser. Durable exceptions/provenance need a separately approved schema proposal. |
| LQA-5 | 18–19, 39–47, 52, 54 | Reader, community and consultant workflows; typeset PDF/font/layout checks require final production artifacts. Record explicit completion, never infer it from a clean text scan. |
| LQA-6 | Expansion across Indian languages, then other languages | Register independently tested small language packs. Shared Unicode checks remain available everywhere; report unsupported language rules honestly. Test shared-script ambiguity and mixed-language input for each addition. |

Execution of LQA-1 is authorized by the user's request. Later linguistic packs
require approved project-specific data; the broad prose framework does not supply
a dictionary, exhaustive grammar, reference corpus or production PDFs. Fully
automatic scheduling and detection are feasible; fully automatic publication
sign-off is not supported by these inputs.

## Sources for character rules

- Unicode Standard, Tamil section:
  https://www.unicode.org/versions/Unicode17.0.0/core-spec/chapter-12/#G11280
- W3C Tamil layout resources: https://www.w3.org/International/ilreq/tamil/

These inform implementation only; runtime checks never access them.

## Verification

Record executed tests and measurements here and in BUILD_LOG.md. Include legal
and malformed Tamil, NFD equivalence, mixed scripts, stable finding identity,
exact raw spans, edit/switch races, pauses, external edits, missing/oversize/bad
files, report limits, unchanged-input reuse and UI stale-response isolation.
Run the repository's engine and frontend gates. Frozen and desktop acceptance
remain separate release requirements.

### LQA-1 implementation and verification, 2026-09-22

Implemented on `language-qa`: `tc_ai_bridge/language_qa.py` (rules/detection),
`language_qa_jobs.py` (bounded disposable background analysis), automatic open/import
and committed-edit hooks, `languageQa.status/pause`, and the separate collapsible
Language QA panel. A request carries its project path, so a delayed old-book pause
cannot pause the new book. Switching books, edits and pause invalidate generations;
project transaction-recovery failures block scanning. No schema or dependency changed.

- Full engine suite: **1,313 passed** (serial, 20m50s; xdist absent locally).
  Final focused suite: **31 passed**, including checks added after that full run.
- Frontend: **480 passed**; final panel checks **6 passed**; Svelte **0 errors,
  0 warnings**; production build passed (existing large-chunk notice remains).
- Final source protocol benchmark: 401 verses, 15.328 s background wall time while
  deliberately yielding; foreground ping median 0.264 ms / max 0.831 ms.
- Final frozen protocol benchmark: 401 verses, 15.484 s; ping median 0.327 ms / max
  1.321 ms. Pause, explicit Scripture edit, resume and reuse of three unchanged
  chapters passed. These are measurements on this machine, not universal guarantees.
- Typical 191-character rule pass median 0.6–0.8 ms; 20,000-character stress
  inputs measured 7.6–44.9 ms in a standalone check.
- The new engine modules occupied approximately **16 KB compressed** in the PYZ
  archive (15,788 bytes in the final build); no model, external service, dictionary
  download or new package is added.
  This is module payload, not a controlled installer-size comparison.
- Both frozen executables built in `engine/dist/language-qa/`. The standard
  whole-sidecar smoke is **blocked by pre-existing #170**: the package says 0.12.0,
  but both engine version constants at the starting HEAD say 0.11.0. The Language
  QA-specific frozen benchmark passes independently. #130 remains a separate known
  later smoke issue; it was not reached in this run.
- Installed-app visual/interactive acceptance: **NOT RUN**. Browser automation
  inventory was empty. No installer was published or installed.

Run the reproducible scoped source/frozen acceptance with:

```powershell
.\engine\.venv\Scripts\python.exe scripts\benchmark_language_qa.py
.\engine\.venv\Scripts\python.exe scripts\benchmark_language_qa.py --engine engine\dist\language-qa\bridge-engine.exe
```

Next stage needs approved Tamil house-style, spelling variants, terminology/names,
and reviewed grammar/sandhi examples. The supplied framework specifies categories;
it does not establish correct answers for arbitrary Tamil sentences. LQA-2 through
LQA-6 remain planned, and LQA-1 is not a publication-readiness certification.
