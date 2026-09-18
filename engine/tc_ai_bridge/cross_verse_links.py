"""Bridge-private cross-verse alignment links (#117).

translationCore alignment groups are verse-local: each verse's groups may only
contain that verse's own target tokens, and ``_validate_alignment_identity``
rejects anything else on every save. Bridge never fakes a cross-verse link
inside them (``semantic_alignment_guard.py``, INVARIANTS ss39). When a reviewer
sees that a source token of verse 3 is realized in verse 6's target text, that
judgement is recorded *here* -- table ``alignment_cross_verse_links`` in
``bridge-workbench.sqlite3`` -- and nowhere in ``alignmentData/``. The tC group
for the source token stays empty, the target word stays in its own verse's
word bank, and ``completionState`` never turns complete for either verse,
because aligned USFM cannot express the link.

Identity is the pair of tC token signatures (``word U+241F occurrence U+241F
occurrences``) plus chapter and verse on both sides. The positional
``H001``/``T001`` ids that ``make_inventory`` regenerates on every load are
resolved to signatures on the way in and back to ids on the way out; they are
never stored.

Every change is three writes: the row itself (``_write`` / ``_delete``, whose
change_log row image sync replays), a domain event on ``change_log``
(``crossVerseLink`` / ``crossVerseUnlink`` / ``crossVerseInvalidate``), and an
``alignment_history`` row *without* a ``backupPath`` -- so it is in the
per-verse history but invisible to ``alignment.restore``, which only restores
files. A link is marked ``invalid`` rather than deleted when a target text edit
removes the word it pointed at: the reviewer's judgement is kept for the
record and shown as no longer applicable.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .alignment_engine import AlignmentError
from .models import TokenRef
from .workbench_repository import natural_row_id

if TYPE_CHECKING:  # pragma: no cover
    from .tc_project import TranslationCoreProject

TABLE = "alignment_cross_verse_links"
STATE_ACTIVE = "active"
STATE_INVALID = "invalid"


def _end(chapter: str | int, verse: str | int, token: TokenRef, *, source: bool) -> dict[str, Any]:
    end: dict[str, Any] = {
        "chapter": str(chapter),
        "verse": str(verse),
        "word": token.word,
        "occurrence": int(token.occurrence),
        "occurrences": int(token.occurrences),
        "signature": token.signature,
    }
    if source:
        for key in ("strong", "lemma", "morph"):
            value = getattr(token, key, "")
            if value:
                end[key] = value
    return end


class CrossVerseLinkStore:
    """Reader/writer for one project's cross-verse links."""

    def __init__(self, project: "TranslationCoreProject") -> None:
        self.project = project

    # ---- identity -----------------------------------------------------------

    @property
    def _identity(self):
        return self.project.workbench_identity

    def _row_id(
        self, s_chapter: str, s_verse: str, s_signature: str,
        t_chapter: str, t_verse: str, t_signature: str,
    ) -> str:
        identity = self._identity
        return natural_row_id(
            identity.project_id, self.project.book_id, TABLE,
            s_chapter, s_verse, s_signature, t_chapter, t_verse, t_signature,
        )

    # ---- reads ----------------------------------------------------------------

    def links_for_verse(self, chapter: str | int, verse: str | int) -> list[dict[str, Any]]:
        """Every link touching a verse, as source or as target, oldest first."""
        identity = self._identity
        chapter, verse = str(chapter), str(verse)
        found: dict[str, dict[str, Any]] = {}
        for equals in (
            {"chapter": chapter, "verse": verse},
            {"target_chapter": chapter, "target_verse": verse},
        ):
            for payload in self.project.workbench.payloads(
                TABLE, project_id=identity.project_id, book_id=self.project.book_id, equals=equals,
            ):
                if isinstance(payload, dict) and payload.get("id"):
                    found[str(payload["id"])] = payload
        return sorted(found.values(), key=lambda item: (str(item.get("createdAt", "")), str(item["id"])))

    def active_links(self) -> list[dict[str, Any]]:
        """Every active link of this book, oldest first (#119: Stage 6B evidence)."""
        identity = self._identity
        payloads = self.project.workbench.payloads(
            TABLE, project_id=identity.project_id, book_id=self.project.book_id,
            equals={"state": STATE_ACTIVE},
        )
        return sorted(
            (p for p in payloads if isinstance(p, dict) and p.get("id")),
            key=lambda item: (str(item.get("createdAt", "")), str(item["id"])),
        )

    def digest(self) -> str:
        """Content digest over every link row of this book, active or invalid.

        Folded into `alignment_state_digest` (#119) so that Stage 6B's run
        fingerprint and `synchronize_alignment_state`'s staling memo both move
        when a link is added, removed or invalidated -- the same rule that
        makes a completion-marker change stale a cached location run.
        """
        import hashlib
        identity = self._identity
        rows = self.project.workbench.rows(
            TABLE, project_id=identity.project_id, book_id=self.project.book_id, order_by="id",
        )
        builder = hashlib.sha256()
        for row in rows:
            builder.update(
                f"{row['id']}␟{row.get('state')}␟{row.get('revision')}␟{row.get('updated_at')}".encode("utf-8")
            )
        return builder.hexdigest()

    def get(self, link_id: str) -> dict[str, Any] | None:
        row = self.project.workbench.get(TABLE, link_id)
        if row is None:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    # ---- writes ---------------------------------------------------------------

    def link(
        self,
        source_chapter: str | int, source_verse: str | int, source_token: TokenRef,
        target_chapter: str | int, target_verse: str | int, target_token: TokenRef,
        *, origin: str = "",
    ) -> dict[str, Any]:
        """Record that ``source_token`` (of verse A) is realized by ``target_token`` (of verse B).

        Re-linking an ``invalid`` pair reactivates it; re-linking an ``active``
        pair is refused, so a double drop cannot write two events.

        ``origin`` records what produced the link -- ``"ai-auto"`` for one an
        agreed model proposal applied without a per-link click (#146). It rides
        on the ``change_log`` event only, never on the row: the *fact* recorded
        is identical however it was reached, and a row column would be a schema
        bump for something only the audit trail needs. The event is append-only
        and can never be edited, which is exactly the property "who decided
        this?" wants.
        """
        source = _end(source_chapter, source_verse, source_token, source=True)
        target = _end(target_chapter, target_verse, target_token, source=False)
        row_id = self._row_id(
            source["chapter"], source["verse"], source["signature"],
            target["chapter"], target["verse"], target["signature"],
        )
        existing = self.get(row_id)
        if existing is not None and existing.get("state") == STATE_ACTIVE:
            raise AlignmentError(
                f"{source['word']} ({source['chapter']}:{source['verse']}) is already linked to "
                f"{target['word']} ({target['chapter']}:{target['verse']})."
            )
        now = self.project.workbench._now()
        payload = {
            "id": row_id,
            "bookId": self.project.book_id,
            "source": source,
            "target": target,
            "state": STATE_ACTIVE,
            "createdAt": existing.get("createdAt", now) if existing else now,
            "updatedAt": now,
            "actorId": self._identity.actor_id,
        }
        self._write_row(payload)
        self._event(
            row_id, "crossVerseLink",
            {**payload, "origin": origin} if origin else payload,
        )
        self._history(source["chapter"], source["verse"], "crossVerseLink", payload)
        return payload

    def unlink(self, link_id: str) -> dict[str, Any]:
        payload = self.get(link_id)
        if payload is None:
            raise AlignmentError("That cross-verse link no longer exists. Reload before removing it.")
        identity = self._identity
        self.project.workbench._delete(
            TABLE, link_id,
            project_id=identity.project_id, book_id=self.project.book_id,
            actor_id=identity.actor_id, device_id=identity.device_id,
        )
        self._event(link_id, "crossVerseUnlink", payload)
        self._history(payload["source"]["chapter"], payload["source"]["verse"], "crossVerseUnlink", payload)
        return payload

    def invalidate_missing_targets(
        self, chapter: str | int, verse: str | int, missing_signatures: set[str],
    ) -> list[dict[str, Any]]:
        """Mark every active link whose *target* word in this verse was removed
        by a text edit. Called by ``apply_scripture_edit`` with the signatures
        the reconcile step dropped; a word that survives the edit under the
        same signature keeps its link."""
        if not missing_signatures:
            return []
        chapter, verse = str(chapter), str(verse)
        invalidated: list[dict[str, Any]] = []
        for payload in self.links_for_verse(chapter, verse):
            target = payload.get("target", {})
            if payload.get("state") != STATE_ACTIVE:
                continue
            if target.get("chapter") != chapter or target.get("verse") != verse:
                continue
            if target.get("signature") not in missing_signatures:
                continue
            updated = dict(payload)
            updated["state"] = STATE_INVALID
            updated["invalidReason"] = (
                f"{target.get('word', '')} is no longer in the text of {chapter}:{verse}."
            )
            updated["updatedAt"] = self.project.workbench._now()
            self._write_row(updated)
            self._event(updated["id"], "crossVerseInvalidate", updated)
            self._history(updated["source"]["chapter"], updated["source"]["verse"], "crossVerseInvalidate", updated)
            invalidated.append(updated)
        return invalidated

    # ---- the three writes -----------------------------------------------------

    def _write_row(self, payload: dict[str, Any]) -> None:
        identity = self._identity
        source, target = payload["source"], payload["target"]
        self.project.workbench._write(
            TABLE, payload["id"],
            project_id=identity.project_id, book_id=self.project.book_id, payload=payload,
            actor_id=identity.actor_id, device_id=identity.device_id,
            expected_revision=None,
            extra_columns={
                "chapter": source["chapter"], "verse": source["verse"],
                "source_signature": source["signature"],
                "target_chapter": target["chapter"], "target_verse": target["verse"],
                "target_signature": target["signature"],
                "state": payload["state"],
            },
        )

    def _event(self, row_id: str, op: str, payload: dict[str, Any]) -> None:
        identity = self._identity
        self.project.workbench.append_event(
            TABLE, row_id,
            project_id=identity.project_id, book_id=self.project.book_id, op=op, payload=payload,
            actor_id=identity.actor_id, device_id=identity.device_id,
        )

    def _history(self, chapter: str, verse: str, operation: str, link: dict[str, Any]) -> None:
        # Same table and id shape as `_record_alignment_history`, deliberately
        # without `backupPath`: nothing on disk changed, so there is nothing to
        # restore, and `_alignment_history_entries` skips it for that reason.
        identity = self._identity
        iso, safe = self.project._timestamp()
        history_id = f"{safe}_{operation}.json"
        payload = {
            "id": history_id,
            "bookId": self.project.book_id,
            "chapter": str(chapter),
            "verse": str(verse),
            "operation": operation,
            "timestamp": iso,
            "link": link,
        }
        row_id = natural_row_id(
            identity.project_id, self.project.book_id, "alignment_history",
            str(chapter), str(verse), history_id,
        )
        self.project.workbench._write(
            "alignment_history", row_id,
            project_id=identity.project_id, book_id=self.project.book_id, payload=payload,
            actor_id=identity.actor_id, device_id=identity.device_id,
            expected_revision=None,
            extra_columns={"chapter": str(chapter), "verse": str(verse)},
        )
