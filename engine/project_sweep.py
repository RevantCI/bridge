"""Background Layer-1 (deterministic) QA sweep across every book in a
translationCore collection.

Deliberately NOT built on check_jobs.CheckJobManager: that manager is
scoped to chapters/verses of the single project currently held in
BridgeEngine.project (the engine-wide "open in the UI" slot), and its
worker thread calls back into BridgeEngine methods that read that slot.
A whole-collection sweep instead constructs its own TranslationCoreProject
instance per sibling book and never touches BridgeEngine.project, so it can
run in the background while the user keeps editing the book they have open
without either job clobbering the other's notion of "the current project".
This is a first, intentionally simple slice (sequential, not resumable
across an app restart) — see GitHub issue #12 for the harder project-level
job coordinator this is expected to fold into.
"""
from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


class SweepError(RuntimeError):
    pass


class SweepConflict(SweepError):
    pass


class SweepNotFound(SweepError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SweepBook:
    path: str
    book_id: str
    book_name: str


# Given one SweepBook, return (findings-as-dicts, error-or-None) for that
# book. Errors are caught by the manager too, but a checker that wants to
# report a clean per-book message (rather than a raw exception string)
# can return one via the tuple instead of raising.
RunBook = Callable[[SweepBook], tuple[list[dict[str, Any]], Optional[str]]]


class _SweepJob:
    def __init__(self, books: tuple[SweepBook, ...]) -> None:
        self.id = str(uuid.uuid4())
        self.books = books
        self.state = "queued"
        self.current_book: Optional[str] = None
        self.results: dict[str, dict[str, Any]] = {}
        self.error: Optional[str] = None
        self.created_at = _now()
        self.finished_at: Optional[str] = None
        self.cancel_event = threading.Event()
        self.lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            total = len(self.books)
            completed = sum(
                1 for r in self.results.values() if r.get("status") in {"succeeded", "failed"}
            )
            percent = round((completed / total) * 100) if total else 0
            return {
                "jobId": self.id,
                "state": self.state,
                "totalBooks": total,
                "completedBooks": completed,
                "percent": max(0, min(100, percent)),
                "currentBook": self.current_book,
                "results": copy.deepcopy(self.results),
                "error": self.error,
                "createdAt": self.created_at,
                "finishedAt": self.finished_at,
            }


class ProjectSweepManager:
    """Owns one active whole-collection Layer-1 sweep at a time. A separate
    lock domain from CheckJobManager on purpose — a project-wide book sweep
    and a per-chapter verse-checking pass are different scopes of work and
    must be able to proceed independently."""

    def __init__(self) -> None:
        self._jobs: dict[str, _SweepJob] = {}
        self._active_job_id: Optional[str] = None
        self._lock = threading.RLock()

    def start(self, books: list[SweepBook], *, run_book: RunBook) -> dict[str, Any]:
        with self._lock:
            active = self._jobs.get(self._active_job_id or "")
            if active is not None and active.state not in TERMINAL_STATES:
                raise SweepConflict(f"Project sweep {active.id} is already {active.state}.")
            job = _SweepJob(tuple(books))
            self._jobs[job.id] = job
            self._active_job_id = job.id

        thread = threading.Thread(
            target=self._run, args=(job, run_book),
            name=f"bridge-sweep-{job.id[:8]}", daemon=True,
        )
        thread.start()
        return job.snapshot()

    def status(self, job_id: str = "") -> dict[str, Any]:
        with self._lock:
            resolved_id = job_id or self._active_job_id or ""
            job = self._jobs.get(resolved_id)
        if job is None:
            raise SweepNotFound(f"Unknown project sweep '{resolved_id}'.")
        return job.snapshot()

    def cancel(self, job_id: str = "") -> dict[str, Any]:
        with self._lock:
            resolved_id = job_id or self._active_job_id or ""
            job = self._jobs.get(resolved_id)
        if job is None:
            raise SweepNotFound(f"Unknown project sweep '{resolved_id}'.")
        with job.lock:
            if job.state not in TERMINAL_STATES:
                job.cancel_event.set()
                job.state = "cancelling"
        return job.snapshot()

    def _run(self, job: _SweepJob, run_book: RunBook) -> None:
        with job.lock:
            job.state = "running"
        for book in job.books:
            if job.cancel_event.is_set():
                with job.lock:
                    job.state = "cancelled"
                    job.current_book = None
                    job.finished_at = _now()
                return
            with job.lock:
                job.current_book = book.book_id
            try:
                findings, book_error = run_book(book)
            except Exception as exc:  # one book must not abort the whole sweep
                findings, book_error = [], str(exc)
            with job.lock:
                job.results[book.book_id] = {
                    "bookId": book.book_id,
                    "bookName": book.book_name,
                    "path": book.path,
                    "status": "failed" if book_error else "succeeded",
                    "findingCount": len(findings),
                    "findings": findings,
                    "error": book_error,
                }
        with job.lock:
            failed = [r for r in job.results.values() if r.get("status") == "failed"]
            job.state = "failed" if failed else "succeeded"
            job.error = f"{len(failed)} book(s) failed checking." if failed else None
            job.current_book = None
            job.finished_at = _now()
