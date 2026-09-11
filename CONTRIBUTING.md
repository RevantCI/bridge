# Contributing to Bridge

Bridge is maintained by two people. This document exists so that neither of us has to
hold the process in our heads, and so an idea, a decision and a commit can always be
traced to each other.

Read `CLAUDE.md` first if you are writing code — it holds the technical constraints.
This file is about the flow.

---

## The shape of it

```
  idea  ──►  issue  ──►  triaged  ──►  commit on main
          (cheap, any)   (labelled)    (CI runs)
```

Deliberately short. A two-person project doesn't need more, and anything more will
quietly stop being done.

## 1. Ideas and issues

**Open an issue.** Use the **Idea** template for anything speculative — half-formed,
"the AI suggested this", "a translator complained about". There is no separate
proposal stage and no waiting: filing costs nothing and an unfiled idea is lost.

The template asks four things:

- **Problem** — what goes wrong today, in one sentence
- **Who hits it** — a translator, a reviewer, a developer, or us
- **Smallest useful version** — what a first slice looks like
- **What it might break** — which stage, which schema, which existing behaviour

If the "who hits it" line can't be filled in with a real person doing real work, the
idea usually answers itself.

The maintainer triages open issues and either lets them stand, or closes them with a
reason. **A closed issue always gets a written reason**, and if the reason is a real
decision rather than a shrug, it goes in `docs/DECISIONS.md`. Undocumented rejections
come back every few weeks wearing a different hat.

Labels, applied by hand during triage:

- `effort:` — `easy` / `moderate` / `hard` / `very-hard` / `research-spike`
- `area:` — `frontend` / `engine` / `data-model` / `protocol` / `testing`
- `wontfix` — closed on purpose, reason in the thread
- the `feature:` and `milestone:` labels group longer-running work

Research spikes are time-boxed to **one day**. Write the finding into the issue and
close it. An open-ended spike is a backlog leak.

Don't start work on someone else's assigned issue without saying so in the thread.

## 2. Commits

Work goes **directly onto `main`**. There is no branch protection and no required
review; branch only when you actually want one (a long change, or something you want
a second opinion on before it lands).

- Commit messages: present tense, one line, what changed and why it matters.
  Reference the issue: `Fix breadcrumb returning imported project to Import Review (#51)`
- Keep commits single-purpose. A commit that touches the engine, the schema and the
  UI at once can't be reviewed or reverted cleanly.
- Some things should not go straight to main without asking first — see §4.

## 3. CI

`.github/workflows/ci.yml` runs on every push to `main` and on every pull request:

| Job | Runs | Where |
|---|---|---|
| `frontend` | `npm run check`, `npm run test` | ubuntu |
| `engine` | the full pytest suite | windows |
| `rust` | `cargo test` | windows |
| `golden-notice` | warns if a Stage 5/6B golden moved | ubuntu |
| `ci-ok` | one aggregate status | ubuntu |

Jobs are path-filtered, so a docs-only commit doesn't pay for a 20-minute engine run,
and a change to `ci.yml` itself re-runs everything.

This is the only automated gate there is, so **a red run on `main` is not something to
explain away in a comment** — it is the last line of defence. `release.yml` builds the
installer on a tag and is not a gate: it never runs pytest, and its frozen-sidecar
smoke test is `continue-on-error` for a known pre-existing defect.

CI is not the whole story. `docs/QA_TEST_MATRIX.md` is the release gate, and a feature
isn't release-ready because its unit tests pass — check the matrix's source, frozen and
desktop rows.

## 4. Things to ask about before writing code

Open an issue and get an answer first:

- schema changes (the companion database is at v14)
- re-baselining a golden
- anything adding a network dependency, an account or a login to a runtime path
- changing confidence thresholds or auto-apply behaviour
- a second Scripture writer, or another path for applying corrections to the text
- switching or bundling the multilingual embedding model

These are listed again under *Stop and ask before writing any code* in `CLAUDE.md`.
They're repeated because they're the ones that are cheapest to start and most
expensive to undo.

## 5. Pull requests, when you open one

PRs are optional here, but the template is worth filling in when you do, because the
two sections that matter aren't about the code:

**What I verified myself.** Things you ran and watched happen. "Built the installer,
imported a project, clicked through the review queue, the findings appeared." Evidence.

**What I have not verified.** Things you believe because the code reads correctly, or
because a tool told you so. This is not a confession — it's the most useful part of the
review, because it tells the reviewer exactly where to look. When code is AI-assisted, a
fluent explanation of why something works is not the same as having seen it work, and
pretending otherwise is how a subtle bug reaches a translation team.

The same split is worth putting in a commit message for anything substantial that goes
straight to main.

## 6. The weekly rhythm

- **Friday, 30 minutes.** Maintainer updates `docs/HANDOFF.md` with what changed, what's
  in flight, and what the next person would need to know. Records any decisions made
  that week in `docs/DECISIONS.md`.
- **Friday triage.** New issues get labelled, or closed with a reason.
