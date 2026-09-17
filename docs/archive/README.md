# docs/archive

Point-in-time documents kept for the record. Nothing here is maintained; each one
describes the repository, an installer or a review at the commit it names. The
current-state docs are `../ARCHITECTURE.md`, `../DEVELOPER_GUIDE.md` and, for the
full narrative, `../BUILD_LOG.md`. Moved here 2026-09-16 by #107.

`HANDOFF.md` was deleted on 2026-09-17: its status records duplicated
`BUILD_LOG.md`, its transfer instructions no longer apply, and the sections that
were project knowledge (§20, §21, §31, §36, §39, §44.8) were lifted verbatim into
`../INVARIANTS.md`, keeping their numbers so the citations from engine code still
resolve.

| File | What it was |
|---|---|
| `BETA15_HANDOFF_2026-08-31.md` | Beta 15 developer handoff, written 2026-08-31; lived inside `DEVELOPER_GUIDE.md` §2.1 until 2026-09-17 |
| `FONT_SUPPORT_PLAN.md` | Indic and source-script font support plan, self-declared implemented 2026-09-08; where it and the code disagree, the code wins |
| `V11-000_STAGE6B_ALIGNMENT_SPIKE.md` | Research spike: why Stage 6B never consulted completed word alignment (#54), with the fix plan |
| `V11-000a_REVIEW_FIX_PROMPT.md` | Review findings F1–F6 on the V11-000 fix and the prompt that drove the follow-up commits |
| `V11-003_ISSUE57_PROMPT.md` | Product decision and prompt for #57 (review-status backfill, W1 fix) |
| `V1_1_UNICODE_ACCEPTANCE.md` | Installed-app acceptance script for the Unicode/Tamil correction cases (A–D), against the 0.9.7 installer |
| `V1_1_ACCEPTANCE_01.md` | Installed-app acceptance run of 2026-09-12 (finding menu, #69/#70) |
| `STAGE_9B4_ACCEPTANCE.md` | Installed-app acceptance script for Stage 9B.4 verification cases A/B/C, driven by `scripts/seed_correction_acceptance.py` |
