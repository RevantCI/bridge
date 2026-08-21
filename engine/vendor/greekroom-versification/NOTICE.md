# Vendored: Greek Room versification tools

This directory contains files copied from the `BibleNLP/greek-room` GitHub
repository, at path `greekroom/greekroom/versification/`, the same repo and
pinned commit already vendored for the USFM checker
(`engine/vendor/greekroom-usfm/`). See `docs/DEVELOPER_HANDOFF.md` for the
full investigation of what was verified this session and why it's vendored
this way.

## Provenance

- Source: https://github.com/BibleNLP/greek-room
- Path: `greekroom/greekroom/versification/`
- Pinned commit: `18ddcf0e6c03fa2774b73b21186115d712e4cba9` (same as the USFM checker)
- Fetched: 2026-08-21
- Files copied: `versification.py`, plus `data/standard_mappings/{org,eng,rsc,rso,vul,lxx}.json`.
- **Not published on PyPI** — confirmed freshly this session (not assumed from
  the USFM checker precedent): only `greekroom`'s `owl` and `gr_utilities`
  submodules are on PyPI; `usfm`, `versification`, and `wildebeest` all exist
  only in the source tree.

### Deliberately NOT vendored

- `data/vref.txt` (390 KB) and `data/psalm-descriptive-titles.txt` — read by
  the vendored `main()` CLI entry point only (as a default arg and via
  `Versification.vref_filename()`), never by the `BibleStructure`,
  `Versification`, `VersifiedCorpus`, `VersificationMatch`, or
  `BackVersification` classes that Bridge actually calls. Verified by
  reading the source, not assumed. Bridge never calls `main()`.
- `verse_inspection.py`, `versification_diff_html.py`,
  `versification_diff_txt.py`, `extract_vref_txt_from_usfm_extract_jsonl.py`
  — auxiliary CLI reporting/diffing tools operating on flat corpus+vref
  files, not needed by Bridge's per-project reversification and
  back-versification use case.
- `greekroom/gr_utilities/general_util.py` and
  `greekroom/usfm/ualign_utilities.py` are duplicated here from
  `engine/vendor/greekroom-usfm/` (same pinned commit, byte-identical
  content) rather than shared across the two vendor directories, matching
  the existing vendor dir's self-contained pattern.

## Real, verified integration differences from the USFM checker

Unlike `usfm_check.py` (a 4,000-line CLI script with no reusable functions,
forced into a subprocess), `versification.py` is a genuine library —
`BibleStructure`, `Versification`, `VersifiedCorpus`, `VersificationMatch`,
and `BackVersification` are real classes with methods that operate on
in-memory dicts, not just file paths. Confirmed by reading the source and
exercising it directly against the real vendored data (not assumed from the
USFM precedent — that assumption would have been wrong). Bridge's wrapper
(`engine/tc_ai_bridge/versification.py`) therefore **imports this directly
into the long-lived `bridge-engine` process** — no subprocess, no helper
executable, no PyInstaller spec — a materially different integration shape
than the USFM checker's.

**Zero source patches were needed** (unlike `usfm_check.py`'s two
`# BRIDGE PATCH` markers), because Bridge's usage pattern avoids every file
path where the real problems below live. This was verified by actually
exercising the code against real data on Windows, not assumed:

1. **Import path.** `versification.py` does
   `from greekroom.usfm.ualign_utilities import BibleUtilities` — it expects
   `ualign_utilities.py` inside a `greekroom/usfm/` subpackage. The USFM
   checker's own copy of that file sits flat at its vendor root instead
   (`usfm_check.py` imports it as a same-directory module: `import
   ualign_utilities`). These are two different, both-real import
   conventions from the same upstream commit. Solved by directory layout
   here (`greekroom/usfm/ualign_utilities.py`), not by editing either
   vendored file.
