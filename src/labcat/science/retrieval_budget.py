"""A shared deadline for repository discovery and same-chat record
refresh."""

import time
from contextlib import contextmanager
from contextvars import ContextVar

_deadline = ContextVar("labcat_repository_deadline", default=None)


def bounded_deadline(seconds):
    now = time.monotonic()
    shared = _deadline.get()
    deadline = min(now + seconds, shared) if shared is not None else now + seconds
    if deadline <= now:
        raise ValueError("The public repository time budget was exhausted.")
    return deadline


@contextmanager
def repository_budget(seconds=30):
    token = _deadline.set(bounded_deadline(seconds))
    try:
        yield
    finally:
        _deadline.reset(token)
