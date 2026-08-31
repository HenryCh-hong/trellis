from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from app.tasks.base import TaskHandle, TaskQueue, new_task_id

logger = logging.getLogger(__name__)


class InProcessTaskQueue(TaskQueue):
    def __init__(self, max_workers: int = 4, history: int = 200) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="task")
        self._tasks: OrderedDict[str, TaskHandle] = OrderedDict()
        self._history = history
        self._lock = threading.Lock()

    def enqueue(self, name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> TaskHandle:
        handle = TaskHandle(id=new_task_id(), name=name)
        with self._lock:
            self._tasks[handle.id] = handle
            while len(self._tasks) > self._history:
                self._tasks.popitem(last=False)

        def run() -> None:
            handle.status = "running"
            handle.started_at = datetime.now(UTC)
            try:
                handle.result = fn(*args, **kwargs)
                handle.status = "succeeded"
            except Exception as exc:
                handle.status = "failed"
                handle.error = f"{type(exc).__name__}: {exc}"
                logger.exception("task %s (%s) failed", handle.id, name)
            finally:
                handle.finished_at = datetime.now(UTC)

        self._pool.submit(run)
        return handle

    def get(self, task_id: str) -> TaskHandle | None:
        return self._tasks.get(task_id)

    def list(self, limit: int = 50) -> list[TaskHandle]:
        return list(reversed(list(self._tasks.values())))[:limit]

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


_queue: InProcessTaskQueue | None = None


def get_queue() -> InProcessTaskQueue:
    global _queue
    if _queue is None:
        _queue = InProcessTaskQueue()
    return _queue
