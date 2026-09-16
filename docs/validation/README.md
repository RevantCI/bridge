# Semantic mapping validation set (historical)

`irvtam-semantic-mapping-candidates.json` is the generated review queue that
the Stage 3 semantic-mapping validation workflow consumed. **That workflow was
removed on 2026-09-16 (#100)**: the dashboard's *Validate semantic mappings*
button, `SemanticMappingValidation.svelte`, the `semanticValidation.list/decide`
protocol methods, `semantic_validation_service.py`, and the
`scripts/generate_irvtam_mapping_candidates.py` generator are gone. Nothing in
Bridge reads this file any more. It stays in the repository as the evidence
record described below; do not rewrite it as though the model originally
produced human-confirmed data.

## What the file is

The checked-in IRVTam corpus (`engine/resources/semantic_mapping/regression/`)
contains complete Luke and Philippians USFM files. After explicit data-transfer
authorization, a full structured semantic pass with `gpt-5.6` produced 90
validator-accepted mappings. The representative review queue holds 40
candidates: 28 from Luke and 12 from Philippians. Every row is
`MACHINE_PROPOSED` / `UNCONFIRMED` in the file itself.

All 43 overt target spans were re-derived from the imported USFM: the stored
quote occurs unambiguously and equals the text at its stored offsets.
Model-supplied offsets were never trusted. One Luke 11:2-4 batch was rejected
in full because a proposed quote failed this check; its diagnostic is retained
in `batchDiagnostics`. The PHP 1:3 → PHP 1:6 cross-verse regression is present
with source `τῷ Θεῷ μου` and target `என் தேவனை`.

The artifact's SHA-256 is
`C4610F094F85A1530E4AD137412B1434E88A41A04686126E782E1AD3E989C344`.

## What the review found

All 40 candidates were human-reviewed in the installed app on 2026-08-31:
38 confirmed, 1 corrected (LUK 3:34, `translate-names`, whose correction
matched the proposal in every material field), 1 rejected (PHP 1:5,
translationWord `fellowship`, no reviewer note). Combined proposal agreement
was 95%. The full table and the interpretation of the two non-confirmed records
are in `docs/DEVELOPER_GUIDE.md`, "Historical Beta 15 developer handoff".

The per-project audit files that held the raw decisions
(`semanticValidation/irvtam-v0.1.json` under each Tamil IRV project) no longer
exist on any machine: those projects were re-imported after the #76 store
cutover, and a search on 2026-09-16 found no copy. The summary above is the
surviving record.

## What remains in the code

The Stage 3 mapping engine itself — `semantic_mapping.py`,
`semantic_mapping_bridge.py`, `semantic_mapping_service.py`,
`semantic_review_policy.py` — is still present and still feeds the AI review
pack in `ai_client.py`. The `semantic_validation_runs` table stays in the
workbench schema's v1 block (the ladder is never edited); nothing writes to it.
