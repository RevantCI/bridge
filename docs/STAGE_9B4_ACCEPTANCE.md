# Stage 9B.4 installed desktop acceptance — Bridge 0.9.4

Candidate build, **not released**. Everything below is run against the
installed `Bridge_0.9.4_x64-setup.exe`, not `tauri dev`.

Seed the three projects first, from the repository:

```powershell
python scripts/seed_correction_acceptance.py C:\bridge-acceptance
```

That writes `C:\bridge-acceptance\acceptance-manifest.json` with every id you
need below, and three project folders. Open each with **Open project** in
Bridge, then go to **Alignment Review → QA**.

---

## Read this before you start: what each case actually is

| case | fixture kind | expected verdict |
|---|---|---|
| **A** | **controlled verification fixture** | `PASSED` |
| **B** | **controlled verification fixture** | `FAILED` |
| **C** | **real production flow**, Stage 5 → 6A → 6B → 7 → 8 | `UNCERTAIN` |

Only **C** is production end-to-end. A and B publish controlled current
evidence directly so the verifier meets a decisive PASSED and a decisive
FAILED; do not describe them as production end-to-end in any report.

**Why the real case cannot reach PASSED.** A PASSED verdict requires Stage 6B
to positively *re-locate* the corrected obligation. In 0.9.4 every route to the
0.36 location threshold is closed for a cross-language project:

- no production multilingual embedding provider ships (`available = False`),
- the embedding cache is not consulted when the provider is unavailable,
- nothing in the running app ever writes `lexical_groups`, so the
  human-precedent signal (the heaviest, weight 0.65) is always empty,
- lexical + concept + structural + exact-span sum to about **0.19**.

So the verifier returns `UNCERTAIN` with `PROVIDER_LIMITED`, which is the
correct answer — it refuses to claim a success it cannot demonstrate. Your
acceptance spec lists provider limitation as an acceptable UNCERTAIN cause.

---

## Case A — PASSED, acknowledgement, restart, idempotency

Project `A-passed-controlled`. It arrives already applied and already
re-analysed, so you start at Verify.

1. Open the project. Open **Alignment Review → QA** and select the finding
   named in the manifest (`findingId`).
2. Confirm the panel shows the correction already applied:
   - application **COMPLETED**
   - affected analysis **COMPLETED**
   - verification **PENDING**
   - source reference **PHP 1:3**, target reference **PHP 1:6**, rendered
     separately — the source verse must not be shown as the corrected one.
3. Click **Verify correction**.
   - Expect verification **PASSED**.
   - Expect the QA disposition still **CONFIRMED_TRANSLATION_ERROR**. A pass
     must never promote the disposition by itself.
   - Expect **Mark correction as corrected** to appear.
4. Click **Verify correction** again immediately, twice in quick succession.
   - Expect exactly one current verification, no crash, no duplicate history
     entry.
5. Click **Mark correction as corrected**.
   - Expect an explicit confirmation dialog. Cancel it once; nothing should
     change. Reopen it and confirm.
   - Expect disposition **CORRECTED**.
   - Expect the original `CONFIRMED_TRANSLATION_ERROR` still visible in
     history, with the finding, proposal, application, analysis job and
     verification record all still present.
6. Click **Mark correction as corrected** again if the control is still
   offered. Expect one acknowledgement only — either idempotent or safely
   refused, never a second `CORRECTED` history event.
7. Check **Word Alignment** for PHP 1:6. It must be **INVALID / reviewable**.
   Verification must not have approved or rebuilt it.
8. Confirm Scripture did not change during verification or acknowledgement:
   PHP 1:6 still reads exactly what it read at step 2.
9. **Close Bridge completely**, reopen, reopen the same project, and re-check:
   application COMPLETED, affected analysis persisted, verification PASSED and
   current, disposition CORRECTED, `correctedBy` and `correctedAt` persisted,
   Scripture correction persisted, Word Alignment still INVALID, and no
   duplicate apply / verification / acknowledgement.

## Case B — FAILED

Project `B-failed-controlled`. Also arrives applied and re-analysed.

1. Open it, select the manifest's `findingId`, click **Verify correction**.
2. Expect verification **FAILED**, with reason codes naming the contradiction
   on the QUANTITY dimension — positive failure evidence, not mere absence.
3. Confirm the panel explains *why* the original obligation is still
   unsatisfied.
4. Confirm **Mark correction as corrected** is not offered, and the
   disposition is not `CORRECTED`.
5. Confirm Scripture and Word Alignment are unchanged by verification.
6. Close Bridge, reopen, confirm FAILED persists.

## Case C — the real production flow, ending UNCERTAIN

Project `C-uncertain-production`. This one you drive from the beginning.

1. Open it and go to **Alignment Review → QA**. Select the manifest's
   `findingId` — a `QUANTITY_PROBLEM` whose source obligation is at
   **PHP 1:3** and whose target realization is at **PHP 1:6**.
2. Check the evidence panes show source and target references **separately**,
   and that nothing claims a source relationship at PHP 1:6.
3. Decide the finding **CONFIRMED_TRANSLATION_ERROR**; review status becomes
   **HUMAN_APPROVED**.
4. Open the correction panel. The candidate span should be offered as
   **PHP 1:6**, the word **"some"**. Propose **"all"**, review and edit the
   wording normally.
5. **Apply** the correction through its confirmation dialog. Immediately after:
   - application **COMPLETED**
   - verification **PENDING**
   - affected analysis **NOT_RUN** — nothing may analyse automatically
   - the finding and its dependants marked stale as appropriate
   - Word Alignment for PHP 1:6 **INVALID / reviewable**
   - PHP 1:6 now reads `all remembrance of you remains with me …`, and
     **PHP 1:3 is untouched**
6. Click **Re-analyze affected passage**. Expect **COMPLETED** or
   **COMPLETED_WITH_WARNINGS**, over the structural range **PHP 1:3–1:6**,
   with resolved source `PHP 1:3` and resolved target `PHP 1:6`.
7. Click **Verify correction**. Expect **UNCERTAIN**, with
   `PROVIDER_LIMITED` among the reason codes and a visible explanation.
8. Confirm **Mark correction as corrected** is not offered, the disposition is
   still `CONFIRMED_TRANSLATION_ERROR`, Scripture is unchanged by
   verification, and `POSSIBLY_MISSING` has not been turned into a FAILED.
9. Close Bridge, reopen, confirm the UNCERTAIN verdict and its reason codes
   persist.

---

## After each case: the read-only inspector

```powershell
python scripts/inspect_correction_application.py <project folder> <findingId> <proposalId>
```

It mutates nothing. Record, per case:

`applicationId`, `applicationState`, `affectedAnalysisJobId`,
`affectedAnalysisState`, `verificationId`, `verificationStatus`,
`verificationCurrent`, `verificationReasonCodes`, `verificationAnalysisJobId`,
`verifierFingerprint`, `correctedAcknowledgement`, `correctedBy`,
`correctedAt`, source references, target references, affected range, target
revision/hash, and `wordAlignment.wordAlignmentState`.

## What must never happen, in any case

- Scripture changed by verification or by acknowledgement.
- `PASSED` setting `CORRECTED` without the explicit confirmation dialog.
- A `POSSIBLY_MISSING` coverage outcome becoming `FAILED`.
- Semantic verification approving or rebuilding Word Alignment.
- A second current verification, or a second `CORRECTED` history event.
