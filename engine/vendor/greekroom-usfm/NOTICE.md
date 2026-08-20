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
- Files copied verbatim, unmodified: `usfm_check.py`, `ualign_utilities.py`,
  `Bible_USFM_tag_data.jsonl`, `Bible_USFM_explanations.txt`, `README.md`.

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

`greekroom/greekroom/versification/` and `greekroom/greekroom/wildebeest/`
also exist only in the source tree, not on PyPI. Only `usfm` was vendored
here, matching the specific decision made for this pass — versification
support is a separate future decision, not assumed to follow automatically
from this one.
