"""Run the workspace's removed-item retention policy while the service
is open."""

import asyncio
import logging

from starlette.concurrency import run_in_threadpool

RETENTION_SWEEP_SECONDS = 60
_LOGGER = logging.getLogger(__name__)


async def sweep_removed_items(store):
    """A failed sweep preserves the service and is retried at the next
    interval."""
    try:
        await run_in_threadpool(store.purge_expired)
    except Exception as error:
        # Database exceptions can include local paths or values. Log only type.
        _LOGGER.warning(
            "Removed-item retention cleanup failed (%s); it will retry.",
            type(error).__name__,
        )


async def maintain_removed_items(store, stop: asyncio.Event):
    """Stop promptly while idle; finish any in-flight transaction before
    exit."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=RETENTION_SWEEP_SECONDS)
        except TimeoutError:
            if not stop.is_set():
                await sweep_removed_items(store)
