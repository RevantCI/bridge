# Where the checks Language QA does not make happen

Language QA is an offline check of the **target text alone**. Some things it
never checks, because they need the source text, a reference translation, or
human judgement (layered-rules Phase 7):

| Not checked by Language QA | Where it is checked |
|---|---|
| Agreement: திணை, பால், எண் (subject–verb, person, gender, number) | The Round 2 linguistic review pass (the proofreader) |
| Pronoun and number shifts against the source | Round 2 review and the consultant; Bridge's semantic review (Stages 6B–8) shows the evidence |
| Meaning shifts | The consultant; Stage 7 meaning analysis in the 9A review queue shows candidates |
| Source words missed or added | The consultant; Stage 8 source coverage in the 9A review queue |
| Textual-basis differences | The consultant (textual-basis review) |
| Theological consistency | The consultant, with the termbase and tW as evidence |

The full picture, with who owns each item before publication, is
`docs/LANGUAGE_QA_TAMIL_SPECIFICATION.md` (Gates 1–3).

**This page is a placeholder for the project's own Round 2 review procedure.**
For the IRV Tamil project, that procedure is the Round 2 proofreading
workflow: the reports under the project's review folder, including the Joel
Round 2 master workflow. A project with its own written procedure should
link it here.

For a developer: none of these belongs in the offline engine. If a task asks
for one of them to be checked offline, stop and point to this page and to
`LANGUAGE_QA_PLAN.md` (LQA-3). It is an architecture question, not an
implementation detail.
