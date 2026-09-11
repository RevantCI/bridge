<!--
  Keep this honest rather than impressive. The "not verified" section is the most
  useful part of the whole template — it tells the reviewer where to look.
-->

## What this does

Closes #

One or two sentences. What changes for the person using Bridge?

---

## What I verified myself

Things you ran and watched work. Be specific — which project, which book, which screen.

- [ ] Built and ran the app locally
- [ ] Clicked through the affected screen(s)
- [ ] Ran the test suites locally

Notes:

---

## What I have **not** verified

Things you believe because the code reads correctly, a tool told you so, or it seemed
obvious. This is not a confession — it's the map of where review effort should go.

If any of this code was AI-assisted, be explicit about which parts you understood and
checked versus which parts you accepted. A fluent explanation of why something works
is not the same as having seen it work.

---

## Risk check

Tick anything this PR touches. Any tick is worth a conversation before it lands
(see *Stop and ask before writing any code* in `CLAUDE.md`).

- [ ] Companion database schema
- [ ] The correction ledger or token lineage
- [ ] Golden baselines under `engine/tests/fixtures/` (a re-baseline should do nothing else)
- [ ] Confidence thresholds or auto-apply behaviour
- [ ] Adds a network call, an account, or a login to a runtime path
- [ ] Analysis pipeline (Stages 5–9)
- [ ] None of the above

---

## Anything you noticed but didn't fix

Adjacent bugs, confusing code, missing tests. File them as ideas or issues rather than
folding them into this PR — but note them here so they don't get lost.
