"""Cancellable background jobs for evidence-grounded tN/tW AI review.

The worker is deliberately local to Bridge rather than using a provider's
remote background mode.  This keeps OpenAI-compatible providers working and
lets the sidecar remain responsive while a chapter or book is processed.
Cancellation is cooperative between verses and model calls; a request already
in flight is allowed to finish, then its result is discarded if cancelled.
"""
from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional


TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


class AIReviewJobError(RuntimeError):
    pass


class AIReviewJobConflict(AIReviewJobError):
    pass


class AIReviewJobNotFound(AIReviewJobError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AIReviewJobSpec:
    scope: str
    mode: str
    project_path: str
    chapters: tuple[str, ...]
    chapter_verses: dict[str, list[str]]
    skipped_current: int = 0
    resume_of: str = ""


class _AIReviewJob:
    def __init__(self, spec: AIReviewJobSpec) -> None:
        self.id = str(uuid.uuid4())
        self.spec = spec
        self.state = "queued"
        self.current_chapter: Optional[str] = None
        self.current_verse: Optional[str] = None
        self.current_stage = "Queued"
        self.current_verse_percent = 0
        self.results: dict[str, dict[str, Any]] = {}
        self.latest_result_key: Optional[str] = None
        self.latest_result: Optional[dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at = _now()
        self.finished_at: Optional[str] = None
        self.cancel_event = threading.Event()
        self.lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            total = sum(len(values) for values in self.spec.chapter_verses.values())
            completed = sum(
                1 for item in self.results.values()
                if item.get("status") in {"succeeded", "failed"}
            )
            in_flight = self.current_verse_percent / 100 if self.current_verse else 0
            percent = 100 if self.state == "succeeded" else round(
                ((completed + in_flight) / total) * 100
            ) if total else 0
            compact_results = {
                key: {
                    "chapter": item.get("chapter"), "verse": item.get("verse"),
                    "status": item.get("status"), "error": item.get("error"),
                    "summary": item.get("summary", ""),
                    "appliedCount": len(item.get("appliedSelections") or []),
                    "skippedCount": len(item.get("skippedSelections") or []),
                    "usage": copy.deepcopy(item.get("usage") or {}),
                }
                for key, item in self.results.items()
            }
            return {
                "jobId": self.id,
                "scope": self.spec.scope,
                "mode": self.spec.mode,
                "projectPath": self.spec.project_path,
                "state": self.state,
                "chapters": list(self.spec.chapters),
                "chapterVerses": copy.deepcopy(self.spec.chapter_verses),
                "skippedCurrentVerses": self.spec.skipped_current,
                "resumeOf": self.spec.resume_of,
                "totalVerses": total,
                "completedVerses": completed,
                "failedVerses": sum(
                    1 for item in self.results.values() if item.get("status") == "failed"
                ),
                "percent": max(0, min(100, percent)),
                "currentChapter": self.current_chapter,
                "currentVerse": self.current_verse,
                "currentStage": self.current_stage,
                "results": compact_results,
                # Only one full evidence bundle crosses the polling boundary.
                # Older full results live in the per-verse companion cache.
                "latestResult": (
                    {"key": self.latest_result_key, "result": copy.deepcopy(self.latest_result)}
                    if self.latest_result_key and self.latest_result is not None else None
                ),
                "error": self.error,
                "createdAt": self.created_at,
                "finishedAt": self.finished_at,
            }


Progress = Callable[[int, str], None]
RunVerse = Callable[[str, str, str, Progress, threading.Event], dict[str, Any]]


class AIReviewJobManager:
    """Own one active AI pass and retain terminal jobs for retry/audit."""

    def __init__(self) -> None:
        self._jobs: dict[str, _AIReviewJob] = {}
        self._active_job_id: Optional[str] = None
        self._lock = threading.RLock()

    def start(self, spec: AIReviewJobSpec, *, run_verse: RunVerse) -> dict[str, Any]:
        if spec.mode not in {"basic", "advanced"}:
            raise AIReviewJobError("AI reviewer mode must be basic or advanced.")
        if spec.scope not in {"verse", "chapter", "book"}:
            raise AIReviewJobError("AI review scope must be verse, chapter, or book.")
        with self._lock:
            active = self._jobs.get(self._active_job_id or "")
            if active is not None and active.state not in TERMINAL_STATES:
                raise AIReviewJobConflict(f"AI review job {active.id} is already {active.state}.")
            job = _AIReviewJob(spec)
            self._jobs[job.id] = job
            self._active_job_id = job.id
        threading.Thread(
            target=self._run,
            args=(job, run_verse),
            name=f"bridge-ai-review-{job.id[:8]}",
            daemon=True,
        ).start()
        return job.snapshot()

    def status(self, job_id: str = "") -> dict[str, Any]:
        with self._lock:
            resolved = job_id or self._active_job_id or ""
            job = self._jobs.get(resolved)
        if job is None:
            raise AIReviewJobNotFound(f"Unknown AI review job '{resolved}'.")
        return job.snapshot()

    def cancel(self, job_id: str = "") -> dict[str, Any]:
        with self._lock:
            resolved = job_id or self._active_job_id or ""
            job = self._jobs.get(resolved)
        if job is None:
            raise AIReviewJobNotFound(f"Unknown AI review job '{resolved}'.")
        with job.lock:
            if job.state not in TERMINAL_STATES:
                job.cancel_event.set()
                job.state = "cancelling"
                job.current_stage = "Cancelling after current AI request"
        return job.snapshot()

    def spec_for_retry(self, job_id: str) -> AIReviewJobSpec:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise AIReviewJobNotFound(f"Unknown AI review job '{job_id}'.")
        with job.lock:
            if job.state not in {"failed", "cancelled"}:
                raise AIReviewJobConflict("Only failed or cancelled AI review jobs can be retried.")
            remaining = {
                chapter: [
                    verse for verse in job.spec.chapter_verses.get(chapter, [])
                    if job.results.get(f"{chapter}:{verse}", {}).get("status") != "succeeded"
                ]
                for chapter in job.spec.chapters
            }
            return AIReviewJobSpec(
                scope=job.spec.scope,
                mode=job.spec.mode,
                project_path=job.spec.project_path,
                chapters=job.spec.chapters,
                chapter_verses=remaining,
                skipped_current=job.spec.skipped_current + sum(
                    1 for item in job.results.values() if item.get("status") == "succeeded"
                ),
                resume_of=job.id,
            )

    def _run(self, job: _AIReviewJob, run_verse: RunVerse) -> None:
        with job.lock:
            job.state = "running"
        try:
            for chapter in job.spec.chapters:
                for verse in job.spec.chapter_verses.get(chapter, []):
                    if self._cancelled(job):
                        return
                    key = f"{chapter}:{verse}"

                    def progress(percent: int, stage: str) -> None:
                        with job.lock:
                            job.current_verse_percent = max(0, min(100, int(percent)))
                            job.current_stage = str(stage)

                    with job.lock:
                        job.current_chapter = chapter
                        job.current_verse = verse
                        job.current_verse_percent = 0
                        job.current_stage = "Preparing AI review"
                    try:
                        payload = run_verse(chapter, verse, job.spec.mode, progress, job.cancel_event)
                        if self._cancelled(job):
                            return
                        result = {
                            "summary": "", "checkReviews": [], "qaIssues": [],
                            "alignmentProposal": None, "alignmentWasAIProposed": False,
                            "appliedSelections": [], "skippedSelections": [], "usage": {},
                        }
                        result.update(copy.deepcopy(payload))
                        result.update({"chapter": chapter, "verse": verse, "status": "succeeded", "error": None})
                    except Exception as exc:  # one bad verse must not discard a chapter/book pass
                        # A cooperative worker may notice cancellation after its
                        # provider request returns and raise instead of returning
                        # a payload. That is still cancellation, not a failed
                        # verse, and no completed model result may be retained.
                        if self._cancelled(job):
                            return
                        result = {
                            "chapter": chapter, "verse": verse, "status": "failed",
                            "summary": "", "checkReviews": [], "qaIssues": [],
                            "alignmentProposal": None, "alignmentWasAIProposed": False,
                            "appliedSelections": [], "skippedSelections": [], "usage": {},
                            "error": str(exc),
                        }
                    with job.lock:
                        job.results[key] = result
                        job.latest_result_key = key
                        job.latest_result = result
                        job.current_verse_percent = 0

            with job.lock:
                failed = [item for item in job.results.values() if item.get("status") == "failed"]
                job.state = "failed" if failed else "succeeded"
                job.error = f"{len(failed)} verse(s) failed AI review." if failed else None
                job.current_stage = "AI review failed" if failed else "Complete"
                job.current_chapter = None
                job.current_verse = None
                job.finished_at = _now()
        except Exception as exc:
            if self._cancelled(job):
                return
            with job.lock:
                job.state = "failed"
                job.error = str(exc)
                job.current_stage = "AI review failed"
                job.finished_at = _now()

    @staticmethod
    def _cancelled(job: _AIReviewJob) -> bool:
        if not job.cancel_event.is_set():
            return False
        with job.lock:
            job.state = "cancelled"
            job.current_stage = "Cancelled"
            job.current_chapter = None
            job.current_verse = None
            job.current_verse_percent = 0
            job.finished_at = _now()
        return True
