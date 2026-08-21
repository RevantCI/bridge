# Vendored: Greek Room USFM checker

This directory contains files copied from the `BibleNLP/greek-room` GitHub
repository, at path `greekroom/greekroom/usfm/`. **This is not published on
PyPI** — only `greekroom`'s `owl` and `gr_utilities` submodules are; `usfm`
exists only in the source tree. See `docs/DEVELOPER_HANDOFF.md` for the full
investigation of why this is vendored rather than a normal pip dependency,
and the long-term costs/practices agreed before doing so.

## Provenance

- Source: https://github.com/BibleNLP/greek-room
- Path: `greekroom/greekroom/usfm/`
- Pinned commit: `18ddcf0e6c03fa2774b73b21186115d712e4cba9`
- Fetched: 2026-08-20
- Files copied: `usfm_check.py`, `ualign_utilities.py`,
  `Bible_USFM_tag_data.jsonl`, `Bible_USFM_explanations.txt`, `README.md`.

## Bridge compatibility patches

`usfm_check.py` has two narrow, annotated local patches that must be
reapplied or reassessed during an upstream sync:

- Portable timestamp formatting because Windows does not support the
  upstream `%-d`/`%-H` `strftime` directives.
- Explicit `utf-8-sig` text inputs and UTF-8 report/log outputs because a
  frozen Windows executable otherwise uses `cp1252` and crashes while reading
  Odia/Tamil/Hebrew USFM or writing language-bearing diagnostics.

## License

BSD 3-Clause License, Copyright (c) 2022 USC/ISI (Ulf Hermjakob, Joel
Mathew). Full text in `LICENSE` in this directory (copied from the repo
root — there is no separate license file inside `usfm/`, so the repo's
root license governs these files). Note: the *published* `greekroom` PyPI
package's own metadata claims Apache 2.0, which conflicts with this
repo-root BSD 3-Clause file — an inconsistency in upstream's own metadata.
It doesn't affect these files either way, since they were never part of
that PyPI package to begin with; the repo's `LICENSE` is what actually
governs the source pulled here.

## Do not casually "clean up" or refactor these files

They are a third-party checkout, not Bridge's own code. Any local
adaptation needed to run them (see `engine/greek_room_engine/adapters/`
for how they're invoked) should live in Bridge's wrapper code, not by
editing these files in place — that keeps a future re-sync against
upstream tractable instead of a full rewrite. If a change here is
genuinely unavoidable, document it clearly (what, why) so it isn't lost
on the next sync.

## Not vendored (out of scope for now)

`greekroom/greekroom/wildebeest/` also exists only in the source tree, not on
PyPI (Bridge uses the real `wildebeest-nlp` PyPI package instead — see
`docs/DEVELOPER_HANDOFF.md`'s Wildebeest section).

`greekroom/greekroom/versification/` **was** out of scope when this note was
originally written; it has since been vendored separately at
`engine/vendor/greekroom-versification/` (see that directory's own
`NOTICE.md`) — a real, independently investigated decision, not an automatic
extension of this one. The two vendor directories are integrated
differently: this one runs as an isolated subprocess/helper executable,
while versification is imported directly as a library, since (unlike this
4,000-line CLI script) `versification.py` is genuinely reusable code.
