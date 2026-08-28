"""VerseEvidence: one composed evidence package for a single chapter:verse.

Investigated first, per the project's standing rule against duplicating
existing resolution logic: tc_ai_bridge already resolves most of what a
verse-level evidence object needs, just scattered across independent call
sites that each re-derive a different subset —

  * ``ai_client.prepare_verse_review`` calls
    ``TranslationHelpsKnowledgeBase.evidence_pack_for_verse`` to build an
    AI-prompt-shaped (char-budgeted, citation-keyed) subset of tN/tW/tA
    evidence.
  * ``local_checks.py`` independently walks the same translationCore check
    entries to produce QAIssues.
  * ``project_import.py`` calls ``original_language_resources.
    source_tokens_for_verse`` once, at import time, to seed blank
    alignments — nothing reads it live for review/evidence display.
  * Alignment groups, human QA decisions, and resource versions are each
    loaded ad hoc wherever a caller happens to need them.

None of those is replaced here — retrofitting ``prepare_verse_review`` or
``local_checks.py`` to consume this object is a separate, larger, riskier
change to a working AI pipeline than this pass calls for. What this module
adds is the thing that didn't exist: ONE place that composes target
text/tokens, source tokens, alignment, translation-helps evidence, and
human decisions into a single object, reusing every one of the resolution
functions above rather than re-deriving any of them, so a future rule-based
checker or AI caller has one evidence-resolution path instead of building
its own.

Deliberately excludes cross-engine QaFindings (Wildebeest/USFM/names,
consistency) and AI review results — those live one layer up. This module
is pure tc_ai_bridge (no GreekRoomEngine dependency), so it can't see them;
BridgeEngine.get_verse_evidence resolves this first and attaches those two
pieces itself, since it's the only place that composes both engines.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .knowledge_base import TranslationHelpsKnowledgeBase
from .models import TokenRef, VerseAlignment
from .original_language_resources import source_tokens_for_verse
from .tc_project import TranslationCoreProject
from .usfm import whitespace_tokens


@dataclass
class VerseEvidence:
    project_id: str
    book_id: str
    target_language_id: str
    target_language_name: str
    target_direction: str
    chapter: str
    verse: str

    target_text: str
    target_tokens: list[str]
    source_tokens: list[TokenRef]

    alignment: VerseAlignment
    alignment_state: str  # "pending" | "completed" | "invalid" — see TranslationCoreProject.word_alignment_state

    # translationCore checking-tool entries (tN/tW) with their resolved
    # evidence text, straight from evidence_pack_for_verse's own 'checks'
    # list — same shape ai.explain sends the model, not re-derived here.
    translation_helps: list[dict[str, Any]]
    reference_bibles: list[dict[str, Any]]
    resource_provenance: dict[str, Any]
    resource_versions: dict[str, str]

    # issueKey -> decision record, from TranslationCoreProject.qa_decisions_for_verse
    human_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    resolved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "projectId": self.project_id,
            "bookId": self.book_id,
            "targetLanguageId": self.target_language_id,
            "targetLanguageName": self.target_language_name,
            "targetDirection": self.target_direction,
            "chapter": self.chapter,
            "verse": self.verse,
            "targetText": self.target_text,
            "targetTokens": list(self.target_tokens),
            "sourceTokens": [t.to_dict() for t in self.source_tokens],
            "alignment": self.alignment.to_dict(),
            "alignmentState": self.alignment_state,
            "translationHelps": self.translation_helps,
            "referenceBibles": self.reference_bibles,
            "resourceProvenance": self.resource_provenance,
            "resourceVersions": dict(self.resource_versions),
            "humanDecisions": self.human_decisions,
            "resolvedAt": self.resolved_at,
        }


def resolve_verse_evidence(
    project: TranslationCoreProject,
    chapter: str,
    verse: str,
    *,
    knowledge_base: Optional[TranslationHelpsKnowledgeBase] = None,
    resource_versions: Optional[dict[str, str]] = None,
) -> VerseEvidence:
    """Compose a VerseEvidence for one chapter:verse of `project`.

    `knowledge_base` may be passed in by a caller that already built one
    (evidence_pack_for_verse touches disk to resolve tA/lexicon content, not
    free) to avoid a redundant TranslationHelpsKnowledgeBase construction;
    a fresh one is built otherwise. `resource_versions` is accepted rather
    than recomputed here because the pinned-version lookup already lives on
    BridgeEngine (_pinned_resource_versions, added for QaFinding provenance)
    — this module has no reason to duplicate it, just to accept it.
    """
    target = project.manifest.get("target_language", {})
    target = target if isinstance(target, dict) else {}

    try:
        # TranslationHelpsKnowledgeBase.__init__ itself raises
        # KnowledgeBaseError when the bundled resources/en/translationHelps
        # folder isn't installed yet (e.g. a raw import that hasn't been
        # materialized, or the resources tree simply missing) — not just
        # evidence_pack_for_verse, so both need to be inside this guard.
        kb = knowledge_base if knowledge_base is not None else TranslationHelpsKnowledgeBase(project)
        pack = kb.evidence_pack_for_verse(chapter, verse)
    except Exception:
        # A verse with no resolvable checking-tool entries (or a project
        # missing translation-helps resources entirely) still has target
        # text, source tokens, and alignment worth returning — evidence
        # pack failure degrades translation_helps to empty, it doesn't
        # abort evidence resolution altogether.
        pack = {"resource_provenance": {}, "reference_bibles": [], "checks": []}

    target_text = project.target_verse_text(chapter, verse)
    raw_source_tokens = source_tokens_for_verse(project.book_id, chapter, verse)

    return VerseEvidence(
        project_id=str(project.summary.path),
        book_id=project.book_id,
        target_language_id=str(target.get("id") or ""),
        target_language_name=str(target.get("name") or ""),
        target_direction=str(target.get("direction") or ""),
        chapter=str(chapter),
        verse=str(verse),
        target_text=target_text,
        target_tokens=whitespace_tokens(target_text),
        source_tokens=[TokenRef.from_dict(t) for t in raw_source_tokens],
        alignment=project.load_verse_alignment(chapter, verse),
        alignment_state=project.word_alignment_state(chapter, verse),
        translation_helps=pack.get("checks", []) or [],
        reference_bibles=pack.get("reference_bibles", []) or [],
        resource_provenance=pack.get("resource_provenance", {}) or {},
        resource_versions=dict(resource_versions or {}),
        human_decisions=project.qa_decisions_for_verse(chapter, verse),
        resolved_at=project.timestamp_iso(),
    )
