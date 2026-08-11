"""Fair single-lane scheduler shared by every MCP model capability."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable

from bob_core.structured_logging import log_model


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class FairModelQueue:
    """Serialize model work and alternate users whenever both are waiting."""

    def __init__(self, on_change: Callable[[dict[str, Any]], None] | None = None):
        self._condition = threading.Condition(threading.RLock())
        self._queues: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self._active: dict[str, Any] | None = None
        self._last_user_id: str | None = None
        self._on_change = on_change

    @staticmethod
    def _public(job: dict[str, Any] | None, **extra: Any) -> dict[str, Any] | None:
        if not job:
            return None
        return {
            "job_id": job["job_id"],
            "user_id": job["user_id"],
            "workspace_id": job.get("workspace_id"),
            "request_id": job.get("request_id"),
            "tool": job["tool"],
            "queued_at": job["queued_at"],
            "started_at": job.get("started_at"),
            **extra,
        }

    def _pending_users(self) -> list[str]:
        return [user_id for user_id, jobs in self._queues.items() if jobs]

    def _next_user(self) -> str | None:
        users = self._pending_users()
        if not users:
            return None
        return next((user_id for user_id in users if user_id != self._last_user_id), users[0])

    def _scheduled(self) -> list[dict[str, Any]]:
        copies = OrderedDict((user_id, list(jobs)) for user_id, jobs in self._queues.items() if jobs)
        ordered: list[dict[str, Any]] = []
        last_user_id = self._active.get("user_id") if self._active else self._last_user_id
        while any(copies.values()):
            users = [user_id for user_id, jobs in copies.items() if jobs]
            user_id = next((candidate for candidate in users if candidate != last_user_id), users[0])
            ordered.append(copies[user_id].pop(0))
            last_user_id = user_id
        return ordered

    def snapshot(self, actor_user_id: str | None = None) -> dict[str, Any]:
        with self._condition:
            waiting = [self._public(job, position=index + 1) for index, job in enumerate(self._scheduled())]
            own_waiting = [job for job in waiting if not actor_user_id or job["user_id"] == actor_user_id]
            active = self._public(self._active, status="running")
            own_active = active if active and (not actor_user_id or active["user_id"] == actor_user_id) else None
            return {
                "lane_count": 1,
                "status": "running" if own_active else "queued" if own_waiting else "idle",
                "active": own_active,
                "model_busy": bool(active),
                "waiting": own_waiting,
                "queue_depth": len(waiting),
                "total_depth": len(waiting) + int(bool(active)),
            }

    def _changed(self) -> None:
        if self._on_change:
            self._on_change(self.snapshot())

    def run(
        self,
        *,
        actor_user_id: str | None,
        workspace_id: str | None,
        request_id: str | None,
        tool: str,
        operation: Callable[[], Any],
    ) -> Any:
        user_id = str(actor_user_id or "anonymous")
        job = {
            "job_id": f"model_job_{uuid.uuid4()}",
            "user_id": user_id,
            "workspace_id": workspace_id,
            "request_id": request_id,
            "tool": tool,
            "queued_at": _now(),
            "queued_monotonic": time.monotonic(),
        }
        with self._condition:
            self._queues.setdefault(user_id, []).append(job)
            log_model("model.queue.queued", **self._public(job), queue_depth=sum(map(len, self._queues.values())))
            self._changed()
            while True:
                next_user = self._next_user()
                if self._active is None and next_user == user_id and self._queues[user_id][0] is job:
                    self._queues[user_id].pop(0)
                    if not self._queues[user_id]:
                        del self._queues[user_id]
                    self._active = job
                    self._last_user_id = user_id
                    job["started_at"] = _now()
                    break
                self._condition.wait()
            wait_ms = round((time.monotonic() - job["queued_monotonic"]) * 1000)
            log_model("model.queue.started", **self._public(job), wait_ms=wait_ms)
            self._changed()
        try:
            result = operation()
            if isinstance(result, dict):
                result = {**result, "queue": {**self._public(job), "wait_ms": wait_ms, "lane_count": 1}}
            log_model("model.queue.completed", **self._public(job), wait_ms=wait_ms, outcome="success")
            return result
        except Exception as exc:
            log_model("model.queue.failed", **self._public(job), wait_ms=wait_ms, outcome="failed", error={"type": type(exc).__name__, "message": str(exc)})
            raise
        finally:
            with self._condition:
                self._active = None
                self._changed()
                self._condition.notify_all()

