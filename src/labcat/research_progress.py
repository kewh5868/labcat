"""Transient server-owned progress, without prompts, credentials or
model prose."""

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import UUID, uuid4

PHASES = {
    "preparing": "Preparing this research request and its chat context.",
    "profile": "Selecting ranking preferences for this question.",
    "intake": "Checking the request against the research safeguards.",
    "model": "The connected model is assessing the research request.",
    "discovery": "Searching public indexes for relevant materials and publications.",
    "candidate_review": (
        "Identifying materials mentioned in the retrieved public sources."
    ),
    "repositories": "Retrieving candidate identities and properties from repositories.",
    "literature": "Checking open-access literature for missing material properties.",
    "ranking": "Comparing retrieved evidence against the selected ranking preferences.",
    "formatting": "Preparing the Summary and Technical Overview.",
    "saving": "Saving this response and any linked sources.",
    "structures": "Finding reference structures for the shortlisted materials.",
    "completed": "Request finished. The response is ready in this chat.",
    "failed": "This request could not finish. Check the chat error before retrying.",
}
_observer = ContextVar("research_progress_observer", default=None)


def current_observer():
    """Capture the server callback when constructing a cross-thread tool
    session."""
    return _observer.get()


@contextmanager
def progress_observer(observer):
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


class ResearchInProgress(ValueError):
    """Prevent overlapping submissions or accidental replay in a single
    chat."""


def report_progress(phase: str):
    """Called by trusted code only when an actual pipeline phase
    begins."""
    if phase not in PHASES:
        raise ValueError("Unsupported research phase.")
    observer = _observer.get()
    if observer is not None:
        observer(phase)


class ResearchProgress:
    """One backend process's recent runs; completed entries may be
    evicted."""

    def __init__(self):
        self._lock = threading.RLock()
        self._runs = {}
        self._admitting = set()

    def snapshot(self, chat_id: str, run_id: str | None = None):
        with self._lock:
            row = self._runs.get(chat_id)
            if row is not None and (run_id is None or row["run_id"] == run_id):
                return row.copy()
        return {
            "run_id": None,
            "status": "idle",
            "phase": "idle",
            "message": "Waiting for this request to start.",
            "started_at": None,
            "updated_at": None,
            "sequence": 0,
        }

    def busy(self, chat_id: str) -> bool:
        """Protect mutations during both admission and published
        execution."""
        with self._lock:
            return chat_id in self._admitting or (
                self._runs.get(chat_id, {}).get("status") == "running"
            )

    def running(self):
        """Snapshot only this process's active runs, without prompts or
        results."""
        with self._lock:
            return [
                {"chat_id": chat_id, **row}
                for chat_id, row in sorted(self._runs.items())
                if row["status"] == "running"
            ]

    def _update(self, chat_id, run_id, phase):
        with self._lock:
            row = self._runs.get(chat_id)
            if row is None or row["run_id"] != run_id:
                return
            row.update(
                phase=phase,
                message=PHASES[phase],
                status=phase if phase in {"completed", "failed"} else "running",
                updated_at=datetime.now(UTC).isoformat(),
                sequence=row["sequence"] + 1,
            )

    @contextmanager
    def track(self, chat_id: str, run_id: str | None = None, *, before_start=None):
        identifier = str(UUID(run_id)) if run_id is not None else str(uuid4())
        with self._lock:
            old = self._runs.get(chat_id)
            if chat_id in self._admitting or (
                old and (old["status"] == "running" or old["run_id"] == identifier)
            ):
                raise ResearchInProgress(
                    "This chat already has a running or completed submission. "
                    "Reload its saved history before submitting again."
                )
            # Bound memory without evicting an active run or storing user text.
            while (
                len(self._runs.keys() | self._admitting) >= 256
                and chat_id not in self._runs
            ):
                removable = next(
                    (
                        key
                        for key, row in self._runs.items()
                        if row["status"] != "running" and key not in self._admitting
                    ),
                    None,
                )
                if removable is None:
                    raise ResearchInProgress(
                        "Research is busy. Retry after a running request finishes."
                    )
                del self._runs[removable]
            # Reserve this chat and its capacity before releasing the lock.
            # Readiness may verify an account over the network; other chats must
            # remain readable and able to publish progress during that check.
            self._admitting.add(chat_id)
        try:
            # Snapshot the latest context and persist the accepted title before
            # publishing a run. Duplicates cannot enter this callback.
            if before_start is not None:
                before_start()
            with self._lock:
                now = datetime.now(UTC).isoformat()
                self._runs[chat_id] = {
                    "run_id": identifier,
                    "status": "running",
                    "phase": "preparing",
                    "message": PHASES["preparing"],
                    "started_at": now,
                    "updated_at": now,
                    "sequence": 1,
                }
        finally:
            with self._lock:
                self._admitting.discard(chat_id)
        token = _observer.set(lambda phase: self._update(chat_id, identifier, phase))
        try:
            yield
        except BaseException:
            self._update(chat_id, identifier, "failed")
            raise
        else:
            self._update(chat_id, identifier, "completed")
        finally:
            _observer.reset(token)
