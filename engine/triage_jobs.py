"""Background AI-triage run across the books of a translationCore collection.

Modeled on report_jobs.ReportJobManager and, like it, deliberately its own
lock domain: triage is optional and online, so it must never refuse to start
because a report build or a check job happens to be running, and must never
make either of those wait on a network call. The worker builds its own
TranslationCoreProject per sibling book and never touches
BridgeEngine.project, so the reviewer keeps working in whatever book they
have open while triage runs.

Unlike a report, triage has no payload to fetch at the end: every verdict is
persisted per book as it is produced (tc_ai_bridge/triage.py), so a run that
is cancelled or dies halfway still leaves everything it already paid for on
disk, and the report screen reads verdicts through triage.results rather
than from the job.
"""
from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


class TriageJobError(RuntimeError):
    pass


class TriageJobConflict(TriageJobError):
    pass


class TriageJobNotFound(TriageJobError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class TriageBook:
    path: str
    book_id: str
    book_name: str


# Given one TriageBook, a progress reporter and the job's cancel event,
# triage it and return the per-book summary run_book_triage produces. The
# cancel event is handed in rather than looked up afterwards so a cancel
# issued in the first instants of a run cannot be missed. Exceptions are
# caught by the manager and recorded against that book only.
RunBook = Callable[[TriageBook, "ProgressReporter", threading.Event], dict[str, Any]]


class ProgressReporter:
    """Handed to the worker so per-batch progress inside one book reaches the
    job snapshot without the triage module knowing what a job is."""

    def __init__(self, job: "_TriageJob", book: TriageBook) -> None:
        self._job = job
        self._book = book

    def __call__(self, completed: int, skipped: int, chapter: str) -> None:
        with self._job.lock:
            self._job.book_completed = completed
            self._job.book_skipped = skipped
            self._job.current_chapter = chapter or None


class _TriageJob:
    def __init__(self, books: tuple[TriageBook, ...], *, force: bool) -> None:
        self.id = str(uuid.uuid4())
        self.books = books
        self.force = force
        self.state = "queued"
        self.current_book: Optional[str] = None
        self.current_chapter: Optional[str] = None
        self.completed_books = 0
        # Progress within the book currently being triaged.
        self.book_completed = 0
        self.book_skipped = 0
        # Totals across books already finished.
        self.triaged = 0
        self.skipped = 0
        self.pruned = 0
        self.failed_batches = 0
        self.failed_books: list[dict[str, str]] = []
        self.summaries: list[dict[str, Any]] = []
        self.error: Optional[str] = None
        self.created_at = _now()
        self.finished_at: Optional[str] = None
        self.cancel_event = threading.Event()
        self.lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            total = len(self.books)
            percent = round((self.completed_books / total) * 100) if total else 100
            return {
                "jobId": self.id,
                "state": self.state,
                "force": self.force,
                "totalBooks": total,
                "completedBooks": self.completed_books,
                "percent": max(0, min(100, percent)),
                "currentBook": self.current_book,
                "currentChapter": self.current_chapter,
                # Findings triaged/skipped in the book in flight, so the UI can
                # show movement during a long single-book run.
                "currentBookTriaged": self.book_completed,
                "currentBookSkipped": self.book_skipped,
                "triaged": self.triaged,
                "skipped": self.skipped,
                "pruned": self.pruned,
                "failedBatches": self.failed_batches,
                "failedBooks": copy.deepcopy(self.failed_books),
                "books": copy.deepcopy(self.summaries),
                "error": self.error,
                "createdAt": self.created_at,
                "finishedAt": self.finished_at,
            }


class TriageJobManager:
    """Owns one active triage run at a time."""

    def __init__(self) -> None:
        self._jobs: dict[str, _TriageJob] = {}
        self._active_job_id: Optional[str] = None
        self._lock = threading.RLock()

    def active(self) -> Optional[dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(self._active_job_id or "")
        if job is None:
            return None
        snapshot = job.snapshot()
        return snapshot if snapshot["state"] not in TERMINAL_STATES else None

    def start(self, books: list[TriageBook], *, run_book: RunBook, force: bool = False) -> dict[str, Any]:
        with self._lock:
            active = self._jobs.get(self._active_job_id or "")
            if active is not None and active.state not in TERMINAL_STATES:
                raise TriageJobConflict(f"Triage run {active.id} is already {active.state}.")
            job = _TriageJob(tuple(books), force=force)
            self._jobs[job.id] = job
            self._active_job_id = job.id
            for stale_id in [jid for jid in self._jobs if jid != job.id]:
                del self._jobs[stale_id]

        thread = threading.Thread(
            target=self._run, args=(job, run_book),
            name=f"bridge-triage-{job.id[:8]}", daemon=True,
        )
        thread.start()
        return job.snapshot()

    def _resolve(self, job_id: str) -> _TriageJob:
        with self._lock:
            resolved_id = job_id or self._active_job_id or ""
            job = self._jobs.get(resolved_id)
        if job is None:
            raise TriageJobNotFound(f"Unknown triage job '{resolved_id}'.")
        return job

    def status(self, job_id: str = "") -> dict[str, Any]:
        return self._resolve(job_id).snapshot()

    def cancel(self, job_id: str = "") -> dict[str, Any]:
        job = self._resolve(job_id)
        with job.lock:
            if job.state not in TERMINAL_STATES:
                job.cancel_event.set()
                job.state = "cancelling"
        return job.snapshot()

    def _run(self, job: _TriageJob, run_book: RunBook) -> None:
        with job.lock:
            job.state = "running"
        for book in job.books:
            if job.cancel_event.is_set():
                break
            with job.lock:
                job.current_book = book.book_id
                job.current_chapter = None
                job.book_completed = 0
                job.book_skipped = 0
            try:
                summary = run_book(book, ProgressReporter(job, book), job.cancel_event)
            except Exception as exc:  # one book must not sink the whole run
                with job.lock:
                    job.failed_books.append({"bookId": book.book_id, "error": str(exc)})
                    job.completed_books += 1
                continue
            with job.lock:
                job.summaries.append({"bookId": book.book_id, "bookName": book.book_name, **summary})
                job.triaged += int(summary.get("triaged", 0) or 0)
                job.skipped += int(summary.get("skipped", 0) or 0)
                job.pruned += int(summary.get("pruned", 0) or 0)
                job.failed_batches += int(summary.get("failedBatches", 0) or 0)
                job.completed_books += 1

        with job.lock:
            if job.cancel_event.is_set():
                job.state = "cancelled"
            elif job.failed_books and not job.summaries:
                job.state = "failed"
                job.error = f"{len(job.failed_books)} book(s) could not be triaged."
            else:
                job.state = "succeeded"
                if job.failed_books:
                    job.error = f"{len(job.failed_books)} book(s) could not be triaged."
            job.current_book = None
            job.current_chapter = None
            job.finished_at = _now()
