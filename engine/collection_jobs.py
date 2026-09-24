"""Collection-level QA runs: every book of a multi-book collection, one after
another (layered-rules Phase 4.4, `collection.runChecks`).

Same shape as check_jobs.py: one active job, a worker thread, JSON-native
snapshots. The manager owns ordering, skipping, pause, cancel and timing; the
engine supplies the callables that do the work, so this module never opens a
project or runs a check itself:

- `run_book(book, cancel_event)` checks one book end to end (materializing a
  lazy sibling first) and returns its summary;
- `record_run(entry)` persists a finished book into `.bridge/collection.json`
  (`qaRuns[]`) so a later run can skip it;
- `final_stage(books, cancel_event)` runs the whole-collection passes once
  every book is done. Those write reports, never Scripture.

Resumable: a book whose recorded content hash matches its current chapter
files is skipped, so a run that was cancelled or crashed picks up where it
stopped. Pause takes effect between books; cancel stops the book in flight
after its current verse (the check job's own cancellation), and a cancelled
book records nothing, so no half-written result is ever kept.
"""
from __future__ import annotations

import copy
import hashlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


class CollectionJobError(RuntimeError):
    pass


class CollectionJobConflict(CollectionJobError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def book_content_hash(path: str | Path, book_id: str) -> str:
    """sha256 over a book's chapter JSON files, in chapter order: what a
    completed run is keyed by. Empty for a book with no chapter files yet (a
    lazy sibling), which never matches, so it is always run."""
    directory = Path(path) / book_id
    if not book_id or not directory.is_dir():
        return ""
    digest = hashlib.sha256()
    files = sorted((p for p in directory.glob("*.json") if p.stem.isdecimal()), key=lambda p: int(p.stem))
    if not files:
        return ""
    for chapter in files:
        digest.update(chapter.name.encode("utf-8"))
        digest.update(chapter.read_bytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class CollectionJobSpec:
    collection_path: str
    books: tuple[dict[str, Any], ...]
    checks: tuple[str, ...]
    # bookId -> the last completed run recorded for it (qaRuns[]).
    previous_runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    force: bool = False


RunBook = Callable[[dict[str, Any], threading.Event], dict[str, Any]]
RecordRun = Callable[[dict[str, Any]], None]
FinalStage = Callable[[list[dict[str, Any]], threading.Event], dict[str, Any]]


class _CollectionJob:
    def __init__(self, spec: CollectionJobSpec) -> None:
        self.id = str(uuid.uuid4())
        self.spec = spec
        self.state = "queued"
        self.paused = False
        self.current_book: Optional[str] = None
        self.books: list[dict[str, Any]] = [
            {"bookId": str(b.get("bookId") or ""), "bookName": str(b.get("bookName") or ""),
             "path": str(b.get("path") or ""), "state": "pending", "elapsedSeconds": None,
             "jobId": None, "findingsByCategory": {}, "checkedVerses": 0, "error": None,
             "completedAt": None}
            for b in spec.books
        ]
        self.final_stage: Optional[dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at = _now()
        self.finished_at: Optional[str] = None
        self.started_monotonic = time.monotonic()
        self.cancel_event = threading.Event()
        self.resume_event = threading.Event()
        self.resume_event.set()
        self.lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            done = [b for b in self.books if b["state"] in {"done", "skipped", "failed"}]
            timed = [b["elapsedSeconds"] for b in self.books if b["state"] == "done" and b["elapsedSeconds"]]
            remaining = sum(1 for b in self.books if b["state"] in {"pending", "running"})
            # The estimate uses measured books only: skipped ones took no time.
            estimate = round(sum(timed) / len(timed) * remaining, 1) if timed and remaining else None
            return {
                "jobId": self.id, "state": self.state, "paused": self.paused,
                "collectionPath": self.spec.collection_path, "checks": list(self.spec.checks),
                "totalBooks": len(self.books), "completedBooks": len(done),
                "percent": round(100 * len(done) / len(self.books)) if self.books else 100,
                "currentBook": self.current_book,
                "books": copy.deepcopy(self.books),
                "finalStage": copy.deepcopy(self.final_stage),
                "elapsedSeconds": round(time.monotonic() - self.started_monotonic, 1),
                "estimatedRemainingSeconds": estimate,
                "error": self.error, "createdAt": self.created_at, "finishedAt": self.finished_at,
            }


class CollectionJobManager:
    """One active collection run; completed snapshots are kept for status."""

    def __init__(self) -> None:
        self._jobs: dict[str, _CollectionJob] = {}
        self._active_id: Optional[str] = None
        self._lock = threading.RLock()

    def active(self) -> bool:
        with self._lock:
            job = self._jobs.get(self._active_id or "")
            return job is not None and job.state not in TERMINAL_STATES

    def start(self, spec: CollectionJobSpec, *, run_book: RunBook, record_run: RecordRun,
              final_stage: Optional[FinalStage] = None, book_hash: Callable[[dict[str, Any]], str] | None = None,
              ) -> dict[str, Any]:
        with self._lock:
            if self.active():
                raise CollectionJobConflict("A collection QA run is already in progress.")
            job = _CollectionJob(spec)
            self._jobs[job.id] = job
            self._active_id = job.id
        thread = threading.Thread(
            target=self._run, args=(job, run_book, record_run, final_stage, book_hash or (
                lambda book: book_content_hash(book.get("path", ""), str(book.get("bookId") or "")))),
            name=f"bridge-collection-{job.id[:8]}", daemon=True)
        thread.start()
        return job.snapshot()

    def _job(self, job_id: str = "") -> _CollectionJob:
        with self._lock:
            job = self._jobs.get(job_id or self._active_id or "")
        if job is None:
            raise CollectionJobError(f"Unknown collection QA run '{job_id}'.")
        return job

    def status(self, job_id: str = "") -> dict[str, Any]:
        return self._job(job_id).snapshot()

    def pause(self, paused: bool, job_id: str = "") -> dict[str, Any]:
        job = self._job(job_id)
        with job.lock:
            if job.state not in TERMINAL_STATES:
                job.paused = paused
                (job.resume_event.clear if paused else job.resume_event.set)()
        return job.snapshot()

    def cancel(self, job_id: str = "") -> dict[str, Any]:
        job = self._job(job_id)
        with job.lock:
            if job.state not in TERMINAL_STATES:
                job.cancel_event.set()
                job.resume_event.set()  # a paused run wakes up to stop
                job.state = "cancelling"
        return job.snapshot()

    def _run(self, job: _CollectionJob, run_book: RunBook, record_run: RecordRun,
             final_stage: Optional[FinalStage], book_hash: Callable[[dict[str, Any]], str]) -> None:
        with job.lock:
            job.state = "running"
        try:
            for index, book in enumerate(job.spec.books):
                job.resume_event.wait()
                if job.cancel_event.is_set():
                    return self._finish(job, "cancelled")
                row = job.books[index]
                content_hash = book_hash(book)
                previous = job.spec.previous_runs.get(row["bookId"]) or {}
                if (not job.spec.force and content_hash and previous.get("state") == "done"
                        and previous.get("contentHash") == content_hash
                        and set(previous.get("checks") or []) >= set(job.spec.checks)):
                    with job.lock:
                        row.update(state="skipped", findingsByCategory=previous.get("findingsByCategory") or {},
                                   completedAt=previous.get("completedAt"), jobId=previous.get("jobId"))
                    continue
                with job.lock:
                    row["state"] = "running"
                    job.current_book = row["bookId"]
                started = time.monotonic()
                try:
                    result = run_book(book, job.cancel_event)
                except Exception as exc:  # one book must not abort the collection
                    with job.lock:
                        row.update(state="failed", error=str(exc),
                                   elapsedSeconds=round(time.monotonic() - started, 2))
                    continue
                if job.cancel_event.is_set() or result.get("state") == "cancelled":
                    with job.lock:
                        row["state"] = "pending"  # nothing recorded: the next run redoes it
                    return self._finish(job, "cancelled")
                elapsed = round(time.monotonic() - started, 2)
                state = "done" if result.get("state") == "succeeded" else "failed"
                entry = {
                    "bookId": row["bookId"], "state": state, "completedAt": _now(),
                    "jobId": result.get("jobId"), "contentHash": book_hash(book),
                    "checks": list(job.spec.checks), "elapsedSeconds": elapsed,
                    "findingsByCategory": result.get("findingsByCategory") or {},
                    "checkedVerses": int(result.get("checkedVerses") or 0),
                }
                with job.lock:
                    row.update(state=state, elapsedSeconds=elapsed, jobId=entry["jobId"],
                               findingsByCategory=entry["findingsByCategory"], completedAt=entry["completedAt"],
                               checkedVerses=entry["checkedVerses"], error=result.get("error"))
                if state == "done":
                    try:
                        record_run(entry)
                    except Exception as exc:
                        with job.lock:
                            row["error"] = f"Run finished but was not recorded: {exc}"
            with job.lock:
                job.current_book = None
            if final_stage is not None and not job.cancel_event.is_set():
                with job.lock:
                    job.current_book = "(whole collection)"
                books = [dict(b) for b in job.books if b["state"] in {"done", "skipped"}]
                try:
                    stage = final_stage(books, job.cancel_event)
                except Exception as exc:
                    stage = {"error": str(exc)}
                with job.lock:
                    job.final_stage = stage
                    job.current_book = None
            if job.cancel_event.is_set():
                return self._finish(job, "cancelled")
            failed = [b for b in job.books if b["state"] == "failed"]
            self._finish(job, "failed" if failed else "succeeded",
                         f"{len(failed)} book(s) failed." if failed else None)
        except Exception as exc:
            self._finish(job, "failed", str(exc))

    @staticmethod
    def _finish(job: _CollectionJob, state: str, error: Optional[str] = None) -> None:
        with job.lock:
            job.state = state
            job.error = error
            job.current_book = None
            job.finished_at = _now()
