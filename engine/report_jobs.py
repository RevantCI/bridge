"""Background whole-collection QA report build.

Modeled on project_sweep.ProjectSweepManager and deliberately its own lock
domain: generating a report must never be refused because a Layer-1 sweep
or a chapter check job happens to be running, and vice versa. Like the
sweep, the worker builds its own TranslationCoreProject per sibling book
and never touches BridgeEngine.project, so the reviewer can keep working
in whatever book they have open while the report builds.

The finished report is held in memory on the job and fetched once with
report.get; report.status stays small enough to poll every half second
even when the report itself carries tens of thousands of rows.
"""
from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


class ReportJobError(RuntimeError):
    pass


class ReportJobConflict(ReportJobError):
    pass


class ReportJobNotFound(ReportJobError):
    pass


class ReportNotReady(ReportJobError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ReportBook:
    path: str
    book_id: str
    book_name: str
    lazy: bool = False
    missing: bool = False


# Given one ReportBook, return its finished per-book report dict (see
# qa_report.build_book_qa_report / unopened_book_report). Exceptions are
# caught by the manager and recorded on that book only.
BuildBook = Callable[[ReportBook], dict[str, Any]]
# Given every per-book report, return the collection payload.
Assemble = Callable[[list[dict[str, Any]]], dict[str, Any]]


class _ReportJob:
    def __init__(self, books: tuple[ReportBook, ...]) -> None:
        self.id = str(uuid.uuid4())
        self.books = books
        self.state = "queued"
        self.current_book: Optional[str] = None
        self.completed = 0
        self.failed_books: list[dict[str, str]] = []
        self.report: Optional[dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at = _now()
        self.finished_at: Optional[str] = None
        self.cancel_event = threading.Event()
        self.lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            total = len(self.books)
            percent = round((self.completed / total) * 100) if total else 100
            return {
                "jobId": self.id,
                "state": self.state,
                "totalBooks": total,
                "completedBooks": self.completed,
                "percent": max(0, min(100, percent)),
                "currentBook": self.current_book,
                "failedBooks": copy.deepcopy(self.failed_books),
                "error": self.error,
                "createdAt": self.created_at,
                "finishedAt": self.finished_at,
                "ready": self.report is not None,
            }


class ReportJobManager:
    """Owns one active report build at a time; the last finished report
    stays retrievable until the next build replaces it."""

    def __init__(self) -> None:
        self._jobs: dict[str, _ReportJob] = {}
        self._active_job_id: Optional[str] = None
        self._lock = threading.RLock()

    def start(self, books: list[ReportBook], *, build_book: BuildBook, assemble: Assemble) -> dict[str, Any]:
        with self._lock:
            active = self._jobs.get(self._active_job_id or "")
            if active is not None and active.state not in TERMINAL_STATES:
                raise ReportJobConflict(f"Report {active.id} is already {active.state}.")
            job = _ReportJob(tuple(books))
            self._jobs[job.id] = job
            self._active_job_id = job.id
            # Only the latest job is ever fetched; drop older payloads so a
            # long session doesn't accumulate whole-Bible reports in memory.
            for stale_id in [jid for jid in self._jobs if jid != job.id]:
                del self._jobs[stale_id]

        thread = threading.Thread(
            target=self._run, args=(job, build_book, assemble),
            name=f"bridge-report-{job.id[:8]}", daemon=True,
        )
        thread.start()
        return job.snapshot()

    def _resolve(self, job_id: str) -> _ReportJob:
        with self._lock:
            resolved_id = job_id or self._active_job_id or ""
            job = self._jobs.get(resolved_id)
        if job is None:
            raise ReportJobNotFound(f"Unknown report job '{resolved_id}'.")
        return job

    def status(self, job_id: str = "") -> dict[str, Any]:
        return self._resolve(job_id).snapshot()

    def get(self, job_id: str = "") -> dict[str, Any]:
        job = self._resolve(job_id)
        with job.lock:
            if job.report is None:
                raise ReportNotReady(f"Report job '{job.id}' is {job.state}; no report is available yet.")
            return {**job.snapshot(), "report": copy.deepcopy(job.report)}

    def cancel(self, job_id: str = "") -> dict[str, Any]:
        job = self._resolve(job_id)
        with job.lock:
            if job.state not in TERMINAL_STATES:
                job.cancel_event.set()
                job.state = "cancelling"
        return job.snapshot()

    def _run(self, job: _ReportJob, build_book: BuildBook, assemble: Assemble) -> None:
        with job.lock:
            job.state = "running"
        reports: list[dict[str, Any]] = []
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
                report = build_book(book)
            except Exception as exc:  # one unreadable book must not sink the whole report
                report = None
                with job.lock:
                    job.failed_books.append({"bookId": book.book_id, "error": str(exc)})
            if report is not None:
                reports.append(report)
            with job.lock:
                job.completed += 1
        try:
            payload = assemble(reports)
        except Exception as exc:
            with job.lock:
                job.state = "failed"
                job.error = f"Could not assemble the report: {exc}"
                job.current_book = None
                job.finished_at = _now()
            return
        with job.lock:
            job.report = payload
            job.state = "failed" if job.failed_books and not reports else "succeeded"
            if job.failed_books:
                job.error = f"{len(job.failed_books)} book(s) could not be read."
            job.current_book = None
            job.finished_at = _now()
