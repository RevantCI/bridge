# Semantic mapping validation sets

`irvtam-semantic-mapping-candidates.json` is a generated review queue, not
ground truth. Every row starts as `MACHINE_PROPOSED` / `UNCONFIRMED`.

The current checked-in IRVTam corpus contains complete Luke and Philippians
USFM files. The local-only generation pass produced 36 candidates across both
books. One row is the required exact PHP 1:3 → PHP 1:6 regression sentinel.
The remaining rows are explicitly marked `STRUCTURAL_SCREEN`: Stage 3 source
help metadata and target USFM structure selected them as useful passages for
semantic review, but no target span or meaning-preserved conclusion was
accepted. They must not be used for Basic-mode auto-application.

Generate the local-only set without transmitting corpus text:

```powershell
.\engine\.venv\Scripts\python.exe scripts\generate_irvtam_mapping_candidates.py --structural-only --limit 40
```

The same script can run the full structured semantic mapper when transmission
of the selected source evidence and target passages to the configured
OpenAI-compatible endpoint has been explicitly authorized. That pass replaces
structural screens with exact, USFM-verified span proposals where the model can
ground them; competing/unresolved results remain review states.

Human validation must be recorded through the Stage 3 companion mapping audit.
It must never edit verse markers, target word order, or translationCore's
verse-local check data merely because a passage relationship crosses verses.
