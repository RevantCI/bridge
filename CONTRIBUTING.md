# Contributing to Bridge

Bridge is maintained by two people. This document exists so that neither of us has to
hold the process in our heads, and so an idea, a decision and a commit can always be
traced to each other.

Read `CLAUDE.md` first if you are writing code — it holds the technical constraints.
This file is about the flow.

---

## The shape of it

```
  idea  ──►  Discussion  ──►  accepted issue  ──►  branch  ──►  PR  ──►  main
           (no promise)      (on the board)                    (reviewed)
```

The important line is the second arrow. **An idea becoming an issue is a decision, and
only the maintainer makes it.** That is the whole point of separating the two: ideas
should be cheap and plentiful, the board should be short and true.

## 1. Ideas

Post them in **Discussions → Ideas**. Anything goes there: half-formed, speculative,
"the AI suggested this", "a translator complained about". Nothing in Discussions is a
commitment by anyone, so there is no cost to being wrong.

Use the four prompts in the idea template:

- **Problem** — what goes wrong today, in one sentence
- **Who hits it** — a translator, a reviewer, a developer, or us
- **Smallest useful version** — what a first slice looks like
- **What it might break** — which stage, which schema, which existing behaviour

If the "who hits it" line can't be filled in with a real person doing real work, the
idea usually answers itself.

The maintainer triages Discussions weekly and does one of three things:

| Outcome | What happens |
|---|---|
| **Accept** | Promoted to an issue, labelled `status:accepted`, put on the board |
| **Later** | Stays a Discussion, labelled `later`, revisited at the next milestone |
| **No** | Closed with a reason, and the reason is recorded in `docs/DECISIONS.md` |

A "no" always gets a written reason. Undocumented rejections come back every few weeks
wearing a different hat.

## 2. Issues

**An issue means work we have agreed to do.** If it's on the board, it's real.

Every issue carries:

- `status:accepted` — set by the maintainer, the gate for starting work
- an `effort:` label — `easy` / `moderate` / `hard` / `very-hard` / `research-spike`
- an `area:` label — `frontend` / `engine` / `data-model` / `protocol` / `testing`

Research spikes are time-boxed to **one day**. Write the finding into the issue and
close it. An open-ended spike is a backlog leak.

Do not start work on an issue without `status:accepted`. Do not start work on someone
else's assigned issue without saying so in the thread.

## 3. Branches and commits

- Branch from `main`: `<issue-number>-short-description`, e.g. `51-breadcrumb-import-review`
- `main` is protected. No direct pushes, including by the maintainer.
- Commit messages: present tense, one line, what changed and why it matters.
  Reference the issue: `Fix breadcrumb returning imported project to Import Review (#51)`

## 4. Pull requests

Open a PR as soon as you have something to look at — draft is fine, and earlier is
better than polished. Fill in the template honestly; the two sections that matter are:

**What I verified myself.** Things you ran and watched happen. "Built the installer,
imported a project, clicked through the review queue, the findings appeared." Evidence.

**What I have not verified.** Things you believe because the code reads correctly, or
because a tool told you so. This is not a confession — it's the most useful part of the
review, because it tells the reviewer exactly where to look. When code is AI-assisted,
a fluent explanation of why something works is not the same as having seen it work, and
pretending otherwise is how a subtle bug reaches a translation team.

**Checks must be green.** CI runs the frontend checks, the Python suite and the Rust
tests on every PR. A failing check is not something to explain away in a comment.

**Review.** The maintainer reviews everything that touches the engine, the data model
or the analysis pipeline (enforced by `CODEOWNERS`). Frontend-only changes can be
merged after one pass. Nothing merges without a review, including the maintainer's own
work — a second pair of eyes on a two-person project is the only structural defence
there is.

**Merge.** Squash, with the issue number in the title. The commit log then doubles as
the changelog and feeds the weekly `HANDOFF.md` update.

## 5. Things that are not PR-sized

Open a Discussion and get an answer before writing code:

- schema changes
- re-baselining goldens
- anything adding a network dependency, an account or a login
- changing confidence thresholds or auto-apply behaviour
- switching or bundling the multilingual embedding model

These are listed again under *Stop and ask before writing any code* in
`CLAUDE.md`. They're repeated because they're the ones
that are cheapest to start and most expensive to undo.

## 6. The weekly rhythm

- **Friday, 30 minutes.** Maintainer updates `docs/HANDOFF.md` with what changed, what's
  in flight, and what the next person would need to know. Records any decisions made
  that week in `docs/DECISIONS.md`.
- **Friday triage.** New Discussions get accepted, deferred or closed with a reason.

That's the entire process. A two-person project doesn't need more, and anything more
will quietly stop being done.
