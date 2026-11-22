"""Running blocking PDF work for ``asyncio`` code.

``asyncio.shield`` is not used: when its waiter is cancelled, CPython 3.14.0 to 3.14.2 report
the job's error to the event loop as "exception in shielded future". ``asyncio.wait`` leaves
the work running just the same.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")

#: How long a cancelled call waits for its tab or browser to be closed.
_CLEANUP_SECONDS = 10.0


async def run_in_thread(work: Callable[[threading.Event], T]) -> T:
    """Run ``work`` in the event loop's thread pool, so the loop stays free.

    When the awaiting task is cancelled, a job still waiting for a thread is dropped. For
    a running one the event given to ``work`` is set, and the task waits for it to stop
    and clean up before the cancellation goes on.
    """
    stop, started = threading.Event(), threading.Event()

    def job() -> T:
        started.set()
        return work(stop)

    future = asyncio.get_running_loop().run_in_executor(None, job)
    try:
        await asyncio.wait({future})
    except asyncio.CancelledError:
        stop.set()
        if started.is_set():
            await _wait_for_cleanup(future)
        else:
            future.cancel()
        raise
    return future.result()


async def run_to_completion(work: Callable[[], T]) -> T:
    """Run ``work`` on a thread of its own, to the end even when the task is cancelled.

    For closing: the loop's pool can be full of the very jobs that closing has to stop.
    """
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lifeastroapi-close")
    future = asyncio.get_running_loop().run_in_executor(executor, work)
    executor.shutdown(wait=False)
    try:
        await asyncio.wait({future})
    except asyncio.CancelledError:
        await _wait_for_cleanup(future)
        raise
    return future.result()


async def _wait_for_cleanup(future: asyncio.Future[T]) -> None:
    # The task reports its cancellation, so the job's own error is read here and dropped.
    future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait({future}, timeout=_CLEANUP_SECONDS)
