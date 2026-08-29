# Semantic mapping validation sets

`irvtam-semantic-mapping-candidates.json` is a generated review queue, not
ground truth. Every row starts as `MACHINE_PROPOSED` / `UNCONFIRMED`.

The checked-in IRVTam corpus contains complete Luke and Philippians USFM files.
After explicit data-transfer authorization, the full structured semantic pass
with `gpt-5.6` produced 90 validator-accepted mappings. The representative
review queue contains 40 candidates: 28 from Luke and 12 from Philippians.
Every one remains unconfirmed and must not be treated as ground truth.

All 43 overt target spans in the queue were re-derived from the imported USFM:
the stored quote occurs unambiguously and equals the text at its stored
offsets. Model-supplied offsets are never trusted. One Luke 11:2-4 batch was
rejected in full because a proposed quote failed this check; its diagnostic is
retained in `batchDiagnostics`. The exact PHP 1:3 -> PHP 1:6 regression is
present with source `τῷ Θεῷ μου` and target `என் தேவனை`.

Generate the local-only set without transmitting corpus text:

```powershell
.\engine\.venv\Scripts\python.exe scripts\generate_irvtam_mapping_candidates.py --structural-only --limit 40
```

Run the authorized full structured pass with:

```powershell
.\engine\.venv\Scripts\python.exe scripts\generate_irvtam_mapping_candidates.py --max-batches 10 --units-per-batch 10 --limit 40
```

The full pass checkpoints after each batch and caches content-fingerprinted
validated results under the ignored `engine/build/semantic-corpus-discovery`
directory. A rejected batch does not discard previous paid-for work and does
not cause Bridge to weaken exact-quote validation.

The generated artifact SHA-256 is
`C4610F094F85A1530E4AD137412B1434E88A41A04686126E782E1AD3E989C344`.

Human validation must be recorded through the Stage 3 companion mapping audit.
It must never edit verse markers, target word order, or translationCore's
verse-local check data merely because a passage relationship crosses verses.

In Bridge, switch to **Advanced** mode, open the IRVTam Luke or Philippians
project dashboard, and select **Validate semantic mappings**. Enter the reviewer
identity, inspect the source/help evidence and imported-USFM target spans, then
choose **Confirm exact mapping**, **Correct**, **Reject**, or **Needs
discussion**. Corrected spans use one line per span:

```text
BOOK chapter:verse | exact target quote | optional start | optional end
```

Bridge records these decisions under the project's companion
`semanticValidation/irvtam-v0.1.json` audit. The first release gate is 15–20
representative human decisions. Only after reviewing the displayed calibration
by confidence and relationship should model thresholds or classification
behavior be changed.