2. **Windows encoding crash — real, reproduced, but not hit by Bridge's
   usage.** `VersifiedCorpus.load_corpus()` (and `write_corpus()`, and the
   file opens inside `main()`/`BackVersification.__init__`) call bare
   `open()` with no explicit encoding. On this Windows machine that resolves
   to `cp1252`, and feeding it real Tamil verse text reproduces a real
   `UnicodeDecodeError` — the exact same bug class already found and patched
   in `usfm_check.py` (see that directory's `NOTICE.md`). Confirmed with a
   real Tamil string, not assumed from the sibling bug. **Bridge's wrapper
   never calls `load_corpus`/`write_corpus`/`main()`** — it builds
   `VersifiedCorpus.vref2verse` directly from Bridge's own already-parsed
   chapter/verse JSON — so this bug is architecturally avoided rather than
   patched. If anything ever calls those file-based methods directly, this
   will resurface; patch it the same way as `usfm_check.py` if that happens.
3. **Real long-lived-process bug, found by actually calling it twice.**
   `Versification.load_versifications()` populates *class-level* state
   (`Versification.versification_d`, `Versification.org`) that is never
   reset. A second real call in the same process — exactly what a
   long-running `bridge-engine.exe` would do on a naive per-project-open
   call — hits `Versification.__init__`'s duplicate-schema branch, logs an
   error, and returns **without setting any instance attributes**. The
   caller doesn't know this happened and proceeds to call
   `check_mappings()` on the half-built object, which crashes with
   `AttributeError: 'Versification' object has no attribute
   'verse_id_list'`. Reproduced directly, not assumed. Fixed in Bridge's own
   wrapper by loading exactly once per process (lock + flag guard) —
   `engine/tc_ai_bridge/versification.py` is the only code allowed to call
   `Versification.load_versifications()`; nothing else should call it
   directly.
4. **Catastrophic concurrency slowdown, found by writing concurrency edge
   case tests and measuring, not by reading the source.** `VersificationMatch.__init__`
   scans a schema's full `verse_id_list` (tens of thousands of entries for
   `eng`/`org`) in pure Python. That's ~0.5s single-threaded — fine. But run
   several of these scans on different threads **at the same time** and
   CPython's GIL doesn't just serialize the work proportionally: measured
   directly, 16 threads each running one scan concurrently took **~47
   seconds per thread**, not the ~8s naive linear scaling would predict —
   over 90x worse than sequential. This is real GIL contention on tight
   pure-Python loops under many simultaneous threads, not a bug in the
   scan's logic itself (the single-threaded result is always correct).
   Bridge's own `detect_schema()` calls this once per schema (up to six
   times) on every call, so a burst of near-simultaneous
   `versification.detect` requests — e.g. a user quickly switching between
   several just-opened book tabs before each book's per-project cache in
   `bridge_service.py` is warm — would look exactly like the sidecar
   hanging. Fixed by serializing `detect_schema()`'s scan with the same
   lock `_ensure_loaded()` already uses (`engine/tc_ai_bridge/
   versification.py`): the same 16-thread scenario then completes in ~8s
   total, not ~47s each. `to_org_ref()`/`back_versification_map()` do
   plain dict lookups, not this scan, and were separately measured to be
   safe unlocked under the same concurrency — don't add locking there
   without re-measuring first, and don't assume this lock is free
   insurance for future code added to this module either. See
   `engine/tests/test_versification_concurrency.py` for the reproduction
   and the regression guard (a wall-clock bound tight enough that the
   unfixed behavior blows through it by 5-10x).

## License — two different licenses cover this directory, unlike the USFM checker

- **Code** (`versification.py`, and the duplicated `general_util.py` /
  `ualign_utilities.py`): BSD 3-Clause, Copyright (c) 2022 USC/ISI (Ulf
  Hermjakob, Joel Mathew). Full text in `LICENSE` in this directory — same
  license and same caveat about the *published* `greekroom` PyPI package's
  conflicting Apache-2.0 metadata as documented in
  `engine/vendor/greekroom-usfm/NOTICE.md`.
- **Data** (`data/standard_mappings/*.json`): these are **not** greek-room's
  own data. Per that directory's own upstream `README.md`, they were
  "gathered/created by the Copenhagen Alliance Versification Working Group"
  (https://github.com/Copenhagen-Alliance/versification-specification) and
  merely re-hosted inside greek-room's tree. That repository's own
  `LICENSE.md` splits code (Apache 2.0) from **data (CC BY-SA 4.0 —
  Attribution-ShareAlike)**, and versification mapping tables are data, not
  code. **This is a genuinely different, non-obvious license situation from
  the USFM checker vendoring decision** — CC BY-SA 4.0 requires attribution
  and, for any redistributed adaptation, the same license on that
  adaptation. Bridge's own root `LICENSE` is GPLv3 (already copyleft, already
  requires source availability), which makes bundling attributed,
  unmodified CC BY-SA 4.0 reference data low-risk — but this was a real
  decision point, not a rubber stamp of the BSD-3-Clause precedent, and
  should be re-reviewed if these JSON files are ever modified before
  redistribution (as opposed to used unmodified, which is what Bridge does).

## Do not casually "clean up" or refactor these files

Same policy as `engine/vendor/greekroom-usfm/`: this is a third-party
checkout, not Bridge's own code. Local adaptation belongs in
`engine/tc_ai_bridge/versification.py`, not edits to the files here.
