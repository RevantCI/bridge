# Decisions

Architectural and product decisions, newest first. Five lines each — this is a log, not
a design document.

Every entry answers: what was decided, why, and what it rules out. A decision with no
recorded reason gets re-litigated every few weeks, which is the thing this file exists
to prevent. Rejected ideas belong here too.

**Format**

```
## YYYY-MM-DD — Short title
**Decision:** what we are doing.
**Because:** the reason, including the alternative we didn't take.
**Rules out:** what this closes off, and what would have to change to reopen it.
**Revisit when:** a condition, or "not planned".
```

---

## 2026-09-11 — Ideas live in Discussions, the board holds accepted work only

**Decision:** New ideas go to Discussions → Ideas. They become issues only when the
maintainer accepts them and applies `status:accepted`.
**Because:** AI makes ideas nearly free to produce, and eleven filed in a single day sat
next to committed work and made the backlog unreadable. Separating them keeps ideas cheap
and the board honest.
**Rules out:** treating an open issue as "someone might do this one day". If it's on the
board, it's agreed.
**Revisit when:** the team grows past three people and triage becomes a bottleneck.

## 2026-09-11 — Offline-first is an invariant, not a default

**Decision:** No feature may require a network call, an account or a login on a path a
translator uses during normal work.
**Because:** the users are translation teams working in the field, often without reliable
internet. It is the product's actual differentiator.
**Rules out:** a hosted database as the primary store, server-side analysis, and
login-gated features. A collaborative Bridge has to be sync-based, not client-server.
**Revisit when:** never for the desktop app. A separate web product is a separate decision.

<!-- New entries go above this line. -->
