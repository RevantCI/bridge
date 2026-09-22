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
from typing import Any

from .language_qa import RULE_VERSION, detect_language, scan_text

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
        self._cache: dict[str, tuple[str, str, dict[str, Any]]] = {}
        self._summary: dict[str, Any] = {"state": "idle", "findings": [], "limitations": []}

    def touch(self) -> None:
        self._foreground = time.monotonic()

    def bind(self, project: Any, *, blocked_reason: str = "") -> None:
        target = project.manifest.get("target_language", {})
        declared = str(target.get("id") or "") if isinstance(target, dict) else ""
        with self._lock:
            self._context = (str(project.path), project.book_id, declared, project.book_dir)
            self._cache.clear()
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
            self._summary = {"state": "idle", "findings": [], "limitations": []}

    def invalidate(self, chapter: str) -> None:
        with self._lock:
            self._cache.pop(str(chapter), None)
            self._schedule()

    def pause(self, paused: bool) -> dict[str, Any]:
        with self._lock:
            if self._blocked_reason:
                return self.status()
            self._paused = paused
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

    def status(self, *, offset: int = 0, limit: int = 0) -> dict[str, Any]:
        with self._lock:
            if (self._context and not self._paused and self._thread is None
                    and time.monotonic() - self._last_scan >= REFRESH_SECONDS):
                self._schedule()
            offset = max(0, int(offset))
            limit = max(0, min(100, int(limit)))
            findings = self._summary.get("findings", [])
            result = {k: v for k, v in self._summary.items() if k != "findings"}
            result.update({
                "projectPath": self._context[0] if self._context else "",
                "book": self._context[1] if self._context else "",
                "generation": self._generation, "ruleVersion": RULE_VERSION,
                "totalFindings": len(findings), "offset": offset,
                "findings": findings[offset:offset + limit],
                "coverage": "Enabled technical checks only; no grammar or publication certification.",
                "storage": "Session results; automatically regenerated on reopen.",
            })
            return copy.deepcopy(result)

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
        candidates = (p for p in directory.glob("*.json") if p.stem.isdecimal())
        paths = sorted(itertools.islice(candidates, MAX_CHAPTERS + 1), key=lambda p: int(p.stem))
        limitations: list[str] = []
        if len(paths) > MAX_CHAPTERS:
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
                    if isinstance(text, str) and "\\" not in text and verse[:1].isdigit():
                        sample += text[:20_000 - len(sample)]
                    if len(sample) >= 20_000:
                        break
            except (OSError, ValueError, UnicodeError):
                pass  # Main pass reports the exact chapter error.
            if len(sample) >= 20_000:
                break
        detection = detect_language(sample, declared)
        findings: list[dict[str, Any]] = []
        checked = skipped = reused = 0
        cache: dict[str, tuple[str, str, dict[str, Any]]] = {}
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
                if cached and cached[:2] == (digest, detection["pack"]):
                    chapter_result = cached[2]
                    reused += 1
                else:
                    chapter_result = {"findings": [], "limitations": [], "checked": 0, "skipped": 0}
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
                        if result["limitations"]:
                            chapter_result["skipped"] += 1
                            if len(chapter_result["limitations"]) < 20:
                                chapter_result["limitations"].extend(
                                    f"{verse}: {message}" for message in result["limitations"])
                        else:
                            chapter_result["checked"] += 1
                        room = MAX_BOOK_FINDINGS - len(findings) - len(chapter_result["findings"])
                        chapter_result["findings"].extend(result["findings"][:max(0, room)])
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
                limitations.extend(f"Chapter {path.stem}: {m}" for m in chapter_result["limitations"])
                if chapter_result["skipped"] and not chapter_result["limitations"]:
                    limitations.append(f"Chapter {path.stem}: non-verse or non-text entries omitted.")
                # Retry limited/omitted chapters on subsequent passes; a preceding
                # edit may have freed the book-wide result budget in the meantime.
                if not chapter_result["limitations"]:
                    cache[path.stem] = (digest, detection["pack"], chapter_result)
            except (OSError, ValueError, UnicodeError) as exc:
                limitations.append(f"Chapter {path.stem}: {exc}")
            if len(findings) >= MAX_BOOK_FINDINGS:
                limitations.append("Book finding limit reached; additional findings/chapters may be omitted.")
                break
            if len(limitations) >= 200:
                limitations = limitations[:200] + ["Diagnostic limit reached; remaining chapters omitted."]
                break
        with self._lock:
            if self._cancelled(generation):
                return None
            self._cache = cache
        return {"state": "completed", "language": detection, "findings": findings,
                "limitations": limitations, "incomplete": bool(limitations or skipped),
                "checkedVerses": checked, "skippedVerses": skipped,
                "reusedChapters": reused, "completedChapters": completed + 1,
                "totalChapters": len(paths)}

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
                    result["elapsedSeconds"] = round(time.monotonic() - started, 3)
                    self._summary = result
                self._last_scan = time.monotonic()
                self._thread = None
                return
