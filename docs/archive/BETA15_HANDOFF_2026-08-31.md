<!-- Archived 2026-09-17 from docs/DEVELOPER_GUIDE.md, where it sat inside
     section 2.1 as a dated snapshot. Kept verbatim; the live roadmap is
     DEVELOPER_GUIDE.md section 2 and the session record is BUILD_LOG.md. -->

# Historical Beta 15 developer handoff — 2026-08-31

> This subsection is retained as an audit snapshot. Its “next” instructions
> describe the repository on 2026-08-31 and are superseded by §2.1 and the
> latest sections of `BUILD_LOG.md` (`HANDOFF.md` is archived, #107).

Start from `main` at `933d48c` (`feat(dashboard): split project dashboard into
book list and report panels`) or a later descendant. The working tree was clean
before this handoff update. The bundled proposal artifact remains
[`validation/irvtam-semantic-mapping-candidates.json`](../validation/irvtam-semantic-mapping-candidates.json):
40 `MACHINE_PROPOSED` rows generated with `gpt-5.6`. Do not rewrite that file
as though the model originally produced human-confirmed data.

Manual installed-app validation is complete for every bundled candidate:

| Book | Reviewed | Confirmed | Corrected | Rejected | Displayed agreement |
|---|---:|---:|---:|---:|---:|
| Luke | 28/28 | 27 | 1 | 0 | 96% |
| Philippians | 12/12 | 11 | 0 | 1 | 92% |
| **Combined** | **40/40** | **38** | **1** | **1** | **95%** |

Bridge was restarted after review. Both book-specific decision sets and their
calibration totals persisted. The reviewed set covers `SAME_VERSE`,
`CROSS_VERSE`, `CROSS_VERSE_REORDERED`, `SPLIT_ACROSS_VERSES`,
`MERGED_ACROSS_VERSES`, `REORDERED_WITHIN_VERSE`, `CLAUSE_MOVED`,
`SENTENCE_REORDERED`, `PRONOMINALIZED`, `GRAMMATICALLY_ENCODED`, `IMPLICIT`,
and `PARAPHRASED`. The known regression is explicitly human-confirmed:

```text
PHP 1:3  τῷ Θεῷ μου
PHP 1:6  என் தேவனை
CROSS_VERSE_REORDERED · PRESERVED · proposed confidence 0.99
candidate a9d12c8a97e405ae0709
```

The two non-confirmed records require careful interpretation:

- `dababa8fb3c5280df4c0` (LUK 3:34, `translate-names`) was saved as
  `HUMAN_CORRECTED`. Its saved mapping has the two exact spans in LUK 3:33 and
  3:34, `CROSS_VERSE + SPLIT_ACROSS_VERSES + PARAPHRASED`, `PRESERVED`, and
  confidence `0.99`. That payload currently matches the machine proposal in
  all material mapping fields. Treat it as proof of the correction workflow,
  not as evidence that a relationship or threshold is wrong.
- `a55017aa58d2d1fcb657` (PHP 1:5, translationWord `fellowship`) was rejected.
  The rejected proposal mapped `τῇ κοινωνίᾳ` to
  `நீங்கள் எங்களோடு ஊழியத்தில் ஐக்கியப்பட்டிருப்பதால்` in PHP 1:3 at
  confidence `0.97`. The audit contains no reviewer note, so it establishes a
  negative regression fixture but does **not** by itself justify a particular
  prompt, relationship, or confidence adjustment. Obtain or derive explicit
  linguistic evidence before changing production policy.

The per-project source audits were local companion data at

```text
%LOCALAPPDATA%\Bridge\data\projects\tam_irv_luk\.apps\translationCoreAI\semanticValidation\irvtam-v0.1.json
%LOCALAPPDATA%\Bridge\data\projects\tam_irv_php\.apps\translationCoreAI\semanticValidation\irvtam-v0.1.json
```

and **no longer exist**: those projects were re-imported after the #76 cutover,
and a 2026-09-16 search of the machine (every `bridge-workbench.sqlite3`
included) found no copy. The "next implementation steps" this snapshot used to
list — export a sanitized fixture of the 40 decisions, add per-decision
regressions, calibrate by confidence band, exercise the `Needs discussion`
path — were therefore never done and are now moot: the validation queue itself
was removed in #100. The table above and the two non-confirmed records described
here are the surviving record.
5. Run the focused semantic suites, complete Python suite, Svelte check,
   production frontend build, UI-state tests, Rust tests, frozen-sidecar smoke,
   and NSIS packaging. Then perform installed Beta 15 upgrade/persistence,
   validation, USFM-preservation, alignment, export, and Paratext acceptance.

Do not mark Beta 15 complete merely from the 40/40 review count. The checked-in
fixture, evidence-supported calibration decision, automated gates, exact
artifact provenance, and installed acceptance are still release requirements.

**Lesson worth keeping in mind for future phases:** every external
integration attempted so far (Wildebeest, USFM checker, versification,
Uroman) turned out to have a real, non-obvious problem that only surfaced by
actually running the code — wrong PyPI package name, a Python 3.13
compatibility break, an unpublished dependency, a Windows-only `strftime`
crash, a version-skew bug between upstream's GitHub and PyPI releases, a
class-level-state crash on a second call, a silently different data license
hiding inside an otherwise-permissive vendor tree. Verify by running, not by
reading a doc's description — including this repo's own docs.

**Deliberately not yet done** (scope decisions, not bugs):

- Live original-language resource downloads (current baseline is a pinned,
  bundled snapshot — see §4).
- Automatic continuous Paratext or Logos synchronization. Bridge currently
  performs explicit one-shot Paratext issue handoffs; the live Paratext path is
  verified, while Logos remains unverified against a running installation.
- A dedicated UI panel for alignment corpus statistics (protocol-only today).
- A second-language semantic-mapping corpus validation. The first IRVTam set
  was fully reviewed and its validation queue then removed (#100); a second
  corpus would need a new review surface, not a revival of that one.
- Manual alignment does not invent source tokens — it requires original-
  language tokens already present from import.

---
