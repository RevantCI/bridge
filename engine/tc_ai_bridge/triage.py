"""AI triage: score how likely each Greek Room finding is to be a false positive.

An overlay, never a gate. Triage reads findings that a check job already
persisted, asks a model to judge each one, and stores the verdict beside
them. Nothing in the offline check/report flow reads or waits for it, and a
finding's own status/severity is never rewritten — the report page uses the
score only to hide rows a reviewer asked it to hide.

Three properties this module exists to guarantee:

1. **A cached verdict is never re-bought.** Findings are keyed by
   ``triage_hash`` — a hash of the finding's *evidence*, not its id. A
   re-run over an unchanged book makes zero model calls. Deliberately NOT
   ``bridge_service._stable_finding_id``: that id must stay stable when a
   verse is edited so a human decision survives, whereas a verdict about
   evidence that changed is worthless and must be discarded.

2. **A malformed response never fails a run.** Providers behind
   ``api_base_url`` vary wildly in how well they honour a JSON schema;
   local vLLM/Ollama servers routinely wrap output in markdown fences. The
   parser strips fences and accepts several shapes; anything it still can't
   read marks that batch ``uncertain`` at confidence 0 and logs the raw text.

3. **A human override always wins and is never clobbered.** Overrides are
   skipped when batching, preserved by ``force``, and the merge re-reads the
   book file immediately before writing so an override recorded mid-run
   survives (the same lost-update class that ``.bridge/progress.json``
   currently has between its two writers).

Stdlib-only imports from the package's own leaves, so ``qa_report`` can
import this without an import cycle (``bridge_service`` imports
``qa_report``; see the duplicated ``stable_finding_id`` there for what that
constraint has already cost once).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import unicodedata
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from .original_language_resources import source_tokens_for_verse
from .tc_project import TranslationCoreProject
from .triage_prompts import DEFAULT_FAMILY, FAMILIES, family_for, instructions_for

log = logging.getLogger(__name__)

TRIAGE_SCHEMA_VERSION = 1

VERDICTS = ("true_positive", "false_positive", "uncertain")
OVERRIDE_VERDICTS = ("true_positive", "false_positive")

# One request per chapter x family, capped here. 25 keeps a batch's prompt
# well inside any reasonable context window even for verses with long
# evidence lists, and keeps the blast radius of one unparseable response to
# at most 25 findings marked uncertain.
MAX_BATCH = 25

# How many verses either side of the finding's own verse go into its context.
CONTEXT_RADIUS = 1

_WHITESPACE = re.compile(r"\s+")
# ```json ... ``` or ``` ... ```, with or without a trailing newline.
_FENCE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _norm(value: Any) -> str:
    """NFC + whitespace-collapsed, so a cached verdict survives a cosmetic
    reflow of the same text but not a real edit to it."""
    text = unicodedata.normalize("NFC", str(value or ""))
    return _WHITESPACE.sub(" ", text).strip()


def canonical_evidence(finding: dict[str, Any]) -> str:
    """The part of a finding whose change must invalidate a cached verdict.

    Offsets are deliberately excluded: the same flagged text shifting
    position because an earlier word was edited does not change the
    judgement, and re-buying every verdict in a verse after any edit
    anywhere in it would make the cache close to useless.
    """
    parts = [
        _norm(finding.get("original_text")),
        _norm(finding.get("suggested_replacement")),
        _norm(finding.get("explanation")),
    ]
    for item in finding.get("evidence") or []:
        if isinstance(item, dict):
            parts.append(f"{_norm(item.get('label'))}={_norm(item.get('value'))}")
        else:
            parts.append(_norm(item))
    return "".join(parts)


def triage_hash(*, book: str, chapter: str, verse: str, check_type: str,
                finding: dict[str, Any]) -> str:
    """Stable key for one finding's triage verdict.

    `chapter`/`verse` must be the caller's *row keys* — the strings the
    check-findings snapshot is keyed by, which preserve USFM verse bridges
    ("3-4") and segments ("3a"). QaFinding's own chapter/verse fields are
    ints that collapse both (finding.py:64-65, and see CLAUDE.md gotcha 12).
    """
    key = "|".join([
        str(book or "").strip().lower(),
        str(chapter or "").strip(),
        str(verse or "").strip(),
        str(check_type or "").strip(),
        canonical_evidence(finding),
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


# -- reading the findings triage operates on ------------------------------


def _finding_is_greek_room(finding: dict[str, Any]) -> bool:
    """Mirror qa_report._finding_category's greekRoom bucket.

    tN/tW rows are workflow state read live from translationCore's index,
    not checker output, and alignment-category rows are completion marks —
    neither is a "the checker may have cried wolf" judgement, so neither is
    worth spending a model call on.
    """
    return str(finding.get("category", "")) not in (
        "alignment", "translation_note", "translation_word",
    )


def persisted_findings(
    project: TranslationCoreProject, chapters: Iterable[str],
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    """{(chapter, verse): {finding id: finding}} from the chapter snapshots,
    then whatever the whole-book USFM/Names cache adds. The snapshot wins on
    a shared id (it carries the verse key the job used, which keeps bridged
    verses like '3-4' intact).

    Hoisted out of qa_report._BookReport so the report and the triage worker
    enumerate findings through exactly one code path — a divergence here
    would silently produce triage verdicts for rows the report never shows,
    or leave visible rows permanently untriaged.
    """
    by_verse: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for chapter in chapters:
        snapshot = project.load_check_findings_snapshot(chapter)
        for verse, findings in snapshot.items():
            bucket = by_verse.setdefault((str(chapter), str(verse)), {})
            for finding in findings or []:
                if isinstance(finding, dict) and finding.get("id"):
                    bucket.setdefault(str(finding["id"]), finding)
    cache = project.load_check_cache()
    for section in ("wildebeest", "usfm", "names"):
        for finding in (cache.get(section) or {}).get("findings", []) or []:
            if not isinstance(finding, dict) or not finding.get("id"):
                continue
            key = (str(finding.get("chapter", "")), str(finding.get("verse", "")))
            by_verse.setdefault(key, {}).setdefault(str(finding["id"]), finding)
    return by_verse


def triable_findings(
    project: TranslationCoreProject, chapters: Iterable[str],
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    """persisted_findings, minus everything triage has no business judging."""
    result: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for key, findings in persisted_findings(project, chapters).items():
        keep = {fid: f for fid, f in findings.items() if _finding_is_greek_room(f)}
        if keep:
            result[key] = keep
    return result


# -- batching -------------------------------------------------------------


class TriageItem:
    """One finding queued for a model call."""

    __slots__ = ("hash", "finding_id", "chapter", "verse", "check_type", "family", "finding")

    def __init__(self, *, hash: str, finding_id: str, chapter: str, verse: str,
                 check_type: str, family: str, finding: dict[str, Any]) -> None:
        self.hash = hash
        self.finding_id = finding_id
        self.chapter = chapter
        self.verse = verse
        self.check_type = check_type
        self.family = family
        self.finding = finding


def build_items(book_id: str, findings_by_verse: dict[tuple[str, str], dict[str, dict[str, Any]]]) -> list[TriageItem]:
    items: list[TriageItem] = []
    for (chapter, verse), findings in findings_by_verse.items():
        for finding_id, finding in findings.items():
            check_type = str(finding.get("check_type", "") or "")
            items.append(TriageItem(
                hash=triage_hash(book=book_id, chapter=chapter, verse=verse,
                                 check_type=check_type, finding=finding),
                finding_id=finding_id, chapter=chapter, verse=verse,
                check_type=check_type,
                family=family_for(check_type, str(finding.get("category", "") or "")),
                finding=finding,
            ))
    return items


def build_batches(items: list[TriageItem], max_batch: int = MAX_BATCH) -> list[list[TriageItem]]:
    """Group into one request per chapter x family, chunked to max_batch.

    Chapter-scoped so every finding in a batch shares nearby context and one
    unparseable response can only spoil one chapter's worth of one family;
    family-scoped because the prompt differs per family.
    """
    grouped: dict[tuple[str, str], list[TriageItem]] = {}
    for item in items:
        grouped.setdefault((item.chapter, item.family), []).append(item)

    batches: list[list[TriageItem]] = []
    for key in sorted(grouped, key=lambda k: (_chapter_sort_key(k[0]), k[1])):
        bucket = grouped[key]
        bucket.sort(key=lambda i: (_verse_sort_key(i.verse), i.finding_id))
        for start in range(0, len(bucket), max(1, max_batch)):
            batches.append(bucket[start:start + max(1, max_batch)])
    return batches


def _chapter_sort_key(chapter: str) -> tuple[int, str]:
    digits = re.findall(r"\d+", str(chapter))
    return (int(digits[0]) if digits else 9999, str(chapter))


def _verse_sort_key(verse: str) -> tuple[int, str]:
    digits = re.findall(r"\d+", str(verse))
    return (int(digits[0]) if digits else 9999, str(verse))


# -- context --------------------------------------------------------------


def _neighbour_verses(project: TranslationCoreProject, chapter: str, verse: str) -> list[str]:
    """The verse keys within CONTEXT_RADIUS of `verse` in `chapter`, in order,
    using the chapter's real verse list so bridges/segments are handled by
    position rather than by arithmetic on a number that may not exist."""
    try:
        verses = [str(v) for v in project.verses(chapter)]
    except Exception:
        return [str(verse)]
    if str(verse) not in verses:
        return [str(verse)]
    index = verses.index(str(verse))
    low = max(0, index - CONTEXT_RADIUS)
    high = min(len(verses), index + CONTEXT_RADIUS + 1)
    return verses[low:high]


def _aligned_source_words(project: TranslationCoreProject, chapter: str, verse: str) -> list[dict[str, str]]:
    """Source-language words for this verse, preferring the project's own
    alignment groups (the zaln/w data translationCore wrote) and falling back
    to the bundled original-language tokens when the verse is unaligned."""
    words: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    try:
        alignment = project.load_verse_alignment(chapter, verse)
    except Exception:
        alignment = None
    if alignment is not None:
        for group in alignment.alignments:
            for token in group.top_words:
                key = (str(token.word), str(token.occurrence))
                if key in seen:
                    continue
                seen.add(key)
                entry = {"word": str(token.word)}
                if getattr(token, "lemma", ""):
                    entry["lemma"] = str(token.lemma)
                if getattr(token, "strong", ""):
                    entry["strong"] = str(token.strong)
                if getattr(token, "morph", ""):
                    entry["morph"] = str(token.morph)
                targets = [str(t.word) for t in group.bottom_words]
                if targets:
                    entry["alignedTo"] = " ".join(targets)
                words.append(entry)
    if words:
        return words
    try:
        for raw in source_tokens_for_verse(project.book_id, chapter, verse) or []:
            if not isinstance(raw, dict) or not raw.get("word"):
                continue
            entry = {"word": str(raw["word"])}
            for field in ("lemma", "strong", "morph"):
                if raw.get(field):
                    entry[field] = str(raw[field])
            words.append(entry)
    except Exception:
        pass
    return words


def finding_context(project: TranslationCoreProject, item: TriageItem) -> dict[str, Any]:
    """Everything the model sees about one finding."""
    finding = item.finding
    evidence = [
        {"label": str(e.get("label", "")), "value": str(e.get("value", ""))}
        for e in (finding.get("evidence") or []) if isinstance(e, dict)
    ]
    verses: list[dict[str, str]] = []
    for neighbour in _neighbour_verses(project, item.chapter, item.verse):
        try:
            text = project.target_verse_text(item.chapter, neighbour)
        except Exception:
            continue
        verses.append({
            "ref": f"{item.chapter}:{neighbour}",
            "text": text,
            **({"isFindingVerse": True} if neighbour == item.verse else {}),
        })

    context: dict[str, Any] = {
        "finding_id": item.finding_id,
        "check_type": item.check_type,
        "engine": str(finding.get("engine", "") or ""),
        "severity": str(finding.get("severity", "") or ""),
        "flagged_text": str(finding.get("original_text", "") or ""),
        "explanation": str(finding.get("explanation", "") or ""),
        "target_verses": verses,
    }
    if finding.get("suggested_replacement"):
        context["suggested_replacement"] = str(finding["suggested_replacement"])
    if evidence:
        context["evidence"] = evidence
    source_words = _aligned_source_words(project, item.chapter, item.verse)
    if source_words:
        context["source_words"] = source_words
    return context


def build_batch_input(project: TranslationCoreProject, batch: list[TriageItem]) -> str:
    """The user-message payload for one batch."""
    book = project.book_id.upper()
    target = project.manifest.get("target_language", {})
    target = target if isinstance(target, dict) else {}
    payload = {
        "book": book,
        "target_language": str(target.get("name") or target.get("id") or "unknown"),
        "findings": [finding_context(project, item) for item in batch],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# -- response parsing -----------------------------------------------------


def strip_fences(text: str) -> str:
    """Remove one wrapping markdown code fence, if present."""
    match = _FENCE.match(str(text or ""))
    return match.group(1) if match else str(text or "")


def parse_triage_response(text: str) -> Optional[list[dict[str, Any]]]:
    """Parse a batch response into result dicts, or None if unreadable.

    Accepts, in order of how often providers actually produce them:
    ``{"results": [...]}``, a bare ``[...]``, and ``{"findings": [...]}``.
    Returns None rather than raising — the caller degrades the batch to
    `uncertain` and keeps going, because one bad response must not end a
    whole-Bible run.
    """
    raw = strip_fences(text).strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None

    rows: Any = None
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("results", "findings", "triage"):
            if isinstance(data.get(key), list):
                rows = data[key]
                break
    if not isinstance(rows, list):
        return None

    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        finding_id = str(row.get("finding_id") or row.get("findingId") or "").strip()
        verdict = str(row.get("verdict") or "").strip().lower()
        if not finding_id or verdict not in VERDICTS:
            continue
        parsed.append({
            "finding_id": finding_id,
            "verdict": verdict,
            "confidence": _clamp_confidence(row.get("confidence")),
            "reason": _norm(row.get("reason"))[:400],
        })
    return parsed or None


def _clamp_confidence(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    # Tolerate a provider that answers 0.0-1.0 instead of 0-100. A genuine
    # 1% confidence is indistinguishable from a 1.0 probability here, and
    # reading it as 100 would be the dangerous direction, so only values
    # strictly between 0 and 1 are rescaled.
    if 0.0 < number < 1.0:
        number *= 100.0
    return max(0, min(100, int(round(number))))


# -- records --------------------------------------------------------------


def make_record(item: TriageItem, result: dict[str, Any], model: str) -> dict[str, Any]:
    return {
        "findingId": item.finding_id,
        "chapter": item.chapter,
        "verse": item.verse,
        "checkType": item.check_type,
        "family": item.family,
        "verdict": result["verdict"],
        "confidence": int(result["confidence"]),
        "reason": result["reason"],
        "model": model,
        "timestamp": _now(),
        "userOverride": None,
    }


def unreadable_record(item: TriageItem, model: str) -> dict[str, Any]:
    return make_record(
        item,
        {"verdict": "uncertain", "confidence": 0,
         "reason": "The model's response for this batch could not be parsed."},
        model,
    )


def effective_verdict(record: dict[str, Any]) -> str:
    """A user override always wins over the model verdict."""
    override = record.get("userOverride")
    if isinstance(override, dict) and str(override.get("verdict") or "") in OVERRIDE_VERDICTS:
        return str(override["verdict"])
    return str(record.get("verdict") or "uncertain")


def is_cached(record: Any) -> bool:
    """Whether an existing entry means this finding need not be re-sent."""
    if not isinstance(record, dict):
        return False
    if isinstance(record.get("userOverride"), dict):
        return True
    return str(record.get("verdict") or "") in VERDICTS


# -- the run --------------------------------------------------------------


class TriageUnavailable(RuntimeError):
    """Triage cannot run at all (no API key, no reachable endpoint)."""


# Called with (completed_findings, skipped_findings, chapter) after each batch.
Progress = Callable[[int, int, str], None]


def run_book_triage(
    project: TranslationCoreProject,
    *,
    call_model: Callable[[str, str], str],
    model: str,
    lock: threading.RLock,
    force: bool = False,
    cancel: Optional[threading.Event] = None,
    progress: Optional[Progress] = None,
    on_usage: Optional[Callable[[], None]] = None,
) -> dict[str, Any]:
    """Triage every persisted Greek Room finding in one book.

    `call_model(instructions, input_text) -> raw text` is injected so the job
    layer owns client construction and the tests can run the whole path with
    no network. `lock` guards the book's triage file against a concurrent
    triage.override on the dispatcher thread.
    """
    chapters = [str(c) for c in project.chapters()]
    items = build_items(project.book_id, triable_findings(project, chapters))

    with lock:
        existing = project.load_triage_records()

    pending: list[TriageItem] = []
    skipped = 0
    for item in items:
        record = existing.get(item.hash)
        if isinstance(record, dict) and isinstance(record.get("userOverride"), dict):
            # An override survives force: the human already answered this.
            skipped += 1
            continue
        if not force and is_cached(record):
            skipped += 1
            continue
        pending.append(item)

    completed = 0
    failed_batches = 0
    if progress:
        progress(completed, skipped, "")

    for batch in build_batches(pending):
        if cancel is not None and cancel.is_set():
            break
        chapter = batch[0].chapter
        family = batch[0].family
        instructions = instructions_for(family)
        try:
            raw = call_model(instructions, build_batch_input(project, batch))
            results = parse_triage_response(raw)
        except Exception as exc:  # noqa: BLE001 - one batch must not end the run
            log.warning(
                "Triage batch failed (%s %s, family %s): %s",
                project.book_id, chapter, family, exc,
            )
            results = None
            raw = ""
        if on_usage is not None:
            try:
                on_usage()
            except Exception:  # noqa: BLE001 - usage accounting is never fatal
                pass

        if results is None:
            failed_batches += 1
            log.warning(
                "Triage response for %s %s (family %s) was unparseable; raw response: %r",
                project.book_id, chapter, family, str(raw)[:2000],
            )
            new_records = {item.hash: unreadable_record(item, model) for item in batch}
        else:
            by_id = {r["finding_id"]: r for r in results}
            new_records = {}
            for item in batch:
                result = by_id.get(item.finding_id)
                new_records[item.hash] = (
                    make_record(item, result, model) if result
                    else unreadable_record(item, model)
                )

        # Re-read under the lock so an override recorded while this batch was
        # in flight is preserved rather than overwritten by the stale copy
        # this worker loaded before the request.
        with lock:
            current = project.load_triage_records()
            for key, record in new_records.items():
                previous = current.get(key)
                if isinstance(previous, dict) and isinstance(previous.get("userOverride"), dict):
                    record["userOverride"] = previous["userOverride"]
                current[key] = record
            project.save_triage_records(current)

        completed += len(batch)
        if progress:
            progress(completed, skipped, chapter)

    cancelled = cancel is not None and cancel.is_set()
    pruned = 0
    if not cancelled:
        with lock:
            current = project.load_triage_records()
            live = {item.hash for item in items}
            stale = [key for key in current if key not in live]
            if stale:
                for key in stale:
                    del current[key]
                project.save_triage_records(current)
                pruned = len(stale)

    return {
        "bookId": project.book_id,
        "findings": len(items),
        "triaged": completed,
        "skipped": skipped,
        "pruned": pruned,
        "failedBatches": failed_batches,
        "cancelled": cancelled,
    }
