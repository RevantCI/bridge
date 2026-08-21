# Vendored: Greek Room Smart Edit Distance (SED)

This directory contains files copied from the `BibleNLP/greek-room` GitHub
repository, at path `smart_edit_distance/`. **This is not published on
PyPI under any name** (`smart-edit-distance`, `smart_edit_distance` — both
checked, neither exists) and is not part of the published `greekroom`
PyPI package either (that package, confirmed by inspecting the installed
wheel while investigating the USFM checker, only ships `owl` and
`gr_utilities`). See `docs/DEVELOPER_HANDOFF.md`'s Phase 5 research
breadcrumb for the full investigation.

## Provenance

- Source: https://github.com/BibleNLP/greek-room
- Path: `smart_edit_distance/`
- Pinned commit: `18ddcf0e6c03fa2774b73b21186115d712e4cba9` (the same commit
  already pinned for `engine/vendor/greekroom-usfm/` and
  `engine/vendor/greekroom-versification/` — this is one more directory out
  of that same repo checkout, not an independent version).
- Fetched: 2026-08-21
- Files copied: `smart_edit_distance.py` (from `src/`),
  `data/string-distance-cost-rules.txt`,
  `data/string-distance-cost-rules-Devanagari.txt`. Confirmed via the
  GitHub API tree listing that these three files are the entire contents
  of `smart_edit_distance/` at this commit — no `README`, tests, or
  `__init__.py` exist there to omit.

## What this is, and how it's integrated

Written by Ulf Hermjakob, USC/ISI — the same author and research group as
Wildebeest, the USFM checker, versification, and Uroman. A ~430-line, pure
standard-library module (`argparse`, `logging`, `re`, `sys`, `typing` only
— no third-party imports, and does not import Uroman itself despite its
own docstring describing the two as complementary). `SmartEditDistance` is
a plain class holding only per-instance state — checked directly by
instantiating it twice in the same process, unlike
`Versification.load_versifications()`'s real class-level-state bug, this
does not reproduce here.

**Integrated like versification.py, not like the USFM checker**: this is
genuinely reusable library code (a class with methods operating on
in-memory data), not a monolithic CLI/report-generator script, so it's
imported directly into the long-lived `bridge-engine` process rather than
run as a subprocess. See `engine/greek_room_engine/adapters/names_adapter.py`.

## Real bug found by running it against the real data file

`SmartEditDistance.load_smart_edit_distance_data()` accepts either a file
object or a string path; when given a string path it calls bare
`open(raw_cost_file)` with **no explicit encoding**. The real
`string-distance-cost-rules.txt` contains 117 non-ASCII bytes (confirmed
by reading it as raw bytes). Loading it under this project's Windows dev
machine's default locale (`cp1252`) reproduces
`UnicodeDecodeError: 'charmap' codec can't decode byte 0x90 in position
3802: character maps to <undefined>` — the third time this exact bug class
(bare `open()` defaulting to a non-UTF-8 Windows codepage) has been found
in this project's Greek Room integrations, after `usfm_check.py` and
`versification.py`'s file-based methods.

**Not patched in this vendored file** — architecturally avoided instead,
the same choice made for `versification.py`'s equivalent bug: Bridge's own
`names_adapter.py` always opens the cost-rules file itself with explicit
`encoding="utf-8"` and passes the resulting file object in, so the buggy
`isinstance(raw_cost_file, str)` branch inside `load_smart_edit_distance_data`
is simply never reached. If anything is ever added that calls this method
with a bare string path instead, patch it the same way
`usfm_check.py`'s two call sites were patched (see that directory's
NOTICE.md).

## Only the general cost-rules file is wired up so far

`data/string-distance-cost-rules-Devanagari.txt` is vendored (so a future
sync doesn't need to re-fetch it) but **not loaded by `names_adapter.py`
in this pass** — verifying how a script-specific supplementary cost file
is meant to be combined with the general one (loaded in addition to, or
instead of?) wasn't done this session. Treat Devanagari-script target
projects as running on the general-purpose cost rules only, same
precision as any other script, until this is verified and wired up.

## License

BSD 3-Clause License, Copyright (c) 2022 USC/ISI (Ulf Hermjakob, Joel
Mathew). Full text in `LICENSE` in this directory (copied from the repo
root, same as the other two vendor directories — there is no separate
license file inside `smart_edit_distance/`). Same repo-root license
governs these files; no separate/hidden data license was found here
(checked directly, since versification's `data/` directory turned out to
carry a different CC BY-SA license than its code — this time there isn't
a second license to reconcile).

## Do not casually "clean up" or refactor these files

They are a third-party checkout, not Bridge's own code. Any local
adaptation needed to run them should live in Bridge's wrapper code
(`engine/greek_room_engine/adapters/names_adapter.py`), not by editing
these files in place — see `engine/vendor/greekroom-usfm/NOTICE.md`'s
fuller explanation of why, which applies equally here.
