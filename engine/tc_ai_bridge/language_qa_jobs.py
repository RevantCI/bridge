"""Disposable, bounded background Language QA. Never writes project files.

Workers exit after a pass; status polling discovers external edits. Generation
checks isolate edits, pause/resume and project switches from in-flight work.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import terminology
from .language_qa import (CROSSING_LIMITATION, INLINE_RULES, MAX_VERSE_CHARS, MAX_WORDLIST_TERMS,
                          RULE_VERSION, detect_language, lift_inline_usfm, scan_text,
                          stable_finding_id, word_occurrences, wordlist_findings)

MAX_CHAPTER_BYTES = 2 * 1024 * 1024
MAX_BOOK_FINDINGS = 3000
MAX_CHAPTERS = 1000
MAX_CHAPTER_VERSES = 2000
REFRESH_SECONDS = 15.0


class LanguageQaManager:
    def __init__(self, *, debounce: float = .75, yield_seconds: float = .02) -> None:
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._generation = 0
        self._context: tuple[str, str, str, Path] | None = None
        self._paused = False
        self._blocked_reason = ""
        self._foreground = 0.0
        self._last_deferral = 0.0
        self._last_scan = 0.0
        self._debounce = debounce
        self._yield_seconds = yield_seconds
        self._cache: dict[str, tuple[str, str, str, str, dict[str, Any]]] = {}
        self._source_signature: tuple[tuple[str, int, int], ...] | None = None
        self._paused_state: str | None = None
        self._terminology_loader: Callable[[], list[dict[str, Any]]] | None = None
        self._decisions_loader: Callable[[], list[dict[str, Any]]] | None = None
        self._summary: dict[str, Any] = {"state": "idle", "findings": [], "limitations": []}

    def touch(self) -> None:
        self._foreground = time.monotonic()

    def bind(self, project: Any, *, blocked_reason: str = "") -> None:
        target = project.manifest.get("target_language", {})
        declared = str(target.get("id") or "") if isinstance(target, dict) else ""
        with self._lock:
            self._context = (str(project.path), project.book_id, declared, project.book_dir)
            self._cache.clear()
            self._source_signature = None
            self._paused_state = None
            self._terminology_loader = getattr(project, "terminology_rules", None)
            self._decisions_loader = getattr(project, "project_qa_decisions", None)
            self._paused = bool(blocked_reason)
            self._blocked_reason = blocked_reason
            self._schedule()
            if blocked_reason:
                self._summary.update(state="failed", error=blocked_reason, incomplete=True,
                                     limitations=["Project recovery must complete before checking."])

    def unbind(self) -> None:
        with self._lock:
            self._context = None
            self._generation += 1
            self._wake.set()
            self._cache.clear()
            self._source_signature = None
            self._paused_state = None
            self._terminology_loader = None
            self._decisions_loader = None
            self._summary = {"state": "idle", "findings": [], "limitations": []}

    def invalidate(self, chapter: str) -> None:
        with self._lock:
            self._cache.pop(str(chapter), None)
            self._schedule()

    def invalidate_all(self) -> None:
        """Discard every chapter's cached result, not just one.

        For something book-wide that changed underneath Language QA rather
        than one chapter's text -- a termbase rule added or edited through
        Settings (#171). `_scan()` already recomputes `termbase_version`
        fresh every pass and would eventually bust every chapter's cache
        entry on its own the next time anything triggers a scan, but nothing
        else does that on its own when only the termbase changed -- the
        idle-refresh check only watches chapter file mtimes/sizes. Without
        this, a rule added via terminology.record would sit invisible until
        an unrelated edit happened to trigger a fresh pass.
        """
        with self._lock:
            self._cache.clear()
            self._schedule()

    def pause(self, paused: bool) -> dict[str, Any]:
        with self._lock:
            if self._blocked_reason:
                return self.status()
            was_paused = self._paused
            self._paused = paused
            if paused:
                # Stop scheduling work but keep the last results on screen —
                # pausing is not an invalidation, nothing found so far is wrong.
                self._generation += 1
                self._wake.set()
                if not was_paused:
                    self._paused_state = self._summary.get("state")
                self._summary["state"] = "paused"
                return self.status()
            resumable = (was_paused and self._context is not None
                        and self._paused_state == "completed")
            context = self._context
            generation = self._generation
        if resumable:
            # Nothing forced a real edit while paused. A content-limited
            # chapter (e.g. unbalanced inline USFM) never qualifies for _scan's cache,
            # so resuming unconditionally would redo that pass for the exact
            # same result — visible as the whole book restarting from zero.
            signature = self._chapter_signature(context[3])
            with self._lock:
                if (not self._paused and context == self._context
                        and generation == self._generation
                        and self._summary.get("state") == "paused"
                        and signature == self._source_signature):
                    self._summary["state"] = "completed"
                    self._last_scan = time.monotonic()
                    return self.status()
        with self._lock:
            self._schedule()
        return self.status()

    def _schedule(self) -> None:
        # Called under the small metadata lock; no filesystem work here.
        self._generation += 1
        self._wake.set()
        self._summary = {
            "state": "paused" if self._paused else "queued", "findings": [],
            "limitations": [], "completedChapters": 0, "totalChapters": 0,
        }
        if self._context and not self._paused and self._thread is None:
            self._thread = threading.Thread(target=self._run, name="language-qa", daemon=True)
            self._thread.start()

    def _refresh_if_due(self) -> None:
        """Idle-refresh probe shared by every poll: reschedule when chapter
        files changed on disk since the last completed pass (an external
        editor), at most once per REFRESH_SECONDS."""
        probe: tuple[int, tuple[str, str, str, Path]] | None = None
        with self._lock:
            if (self._context and not self._paused and self._thread is None
                    and time.monotonic() - self._last_scan >= REFRESH_SECONDS):
                # Reserve this refresh interval before touching the filesystem.
                # The stdio dispatcher is serial in production, but tests and
                # embedded clients may call status concurrently.
                self._last_scan = time.monotonic()
                probe = (self._generation, self._context)
        if probe is not None:
            generation, context = probe
            signature = self._chapter_signature(context[3])
            with self._lock:
                if (generation == self._generation and context == self._context
                        and not self._paused and self._thread is None
                        and signature != self._source_signature):
                    self._schedule()

    def inline(self, *, chapter: str | None = None) -> dict[str, Any]:
        """Every finding of an INLINE_RULES rule, for one chapter or the whole
        book -- not paged. The verse marks are drawn from this; status() is a
        page for the panel's list, and a page cannot back marks (a book with
        more findings than one page lost marks past it). Still bounded: the
        summary itself never holds more than MAX_BOOK_FINDINGS, and each
        verse contributes at most MAX_VERSE_FINDINGS."""
        self._refresh_if_due()
        with self._lock:
            wanted = None if chapter is None else str(chapter)
            findings = [
                f for f in self._summary.get("findings", [])
                if f.get("rule") in INLINE_RULES
                and (wanted is None or str(f.get("chapter")) == wanted)
            ]
            return copy.deepcopy({
                "projectPath": self._context[0] if self._context else "",
                "book": self._context[1] if self._context else "",
                "generation": self._generation,
                "state": self._summary.get("state", "idle"),
                "ruleVersion": RULE_VERSION, "chapter": wanted,
                "inlineRules": sorted(INLINE_RULES), "findings": findings,
            })

    def status(self, *, offset: int = 0, limit: int = 0) -> dict[str, Any]:
        self._refresh_if_due()
        with self._lock:
            offset = max(0, int(offset))
            limit = max(0, min(100, int(limit)))
            findings = self._summary.get("findings", [])
            result = {k: v for k, v in self._summary.items() if k != "findings"}
            result.update({
                "projectPath": self._context[0] if self._context else "",
                "book": self._context[1] if self._context else "",
                "generation": self._generation, "ruleVersion": RULE_VERSION,
                "inlineRules": sorted(INLINE_RULES),
                "totalFindings": len(findings), "offset": offset,
                "findings": findings[offset:offset + limit],
                "coverage": "Enabled technical checks only; no grammar or publication certification.",
                "storage": "Session results; automatically regenerated on reopen.",
            })
            return copy.deepcopy(result)

    @staticmethod
    def _chapter_signature(directory: Path) -> tuple[tuple[str, int, int], ...]:
        """Cheap change detector for idle polling; content is hashed by workers.

        Normal editor saves change size or mtime. A scan triggered by Bridge's
        edit hook or another invalidation still hashes content, so equal metadata
        can never make changed content reusable once a scan has been requested.
        """
        entries: list[tuple[str, int, int]] = []
        candidates = (p for p in directory.glob("*.json") if p.stem.isdecimal())
        for path in itertools.islice(candidates, MAX_CHAPTERS + 1):
            try:
                stat = path.stat()
                entries.append((path.name, stat.st_mtime_ns, stat.st_size))
            except OSError:
                entries.append((path.name, -1, -1))
        return tuple(sorted(entries))

    def _cancelled(self, generation: int) -> bool:
        return generation != self._generation or self._paused or self._context is None

    def _yield(self, generation: int) -> bool:
        if self._wake.wait(self._yield_seconds):
            return False
        # Requests never wait for the worker. Cap foreground deferral so regular
        # connector polling cannot starve checking indefinitely.
        now = time.monotonic()
        if now - self._foreground < .1 and now - self._last_deferral >= .5:
            self._last_deferral = now
            self._wake.wait(.05)
        return not self._cancelled(generation)

    @staticmethod
    def _read(path: Path) -> tuple[dict[str, Any], tuple[int, int], str]:
        before = path.stat()
        with path.open("rb") as stream:
            raw = stream.read(MAX_CHAPTER_BYTES + 1)
        if len(raw) > MAX_CHAPTER_BYTES:
            raise ValueError("Chapter exceeds 2 MiB; not checked.")
        after = path.stat()
        signature = (after.st_mtime_ns, after.st_size)
        if signature != (before.st_mtime_ns, before.st_size):
            raise ValueError("Chapter changed while being read; waiting for the next pass.")
        def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            data: dict[str, Any] = {}
            for key, value in pairs:
                if key in data:
                    raise ValueError(f"Duplicate chapter JSON key: {key!r}; not checked.")
                data[key] = value
            return data

        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_keys)
        if not isinstance(data, dict):
            raise ValueError("Chapter must contain a verse-keyed JSON object.")
        return data, signature, hashlib.sha256(raw).hexdigest()

    def _scan(self, generation: int, context: tuple[str, str, str, Path]) -> dict[str, Any] | None:
        _, book, declared, directory = context
        source_signature = self._chapter_signature(directory)
        candidates = (p for p in directory.glob("*.json") if p.stem.isdecimal())
        paths = sorted(itertools.islice(candidates, MAX_CHAPTERS + 1), key=lambda p: int(p.stem))
        limitations: list[str] = []
        truncated = len(paths) > MAX_CHAPTERS
        if truncated:
            limitations.append("Chapter limit reached; additional chapters omitted.")
            paths = paths[:MAX_CHAPTERS]
        if not paths:
            raise ValueError("No target chapter JSON files available for Language QA.")
        # Bounded sample across current target chapters, never original USFM.
        sample = ""
        for path in paths:
            if not self._yield(generation):
                return None
            try:
                data, _, _ = self._read(path)
                for verse, text in itertools.islice(data.items(), MAX_CHAPTER_VERSES):
                    if isinstance(text, str) and verse[:1].isdigit() and len(text) <= MAX_VERSE_CHARS:
                        lifted, _ = lift_inline_usfm(text)
                        if lifted is not None:
                            sample += lifted.visible[:20_000 - len(sample)]
                    if len(sample) >= 20_000:
                        break
            except (OSError, ValueError, UnicodeError):
                pass  # Main pass reports the exact chapter error.
            if len(sample) >= 20_000:
                break
        detection = detect_language(sample, declared)
        with self._lock:
            terminology_loader = self._terminology_loader
            decisions_loader = self._decisions_loader
        try:
            raw_terms = terminology_loader() if terminology_loader else []
        except Exception as exc:
            raw_terms = []
            limitations.append(f"Terminology unavailable: {exc}")
        term_index = terminology.TermIndex(raw_terms)
        try:
            raw_decisions = decisions_loader() if decisions_loader else []
        except Exception as exc:
            raw_decisions = []
            limitations.append(f"Decisions unavailable: {exc}")
        # Only terminology.deprecated-form findings ever consult this -- see
        # the per-verse block below. Not a general Language QA decision
        # framework; every other rule stays exactly as disposable as before.
        term_decisions = {
            str(row.get("issueKey", "")): str(row.get("decision", ""))
            for row in raw_decisions if isinstance(row, dict)
        }
        # A book-wide hash of the raw termbase and decisions, folded into the
        # per-chapter cache key below -- a curated term or a review decision
        # changing must invalidate every cached chapter's findings the same
        # way an edited chapter would, even though the chapter's own text is
        # untouched.
        termbase_version = hashlib.sha1(
            json.dumps(raw_terms, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        decisions_version = hashlib.sha1(
            json.dumps(term_decisions, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        findings: list[dict[str, Any]] = []
        checked = skipped = reused = 0
        cache: dict[str, tuple[str, str, str, str, dict[str, Any]]] = {}
        book_counts: dict[str, int] = {}
        book_first_seen: dict[str, tuple[str, str, int, int, str, str]] = {}
        for completed, path in enumerate(paths):
            if not self._yield(generation):
                return None
            with self._lock:
                if self._cancelled(generation):
                    return None
                self._summary.update(state="running", language=detection,
                                     completedChapters=completed, totalChapters=len(paths))
                cached = self._cache.get(path.stem)
            try:
                # Hash bounded input even when metadata is unchanged: copying or
                # restoring a file can preserve both its length and timestamp.
                data, signature, digest = self._read(path)
                if cached and cached[:4] == (digest, detection["pack"], termbase_version, decisions_version):
                    chapter_result = cached[4]
                    reused += 1
                else:
                    chapter_result = {"findings": [], "limitations": [], "checked": 0, "skipped": 0,
                                      "words": {}, "firstSeen": {}}
                    if len(data) > MAX_CHAPTER_VERSES:
                        chapter_result["limitations"].append("Chapter verse limit reached; remaining entries omitted.")
                    for verse, text in itertools.islice(data.items(), MAX_CHAPTER_VERSES):
                        if not self._yield(generation):
                            return None
                        if not verse[:1].isdigit() or not isinstance(text, str):
                            chapter_result["skipped"] += 1
                            continue
                        result = scan_text(text, book=book, chapter=path.stem, verse=verse,
                                           tamil=detection["pack"] == "tamil")
                        verse_limitations = list(result["limitations"])
                        if not result["checked"]:
                            chapter_result["skipped"] += 1
                        else:
                            chapter_result["checked"] += 1
                            if detection["pack"] == "tamil":
                                # Same visible text scan_text read; every span below is
                                # translated back to raw code points, and one that would
                                # cross lifted markup is dropped, as scan_text does.
                                lifted, _ = lift_inline_usfm(text)
                                assert lifted is not None  # scan_text checked this verse
                                crossing = 0
                                for word, w_start, w_end in word_occurrences(lifted.visible):
                                    span = lifted.raw_span(w_start, w_end)
                                    if span is None:
                                        continue  # a word split by markup is not one word
                                    chapter_result["words"][word] = chapter_result["words"].get(word, 0) + 1
                                    chapter_result["firstSeen"].setdefault(word, (
                                        path.stem, verse, *span, text[span[0]:span[1]], result["textHash"]))
                                term_occurrences: dict[tuple[str, str], int] = {}
                                for visible_match in terminology.find_deprecated_forms(lifted.visible, term_index):
                                    span = lifted.raw_span(visible_match["start"], visible_match["end"])
                                    if span is None:
                                        crossing += 1
                                        continue
                                    match = {**visible_match, "start": span[0], "end": span[1],
                                             "matchedText": text[span[0]:span[1]]}
                                    key = ("terminology.deprecated-form", match["matchedText"])
                                    term_occurrences[key] = term_occurrences.get(key, 0) + 1
                                    # Always advance the counter above, even when this
                                    # specific occurrence ends up suppressed below --
                                    # otherwise a later, undecided occurrence of the
                                    # same word in the same verse would shift onto a
                                    # different, unstable id once an earlier one is
                                    # ignored.
                                    finding_id = stable_finding_id(
                                        book, path.stem, verse, "terminology.deprecated-form",
                                        match["matchedText"], term_occurrences[key])
                                    # Only "ignored" is a sticky, deliberate reviewer
                                    # decision. "accepted" is an audit record of a past
                                    # Use action, not a standing verdict on this text --
                                    # the fix already removed the match naturally, and
                                    # if the identical deprecated text is reintroduced
                                    # later at the same position (same id, since the id
                                    # is where-based, not when-based) that is a new
                                    # violation, not a stale one. Suppressing it too was
                                    # a real bug, caught in desktop acceptance, not a
                                    # hypothetical.
                                    if term_decisions.get(finding_id) == "ignored":
                                        continue
                                    preferred = ", ".join(match["preferredRenderings"]) or "no preferred form recorded yet"
                                    note = f" {match['note']}" if match["note"] else ""
                                    chapter_result["findings"].append({
                                        "id": finding_id,
                                        "book": book, "chapter": path.stem, "verse": verse,
                                        "rule": "terminology.deprecated-form", "severity": "high",
                                        "start": match["start"], "end": match["end"],
                                        "originalText": match["matchedText"],
                                        "message": (f'"{match["matchedText"]}" is marked deprecated for '
                                                   f'{match["conceptId"]}. Preferred form: {preferred}.{note} '
                                                   f'Verify this occurrence.'),
                                        "textHash": result["textHash"], "ruleVersion": RULE_VERSION,
                                        "status": "review-needed",
                                        "suggestedReplacement": match["suggestedReplacement"],
                                    })
                                if crossing:
                                    verse_limitations.append(f"{crossing} terminology {CROSSING_LIMITATION}")
                        # A checked verse can still carry a limitation (a candidate
                        # crossing markup, the per-verse finding limit): report it, and
                        # keep the chapter out of the cache so it is retried.
                        if verse_limitations and len(chapter_result["limitations"]) < 20:
                            chapter_result["limitations"].extend(
                                f"{verse}: {message}" for message in verse_limitations)
                        # Same "ignored" is sticky, "accepted" is not distinction as the
                        # terminology block above, scoped narrowly to this one rule --
                        # not a general suppression framework for every scan_text rule.
                        # Filtered before the room slice, like the terminology block's
                        # own `continue`, so an ignored finding never consumes budget it
                        # will never use.
                        scan_findings = [
                            f for f in result["findings"]
                            if not (f["rule"] == "tamil.vallinam-missing"
                                    and term_decisions.get(f["id"]) == "ignored")
                        ]
                        room = MAX_BOOK_FINDINGS - len(findings) - len(chapter_result["findings"])
                        chapter_result["findings"].extend(scan_findings[:max(0, room)])
                        if len(result["findings"]) > room:
                            chapter_result["limitations"].append("Book finding limit reached; remaining verses omitted.")
                            break
                    final = path.stat()
                    if signature != (final.st_mtime_ns, final.st_size):
                        raise ValueError("Chapter changed during checking; waiting for the next pass.")
                # Even cached data is bounded by the current book's remaining room.
                room = MAX_BOOK_FINDINGS - len(findings)
                findings.extend(chapter_result["findings"][:room])
                checked += chapter_result["checked"]
                skipped += chapter_result["skipped"]
                for word, count in chapter_result["words"].items():
                    book_counts[word] = book_counts.get(word, 0) + count
                for word, location in chapter_result["firstSeen"].items():
                    book_first_seen.setdefault(word, location)
                limitations.extend(f"Chapter {path.stem}: {m}" for m in chapter_result["limitations"])
                if chapter_result["skipped"] and not chapter_result["limitations"]:
                    limitations.append(f"Chapter {path.stem}: non-verse or non-text entries omitted.")
                # Retry limited/omitted chapters on subsequent passes; a preceding
                # edit may have freed the book-wide result budget in the meantime.
                if not chapter_result["limitations"]:
                    cache[path.stem] = (digest, detection["pack"], termbase_version, decisions_version, chapter_result)
            except (OSError, ValueError, UnicodeError) as exc:
                limitations.append(f"Chapter {path.stem}: {exc}")
            if len(findings) >= MAX_BOOK_FINDINGS:
                limitations.append("Book finding limit reached; additional findings/chapters may be omitted.")
                truncated = True
                break
            if len(limitations) >= 200:
                limitations = limitations[:200] + ["Diagnostic limit reached; remaining chapters omitted."]
                truncated = True
                break
        # A truncated pass never opened every chapter, so a word that is genuinely
        # common in the unread tail would look artificially rare here -- exactly
        # the false-positive shape the rarity+similarity guardrail must prevent.
        if truncated:
            limitations.append("Wordlist audit skipped: book scan was truncated.")
        elif len(book_counts) > MAX_WORDLIST_TERMS:
            limitations.append("Wordlist audit skipped: too many distinct words to compare.")
        else:
            wordlist = wordlist_findings(book, book_counts, book_first_seen)
            room = MAX_BOOK_FINDINGS - len(findings)
            findings.extend(wordlist[:max(0, room)])
            if len(wordlist) > room:
                limitations.append("Book finding limit reached; wordlist audit findings omitted.")
        with self._lock:
            if self._cancelled(generation):
                return None
            self._cache = cache
        return {"state": "completed", "language": detection, "findings": findings,
                "limitations": limitations, "incomplete": bool(limitations or skipped),
                "checkedVerses": checked, "skippedVerses": skipped,
                "reusedChapters": reused, "completedChapters": completed + 1,
                "totalChapters": len(paths), "_sourceSignature": source_signature}

    def _run(self) -> None:
        while True:
            with self._lock:
                if self._paused or self._context is None:
                    self._thread = None
                    return
                generation, context = self._generation, self._context
                self._wake.clear()
            started = time.monotonic()
            try:
                result = None if self._wake.wait(self._debounce) else self._scan(generation, context)
            except Exception as exc:
                result = {"state": "failed", "error": str(exc), "findings": [],
                          "limitations": ["Language QA did not complete."], "incomplete": True}
            with self._lock:
                if generation != self._generation:
                    continue
                if result is not None:
                    source_signature = result.pop("_sourceSignature", None)
                    result["elapsedSeconds"] = round(time.monotonic() - started, 3)
                    self._summary = result
                    if source_signature is not None:
                        self._source_signature = source_signature
                self._last_scan = time.monotonic()
                self._thread = None
                return
